import time
from arduino.arduino_connection import ArduinoConnection
from controller.pid_controller import PIDController
import base_config as temp_conf

if temp_conf.CONFIG_MODULE is not None:
    conf = temp_conf.CONFIG_MODULE
else:
    conf = temp_conf

class RobotController:
    def __init__(self):
        self.connection = ArduinoConnection()
        self.current_angle = 90
        self.current_speed = 0
        self.pid = PIDController(1, 0, 0, 1, output_limits=(-80, 80))

    def _send_command(self, cmd: str):
        cmd = cmd.strip() + "\n" 
        self.connection.send_command(cmd)

    def servo(self, angle: int):
        if angle < conf.MIN_SERVO_ANGLE:
            angle = conf.MIN_SERVO_ANGLE
        elif angle > conf.MAX_SERVO_ANGLE:
            angle = conf.MAX_SERVO_ANGLE
        
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
        
    def forward_pulse(self,s):
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
        if conf.SERVO_DIRECTION == "ltr":
            steering_angle = conf.SERVO_CENTER - self.pid.update(error)
        else: # rtl
            steering_angle = conf.SERVO_CENTER + self.pid.update(error)
        
        steering_angle = int(max(conf.MIN_SERVO_ANGLE, min(conf.MAX_SERVO_ANGLE, steering_angle)))
        return steering_angle
    
    def set_angle_by_error(self, error):
        self.set_angle(self.calculate_angle_by_error(error))

# instanciate the controller 
controller = RobotController() # <- i don't like it
