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


class LaneRecoveryDetectionTests(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace(
            LANE_THRESHOLD=180,
            HOUGH_THRESHOLD=15,
            HOUGH_MIN_LINE_LENGTH=8,
            HOUGH_MAX_LINE_GAP=10,
            HOUGH_BLUR_KERNEL=3,
            HOUGH_MORPH_CLOSE=True,
        )

    def test_sobel_hough_recovery_detects_a_faint_vertical_lane_marking(self):
        frame = np.zeros((220, 320, 3), dtype=np.uint8)
        cv2.line(frame, (102, 28), (102, 205), (72, 72, 72), 5, cv2.LINE_AA)

        edges, lines = detect_recovery_lines(
            frame, (40, 12, 180, 215), self.config
        )

        self.assertIsNotNone(edges)
        self.assertGreater(int(np.count_nonzero(edges)), 0)
        self.assertIsNotNone(lines)
        self.assertGreaterEqual(len(lines), 1)
        self.assertTrue(
            any(abs(float(np.asarray(line).reshape(-1)[0]) - 62.0) < 12.0
                for line in lines),
            "The recovery detector should return a segment near the drawn line",
        )

    def test_recovery_roi_is_clipped_to_the_camera_frame(self):
        frame = np.zeros((40, 60, 3), dtype=np.uint8)

        edges, lines = detect_recovery_lines(
            frame, (-100, -100, 200, 200), self.config
        )

        self.assertEqual(edges.shape, (40, 60))
        self.assertIsNone(lines)

    def test_invalid_or_empty_input_is_ignored(self):
        self.assertEqual(
            detect_recovery_lines(None, (0, 0, 10, 10), self.config),
            (None, None),
        )
        self.assertEqual(
            detect_recovery_lines(
                np.zeros((10, 10, 3), dtype=np.uint8),
                (5, 5, 5, 5),
                self.config,
            ),
            (None, None),
        )


if __name__ == "__main__":
    unittest.main()
