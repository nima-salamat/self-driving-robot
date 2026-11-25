"""Opt-in, fail-safe behavior coordination for the AVIS simulator.

AVIS exposes only three directional range readings. This module deliberately
uses short, bounded steering nudges rather than pretending those readings form
a full free-space map. It never overrides a stop, a red/unknown traffic-light
hold, or invalid lane perception.
"""
import logging
import math
import time

from modes.simulation.base_adapter import VehicleCommand
from vision.stop_line import StopLineDetector
from vision.traffic_light import GreenConfirmationWindow, TrafficLightDetector

logger = logging.getLogger(__name__)


def _finite_range(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _brake(command, reason):
    return VehicleCommand(
        steering=command.steering,
        throttle=0.0,
        brake=1.0,
        servo_angle=command.servo_angle,
        target_speed=0.0,
        reason=reason,
    )


class RangeObstacleAvoidance:
    """Sensor-gated, staged lane-change controller for the three-ray AVIS setup.

    The controller uses a smooth lane-change profile, holds the lateral offset
    while clearing the obstacle, and only rejoins after both a clear-front
    confirmation window and a minimum travelled distance. It is intentionally
    conservative because AVIS exposes range rays rather than a full occupancy
    grid or rear-facing sensors.
    """

    CLEAR = "clear"
    SHIFT = "shift"
    PASS = "pass"
    REJOIN = "rejoin"
    BLOCKED = "blocked"

    def __init__(self, config):
        self.config = config
        self.state = self.CLEAR
        self.direction = 0.0
        self.state_since = 0.0
        self.pass_started_at = 0.0
        self.distance_since_shift_cm = 0.0
        self.clear_observations = 0
        self.last_ranges = {"left": None, "front": None, "right": None}
        self.last_lane_quality = None
        self.last_reason = "obstacle avoidance idle"
        self._last_output_steering = None
        self._last_output_at = None

    def _number(self, key, default):
        try:
            value = float(getattr(self.config, key, default))
        except (TypeError, ValueError, OverflowError):
            return float(default)
        return value if math.isfinite(value) else float(default)

    @staticmethod
    def _smoothstep(progress):
        value = max(0.0, min(1.0, float(progress)))
        return value * value * (3.0 - 2.0 * value)

    def _set_state(self, state, now, reason):
        previous = self.state
        self.state = state
        self.state_since = now
        self.clear_observations = 0
        self.last_reason = reason
        if state == self.SHIFT:
            self.distance_since_shift_cm = 0.0
        if state == self.PASS:
            self.pass_started_at = now
        if previous != state:
            logger.info("AVIS obstacle maneuver: %s -> %s (%s)", previous, state, reason)

    def _brake(self, command, reason):
        self.last_reason = reason
        return _brake(command, reason)

    def _steer_command(self, command, steering, throttle_cap, reason, now):
        steering_limit = max(
            0.05,
            min(1.0, self._number("SIMULATOR_STEERING_LIMIT", 1.0)),
        )
        target_steering = max(-steering_limit, min(steering_limit, steering))
        rate = max(0.1, min(10.0, self._number("SIMULATOR_STEERING_RATE", 2.0)))
        previous_at = self._last_output_at
        dt = 0.05 if previous_at is None else max(0.0, min(0.25, now - previous_at))
        previous_steering = (
            command.steering if self._last_output_steering is None
            else self._last_output_steering
        )
        max_step = rate * dt
        applied_steering = previous_steering + max(
            -max_step,
            min(max_step, target_steering - previous_steering),
        )
        self._last_output_steering = applied_steering
        self._last_output_at = now
        self.last_reason = reason
        return VehicleCommand(
            steering=max(-steering_limit, min(steering_limit, applied_steering)),
            throttle=min(command.throttle, max(0.0, throttle_cap)),
            brake=0.0,
            servo_angle=command.servo_angle,
            target_speed=min(command.target_speed, 15.0),
            reason=reason,
        )

    def apply(
        self,
        command,
        ranges,
        *,
        perception_valid,
        distance_delta_cm=0.0,
        lane_quality=None,
        now=None,
    ):
        now = time.monotonic() if now is None else float(now)
        ranges = ranges if isinstance(ranges, dict) else {}
        self.last_ranges = {
            key: _finite_range(ranges.get(key))
            for key in ("left", "front", "right")
        }
        self.last_lane_quality = lane_quality

        if not bool(getattr(self.config, "SIMULATOR_OBSTACLE_AVOIDANCE_ENABLED", False)):
            if self.state != self.CLEAR:
                self._set_state(
                    self.BLOCKED, now,
                    "lane-change option disabled during an active maneuver; braking",
                )
                return self._brake(command, self.last_reason)
            self.last_reason = "obstacle avoidance disabled"
            return command

        if command.brake >= 0.5 or not perception_valid:
            if self.state != self.CLEAR:
                self._set_state(
                    self.BLOCKED, now,
                    "lane perception or another safety rule requested braking during bypass",
                )
                return self._brake(command, self.last_reason)
            self.last_reason = (
                "waiting for valid lane perception before starting a lane change"
                if not perception_valid else command.reason or "another safety rule owns braking"
            )
            return command

        front = self.last_ranges["front"]
        left = self.last_ranges["left"]
        right = self.last_ranges["right"]
        trigger = max(36.0, self._number("SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM", 100.0))
        clear_distance = max(
            trigger + 1.0,
            self._number("SIMULATOR_OBSTACLE_CLEAR_DISTANCE_CM", 125.0),
        )
        minimum_side = max(
            1.0,
            self._number("SIMULATOR_OBSTACLE_SIDE_CLEARANCE_CM", 75.0),
        )
        hard_stop = max(
            20.0,
            self._number("SIMULATOR_OBSTACLE_STOP_DISTANCE_CM", 35.0),
        )
        shift_duration = max(
            0.05,
            self._number("SIMULATOR_OBSTACLE_SHIFT_SECONDS", 0.35),
        )
        rejoin_duration = max(
            0.05,
            self._number("SIMULATOR_OBSTACLE_REJOIN_SECONDS", 0.35),
        )
        pass_timeout = max(
            0.2,
            self._number("SIMULATOR_OBSTACLE_PASS_TIMEOUT_SECONDS", 4.0),
        )
        offset = max(
            0.05,
            min(0.35, self._number("SIMULATOR_OBSTACLE_STEERING_OFFSET", 0.28)),
        )
        throttle_cap = max(
            0.0,
            min(0.25, self._number("SIMULATOR_OBSTACLE_THROTTLE_LIMIT", 0.12)),
        )
        minimum_pass_distance = max(40.0, min(150.0, trigger * 0.75))

        if front is None:
            self._set_state(
                self.BLOCKED, now,
                "AVIS front range is missing; no lane change is allowed without forward range data",
            )
            return self._brake(command, self.last_reason)
        if front <= hard_stop:
            self._set_state(
                self.BLOCKED, now,
                f"emergency front range {front:.1f} cm; hard braking",
            )
            return self._brake(command, self.last_reason)

        if self.state in {self.SHIFT, self.PASS, self.REJOIN}:
            selected_side = left if self.direction < 0 else right
            if selected_side is None or selected_side < minimum_side:
                self._set_state(
                    self.BLOCKED, now,
                    "selected lane-change side is no longer proven clear; braking",
                )
                return self._brake(command, self.last_reason)

        if self.state == self.BLOCKED:
            if front >= clear_distance:
                self.clear_observations += 1
                if self.clear_observations >= 3:
                    self._set_state(self.CLEAR, now, "forward clearance restored; maneuver controller re-armed")
                else:
                    return self._brake(
                        command,
                        f"waiting for clear front range ({self.clear_observations}/3 observations)",
                    )
            else:
                self.clear_observations = 0
                return self._brake(command, self.last_reason)

        if self.state == self.CLEAR:
            if front > trigger:
                self.last_reason = "armed; no obstacle inside the lane-change trigger distance"
                return command
            candidates = [
                (distance, direction, side_name)
                for distance, direction, side_name in (
                    (left, -1.0, "left"),
                    (right, 1.0, "right"),
                )
                if distance is not None and distance >= minimum_side
            ]
            if not candidates:
                self._set_state(
                    self.BLOCKED, now,
                    "obstacle ahead but neither side sensor confirms minimum clearance",
                )
                return self._brake(command, self.last_reason)
            clearance, direction, side_name = max(candidates, key=lambda item: item[0])
            if bool(getattr(self.config, "SIMULATOR_STEERING_INVERTED", False)):
                direction = -direction
            self.direction = direction
            self._set_state(
                self.SHIFT, now,
                f"lane change {side_name} selected; side range {clearance:.1f} cm",
            )

        if self.state == self.SHIFT:
            elapsed = max(0.0, now - self.state_since)
            progress = self._smoothstep(elapsed / shift_duration)
            if elapsed >= shift_duration:
                self._set_state(self.PASS, now, "lane-change shift completed; holding bypass path")
                progress = 1.0
            return self._steer_command(
                command,
                command.steering + self.direction * offset * progress,
                throttle_cap,
                f"obstacle lane change: shifting {('left' if self.direction < 0 else 'right')} ({progress:.0%})",
                now,
            )

        if self.state == self.PASS:
            delta = _finite_range(distance_delta_cm)
            if delta is not None:
                self.distance_since_shift_cm += min(delta, 100.0)
            if now - self.pass_started_at > pass_timeout:
                self._set_state(
                    self.BLOCKED, now,
                    "obstacle did not clear within the configured pass timeout",
                )
                return self._brake(command, self.last_reason)
            if front >= clear_distance:
                self.clear_observations += 1
            else:
                self.clear_observations = 0
            if (
                self.clear_observations >= 3
                and self.distance_since_shift_cm >= minimum_pass_distance
            ):
                self._set_state(
                    self.REJOIN, now,
                    "front path clear and minimum pass distance reached; beginning lane rejoin",
                )
            else:
                reason = (
                    "obstacle lane change: passing; confirming clearance and travel distance"
                    if front >= clear_distance
                    else "obstacle lane change: passing beside obstacle"
                )
                return self._steer_command(
                    command,
                    command.steering + self.direction * offset * 0.78,
                    throttle_cap,
                    reason,
                    now,
                )

        if self.state == self.REJOIN:
            if front <= trigger:
                self._set_state(
                    self.PASS, now,
                    "obstacle re-entered forward range; holding bypass path",
                )
                return self._steer_command(
                    command,
                    command.steering + self.direction * offset * 0.78,
                    throttle_cap,
                    "obstacle lane change: obstacle remains ahead",
                    now,
                )
            elapsed = max(0.0, now - self.state_since)
            progress = self._smoothstep(elapsed / rejoin_duration)
            if elapsed >= rejoin_duration:
                self._set_state(self.CLEAR, now, "lane rejoin completed")
                self._last_output_steering = command.steering
                self._last_output_at = now
                return command
            return self._steer_command(
                command,
                command.steering + self.direction * offset * 0.78 * (1.0 - progress),
                throttle_cap,
                f"obstacle lane change: rejoining original lane ({progress:.0%})",
                now,
            )

        return command

    def snapshot(self):
        minimum_pass_distance = max(
            40.0,
            min(
                150.0,
                self._number("SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM", 100.0) * 0.75,
            ),
        )
        return {
            "enabled": bool(getattr(self.config, "SIMULATOR_OBSTACLE_AVOIDANCE_ENABLED", False)),
            "state": self.state,
            "direction": (
                "left" if self.direction < 0 else "right" if self.direction > 0 else None
            ) if self.state != self.CLEAR else None,
            "ranges_cm": dict(self.last_ranges),
            "lane_quality": self.last_lane_quality,
            "distance_since_shift_cm": round(self.distance_since_shift_cm, 1),
            "minimum_pass_distance_cm": round(minimum_pass_distance, 1),
            "front_clear_observations": int(self.clear_observations),
            "reason": self.last_reason,
        }

class AVISBehaviorCoordinator:
    """Coordinates optional AVIS City/Race behavior without physical I/O."""

    def __init__(self, config, vision_profile):
        self.config = config
        self.vision_profile = str(vision_profile).lower()
        self.is_city = self.vision_profile == "city"
        self.obstacles = RangeObstacleAvoidance(config)
        self.stop_line_detector = (
            StopLineDetector(config)
            if self.is_city and bool(getattr(config, "SIMULATOR_STOP_LINE_ENABLED", True))
            else None
        )
        self.traffic_detector = (
            TrafficLightDetector(config)
            if self.is_city and bool(getattr(config, "SIMULATOR_TRAFFIC_LIGHTS_ENABLED", True))
            else None
        )
        window = int(getattr(config, "SIMULATOR_TL_CONFIRMATION_WINDOW", 10))
        required = int(getattr(config, "SIMULATOR_TL_GREEN_REQUIRED", 8))
        self.green_window = GreenConfirmationWindow(window, required) if self.traffic_detector else None
        self.stop_line_confirm_count = 0
        self.stop_line_waiting = False
        self.stop_line_armed = self.stop_line_detector is not None
        self.stop_line_absent_count = 0
        self.stop_line_started_at = None
        self.traffic_light_hold = False
        self.last_light_color = None
        self.last_frame_token = None
        self.stop_sign_until = 0.0
        self.park_latched = False
        self.turn_direction = 0.0
        self.turn_until = 0.0
        self.last_sign_label = None
        self._last_sign_request_id = 0
        self._sign_frame_count = 0
        self._sign_blank_count = 0
        self.sign_detector = None
        self._sign_error = None

        if bool(getattr(config, "SIMULATOR_SIGN_ACTIONS_ENABLED", False)):
            self._start_sign_detector()

    def _start_sign_detector(self):
        try:
            # The ONNX detector exposes per-detection confidence, which the
            # simulator uses to reject uncertain sign actions. The current SVM
            # adapter has no confidence output and is deliberately not offered.
            from traffic_sign_detector.yolo_detector import TrafficSignDetector
            detector = TrafficSignDetector(intra_op_num_threads=2)
            from traffic_sign_detector.async_detector import AsyncSignDetector
            self.sign_detector = AsyncSignDetector(detector)
        except Exception as exc:
            self._sign_error = f"{type(exc).__name__}: {exc}"
            logger.exception("AVIS sign actions requested but detector initialization failed")
            raise RuntimeError("Could not initialize the optional AVIS traffic-sign detector: " + self._sign_error) from exc

    def submit_sign_frame(self, frame):
        if self.sign_detector is None or frame is None:
            return
        interval = max(1, int(getattr(self.config, "SIMULATOR_SIGN_SCAN_INTERVAL", 6)))
        self._sign_frame_count += 1
        if self._sign_frame_count % interval == 0:
            try:
                self.sign_detector.submit(
                    frame.image.copy(),
                    frame_captured_at=getattr(frame, "captured_at", None),
                )
            except Exception:
                logger.debug("Could not submit AVIS sign frame", exc_info=True)
        latest = self.sign_detector.latest(max_age_s=0.9)
        if latest is None or latest[0] <= self._last_sign_request_id:
            return
        self._last_sign_request_id = latest[0]
        payload = latest[1] if isinstance(latest[1], dict) else {}
        label = str(payload.get("text", "")).strip().upper()
        confidence = _finite_range(payload.get("confidence"))
        minimum = float(getattr(self.config, "SIMULATOR_SIGN_CONFIDENCE", 0.45))
        if not label or confidence is None or confidence < minimum:
            self._sign_blank_count += 1
            if self._sign_blank_count >= 3:
                self.last_sign_label = None
            return
        if label == self.last_sign_label:
            self._sign_blank_count = 0
            return
        self._sign_blank_count = 0
        self.last_sign_label = label
        now = time.monotonic()
        if label == "STOP":
            hold = max(0.1, float(getattr(self.config, "SIMULATOR_SIGN_STOP_HOLD_SECONDS", 2.0)))
            self.stop_sign_until = max(self.stop_sign_until, now + hold)
        elif label == "PARK":
            self.park_latched = True
            self.turn_direction = 0.0
        elif label == "TURN LEFT":
            self.turn_direction = -1.0
            self.turn_until = now + max(0.1, float(getattr(self.config, "SIMULATOR_SIGN_TURN_HOLD_SECONDS", 0.6)))
        elif label == "TURN RIGHT":
            self.turn_direction = 1.0
            self.turn_until = now + max(0.1, float(getattr(self.config, "SIMULATOR_SIGN_TURN_HOLD_SECONDS", 0.6)))
        elif label == "STRAIGHT":
            self.park_latched = False
            self.turn_direction = 0.0
            self.turn_until = 0.0
        logger.info("AVIS sign action accepted: %s (confidence %.3f)", label, confidence)

    def _observe_road_rules(self, frame, now):
        if not self.is_city or frame is None:
            return
        token = getattr(frame, "sequence", None) or getattr(frame, "captured_at", None)
        if token == self.last_frame_token:
            return
        self.last_frame_token = token

        line_detected = False
        if self.stop_line_detector is not None:
            try:
                line_result = self.stop_line_detector.detect(frame.image)
                line_detected = bool(line_result.get("detected"))
            except Exception:
                logger.exception("AVIS stop-line detector failed; retaining any active stop")
                line_detected = False

        if self.stop_line_armed and self.stop_line_detector is not None:
            if line_detected:
                self.stop_line_confirm_count += 1
                if self.stop_line_confirm_count >= max(
                    1, int(getattr(self.config, "SIMULATOR_STOP_LINE_CONFIRM_FRAMES", 3))
                ):
                    self.stop_line_waiting = True
                    self.stop_line_started_at = now
                    self.stop_line_armed = False
                    self.stop_line_absent_count = 0
                    if self.green_window:
                        self.green_window.reset()
            else:
                self.stop_line_confirm_count = 0

        if self.traffic_detector is not None:
            try:
                color, _debug = self.traffic_detector.detect(frame.image)
            except Exception:
                logger.exception("AVIS traffic-light detector failed; treating signal as unknown")
                color = None
            self.last_light_color = color
            if color == "RED" and not self.traffic_light_hold:
                self.traffic_light_hold = True
                if self.green_window:
                    self.green_window.reset()
            if self.green_window and (self.traffic_light_hold or self.stop_line_waiting):
                confirmed = self.green_window.observe(color, token)
                if confirmed:
                    self.traffic_light_hold = False
                    self.stop_line_waiting = False
                    self.stop_line_started_at = None
        elif self.stop_line_waiting:
            dwell = max(0.1, float(getattr(self.config, "SIMULATOR_STOP_LINE_DWELL_SECONDS", 1.0)))
            if self.stop_line_started_at is not None and now - self.stop_line_started_at >= dwell:
                self.stop_line_waiting = False
                self.stop_line_started_at = None

        if not line_detected and not self.stop_line_waiting and not self.stop_line_armed:
            self.stop_line_absent_count += 1
            if self.stop_line_absent_count >= 8:
                self.stop_line_armed = True
                self.stop_line_confirm_count = 0
                self.stop_line_absent_count = 0
        elif line_detected:
            self.stop_line_absent_count = 0

    def apply(self, frame, perception, command, *, distance_delta_cm=0.0, now=None):
        if str(getattr(self.config, "SIMULATOR_BACKEND", "avis")).lower() != "avis":
            return command
        now = time.monotonic() if now is None else float(now)
        self._observe_road_rules(frame, now)

        if self.traffic_light_hold or self.stop_line_waiting:
            reason = (
                "AVIS City stop line: waiting for confirmed green signal"
                if self.stop_line_waiting
                else "AVIS City traffic light is red or has not yet been confirmed green"
            )
            return _brake(command, reason)

        if self.park_latched:
            return _brake(command, "PARK sign latched; waiting for a confirmed STRAIGHT sign")
        if now < self.stop_sign_until:
            return _brake(command, "STOP sign hold")

        perception_valid = bool((perception or {}).get("perception_valid", False))
        ranges = getattr(frame, "ranges_cm", {}) if frame is not None else {}
        lane_tracking = (perception or {}).get("line_tracking")
        lane_quality = (perception or {}).get("perception_quality")
        obstacle_command = self.obstacles.apply(
            command,
            ranges,
            perception_valid=perception_valid,
            distance_delta_cm=distance_delta_cm,
            lane_quality=lane_quality,
            now=now,
        )
        if self.obstacles.state != RangeObstacleAvoidance.CLEAR or obstacle_command is not command:
            return obstacle_command

        if self.turn_direction and now < self.turn_until and command.brake < 0.5 and perception_valid:
            offset = max(0.05, min(0.35, float(getattr(
                self.config, "SIMULATOR_SIGN_STEERING_OFFSET", 0.18
            ))))
            direction = self.turn_direction
            if bool(getattr(self.config, "SIMULATOR_STEERING_INVERTED", False)):
                direction = -direction
            return VehicleCommand(
                steering=max(-0.45, min(0.45, command.steering + direction * offset)),
                throttle=min(command.throttle, 0.12),
                brake=0.0,
                servo_angle=command.servo_angle,
                target_speed=min(command.target_speed, 15.0),
                reason=f"traffic sign {self.last_sign_label}: bounded turn-steering nudge",
            )
        if now >= self.turn_until:
            self.turn_direction = 0.0
        return obstacle_command

    def snapshot(self):
        return {
            "obstacle": self.obstacles.snapshot(),
            "stop_line_enabled": self.stop_line_detector is not None,
            "stop_line_waiting": bool(self.stop_line_waiting),
            "stop_line_armed": bool(self.stop_line_armed),
            "traffic_light_enabled": self.traffic_detector is not None,
            "traffic_light": self.last_light_color,
            "traffic_light_hold": bool(self.traffic_light_hold),
            "sign_enabled": self.sign_detector is not None,
            "sign_label": self.last_sign_label,
            "park_latched": bool(self.park_latched),
            "sign_detector_error": self._sign_error,
        }

    def close(self):
        detector, self.sign_detector = self.sign_detector, None
        if detector is not None:
            try:
                detector.close()
            except Exception:
                logger.debug("Could not close AVIS sign detector", exc_info=True)
