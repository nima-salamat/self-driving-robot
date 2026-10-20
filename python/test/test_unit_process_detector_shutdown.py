"""Regression tests for shutdown races in the process sign detector."""
import queue
import sys
import threading
import unittest
from pathlib import Path

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from traffic_sign_detector.process_detector import ProcessSignDetector


class _CloseDuringReadQueue:
    def __init__(self, detector):
        self.detector = detector

    def get_nowait(self):
        # Mimic close() being called after _collect_results checked _closed
        # but before multiprocessing.Queue.get_nowait() reads the queue.
        self.detector._closed = True
        raise ValueError("Queue is closed")


class _EmptyQueue:
    def get_nowait(self):
        raise queue.Empty


class _CloseDuringQsizeQueue:
    def __init__(self, detector):
        self.detector = detector

    def qsize(self):
        # Mimic Queue.close() racing with status() after its first closed check.
        self.detector._closed = True
        raise ValueError("Queue is closed")


class _Worker:
    def is_alive(self):
        return False


class ProcessSignDetectorShutdownTests(unittest.TestCase):
    def test_collect_results_tolerates_queue_closed_during_health_poll(self):
        detector = ProcessSignDetector.__new__(ProcessSignDetector)
        detector._closed = False
        detector._results = _CloseDuringReadQueue(detector)

        # Must treat this as normal shutdown, not leak ValueError into /api/health.
        detector._collect_results()

    def test_status_tolerates_request_queue_closed_during_qsize(self):
        detector = ProcessSignDetector.__new__(ProcessSignDetector)
        detector._closed = False
        detector._results = _EmptyQueue()
        detector._requests = _CloseDuringQsizeQueue(detector)
        detector._lock = threading.Lock()
        detector._worker = _Worker()
        detector._max_frame_bytes = 1024
        detector.intra_op_num_threads = 1
        detector._paused = threading.Event()
        detector._requests_enabled = threading.Event()
        detector._idle = threading.Event()
        detector._idle.set()
        detector._active = threading.Event()
        detector._latest = None
        detector._last_result_at = None
        detector._last_submit_at = None
        detector._submitted = 0
        detector._completed = 0
        detector._failures = 0
        detector._replaced = 0
        detector._dropped = 0
        detector._last_latency_ms = None
        detector._last_error = None

        status = detector.status()

        self.assertFalse(status["worker_alive"])
        self.assertEqual(status["queue_depth"], 0)
        self.assertFalse(status["inference_in_flight"])


if __name__ == "__main__":
    unittest.main()
