import threading
import time
import unittest
from unittest.mock import patch

import sys
sys.path.insert(0, "python")

from arduino.arduino_connection import ArduinoConnection


class FakeSerial:
    def __init__(self, fail_safe_state=False):
        self.is_open = True
        self.writes = []
        self.in_waiting = 0
        self.fail_safe_state = fail_safe_state

    def write(self, data):
        if self.fail_safe_state:
            self.fail_safe_state = False
            raise OSError("simulated safe-state failure")
        self.writes.append(data)
        return len(data)

    def flush(self):
        return None

    def read(self, size):
        return b""

    def close(self):
        self.is_open = False


class ArduinoReconnectTests(unittest.TestCase):
    def test_retries_repeated_open_failures_without_new_commands(self):
        attempts = []
        fake = FakeSerial()

        def serial_factory(*_args, **_kwargs):
            attempts.append(time.monotonic())
            if len(attempts) <= 3:
                raise OSError("simulated open failure")
            return fake

        with patch(
            "arduino.arduino_connection.serial.SerialException", OSError, create=True
        ), patch(
            "arduino.arduino_connection.serial.Serial",
            side_effect=serial_factory,
            create=True,
        ):
            connection = ArduinoConnection(
                reboot_wait=0,
                reconnect_interval=0.05,
                max_retries=2,
                heartbeat_interval=1,
            )
            try:
                self.assertTrue(connection.wait_until_connected(2.0))
                self.assertEqual(len(attempts), 4)
                self.assertEqual(connection.state, ArduinoConnection.CONNECTED)
                # No send_command() call is made after construction/initial request.
                self.assertEqual(fake.writes, [b"stop\n", b"servo 95\n"])
            finally:
                connection.close.__wrapped__(connection)

        intervals = [later - earlier for earlier, later in zip(attempts, attempts[1:])]
        self.assertGreaterEqual(intervals[0], 0.035)
        self.assertGreaterEqual(intervals[1], 0.15)
        self.assertLess(max(intervals), 0.7)

    def test_safe_state_failure_is_retried_before_connection_is_exposed(self):
        attempts = []
        serials = [FakeSerial(fail_safe_state=True), FakeSerial()]

        def serial_factory(*_args, **_kwargs):
            attempts.append(time.monotonic())
            return serials[min(len(attempts) - 1, len(serials) - 1)]

        with patch(
            "arduino.arduino_connection.serial.SerialException", OSError, create=True
        ), patch(
            "arduino.arduino_connection.serial.Serial",
            side_effect=serial_factory,
            create=True,
        ):
            connection = ArduinoConnection(
                reboot_wait=0,
                reconnect_interval=0.05,
                max_retries=3,
                heartbeat_interval=1,
            )
            try:
                self.assertTrue(connection.wait_until_connected(1.0))
                self.assertEqual(len(attempts), 2)
                self.assertFalse(serials[0].is_open)
                self.assertEqual(serials[1].writes, [b"stop\n", b"servo 95\n"])
            finally:
                connection.close.__wrapped__(connection)

    def test_close_interrupts_retry_backoff_and_joins_worker(self):
        attempted = threading.Event()

        def serial_factory(*_args, **_kwargs):
            attempted.set()
            raise OSError("simulated unavailable device")

        with patch(
            "arduino.arduino_connection.serial.SerialException", OSError, create=True
        ), patch(
            "arduino.arduino_connection.serial.Serial",
            side_effect=serial_factory,
            create=True,
        ):
            connection = ArduinoConnection(
                reboot_wait=0,
                reconnect_interval=0.5,
                max_retries=1,
                heartbeat_interval=1,
            )
            self.assertTrue(attempted.wait(1.0))
            deadline = time.monotonic() + 1.0
            while connection.last_error is None and time.monotonic() < deadline:
                time.sleep(0.001)
            self.assertIsNotNone(connection.last_error)
            worker = connection._reconnect_thread
            started = time.monotonic()
            # Exercise the close implementation on Windows too; the public
            # decorator intentionally disables serial operations on that OS.
            connection.close.__wrapped__(connection)

        self.assertLess(time.monotonic() - started, 0.5)
        self.assertFalse(worker.is_alive())
        self.assertIsNone(connection.serial_connection)
        self.assertEqual(connection.state, ArduinoConnection.DISCONNECTED)


if __name__ == "__main__":
    unittest.main()
