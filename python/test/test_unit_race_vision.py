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



class RaceVisionDebugOverlayTests(unittest.TestCase):
    def test_debug_lane_guide_uses_absolute_frame_coordinates_and_compact_labels(self):
        source = (
            PYTHON_ROOT / "vision" / "race_vision_processing.py"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "lane_center_guide_x = int(np.clip(frame_center - lane_center, 0, w_dbg - 1))",
            source,
        )
        self.assertIn('candidate_label = "Candidate:"', source)
        self.assertIn("candidate_font_scale = max(0.24, min(0.38, h_dbg / 1400.0))", source)
        self.assertNotIn("R Hough candidates:", source)
        self.assertNotIn("L Hough candidates:", source)


if __name__ == "__main__":
    unittest.main()
