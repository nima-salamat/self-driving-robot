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
    """Direct, ROI-confirmed AVIS obstacle lane-change state machine.

    AVIS steering is normalized to [-1, 1]: negative is left and positive is
    right. Range rays gate each side independently; every direct-search phase
    has a timeout that fails closed rather than steering indefinitely.
    """

    CLEAR = "clear"
    SHIFT_LEFT_DIRECT = "shift_left_direct"
    SEARCH_LEFT_ROI = "search_left_roi"
    PASS_LANE_FOLLOW = "pass_lane_follow"
    SHIFT_RIGHT_DIRECT = "shift_right_direct"
    SEARCH_RIGHT_ROI = "search_right_roi"
    BLOCKED = "blocked"

    # Compatibility aliases for older diagnostics/integrations.
    SHIFT = SHIFT_LEFT_DIRECT
    PASS = PASS_LANE_FOLLOW
    REJOIN = SHIFT_RIGHT_DIRECT

    def __init__(self, config):
        self.config = config
        self.state = self.CLEAR
        self.selected_side = None
        self.state_since = 0.0
        self.pass_started_at = 0.0
        self.roi_confirmations = 0
        self.clear_observations = 0
        self.awaiting_clear = False
        self.last_ranges = {"left": None, "front": None, "right": None}
        self.last_reason = "obstacle avoidance idle"
        self.last_maneuver_roi = None

    def _number(self, key, default):
        try:
            value = float(getattr(self.config, key, default))
        except (TypeError, ValueError, OverflowError):
            return float(default)
        return value if math.isfinite(value) else float(default)

    def _integer(self, key, default):
        try:
            value = int(getattr(self.config, key, default))
        except (TypeError, ValueError, OverflowError):
            return int(default)
        return value

    def _set_state(self, state, now, reason):
        previous = self.state
        self.state = state
        self.state_since = now
        self.roi_confirmations = 0
        self.last_reason = reason
        if state == self.PASS_LANE_FOLLOW:
            self.pass_started_at = now
        if state == self.CLEAR:
            self.selected_side = None
        if previous != state:
            logger.info("AVIS obstacle maneuver: %s -> %s (%s)", previous, state, reason)

    def prepare_vision(self, now=None):
        """Select the temporary lane ROI before the next camera frame is parsed."""
        active_roi = None
        if self.state == self.SEARCH_LEFT_ROI:
            active_roi = "left"
        elif self.state == self.SEARCH_RIGHT_ROI:
            active_roi = "right"
        self.config.SIMULATOR_ACTIVE_OBSTACLE_ROI = active_roi
        return active_roi

    def _direct_command(self, command, side, reason):
        setting = (
            "SIMULATOR_OBSTACLE_LEFT_STEERING_PERCENT"
            if side == "left"
            else "SIMULATOR_OBSTACLE_RIGHT_STEERING_PERCENT"
        )
        percent = max(0.0, min(100.0, self._number(setting, 80.0)))
        steering_limit = max(
            0.05, min(1.0, self._number("SIMULATOR_STEERING_LIMIT", 1.0))
        )
        steering = (-1.0 if side == "left" else 1.0) * percent / 100.0
        steering = max(-steering_limit, min(steering_limit, steering))
        throttle_limit = max(
            0.0, min(1.0, self._number("SIMULATOR_THROTTLE_LIMIT", 0.35))
        )
        throttle_cap = max(
            0.0, min(0.25, self._number("SIMULATOR_OBSTACLE_THROTTLE_LIMIT", 0.08))
        )
        throttle = min(throttle_limit, throttle_cap)
        target_speed = max(
            0.0, min(15.0, self._number("SIMULATOR_TARGET_SPEED", 15.0))
        )
        self.last_reason = reason
        return VehicleCommand(
            steering=steering,
            throttle=throttle,
            brake=0.0,
            servo_angle=command.servo_angle,
            target_speed=target_speed,
            reason=reason,
        )

    def _brake(self, command, reason):
        self.last_reason = reason
        self.config.SIMULATOR_ACTIVE_OBSTACLE_ROI = None
        return _brake(command, reason)

    def _direct_phase(self, command, side, now, delay, search_state):
        elapsed = max(0.0, now - self.state_since)
        if self.state in {self.SHIFT_LEFT_DIRECT, self.SHIFT_RIGHT_DIRECT} and elapsed >= delay:
            self._set_state(
                search_state,
                now,
                f"{side} steering delay elapsed; enabling {side} maneuver ROI",
            )
        if self.state == search_state:
            timeout = max(
                0.5,
                min(15.0, self._number("SIMULATOR_OBSTACLE_ROI_SEARCH_TIMEOUT_SECONDS", 4.0)),
            )
            if now - self.state_since > timeout:
                self._set_state(
                    self.BLOCKED, now,
                    f"{side} maneuver ROI did not find a valid lane before search timeout",
                )
                return self._brake(command, self.last_reason)
        percent = self._number(
            "SIMULATOR_OBSTACLE_LEFT_STEERING_PERCENT"
            if side == "left"
            else "SIMULATOR_OBSTACLE_RIGHT_STEERING_PERCENT",
            80.0,
        )
        return self._direct_command(
            command, side,
            f"obstacle lane change: direct {side} steering ({max(0.0, min(100.0, percent)):.0f}%)",
        )

    def apply(
        self,
        command,
        ranges,
        *,
        perception_valid,
        distance_delta_cm=0.0,
        lane_quality=None,
        lane_kp=None,
        lane_tracking=None,
        maneuver_roi=None,
        now=None,
    ):
        now = time.monotonic() if now is None else float(now)
        ranges = ranges if isinstance(ranges, dict) else {}
        self.last_ranges = {
            key: _finite_range(ranges.get(key))
            for key in ("left", "front", "right")
        }
        front = self.last_ranges["front"]
        left = self.last_ranges["left"]
        right = self.last_ranges["right"]

        if not bool(getattr(self.config, "SIMULATOR_OBSTACLE_AVOIDANCE_ENABLED", False)):
            if self.state != self.CLEAR:
                return self._brake(
                    command,
                    "lane-change option disabled during an active maneuver; braking",
                )
            self.config.SIMULATOR_ACTIVE_OBSTACLE_ROI = None
            self.last_reason = "obstacle avoidance disabled"
            return command

        trigger = max(36.0, self._number("SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM", 120.0))
        clear_distance = max(
            trigger + 1.0,
            self._number("SIMULATOR_OBSTACLE_CLEAR_DISTANCE_CM", 150.0),
        )
        minimum_side = max(
            1.0, self._number("SIMULATOR_OBSTACLE_SIDE_CLEARANCE_CM", 75.0)
        )
        hard_stop = max(
            20.0, self._number("SIMULATOR_OBSTACLE_STOP_DISTANCE_CM", 60.0)
        )
        roi_delay = max(
            0.0, min(5.0, self._number("SIMULATOR_OBSTACLE_ROI_DELAY_SECONDS", 1.0))
        )
        confirm_frames = max(
            1, min(10, self._integer("SIMULATOR_OBSTACLE_ROI_CONFIRM_FRAMES", 2))
        )
        lane_hold = max(
            0.2, min(10.0, self._number("SIMULATOR_OBSTACLE_LANE_HOLD_SECONDS", 3.0))
        )

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

        if self.state == self.BLOCKED:
            if front >= clear_distance:
                self.clear_observations += 1
                if self.clear_observations >= 3:
                    self.awaiting_clear = True
                    self._set_state(
                        self.CLEAR, now,
                        "forward clearance restored; maneuver controller re-armed",
                    )
                    self.config.SIMULATOR_ACTIVE_OBSTACLE_ROI = None
                else:
                    return self._brake(
                        command,
                        f"waiting for clear front range ({self.clear_observations}/3 observations)",
                    )
            else:
                self.clear_observations = 0
                return self._brake(command, self.last_reason)

        if self.state == self.CLEAR:
            if self.awaiting_clear:
                if front >= clear_distance:
                    self.clear_observations += 1
                    if self.clear_observations >= 3:
                        self.awaiting_clear = False
                        self.clear_observations = 0
                else:
                    self.clear_observations = 0
                    self.last_reason = "waiting for the previous obstacle to clear before re-arming"
                    return command
            if front > trigger:
                self.last_reason = "armed; no obstacle inside the lane-change trigger distance"
                self.config.SIMULATOR_ACTIVE_OBSTACLE_ROI = None
                return command
            normal_lane_lost_stop = (
                not perception_valid
                and "no valid lane" in str(getattr(command, "reason", "")).lower()
            )
            if command.brake >= 0.5 and not normal_lane_lost_stop:
                self._set_state(
                    self.BLOCKED, now,
                    "an explicit non-lane safety hold is active; obstacle lane change remains inhibited",
                )
                return self._brake(command, self.last_reason)
            if left is None or left < minimum_side:
                self._set_state(
                    self.BLOCKED, now,
                    "left lane departure is not proven clear by the left range sensor; braking",
                )
                return self._brake(command, self.last_reason)
            self._set_state(
                self.SHIFT_LEFT_DIRECT, now,
                f"left lane departure selected; left clearance {left:.1f} cm",
            )
            self.selected_side = "left"
            self.config.SIMULATOR_ACTIVE_OBSTACLE_ROI = None
            return self._direct_command(command, "left", "obstacle lane change: direct left steering")

        if self.state in {self.SHIFT_LEFT_DIRECT, self.SEARCH_LEFT_ROI, self.PASS_LANE_FOLLOW}:
            if left is None or left < minimum_side:
                self._set_state(
                    self.BLOCKED, now,
                    "left-side clearance is no longer proven during bypass; braking",
                )
                return self._brake(command, self.last_reason)

        if self.state in {self.SHIFT_RIGHT_DIRECT, self.SEARCH_RIGHT_ROI}:
            if right is None or right < minimum_side:
                self._set_state(
                    self.BLOCKED, now,
                    "right-side clearance is not proven for the return maneuver; braking",
                )
                return self._brake(command, self.last_reason)

        if self.state == self.SHIFT_LEFT_DIRECT:
            return self._direct_phase(
                command, "left", now, roi_delay, self.SEARCH_LEFT_ROI
            )

        if self.state == self.SEARCH_LEFT_ROI:
            observed = (
                isinstance(maneuver_roi, dict)
                and maneuver_roi.get("side") == "left"
                and bool(maneuver_roi.get("observed"))
                and bool(perception_valid)
            )
            self.roi_confirmations = self.roi_confirmations + 1 if observed else 0
            self.last_maneuver_roi = "left" if observed else None
            if self.roi_confirmations >= confirm_frames:
                self._set_state(
                    self.PASS_LANE_FOLLOW, now,
                    "left maneuver ROI confirmed a lane; handing steering back to lane PID",
                )
                self.config.SIMULATOR_ACTIVE_OBSTACLE_ROI = "left"
                return command
            return self._direct_phase(
                command, "left", now, roi_delay, self.SEARCH_LEFT_ROI
            )

        if self.state == self.PASS_LANE_FOLLOW:
            if not perception_valid or command.brake >= 0.5:
                self._set_state(
                    self.BLOCKED, now,
                    "passing-lane perception was lost; stopping instead of driving blind",
                )
                return self._brake(command, self.last_reason)
            if now - self.pass_started_at >= lane_hold:
                if right is None or right < minimum_side:
                    self._set_state(
                        self.BLOCKED, now,
                        "passing interval ended but right-side clearance is not proven; braking",
                    )
                    return self._brake(command, self.last_reason)
                self._set_state(
                    self.SHIFT_RIGHT_DIRECT, now,
                    "passing-lane hold completed; beginning direct right return",
                )
                self.selected_side = "right"
                self.config.SIMULATOR_ACTIVE_OBSTACLE_ROI = None
                return self._direct_command(
                    command, "right", "obstacle lane change: direct right steering"
                )
            self.last_reason = (
                "obstacle lane change: following the passing lane with normal lane PID"
            )
            # The confirmation frame used the temporary ROI; subsequent
            # passing-lane frames return to the ordinary lane detector and PID.
            self.config.SIMULATOR_ACTIVE_OBSTACLE_ROI = None
            return command

        if self.state == self.SHIFT_RIGHT_DIRECT:
            return self._direct_phase(
                command, "right", now, roi_delay, self.SEARCH_RIGHT_ROI
            )

        if self.state == self.SEARCH_RIGHT_ROI:
            observed = (
                isinstance(maneuver_roi, dict)
                and maneuver_roi.get("side") == "right"
                and bool(maneuver_roi.get("observed"))
                and bool(perception_valid)
            )
            self.roi_confirmations = self.roi_confirmations + 1 if observed else 0
            self.last_maneuver_roi = "right" if observed else None
            if self.roi_confirmations >= confirm_frames:
                self.awaiting_clear = True
                self.clear_observations = 0
                self._set_state(
                    self.CLEAR, now,
                    "right maneuver ROI confirmed the original lane; normal lane detection restored",
                )
                self.config.SIMULATOR_ACTIVE_OBSTACLE_ROI = None
                return command
            return self._direct_phase(
                command, "right", now, roi_delay, self.SEARCH_RIGHT_ROI
            )

        self.config.SIMULATOR_ACTIVE_OBSTACLE_ROI = None
        return command

    def snapshot(self):
        active_roi = self.prepare_vision()
        direction = (
            "left" if self.state in {
                self.SHIFT_LEFT_DIRECT, self.SEARCH_LEFT_ROI, self.PASS_LANE_FOLLOW
            } else "right" if self.state in {
                self.SHIFT_RIGHT_DIRECT, self.SEARCH_RIGHT_ROI
            } else None
        )
        direct_side = (
            "left" if self.state in {self.SHIFT_LEFT_DIRECT, self.SEARCH_LEFT_ROI}
            else "right" if self.state in {self.SHIFT_RIGHT_DIRECT, self.SEARCH_RIGHT_ROI}
            else None
        )
        direct_setting = (
            "SIMULATOR_OBSTACLE_LEFT_STEERING_PERCENT"
            if direct_side == "left"
            else "SIMULATOR_OBSTACLE_RIGHT_STEERING_PERCENT"
        )
        lane_hold = max(
            0.2, min(10.0, self._number("SIMULATOR_OBSTACLE_LANE_HOLD_SECONDS", 3.0))
        )
        return {
            "enabled": bool(getattr(self.config, "SIMULATOR_OBSTACLE_AVOIDANCE_ENABLED", False)),
            "state": self.state,
            "direction": direction,
            "active_maneuver_roi": active_roi,
            "roi_confirmations": int(self.roi_confirmations),
            "roi_confirmations_required": max(
                1, min(10, self._integer("SIMULATOR_OBSTACLE_ROI_CONFIRM_FRAMES", 2))
            ),
            "roi_search_timeout_seconds": max(
                0.5, min(15.0, self._number("SIMULATOR_OBSTACLE_ROI_SEARCH_TIMEOUT_SECONDS", 4.0))
            ),
            "direct_steering_percent": (
                max(0.0, min(100.0, self._number(direct_setting, 80.0)))
                if direct_side else None
            ),
            "lane_hold_seconds": lane_hold,
            "lane_hold_elapsed_seconds": (
                max(0.0, min(lane_hold, time.monotonic() - self.pass_started_at))
                if self.state == self.PASS_LANE_FOLLOW else 0.0
            ),
            "ranges_cm": dict(self.last_ranges),
            "front_clear_observations": int(self.clear_observations),
            "awaiting_obstacle_clear": bool(self.awaiting_clear),
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

    def prepare_vision(self, now=None):
        if str(getattr(self.config, "SIMULATOR_BACKEND", "avis")).lower() != "avis":
            return None
        return self.obstacles.prepare_vision(now=now)

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
        lane_quality = (perception or {}).get("perception_quality")
        lane_kp = (perception or {}).get("kp")
        lane_tracking = (perception or {}).get("line_tracking")
        maneuver_roi = (perception or {}).get("maneuver_roi")
        obstacle_command = self.obstacles.apply(
            command,
            ranges,
            perception_valid=perception_valid,
            distance_delta_cm=distance_delta_cm,
            lane_quality=lane_quality,
            lane_kp=lane_kp,
            lane_tracking=lane_tracking,
            maneuver_roi=maneuver_roi,
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
