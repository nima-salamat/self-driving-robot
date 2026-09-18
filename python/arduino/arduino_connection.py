import logging
import serial
import threading
import time
from collections import deque

from utils.decorators import if_is_not_windows

logger = logging.getLogger(__name__)


class ArduinoConnection:
    """Thread-safe serial transport with asynchronous recovery and telemetry draining."""

    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    RECONNECTING = "RECONNECTING"

    def __init__(
        self,
        port="/dev/ttyUSB0",
        baudrate=115200,
        timeout=0.1,
        max_retries=3,
        reboot_wait=2.0,
        reconnect_interval=0.5,
        reconnect_timeout=0.5,
        telemetry_enabled=True,
        telemetry_buffer_size=100,
        command_write_timeout=0.1,
        enabled=True,
    ):
        self.port = port
        self.baudrate = baudrate
        self.timeout = max(0.01, float(timeout))
        self.max_retries = max(1, int(max_retries))
        self.reboot_wait = max(0.0, float(reboot_wait))
        self.reconnect_interval = max(0.05, float(reconnect_interval))
        self.reconnect_timeout = max(0.05, float(reconnect_timeout))
        self.command_write_timeout = max(0.01, float(command_write_timeout))
        self.enabled = bool(enabled)

        self.serial_connection = None
        self._state = self.DISCONNECTED
        self._state_lock = threading.RLock()
        self._serial_lock = threading.RLock()
        self._reconnect_lock = threading.Lock()
        self._reconnect_requested = threading.Event()
        self._stop_event = threading.Event()
        self._connected_event = threading.Event()
        self._reader_thread = None
        self._reconnect_thread = None
        self._telemetry_thread_started = False
        self._rx_buffer = bytearray()
        self._telemetry = deque(maxlen=max(1, int(telemetry_buffer_size)))
        self._telemetry_lock = threading.Lock()
        self._telemetry_enabled = bool(telemetry_enabled)
        self._print_telemetry = False
        self._last_error = None

        if self.enabled:
            self._reconnect_thread = threading.Thread(
                target=self._reconnect_worker,
                name="arduino-reconnect",
                daemon=True,
            )
            self._reconnect_thread.start()
            self._request_reconnect()

    @property
    def state(self):
        with self._state_lock:
            return self._state

    @property
    def connected(self):
        return self.state == self.CONNECTED

    @property
    def last_error(self):
        with self._state_lock:
            return self._last_error

    def set_print_telemetry(self, enabled):
        self._print_telemetry = bool(enabled)

    def telemetry_snapshot(self, limit=None):
        with self._telemetry_lock:
            lines = list(self._telemetry)
        if limit is not None:
            limit = max(0, int(limit))
            lines = lines[-limit:] if limit else []
        return lines

    def telemetry_status(self, limit=50):
        return {
            "enabled": self._telemetry_enabled,
            "connected": self.connected,
            "state": self.state,
            "lines": self.telemetry_snapshot(limit),
        }

    def _set_state(self, state, error=None):
        with self._state_lock:
            self._state = state
            self._last_error = str(error) if error else None
        if state == self.CONNECTED:
            self._connected_event.set()
        else:
            self._connected_event.clear()

    def _request_reconnect(self):
        if not self.enabled or self._stop_event.is_set():
            return
        self._reconnect_requested.set()

    def wait_until_connected(self, timeout):
        if not self.enabled:
            return False
        return self._connected_event.wait(max(0.0, float(timeout)))

    def _open_serial(self):
        if self._stop_event.is_set():
            return False

        self._set_state(self.RECONNECTING)
        try:
            with self._serial_lock:
                old = self.serial_connection
                if old is not None:
                    try:
                        old.close()
                    except Exception:
                        pass
                    self.serial_connection = None

                connection = serial.Serial(
                    self.port,
                    self.baudrate,
                    timeout=self.timeout,
                    write_timeout=self.command_write_timeout,
                )
                self.serial_connection = connection

            # Opening a USB Arduino can reset the board. Preserve the existing
            # reboot delay, but keep it entirely inside the recovery worker.
            if self.reboot_wait:
                deadline = time.monotonic() + self.reboot_wait
                while not self._stop_event.is_set() and time.monotonic() < deadline:
                    time.sleep(min(0.05, deadline - time.monotonic()))

            self._set_state(self.CONNECTED)
            logger.info("Arduino serial connected: %s @ %s", self.port, self.baudrate)
            return True
        except (serial.SerialException, OSError) as exc:
            self.serial_connection = None
            self._set_state(self.DISCONNECTED, exc)
            return False

    def _reconnect_worker(self):
        while not self._stop_event.is_set():
            self._reconnect_requested.wait(timeout=self.reconnect_interval)
            if self._stop_event.is_set():
                break
            if not self._reconnect_requested.is_set():
                continue
            self._reconnect_requested.clear()

            with self._reconnect_lock:
                if self.connected:
                    continue
                if self._open_serial():
                    self._establish_safe_state()

    def _establish_safe_state(self):
        """Send a safe stop/center sequence before normal control resumes."""
        try:
            with self._serial_lock:
                connection = self.serial_connection
                if connection is None or not connection.is_open:
                    return False
                connection.write(b"stop\nservo 90\n")
                connection.flush()
            return True
        except Exception as exc:
            self._mark_disconnected(exc)
            return False

    def _mark_disconnected(self, error=None):
        with self._serial_lock:
            connection = self.serial_connection
            self.serial_connection = None
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
        self._set_state(self.DISCONNECTED, error)
        self._request_reconnect()

    def _reader_loop(self):
        while not self._stop_event.is_set():
            if not self.enabled:
                return

            if not self.connected:
                time.sleep(0.05)
                continue

            try:
                with self._serial_lock:
                    connection = self.serial_connection
                    waiting = connection.in_waiting if connection and connection.is_open else 0
                    if waiting <= 0:
                        data = b""
                    else:
                        # Bound each reader pass so a telemetry burst cannot monopolize
                        # this thread indefinitely.
                        data = connection.read(min(waiting, 4096))

                if data:
                    self._consume_bytes(data)
                else:
                    time.sleep(0.002)
            except (serial.SerialException, OSError) as exc:
                self._mark_disconnected(exc)
            except Exception as exc:
                logger.exception("Arduino telemetry reader failed")
                self._mark_disconnected(exc)

    def _ensure_reader_started(self):
        if self._reader_thread is None:
            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                name="arduino-telemetry",
                daemon=True,
            )
            self._reader_thread.start()

    def _consume_bytes(self, data):
        self._rx_buffer.extend(data)
        while True:
            newline = self._rx_buffer.find(b"\n")
            if newline < 0:
                if len(self._rx_buffer) > 16384:
                    self._rx_buffer.clear()
                break

            raw = bytes(self._rx_buffer[:newline])
            del self._rx_buffer[:newline + 1]
            line = raw.rstrip(b"\r").decode("utf-8", errors="replace").strip()
            if not line:
                continue

            with self._telemetry_lock:
                self._telemetry.append(line)

            if self._print_telemetry:
                print(f"[Arduino] {line}", flush=True)

    @if_is_not_windows
    def send_command(self, command):
        if not self.enabled:
            return False

        if isinstance(command, str):
            command = command.encode()

        self._ensure_reader_started()

        if not self.connected:
            self._request_reconnect()
            return False

        try:
            with self._serial_lock:
                connection = self.serial_connection
                if connection is None or not connection.is_open:
                    raise serial.SerialException("Arduino connection is not open")
                connection.write(command)
                connection.flush()
            return True
        except (serial.SerialException, OSError, TimeoutError) as exc:
            self._mark_disconnected(exc)
            return False
        except Exception as exc:
            logger.exception("Arduino command failed")
            self._mark_disconnected(exc)
            return False

    @if_is_not_windows
    def read_command(self):
        """Compatibility API: return the newest buffered telemetry line only."""
        lines = self.telemetry_snapshot(1)
        return lines[-1] if lines else ""

    @if_is_not_windows
    def close(self):
        self._stop_event.set()
        self._reconnect_requested.set()

        with self._serial_lock:
            connection = self.serial_connection
            self.serial_connection = None
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    logger.exception("Failed to close Arduino serial connection")

        for thread in (self._reader_thread, self._reconnect_thread):
            if thread and thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=1.0)

        self._set_state(self.DISCONNECTED)
