import base_config
import json
import sys
import os
import tempfile
from unittest.mock import Mock, patch
import threading
import time
import types
import unittest

sys.path.insert(0, "python")

from arduino.arduino_connection import ArduinoConnection
from controller.pid_controller import PIDController
from traffic_sign_detector.async_detector import AsyncSignDetector
from utils.health import FaultSeverity, HealthMonitor, HealthState
from utils.json_config import _validate
from utils.runtime_metrics import RuntimeMetrics
from utils.fps import FPS
from utils.preflight import PreflightReport, _check_arduino, _check_stream_security


class ArduinoContractCliPolicyTests(unittest.TestCase):
    @staticmethod
    def _args(arduino_config=None):
        return types.SimpleNamespace(
            debug=None,
            stream=None,
            fps=None,
            performance=None,
            without_arduino=None,
            read_arduino_output=None,
            stream_control=None,
            camera_mode=None,
            camera_index=None,
            arduino_config=arduino_config,
            arduino_contract_timeout=None,
            city_lane_detector=None,
            stream_host=None,
            ml_lane_model=None,
        )

    def test_json_cannot_enable_handshake_without_explicit_cli_flag(self):
        from main import _apply_cli_overrides

        for mode in ("city", "race"):
            with self.subTest(mode=mode):
                config = types.SimpleNamespace(ARDUINO_CONFIG="stale-from-json")
                _apply_cli_overrides(config, self._args())
                self.assertIsNone(config.ARDUINO_CONFIG)

    def test_explicit_cli_path_enables_handshake(self):
        from main import _apply_cli_overrides

        config = types.SimpleNamespace(ARDUINO_CONFIG=None)
        _apply_cli_overrides(
            config,
            self._args("python/arduino_configs/mega2560_default.json"),
        )
        self.assertEqual(
            config.ARDUINO_CONFIG,
            "python/arduino_configs/mega2560_default.json",
        )


class RuntimeMetricsTests(unittest.TestCase):
    def test_runtime_metrics_records_named_pipeline_stages(self):
        metrics = RuntimeMetrics()
        metrics.record_stage("lane", 12.5)
        metrics.record_stage("sign_latency", 34.0)

        timing = metrics.snapshot()["timing"]
        self.assertEqual(timing["lane"]["count"], 1)
        self.assertEqual(timing["lane"]["p95_ms"], 12.5)
        self.assertEqual(timing["sign_latency"]["p95_ms"], 34.0)

    def test_percentile_statistics_use_nearest_rank(self):
        statistics = RuntimeMetrics._statistics(list(range(1, 101)))
        self.assertEqual(statistics["count"], 100)
        self.assertEqual(statistics["p50_ms"], 50)
        self.assertEqual(statistics["p95_ms"], 95)
        self.assertEqual(statistics["p99_ms"], 99)

    def test_processing_fps_counts_perception_cycles_not_outer_loop_iterations(self):
        metrics = types.SimpleNamespace(record_loop=Mock())
        fps = FPS(config=types.SimpleNamespace(
            runtime_metrics=metrics,
            PERFORMANCE=False,
        ))

        with patch("utils.fps.time.monotonic", side_effect=[0.0, 0.010, 0.020, 0.033]):
            fps.start()
            fps.loop_update()
            fps.loop_update()
            fps.update()

        self.assertAlmostEqual(fps.instant_fps, 1.0 / 0.033)
        self.assertEqual(fps._num_frames, 1)
        metrics.record_loop.assert_called_once()
        self.assertAlmostEqual(metrics.record_loop.call_args.args[0], 10.0)

    def test_processing_fps_clears_after_perception_stalls(self):
        fps = FPS(config=types.SimpleNamespace(runtime_metrics=None, PERFORMANCE=False))
        with patch("utils.fps.time.monotonic", side_effect=[0.0, 0.033, 1.040]):
            fps.start()
            fps.update()
            fps.loop_update()

        self.assertEqual(fps.instant_fps, 0.0)
        self.assertEqual(fps.second_fps, 0.0)

    def test_statistics_and_counters(self):
        metrics = RuntimeMetrics(window_size=3)
        metrics.record_loop(10)
        metrics.record_loop(20)
        metrics.record_loop(30)
        metrics.record_perception(11, True)
        metrics.record_perception(12, True)
        metrics.record_perception(13, True)
        metrics.record_camera(4, True)
        metrics.record_camera(9, False)
        snapshot = metrics.snapshot()
        self.assertEqual(snapshot["counters"]["frames"], 3)
        self.assertEqual(snapshot["counters"]["loop_iterations"], 3)
        self.assertEqual(snapshot["counters"]["camera_failures"], 1)
        self.assertEqual(snapshot["timing"]["loop"]["max_ms"], 30)
        self.assertEqual(snapshot["timing"]["loop"]["p50_ms"], 20)
        self.assertEqual(snapshot["timing"]["loop"]["p95_ms"], 30)
        self.assertEqual(snapshot["timing"]["loop"]["p99_ms"], 30)


class HealthTests(unittest.TestCase):
    def test_dynamic_arduino_fault(self):
        monitor = HealthMonitor()

        connection = types.SimpleNamespace(
            connected=False,
            state="DISCONNECTED",
            last_error="port unavailable",
        )
        config = types.SimpleNamespace(
            WITHOUT_ARDUINO=False,
            arduino_connection=connection,
        )

        snapshot = monitor.snapshot_runtime(config)
        self.assertEqual(snapshot["state"], HealthState.FAULT)
        self.assertEqual(
            snapshot["faults"]["arduino_serial"]["severity"],
            FaultSeverity.CRITICAL,
        )

    def test_stale_sign_result_is_suppressed_when_worker_is_intentionally_paused(self):
        monitor = HealthMonitor()
        monitor.set_lifecycle(HealthState.RUNNING)
        config = types.SimpleNamespace(
            WITHOUT_ARDUINO=True,
            MODE="race",
            RUN_LVL="MOVE",
            WITH_SIGN=True,
            sign_detector=types.SimpleNamespace(status=lambda: {
                "worker_alive": True,
                "paused": True,
                "requests_enabled": True,
                "inference_in_flight": False,
                "last_result_age_s": 30.0,
            }),
        )

        snapshot = monitor.snapshot_runtime(config)
        self.assertNotIn("sign_result_stale", snapshot["faults"])

    def test_stale_sign_result_is_reported_when_detection_is_enabled(self):
        monitor = HealthMonitor()
        monitor.set_lifecycle(HealthState.RUNNING)
        config = types.SimpleNamespace(
            WITHOUT_ARDUINO=True,
            MODE="city",
            RUN_LVL="MOVE",
            WITH_SIGN=True,
            sign_detector=types.SimpleNamespace(status=lambda: {
                "worker_alive": True,
                "paused": False,
                "requests_enabled": True,
                "inference_in_flight": False,
                "last_result_age_s": 30.0,
            }),
        )

        snapshot = monitor.snapshot_runtime(config)
        self.assertIn("sign_result_stale", snapshot["faults"])

    def test_operator_stop_suppresses_age_faults_for_inactive_pipelines(self):
        monitor = HealthMonitor()
        monitor.set_lifecycle(HealthState.RUNNING)
        config = types.SimpleNamespace(
            WITHOUT_ARDUINO=True,
            MODE="city",
            RUN_LVL="STOP",
            STREAM=False,
            DEBUG=False,
            WITH_SIGN=True,
            camera=types.SimpleNamespace(
                camera_initialized=True,
                last_capture_valid=True,
                last_capture_at=time.monotonic() - 30.0,
                consecutive_failures=0,
            ),
            runtime_metrics=types.SimpleNamespace(snapshot=lambda: {
                "last_perception_valid": True,
                "last_perception_age_ms": 30000.0,
            }),
            sign_detector=types.SimpleNamespace(status=lambda: {
                "worker_alive": True,
                "paused": False,
                "requests_enabled": True,
                "inference_in_flight": False,
                "last_result_age_s": 30.0,
            }),
        )

        snapshot = monitor.snapshot_runtime(config)
        self.assertNotIn("camera_stale", snapshot["faults"])
        self.assertNotIn("perception_stale", snapshot["faults"])
        self.assertNotIn("sign_result_stale", snapshot["faults"])

    def test_ready_without_fault(self):
        monitor = HealthMonitor()
        config = types.SimpleNamespace(WITHOUT_ARDUINO=True)
        snapshot = monitor.snapshot_runtime(config)
        self.assertEqual(snapshot["state"], HealthState.READY)


class PIDTests(unittest.TestCase):
    def test_bounds_and_reset(self):
        pid = PIDController(
            kp=1.0, ki=0.0, kd=0.1, dt=0.1,
            output_limits=(-10, 10),
            min_dt=0.01, max_dt=0.2,
        )
        self.assertLessEqual(pid.update(100, now=1.0), 10)
        self.assertGreaterEqual(pid.update(-100, now=1.1), -10)
        pid.reset()
        self.assertIsNone(pid._prev_error)
        self.assertEqual(pid._integral, 0.0)


class ConfigValidationTests(unittest.TestCase):
    def test_unknown_mode_json_key_is_warned_and_not_attached_to_config(self):
        from utils.json_config import _load_into

        with tempfile.TemporaryDirectory() as directory:
            filename = os.path.join(directory, "city.json")
            with open(filename, "w", encoding="utf-8") as handle:
                json.dump({"TYPOED_UNKNOWN_SETTING": 7, "TARGET_PROCESSING_FPS": 22.0}, handle)
            config = types.SimpleNamespace()
            with self.assertLogs("utils.json_config", level="WARNING") as logs:
                _load_into(config, filename)
            self.assertFalse(hasattr(config, "TYPOED_UNKNOWN_SETTING"))
            self.assertEqual(config.TARGET_PROCESSING_FPS, 22.0)
            self.assertIn("TYPOED_UNKNOWN_SETTING", " ".join(logs.output))

    def test_persisted_processing_rate_is_loaded_from_mode_json(self):
        from utils.json_config import _load_into

        with tempfile.TemporaryDirectory() as directory:
            filename = os.path.join(directory, "city.json")
            with open(filename, "w", encoding="utf-8") as handle:
                json.dump({"TARGET_PROCESSING_FPS": 22.0}, handle)
            config = types.SimpleNamespace()
            _load_into(config, filename)
            self.assertEqual(config.TARGET_PROCESSING_FPS, 22.0)

    def test_boolean_and_numeric_validation(self):
        self.assertIs(_validate("CAMERA_FALLBACK_TO_OPENCV", True), True)
        with self.assertRaises(ValueError):
            _validate("CAMERA_FALLBACK_TO_OPENCV", "yes")
        with self.assertRaises(ValueError):
            _validate("CONTROL_PERIOD", 0)


class PartialRuntimeConstructionCleanupTests(unittest.TestCase):
    def test_city_and_race_close_resources_when_robot_constructor_fails(self):
        import importlib

        class Resource:
            def __init__(self, label, method_name, events):
                self.label = label
                self.method_name = method_name
                self.events = events
            def close(self):
                self.events.append((self.label, "close"))
            def release(self):
                self.events.append((self.label, "release"))

        for module_name, config_name in (
            ("modes.city.city", "config_city"),
            ("modes.race.race", "config_race"),
        ):
            with self.subTest(mode=module_name):
                module = importlib.import_module(module_name)
                events = []
                config = types.SimpleNamespace(
                    sign_detector=Resource("signs", "close", events),
                    output_manager=Resource("output", "close", events),
                    camera=Resource("camera", "release", events),
                    arduino_connection=Resource("serial", "close", events),
                    robot_controller=types.SimpleNamespace(),
                )
                with patch.object(module, config_name, config), patch.object(
                    module, "Robot", side_effect=RuntimeError("constructor failure")
                ):
                    with self.assertRaisesRegex(RuntimeError, "constructor failure"):
                        module.start()

                self.assertEqual(events, [
                    ("signs", "close"), ("output", "close"),
                    ("camera", "release"), ("serial", "close"),
                ])
                for attr in (
                    "sign_detector", "output_manager", "camera", "robot_controller",
                    "arduino_connection", "encoder_odometry", "runtime_robot",
                ):
                    self.assertFalse(hasattr(config, attr), attr)


class ArduinoConnectionTests(unittest.TestCase):
    def test_disabled_transport_is_safe(self):
        original_config = base_config.CONFIG_MODULE
        base_config.CONFIG_MODULE = None
        connection = ArduinoConnection(enabled=False)
        try:
            self.assertFalse(connection.connected)
            self.assertFalse(connection.send_command("motor 100\n"))
            self.assertEqual(connection.read_command(), "")
        finally:
            connection.close()
            base_config.CONFIG_MODULE = original_config


class CityCrosswalkMarkerTests(unittest.TestCase):
    def test_crosswalk_status_handles_missing_marker_text(self):
        from modes.city.city import Robot

        self.assertEqual(
            Robot._format_crosswalk_status_text(None, "RED"),
            "RED",
        )

    def test_crosswalk_status_formats_numeric_marker_and_light(self):
        from modes.city.city import Robot

        self.assertEqual(
            Robot._format_crosswalk_status_text(5, "GREEN"),
            "5 | GREEN",
        )

    def test_crosswalk_status_omits_empty_values(self):
        from modes.city.city import Robot

        self.assertEqual(Robot._format_crosswalk_status_text(None, ""), "")
        self.assertEqual(Robot._format_crosswalk_status_text("STOP", None), "STOP")

    def test_sign_mode_uses_async_sign_handling_path(self):
        from unittest.mock import Mock, patch
        from modes.city import city as city_module

        robot = city_module.Robot.__new__(city_module.Robot)
        frame = object()
        debug_frame = object()
        annotated_frame = object()
        robot.handle_read_sign_or_tag = Mock(
            return_value=(5, True, annotated_frame, ((1, 2), (3, 4)))
        )

        with patch.object(
            city_module.config_city,
            "WITH_APRILTAG",
            False,
        ), patch.object(
            city_module.config_city,
            "WITH_SIGN",
            True,
        ):
            sign_text, result_frame = robot._process_crosswalk_marker(
                frame,
                debug_frame,
            )

        robot.handle_read_sign_or_tag.assert_called_once_with(
            frame,
            debug_frame,
        )
        self.assertEqual(sign_text, 5)
        self.assertIs(result_frame, annotated_frame)


    def test_crosswalk_apriltag_path_uses_shared_handler(self):
        from unittest.mock import Mock, patch
        from modes.city import city as city_module

        robot = city_module.Robot.__new__(city_module.Robot)
        frame = object()
        debug_frame = object()
        annotated_frame = object()
        robot.handle_read_sign_or_tag = Mock(
            return_value=(None, False, annotated_frame, None)
        )

        with patch.object(
            city_module.config_city,
            "WITH_APRILTAG",
            True,
        ), patch.object(
            city_module.config_city,
            "WITH_SIGN",
            False,
        ):
            sign_text, result_frame = robot._process_crosswalk_marker(
                frame,
                debug_frame,
            )

        robot.handle_read_sign_or_tag.assert_called_once_with(
            frame,
            debug_frame,
        )
        self.assertIsNone(sign_text)
        self.assertIs(result_frame, annotated_frame)

    def test_city_marker_handler_is_safe_when_all_markers_are_disabled(self):
        from unittest.mock import patch
        from modes.city import city as city_module

        robot = city_module.Robot.__new__(city_module.Robot)
        frame = object()
        debug_frame = object()

        with patch.object(
            city_module.config_city,
            "WITH_SIGN",
            False,
        ), patch.object(
            city_module.config_city,
            "WITH_APRILTAG",
            False,
        ):
            result = robot.handle_read_sign_or_tag(frame, debug_frame)

        self.assertEqual(result, (None, False, debug_frame, None))


class AsyncSignDetectorTests(unittest.TestCase):
    def test_worker_survives_detector_exception(self):
        processed = threading.Event()

        class FakeDetector:
            calls = 0

            def process_frame(self, frame, debug_frame=None):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("simulated inference failure")
                processed.set()
                return {"label": "ok"}

        detector = FakeDetector()
        worker = AsyncSignDetector(detector)
        try:
            worker.submit(object())
            self.assertTrue(
                self._wait(lambda: worker.status()["failures"] == 1),
                "first inference failure was not observed",
            )
            worker.submit(object())
            self.assertTrue(processed.wait(2.0))
            self.assertTrue(worker.status()["worker_alive"])
            self.assertEqual(worker.latest()[1]["label"], "ok")
        finally:
            worker.close()

    def test_manual_request_pause_is_independent_from_phase_resume(self):
        calls = []
        processed = threading.Event()

        class FakeDetector:
            def process_frame(self, frame, debug_frame=None):
                calls.append(frame)
                processed.set()
                return {"label": "ok"}

        worker = AsyncSignDetector(FakeDetector())
        try:
            worker.pause()
            worker.pause_requests()
            worker.resume()  # Phase transitions must not re-enable operator-disabled requests.

            self.assertFalse(worker.status()["requests_enabled"])
            self.assertIsNone(worker.submit("discarded-frame"))
            self.assertEqual(calls, [])

            worker.resume_requests()
            self.assertTrue(worker.status()["requests_enabled"])
            self.assertIsNotNone(worker.submit("accepted-frame"))
            self.assertTrue(processed.wait(2.0))
            self.assertEqual(calls, ["accepted-frame"])
        finally:
            worker.close()

    @staticmethod
    def _wait(predicate, timeout=2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return False



class CityRaceAprilTagFallbackTests(unittest.TestCase):
    def _assert_missing_apriltag_is_a_normal_result(self, mode):
        from unittest.mock import Mock, patch

        import numpy as np

        if mode == "city":
            from modes.city import city as mode_module

            config = mode_module.config_city
        elif mode == "race":
            from modes.race import race as mode_module

            config = mode_module.config_race
        else:
            self.fail(f"Unsupported test mode: {mode}")

        robot = mode_module.Robot.__new__(mode_module.Robot)
        robot.apriltag_detector = Mock()
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        debug_frame = frame.copy()
        robot.apriltag_detector.detect.return_value = (
            [],
            debug_frame,
            None,
            None,
        )

        with patch.object(config, "WITH_APRILTAG", True), patch.object(
            config, "WITH_SIGN", False
        ):
            result = robot.handle_read_sign_or_tag(frame, debug_frame)

        self.assertIsNone(result[0], mode)
        self.assertFalse(result[1], mode)
        self.assertIs(result[2], debug_frame, mode)
        self.assertIsNone(result[3], mode)
        robot.apriltag_detector.detect.assert_called_once()

    def test_city_mode_handles_frame_without_apriltag(self):
        self._assert_missing_apriltag_is_a_normal_result("city")

    def test_race_mode_handles_frame_without_apriltag(self):
        self._assert_missing_apriltag_is_a_normal_result("race")


class RaceLaneLossPolicyTests(unittest.TestCase):
    def test_race_lane_loss_uses_previous_servo_angle(self):
        from types import SimpleNamespace
        from modes.race.race import Robot

        robot = Robot.__new__(Robot)
        robot.control = SimpleNamespace(last_angle=116, current_angle=116)
        result = {
            "lane_type": "none",
            "perception_valid": False,
            "steering_angle": 150,
        }

        self.assertTrue(robot._hold_last_steering_if_lane_missing(result))
        self.assertEqual(result["steering_angle"], 116)
        self.assertEqual(result["lane_type"], "none")

    def test_lane_detection_available_does_not_override_new_angle(self):
        from types import SimpleNamespace
        from modes.race.race import Robot

        robot = Robot.__new__(Robot)
        robot.control = SimpleNamespace(last_angle=116, current_angle=116)
        result = {
            "lane_type": "both",
            "perception_valid": True,
            "steering_angle": 104,
        }

        self.assertFalse(robot._hold_last_steering_if_lane_missing(result))
        self.assertEqual(result["steering_angle"], 104)


class CityRaceStreamIntegrationTests(unittest.TestCase):
    def setUp(self):
        import stream

        self._stream_test_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._stream_test_directory.cleanup)
        base_dir_patch = patch.object(stream, "BASE_DIR", self._stream_test_directory.name)
        base_dir_patch.start()
        self.addCleanup(base_dir_patch.stop)
        env_patch = patch.dict(os.environ, {"STREAM_USERNAME": "", "STREAM_PASSWORD": ""})
        env_patch.start()
        self.addCleanup(env_patch.stop)
    def _assert_mode_publishes_jpeg(self, mode):
        from types import SimpleNamespace
        from unittest.mock import patch

        import cv2
        import numpy as np
        from stream import WebStreamer

        if mode == "city":
            from modes.city import city as mode_module

            config = mode_module.config_city
            stream_method = mode_module.Robot.handle_debug_stream
            stream_args = (90.0, False, "running", "None")
        elif mode == "race":
            from modes.race import race as mode_module

            config = mode_module.config_race
            stream_method = mode_module.Robot.handle_debug_stream
            stream_args = (90.0, "running", "None")
        else:
            self.fail(f"Unsupported test mode: {mode}")

        robot = mode_module.Robot.__new__(mode_module.Robot)
        robot.fps = SimpleNamespace(instant_fps=12.0, second_fps=11.0)
        robot.control = SimpleNamespace(last_angle=90.0)
        robot.last_tag = None
        robot.output = SimpleNamespace(is_recording=lambda: False)
        frame = np.full((240, 320, 3), 80, dtype=np.uint8)
        result = {"debug": {"combined": frame.copy()}}

        with patch.object(config, "STREAM", True), patch.object(
            config, "DEBUG", False
        ), patch.object(config, "TAKE_PICTURE", False), patch.object(
            config, "RECORD_VIDEO", False
        ), patch.object(config, "debug_frames_list", []), patch.object(
            config, "stream_frame_seq", 0, create=True
        ), patch.object(
            config, "stream_frame_lock", threading.RLock(), create=True
        ), patch.object(
            config, "stream_frame_timestamps", None, create=True
        ):
            stream_method(robot, result, frame, *stream_args)

            response = WebStreamer(config).app.test_client().get(
                "/video_feed_frame"
            )

            self.assertEqual(response.status_code, 200, mode)
            self.assertEqual(response.mimetype, "image/jpeg", mode)
            self.assertEqual(
                response.headers.get("X-Stream-Frame-Sequence"),
                "1",
                mode,
            )
            decoded = cv2.imdecode(
                np.frombuffer(response.data, dtype=np.uint8),
                cv2.IMREAD_COLOR,
            )
            self.assertIsNotNone(decoded, mode)
            self.assertEqual(decoded.shape, frame.shape, mode)

    def test_city_mode_publishes_new_debug_frame_to_http_stream(self):
        self._assert_mode_publishes_jpeg("city")

    def test_race_mode_publishes_new_debug_frame_to_http_stream(self):
        self._assert_mode_publishes_jpeg("race")




class ArduinoPreflightTests(unittest.TestCase):
    def test_preflight_enumerates_port_without_opening_or_resetting_board(self):
        config = types.SimpleNamespace(
            WITHOUT_ARDUINO=False,
            SERIAL_PORT="/dev/ttyUSB0",
            ARDUINO_CONFIG=None,
        )
        fake_port = types.SimpleNamespace(device="/dev/ttyUSB0")
        with patch("serial.tools.list_ports.comports", return_value=[fake_port]), patch(
            "serial.Serial"
        ) as serial_open:
            report = PreflightReport()
            _check_arduino(report, config)

        serial_open.assert_not_called()
        port_check = next(check for check in report.checks if check.name == "Arduino serial port")
        self.assertTrue(port_check.ok)
        self.assertIn("was not opened", port_check.detail)
        contract_check = next(check for check in report.checks if check.name == "Arduino firmware contract")
        self.assertFalse(contract_check.critical)
        self.assertIn("not verified by preflight", contract_check.detail)
        self.assertTrue(report.ok)

    def test_preflight_rejects_invalid_strict_hardware_profile_without_opening_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = types.SimpleNamespace(
                WITHOUT_ARDUINO=False,
                SERIAL_PORT="/dev/ttyUSB0",
                ARDUINO_CONFIG=os.path.join(tmp, "missing-profile.json"),
            )
            with patch(
                "serial.tools.list_ports.comports",
                return_value=[types.SimpleNamespace(device="/dev/ttyUSB0")],
            ), patch("serial.Serial") as serial_open:
                report = PreflightReport()
                _check_arduino(report, config)

            serial_open.assert_not_called()
            profile_check = next(check for check in report.checks if check.name == "Arduino hardware profile")
            self.assertFalse(profile_check.ok)
            self.assertFalse(report.ok)




class StreamPreflightSecurityTests(unittest.TestCase):
    def test_preflight_fails_for_remote_bind_without_credentials(self):
        config = types.SimpleNamespace(STREAM=True, STREAM_HOST="0.0.0.0")
        with patch("stream.auth_api.load_stream_credentials", return_value=(None, None)):
            report = PreflightReport()
            _check_stream_security(report, config)

        check = next(item for item in report.checks if item.name == "Stream authentication")
        self.assertFalse(check.ok)
        self.assertTrue(check.critical)
        self.assertIn("requires both STREAM_USERNAME and STREAM_PASSWORD", check.detail)

    def test_preflight_allows_local_bind_without_credentials(self):
        config = types.SimpleNamespace(STREAM=True, STREAM_HOST="127.0.0.1")
        with patch("stream.auth_api.load_stream_credentials", return_value=(None, None)):
            report = PreflightReport()
            _check_stream_security(report, config)

        check = next(item for item in report.checks if item.name == "Stream authentication")
        self.assertTrue(check.ok)
        self.assertIn("loopback-only", check.detail)
        self.assertTrue(report.ok)
if __name__ == "__main__":
    unittest.main()