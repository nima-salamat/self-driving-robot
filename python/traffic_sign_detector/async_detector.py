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
        self._latest = None
        self._next_id = 0
        self._submitted = 0
        self._completed = 0
        self._failures = 0
        self._last_result_at = None
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
        with self._lock:
            self._next_id += 1
            request_id = self._next_id

        request = (request_id, frame, debug_frame)
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

    def latest(self):
        with self._lock:
            return self._latest

    def _run(self):
        logger = logging.getLogger(__name__)
        while not self._stop.is_set():
            try:
                request_id, frame, debug_frame = self._requests.get(timeout=0.1)
            except queue.Empty:
                continue

            started = time.monotonic()
            try:
                result = self.detector.process_frame(frame, debug_frame=debug_frame)
                with self._lock:
                    self._latest = (request_id, result)
                    self._completed += 1
                    self._last_result_at = time.monotonic()
                    self._last_latency_ms = (self._last_result_at - started) * 1000.0
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
                "last_result_age_s": last_result_age_s,
                "last_latency_ms": self._last_latency_ms,
                "last_error": self._last_error,
            }
    def close(self):
        self._stop.set()
        if self._worker.is_alive() and self._worker is not threading.current_thread():
            self._worker.join(timeout=1.0)
