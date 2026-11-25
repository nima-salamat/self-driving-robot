"""Virtual actuator and speed controller shared by simulator backends."""
import math
import time

from controller.pid_controller import PIDController

from .base_adapter import VehicleCommand


class VirtualVehicleController:
    """Maps the existing servo-angle contract onto normalized simulator inputs."""
    def __init__(self, config, backend):
        self.config = config
        self.backend = backend
        self.minimum = float(getattr(config, "MIN_SERVO_ANGLE", 55))
        self.maximum = float(getattr(config, "MAX_SERVO_ANGLE", 125))
        self.center = float(getattr(config, "SERVO_CENTER", 95))
        if not self.minimum < self.center < self.maximum:
            raise ValueError("servo limits must contain SERVO_CENTER")
        self._pid_signature = None
        self._pid_controller = None
        self._sync_pid_settings()
        self.last_servo = self.center
        self._last_steering = 0.0
        self._last_throttle = 0.0
        self._last_control_at = time.monotonic()
        self.last_command = VehicleCommand(0.0, 0.0, 1.0, self.center, 0.0, "initial safe stop")
        self._has_valid_perception = False
        self._perception_invalid_frames = 0

    def _sync_pid_settings(self):
        """Rebuild the virtual PID only when its live settings have changed."""
        try:
            minimum = float(getattr(self.config, "MIN_SERVO_ANGLE", self.minimum))
            center = float(getattr(self.config, "SERVO_CENTER", self.center))
            maximum = float(getattr(self.config, "MAX_SERVO_ANGLE", self.maximum))
            if all(math.isfinite(x) for x in (minimum, center, maximum)) and minimum < center < maximum:
                self.minimum, self.center, self.maximum = minimum, center, maximum
        except (TypeError, ValueError, OverflowError):
            pass

        raw_limits = getattr(self.config, "OUTPUT_LIMITS", (-80.0, 80.0))
        try:
            if not isinstance(raw_limits, (list, tuple)) or len(raw_limits) != 2:
                raise ValueError
            output_low, output_high = float(raw_limits[0]), float(raw_limits[1])
            if not all(math.isfinite(x) for x in (output_low, output_high)) or output_low >= output_high:
                raise ValueError
        except (TypeError, ValueError, OverflowError):
            output_low, output_high = -80.0, 80.0

        def finite_setting(name, default):
            try:
                value = float(getattr(self.config, name, default))
            except (TypeError, ValueError, OverflowError):
                return float(default)
            return value if math.isfinite(value) else float(default)

        use_pid = bool(getattr(self.config, "USE_PID", False))
        kp = finite_setting("KP", 0.35)
        ki = finite_setting("KI", 0.0)
        kd = finite_setting("KD", 0.01)
        kt = max(0.0, finite_setting("KT", 0.01))
        min_dt = max(0.0001, finite_setting("PID_MIN_DT", 0.001))
        max_dt = max(min_dt, finite_setting("PID_MAX_DT", 0.2))
        derivative_filter = min(1.0, max(0.0, finite_setting("PID_DERIVATIVE_FILTER", 0.25)))
        signature = (
            use_pid, kp, ki, kd, kt, output_low, output_high,
            min_dt, max_dt, derivative_filter,
        )
        if signature == self._pid_signature:
            return
        self._pid_signature = signature
        self._pid_controller = (
            PIDController(
                kp, ki, kd, dt=kt if kt > 0 else 0.01,
                output_limits=(output_low, output_high),
                min_dt=min_dt, max_dt=max_dt,
                derivative_filter=derivative_filter,
            )
            if use_pid else None
        )

    def _pid_servo_angle(self, perception, now):
        self._sync_pid_settings()
        if self._pid_controller is None:
            return None
        if bool(getattr(self.config, "AUTO_UPDATE_KP", False)):
            try:
                frame_kp = float(perception.get("kp"))
                if math.isfinite(frame_kp):
                    self._pid_controller.kp = max(-100.0, min(100.0, frame_kp))
            except (TypeError, ValueError, OverflowError):
                pass
        correction = self._pid_controller.update(perception.get("error", 0.0), now=now)
        direction = str(getattr(self.config, "SERVO_DIRECTION", "ltr")).lower()
        signed_correction = -correction if direction == "rtl" else correction
        angle = self.center + signed_correction
        return max(self.minimum, min(self.maximum, angle))

    def command_for(self, perception, speed_kmh=0.0):
        perception = perception or {}
        raw_valid = bool(perception.get("perception_valid", False))
        if raw_valid:
            self._has_valid_perception = True
            self._perception_invalid_frames = 0
        else:
            self._perception_invalid_frames += 1
        grace_frames = max(
            0, int(getattr(self.config, "SIMULATOR_PERCEPTION_LOSS_GRACE_FRAMES", 3))
        )
        grace_active = bool(
            not raw_valid
            and self._has_valid_perception
            and self._perception_invalid_frames <= grace_frames
        )
        valid = raw_valid or grace_active
        self._sync_pid_settings()
        now = time.monotonic()
        dt = max(0.0, min(0.25, now - self._last_control_at))
        self._last_control_at = now
        if raw_valid:
            try:
                angle = float(perception.get("steering_angle", self.last_servo))
            except (TypeError, ValueError, OverflowError):
                angle = self.last_servo
            if not math.isfinite(angle):
                angle = self.last_servo
            pid_angle = self._pid_servo_angle(perception, now)
            if pid_angle is not None:
                angle = pid_angle
            self.last_servo = max(self.minimum, min(self.maximum, angle))
        elif not grace_active and self._pid_controller is not None:
            # Reset derivative history after the bounded dropout grace; the next
            # fresh measurement starts clean instead of producing a D spike.
            self._pid_controller.reset()
        # On missing perception, keep the previous steering estimate; braking
        # is a separate, mode-editable simulation policy.
        if self.last_servo < self.center:
            steering = (self.last_servo - self.center) / max(1.0, self.center - self.minimum)
        else:
            steering = (self.last_servo - self.center) / max(1.0, self.maximum - self.center)
        steering = max(-1.0, min(1.0, steering))
        if bool(getattr(self.config, "SIMULATOR_STEERING_INVERTED", False)):
            steering = -steering
        target = min(200.0, max(0.0, float(getattr(self.config, "SIMULATOR_TARGET_SPEED", 20.0))))
        tracking = perception.get("line_tracking")
        if raw_valid and isinstance(tracking, dict) and tracking.get("enabled"):
            # A single observed boundary is enough to continue safely using the
            # learned lane width, but lower speed while geometry is inferred.
            # If both boundaries disappear, the tracker enters a short coast
            # window with a more conservative speed factor before invalidating
            # perception and allowing the existing lost-lane brake policy.
            try:
                speed_factor = float(tracking.get("speed_factor", 1.0))
            except (TypeError, ValueError, OverflowError):
                speed_factor = 0.25
            if math.isfinite(speed_factor):
                target *= max(0.0, min(1.0, speed_factor))
        if grace_active:
            # A single missing camera/Hough frame must not alternate full
            # throttle and full brake. Continue briefly on the last steering
            # estimate at reduced speed, then apply the configured lost-lane stop.
            target *= 0.55
        limit = max(0.0, min(1.0, float(getattr(self.config, "SIMULATOR_THROTTLE_LIMIT", 0.35))))
        if self.backend in {"carla", "avis"}:
            # Both simulator backends need a normalized steering envelope.
            # AVIS previously received raw frame-to-frame vision changes, which
            # made small lane-detection fluctuations appear as steering jitter.
            steering_limit = min(1.0, max(0.05, float(getattr(self.config, "SIMULATOR_STEERING_LIMIT", 0.28))))
            steering_rate = min(10.0, max(0.10, float(getattr(self.config, "SIMULATOR_STEERING_RATE", 0.80))))
            target_steering = max(-steering_limit, min(steering_limit, steering))
            steering_step = steering_rate * dt
            steering = self._last_steering + max(-steering_step, min(steering_step, target_steering - self._last_steering))
            self._last_steering = steering
            # Settings validation provides physical normalized bounds (0..1);
            # the conservative defaults remain low but are user-adjustable.
        brake = 0.0
        reason = (
            "lane estimate accepted" if raw_valid
            else "brief perception dropout grace ({}/{}); holding last steering".format(
                self._perception_invalid_frames, grace_frames
            ) if grace_active
            else "lane estimate unavailable"
        )
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
            if not math.isfinite(current_speed):
                current_speed = 0.0
            if target <= 0:
                throttle, brake = 0.0, 1.0
            elif current_speed > target + 0.5:
                overspeed = current_speed - target - 0.5
                throttle = 0.0
                brake = min(0.45, 0.10 + overspeed * 0.07)
            else:
                speed_error = max(0.0, target - current_speed)
                desired_throttle = min(limit, 0.02 + speed_error * 0.02)
                rise_rate = min(1.0, max(0.01, float(getattr(self.config, "SIMULATOR_THROTTLE_RISE_RATE", 0.12))))
                if desired_throttle > self._last_throttle:
                    throttle = min(desired_throttle, self._last_throttle + rise_rate * dt)
                else:
                    throttle = desired_throttle
            self._last_throttle = throttle
        if self.backend == "carla" and brake >= 0.5:
            self._last_throttle = 0.0
        command = VehicleCommand(
            steering=steering, throttle=max(0.0, min(1.0, throttle)),
            brake=max(0.0, min(1.0, brake)), servo_angle=self.last_servo,
            target_speed=target, reason=reason,
        )
        self.last_command = command
        return command
