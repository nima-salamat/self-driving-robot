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

    def test_hall_tracking_forces_debug_payload_for_simulator_stream(self):
        import modes.city.config_city as city_config
        from unittest.mock import patch

        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        with patch.object(city_config, "HALL_LINE_TRACKING_ENABLED", True), patch.object(
            city_config, "DEBUG", False
        ), patch.object(city_config, "STREAM", False):
            result = VisionProcessor().detect(frame)

        self.assertFalse(result["perception_valid"])
        self.assertTrue(result["line_tracking"]["enabled"])
        self.assertIsNotNone(result["debug"])
        self.assertIn("lane_tracking", result["debug"]["draw_data"])

    def test_hall_sobel_hough_pipeline_tracks_synthetic_city_lane_pair(self):
        import modes.city.config_city as config
        from unittest.mock import patch

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        import cv2
        cv2.line(frame, (250, 240), (205, 479), (255, 255, 255), 4)
        cv2.line(frame, (390, 240), (435, 479), (255, 255, 255), 4)
        values = {
            "HALL_LINE_TRACKING_ENABLED": True, "HALL_LINE_TRACKING_MAX_MISSED": 4,
            "HALL_LINE_TRACKING_REACQUIRE_FRAMES": 2,
            "SIMULATOR_BACKEND": "carla",
            "USE_BEV": False, "OLD_METHOD": False, "LANE_THRESHOLD": 70,
            "HOUGH_THRESHOLD": 10, "HOUGH_MIN_LINE_LENGTH": 20,
            "HOUGH_MAX_LINE_GAP": 10, "HOUGH_BLUR_KERNEL": 3,
            "HOUGH_MORPH_CLOSE": True, "DEBUG": False, "STREAM": False,
            "LANE_ROI_MODE": "rectangle", "RL_TOP_ROI": .5, "RL_BOTTOM_ROI": 1.,
            "RL_LEFT_ROI": .55, "RL_RIGHT_ROI": .9,
            "LL_TOP_ROI": .5, "LL_BOTTOM_ROI": 1.,
            "LL_LEFT_ROI": .1, "LL_RIGHT_ROI": .45,
        }
        with patch.multiple(config, create=True, **values):
            processor = VisionProcessor()
            processor.detect(frame)  # First consistent frame is only pending.
            result = processor.detect(frame)

        self.assertTrue(result["line_tracking"]["enabled"])
        self.assertEqual(result["lane_type"], "both")
        self.assertTrue(result["perception_valid"])
        self.assertEqual(result["observed_lane_boundaries"], 2)
        self.assertEqual(result["line_tracking"]["reacquire_frames"], 2)

    def test_hall_tracker_receives_bev_geometry_mode_from_city_processor(self):
        import modes.city.config_city as config
        from unittest.mock import patch

        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        values = {
            "HALL_LINE_TRACKING_ENABLED": True,
            "SIMULATOR_BACKEND": "carla",
            "USE_BEV": True,
            "OLD_METHOD": False,
            "DEBUG": False,
            "STREAM": False,
        }
        with patch.multiple(config, create=True, **values):
            result = VisionProcessor().detect(frame)

        self.assertEqual(result["line_tracking"]["geometry_mode"], "bev")
        self.assertEqual(result["debug"]["draw_data"]["geometry_mode"], "bev")
        self.assertEqual(result["line_tracking"]["lane_width_model"], "constant_bev")

    def test_simulator_hall_uses_exact_configured_rois_when_legacy_resizing_is_enabled(self):
        import modes.city.config_city as config
        from unittest.mock import patch

        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        values = {
            "HALL_LINE_TRACKING_ENABLED": True,
            "HALL_LINE_TRACKING_MAX_MISSED": 4,
            "HALL_LINE_TRACKING_REACQUIRE_FRAMES": 3,
            "SIMULATOR_BACKEND": "carla",
            "USE_BEV": False,
            "OLD_METHOD": False,
            "ROI_RESIZABLE": True,
            "LANE_THRESHOLD": 70,
            "HOUGH_THRESHOLD": 10,
            "HOUGH_MIN_LINE_LENGTH": 20,
            "HOUGH_MAX_LINE_GAP": 10,
            "HOUGH_BLUR_KERNEL": 3,
            "HOUGH_MORPH_CLOSE": True,
            "DEBUG": False,
            "STREAM": False,
            "LANE_ROI_MODE": "rectangle",
            "RL_TOP_ROI": .5,
            "RL_BOTTOM_ROI": 1.0,
            "RL_LEFT_ROI": .55,
            "RL_RIGHT_ROI": .90,
            "LL_TOP_ROI": .5,
            "LL_BOTTOM_ROI": 1.0,
            "LL_LEFT_ROI": .12,
            "LL_RIGHT_ROI": .45,
        }
        with patch.multiple(config, create=True, **values):
            processor = VisionProcessor()
            # Simulate the legacy counters being non-zero. Hall mode must not
            # silently feed their edge-expanded rectangle to the detector.
            processor.lroi_unseen_counter = 10
            processor.rroi_unseen_counter = 10
            result = processor.detect(frame)

        draw = result["debug"]["draw_data"]
        expected_left = (int(.12 * 640), int(.5 * 480), int(.45 * 640), 480)
        expected_right = (int(.55 * 640), int(.5 * 480), int(.90 * 640), 480)
        self.assertEqual(draw["configured_roi_bounds"]["LL"], expected_left)
        self.assertEqual(draw["configured_roi_bounds"]["RL"], expected_right)
        self.assertEqual(draw["roi_bounds"]["LL"], expected_left)
        self.assertEqual(draw["roi_bounds"]["RL"], expected_right)
        self.assertFalse(draw["legacy_roi_resizable_applied"])
        self.assertEqual(result["line_tracking"]["left"]["search_roi"], list(expected_left))
        self.assertEqual(result["line_tracking"]["right"]["search_roi"], list(expected_right))

    def test_avis_city_simulator_detects_crosswalk_and_returns_debug_geometry(self):
        import modes.city.config_city as city_config
        from unittest.mock import patch

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        frame[48:240, 32:288] = (255, 255, 255)
        lines = np.asarray([
            [[30, 15, 32, 170]], [[90, 15, 92, 170]], [[150, 15, 152, 170]],
            [[10, 155, 245, 157]], [[10, 135, 245, 137]],
        ], dtype=np.float32)
        values = {
            "SIMULATOR_BACKEND": "avis", "USE_BEV": False, "OLD_METHOD": False,
            "CW_OLD_METHOD": True, "CROSSWALK_THRESHOLD": 120,
            "CROSSWALK_VERTICAL_MIN_LINES": 2, "CROSSWALK_HORIZONTAL_MIN_LINES": 2,
            "CW_TOP_ROI": 0.2, "CW_BOTTOM_ROI": 1.0,
            "CW_LEFT_ROI": 0.1, "CW_RIGHT_ROI": 0.9,
            "DEBUG": False, "STREAM": False, "HALL_LINE_TRACKING_ENABLED": False,
        }
        fake_lsd = type(
            "FakeLineSegmentDetector", (),
            {"detect": lambda self, _image: (lines, None, None, None)},
        )()
        with patch.multiple(city_config, create=True, **values), patch(
            "vision.city_vision_processing.cv2.createLineSegmentDetector",
            return_value=fake_lsd,
        ):
            processor = VisionProcessor()
            result = processor.detect(frame)

        self.assertTrue(result["crosswalk"])
        self.assertEqual(result["crosswalk_color"], "WHITE")
        self.assertIsNotNone(result["crosswalk_geometry"])
        self.assertGreater(result["crosswalk_geometry"]["radius"], 0)
        self.assertEqual(
            result["debug"]["draw_data"]["crosswalk_geometry"],
            result["crosswalk_geometry"],
        )

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
