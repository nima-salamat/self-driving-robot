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
        heartbeat_interval=0.1,
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
        self.heartbeat_interval = max(0.05, float(heartbeat_interval))
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
        self._heartbeat_thread = None
        self._telemetry_thread_started = False
        self._rx_buffer = bytearray()
        self._telemetry = deque(maxlen=max(1, int(telemetry_buffer_size)))
        self._telemetry_lock = threading.Lock()
        self._telemetry_enabled = bool(telemetry_enabled)
        self._max_telemetry_line_bytes = 4096
        self._print_telemetry = False
        self._last_error = None
        self._consecutive_reconnect_failures = 0
        self._telemetry_started_at = time.monotonic()
        self._telemetry_lines_received = 0
        self._telemetry_bytes_received = 0
        self._telemetry_dropped_lines = 0
        self._last_telemetry_at = None
        self._connected_at = None

        if self.enabled:
            self._reconnect_thread = threading.Thread(
                target=self._reconnect_worker,
                name="arduino-reconnect",
                daemon=True,
            )
            self._reconnect_thread.start()
            self._ensure_reader_started()
            self._heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop,
                name="arduino-heartbeat",
                daemon=True,
            )
            self._heartbeat_thread.start()
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
        now = time.monotonic()
        with self._telemetry_lock:
            lines_received = self._telemetry_lines_received
            bytes_received = self._telemetry_bytes_received
            dropped_lines = self._telemetry_dropped_lines
            last_telemetry_at = self._last_telemetry_at
            buffered = len(self._telemetry)
        elapsed = max(0.0, now - self._telemetry_started_at)
        return {
            "enabled": self._telemetry_enabled,
            "connected": self.connected,
            "state": self.state,
            "lines": self.telemetry_snapshot(limit),
            "lines_received": lines_received,
            "bytes_received": bytes_received,
            "dropped_lines": dropped_lines,
            "buffered_lines": buffered,
            "line_rate_hz": lines_received / elapsed if elapsed > 0 else 0.0,
            "last_line_age_s": (max(0.0, now - last_telemetry_at) if last_telemetry_at is not None else None),
            "reconnect_failures": self._consecutive_reconnect_failures,
            "connected_age_s": (
                max(0.0, now - self._connected_at)
                if self._connected_at is not None
                else None
            ),
        }

    def _set_state(self, state, error=None):
        with self._state_lock:
            self._state = state
            self._last_error = str(error) if error else None
        if state == self.CONNECTED:
            self._connected_at = time.monotonic()
            self._connected_event.set()
        else:
            self._connected_at = None
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
                    timeout=min(self.timeout, self.reconnect_timeout),
                    write_timeout=self.reconnect_timeout,
                )
                self.serial_connection = connection

            # Opening a USB Arduino can reset the board. Preserve the existing
            # reboot delay, but keep it entirely inside the recovery worker.
            if self.reboot_wait:
                deadline = time.monotonic() + self.reboot_wait
                while not self._stop_event.is_set() and time.monotonic() < deadline:
                    time.sleep(min(0.05, deadline - time.monotonic()))

            if self._stop_event.is_set():
                with self._serial_lock:
                    connection = self.serial_connection
                    self.serial_connection = None
                    if connection is not None:
                        try:
                            connection.close()
                        except Exception:
                            pass
                self._set_state(self.DISCONNECTED)
                return False

            return True
        except (serial.SerialException, OSError) as exc:
            self.serial_connection = None
            self._consecutive_reconnect_failures += 1
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
                    if self._establish_safe_state():
                        self._consecutive_reconnect_failures = 0
                        self._set_state(self.CONNECTED)
                        logger.info(
                            "Arduino serial connected: %s @ %s",
                            self.port,
                            self.baudrate,
                        )
                    elif self._consecutive_reconnect_failures >= self.max_retries:
                        # Back off after repeated failures without blocking the control thread.
                        self._stop_event.wait(min(self.reconnect_interval * 4.0, 5.0))
                elif self._consecutive_reconnect_failures >= self.max_retries:
                    # Back off after repeated failures without blocking the control thread.
                    self._stop_event.wait(min(self.reconnect_interval * 4.0, 5.0))

    def _establish_safe_state(self):
        """Send a safe stop/center sequence before normal control resumes."""
        try:
            with self._serial_lock:
                connection = self.serial_connection
                if connection is None or not connection.is_open:
                    return False
                connection.write(b"stop\n")
                connection.flush()
                connection.write(b"servo 90\n")
                connection.flush()
            return True
        except Exception as exc:
            self._mark_disconnected(exc, expected_connection=self.serial_connection)
            return False

    def _mark_disconnected(self, error=None, expected_connection=None):
        with self._serial_lock:
            connection = self.serial_connection
            if expected_connection is not None and connection is not expected_connection:
                return

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
                self._mark_disconnected(exc, expected_connection=connection)
            except Exception as exc:
                logger.exception("Arduino telemetry reader failed")
                self._mark_disconnected(exc, expected_connection=connection)

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
                if len(self._rx_buffer) > self._max_telemetry_line_bytes:
                    self._rx_buffer.clear()
                    with self._telemetry_lock:
                        self._telemetry_dropped_lines += 1
                break

            if newline > self._max_telemetry_line_bytes:
                del self._rx_buffer[:newline + 1]
                with self._telemetry_lock:
                    self._telemetry_dropped_lines += 1
                continue

            raw = bytes(self._rx_buffer[:newline])
            del self._rx_buffer[:newline + 1]
            line = raw.rstrip(b"\r").decode("utf-8", errors="replace").strip()
            if not line:
                continue

            with self._telemetry_lock:
                self._telemetry_lines_received += 1
                self._telemetry_bytes_received += len(raw) + 1
                self._last_telemetry_at = time.monotonic()
                if len(self._telemetry) == self._telemetry.maxlen:
                    self._telemetry_dropped_lines += 1
                self._telemetry.append(line)

            if self._print_telemetry:
                print(f"[Arduino] {line}", flush=True)

    def _heartbeat_loop(self):
        heartbeat = b"heartbeat\n"
        while not self._stop_event.is_set():
            if self.enabled and self.connected:
                try:
                    with self._serial_lock:
                        connection = self.serial_connection
                        if connection is None or not connection.is_open:
                            raise serial.SerialException(
                                "Arduino connection is not open"
                            )
                        connection.write(heartbeat)
                        connection.flush()
                except (serial.SerialException, OSError, TimeoutError) as exc:
                    self._mark_disconnected(
                        exc,
                        expected_connection=connection,
                    )
                except Exception as exc:
                    logger.exception("Arduino heartbeat failed")
                    self._mark_disconnected(
                        exc,
                        expected_connection=connection,
                    )

            self._stop_event.wait(self.heartbeat_interval)

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
            self._mark_disconnected(exc, expected_connection=connection)
            return False
        except Exception as exc:
            logger.exception("Arduino command failed")
            self._mark_disconnected(exc, expected_connection=connection)
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

        for thread in (
            self._reader_thread,
            self._reconnect_thread,
            self._heartbeat_thread,
        ):
            if thread and thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=1.0)

        self._set_state(self.DISCONNECTED)
