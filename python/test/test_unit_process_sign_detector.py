import queue
import time
import unittest

import numpy as np

from traffic_sign_detector.process_detector import ProcessSignDetector, _replace_queue_item


class _FakeSignDetector:
    def process_frame(self, original_image, debug_frame=None, **kwargs):
        # A short predictable workload exercises process handoff and replacement.
        time.sleep(0.04)
        return {
            "coordinate": None,
            "text": str(int(original_image[0, 0, 0])),
            "confidence": 0.9,
            "binary_mask": np.zeros(original_image.shape[:2], dtype=np.uint8),
            "debug_frame": debug_frame,
        }


class ProcessSignDetectorTests(unittest.TestCase):
    def test_replace_queue_item_keeps_latest_waiting_request(self):
        requests = queue.Queue(maxsize=1)
        self.assertTrue(_replace_queue_item(requests, "old"))
        self.assertTrue(_replace_queue_item(requests, "new"))
        self.assertEqual(requests.get_nowait(), "new")

    def test_worker_processes_newest_pending_frame_and_closes(self):
        detector = ProcessSignDetector("yolo", detector_factory=_FakeSignDetector)
        latest_request_id = None
        try:
            for value in range(8):
                latest_request_id = detector.submit(
                    np.full((8, 10, 3), value, dtype=np.uint8)
                )
                self.assertIsNotNone(latest_request_id)

            deadline = time.monotonic() + 8.0
            result = None
            while time.monotonic() < deadline:
                result = detector.latest()
                if result is not None and result[0] == latest_request_id:
                    break
                time.sleep(0.02)

            self.assertIsNotNone(result)
            self.assertEqual(result[0], latest_request_id)
            self.assertEqual(result[1]["text"], "7")
            self.assertNotIn("binary_mask", result[1])
            self.assertNotIn("debug_frame", result[1])
            status = detector.status()
            self.assertGreaterEqual(status["submitted"], 1)
            self.assertEqual(status["queue_depth"], 0)
        finally:
            detector.close()

        self.assertFalse(detector._worker.is_alive())


if __name__ == "__main__":
    unittest.main()
