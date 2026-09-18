import logging
import queue
import threading
import time


class AsyncSignDetector:
    """Single-worker latest-frame adapter for an existing sign detector."""

    def __init__(self, detector):
        self.detector = detector
        self._requests = queue.Queue(maxsize=1)
        self._lock = threading.Lock()
        self._latest = None  # (request_id, result, submitted_at, completed_at)
        self._next_id = 0
        self._submitted = 0
        self._completed = 0
        self._failures = 0
        self._last_result_at = None
        self._last_submit_at = None
        self._last_latency_ms = None
        self._last_error = None
        self._stop = threading.Event()
        self._worker = threading.Thread(
            target=self._run,
            name="sign-detector",
            daemon=True,
        )
        self._worker.start()

    def submit(self, frame, debug_frame=None):
        if frame is None:
            return None
        submitted_at = time.monotonic()
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            self._last_submit_at = submitted_at
        request = (request_id, frame, debug_frame, submitted_at)
        try:
            self._requests.put_nowait(request)
            with self._lock:
                self._submitted += 1
            return request_id
        except queue.Full:
            try:
                self._requests.get_nowait()
                self._requests.task_done()
            except queue.Empty:
                pass
            try:
                self._requests.put_nowait(request)
                with self._lock:
                    self._submitted += 1
                return request_id
            except queue.Full:
                return None

    def latest(self, max_age_s=None):
        with self._lock:
            latest = self._latest

        if latest is None or max_age_s is None:
            return latest

        max_age_s = max(0.0, float(max_age_s))
        input_age_s = max(0.0, time.monotonic() - latest[2])
        return latest if input_age_s <= max_age_s else None

    def _run(self):
        logger = logging.getLogger(__name__)
        while not self._stop.is_set():
            try:
                request_id, frame, debug_frame, submitted_at = self._requests.get(timeout=0.1)
            except queue.Empty:
                continue

            started = time.monotonic()
            try:
                result = self.detector.process_frame(frame, debug_frame=debug_frame)
                completed_at = time.monotonic()
                with self._lock:
                    self._latest = (
                        request_id,
                        result,
                        submitted_at,
                        completed_at,
                    )
                    self._completed += 1
                    self._last_result_at = completed_at
                    self._last_latency_ms = (completed_at - started) * 1000.0
                    self._last_error = None
            except Exception as exc:
                with self._lock:
                    self._failures += 1
                    self._last_error = f"{type(exc).__name__}: {exc}"
                logger.exception("Asynchronous sign detection failed")
            finally:
                self._requests.task_done()

    def status(self):
        with self._lock:
            last_result_age_s = (
                max(0.0, time.monotonic() - self._last_result_at)
                if self._last_result_at is not None
                else None
            )
            return {
                "worker_alive": self._worker.is_alive(),
                "queue_depth": self._requests.qsize(),
                "submitted": self._submitted,
                "completed": self._completed,
                "failures": self._failures,
                "last_result_request_id": (
                    self._latest[0] if self._latest is not None else None
                ),
                "last_result_age_s": last_result_age_s,
                "last_result_input_age_s": (
                    max(0.0, time.monotonic() - self._latest[2])
                    if self._latest is not None
                    else None
                ),
                "last_submit_age_s": (
                    max(0.0, time.monotonic() - self._last_submit_at)
                    if self._last_submit_at is not None
                    else None
                ),
                "inference_in_flight": self._completed < self._submitted,
                "last_latency_ms": self._last_latency_ms,
                "last_error": self._last_error,
            }
    def close(self):
        self._stop.set()
        if self._worker.is_alive() and self._worker is not threading.current_thread():
            self._worker.join(timeout=1.0)
