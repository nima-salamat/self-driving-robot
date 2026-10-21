"""Opt-in encoder odometry for the single-channel encoder firmware protocol.

The firmware's encoder has no direction channel. Signed travel is therefore an
estimate based on the motor direction context at sample time; wheel coast during
stops/reversals, slip, backlash, missed edges and integer counter wrap can make
the estimate discontinuous or biased. Position uses a bicycle model and is not
ground-truth localization.
"""

import math
import threading
import time
from collections import deque


class EncoderOdometry:
    def __init__(self, pulse_distance_cm, wheelbase_cm=None, servo_center=95,
                 servo_min=55, servo_max=125, max_wheel_angle_deg=25.0,
                 history_size=1200, max_sample_age_s=0.5):
        if not math.isfinite(float(pulse_distance_cm)) or pulse_distance_cm <= 0:
            raise ValueError("pulse_distance_cm must be a positive finite value")
        self.pulse_distance_cm = float(pulse_distance_cm)
        self.wheelbase_cm = float(wheelbase_cm) if wheelbase_cm is not None else None
        self.servo_center = float(servo_center)
        self.servo_min = float(servo_min)
        self.servo_max = float(servo_max)
        self.max_wheel_angle_deg = float(max_wheel_angle_deg)
        if not math.isfinite(self.max_wheel_angle_deg) or not 0.0 < self.max_wheel_angle_deg <= 45.0:
            raise ValueError("max_wheel_angle_deg must be in (0, 45]")
        self.calibrated = self._has_steering_calibration()
        self.max_sample_age_s = max(0.01, float(max_sample_age_s))
        self.history = deque(maxlen=max(2, int(history_size)))
        self._lock = threading.RLock()
        self._epoch = None
        self._pulses = None
        self._last_at = None
        self._continuity_broken = False
        self._servo = self.servo_center
        self._last_delta_pulses = 0
        self._total_distance = 0.0
        self._travel_distance = 0.0
        self._x = self._y = self._heading = 0.0
        self._valid = False
        self._reason = "waiting for extended encoder telemetry"
        self._last_sample_age = None

    def _has_steering_calibration(self):
        return bool(
            self.wheelbase_cm is not None and self.wheelbase_cm > 0 and
            self.servo_min < self.servo_center < self.servo_max and
            0.0 < self.max_wheel_angle_deg <= 45.0
        )

    def _road_wheel_angle(self, servo):
        # Firmware telemetry gives the servo command, not physical wheel angles.
        # Map each side of the configured center to the editable maximum effective
        # steering angle. This is a starting model, not a measured Ackermann angle.
        command = max(self.servo_min, min(self.servo_max, float(servo)))
        if command <= self.servo_center:
            span = self.servo_center - self.servo_min
            ratio = (self.servo_center - command) / span
            return -ratio * self.max_wheel_angle_deg
        span = self.servo_max - self.servo_center
        ratio = (command - self.servo_center) / span
        return ratio * self.max_wheel_angle_deg

    def ingest(self, sample, received_at=None):
        """Accept one parsed ODOM1 record; repeated pulse totals add no travel."""
        received_at = time.monotonic() if received_at is None else float(received_at)
        if not math.isfinite(received_at):
            return False
        with self._lock:
            if not sample.get("extended"):
                self._mark_gap("invalid or legacy encoder telemetry")
                return False
            epoch = sample.get("epoch")
            pulses = sample.get("signed_pulses")
            servo = sample.get("servo")
            if not isinstance(pulses, int) or not isinstance(servo, (int, float)):
                self._mark_gap("malformed encoder telemetry")
                return False
            self._servo = float(servo)
            if self._epoch is None:
                self._epoch, self._pulses, self._last_at = epoch, pulses, received_at
                self._last_delta_pulses = 0
                self._valid = bool(sample.get("valid", True))
                self._reason = "re-anchored after odometry discontinuity" if self._continuity_broken else "origin established"
                self._append(valid=not self._continuity_broken, gap=self._continuity_broken, at=received_at)
                self._continuity_broken = False
                return self._valid
            # Consumers may replay a rolling telemetry window every control cycle.
            # Ignore duplicate/out-of-order records before considering the epoch
            # or pulse delta; replaying an older counter can otherwise add false
            # positive/negative travel to the odometry estimate.
            if self._last_at is not None and received_at <= self._last_at:
                return False
            if epoch != self._epoch:
                self._epoch, self._pulses, self._last_at = epoch, pulses, received_at
                self._mark_gap("Arduino reboot/counter epoch changed")
                return False
            if received_at - self._last_at > self.max_sample_age_s:
                self._epoch, self._pulses = epoch, pulses
                self._mark_gap("encoder telemetry interval exceeded freshness bound")
                return False
            delta = pulses - self._pulses
            if abs(delta) > 100000:
                self._epoch, self._pulses = epoch, pulses
                self._mark_gap("implausible encoder counter jump")
                return False
            self._pulses, self._last_at = pulses, received_at
            self._last_delta_pulses = delta
            distance = delta * self.pulse_distance_cm
            self._total_distance += distance
            self._travel_distance += abs(distance)
            if self.calibrated and distance:
                angle = math.radians(self._road_wheel_angle(self._servo))
                curvature = math.tan(angle) / self.wheelbase_cm
                dtheta = distance * curvature
                if abs(dtheta) < 1e-9:
                    self._x += distance * math.cos(self._heading)
                    self._y += distance * math.sin(self._heading)
                else:
                    radius = 1.0 / curvature
                    self._x += radius * (math.sin(self._heading + dtheta) - math.sin(self._heading))
                    self._y -= radius * (math.cos(self._heading + dtheta) - math.cos(self._heading))
                self._heading += dtheta
            self._valid = bool(sample.get("valid", True))
            self._reason = "continuous signed-pulse estimate"
            self._append(valid=self._valid, gap=False, at=received_at)
            return self._valid

    def mark_discontinuity(self, reason):
        with self._lock:
            self._mark_gap(str(reason))

    def _mark_gap(self, reason):
        self._valid = False
        self._reason = reason
        self._continuity_broken = True
        # Re-anchor on the next valid sample; never integrate across unknown
        # motion while the host or telemetry stream was unavailable.
        self._epoch = self._pulses = self._last_at = None
        if not self.history or not self.history[-1].get("gap") or self.history[-1].get("reason") != reason:
            self._append(valid=False, gap=True, at=time.monotonic())

    def _append(self, valid, gap, at):
        self.history.append({"x_cm": self._x if self.calibrated else None,
                             "y_cm": self._y if self.calibrated else None,
                             "heading_rad": self._heading if self.calibrated else None,
                             "signed_pulses": self._pulses,
                             "pulse_delta": self._last_delta_pulses,
                             "servo_command": self._servo,
                             "valid": bool(valid and self._valid), "gap": bool(gap),
                             "reason": self._reason if gap else None,
                             "at": at})

    def snapshot(self, now=None):
        now = time.monotonic() if now is None else float(now)
        with self._lock:
            age = None if self._last_at is None else max(0.0, now - self._last_at)
            if age is not None and age > self.max_sample_age_s:
                valid = False
                reason = "encoder telemetry is stale"
            else:
                valid, reason = self._valid, self._reason
            return {"label": "Estimated Odometry", "valid": valid,
                    "reason": reason, "trajectory_available": self.calibrated,
                    "signed_pulses": self._pulses,
                    "steering_angle_source": "arduino_servo_command",
                    "road_wheel_angle_deg": self._road_wheel_angle(self._servo) if self.calibrated else None,
                    "max_wheel_angle_deg": self.max_wheel_angle_deg,
                    "travel_cm": self._travel_distance,
                    "signed_distance_cm": self._total_distance,
                    "x_cm": self._x if self.calibrated else None,
                    "y_cm": self._y if self.calibrated else None,
                    "heading_rad": self._heading if self.calibrated else None,
                    "servo_command": self._servo, "servo_center": self.servo_center,
                    "pulse_distance_cm": self.pulse_distance_cm,
                    "wheelbase_cm": self.wheelbase_cm,
                    "max_wheel_angle_deg": self.max_wheel_angle_deg,
                    "sample_age_s": age,
                    "history": list(self.history)}

    def reset_display_origin(self):
        """Zero only visualization pose; never touches Arduino counters/motors."""
        with self._lock:
            self._x = self._y = self._heading = 0.0
            self.history.clear()
            self._append(valid=self._valid, gap=False, at=time.monotonic())
