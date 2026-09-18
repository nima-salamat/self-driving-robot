import time
from arduino.arduino_connection import ArduinoConnection
from controller.pid_controller import PIDController

class RobotController:
    _instance =  None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config=None):
        if self._initialized:
            return
            
        if config is None:
            raise ValueError("Config must be provided during the first initialization of RobotController.")
            
        self.config = config
        
        mode = getattr(self.config, 'MODE', 'unknown')
        print(f"Mode: {mode}")
        
        kp = getattr(self.config, 'KP', 1.0)
        ki = getattr(self.config, 'KI', 0.0)
        kd = getattr(self.config, 'KD', 0.0)
        kt = getattr(self.config, 'KT', 0.0)
        output_limits = getattr(self.config, 'OUTPUT_LIMITS', (-255, 255))
        
        self.min_servo_angle = getattr(self.config, 'MIN_SERVO_ANGLE', 0)
        self.max_servo_angle = getattr(self.config, 'MAX_SERVO_ANGLE', 180)
        self.servo_center = getattr(self.config, 'SERVO_CENTER', 90)
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
            enabled=not self.without_arduino,
        )
        self.connection.set_print_telemetry(
            bool(getattr(self.config, "READ_ARDUINO_OUTPUT", False))
        )
        if not self.without_arduino:
            startup_wait = max(0.0, float(getattr(self.config, "SERIAL_STARTUP_WAIT", 3.0)))
            if startup_wait and not self.connection.wait_until_connected(startup_wait):
                print("Arduino not connected during startup; recovery continues in background.")
        self.current_angle = 90
        self.current_speed = 0
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

        self.last_angle = 90
        self.command_sequence = 0
        self.last_command = None
        self._initialized = True

    def _send_command(self, cmd: str):
        cmd = cmd.strip() + "\n"
        return self.connection.send_command(cmd)

    def servo(self, angle: int):
        if angle < self.min_servo_angle:
            angle = self.min_servo_angle
        elif angle > self.max_servo_angle:
            angle = self.max_servo_angle
        
        return self._send_command(f"servo {angle}")

    def motor(self, speed: int):
        if speed > 255:
            speed = 255
        elif speed < -255:
            speed = -255
            
        if speed != 0 and not self.without_arduino and not self.connection.connected:
            self.connection.send_command("stop\n")
            self.current_speed = 0
            return False

        if self.current_speed == speed:
            return True
        self.current_speed = speed
        return self._send_command(f"motor {speed}")

    def stop(self):
        """Stop the robot"""
        self.current_speed = 0
        return self._send_command("stop")

    def set_angle(self, angle: int):
        if self.last_angle == angle:
            return True
        self.last_angle = angle
        return self.servo(angle)
    
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
        
    def forward_pulse(self, s):
        self._send_command(s)
    
    def backward_pulse(self, s):
        self._send_command(s)
        
    def read(self):
        """
            read data from arduino . . . 
        """
        command = self.connection.read_command().strip()
        commands = command.split(" ")
        if len(commands) == 6:
            try:
                return {
                    "lane": commands[0], # R, L    status when robot is in the right or left line
                    "motor_status": commands[1], # motor status in when S as stoped F moving forward and B moving backward
                    "right_ultrasonic_dist": float(commands[2]), # cm in float like 6.5 cm
                    "left_ultrasonic_dist": float(commands[3]), # cm in float 
                    "arduino_fps": int(commands[4]), # fps
                    "doing_hardcode": True if commands[5] == "1" else False
                }
            except:
                return dict()
            
        return dict()
    
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
        if lane_type == "none":
            self.pid.reset()
            self.stop()
            return False
        return self.set_angle(self.calculate_angle_by_error(error))

    def signal_left(self):
        self._send_command("left")

    def signal_right(self):
        self._send_command("right")