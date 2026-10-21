import sys
import unittest
from pathlib import Path

PYTHON_ROOT = Path(__file__).resolve().parents[1]
TEST_ROOT = Path(__file__).resolve().parent
for path in (str(PYTHON_ROOT), str(TEST_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import test_manual_control as manual


class ManualControlSafetyTests(unittest.TestCase):
    def setUp(self):
        with manual.state_lock:
            known_sids = set(manual.state["clients"])
        self.client = manual.socketio.test_client(
            manual.app, auth={"token": manual.MANUAL_TOKEN}
        )
        self.assertTrue(self.client.is_connected())
        with manual.state_lock:
            new_sids = set(manual.state["clients"]) - known_sids
        self.assertEqual(len(new_sids), 1)
        self.sid = next(iter(new_sids))
        with manual.state_lock:
            manual.state["estop"] = False
            manual.state["hold_stop_clients"].clear()
            manual.state["seq_seen"].clear()
            manual.state["speed"] = manual.state["speed_target"] = 0.0
            manual.state["angle"] = manual.state["angle_target"] = manual.SERVO_CENTER
            manual.state["speed_immediate"] = False
            manual.state["steering_immediate"] = False
            manual.state["last_cmd"] = 0.0
            manual.state["watchdog_active"] = True
            manual.settings["max_speed"] = 200
            manual.settings["angle_limit_deg"] = 60
            manual.settings["angle_trim"] = 0.0

    def tearDown(self):
        if self.client.is_connected():
            self.client.disconnect()

    def test_servo_mapping_reaches_both_configured_endpoints(self):
        self.assertEqual(
            manual._servo_angle_for_steer(-1.0, 90.0), manual.SERVO_MIN
        )
        self.assertEqual(
            manual._servo_angle_for_steer(0.0, 90.0), manual.SERVO_CENTER
        )
        self.assertEqual(
            manual._servo_angle_for_steer(1.0, 90.0), manual.SERVO_MAX
        )

    def test_space_hold_stop_blocks_motion_and_release_does_not_resume_stale_speed(self):
        self.client.emit("hold_stop", {"active": True})
        with manual.state_lock:
            self.assertIn(self.sid, manual.state["hold_stop_clients"])

        self.client.emit(
            "input",
            {"seq": 1, "forward": 1, "steer": 1, "speed_scale": 1},
        )
        with manual.state_lock:
            self.assertEqual(manual.state["speed_target"], 0.0)
            self.assertEqual(manual.state["angle_target"], manual.SERVO_CENTER)
            self.assertEqual(manual.state["last_cmd"], 0.0)

        self.client.emit("hold_stop", {"active": False})
        with manual.state_lock:
            self.assertNotIn(self.sid, manual.state["hold_stop_clients"])
            self.assertEqual(manual.state["speed_target"], 0.0)
            self.assertEqual(manual.state["last_cmd"], 0.0)

        # Motion is accepted only when a new post-release input arrives.
        self.client.emit(
            "input",
            {"seq": 2, "forward": 1, "steer": 1, "speed_scale": 1},
        )
        with manual.state_lock:
            self.assertGreater(manual.state["speed_target"], 0.0)
            self.assertEqual(manual.state["angle_target"], manual.SERVO_MAX)

    def test_immediate_neutral_input_stops_throttle_without_canceling_steering(self):
        self.client.emit(
            "input",
            {"seq": 1, "forward": 1, "steer": 0.5, "speed_scale": 1},
        )
        self.client.emit(
            "input",
            {"seq": 2, "forward": 0, "steer": 0.5, "speed_scale": 0,
             "speed_immediate": True},
        )
        with manual.state_lock:
            self.assertEqual(manual.state["speed_target"], 0.0)
            self.assertTrue(manual.state["speed_immediate"])
            self.assertEqual(
                manual.state["angle_target"],
                manual._servo_angle_for_steer(0.5, 60.0),
            )

    def test_keyboard_key_release_is_wired_to_immediate_neutral(self):
        # The controller UI is embedded in this Python file, so guard the
        # browser-to-server dead-man wiring against accidental regressions.
        html = manual.INDEX_HTML
        self.assertIn("function forceKeyboardThrottleStop()", html)
        self.assertIn("if(!keyState.up&&!keyState.down)forceKeyboardThrottleStop();", html)
        self.assertIn(
            "sendInput({forward:0,steer:current.steer,speed_scale:0,speed_immediate:true})",
            html,
        )

    def test_camera_stream_encodes_each_capture_once_and_serves_latest_jpeg(self):
        source = (PYTHON_ROOT / "test" / "test_manual_control.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("latest_camera_jpeg=None", source)
        self.assertIn("latest_camera_jpeg = encoded.tobytes()", source)
        self.assertIn("last_frame_at = 0.0", source)
        self.assertNotIn('ok,jpg=cv2.imencode(".jpg",frame', source)

    def test_mobile_layout_uses_dynamic_viewport_safe_areas_and_landscape_rules(self):
        html = manual.INDEX_HTML
        self.assertIn("height:100dvh", html)
        self.assertIn("env(safe-area-inset-bottom)", html)
        self.assertIn("@media(max-height:500px) and (orientation:landscape)", html)
        self.assertIn("}, 33); // ~30 Hz", html)

    def test_priority_stop_is_immediate_then_refreshed_at_ten_hz(self):
        interval = manual.PRIORITY_STOP_REFRESH_INTERVAL
        self.assertTrue(manual._priority_stop_due(True, False, 1.0, 1.0))
        self.assertFalse(manual._priority_stop_due(True, True, 1.05, 1.0))
        self.assertTrue(manual._priority_stop_due(True, True, 1.0 + interval, 1.0))
        self.assertFalse(manual._priority_stop_due(False, True, 2.0, 1.0))


if __name__ == "__main__":
    unittest.main()
