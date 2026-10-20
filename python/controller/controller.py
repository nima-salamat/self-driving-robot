import logging
import time
from arduino.arduino_connection import ArduinoConnection
from arduino.hardware_contract import (
    ArduinoHardwareConfigError,
    perform_hardware_handshake,
)
from controller.pid_controller import PIDController
from controller.motion_history import MotionHistory

logger = logging.getLogger(__name__)


class RobotController:
    def __init__(self, config=None):
        if config is None:
            raise ValueError("Config must be provided during the first initialization of RobotController.")
            
        self.config = config
        self.motion_inhibited = False
        self.motion_inhibit_reason = None

        mode = getattr(self.config, 'MODE', 'unknown')
        print(f"Mode: {mode}")
        
        kp = getattr(self.config, 'KP', 1.0)
        ki = getattr(self.config, 'KI', 0.0)
        kd = getattr(self.config, 'KD', 0.0)
        kt = getattr(self.config, 'KT', 0.0)
        output_limits = getattr(self.config, 'OUTPUT_LIMITS', (-255, 255))
        
        self.min_servo_angle = getattr(self.config, 'MIN_SERVO_ANGLE', 0)
        self.max_servo_angle = getattr(self.config, 'MAX_SERVO_ANGLE', 180)
        self.servo_center = getattr(self.config, 'SERVO_CENTER', 95)
        self.servo_direction = getattr(self.config, 'SERVO_DIRECTION', 'ltr')

        self.without_arduino = bool(getattr(self.config, "WITHOUT_ARDUINO", False))
        self.connection = ArduinoConnection(
            port=getattr(self.config, "SERIAL_PORT", "/dev/ttyUSB0"),
            baudrate=getattr(self.config, "BAUD_RATE", 115200),
            timeout=getattr(self.config, "SERIAL_TIMEOUT", 0.1),
            max_retries=getattr(self.config, "SERIAL_MAX_RETRIES", 3),
            reboot_wait=getattr(self.config, "SERIAL_REBOOT_WAIT", 2.0),
            reconnect_interval=getattr(self.config, "SERIAL_RECONNECT_INTERVAL", 0.5),
            reconnect_timeout=getattr(self.config, "SERIAL_RECONNECT_TIMEOUT", 0.5),
            telemetry_enabled=True,
            telemetry_buffer_size=getattr(self.config, "SERIAL_TELEMETRY_BUFFER_SIZE", 100),
            heartbeat_interval=getattr(self.config, "HOST_HEARTBEAT_INTERVAL", 0.1),
            servo_center=int(getattr(self.config, "SERVO_CENTER", 95)),
            enabled=not self.without_arduino,
            automatic_commands_enabled=bool(
                getattr(self.config, "SEND_AUTOMATIC_ARDUINO_COMMANDS", True)
            ),
        )
        self.connection.set_print_telemetry(
            bool(getattr(self.config, "READ_ARDUINO_OUTPUT", False))
        )
        contract_path = getattr(self.config, "ARDUINO_CONFIG", None)
        if not self.without_arduino:
            startup_wait = max(0.0, float(getattr(self.config, "SERIAL_STARTUP_WAIT", 3.0)))
            if contract_path:
                if not self.connection.wait_until_connected(startup_wait):
                    raise ArduinoHardwareConfigError(
                        "Arduino did not connect before the strict hardware contract startup deadline"
                    )
                report = perform_hardware_handshake(
                    self.connection,
                    contract_path,
                    timeout=getattr(self.config, "ARDUINO_CONTRACT_TIMEOUT", 3.0),
                )
                self._arduino_contract_ready = True
                print(
                    "[Arduino contract] OK "
                    f"firmware={report['firmware_id']} "
                    f"protocol={report['protocol']} "
                    f"board={report['board']} "
                    f"config={report['config_id']} "
                    f"fingerprint={report['fingerprint']}"
                )
            elif startup_wait and not self.connection.wait_until_connected(startup_wait):
                print("Arduino not connected during startup; recovery continues in background.")
        self.current_angle = self.servo_center
        self.current_speed = 0
        # Refresh steady motor commands because firmware may discard input during pulse motion.
        self._last_motor_command_at = None
        self.pid = PIDController(
            kp,
            ki,
            kd,
            kt,
            output_limits=output_limits,
            min_dt=getattr(self.config, "PID_MIN_DT", 0.001),
            max_dt=getattr(self.config, "PID_MAX_DT", 0.2),
            derivative_filter=getattr(self.config, "PID_DERIVATIVE_FILTER", 0.25),
        )
        
        setattr(self.config, "robot_controller", self)
        setattr(self.config, "arduino_connection", self.connection)

        self.last_angle = self.servo_center
        self.current_angle = self.servo_center
        self._last_connection_state = bool(self.connection.connected)
        self.command_sequence = 0
        self._encoder_telemetry_ready = False
        self._adaptive_mode_ready = False
        self._telemetry_parse_failures = 0
        self.last_command = None
        self._arduino_contract_ready = not bool(getattr(self.config, "ARDUINO_CONFIG", None))
        self.motion_history = MotionHistory(
            max_pulses=getattr(self.config, "MOTION_HISTORY_MAX_PULSES", 200),
            max_events=getattr(self.config, "MOTION_HISTORY_MAX_EVENTS", 128),
        )
        setattr(self.config, "motion_history", self.motion_history)

    def encoder_telemetry(self, limit=5):
        """Return newest valid ODOM1 status records and receive timestamps."""
        records = self.connection.telemetry_records(limit=limit)
        parsed = []
        for record in records:
            sample = self.parse_status_line(record["line"])
            if sample is not None:
                sample["received_at"] = record["received_at"]
                parsed.append(sample)
        return parsed

    def request_encoder_telemetry(self, timeout=2.0):
        if self.without_arduino or not self.connection.connected:
            return False
        started = time.monotonic()
        self._encoder_telemetry_ready = False
        if not self._send_command("encoder telemetry on"):
            return False
        deadline = time.monotonic() + max(0.0, float(timeout))
        while time.monotonic() < deadline:
            if any(record["received_at"] >= started and
                   "ENCODER TELEMETRY ODOM1 ON" in record["line"]
                   for record in self.connection.telemetry_records()):
                self._encoder_telemetry_ready = True
                return True
            time.sleep(0.01)
        return False

    def request_adaptive_lane_mode(self, emergency_distance_cm, timeout=2.0):
        if self.without_arduino or not self.connection.connected:
            return False
        threshold = int(round(float(emergency_distance_cm)))
        if not 1 <= threshold <= 34:
            return False
        started = time.monotonic()
        self._adaptive_mode_ready = False
        if not self._send_command(f"lane adaptive {threshold}"):
            return False
        deadline = time.monotonic() + max(0.0, float(timeout))
        while time.monotonic() < deadline:
            lines = [record["line"] for record in self.connection.telemetry_records()
                     if record["received_at"] >= started]
            if any("LANE ADAPTIVE REJECTED" in line for line in lines):
                return False
            if any("LANE ADAPTIVE ACK" in line for line in lines):
                self._adaptive_mode_ready = True
                return True
            time.sleep(0.01)
        return False

    def adaptive_emergency_release(self, timeout=2.0):
        if not self._send_command("lane adaptive release"):
            return False
        deadline = time.monotonic() + max(0.0, float(timeout))
        while time.monotonic() < deadline:
            lines = self.connection.telemetry_snapshot()
            if any("LANE ADAPTIVE RELEASE REJECTED" in line for line in lines):
                return False
            if any("LANE ADAPTIVE RELEASE ACK" in line for line in lines):
                return True
            time.sleep(0.01)
        return False

    @staticmethod
    def parse_status_line(line):
        fields = str(line).split()
        if len(fields) < 7:
            return None
        try:
            base = {
                "lane": fields[0], "motor_status": fields[1],
                "right_ultrasonic_dist": float(fields[2]),
                "left_ultrasonic_dist": float(fields[3]),
                "side_ultrasonic_dist": float(fields[4]),
                "arduino_fps": int(fields[5]),
                "doing_hardcode": fields[6] == "1",
            }
        except (ValueError, OverflowError):
            return None
        if len(fields) == 7:
            base["extended"] = False
            return base
        if len(fields) == 8 and fields[7].startswith("ODOM"):
            # Firmware transition/reply lines can be interleaved with status;
            # only ODOM1 records are accepted as encoder samples.
            return None
        # ODOM1 fields: cumulative signed pulses, raw count, servo command,
        # epoch, front-valid, front-sequence, front-age-ms, rear-left-valid,
        # rear-left-sequence, rear-left-age-ms.
        if len(fields) != 18 or fields[7] != "ODOM1":
            return None
        try:
            base.update({
                "extended": True,
                "signed_pulses": int(fields[8]), "raw_count": int(fields[9]),
                "servo": int(fields[10]), "epoch": int(fields[11]),
                "front_valid": fields[12] == "1", "front_sequence": int(fields[13]),
                "front_age_ms": int(fields[14]),
                "side_valid": fields[15] == "1", "side_sequence": int(fields[16]),
                "side_age_ms": int(fields[17]),
            })
        except (ValueError, OverflowError):
            return None
        # Encoder/path validity is independent of range-sensor echo validity.
        base["valid"] = True
        return base

    def record_event(self, event, metadata=None):
        self.motion_history.record_event(event, metadata=metadata)

    def set_motion_inhibited(self, inhibited, reason=None):
        """Latch actuator commands off until an explicit successful release."""
        inhibited = bool(inhibited)
        reason = str(reason or "traffic_stop")

        if inhibited:
            if not self.motion_inhibited:
                self.current_speed = 0
                self._last_motor_command_at = None
                self.pid.reset()
            self.motion_inhibited = True
            self.motion_inhibit_reason = reason
            return True

        if not self.motion_inhibited:
            return True

        # Send the existing explicit release command before clearing the Python
        # gate. A successful serial write does not confirm MCU acceptance.
        if not self.without_arduino:
            if not self._send_command(
                "motion enable",
                event="motion_inhibit_released",
                metadata={"reason": reason},
                allow_while_inhibited=True,
            ):
                return False

        self.motion_inhibited = False
        self.motion_inhibit_reason = None
        self.current_speed = 0
        self._last_motor_command_at = None
        self.pid.reset()
        return True

    def configure_lane_sequences(
        self,
        left_sequence: str,
        right_sequence: str,
        *,
        persist: bool = False,
        command_delay_s: float = 0.4,
    ) -> bool:
        """Send hardcoded lane sequences using the ordinary SET serial protocol."""
        if self.without_arduino:
            return False

        wait_s = max(
            0.0,
            float(getattr(self.config, "SERIAL_STARTUP_WAIT", 3.0)),
        )
        if not self.connection.connected and not self.connection.wait_until_connected(wait_s):
            logger.error("Cannot configure hardcoded lane sequences: Arduino is not connected.")
            return False

        commands = [
            ("lane manual", None, None),
            (
                f"set left {left_sequence.strip()}",
                "hardcode_lane_change_configured",
                {"side": "left"},
            ),
            (
                f"set right {right_sequence.strip()}",
                "hardcode_lane_change_configured",
                {"side": "right"},
            ),
        ]
        if persist:
            commands.append(("save", "hardcode_lane_change_saved", None))

        for command, event, metadata in commands:
            if not self._send_command(command, event=event, metadata=metadata):
                logger.error(
                    "Failed to send Arduino lane configuration command %r; "
                    "automatic lane changing remains disabled.",
                    command,
                )
                return False
            if command_delay_s > 0:
                time.sleep(command_delay_s)

        if not self._send_command("lane auto"):
            logger.error("Lane sequences were sent, but lane auto failed.")
            return False
        return True

    def _send_command(
        self,
        cmd: str,
        *,
        event=None,
        record_motion=False,
        metadata=None,
        allow_while_inhibited=False,
    ):
        command = cmd.strip()
        if (
            self.motion_inhibited
            and command.lower() != "stop"
            and not allow_while_inhibited
        ):
            # Record the local rejection, but do not touch the serial transport.
            now = time.monotonic()
            self.command_sequence += 1
            self.last_command = {
                "sequence": self.command_sequence,
                "command": command,
                "success": False,
                "blocked": True,
                "blocked_reason": self.motion_inhibit_reason,
                "generated_at": now,
                "transmitted_at": None,
                "latency_ms": 0.0,
            }
            return False

        started = time.monotonic()
        success = self.connection.send_command(command + "\n")
        finished = time.monotonic()

        metrics = getattr(self.config, "runtime_metrics", None)
        if metrics is not None:
            metrics.record_serial((finished - started) * 1000.0, success)

        self.command_sequence += 1
        self.last_command = {
            "sequence": self.command_sequence,
            "command": command,
            "success": bool(success),
            "generated_at": started,
            "transmitted_at": finished if success else None,
            "latency_ms": (finished - started) * 1000.0,
        }

        if success and event is not None:
            self.motion_history.record_event(
                event,
                metadata={
                    "command": command,
                    **dict(metadata or {}),
                },
            )

        if success and record_motion:
            self.motion_history.record_pulse_command(
                command,
                event=event or "pulse_command",
                metadata=metadata,
            )

        return success

    def _sync_connection_state(self):
        connected = bool(self.connection.connected)
        if connected != self._last_connection_state:
            had_connection = bool(self._last_connection_state)
            odometry = getattr(self.config, "encoder_odometry", None)
            if odometry is not None:
                odometry.mark_discontinuity(
                    "serial reconnect/loss; physical motion during outage is unknown"
                )
            self.last_angle = None
            self.current_angle = None
            self.current_speed = 0
            self._last_motor_command_at = None
            self.pid.reset()
            self._last_connection_state = connected
            if had_connection and connected:
                self._connection_reestablished = True

            if not connected:
                self._arduino_contract_ready = not bool(
                    getattr(self.config, "ARDUINO_CONFIG", None)
                )
                self._adaptive_mode_ready = False
                self._encoder_telemetry_ready = False

        if connected and not self._arduino_contract_ready:
            contract_path = getattr(self.config, "ARDUINO_CONFIG", None)
            if contract_path:
                perform_hardware_handshake(
                    self.connection,
                    contract_path,
                    timeout=getattr(self.config, "ARDUINO_CONTRACT_TIMEOUT", 3.0),
                )
                self._arduino_contract_ready = True
        if connected and getattr(self.config, "ADAPTIVE_OBSTACLE_AVOIDANCE_ENABLED", False) and not getattr(self, "_adaptive_mode_ready", False):
            self._adaptive_mode_ready = self.request_adaptive_lane_mode(
                getattr(self.config, "OBSTACLE_STOP_DISTANCE_CM", 4.0)
            )
            if self._adaptive_mode_ready:
                self.config.adaptive_reconnected = True
        if connected and (getattr(self.config, "ENCODER_MAP_ENABLED", False) or
                          getattr(self.config, "ADAPTIVE_OBSTACLE_AVOIDANCE_ENABLED", False)) and not getattr(self, "_encoder_telemetry_ready", False):
            self._encoder_telemetry_ready = self.request_encoder_telemetry()
        if connected and (getattr(self.config, "ENCODER_MAP_ENABLED", False) or
                          getattr(self.config, "ADAPTIVE_OBSTACLE_AVOIDANCE_ENABLED", False)) and not self._encoder_telemetry_ready:
            raise RuntimeError("Encoder telemetry ODOM1 was not acknowledged after serial reconnect")
        if connected and getattr(self.config, "ADAPTIVE_OBSTACLE_AVOIDANCE_ENABLED", False) and not self._adaptive_mode_ready:
            raise RuntimeError("Adaptive lane mode was not acknowledged after serial reconnect")

    def hardware_ready(self):
        return self.without_arduino or self.connection.connected

    def servo(self, angle: int):
        if self.motion_inhibited:
            return False
        if angle < self.min_servo_angle:
            angle = self.min_servo_angle
        elif angle > self.max_servo_angle:
            angle = self.max_servo_angle

        return self._send_command(f"servo {angle}")

    def motor(self, speed: int):
        if self.motion_inhibited:
            return False
        self._sync_connection_state()
        if speed > 255:
            speed = 255
        elif speed < -255:
            speed = -255

        if speed != 0 and not self.without_arduino and not self.connection.connected:
            self.connection.send_command("stop\n")
            self.current_speed = 0
            self._last_motor_command_at = None
            return False

        now = time.monotonic()
        refresh_interval = max(
            0.0,
            float(getattr(self.config, "MOTOR_COMMAND_REFRESH_INTERVAL", 0.1)),
        )
        if (
            self.current_speed == speed
            and self._last_motor_command_at is not None
            and now - self._last_motor_command_at < refresh_interval
        ):
            return True

        success = self._send_command(f"motor {speed}")
        if success:
            self.current_speed = speed
            self._last_motor_command_at = time.monotonic()
        else:
            # Do not cache a command as applied when the serial transport failed.
            self.current_speed = 0
            self._last_motor_command_at = None
        return success

    def stop(self, reason=None):
        """Stop the robot and optionally record a semantic stop event."""
        self._sync_connection_state()
        self.current_speed = 0
        self._last_motor_command_at = None
        self.pid.reset()
        if reason is not None:
            self.record_event(
                "stop",
                {"reason": str(reason), "angle": self.current_angle},
            )
        return self._send_command("stop")

    def set_angle(self, angle: int):
        if self.motion_inhibited:
            return False
        self._sync_connection_state()
        angle = max(self.min_servo_angle, min(self.max_servo_angle, angle))
        if self.last_angle == angle:
            return True

        success = self.servo(angle)
        if success:
            self.last_angle = angle
            self.current_angle = angle
        else:
            self.last_angle = None
            self.current_angle = None
        return success
    
    def set_speed(self, speed: int):
        self.motor(speed)
    
    def forward(self, speed: int = None):
        if speed is None:
            speed = self.current_speed if self.current_speed > 0 else 150
        self.motor(abs(speed))
    
    def backward(self, speed: int = None):
        if speed is None:
            speed = self.current_speed if self.current_speed < 0 else -150
        self.motor(-abs(speed))
        
    def forward_pulse(self, s, event="forward_pulse", metadata=None):
        if self.motion_inhibited:
            return False
        return self._send_command(
            s,
            event=event,
            record_motion=True,
            metadata=metadata,
        )
    
    def backward_pulse(self, s, event="backward_pulse", metadata=None):
        if self.motion_inhibited:
            return False
        return self._send_command(
            s,
            event=event,
            record_motion=True,
            metadata=metadata,
        )
        
    def read(self):
        """
            read data from arduino . . . 
        """
        command = self.connection.read_command().strip()
        if not command:
            return {}

        commands = command.split()
        return self.parse_status_line(command) or {}
    
    def update_kp(self, kp):
        self.pid.kp = kp

    def calculate_angle_by_error(self, error):
        if self.servo_direction == "rtl":
            steering_angle = self.servo_center - self.pid.update(error)
        else: # ltr
            steering_angle = self.servo_center + self.pid.update(error)
        
        steering_angle = int(max(self.min_servo_angle, min(self.max_servo_angle, steering_angle)))
        return steering_angle
    
    def set_angle_by_error(self, error, lane_type):
        if self.motion_inhibited:
            return False
        if lane_type == "none":
            # Do not reset the actuator to a stop just because lane pixels are
            # temporarily absent. Hold the last applied servo angle and reset
            # PID history so the next valid measurement cannot cause a spike.
            self.pid.reset()
            held_angle = self.last_angle
            if held_angle is None:
                held_angle = self.current_angle
            if held_angle is None:
                held_angle = self.servo_center
            return self.set_angle(held_angle)
        return self.set_angle(self.calculate_angle_by_error(error))

    def signal_left(self):
        self._send_command("left")

    def signal_right(self):
        self._send_command("right")
