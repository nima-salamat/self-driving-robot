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

    def test_renderer_handles_missing_frame(self):
        self.assertIsNone(render_lane_debug_overlay(None, {}, self.config, 95))


if __name__ == "__main__":
    unittest.main()
