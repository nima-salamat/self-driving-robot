import unittest

from arduino.hardware_contract import (
    ArduinoHardwareConfigError,
    config_fingerprint,
    load_hardware_config,
)


class HardwareContractTests(unittest.TestCase):
    def valid_config(self):
        return {
            "schema_version": 1,
            "config_id": "test",
            "firmware": {"id": "main_configurable_v1", "protocol": 1},
            "board": "mega2560",
            "modules": [
                {"type": "motor", "id": 0, "pwm": 10, "dir": 12},
                {"type": "servo", "id": 0, "pin": 9, "min": 30, "max": 150, "center": 90},
                {"type": "encoder", "id": 0, "pin": 2},
                {"type": "ultrasonic", "name": "left", "trig": 4, "echo": 5},
                {"type": "ultrasonic", "name": "right", "trig": 6, "echo": 7},
            ],
        }

    def test_fingerprint_is_stable_with_default_options(self):
        import tempfile
        import json
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps(self.valid_config()), encoding="utf-8")
            config = load_hardware_config(path)
            self.assertEqual(config_fingerprint(config), config_fingerprint(config))
            self.assertEqual(config["options"]["stop_distance_cm"], 35)

    def test_duplicate_pin_is_rejected(self):
        import tempfile
        import json
        from pathlib import Path

        raw = self.valid_config()
        raw["modules"][1]["pin"] = 10

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(ArduinoHardwareConfigError):
                load_hardware_config(path)

    def test_ids_must_be_contiguous(self):
        import tempfile
        import json
        from pathlib import Path

        raw = self.valid_config()
        raw["modules"][0]["id"] = 1

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(ArduinoHardwareConfigError):
                load_hardware_config(path)


if __name__ == "__main__":
    unittest.main()
