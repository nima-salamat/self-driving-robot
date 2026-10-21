import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from visualization.lane_debug_overlay import (
    render_lane_debug_overlay,
    resolve_visual_steering_angle,
    steering_marker_x,
)


class LaneDebugOverlayTests(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace(
            OLD_METHOD=False,
            USE_PID=True,
            SERVO_CENTER=95,
            MIN_SERVO_ANGLE=55,
            MAX_SERVO_ANGLE=125,
            SERVO_DIRECTION="ltr",
        )

    def test_non_legacy_system_uses_last_applied_controller_angle(self):
        self.assertEqual(resolve_visual_steering_angle(self.config, 108, 91), 108)

    def test_non_legacy_without_known_controller_angle_does_not_fabricate_one(self):
        self.assertIsNone(resolve_visual_steering_angle(self.config, None, 91))

    def test_legacy_system_keeps_vision_angle(self):
        self.config.OLD_METHOD = True
        self.assertEqual(resolve_visual_steering_angle(self.config, 108, 91), 91)

    def test_marker_follows_physical_servo_direction(self):
        width = 640
        center_x = width // 2
        self.config.SERVO_DIRECTION = "ltr"
        self.assertGreater(steering_marker_x(width, self.config, 105), center_x)
        self.assertLess(steering_marker_x(width, self.config, 85), center_x)

        self.config.SERVO_DIRECTION = "rtl"
        self.assertLess(steering_marker_x(width, self.config, 105), center_x)
        self.assertGreater(steering_marker_x(width, self.config, 85), center_x)

    def test_renderer_returns_annotated_copy_and_preserves_source(self):
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        original = frame.copy()

        rendered = render_lane_debug_overlay(
            frame,
            {"kind": "classical"},
            self.config,
            steering_angle=105,
        )

        self.assertIsNot(rendered, frame)
        self.assertEqual(rendered.shape, frame.shape)
        np.testing.assert_array_equal(frame, original)
        self.assertGreater(np.count_nonzero(rendered), 0)

    def test_servo_guide_can_be_disabled_by_stream_settings(self):
        from unittest.mock import patch

        self.config.stream_ui_settings = {"frame_overlay": {"servo_guide": False}}
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        with patch("visualization.lane_debug_overlay.cv2.putText") as put_text:
            render_lane_debug_overlay(frame, {}, self.config, steering_angle=103)
        put_text.assert_not_called()

    def test_servo_guide_uses_the_configured_center_not_the_default(self):
        from unittest.mock import patch

        self.config.SERVO_CENTER = 103
        self.config.stream_ui_settings = {"frame_overlay": {"servo_guide": True}}
        frame = np.zeros((120, 320, 3), dtype=np.uint8)
        with patch("visualization.lane_debug_overlay.cv2.putText") as put_text:
            render_lane_debug_overlay(frame, {}, self.config, steering_angle=103)
        self.assertTrue(put_text.called)
        self.assertIn("CENTER", put_text.call_args.args[1])
        self.assertIn("Applied 103", put_text.call_args.args[1])
        self.assertIn("Center 103", put_text.call_args.args[1])

    def test_candidate_labels_can_be_disabled(self):
        from unittest.mock import patch

        self.config.stream_ui_settings = {
            "frame_overlay": {"candidate_labels": False, "servo_guide": False}
        }
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        draw_data = {
            "kind": "classical",
            "frame_width": 160,
            "frame_height": 120,
            "roi_bounds": {"RL": (90, 30, 150, 110), "LL": (10, 30, 70, 110)},
        }
        with patch("visualization.lane_debug_overlay.cv2.putText") as put_text:
            render_lane_debug_overlay(frame, draw_data, self.config, steering_angle=None)
        labels = [call.args[1] for call in put_text.call_args_list]
        self.assertNotIn("Candidate:", labels)

    def test_detector_summary_text_is_no_longer_hardcoded_in_graphic_overlay(self):
        from unittest.mock import patch

        self.config.stream_ui_settings = {"frame_overlay": {"servo_guide": False}}
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        for kind in ("blsf", "classical"):
            with self.subTest(kind=kind):
                draw_data = {
                    "kind": kind,
                    "frame_width": 160,
                    "frame_height": 120,
                    "lane_type": "both",
                    "lane_error": 3.5,
                    "crosswalk": True,
                }
                with patch("visualization.lane_debug_overlay.cv2.putText") as put_text:
                    render_lane_debug_overlay(frame, draw_data, self.config, steering_angle=None)
                labels = [call.args[1] for call in put_text.call_args_list]
                self.assertFalse(any("BLSF-BETA" in str(label) for label in labels))
                self.assertFalse(any("crosswalk:" in str(label) for label in labels))

    def test_renderer_handles_missing_frame(self):
        self.assertIsNone(render_lane_debug_overlay(None, {}, self.config, 95))


if __name__ == "__main__":
    unittest.main()
