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

        with (
            patch.object(city_module.config_city, "WITH_APRILTAG", False),
            patch.object(city_module.config_city, "WITH_SIGN", True),
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


if __name__ == "__main__":
    unittest.main()