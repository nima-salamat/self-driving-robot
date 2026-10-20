import queue
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

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
    def test_yolo_detector_uses_explicit_onnx_thread_budget(self):
        from traffic_sign_detector import yolo_detector

        fake_session = SimpleNamespace(
            get_inputs=lambda: [
                SimpleNamespace(name="images", shape=[1, 3, 640, 640])
            ]
        )
        with patch.object(
            yolo_detector.ort, "InferenceSession", return_value=fake_session
        ) as create_session, patch.object(yolo_detector.os, "makedirs"):
            yolo_detector.TrafficSignDetector(
                model_path="fake.onnx", intra_op_num_threads=2
            )

        kwargs = create_session.call_args.kwargs
        self.assertEqual(kwargs["providers"], ["CPUExecutionProvider"])
        self.assertEqual(kwargs["sess_options"].intra_op_num_threads, 2)
        self.assertEqual(kwargs["sess_options"].inter_op_num_threads, 1)

    def test_yolo_detector_rejects_invalid_thread_budget(self):
        from traffic_sign_detector.yolo_detector import TrafficSignDetector

        for threads in (0, -1):
            with self.subTest(threads=threads), self.assertRaises(ValueError):
                TrafficSignDetector(
                    model_path="fake.onnx", intra_op_num_threads=threads
                )

    def test_replace_queue_item_keeps_latest_waiting_request(self):
        requests = queue.Queue(maxsize=1)
        self.assertTrue(_replace_queue_item(requests, "old"))
        self.assertTrue(_replace_queue_item(requests, "new"))
        self.assertEqual(requests.get_nowait(), "new")

    def test_worker_processes_newest_pending_frame_and_closes(self):
        detector = ProcessSignDetector("yolo", detector_factory=_FakeSignDetector)
        latest_request_id = None
        try:
            final_frame_captured_at = time.monotonic() - 0.1
            for value in range(7):
                # Intermediate frames are replaceable under bounded
                # latest-frame backpressure; a rejected frame is counted.
                detector.submit(
                    np.full((8 + value, 10, 3), value, dtype=np.uint8),
                    frame_captured_at=time.monotonic(),
                )

            latest_request_id = None
            submit_deadline = time.monotonic() + 1.0
            final_frame = np.full((15, 10, 3), 7, dtype=np.uint8)
            while latest_request_id is None and time.monotonic() < submit_deadline:
                latest_request_id = detector.submit(
                    final_frame,
                    frame_captured_at=final_frame_captured_at,
                )
                if latest_request_id is None:
                    time.sleep(0.005)
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
            self.assertEqual(result[4], final_frame_captured_at)
            # Age limits are evaluated from the source frame, not when the
            # request was enqueued or when inference started.
            self.assertIsNone(detector.latest(max_age_s=0.01))
            self.assertNotIn("binary_mask", result[1])
            self.assertNotIn("debug_frame", result[1])
            status = detector.status()
            self.assertGreaterEqual(status["submitted"], 1)
            self.assertEqual(status["queue_depth"], 0)
            self.assertEqual(status["frame_transport"], "shared_memory")
            self.assertGreaterEqual(status["shared_memory_frame_bytes"], 15 * 10 * 3)
        finally:
            detector.close()

        self.assertFalse(detector._worker.is_alive())


    def test_pause_and_idle_state_are_consistent_during_frame_handoff(self):
        detector = ProcessSignDetector("yolo", detector_factory=_FakeSignDetector)
        try:
            submitted = detector.submit(
                np.full((24, 32, 3), 3, dtype=np.uint8),
                frame_captured_at=time.monotonic(),
            )
            self.assertIsNotNone(submitted)

            # This can catch the worker before it dequeues, between dequeue and
            # frame snapshot, or while inference is already running. In every
            # case pause must prevent new inference and idle must settle truthfully.
            detector.pause()
            self.assertTrue(detector.wait_until_idle(timeout=3.0))
            status = detector.status()
            self.assertFalse(status["inference_in_flight"])
            self.assertEqual(status["queue_depth"], 0)

            detector.resume()
            fresh = detector.submit(
                np.full((24, 32, 3), 9, dtype=np.uint8),
                frame_captured_at=time.monotonic(),
            )
            self.assertIsNotNone(fresh)
            deadline = time.monotonic() + 3.0
            result = None
            while time.monotonic() < deadline:
                result = detector.latest()
                if result is not None and result[0] == fresh:
                    break
                time.sleep(0.01)
            self.assertIsNotNone(result)
            self.assertEqual(result[0], fresh)
            self.assertEqual(result[1]["text"], "9")
        finally:
            detector.close()

if __name__ == "__main__":
    unittest.main()
