import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from vision.lane_recovery_detection import detect_recovery_lines
from vision.lane_boundary_tracking import LaneBoundaryTracker


class LaneRecoveryDetectionTests(unittest.TestCase):
    @staticmethod
    def _vertical_line(roi, x):
        left, top, _right, bottom = roi
        local_x = float(x - left)
        return np.asarray([[[local_x, 0.0, local_x, float(bottom - top)]]],
                          dtype=np.float32)

    def test_recovery_uses_sobel_hough_inside_the_requested_crop(self):
        frame = np.zeros((180, 320, 3), dtype=np.uint8)
        cv2.line(frame, (118, 20), (118, 170), (255, 255, 255), 4)
        config = SimpleNamespace(
            LANE_THRESHOLD=80, HOUGH_THRESHOLD=10,
            HOUGH_MIN_LINE_LENGTH=12, HOUGH_MAX_LINE_GAP=8,
            HOUGH_BLUR_KERNEL=3, HOUGH_MORPH_CLOSE=True,
        )
        edges, lines = detect_recovery_lines(frame, (70, 10, 170, 175), config)

        self.assertEqual(edges.shape, (165, 100))
        self.assertIsNotNone(lines)
        self.assertTrue(any(
            abs(float(np.asarray(line).reshape(-1)[0]) - 48.0) < 8.0
            for line in lines
        ))

    def test_recovery_crop_is_clipped_and_empty_rois_are_ignored(self):
        frame = np.zeros((32, 48, 3), dtype=np.uint8)
        edges, lines = detect_recovery_lines(
            frame, (-20, -10, 90, 60), SimpleNamespace(LANE_THRESHOLD=180)
        )
        self.assertEqual(edges.shape, (32, 48))
        self.assertIsNone(lines)
        self.assertEqual(
            detect_recovery_lines(frame, (10, 10, 10, 20), SimpleNamespace()),
            (None, None),
        )

    def test_predicted_recovery_roi_detects_boundary_inside_the_configured_roi_gap(self):
        frame_shape = (480, 640, 3)
        left_roi = (90, 300, 228, 440)
        right_roi = (432, 300, 570, 440)
        tracker = LaneBoundaryTracker()
        tracker.update(
            self._vertical_line(left_roi, 235),
            self._vertical_line(right_roi, 465),
            frame_shape, left_roi, right_roi, reference_center_x=350.0,
        )
        tracker.update(
            None, self._vertical_line(right_roi, 465),
            frame_shape, left_roi, right_roi, reference_center_x=350.0,
        )
        search = tracker.recovery_rois(left_roi, right_roi, frame_shape)
        search_roi = search["left"]["roi"]
        self.assertGreater(search_roi[2], left_roi[2])

        frame = np.zeros(frame_shape, dtype=np.uint8)
        cv2.line(frame, (235, search_roi[1]), (235, search_roi[3] - 1),
                 (255, 255, 255), 4)
        _edges, lines = detect_recovery_lines(
            frame, search_roi,
            SimpleNamespace(LANE_THRESHOLD=70, HOUGH_THRESHOLD=8,
                            HOUGH_MIN_LINE_LENGTH=16, HOUGH_MAX_LINE_GAP=8),
        )
        self.assertIsNotNone(lines)
        self.assertTrue(any(
            abs(float(np.asarray(line).reshape(-1)[0]) + search_roi[0] - 235.0) < 8.0
            for line in lines
        ))


if __name__ == "__main__":
    unittest.main()
