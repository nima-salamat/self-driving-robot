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
