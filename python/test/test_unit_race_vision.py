import sys
import unittest
from pathlib import Path

import numpy as np

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from modes.race.race import VisionProcessor


class RaceVisionLaneLossTests(unittest.TestCase):
    def test_no_lane_result_preserves_last_steering_angle(self):
        processor = VisionProcessor()
        processor.last_steering = 116
        blank_frame = np.zeros((230, 380, 3), dtype=np.uint8)

        result = processor.detect(blank_frame)

        self.assertEqual(result["lane_type"], "none")
        self.assertFalse(result["perception_valid"])
        self.assertEqual(result["steering_angle"], 116)


class RaceVisionLineExtractionTests(unittest.TestCase):
    def test_extract_line_accepts_flat_opencv_segment(self):
        line = np.array([10, 20, 30, 40], dtype=np.int32)

        coordinates = VisionProcessor._extract_line(line)

        np.testing.assert_array_equal(coordinates, [10, 20, 30, 40])

    def test_extract_line_accepts_nested_opencv_segment(self):
        line = np.array([[10, 20, 30, 40]], dtype=np.int32)

        coordinates = VisionProcessor._extract_line(line)

        np.testing.assert_array_equal(coordinates, [10, 20, 30, 40])

    def test_best_mid_x_accepts_flat_per_segment_shape(self):
        # Reproduces HoughLinesP output represented as (N, 4), so each
        # line in the loop is shape (4,), not (1, 4).
        processor = VisionProcessor.__new__(VisionProcessor)
        lines = np.array([[10, 20, 30, 40]], dtype=np.int32)

        midpoint = processor._best_mid_x(lines, roi_w=100, roi_h=100)

        self.assertAlmostEqual(midpoint, 20.0)

    def test_extract_line_rejects_malformed_segment(self):
        with self.assertRaisesRegex(ValueError, "4 coordinates"):
            VisionProcessor._extract_line(np.array([10, 20, 30], dtype=np.int32))


if __name__ == "__main__":
    unittest.main()
