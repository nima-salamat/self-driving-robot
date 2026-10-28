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
        # No CLI override must leave a JSON-persisted target rate untouched.
        self.assertIsNone(parse_args([]).target_fps)
        config = types.SimpleNamespace(TARGET_PROCESSING_FPS=22.0)
        args = parse_args(["--mode", "race"])
        _apply_cli_overrides(config, args)
        self.assertEqual(config.TARGET_PROCESSING_FPS, 22.0)

        args = parse_args(["--mode", "race", "--target-fps", "25"])
        _apply_cli_overrides(config, args)
        self.assertEqual(config.TARGET_PROCESSING_FPS, 25.0)

        for target in (20, 15):
            args = parse_args(["--target-fps", str(target)])
            _apply_cli_overrides(config, args)
            self.assertEqual(config.TARGET_PROCESSING_FPS, float(target))

    def test_race_stop_start_and_finish_require_an_enabled_marker_detector(self):
        from main import _validate_opt_in_features

        config = types.SimpleNamespace(
            WITH_SIGN=False,
            WITH_APRILTAG=False,
            SIGN_DETECTOR_METHOD="yolo",
            RACE_STOP_ABSENCE_SECONDS=1.0,
            RACE_STOP_CONFIDENCE_THRESHOLD=0.2,
            ENCODER_PULSE_DISTANCE_CM=None,
            ENCODER_WHEELBASE_CM=None,
            ENCODER_ROAD_ANGLE_MIN_DEG=None,
            ENCODER_ROAD_ANGLE_MAX_DEG=None,
        )
        for argv in (
            ["--mode", "race", "--race-start-on-stop-sign"],
            ["--mode", "race", "--race-finish-after-seconds", "10", "--race-finish-speed", "100"],
        ):
            with self.subTest(argv=argv), self.assertRaisesRegex(
                SystemExit, "requires an enabled STOP marker detector"
            ):
                _validate_opt_in_features(config, parse_args(argv))

        config.WITH_SIGN = True
        _validate_opt_in_features(
            config, parse_args(["--mode", "race", "--race-start-on-stop-sign"])
        )
        config.WITH_SIGN = False
        config.WITH_APRILTAG = True
        _validate_opt_in_features(
            config, parse_args(["--mode", "race", "--race-start-on-stop-sign"])
        )

    def test_multiprocess_camera_is_strictly_opt_in(self):
        config = types.SimpleNamespace(MULTIPROCESS_CAMERA=True)

        args = parse_args([])
        self.assertFalse(args.multiprocess_camera)
        _apply_cli_overrides(config, args)
        self.assertFalse(config.MULTIPROCESS_CAMERA)

        args = parse_args(["--multiprocess-camera"])
        self.assertTrue(args.multiprocess_camera)
        _apply_cli_overrides(config, args)
        self.assertTrue(config.MULTIPROCESS_CAMERA)

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
        self.assertIn("saved in the active mode JSON", help_text)

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

    def test_multiprocess_alias_enables_camera_and_sign_worker(self):
        for flag in ("--multiprocess-camera", "--multiprocess"):
            with self.subTest(flag=flag):
                with patch.object(sys, "argv", ["main.py", flag]):
                    args = parse_args()
                config = types.SimpleNamespace(
                    MULTIPROCESS_CAMERA=False,
                    MULTIPROCESS_SIGN_DETECTOR=False,
                )
                _apply_cli_overrides(config, args)
                self.assertTrue(args.multiprocess_camera)
                self.assertTrue(config.MULTIPROCESS_CAMERA)
                self.assertTrue(config.MULTIPROCESS_SIGN_DETECTOR)
                self.assertEqual(config.MULTIPROCESS_SIGN_INTRA_OP_THREADS, 2)

    def test_sign_threads_are_opt_in_and_require_multiprocessing(self):
        from main import _validate_opt_in_features

        args = parse_args(["--multiprocess", "--sign-intra-op-threads", "1"])
        config = types.SimpleNamespace()
        _apply_cli_overrides(config, args)
        self.assertEqual(config.MULTIPROCESS_SIGN_INTRA_OP_THREADS, 1)
        _validate_opt_in_features(config, args)

        with self.assertRaises(SystemExit):
            _validate_opt_in_features(
                config, parse_args(["--sign-intra-op-threads", "1"])
            )
        with self.assertRaises(SystemExit):
            _validate_opt_in_features(
                config, parse_args(["--multiprocess", "--sign-intra-op-threads", "0"])
            )

    def test_multiprocess_is_strictly_opt_in_even_if_config_is_true(self):
        with patch.object(sys, "argv", ["main.py"]):
            args = parse_args()
        config = types.SimpleNamespace(
            MULTIPROCESS_CAMERA=True,
            MULTIPROCESS_SIGN_DETECTOR=True,
        )
        _apply_cli_overrides(config, args)
        self.assertFalse(config.MULTIPROCESS_CAMERA)
        self.assertFalse(config.MULTIPROCESS_SIGN_DETECTOR)

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
