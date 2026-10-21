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
        self.client = manual.socketio.test_client(
            manual.app, auth={"token": manual.MANUAL_TOKEN}
        )
        self.assertTrue(self.client.is_connected())
        self.sid = self.client.get_sid("/")
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

    def test_priority_stop_is_immediate_then_refreshed_at_ten_hz(self):
        interval = manual.PRIORITY_STOP_REFRESH_INTERVAL
        self.assertTrue(manual._priority_stop_due(True, False, 1.0, 1.0))
        self.assertFalse(manual._priority_stop_due(True, True, 1.05, 1.0))
        self.assertTrue(manual._priority_stop_due(True, True, 1.0 + interval, 1.0))
        self.assertFalse(manual._priority_stop_due(False, True, 2.0, 1.0))


if __name__ == "__main__":
    unittest.main()
