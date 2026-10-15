import argparse
import contextlib
import io
import sys
import types
import unittest
from unittest.mock import patch

from main import _apply_cli_overrides
from utils.parser import parse_args


class CliConfigPrecedenceTests(unittest.TestCase):
    def test_target_fps_default_and_explicit_values_propagate(self):
        self.assertEqual(parse_args([]).target_fps, 30.0)
        config = types.SimpleNamespace()
        args = parse_args(["--mode", "race", "--target-fps", "25"])
        _apply_cli_overrides(config, args)
        self.assertEqual(config.TARGET_PROCESSING_FPS, 25.0)

        for target in (20, 15):
            args = parse_args(["--target-fps", str(target)])
            _apply_cli_overrides(config, args)
            self.assertEqual(config.TARGET_PROCESSING_FPS, float(target))

    def test_target_fps_rejects_invalid_values(self):
        for target in ("0", "-1", "nan", "inf", "-inf", "bad"):
            with self.subTest(target=target), self.assertRaises(SystemExit):
                parse_args(["--target-fps", target])

    def test_help_describes_processing_rate_and_camera_distinction(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as caught:
            parse_args(["--help"])
        self.assertEqual(caught.exception.code, 0)
        help_text = " ".join(output.getvalue().split())
        self.assertIn("vision-processing cycles", help_text)
        self.assertIn("does not set camera FPS", help_text)
        self.assertIn("default: 30", help_text)

    def test_absent_override_flags_do_not_change_config(self):
        with patch.object(sys, "argv", ["main.py"]):
            args = parse_args()

        self.assertIsNone(args.debug)
        self.assertFalse(args.stream)
        self.assertIsNone(args.camera_mode)
        self.assertIsNone(args.camera_index)
        self.assertIsNone(args.arduino_config)

    def test_explicit_flags_are_recorded(self):
        with patch.object(
            sys,
            "argv",
            [
                "main.py",
                "--debug",
                "--camera-mode",
                "webcam",
                "--camera-index",
                "2",
                "--arduino-config",
                "profile.json",
            ],
        ):
            args = parse_args()

        self.assertTrue(args.debug)
        self.assertEqual(args.camera_mode, "webcam")
        self.assertEqual(args.camera_index, 2)
        self.assertEqual(args.arduino_config, "profile.json")

    def test_stream_is_disabled_unless_flag_is_supplied(self):
        for mode in ("city", "race"):
            with self.subTest(mode=mode):
                # Simulate a mode/JSON configuration that previously enabled
                # the stream by default.
                config = types.SimpleNamespace(STREAM=True)
                with patch.object(sys, "argv", ["main.py", "--mode", mode]):
                    args = parse_args()
                self.assertFalse(args.stream)
                _apply_cli_overrides(config, args)
                self.assertFalse(config.STREAM)

                # Passing --stream is the explicit opt-in in both modes.
                config.STREAM = False
                with patch.object(
                    sys,
                    "argv",
                    ["main.py", "--mode", mode, "--stream"],
                ):
                    args = parse_args()
                self.assertTrue(args.stream)
                _apply_cli_overrides(config, args)
                self.assertTrue(config.STREAM)

    def test_only_explicit_values_override_json_values(self):
        config = types.SimpleNamespace(
            DEBUG=True,
            STREAM=True,
            SHOW_FPS=False,
            PERFORMANCE=False,
            WITHOUT_ARDUINO=False,
            READ_ARDUINO_OUTPUT=False,
            STREAM_ALLOW_CONTROL=False,
            CAMERA_MODE="picam",
            USBCAM_ADDR=0,
            ARDUINO_CONFIG=None,
            ARDUINO_CONTRACT_TIMEOUT=3.0,
        )
        args = types.SimpleNamespace(
            debug=None,
            stream=None,
            fps=None,
            performance=True,
            without_arduino=None,
            read_arduino_output=None,
            stream_control=None,
            camera_mode="webcam",
            camera_index=2,
            arduino_config="robot.json",
            arduino_contract_timeout=5.0,
            ml_lane_model=None,
        )

        _apply_cli_overrides(config, args)

        self.assertTrue(config.DEBUG)
        self.assertTrue(config.STREAM)
        self.assertTrue(config.PERFORMANCE)
        self.assertEqual(config.CAMERA_MODE, "webcam")
        self.assertEqual(config.USBCAM_ADDR, 2)
        self.assertEqual(config.ARDUINO_CONFIG, "robot.json")
        self.assertEqual(config.ARDUINO_CONTRACT_TIMEOUT, 5.0)


if __name__ == "__main__":
    unittest.main()
