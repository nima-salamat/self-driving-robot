"""Bounded conservative planner for camera-localized orange obstacles.

This planner deliberately stops when camera geometry cannot justify a route. It
does not infer path clearance from the disconnected left sonar or rear-left
sonar. The single front range is longitudinal evidence only.
"""

import time


class AdaptiveObstaclePlanner:
    STATES = ("FOLLOW_LANE", "OBSTACLE_CANDIDATE", "APPROACH_SLOW",
              "ASSESS_PASSAGE", "SHIFT_TO_PASS_PATH", "PASS_OBSTACLE",
              "RETURN_TO_ORIGINAL_LANE", "VERIFY_RETURN", "SAFE_STOP")

    def __init__(self, trigger_cm, emergency_cm, lane_width_cm, robot_width_cm,
                 clearance_cm, servo_center=95, servo_min=55, servo_max=125,
                 max_sensor_age_s=0.35, timeout_s=12.0):
        if not 0 < emergency_cm < trigger_cm:
            raise ValueError("emergency distance must be positive and below trigger distance")
        if min(lane_width_cm, robot_width_cm, clearance_cm) <= 0:
            raise ValueError("lane, robot, and clearance dimensions must be positive")
        self.trigger_cm, self.emergency_cm = float(trigger_cm), float(emergency_cm)
        self.lane_width_cm, self.robot_width_cm = float(lane_width_cm), float(robot_width_cm)
        self.clearance_cm = float(clearance_cm)
        self.servo_center = float(servo_center)
        self.servo_min = float(servo_min)
        self.servo_max = float(servo_max)
        if not self.servo_min < self.servo_center < self.servo_max:
            raise ValueError("servo limits must contain the calibrated center")
        self.max_sensor_age_s = float(max_sensor_age_s)
        self.timeout_s = float(timeout_s)
        self.state = "FOLLOW_LANE"
        self.reason = "following lane"
        self._candidate_count = 0
        self._started_at = None
        self._side = None
        self._return_count = 0

    def update(self, observation, now=None):
        now = time.monotonic() if now is None else float(now)
        front = observation.get("front_right_cm")
        front_age = observation.get("front_age_s")
        front_valid = (isinstance(front, (int, float)) and front > 0 and
                       front_age is not None and 0 <= front_age <= self.max_sensor_age_s)
        if observation.get("front_sample_sequence") is not None:
            sequence = observation["front_sample_sequence"]
            previous = getattr(self, "_last_front_sequence", None)
            if previous is None or sequence != previous:
                self._fresh_front_confirmations = getattr(self, "_fresh_front_confirmations", 0) + 1
                self._last_front_sequence = sequence
        if self.state not in {"FOLLOW_LANE", "OBSTACLE_CANDIDATE", "SAFE_STOP"}:
            if self._started_at is not None and now - self._started_at > self.timeout_s:
                return self._safe("adaptive maneuver timed out")
            if not front_valid:
                return self._safe("front/right sensor invalid or stale during maneuver")
            if observation.get("connection_lost") or observation.get("odometry_discontinuity"):
                return self._safe("connection/odometry continuity lost")
        if front_valid and front <= self.emergency_cm:
            return self._safe("front/right emergency threshold reached")
        if self.state == "SAFE_STOP":
            return self._decision(speed=0, steering=observation.get("servo_center", 95))
        detected = bool(observation.get("orange_obstacle_detected"))
        localized = observation.get("obstacle_lane_relation") in {"left", "center", "right", "outside_path"}
        if self.state == "FOLLOW_LANE":
            if not front_valid:
                return self._safe("front/right range invalid or stale; stop in degraded mode")
            if front_valid and front <= self.trigger_cm and detected and localized:
                self._candidate_count = 1
                self.state = "OBSTACLE_CANDIDATE"
                self.reason = "fresh camera obstacle and front range candidate"
                self._started_at = now
                return self._decision(speed=observation.get("slow_speed", 80), steering=observation.get("lane_servo", 95))
            return self._decision(speed=observation.get("configured_speed", 200), steering=observation.get("lane_servo", 95))
        if self.state == "OBSTACLE_CANDIDATE":
            if not (front_valid and detected and localized):
                self.state, self._candidate_count = "FOLLOW_LANE", 0
                self.reason = "obstacle candidate not confirmed"
                return self._decision(speed=observation.get("slow_speed", 80), steering=observation.get("lane_servo", 95))
            self._candidate_count += 1
            if self._candidate_count < 3:
                self.state = "APPROACH_SLOW"
                self.reason = "candidate confirmed once; slowing while gathering another observation"
                return self._decision(speed=observation.get("slow_speed", 80), steering=observation.get("lane_servo", 95))
            self.state = "APPROACH_SLOW"
            self.reason = "obstacle confirmed; approach slowly"
        if self.state == "APPROACH_SLOW":
            if detected and localized:
                self._candidate_count += 1
                if self._candidate_count < 3:
                    return self._decision(speed=observation.get("slow_speed", 80), steering=observation.get("lane_servo", 95))
            else:
                self._candidate_count = 0
                self.state = "FOLLOW_LANE"
                self.reason = "obstacle not confirmed during slow approach"
                return self._decision(speed=observation.get("configured_speed", 200), steering=observation.get("lane_servo", 95))
            self.state = "ASSESS_PASSAGE"
            self.reason = "requires fresh justified camera corridor geometry"
        if self.state == "ASSESS_PASSAGE":
            if not observation.get("camera_fresh") or not observation.get("camera_geometry_valid"):
                return self._safe("camera lane/corridor geometry unavailable")
            feasible = observation.get("feasible_sides") or []
            if (not feasible or not observation.get("steering_calibrated") or
                    getattr(self, "_fresh_front_confirmations", 0) < 2):
                return self._safe("no physically justified and reachable passage")
            self._side = feasible[0]
            self.state = "SHIFT_TO_PASS_PATH"
            self.reason = "selected camera-verified corridor: " + self._side
            target = observation.get("path_servo", {}).get(self._side)
            if target is None:
                return self._safe("calibrated steering target for selected path is unavailable")
            return self._decision(speed=observation.get("slow_speed", 80), steering=target)
        if self.state == "SHIFT_TO_PASS_PATH":
            if not observation.get("camera_geometry_valid"):
                return self._safe("lost path geometry while shifting")
            if observation.get("pass_path_acquired"):
                self.state, self.reason = "PASS_OBSTACLE", "following verified passing path"
            return self._decision(speed=observation.get("slow_speed", 80), steering=observation.get("path_servo", {}).get(self._side, observation.get("servo_center", 95)))
        if self.state == "PASS_OBSTACLE":
            if not observation.get("camera_geometry_valid"):
                return self._safe("lost path geometry while passing")
            if observation.get("obstacle_verified_behind"):
                self.state, self.reason = "RETURN_TO_ORIGINAL_LANE", "obstacle verified behind"
            return self._decision(speed=observation.get("slow_speed", 80), steering=observation.get("path_servo", {}).get(self._side, observation.get("servo_center", 95)))
        if self.state == "RETURN_TO_ORIGINAL_LANE":
            if not observation.get("camera_geometry_valid"):
                return self._safe("lost geometry during lane return")
            if observation.get("original_lane_reacquired"):
                self.state, self.reason = "VERIFY_RETURN", "verifying original lane reacquisition"
            return self._decision(speed=observation.get("slow_speed", 80), steering=observation.get("lane_servo", observation.get("servo_center", 95)))
        if self.state == "VERIFY_RETURN":
            if observation.get("original_lane_reacquired") and detected is False:
                self.state, self._started_at, self._side = "FOLLOW_LANE", None, None
                self.reason = "original lane reacquired and obstacle no longer detected"
                return self._decision(speed=observation.get("configured_speed", 200), steering=observation.get("lane_servo", 95))
            self._return_count += 1
            if self._return_count >= 3:
                return self._safe("original lane return not verified")
            return self._decision(speed=observation.get("slow_speed", 80), steering=observation.get("lane_servo", 95))
        return self._safe("unrecognized planner state")

    def _safe(self, reason):
        self.state, self.reason = "SAFE_STOP", str(reason)
        return self._decision(speed=0, steering=95)

    def _decision(self, speed, steering):
        steering = max(self.servo_min, min(self.servo_max, float(steering)))
        return {"state": self.state, "speed": int(speed), "steering": int(round(steering)),
                "reason": self.reason}
