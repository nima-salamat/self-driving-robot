import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from visualization.frame_telemetry import build_frame_telemetry


class FrameTelemetryTests(unittest.TestCase):
    def test_only_selected_frame_fields_are_rendered(self):
        config = SimpleNamespace(
            SERVO_CENTER=103,
            stream_ui_settings={
                "frame_overlay": {
                    "fps": False,
                    "realfps": False,
                    "status": True,
                    "applied_angle": False,
                    "vision_angle": False,
                    "servo_center": True,
                    "error": True,
                    "lane_type": False,
                    "speed": False,
                    "crosswalk": False,
                    "sign": False,
                    "last_tag": False,
                    "confidence": False,
                    "obstacle": False,
                }
            },
        )
        text = " ".join(build_frame_telemetry(
            config,
            instant_fps=8.5,
            real_fps=14.0,
            status="running",
            applied_angle=95,
            vision_angle=101,
            error=-17.5,
            lane_type="both",
        ))
        self.assertIn("Status:running", text)
        self.assertIn("Center:103", text)
        self.assertIn("Error:-17.5", text)
        self.assertNotIn("FPS:", text)
        self.assertNotIn("Target:", text)
        self.assertNotIn("Servo:95", text)
        self.assertNotIn("Lane:", text)

    def test_overlay_settings_are_per_mode_and_wrap_long_text(self):
        config = SimpleNamespace(
            SERVO_CENTER=97,
            stream_ui_settings={"frame_overlay": {"status": True, "servo_center": True}},
        )
        lines = build_frame_telemetry(config, status="STOP HOLD", max_line_length=24)
        self.assertGreaterEqual(len(lines), 2)
        self.assertTrue(all(len(line) <= 40 for line in lines))
        self.assertTrue(any("Center:97" in line for line in lines))


if __name__ == "__main__":
    unittest.main()
