import base_config
import sys
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


class RuntimeMetricsTests(unittest.TestCase):
    def test_statistics_and_counters(self):
        metrics = RuntimeMetrics(window_size=3)
        metrics.record_loop(10)
        metrics.record_loop(20)
        metrics.record_loop(30)
        metrics.record_camera(4, True)
        metrics.record_camera(9, False)
        snapshot = metrics.snapshot()
        self.assertEqual(snapshot["counters"]["frames"], 3)
        self.assertEqual(snapshot["counters"]["camera_failures"], 1)
        self.assertEqual(snapshot["timing"]["loop"]["max_ms"], 30)
        self.assertEqual(snapshot["timing"]["loop"]["p95_ms"], 30)


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
    def test_boolean_and_numeric_validation(self):
        self.assertIs(_validate("CAMERA_FALLBACK_TO_OPENCV", True), True)
        with self.assertRaises(ValueError):
            _validate("CAMERA_FALLBACK_TO_OPENCV", "yes")
        with self.assertRaises(ValueError):
            _validate("CONTROL_PERIOD", 0)


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


class CityRaceStreamIntegrationTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()