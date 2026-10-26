"""Virtual actuator and speed controller shared by simulator backends."""
import math
from .base_adapter import VehicleCommand


class VirtualVehicleController:
    """Maps the existing servo-angle contract onto normalized simulator inputs."""
    def __init__(self, config, backend):
        self.config = config
        self.backend = backend
        self.minimum = float(getattr(config, "MIN_SERVO_ANGLE", 50))
        self.maximum = float(getattr(config, "MAX_SERVO_ANGLE", 130))
        self.center = float(getattr(config, "SERVO_CENTER", 95))
        if not self.minimum < self.center < self.maximum:
            raise ValueError("servo limits must contain SERVO_CENTER")
        self.last_servo = self.center
        self.last_command = VehicleCommand(0.0, 0.0, 1.0, self.center, 0.0, "initial safe stop")

    def command_for(self, perception, speed_kmh=0.0):
        perception = perception or {}
        valid = bool(perception.get("perception_valid", False))
        if valid:
            try:
                angle = float(perception.get("steering_angle", self.last_servo))
            except (TypeError, ValueError):
                angle = self.last_servo
            if not math.isfinite(angle):
                angle = self.last_servo
            self.last_servo = max(self.minimum, min(self.maximum, angle))
        # On missing perception, keep the previous steering estimate; braking
        # is a separate, mode-editable simulation policy.
        if self.last_servo < self.center:
            steering = (self.last_servo - self.center) / max(1.0, self.center - self.minimum)
        else:
            steering = (self.last_servo - self.center) / max(1.0, self.maximum - self.center)
        steering = max(-1.0, min(1.0, steering))
        if bool(getattr(self.config, "SIMULATOR_STEERING_INVERTED", False)):
            steering = -steering
        target = max(0.0, float(getattr(self.config, "SIMULATOR_TARGET_SPEED", 20.0)))
        limit = max(0.0, min(1.0, float(getattr(self.config, "SIMULATOR_THROTTLE_LIMIT", 0.35))))
        brake = 0.0
        reason = "lane estimate accepted" if valid else "lane estimate unavailable"
        if not valid and bool(getattr(self.config, "SIMULATOR_STOP_ON_LOST_LANE", True)):
            throttle, brake, reason = 0.0, 1.0, "no valid lane; simulator braking"
        elif self.backend == "avis":
            throttle = min(1.0, target / 100.0)
            throttle = min(throttle, limit) if limit > 0 else 0.0
        else:
            try:
                current_speed = max(0.0, float(speed_kmh))
            except (TypeError, ValueError):
                current_speed = 0.0
            if target <= 0:
                throttle, brake = 0.0, 1.0
            elif current_speed > target + max(1.0, target * 0.12):
                throttle, brake = 0.0, min(1.0, (current_speed - target) / max(target, 1.0))
            else:
                ratio = max(0.0, min(1.0, (target - current_speed) / max(target, 1.0)))
                throttle = min(limit, max(0.05, ratio * limit))
        command = VehicleCommand(
            steering=steering, throttle=max(0.0, min(1.0, throttle)),
            brake=max(0.0, min(1.0, brake)), servo_angle=self.last_servo,
            target_speed=target, reason=reason,
        )
        self.last_command = command
        return command
