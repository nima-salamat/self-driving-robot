import serial
import threading
import time
from utils.decorators import if_is_not_windows

serial_lock = threading.Lock()


class ArduinoConnection:
    def __init__(self, port="/dev/ttyUSB0", baudrate=115200, timeout=1, max_retries=3, reboot_wait=2.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.max_retries = max_retries
        self.reboot_wait = reboot_wait
        self.serial_connection = None
        self.init_serial_connection()

    @if_is_not_windows
    def init_serial_connection(self, reopen=False):
        try:
            if reopen and self.serial_connection:
                try:
                    self.serial_connection.close()
                except:
                    pass
                time.sleep(0.2)

            self.serial_connection = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
            time.sleep(self.reboot_wait)  # allow Arduino to reboot
            return True
        except serial.SerialException:
            self.serial_connection = None
            return False

    @if_is_not_windows
    def send_command(self, command):
        if isinstance(command, str):
            command = command.encode()

        for _ in range(self.max_retries):
            try:
                with serial_lock:
                    if not self.serial_connection or not self.serial_connection.is_open:
                        if not self.init_serial_connection(reopen=True):
                            time.sleep(0.1)
                            continue
                    self.serial_connection.write(command)
                    try:
                        self.serial_connection.flush()
                    except:
                        pass
                    return True
            except Exception:
                # reopen and retry
                try:
                    self.init_serial_connection(reopen=True)
                except:
                    pass
                time.sleep(0.1)
        return False

    @if_is_not_windows
    def read_command(self):
        if self.serial_connection and self.serial_connection.is_open:
            return self.serial_connection.readline().decode("utf-8").strip()
        return ""

    @if_is_not_windows
    def close(self):
        if self.serial_connection:
            try:
                self.serial_connection.close()
            except:
                pass
