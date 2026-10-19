import sys
import unittest
from pathlib import Path

import numpy as np

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from vision.city_vision_processing import VisionProcessor


class CityVisionLineExtractionTests(unittest.TestCase):
    def test_extract_line_accepts_flat_opencv_segment(self):
        line = np.array([10, 20, 30, 40], dtype=np.float32)

        coordinates = VisionProcessor._extract_line(line)

        np.testing.assert_array_equal(coordinates, [10, 20, 30, 40])

    def test_extract_line_accepts_nested_opencv_segment(self):
        line = np.array([[10, 20, 30, 40]], dtype=np.float32)

        coordinates = VisionProcessor._extract_line(line)

        np.testing.assert_array_equal(coordinates, [10, 20, 30, 40])

    def test_extract_line_rejects_malformed_segment(self):
        with self.assertRaisesRegex(ValueError, "4 coordinates"):
            VisionProcessor._extract_line(np.array([10, 20, 30], dtype=np.float32))

    def test_no_lane_result_preserves_last_steering_angle(self):
        processor = VisionProcessor()
        processor.last_steering = 113
        blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)

        result = processor.detect(blank_frame)

        self.assertEqual(result["lane_type"], "none")
        self.assertFalse(result["perception_valid"])
        self.assertEqual(result["steering_angle"], 113)



    def test_lane_overlay_rendering_lives_outside_the_vision_processor(self):
        vision_source = (
            PYTHON_ROOT / "vision" / "city_vision_processing.py"
        ).read_text(encoding="utf-8")
        overlay_source = (
            PYTHON_ROOT / "visualization" / "lane_debug_overlay.py"
        ).read_text(encoding="utf-8")

        self.assertIn('"kind": "classical"', vision_source)
        self.assertIn('"lane_center_offset_px": float(lane_center)', vision_source)
        self.assertNotIn("cv2.line(", vision_source)
        self.assertNotIn("cv2.putText(", vision_source)
        self.assertIn('label = "Candidate:"', overlay_source)
        self.assertIn("lane_center_offset_px", overlay_source)
        self.assertIn("steering_marker_x", overlay_source)

    def test_debug_payload_is_none_when_debug_and_stream_are_disabled(self):
        import modes.city.config_city as city_config
        from unittest.mock import patch

        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        with patch.object(city_config, "DEBUG", False), patch.object(
            city_config, "STREAM", False
        ):
            result = VisionProcessor().detect(frame)

        self.assertIsNone(result["debug"])

if __name__ == "__main__":
    unittest.main()
