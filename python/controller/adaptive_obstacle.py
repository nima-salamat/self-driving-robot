"""Conservative finite-state obstacle maneuver planner.

The planner uses fresh front-range samples and camera-localized lane geometry.
Estimated image corridor width is not a guarantee of physical clearance. Stale
sensor data, missing geometry, encoder discontinuity, or a maneuver timeout
latches a stop. SAFE_STOP requires explicit operator acknowledgement to reset.
"""

import math
import time


class AdaptiveObstaclePlanner:
    STATES = (
        "FOLLOW_LANE", "OBSTACLE_CANDIDATE", "APPROACH_SLOW",
        "ASSESS_PASSAGE", "SHIFT_TO_PASS_PATH", "PASS_OBSTACLE",
        "RETURN_TO_ORIGINAL_LANE", "VERIFY_RETURN", "SAFE_STOP",
    )

    def __init__(
        self, trigger_cm, emergency_cm, lane_width_cm, robot_width_cm,
        clearance_cm, servo_center=95, servo_min=55, servo_max=125,
        max_sensor_age_s=0.35, timeout_s=12.0,
    ):
        values = (trigger_cm, emergency_cm, lane_width_cm, robot_width_cm,
                  clearance_cm, servo_center, servo_min, servo_max,
                  max_sensor_age_s, timeout_s)
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("planner parameters must be finite")
        if not 0 < emergency_cm < trigger_cm:
            raise ValueError("emergency distance must be positive and below trigger distance")
        if min(lane_width_cm, robot_width_cm, clearance_cm) <= 0:
            raise ValueError("lane, robot, and clearance dimensions must be positive")
        if not servo_min < servo_center < servo_max:
            raise ValueError("servo limits must contain the calibrated center")
        if max_sensor_age_s <= 0 or timeout_s <= 0:
            raise ValueError("sensor-age and maneuver-timeout bounds must be positive")

        self.trigger_cm = float(trigger_cm)
        self.emergency_cm = float(emergency_cm)
        self.lane_width_cm = float(lane_width_cm)
        self.robot_width_cm = float(robot_width_cm)
        self.clearance_cm = float(clearance_cm)
        self.servo_center = float(servo_center)
        self.servo_min = float(servo_min)
        self.servo_max = float(servo_max)
        self.max_sensor_age_s = float(max_sensor_age_s)
        self.timeout_s = float(timeout_s)

        self.state = "FOLLOW_LANE"
        self.reason = "following lane"
        self._started_at = None
        self._last_frame_token = None
        self._last_front_sequence = None
        self._candidate_frames = 0
        self._front_confirmations = 0
        self._unlocalized_close_frames = 0
        self._shift_confirmations = 0
        self._object_absent_confirmations = 0
        self._return_confirmations = 0
        self._verify_confirmations = 0
        self._side = None
        self._target_fraction = None
        self._pass_start_travel_cm = None

    @property
    def selected_side(self):
        return self._side

    @property
    def target_fraction(self):
        return self._target_fraction

    def reset_after_manual_clearance(self, *, operator_confirmed=False):
        """Clear the latched stop only after explicit human acknowledgement."""
        if not operator_confirmed:
            raise ValueError("operator_confirmed=True is required to reset SAFE_STOP")
        self.state = "FOLLOW_LANE"
        self.reason = "operator acknowledged safe route; awaiting fresh observations"
        self._started_at = None
        self._candidate_frames = 0
        self._front_confirmations = 0
        self._unlocalized_close_frames = 0
        self._shift_confirmations = 0
        self._object_absent_confirmations = 0
        self._return_confirmations = 0
        self._verify_confirmations = 0
        self._side = None
        self._target_fraction = None
        self._pass_start_travel_cm = None
        # Keep frame/sensor watermarks so buffered observations cannot be replayed as new.

    def update(self, observation, now=None):
        now = time.monotonic() if now is None else float(now)
        if not math.isfinite(now):
            return self._safe("planner clock is invalid")

        frame_token = observation.get("frame_token")
        frame_new = frame_token is not None and frame_token != self._last_frame_token
        if frame_new:
            self._last_frame_token = frame_token

        front = observation.get("front_right_cm")
        front_age = observation.get("front_age_s")
        front_valid = (
            isinstance(front, (int, float)) and not isinstance(front, bool)
            and math.isfinite(float(front)) and float(front) > 0
            and isinstance(front_age, (int, float)) and not isinstance(front_age, bool)
            and math.isfinite(float(front_age))
            and 0 <= float(front_age) <= self.max_sensor_age_s
        )
        front_sequence = observation.get("front_sample_sequence")
        new_front_sample = (
            front_sequence is not None and front_sequence != self._last_front_sequence
        )
        if new_front_sample:
            self._last_front_sequence = front_sequence
            if self.state in {"OBSTACLE_CANDIDATE", "APPROACH_SLOW"}:
                self._front_confirmations += 1

        if self.state == "SAFE_STOP":
            return self._decision(0, self.servo_center)
        if self.state not in {"FOLLOW_LANE", "OBSTACLE_CANDIDATE"}:
            if self._started_at is not None and now - self._started_at > self.timeout_s:
                return self._safe("adaptive maneuver timed out")
            if not front_valid:
                return self._safe("front/right range invalid or stale during maneuver")
            if observation.get("connection_lost") or observation.get("odometry_discontinuity"):
                return self._safe("connection or odometry continuity lost")
        if front_valid and front <= self.emergency_cm:
            return self._safe("front/right emergency threshold reached")

        detected = bool(observation.get("orange_obstacle_detected"))
        relation = observation.get("obstacle_lane_relation")
        localized_in_path = detected and relation in {"left", "center", "right"}
        camera_ok = bool(
            observation.get("camera_fresh") and
            observation.get("camera_geometry_valid")
        )
        lane_servo = observation.get("lane_servo", self.servo_center)
        slow_speed = self._speed(observation.get("slow_speed", 70))
        cruise_speed = self._speed(observation.get("configured_speed", 200))
        path_servo = observation.get("path_servo") or {}
        travel = observation.get("travel_cm")
        travel = float(travel) if (
            isinstance(travel, (int, float)) and not isinstance(travel, bool)
            and math.isfinite(float(travel)) and float(travel) >= 0
        ) else None

        if self.state == "FOLLOW_LANE":
            if not front_valid:
                return self._safe("front/right range unavailable; stopping in degraded mode")
            if front <= self.trigger_cm:
                if localized_in_path and frame_new:
                    self.state = "OBSTACLE_CANDIDATE"
                    self._started_at = now
                    self._candidate_frames = 1
                    self._front_confirmations = 1 if new_front_sample else 0
                    self._unlocalized_close_frames = 0
                    self.reason = "obstacle candidate: fresh camera and front range agree"
                    return self._decision(slow_speed, lane_servo)
                if frame_new:
                    self._unlocalized_close_frames += 1
                if self._unlocalized_close_frames >= 3:
                    return self._safe("front object is close but cannot be localized in the path")
                self.reason = "close front return; slowing while checking camera localization"
                return self._decision(slow_speed, lane_servo)
            self._unlocalized_close_frames = 0
            self.reason = "no confirmed obstacle in the intended path"
            return self._decision(cruise_speed, lane_servo)

        if self.state == "OBSTACLE_CANDIDATE":
            if not front_valid:
                return self._safe("front range lost while confirming obstacle")
            if front > self.trigger_cm:
                self.state = "FOLLOW_LANE"
                self.reason = "front range cleared during candidate confirmation"
                return self._decision(slow_speed, lane_servo)
            if frame_new:
                if not localized_in_path:
                    return self._safe("close obstacle localization was lost during confirmation")
                self._candidate_frames += 1
            if self._candidate_frames >= 2:
                self.state = "APPROACH_SLOW"
                self.reason = "candidate seen on distinct frames; approaching slowly"
            return self._decision(slow_speed, lane_servo)

        if self.state == "APPROACH_SLOW":
            if not localized_in_path and frame_new:
                return self._safe("obstacle localization was lost during approach")
            if frame_new:
                self._candidate_frames += 1
            if self._candidate_frames < 3 or self._front_confirmations < 2:
                self.reason = "confirming obstacle across independent camera and range samples"
                return self._decision(slow_speed, lane_servo)
            self.state = "ASSESS_PASSAGE"
            self.reason = "obstacle confirmed; validating left/right image corridors"
            return self._decision(slow_speed, lane_servo)

        if self.state == "ASSESS_PASSAGE":
            if not camera_ok:
                return self._safe("fresh two-boundary camera geometry unavailable")
            if not observation.get("steering_calibrated") or not observation.get("odometry_valid"):
                return self._safe("steering geometry or encoder continuity is not calibrated")
            if travel is None:
                return self._safe("no trustworthy encoder travel estimate")
            options = observation.get("passage_options") or {}
            path_servo = observation.get("path_servo") or {}
            required_gap = self.robot_width_cm + 2.0 * self.clearance_cm
            ranked = []
            for side in ("left", "right"):
                option = options.get(side)
                if not isinstance(option, dict):
                    continue
                fraction = option.get("target_fraction")
                clearance = option.get("clearance_cm")
                angle = path_servo.get(side)
                if not (
                    isinstance(fraction, (int, float)) and math.isfinite(float(fraction))
                    and 0.0 < float(fraction) < 1.0
                    and isinstance(clearance, (int, float)) and math.isfinite(float(clearance))
                    and float(clearance) >= required_gap
                    and isinstance(angle, (int, float)) and math.isfinite(float(angle))
                    and self.servo_min <= float(angle) <= self.servo_max
                ):
                    continue
                ranked.append((float(clearance), side, float(fraction)))
            if not ranked:
                return self._safe("neither image-estimated corridor meets the configured clearance")
            _clearance, self._side, self._target_fraction = max(ranked)
            self.state = "SHIFT_TO_PASS_PATH"
            self._shift_confirmations = 0
            self.reason = f"selected {self._side} corridor by estimated clearance"
            return self._decision(slow_speed, path_servo[self._side])

        if self.state == "SHIFT_TO_PASS_PATH":
            if not camera_ok:
                return self._safe("lost fresh lane geometry while shifting")
            path_servo = observation.get("path_servo") or {}
            angle = path_servo.get(self._side)
            if angle is None:
                return self._safe("selected passing target cannot be tracked")
            if frame_new:
                if observation.get("pass_path_acquired"):
                    self._shift_confirmations += 1
                else:
                    self._shift_confirmations = 0
            if self._shift_confirmations >= 2:
                if travel is None:
                    return self._safe("encoder travel unavailable at start of pass")
                self._pass_start_travel_cm = travel
                self._object_absent_confirmations = 0
                self.state = "PASS_OBSTACLE"
                self.reason = "passing corridor acquired; verifying obstacle clearance"
            return self._decision(slow_speed, angle)

        if self.state == "PASS_OBSTACLE":
            if not camera_ok:
                return self._safe("lost fresh lane geometry while passing")
            angle = path_servo.get(self._side)
            if angle is None:
                return self._safe("passing corridor target cannot be tracked")
            if frame_new:
                if detected:
                    self._object_absent_confirmations = 0
                else:
                    self._object_absent_confirmations += 1
            progress = (
                travel - self._pass_start_travel_cm
                if travel is not None and self._pass_start_travel_cm is not None
                else -1.0
            )
            if (
                self._object_absent_confirmations >= 3
                and progress >= self.robot_width_cm + self.clearance_cm
                and front_valid and front > self.trigger_cm
            ):
                self.state = "RETURN_TO_ORIGINAL_LANE"
                self._return_confirmations = 0
                self.reason = "obstacle absent across fresh frames and front range cleared"
                return_angle = path_servo.get("return")
                if return_angle is None:
                    return self._safe("original-lane return target unavailable")
                return self._decision(slow_speed, return_angle)
            self.reason = "following passing corridor; waiting for independent clearance evidence"
            return self._decision(slow_speed, angle)

        if self.state == "RETURN_TO_ORIGINAL_LANE":
            if not camera_ok:
                return self._safe("lane geometry lost during return")
            return_angle = path_servo.get("return")
            if return_angle is None:
                return self._safe("original-lane target cannot be tracked")
            if frame_new:
                if observation.get("original_lane_reacquired"):
                    self._return_confirmations += 1
                else:
                    self._return_confirmations = 0
            if self._return_confirmations >= 2:
                self.state = "VERIFY_RETURN"
                self._verify_confirmations = 0
                self.reason = "original lane appears reacquired; verifying on fresh frames"
            return self._decision(slow_speed, return_angle)

        if self.state == "VERIFY_RETURN":
            if not camera_ok:
                return self._safe("lane geometry lost while verifying return")
            return_angle = path_servo.get("return")
            if return_angle is None:
                return self._safe("original-lane verification target unavailable")
            if frame_new:
                if observation.get("original_lane_reacquired") and not detected:
                    self._verify_confirmations += 1
                else:
                    self._verify_confirmations = 0
            if self._verify_confirmations >= 3:
                self.state = "FOLLOW_LANE"
                self.reason = "original lane reacquired and verified"
                self._started_at = None
                self._side = None
                self._target_fraction = None
                self._candidate_frames = 0
                self._front_confirmations = 0
                self._unlocalized_close_frames = 0
                return self._decision(cruise_speed, lane_servo)
            return self._decision(slow_speed, return_angle)

        return self._safe("unrecognized planner state")

    @staticmethod
    def _speed(value):
        try:
            return max(0, min(255, int(abs(float(value)))))
        except (TypeError, ValueError, OverflowError):
            return 0

    def _safe(self, reason):
        self.state = "SAFE_STOP"
        self.reason = str(reason)
        return self._decision(0, self.servo_center)

    def _decision(self, speed, steering):
        try:
            steering = float(steering)
            if not math.isfinite(steering):
                steering = self.servo_center
        except (TypeError, ValueError, OverflowError):
            steering = self.servo_center
        steering = max(self.servo_min, min(self.servo_max, steering))
        return {
            "state": self.state,
            "speed": self._speed(speed),
            "steering": int(round(steering)),
            "reason": self.reason,
            "selected_side": self._side,
            "target_fraction": self._target_fraction,
        }
