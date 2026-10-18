"""Process-isolated sign inference with a single replaceable latest-frame slot."""
from __future__ import annotations

import logging
import multiprocessing as mp
import queue
import signal
import threading
import time

import numpy as np

logger = logging.getLogger(__name__)


def _replace_queue_item(target, item):
    """Keep the newest item in a bounded multiprocessing queue."""
    try:
        target.put_nowait(item)
        return True
    except queue.Full:
        # Multiprocessing.Queue has a feeder thread. The semaphore can report
        # Full just before the feeder has made the previous item readable.
        # Retry briefly rather than silently losing the newest camera frame.
        for _ in range(3):
            try:
                target.get(timeout=0.001)
                break
            except queue.Empty:
                continue
        else:
            return False
        try:
            target.put_nowait(item)
            return True
        except queue.Full:
            return False


def _make_detector(method, detector_factory=None):
    if detector_factory is not None:
        return detector_factory()
    if str(method).lower() == "svm":
        from traffic_sign_detector.svm_detector import TrafficSignDetector
    else:
        from traffic_sign_detector.yolo_detector import TrafficSignDetector
    return TrafficSignDetector()


def _sign_worker(method, detector_factory, requests, results, ready, ready_payload,
                 stop_event, paused_event, requests_enabled, idle_event,
                 active_event):
    """Load the model once in the child and process only the newest queued frame."""
    # Ctrl+C should be handled by the owning runtime. A child receiving SIGINT
    # during OpenCV/ONNX work otherwise emits a misleading KeyboardInterrupt.
    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    except (AttributeError, ValueError):
        pass

    try:
        detector = _make_detector(method, detector_factory)
        ready_payload.put((True, None), timeout=2.0)
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        logger.exception("Process sign detector failed to initialize")
        try:
            ready_payload.put((False, detail), timeout=1.0)
        except Exception:
            pass
        ready.set()
        return
    ready.set()

    while not stop_event.is_set():
        try:
            request_id, frame, submitted_at, confidence_threshold, target_sign_types = (
                requests.get(timeout=0.1)
            )
        except queue.Empty:
            continue

        if paused_event.is_set() or not requests_enabled.is_set() or stop_event.is_set():
            if not active_event.is_set() and requests.empty():
                idle_event.set()
            continue

        active_event.set()
        idle_event.clear()
        started = time.monotonic()
        try:
            if str(method).lower() == "svm":
                result = detector.process_frame(frame, debug_frame=None)
            else:
                options = {}
                if confidence_threshold is not None:
                    options["confidence_threshold"] = confidence_threshold
                if target_sign_types is not None:
                    options["target_sign_types"] = target_sign_types
                result = detector.process_frame(frame, debug_frame=None, **options)

            if not isinstance(result, dict):
                raise TypeError("sign detector must return a dictionary")

            # These arrays are not used by the control decision. In particular,
            # never send an unchanged full debug frame or binary mask through IPC.
            result = dict(result)
            result.pop("binary_mask", None)
            result.pop("debug_frame", None)
            completed_at = time.monotonic()
            payload = (
                "ok", request_id, result, submitted_at, completed_at,
                (completed_at - started) * 1000.0, None,
            )
            _replace_queue_item(results, payload)
        except Exception as exc:
            completed_at = time.monotonic()
            detail = f"{type(exc).__name__}: {exc}"
            logger.exception("Process sign inference failed")
            _replace_queue_item(
                results,
                ("error", request_id, None, submitted_at, completed_at,
                 (completed_at - started) * 1000.0, detail),
            )
        finally:
            active_event.clear()
            try:
                queued = not requests.empty()
            except (NotImplementedError, OSError):
                queued = False
            if not queued:
                idle_event.set()


class ProcessSignDetector:
    """API-compatible sign detector worker using spawn and latest-frame replacement.

    Frames are never accumulated: at most one request waits while one inference
    is running. New submissions replace that waiting request, so the worker picks
    up the newest available frame when its current inference finishes.
    """

    multiprocess = True
    STARTUP_TIMEOUT_S = 45.0

    def __init__(self, method="yolo", *, detector_factory=None):
        self.method = str(method).lower()
        self._context = mp.get_context("spawn")
        self._requests = self._context.Queue(maxsize=1)
        self._results = self._context.Queue(maxsize=1)
        self._ready_payload = self._context.Queue(maxsize=1)
        self._ready = self._context.Event()
        self._stop = self._context.Event()
        self._paused = self._context.Event()
        self._requests_enabled = self._context.Event()
        self._requests_enabled.set()
        self._idle = self._context.Event()
        self._idle.set()
        self._active = self._context.Event()
        self._lock = threading.Lock()
        self._next_id = 0
        self._submitted = 0
        self._completed = 0
        self._failures = 0
        self._replaced = 0
        self._dropped = 0
        self._latest = None
        self._last_result_at = None
        self._last_submit_at = None
        self._last_latency_ms = None
        self._last_error = None
        self._closed = False

        self._worker = self._context.Process(
            target=_sign_worker,
            name="robot-sign-detector",
            args=(
                self.method, detector_factory, self._requests, self._results,
                self._ready, self._ready_payload, self._stop, self._paused,
                self._requests_enabled, self._idle, self._active,
            ),
            daemon=True,
        )
        self._worker.start()
        if not self._ready.wait(self.STARTUP_TIMEOUT_S):
            self.close()
            raise RuntimeError(
                f"Sign detector process did not initialize within "
                f"{self.STARTUP_TIMEOUT_S:.0f} seconds"
            )
        try:
            success, detail = self._ready_payload.get(timeout=1.0)
        except queue.Empty:
            self.close()
            raise RuntimeError("Sign detector process exited during initialization")
        if not success:
            self.close()
            raise RuntimeError(f"Sign detector process initialization failed: {detail}")

    def submit(self, frame, debug_frame=None, confidence_threshold=None,
               target_sign_types=None):
        if frame is None or self._closed:
            return None
        if self._paused.is_set() or not self._requests_enabled.is_set() or self._stop.is_set():
            return None

        submitted_at = time.monotonic()
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            self._last_submit_at = submitted_at
        # Do not transfer debug_frame through the process queue. Control results
        # only need the ROI crop and metadata; the caller keeps its own full frame.
        request = (
            request_id,
            np.array(frame, copy=True, order="C"),
            submitted_at,
            confidence_threshold,
            tuple(target_sign_types) if target_sign_types is not None else None,
        )
        try:
            replacing_waiting_frame = self._requests.full()
        except (NotImplementedError, OSError):
            replacing_waiting_frame = False
        self._idle.clear()
        if not _replace_queue_item(self._requests, request):
            with self._lock:
                self._dropped += 1
            if not self._active.is_set():
                self._idle.set()
            return None

        with self._lock:
            self._submitted += 1
            if replacing_waiting_frame:
                self._replaced += 1
        return request_id

    def _collect_results(self):
        newest = None
        while True:
            try:
                item = self._results.get_nowait()
            except queue.Empty:
                break
            newest = item

        if newest is None:
            return
        kind, request_id, result, submitted_at, completed_at, latency_ms, error = newest
        with self._lock:
            if kind == "error":
                self._failures += 1
                self._last_error = error
                self._last_latency_ms = latency_ms
                return
            self._latest = (request_id, result, submitted_at, completed_at)
            self._completed += 1
            self._last_result_at = completed_at
            self._last_latency_ms = latency_ms
            self._last_error = None

    def latest(self, max_age_s=None):
        self._collect_results()
        with self._lock:
            latest = self._latest
        if latest is None or max_age_s is None:
            return latest
        max_age_s = max(0.0, float(max_age_s))
        input_age_s = max(0.0, time.monotonic() - latest[2])
        return latest if input_age_s < max_age_s else None

    def pause(self):
        self._paused.set()
        self._discard_waiting_requests()

    def resume(self):
        if not self._stop.is_set():
            self._paused.clear()

    def pause_requests(self):
        self._requests_enabled.clear()
        self._discard_waiting_requests()

    def resume_requests(self):
        if not self._stop.is_set():
            self._requests_enabled.set()

    def _discard_waiting_requests(self):
        while True:
            try:
                self._requests.get_nowait()
            except queue.Empty:
                break
        if not self._active.is_set():
            self._idle.set()

    def wait_until_idle(self, timeout=None):
        return self._idle.wait(timeout)

    def status(self):
        self._collect_results()
        now = time.monotonic()
        with self._lock:
            latest = self._latest
            last_result_at = self._last_result_at
            last_submit_at = self._last_submit_at
            counts = {
                "submitted": self._submitted,
                "completed": self._completed,
                "failures": self._failures,
                "replaced": self._replaced,
                "dropped": self._dropped,
                "last_latency_ms": self._last_latency_ms,
                "last_error": self._last_error,
            }
        try:
            queue_depth = self._requests.qsize()
        except (NotImplementedError, OSError):
            queue_depth = int(not self._idle.is_set())
        return {
            "worker_alive": self._worker.is_alive(),
            "paused": self._paused.is_set(),
            "requests_enabled": self._requests_enabled.is_set(),
            "queue_depth": queue_depth,
            **counts,
            "last_result_request_id": latest[0] if latest is not None else None,
            "last_result_age_s": (
                max(0.0, now - last_result_at) if last_result_at is not None else None
            ),
            "last_result_input_age_s": (
                max(0.0, now - latest[2]) if latest is not None else None
            ),
            "last_submit_age_s": (
                max(0.0, now - last_submit_at) if last_submit_at is not None else None
            ),
            "inference_in_flight": self._active.is_set() or queue_depth > 0,
        }

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._stop.set()
        self._paused.clear()
        self._requests_enabled.clear()
        self._idle.set()
        worker = getattr(self, "_worker", None)
        if worker is not None:
            try:
                if worker.is_alive():
                    worker.join(timeout=3.0)
                if worker.is_alive():
                    worker.terminate()
                    worker.join(timeout=1.0)
            except Exception:
                logger.exception("Failed to stop process sign detector")
        for channel in (
            getattr(self, "_requests", None),
            getattr(self, "_results", None),
            getattr(self, "_ready_payload", None),
        ):
            if channel is not None:
                try:
                    channel.cancel_join_thread()
                    channel.close()
                except Exception:
                    pass
