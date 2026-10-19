"""Process-isolated sign inference with a single replaceable latest-frame slot."""
from __future__ import annotations

import logging
import math
import multiprocessing as mp
import queue
import signal
import threading
import time
from multiprocessing.shared_memory import SharedMemory

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


def _make_detector(method, detector_factory=None, intra_op_num_threads=2):
    if detector_factory is not None:
        return detector_factory()
    if str(method).lower() == "svm":
        from traffic_sign_detector.svm_detector import TrafficSignDetector
        return TrafficSignDetector()
    from traffic_sign_detector.yolo_detector import TrafficSignDetector
    return TrafficSignDetector(intra_op_num_threads=intra_op_num_threads)


def _sign_worker(method, detector_factory, intra_op_num_threads, requests, results,
                 ready, ready_payload, stop_event, paused_event, requests_enabled,
                 idle_event, active_event, shared_memory_name, frame_lock,
                 frame_sequence, generation):
    """Infer from a shared-memory latest-frame slot; queues carry metadata only."""
    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    except (AttributeError, ValueError):
        pass

    shared_frame = None
    try:
        shared_frame = SharedMemory(name=shared_memory_name)
        try:
            import cv2
            cv2.setNumThreads(1)
        except Exception:
            logger.debug("Could not bound OpenCV threads in sign worker", exc_info=True)
        detector = _make_detector(method, detector_factory, intra_op_num_threads)
        ready_payload.put((True, None), timeout=2.0)
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        logger.exception("Process sign detector failed to initialize")
        if shared_frame is not None:
            try:
                shared_frame.close()
            except Exception:
                logger.debug("Could not close sign shared memory after startup failure", exc_info=True)
        try:
            ready_payload.put((False, detail), timeout=1.0)
        except Exception:
            pass
        ready.set()
        return
    ready.set()

    try:
        while not stop_event.is_set():
            try:
                (
                    request_id, request_generation, frame_shape, submitted_at,
                    frame_captured_at, confidence_threshold, target_sign_types,
                ) = requests.get(timeout=0.1)
            except queue.Empty:
                continue

            # Serialize in-flight/idle transitions with producer queue updates.
            # In particular, mark work active before checking pause state so a
            # phase gate cannot observe "idle" and release while inference is
            # about to start.
            with frame_lock:
                active_event.set()
                idle_event.clear()
                if (
                    int(request_generation) != int(generation.value)
                    or paused_event.is_set()
                    or not requests_enabled.is_set()
                    or stop_event.is_set()
                ):
                    active_event.clear()
                    try:
                        queued = not requests.empty()
                    except (NotImplementedError, OSError):
                        queued = False
                    if queued:
                        idle_event.clear()
                    else:
                        idle_event.set()
                    continue

                # A newer frame may have replaced this slot after the descriptor
                # was queued. Do not pair stale metadata with the new pixels.
                if int(frame_sequence.value) != int(request_id):
                    frame = None
                else:
                    frame = np.ndarray(
                        tuple(frame_shape), dtype=np.uint8, buffer=shared_frame.buf
                    ).copy()

                if frame is None:
                    active_event.clear()
                    try:
                        queued = not requests.empty()
                    except (NotImplementedError, OSError):
                        queued = False
                    if queued:
                        idle_event.clear()
                    else:
                        idle_event.set()
                    continue

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

                # Keep large image/mask results out of the control-process IPC.
                result = dict(result)
                result.pop("binary_mask", None)
                result.pop("debug_frame", None)
                completed_at = time.monotonic()
                _replace_queue_item(
                    results,
                    (
                        "ok", request_id, result, submitted_at, completed_at,
                        (completed_at - started) * 1000.0, None, frame_captured_at,
                    ),
                )
            except Exception as exc:
                completed_at = time.monotonic()
                detail = f"{type(exc).__name__}: {exc}"
                logger.exception("Process sign inference failed")
                _replace_queue_item(
                    results,
                    (
                        "error", request_id, None, submitted_at, completed_at,
                        (completed_at - started) * 1000.0, detail, frame_captured_at,
                    ),
                )
            finally:
                # The producer uses this same lock while changing the shared
                # sequence and queue. This avoids setting idle after a concurrent
                # submit has already cleared it.
                with frame_lock:
                    active_event.clear()
                    try:
                        queued = not requests.empty()
                    except (NotImplementedError, OSError):
                        queued = False
                    if queued:
                        idle_event.clear()
                    else:
                        idle_event.set()
    finally:
        try:
            shared_frame.close()
        except Exception:
            logger.debug("Could not close sign shared memory in worker", exc_info=True)


class ProcessSignDetector:
    """API-compatible sign detector worker using spawn and latest-frame replacement.

    Frames are never accumulated: at most one request waits while one inference
    is running. New submissions replace that waiting request, so the worker picks
    up the newest available frame when its current inference finishes.
    """

    multiprocess = True
    STARTUP_TIMEOUT_S = 45.0

    def __init__(
        self, method="yolo", *, detector_factory=None, intra_op_num_threads=2,
        max_frame_bytes=4 * 1024 * 1024,
    ):
        self.method = str(method).lower()
        self.intra_op_num_threads = int(intra_op_num_threads)
        if self.intra_op_num_threads < 1:
            raise ValueError("intra_op_num_threads must be a positive integer")
        self._max_frame_bytes = int(max_frame_bytes)
        if self._max_frame_bytes < 1:
            raise ValueError("max_frame_bytes must be a positive integer")
        self._context = mp.get_context("spawn")
        self._shared_frame = SharedMemory(create=True, size=self._max_frame_bytes)
        self._frame_lock = self._context.Lock()
        self._frame_sequence = self._context.Value("q", 0, lock=False)
        # Invalidates descriptors dequeued just before pause, even if the
        # detector is resumed before that worker reaches its pause check.
        self._generation = self._context.Value("q", 0, lock=False)
        self._submit_lock = threading.Lock()
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
                self.method, detector_factory, self.intra_op_num_threads,
                self._requests, self._results,
                self._ready, self._ready_payload, self._stop, self._paused,
                self._requests_enabled, self._idle, self._active,
                self._shared_frame.name, self._frame_lock, self._frame_sequence,
                self._generation,
            ),
            daemon=True,
        )
        try:
            self._worker.start()
        except Exception:
            self.close()
            raise
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
        logger.info(
            "Using multiprocessing traffic-sign inference "
            "(method=%s, intra_op_threads=%s, shared-memory frame slot)",
            self.method, self.intra_op_num_threads,
        )

    def submit(self, frame, debug_frame=None, confidence_threshold=None,
               target_sign_types=None, frame_captured_at=None):
        if frame is None or self._closed:
            return None
        if self._paused.is_set() or not self._requests_enabled.is_set() or self._stop.is_set():
            return None

        source = np.asarray(frame)
        if source.dtype != np.uint8 or source.ndim != 3 or source.shape[2] != 3:
            detail = "sign frame must be a uint8 HxWx3 array"
            with self._lock:
                self._dropped += 1
                self._last_error = detail
            return None
        if source.size == 0 or source.nbytes > self._max_frame_bytes:
            detail = (
                f"sign frame needs {source.nbytes} bytes, shared slot capacity is "
                f"{self._max_frame_bytes}"
            )
            with self._lock:
                self._dropped += 1
                should_log = self._last_error != detail
                self._last_error = detail
            if should_log:
                logger.error("%s", detail)
            return None

        with self._submit_lock:
            if self._closed or self._paused.is_set() or not self._requests_enabled.is_set() or self._stop.is_set():
                return None

            submitted_at = time.monotonic()
            try:
                frame_captured_at = float(frame_captured_at)
                if not math.isfinite(frame_captured_at) or frame_captured_at <= 0:
                    frame_captured_at = submitted_at
            except (TypeError, ValueError):
                frame_captured_at = submitted_at

            with self._lock:
                self._next_id += 1
                request_id = self._next_id
                self._last_submit_at = submitted_at

            # Serialize shared-slot publication, queue replacement and the idle
            # flag under one short lock. The detector copies pixels under this
            # lock, but inference itself always runs outside it.
            with self._frame_lock:
                if self._paused.is_set() or not self._requests_enabled.is_set() or self._stop.is_set():
                    return None
                request = (
                    request_id,
                    int(self._generation.value),
                    tuple(int(dim) for dim in source.shape),
                    submitted_at,
                    frame_captured_at,
                    confidence_threshold,
                    tuple(target_sign_types) if target_sign_types is not None else None,
                )
                self._idle.clear()
                slot = np.ndarray(
                    source.shape, dtype=np.uint8, buffer=self._shared_frame.buf
                )
                np.copyto(slot, source)
                self._frame_sequence.value = request_id

                try:
                    replacing_waiting_frame = self._requests.full()
                except (NotImplementedError, OSError):
                    replacing_waiting_frame = False

                if not _replace_queue_item(self._requests, request):
                    with self._lock:
                        self._dropped += 1
                    try:
                        queued = not self._requests.empty()
                    except (NotImplementedError, OSError):
                        queued = False
                    if self._active.is_set() or queued:
                        self._idle.clear()
                    else:
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
        (
            kind, request_id, result, submitted_at, completed_at,
            latency_ms, error, frame_captured_at,
        ) = newest
        with self._lock:
            if kind == "error":
                self._failures += 1
                self._last_error = error
                self._last_latency_ms = latency_ms
                return
            self._latest = (
                request_id, result, submitted_at, completed_at, frame_captured_at
            )
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
        frame_captured_at = latest[4] if len(latest) >= 5 else latest[2]
        input_age_s = max(0.0, time.monotonic() - frame_captured_at)
        return latest if input_age_s < max_age_s else None

    def pause(self):
        with self._frame_lock:
            self._generation.value += 1
            self._paused.set()
            self._discard_waiting_requests_locked()
            if not self._active.is_set():
                self._idle.set()

    def resume(self):
        with self._frame_lock:
            if not self._stop.is_set():
                self._paused.clear()

    def pause_requests(self):
        with self._frame_lock:
            self._generation.value += 1
            self._requests_enabled.clear()
            self._discard_waiting_requests_locked()
            if not self._active.is_set():
                self._idle.set()

    def resume_requests(self):
        with self._frame_lock:
            if not self._stop.is_set():
                self._requests_enabled.set()

    def _discard_waiting_requests(self):
        with self._frame_lock:
            self._discard_waiting_requests_locked()
            if not self._active.is_set():
                self._idle.set()

    def _discard_waiting_requests_locked(self):
        while True:
            try:
                self._requests.get_nowait()
            except queue.Empty:
                break

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
            "frame_transport": "shared_memory",
            "shared_memory_frame_bytes": self._max_frame_bytes,
            "intra_op_num_threads": self.intra_op_num_threads,
            "paused": self._paused.is_set(),
            "requests_enabled": self._requests_enabled.is_set(),
            "queue_depth": queue_depth,
            **counts,
            "last_result_request_id": latest[0] if latest is not None else None,
            "last_result_age_s": (
                max(0.0, now - last_result_at) if last_result_at is not None else None
            ),
            "last_result_input_age_s": (
                max(
                    0.0,
                    now - (latest[4] if len(latest) >= 5 else latest[2]),
                ) if latest is not None else None
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

        shared_frame = getattr(self, "_shared_frame", None)
        if shared_frame is not None:
            try:
                shared_frame.close()
            except Exception:
                logger.debug("Could not close parent sign shared memory", exc_info=True)
            try:
                shared_frame.unlink()
            except FileNotFoundError:
                pass
            except Exception:
                logger.exception("Could not unlink parent sign shared memory")
