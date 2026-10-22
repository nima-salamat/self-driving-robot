import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

import stream
from arduino.arduino_connection import ArduinoConnection
from modes.city import config_city
from modes.race import config_race
from stream import WebStreamer


class _FakeSerial:
    is_open = True

    def __init__(self):
        self.writes = []
        self.closed = False

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def flush(self):
        pass

    def close(self):
        self.closed = True
        self.is_open = False


class _FakeArduinoConnection:
    connected = True
    enabled = True

    def __init__(self):
        self.commands = []
        self.automatic_commands_enabled = False

    def send_custom_command(self, command):
        self.commands.append(command)
        return True

    def set_automatic_commands_enabled(self, enabled):
        self.automatic_commands_enabled = bool(enabled)

    def telemetry_status(self, limit=50):
        return {
            "state": "CONNECTED",
            "connected": True,
            "lines": [],
            "error": None,
        }


class ArduinoCommandPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base_dir_patch = patch.object(stream, "BASE_DIR", self.tmp.name)
        base_dir_patch.start()
        self.addCleanup(base_dir_patch.stop)
        env_patch = patch.dict(os.environ, {"STREAM_USERNAME": "", "STREAM_PASSWORD": ""})
        env_patch.start()
        self.addCleanup(env_patch.stop)

    def make_streamer(self, connection=None, *, controls=True, mode="city"):
        config = types.SimpleNamespace(
            MODE=mode,
            STREAM=True,
            STREAM_ALLOW_CONTROL=controls,
            RECORD_VIDEO=False,
            USE_BEV=False,
            USE_ML_LANE_DETECTOR=False,
            CITY_LANE_DETECTOR="default",
            debug_frames_list=[],
            stream_frame_seq=0,
            OUTPUT_DIR="output",
            SEND_AUTOMATIC_ARDUINO_COMMANDS=False,
            READ_ARDUINO_OUTPUT=True,
            WITHOUT_ARDUINO=False,
        )
        if connection is not None:
            config.arduino_connection = connection
        return WebStreamer(config), config

    def test_python_defaults_and_json_defaults_match_in_both_modes(self):
        for config, json_name in (
            (config_city, "city.json"),
            (config_race, "race.json"),
        ):
            with self.subTest(mode=config.MODE):
                self.assertIs(config.SEND_AUTOMATIC_ARDUINO_COMMANDS, True)
                with (PYTHON_ROOT / json_name).open(encoding="utf-8") as handle:
                    saved = json.load(handle)
                self.assertIs(saved["SEND_AUTOMATIC_ARDUINO_COMMANDS"], True)

    def test_automatic_commands_are_suppressed_but_custom_commands_bypass_gate(self):
        connection = ArduinoConnection(enabled=False, automatic_commands_enabled=False)
        serial = _FakeSerial()
        connection.enabled = True
        connection._state = connection.CONNECTED
        connection.serial_connection = serial
        try:
            with patch.object(connection, "_ensure_reader_started", return_value=None):
                self.assertFalse(connection.send_command("servo 90\n"))
                self.assertEqual(serial.writes, [])
                self.assertTrue(connection.send_custom_command("servo 90\n"))
                self.assertEqual(serial.writes, [b"servo 90\n"])
                connection.set_automatic_commands_enabled(True)
                self.assertTrue(connection.send_command("servo 91\n"))
                self.assertEqual(serial.writes, [b"servo 90\n", b"servo 91\n"])
        finally:
            connection.enabled = False
            connection.close()

    def test_custom_command_endpoint_bypasses_policy_and_sends_one_line(self):
        connection = _FakeArduinoConnection()
        streamer, config = self.make_streamer(connection)
        client = streamer.app.test_client()

        response = client.post("/api/arduino-command", json={"command": "servo 95"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])
        payload = response.get_json()
        self.assertEqual(payload["delivery_status"], "transmitted_unconfirmed")
        self.assertFalse(payload["device_acknowledged"])
        self.assertFalse(payload["execution_confirmed"])
        self.assertEqual(connection.commands, ["servo 95\\n"])
        self.assertFalse(config.SEND_AUTOMATIC_ARDUINO_COMMANDS)

    def test_custom_command_endpoint_rejects_multiline_and_read_only_mode(self):
        connection = _FakeArduinoConnection()
        streamer, config = self.make_streamer(connection)
        client = streamer.app.test_client()

        bad = client.post("/api/arduino-command", json={"command": "servo 95\nstop"})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(connection.commands, [])

        config.STREAM_ALLOW_CONTROL = False
        denied = client.post("/api/arduino-command", json={"command": "servo 95"})
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(connection.commands, [])

    def test_arduino_status_exposes_current_automatic_command_policy(self):
        connection = _FakeArduinoConnection()
        streamer, _ = self.make_streamer(connection)
        result = streamer.app.test_client().get("/api/arduino-output")
        self.assertEqual(result.status_code, 200)
        self.assertFalse(result.get_json()["automatic_commands_enabled"])

    def test_arduino_status_reports_without_arduino_mode_and_blocks_manual_send(self):
        connection = _FakeArduinoConnection()
        streamer, config = self.make_streamer(connection)
        config.WITHOUT_ARDUINO = True
        client = streamer.app.test_client()

        payload = client.get("/api/arduino-output").get_json()
        self.assertTrue(payload["without_arduino"])
        self.assertFalse(payload["hardware_available"])
        self.assertFalse(payload["connected"])
        self.assertEqual(payload["state"], "DISABLED")

        denied = client.post("/api/arduino-command", json={"command": "servo 95"})
        self.assertEqual(denied.status_code, 409)
        self.assertIn("--without-arduino", denied.get_json()["message"])
        self.assertEqual(connection.commands, [])

    def test_arduino_status_reports_connected_hardware(self):
        streamer, config = self.make_streamer(_FakeArduinoConnection())
        payload = streamer.app.test_client().get("/api/arduino-output").get_json()
        self.assertFalse(payload["without_arduino"])
        self.assertTrue(payload["hardware_available"])
        self.assertTrue(payload["connected"])

    def test_terminal_contains_arduino_command_tab_and_telemetry_policy_button(self):
        template = (PYTHON_ROOT / "stream" / "templates" / "stream.html").read_text(encoding="utf-8")
        javascript = (PYTHON_ROOT / "stream" / "static" / "stream-core.js").read_text(encoding="utf-8")
        stylesheet = (PYTHON_ROOT / "stream" / "static" / "stream.css").read_text(encoding="utf-8")
        telemetry_pos = template.index('<span>Arduino Telemetry</span>')
        policy_pos = template.index('id="arduino_auto_commands_enabled"')
        commands_pos = template.index('class="console-body console-command-body"')
        self.assertIn('data-console-tab="arduino-commands"', template)
        self.assertIn('type="button" id="arduino_auto_commands_enabled"', template)
        self.assertNotIn('type="checkbox" id="arduino_auto_commands_enabled"', template)
        self.assertLess(telemetry_pos, policy_pos)
        telemetry_end = template.index('</details>', telemetry_pos)
        self.assertLess(policy_pos, telemetry_end)
        self.assertEqual(template.count('id="arduino_auto_commands_enabled"'), 1)
        self.assertIn('id="arduino_hardware_notice"', template)
        self.assertIn('id="console_arduino_notice"', template)
        self.assertIn('id="arduino_commands_hardware_notice"', template)
        self.assertIn('id="arduino_custom_command"', template)
        self.assertIn("/api/arduino-command", javascript)
        self.assertIn("SEND_AUTOMATIC_ARDUINO_COMMANDS", javascript)
        self.assertIn("policyToggle.addEventListener('click'", javascript)
        self.assertIn('.arduino-policy-toggle[aria-pressed="true"]', stylesheet)


if __name__ == "__main__":
    unittest.main()
