import sys
import threading
import time
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, "python")

from arduino.arduino_connection import ArduinoConnection
from controller.motion_history import MotionHistory
from utils.json_config import load


class MotionHistoryTests(unittest.TestCase):
    def test_keeps_last_200_individual_pulses(self):
        history = MotionHistory(max_pulses=200, max_events=8)

        recorded = history.record_pulse_command(
            "f 200 205 90",
            event="hardcode_test",
        )

        self.assertEqual(recorded, 200)
        pulses = history.recent_pulses()
        self.assertEqual(len(pulses), 200)
        self.assertEqual(pulses[0]["pulse_index"], 6)
        self.assertEqual(pulses[-1]["pulse_index"], 205)
        self.assertTrue(all(item["event"] == "hardcode_test" for item in pulses))

    def test_multiple_pulse_groups_keep_order_and_metadata(self):
        history = MotionHistory(max_pulses=10, max_events=8)

        recorded = history.record_pulse_command(
            "b 170 3 70 f 170 4 125",
            event="lane_change",
            metadata={"side": "left"},
        )

        self.assertEqual(recorded, 7)
        pulses = history.recent_pulses()
        self.assertEqual([p["direction"] for p in pulses[:3]], ["backward"] * 3)
        self.assertEqual([p["direction"] for p in pulses[3:]], ["forward"] * 4)
        self.assertEqual(pulses[3]["group_index"], 1)
        self.assertEqual(pulses[3]["metadata"]["side"], "left")

    def test_events_are_preserved_separately_from_pulses(self):
        history = MotionHistory(max_pulses=3, max_events=8)

        history.record_event(
            "crosswalk_stop_started",
            metadata={"planned_duration_s": 3.0},
        )
        history.record_pulse_command(
            "f 220 5 90",
            event="crosswalk_straight",
        )

        self.assertEqual(len(history.recent_pulses()), 3)
        self.assertEqual(len(history.recent_events()), 1)
        self.assertEqual(
            history.recent_events()[0]["metadata"]["planned_duration_s"],
            3.0,
        )

    def test_invalid_command_is_not_recorded(self):
        history = MotionHistory()
        self.assertEqual(history.record_pulse_command("set left f 200 10 90"), 0)
        self.assertEqual(history.recent_pulses(), [])


class ArduinoHeartbeatTests(unittest.TestCase):
    class FakeSerial:
        def __init__(self):
            self.is_open = True
            self.writes = []

        def write(self, data):
            self.writes.append(data)
            return len(data)

        def flush(self):
            return None

        def close(self):
            self.is_open = False

    def test_heartbeat_worker_sends_liveness_messages(self):
        fake = self.FakeSerial()
        connection = ArduinoConnection(
            enabled=False,
            heartbeat_interval=0.02,
        )
        try:
            connection.enabled = True
            with connection._serial_lock:
                connection.serial_connection = fake
            connection._set_state(ArduinoConnection.CONNECTED)

            self.assertTrue(connection._send_heartbeat())
            self.assertTrue(connection._send_heartbeat())
            self.assertEqual(fake.writes.count(b"heartbeat\n"), 2)
        finally:
            connection.close()


class JsonConfigPathTests(unittest.TestCase):
    def test_load_uses_project_runtime_path_not_cwd(self):
        import base_config
        import modes.city.config_city as config_city

        previous_mode = base_config.MODE
        previous_change = config_city.CHANGE_WITH_JSON
        previous_left = config_city.LL_LEFT_ROI
        base_config.MODE = "city"
        config_city.CHANGE_WITH_JSON = True

        try:
            with patch("utils.json_config.os.getcwd", return_value="/tmp"):
                load()
            self.assertAlmostEqual(config_city.LL_LEFT_ROI, 0.139)
        finally:
            base_config.MODE = previous_mode
            config_city.CHANGE_WITH_JSON = previous_change
            config_city.LL_LEFT_ROI = previous_left


if __name__ == "__main__":
    unittest.main()
