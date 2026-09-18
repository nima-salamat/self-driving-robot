import queue
import threading


class AsyncSignDetector:
    """Single-worker latest-frame adapter for an existing sign detector."""

    def __init__(self, detector):
        self.detector = detector
        self._requests = queue.Queue(maxsize=1)
        self._lock = threading.Lock()
        self._latest = None
        self._stop = threading.Event()
        self._worker = threading.Thread(
            target=self._run,
            name="sign-detector",
            daemon=True,
        )
        self._worker.start()

    def submit(self, frame, debug_frame=None):
        if frame is None:
            return False
        request = (frame, debug_frame)
        try:
            self._requests.put_nowait(request)
            return True
        except queue.Full:
            try:
                self._requests.get_nowait()
            except queue.Empty:
                pass
            try:
                self._requests.put_nowait(request)
                return True
            except queue.Full:
                return False

    def latest(self):
        with self._lock:
            return self._latest

    def _run(self):
        while not self._stop.is_set():
            try:
                frame, debug_frame = self._requests.get(timeout=0.1)
            except queue.Empty:
                continue

            try:
                result = self.detector.process_frame(frame, debug_frame=debug_frame)
                with self._lock:
                    self._latest = result
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Asynchronous sign detection failed")

    def close(self):
        self._stop.set()
        if self._worker.is_alive() and self._worker is not threading.current_thread():
            self._worker.join(timeout=1.0)
