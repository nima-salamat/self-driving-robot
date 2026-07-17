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

        self.connection = ArduinoConnection()
        self.current_angle = 90
        self.current_speed = 0
        self.pid = PIDController(kp, ki, kd, kt, output_limits=output_limits)
        
        self.last_angle = 90
        self._initialized = True

    def _send_command(self, cmd: str):
        cmd = cmd.strip() + "\n" 
        self.connection.send_command(cmd)

    def servo(self, angle: int):
        if angle < self.min_servo_angle:
            angle = self.min_servo_angle
        elif angle > self.max_servo_angle:
            angle = self.max_servo_angle
        
        self._send_command(f"servo {angle}")

    def motor(self, speed: int):
        if speed > 255:
            speed = 255
        elif speed < -255:
            speed = -255
            
        if self.current_speed != speed:
            self.current_speed = speed
        self._send_command(f"motor {speed}")

    def stop(self):
        """Stop the robot"""
        self._send_command("stop")
        self.current_speed = 0

    def set_angle(self, angle: int):
        self.last_angle = angle
        self.servo(angle)
    
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
            self.set_angle(40)
        self.set_angle(self.calculate_angle_by_error(error))

    def signal_left(self):
        self._send_command("left")

    def signal_right(self):
        self._send_command("right")