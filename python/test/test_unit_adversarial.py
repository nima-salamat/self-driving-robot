import threading
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, "python")

from arduino.arduino_connection import ArduinoConnection


class FakeSerial:
    def __init__(self, *args, **kwargs):
        self.is_open = True
        self.writes = []
        self.in_waiting = 0

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def flush(self):
        return None

    def read(self, size):
        return b""

    def close(self):
        self.is_open = False


class SerialAdversarialTests(unittest.TestCase):
    def test_connection_is_not_published_until_safe_state_is_complete(self):
        fake = FakeSerial()
        with patch("arduino.arduino_connection.serial.Serial", return_value=fake):
            connection = ArduinoConnection(enabled=False, reboot_wait=0)
            try:
                self.assertTrue(connection._open_serial())
                self.assertEqual(connection.state, ArduinoConnection.RECONNECTING)
                self.assertFalse(connection.connected)

                self.assertTrue(connection._establish_safe_state())
                self.assertEqual(
                    fake.writes,
                    [b"stop\n", b"servo 90\n"],
                )
                self.assertFalse(connection.connected)

                connection._set_state(ArduinoConnection.CONNECTED)
                self.assertTrue(connection.connected)
            finally:
                connection.close()

    def test_reconnect_open_aborts_when_shutdown_was_requested(self):
        fake = FakeSerial()
        with patch("arduino.arduino_connection.serial.Serial", return_value=fake):
            connection = ArduinoConnection(enabled=False, reboot_wait=0)
            try:
                connection._stop_event.set()
                self.assertFalse(connection._open_serial())
                self.assertFalse(connection.connected)
                self.assertIsNone(connection.serial_connection)
                self.assertFalse(fake.is_open)
            finally:
                connection.close()

    def test_telemetry_is_bounded_under_flood(self):
        connection = ArduinoConnection(
            enabled=False,
            telemetry_buffer_size=4,
        )
        try:
            for index in range(1000):
                connection._consume_bytes(f"line-{index}\n".encode())
            self.assertEqual(len(connection.telemetry_snapshot()), 4)
            status = connection.telemetry_status()
            self.assertEqual(status["lines_received"], 1000)
            self.assertEqual(status["buffered_lines"], 4)
            self.assertEqual(status["dropped_lines"], 996)
        finally:
            connection.close()

    def test_partial_telemetry_buffer_has_a_hard_bound(self):
        connection = ArduinoConnection(enabled=False)
        try:
            for _ in range(8):
                connection._consume_bytes(b"x" * 4096)
                self.assertLessEqual(len(connection._rx_buffer), 16384)
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()


class FakeControllerConnection:
    def __init__(self, *args, **kwargs):
        self.connected = True
        self.closed = False
        self.result = True
        self.commands = []

    def set_print_telemetry(self, enabled):
        self.print_telemetry = enabled

    def wait_until_connected(self, timeout):
        return self.connected

    def send_command(self, command):
        self.commands.append(command)
        return self.result

    def close(self):
        self.closed = True


def make_controller_config(mode="race"):
    import types
    return types.SimpleNamespace(
        MODE=mode,
        KP=1.0,
        KI=0.0,
        KD=0.1,
        KT=0.0,
        OUTPUT_LIMITS=(-80, 80),
        MIN_SERVO_ANGLE=55,
        MAX_SERVO_ANGLE=125,
        SERVO_CENTER=90,
        SERVO_DIRECTION="ltr",
        WITHOUT_ARDUINO=False,
        SERIAL_PORT="/dev/null",
        BAUD_RATE=115200,
        SERIAL_TIMEOUT=0.1,
        SERIAL_MAX_RETRIES=1,
        SERIAL_STARTUP_WAIT=0,
        SERIAL_REBOOT_WAIT=0,
        SERIAL_RECONNECT_INTERVAL=0.5,
        SERIAL_RECONNECT_TIMEOUT=0.1,
        SERIAL_TELEMETRY_BUFFER_SIZE=4,
        READ_ARDUINO_OUTPUT=False,
        PID_MIN_DT=0.001,
        PID_MAX_DT=0.2,
        PID_DERIVATIVE_FILTER=0.25,
    )


class ControllerAdversarialTests(unittest.TestCase):
    def test_failed_commands_do_not_poison_actuator_cache(self):
        from controller import controller as controller_module

        with patch.object(controller_module, "ArduinoConnection", FakeControllerConnection):
            config = make_controller_config()
            controller = controller_module.RobotController(config=config)
            controller.connection.result = False

            self.assertFalse(controller.set_angle(110))
            self.assertIsNone(controller.last_angle)
            self.assertFalse(controller.motor(150))
            self.assertEqual(controller.current_speed, 0)

    def test_reconnect_invalidates_cached_actuator_state(self):
        from controller import controller as controller_module

        with patch.object(controller_module, "ArduinoConnection", FakeControllerConnection):
            config = make_controller_config()
            controller = controller_module.RobotController(config=config)
            controller.last_angle = 110
            controller.current_speed = 150

            controller.connection.connected = False
            controller._sync_connection_state()
            self.assertIsNone(controller.last_angle)
            self.assertEqual(controller.current_speed, 0)

            controller.connection.connected = True
            controller.connection.commands.clear()
            controller.connection.result = True
            self.assertTrue(controller.set_angle(110))
            self.assertIn("servo 110\n", controller.connection.commands)

    def test_controllers_do_not_leak_configuration_between_modes(self):
        from controller import controller as controller_module

        with patch.object(controller_module, "ArduinoConnection", FakeControllerConnection):
            race = controller_module.RobotController(make_controller_config("race"))
            city = controller_module.RobotController(make_controller_config("city"))

            self.assertIsNot(race, city)
            self.assertIs(race.config.MODE, "race")
            self.assertIs(city.config.MODE, "city")
            self.assertIsNot(race.pid, city.pid)

    def test_stop_resets_pid_state(self):
        from controller import controller as controller_module

        with patch.object(controller_module, "ArduinoConnection", FakeControllerConnection):
            controller = controller_module.RobotController(make_controller_config())
            controller.pid.update(10, now=1.0)
            self.assertIsNotNone(controller.pid._prev_error)
            controller.stop()
            self.assertIsNone(controller.pid._prev_error)


class SignFreshnessAdversarialTests(unittest.TestCase):
    def test_completed_result_has_input_metadata_and_expires(self):
        from traffic_sign_detector.async_detector import AsyncSignDetector

        done = threading.Event()

        class FakeDetector:
            def process_frame(self, frame, debug_frame=None):
                done.set()
                return {"label": frame}

        worker = AsyncSignDetector(FakeDetector())
        try:
            request_id = worker.submit("frame-1")
            self.assertEqual(request_id, 1)
            self.assertTrue(done.wait(2.0))

            latest = worker.latest()
            self.assertIsNotNone(latest)
            self.assertEqual(latest[0], 1)
            self.assertEqual(latest[1]["label"], "frame-1")
            self.assertLessEqual(latest[2], latest[3])
            self.assertIsNone(worker.latest(max_age_s=0.0))
        finally:
            worker.close()


class BlockingVideoWriter:
    def __init__(self):
        self.writes = []
        self.started = threading.Event()
        self.release_event = threading.Event()
        self.is_opened = True
        self.released = False

    def isOpened(self):
        return self.is_opened

    def write(self, frame):
        self.writes.append(frame)
        self.started.set()
        self.release_event.wait(5.0)

    def release(self):
        self.released = True


class RecordingAdversarialTests(unittest.TestCase):
    def test_stop_recording_does_not_wait_for_stuck_writer(self):
        import tempfile
        import types
        from unittest.mock import patch

        from manager.output_manager import OutputManager

        with tempfile.TemporaryDirectory() as tmp:
            config = types.SimpleNamespace(
                OUTPUT_DIR=tmp,
                VIDEO_FPS=20,
                VIDEO_CODEC="mp4v",
                MIN_FREE_DISK_MB=0,
            )
            writer = BlockingVideoWriter()
            manager = OutputManager(config_module=config, output_dir=tmp)

            with patch("manager.output_manager.cv2.VideoWriter", return_value=writer):
                manager.start_recording((1, 1))
                self.assertTrue(manager.write_frame("frame-1"))
                self.assertTrue(writer.started.wait(2.0))

                started = time.monotonic()
                path = manager.stop_recording()
                elapsed = time.monotonic() - started

                self.assertIsNotNone(path)
                self.assertLess(elapsed, 0.2)
                self.assertFalse(manager.is_recording())

            writer.release_event.set()
            manager.close()
            self.assertTrue(writer.released)

    def test_full_queue_never_blocks_control_path(self):
        import tempfile
        import types
        from unittest.mock import patch

        from manager.output_manager import OutputManager

        with tempfile.TemporaryDirectory() as tmp:
            config = types.SimpleNamespace(
                OUTPUT_DIR=tmp,
                VIDEO_FPS=20,
                VIDEO_CODEC="mp4v",
                MIN_FREE_DISK_MB=0,
            )
            writer = BlockingVideoWriter()
            manager = OutputManager(config_module=config, output_dir=tmp)

            with patch("manager.output_manager.cv2.VideoWriter", return_value=writer):
                manager.start_recording((1, 1))
                self.assertTrue(manager.write_frame("frame-1"))
                self.assertTrue(writer.started.wait(2.0))

                for i in range(2, 10):
                    self.assertTrue(manager.write_frame(f"frame-{i}"))

                stats = manager.stats()
                self.assertGreater(stats["dropped_video_frames"], 0)

            writer.release_event.set()
            manager.close()
