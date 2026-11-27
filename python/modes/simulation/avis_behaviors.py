"""Opt-in, fail-safe behavior coordination for the AVIS simulator.

AVIS exposes only three directional range readings. This module deliberately
uses short, bounded steering nudges rather than pretending those readings form
a full free-space map. It never overrides a stop, a red/unknown traffic-light
hold, or invalid lane perception.
"""
import json
import logging
import math
import time
import uuid
from collections import deque

from controller.pid_controller import PIDController
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



class AVISObstacleApproachSpeedController:
    """Regulate AVIS speed toward a km/h target when an enabled range ray sees an object.

    AVIS actuator speed is a percentage command, not km/h. This controller
    therefore uses the Engine's measured km/h as feedback and adjusts only the
    AVIS virtual actuator throttle. It is never used by physical City/Race.
    """

    SENSOR_ORDER = ("left", "front", "right")

    def __init__(self, config):
        self.config = config
        self._pid = PIDController(
            0.035, 0.06, 0.0,
            dt=0.05,
            output_limits=(0.0, 0.35),
            min_dt=0.01,
            max_dt=0.25,
            derivative_filter=0.0,
        )
        self._active = False
        self._brake_active = False
        self._snapshot = {
            "state": "clear",
            "brake_to_target_enabled": bool(getattr(
                config, "SIMULATOR_OBSTACLE_SPEED_LIMIT_BRAKE_ENABLED", False
            )),
            "target_speed_kmh": float(getattr(
                config, "SIMULATOR_OBSTACLE_APPROACH_SPEED_KMH", 10.0
            )),
            "measured_speed_kmh": None,
            "nearest_sensor": None,
            "nearest_distance_cm": None,
            "speed_limit_distance_cm": float(getattr(
                config, "SIMULATOR_OBSTACLE_SPEED_LIMIT_DISTANCE_CM", 1500.0
            )),
            "throttle": None,
            "reason": "no ultrasonic object inside the speed-limit range",
        }

    @staticmethod
    def _valid_speed(value):
        try:
            speed = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return speed if math.isfinite(speed) and speed >= 0 else None

    def apply(self, frame, command, *, now=None):
        now = time.monotonic() if now is None else float(now)
        if str(getattr(command, "reason", "")).startswith("crosswalk hardcode"):
            return command
        ranges = getattr(frame, "ranges_cm", {}) if frame is not None else {}
        ranges = ranges if isinstance(ranges, dict) else {}
        readings = {}
        for sensor in self.SENSOR_ORDER:
            value = _finite_range(ranges.get(sensor))
            if value is not None and value > 0:
                readings[sensor] = value

        enabled_sensors = {
            sensor: bool(getattr(
                self.config,
                "SIMULATOR_OBSTACLE_SPEED_LIMIT_{}_SENSOR_ENABLED".format(sensor.upper()),
                sensor == "front",
            ))
            for sensor in self.SENSOR_ORDER
        }
        speed_limit_readings = {
            sensor: distance
            for sensor, distance in readings.items()
            if enabled_sensors[sensor]
        }
        nearest_sensor = (
            min(speed_limit_readings, key=speed_limit_readings.get)
            if speed_limit_readings else None
        )
        nearest_distance = (
            speed_limit_readings.get(nearest_sensor)
            if nearest_sensor is not None else None
        )
        trigger_distance = max(
            1.0,
            min(10000.0, float(getattr(
                self.config, "SIMULATOR_OBSTACLE_SPEED_LIMIT_DISTANCE_CM", 1500.0
            ))),
        )
        target_speed = max(
            1.0,
            min(100.0, float(getattr(
                self.config, "SIMULATOR_OBSTACLE_APPROACH_SPEED_KMH", 10.0
            ))),
        )

        brake_to_target_enabled = bool(getattr(
            self.config, "SIMULATOR_OBSTACLE_SPEED_LIMIT_BRAKE_ENABLED", False
        ))

        if command.brake >= 0.5:
            self._pid.reset()
            self._active = False
            self._brake_active = False
            self._snapshot = {
                "state": "braking",
                "brake_to_target_enabled": brake_to_target_enabled,
                "target_speed_kmh": target_speed,
                "measured_speed_kmh": self._valid_speed(
                    getattr(frame, "speed_kmh", None)
                ) if frame is not None else None,
                "nearest_sensor": nearest_sensor,
                "nearest_distance_cm": nearest_distance,
                "speed_limit_distance_cm": trigger_distance,
                "speed_limit_sensors_enabled": dict(enabled_sensors),
                "ranges_cm": readings,
                "throttle": 0.0,
                "reason": "an independent stop/brake condition has priority",
            }
            return command

        if nearest_distance is None or nearest_distance >= trigger_distance:
            if self._active or self._brake_active:
                self._pid.reset()
            self._active = False
            self._brake_active = False
            clear_reason = (
                "approach-speed limiting is disabled for all range sensors"
                if not any(enabled_sensors.values())
                else "no enabled ultrasonic sensor reports an object inside the speed-limit range"
            )
            self._snapshot = {
                "state": "clear",
                "brake_to_target_enabled": brake_to_target_enabled,
                "target_speed_kmh": target_speed,
                "measured_speed_kmh": self._valid_speed(
                    getattr(frame, "speed_kmh", None)
                ) if frame is not None else None,
                "nearest_sensor": nearest_sensor,
                "nearest_distance_cm": nearest_distance,
                "speed_limit_distance_cm": trigger_distance,
                "speed_limit_sensors_enabled": dict(enabled_sensors),
                "ranges_cm": readings,
                "throttle": None,
                "reason": clear_reason,
            }
            return command

        sensor_status = getattr(frame, "sensor_status", {}) if frame is not None else {}
        if isinstance(sensor_status, dict) and sensor_status.get("speed_available") is False:
            measured_speed = None
        else:
            measured_speed = self._valid_speed(
                getattr(frame, "speed_kmh", None) if frame is not None else None
            )

        if measured_speed is None:
            self._pid.reset()
            self._active = False
            self._brake_active = False
            self._snapshot = {
                "state": "speed_unavailable",
                "brake_to_target_enabled": brake_to_target_enabled,
                "target_speed_kmh": target_speed,
                "measured_speed_kmh": None,
                "nearest_sensor": nearest_sensor,
                "nearest_distance_cm": nearest_distance,
                "speed_limit_distance_cm": trigger_distance,
                "speed_limit_sensors_enabled": dict(enabled_sensors),
                "ranges_cm": readings,
                "throttle": 0.0,
                "reason": "AVIS speed feedback unavailable while an object is inside the speed-limit range; holding zero speed command",
            }
            return _brake(
                command,
                "AVIS obstacle approach: speed feedback unavailable; holding safe stop",
            )

        if not brake_to_target_enabled:
            self._brake_active = False
        elif self._brake_active:
            # Keep the AVIS zero-speed command latched until measured speed
            # reaches the configured approach speed.
            if measured_speed <= target_speed:
                self._brake_active = False
                self._pid.reset()
        elif measured_speed > target_speed + 0.5:
            # Add a small engage margin to avoid toggling on speed sensor noise.
            self._brake_active = True
            self._pid.reset()

        if self._brake_active:
            self._active = False
            reason = (
                "AVIS obstacle approach: brake command active; measured speed "
                "{:.1f} km/h is above target {:.1f} km/h".format(
                    measured_speed, target_speed
                )
            )
            self._snapshot = {
                "state": "approach_speed_braking",
                "brake_to_target_enabled": True,
                "target_speed_kmh": target_speed,
                "measured_speed_kmh": round(measured_speed, 2),
                "nearest_sensor": nearest_sensor,
                "nearest_distance_cm": round(nearest_distance, 1),
                "speed_limit_distance_cm": trigger_distance,
                "speed_limit_sensors_enabled": dict(enabled_sensors),
                "ranges_cm": {key: round(value, 1) for key, value in readings.items()},
                "throttle": 0.0,
                "brake": 1.0,
                "reason": reason,
            }
            return _brake(command, reason)

        if not self._active:
            self._pid.reset()
            self._active = True

        throttle_ceiling = max(0.0, min(
            float(command.throttle),
            float(getattr(self.config, "SIMULATOR_THROTTLE_LIMIT", 1.0)),
            1.0,
        ))
        self._pid.limit_min = 0.0
        self._pid.limit_max = throttle_ceiling
        throttle = self._pid.update(target_speed - measured_speed, now=now)
        throttle = max(0.0, min(throttle_ceiling, throttle))

        reason = (
            "AVIS obstacle speed limit: {} sensor, target {:.1f} km/h below {:.0f} cm".format(
                nearest_sensor, target_speed, trigger_distance
            )
        )
        self._snapshot = {
            "state": "approach_speed_control",
            "brake_to_target_enabled": brake_to_target_enabled,
            "target_speed_kmh": target_speed,
            "measured_speed_kmh": round(measured_speed, 2),
            "nearest_sensor": nearest_sensor,
            "nearest_distance_cm": round(nearest_distance, 1),
            "speed_limit_distance_cm": trigger_distance,
            "speed_limit_sensors_enabled": dict(enabled_sensors),
            "ranges_cm": {key: round(value, 1) for key, value in readings.items()},
            "throttle": round(throttle, 3),
            "reason": reason,
        }
        return VehicleCommand(
            steering=command.steering,
            throttle=throttle,
            brake=command.brake,
            servo_angle=command.servo_angle,
            target_speed=command.target_speed,
            reason=reason,
        )

    def snapshot(self):
        return dict(self._snapshot)


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
    REJOIN_LANE_FOLLOW = "rejoin_lane_follow"
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
        self.direct_steering_distance_cm = 0.0
        self.pass_started_at = 0.0
        self.return_clear_observations = 0
        self.roi_confirmations = 0
        self.clear_observations = 0
        self.awaiting_clear = False
        self.last_ranges = {"left": None, "front": None, "right": None}
        self.last_reason = "obstacle avoidance idle"
        self.last_maneuver_roi = None
        self.return_steering_history = deque(maxlen=100)
        self._last_observed_track_ids = {}
        self._handoff_plan = None
        self._handoff_sequence = 0
        self._handoff_token_namespace = uuid.uuid4().hex
        self._handoff_missed_frames = 0

    def _number(self, key, default):
        try:
            value = float(getattr(self.config, key, default))
        except (TypeError, ValueError, OverflowError):
            return float(default)
        return value if math.isfinite(value) else float(default)

    def _roi_confirmation_enabled(self):
        configured = bool(getattr(
            self.config, "SIMULATOR_OBSTACLE_ROI_CONFIRMATION_ENABLED", True
        ))
        # Hall-backed AVIS bypasses must confirm the destination ROI and keep
        # following it through rejoin; skipping this stage can end the return
        # immediately after the direct steering timer expires.
        return (
            configured
            or self._hall_handoff_enabled()
            or self._hall_tracking_without_identity_handoff()
        )

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
        if state in {self.SHIFT_LEFT_DIRECT, self.SHIFT_RIGHT_DIRECT}:
            self.direct_steering_distance_cm = 0.0
        if state == self.BLOCKED:
            self.clear_observations = 0
        if state in {self.PASS_LANE_FOLLOW, self.REJOIN_LANE_FOLLOW}:
            self.pass_started_at = now
            self.return_steering_history.clear()
            self.return_clear_observations = 0
        if state == self.CLEAR:
            self.selected_side = None
            self._handoff_plan = None
        if state == self.BLOCKED:
            self._handoff_plan = None
        if previous != state:
            logger.info("AVIS obstacle maneuver: %s -> %s (%s)", previous, state, reason)

    def _record_passing_lane_steering(self, command):
        """Record the lane controller's normalized output as signed AVIS percent."""
        try:
            steering = float(command.steering)
        except (TypeError, ValueError, OverflowError):
            return
        if math.isfinite(steering):
            self.return_steering_history.append(
                max(-1.0, min(1.0, steering)) * 100.0
            )

    def _return_steering_gate_stats(self):
        enabled = bool(getattr(
            self.config, "SIMULATOR_OBSTACLE_RETURN_STEERING_GATE_ENABLED", False
        ))
        window = max(1, min(
            100,
            self._integer("SIMULATOR_OBSTACLE_RETURN_STEERING_SAMPLE_COUNT", 10),
        ))
        minimum = max(-100.0, min(
            100.0,
            self._number("SIMULATOR_OBSTACLE_RETURN_STEERING_MIN_PERCENT", -10.0),
        ))
        maximum = max(-100.0, min(
            100.0,
            self._number("SIMULATOR_OBSTACLE_RETURN_STEERING_MAX_PERCENT", 10.0),
        ))
        if minimum >= maximum:
            minimum, maximum = -10.0, 10.0
        samples = list(self.return_steering_history)[-window:]
        mean = sum(samples) / len(samples) if samples else None
        enough_samples = len(samples) >= window
        ready = bool(
            enough_samples and mean is not None and minimum <= mean <= maximum
        )
        return {
            "enabled": enabled,
            "window": window,
            "sample_count": len(samples),
            "mean_percent": mean,
            "minimum_percent": minimum,
            "maximum_percent": maximum,
            "ready": ready,
            "enough_samples": enough_samples,
        }

    def _hall_handoff_enabled(self):
        """Whether this AVIS profile can use the paired Hall/Hough handoff path."""
        return bool(getattr(self.config, "SIMULATOR_OBSTACLE_HALL_HANDOFF_ENABLED", False)) and not bool(
            getattr(self.config, "OLD_METHOD", False)
        ) and str(getattr(self.config, "SIMULATOR_BACKEND", "avis")).lower() == "avis" and str(
            getattr(self.config, "CITY_LANE_DETECTOR", "default")
).lower().find("blsf") < 0 and not bool(
            getattr(self.config, "USE_ML_LANE_DETECTOR", False)
        )

    def _hall_tracking_without_identity_handoff(self):
        """Keep Hall tracking anchored to the bypass lane when identity transfer is off."""
        return (
            bool(getattr(self.config, "HALL_LINE_TRACKING_ENABLED", False))
            and not bool(getattr(self.config, "OLD_METHOD", False))
            and str(getattr(self.config, "SIMULATOR_BACKEND", "avis")).lower() == "avis"
            and str(getattr(self.config, "CITY_LANE_DETECTOR", "default")).lower().find("blsf") < 0
            and not bool(getattr(self.config, "USE_ML_LANE_DETECTOR", False))
            and not self._hall_handoff_enabled()
        )

    def _remember_lane_tracking(self, lane_tracking):
        if not isinstance(lane_tracking, dict):
            return
        for side in ("left", "right"):
            boundary = lane_tracking.get(side)
            if not isinstance(boundary, dict) or not boundary.get("observed"):
                continue
            track_id = boundary.get("track_id")
            if track_id is not None:
                try:
                    self._last_observed_track_ids[side] = int(track_id)
                except (TypeError, ValueError, OverflowError):
                    continue

    def _refresh_handoff_expected_track(self, lane_tracking):
        if not isinstance(self._handoff_plan, dict) or not isinstance(lane_tracking, dict):
            return False
        details = lane_tracking.get("hall_handoff")
        if not isinstance(details, dict) or details.get("transfer_ok"):
            return False
        if details.get("token") != self._handoff_plan.get("token"):
            return False
        source_side = self._handoff_plan.get("source_side")
        source = lane_tracking.get(source_side)
        if not isinstance(source, dict) or not source.get("observed"):
            return False
        try:
            current_track_id = int(source.get("track_id"))
        except (TypeError, ValueError, OverflowError):
            return False

        previous_track_id = self._handoff_plan.get("expected_track_id")
        if previous_track_id != current_track_id:
            logger.info(
                "AVIS Hall handoff source track refreshed: %s %s -> %s",
                source_side, previous_track_id, current_track_id,
            )
        self._handoff_plan["expected_track_id"] = current_track_id
        self._last_observed_track_ids[source_side] = current_track_id
        return True

    def _start_hall_handoff(self, source_side, target_side):
        self._handoff_sequence += 1
        expected_track_id = self._last_observed_track_ids.get(source_side)
        self._handoff_missed_frames = 0
        self._handoff_plan = {
            "enabled": True,
            "source_side": source_side,
            "target_side": target_side,
            "token": f"{self._handoff_token_namespace}:{self._handoff_sequence}",
            "expected_track_id": expected_track_id,
        }
        logger.info(
            "AVIS Hall ROI handoff armed: %s -> %s (track_id=%s, token=%s)",
            source_side, target_side, expected_track_id,
            self._handoff_plan["token"],
        )
        return self._handoff_plan

    def _handoff_anchor_available(self, maneuver_roi, target_side):
        """Allow a short detector gap, then fail closed if the handed-off line vanishes."""
        locked = bool(
            isinstance(maneuver_roi, dict)
            and maneuver_roi.get("side") == target_side
            and maneuver_roi.get("observed")
            and maneuver_roi.get("handoff_locked")
        )
        if locked:
            self._handoff_missed_frames = 0
            return True
        self._handoff_missed_frames += 1
        return self._handoff_missed_frames <= 2

    def prepare_vision(self, now=None):
        """Publish the temporary ROI owner before the next camera frame is parsed."""
        hall_handoff = self._hall_handoff_enabled()
        pair = None
        if self.state in {
            self.SEARCH_LEFT_ROI, self.PASS_LANE_FOLLOW, self.SHIFT_RIGHT_DIRECT
        }:
            pair = ("left", "right")
        elif self.state in {self.SEARCH_RIGHT_ROI, self.REJOIN_LANE_FOLLOW}:
            pair = ("right", "left")

        active_roi = None
        descriptor = None
        if pair and hall_handoff:
            if (
                not isinstance(self._handoff_plan, dict)
                or self._handoff_plan.get("source_side") != pair[0]
                or self._handoff_plan.get("target_side") != pair[1]
            ):
                self._start_hall_handoff(*pair)
            descriptor = dict(self._handoff_plan)
            active_roi = pair[1]
        elif (
            self.state == self.SEARCH_LEFT_ROI
            and self._roi_confirmation_enabled()
        ) or (
            self.state == self.PASS_LANE_FOLLOW
            and self._hall_tracking_without_identity_handoff()
        ):
            # The left-side Hall ROI is the only independent anchor for the
            # passing lane when cross-ROI identity handoff is disabled. Keep
            # it active for the entire PASS phase instead of reverting to the
            # original pair of lane ROIs immediately after confirmation.
            active_roi = "left"
        elif (
            self.state in {self.SEARCH_RIGHT_ROI, self.REJOIN_LANE_FOLLOW}
            and self._roi_confirmation_enabled()
        ):
            # Keep the confirmed original-lane boundary in its maneuver ROI
            # until the lane controller has completed the rejoin interval.
            active_roi = "right"

        self.config.SIMULATOR_ACTIVE_OBSTACLE_ROI = active_roi
        self.config.SIMULATOR_ACTIVE_OBSTACLE_HALL_HANDOFF = descriptor
        self.config.SIMULATOR_ACTIVE_OBSTACLE_BYPASS = bool(
            getattr(self.config, "SIMULATOR_OBSTACLE_AVOIDANCE_ENABLED", False)
            and self.state not in {self.CLEAR, self.BLOCKED}
        )
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
        throttle_cap_max = (
            1.0 if str(getattr(self.config, "MODE", "")).strip().lower() == "avis" else 0.25
        )
        throttle_cap = max(
            0.0,
            min(throttle_cap_max, self._number("SIMULATOR_OBSTACLE_THROTTLE_LIMIT", 0.08)),
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
        self.config.SIMULATOR_ACTIVE_OBSTACLE_HALL_HANDOFF = None
        return _brake(command, reason)

    def _advance_after_direct_steering(self, side, now, search_state, reason):
        if self._roi_confirmation_enabled():
            self._set_state(search_state, now, reason + f"; enabling {side} maneuver ROI")
            return

        self.last_maneuver_roi = None
        if side == "left":
            self._set_state(
                self.PASS_LANE_FOLLOW,
                now,
                reason + "; ML ROI confirmation disabled, handing control to normal lane following",
            )
        else:
            self.awaiting_clear = True
            self.clear_observations = 0
            self._set_state(
                self.CLEAR,
                now,
                reason + "; MR ROI confirmation disabled, restoring normal lane detection",
            )
        self.config.SIMULATOR_ACTIVE_OBSTACLE_ROI = None
        self.config.SIMULATOR_ACTIVE_OBSTACLE_HALL_HANDOFF = None

    def _direct_phase(self, command, side, now, delay, search_state):
        elapsed = max(0.0, now - self.state_since)
        is_direct_state = self.state in {self.SHIFT_LEFT_DIRECT, self.SHIFT_RIGHT_DIRECT}
        distance_mode = bool(getattr(
            self.config, "SIMULATOR_OBSTACLE_USE_DISTANCE_MODE", False
        ))
        if is_direct_state and distance_mode:
            target_distance = max(
                1.0,
                min(2000.0, self._number(
                    "SIMULATOR_OBSTACLE_DIRECT_STEERING_DISTANCE_CM", 100.0
                )),
            )
            watchdog_seconds = max(
                0.2,
                min(10.0, self._number("SIMULATOR_OBSTACLE_PASS_TIMEOUT_SECONDS", 4.0)),
            )
            if self.direct_steering_distance_cm >= target_distance:
                self._advance_after_direct_steering(
                    side,
                    now,
                    search_state,
                    f"{side} direct steering travelled {self.direct_steering_distance_cm:.1f} cm "
                    f"(target {target_distance:.1f} cm)",
                )
            elif elapsed >= watchdog_seconds:
                self._set_state(
                    self.BLOCKED,
                    now,
                    f"{side} direct steering did not reach {target_distance:.1f} cm "
                    f"within the {watchdog_seconds:.1f} s safety timeout; braking",
                )
                return self._brake(command, self.last_reason)
        elif is_direct_state and elapsed >= delay:
            self._advance_after_direct_steering(
                side,
                now,
                search_state,
                f"{side} direct steering time elapsed after {elapsed:.2f} s",
            )
        if self.state == search_state and not self._roi_confirmation_enabled():
            self._advance_after_direct_steering(
                side,
                now,
                search_state,
                f"{side} maneuver ROI confirmation disabled while searching",
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
        self._remember_lane_tracking(lane_tracking)
        self._refresh_handoff_expected_track(lane_tracking)
        hall_handoff = self._hall_handoff_enabled()
        ranges = ranges if isinstance(ranges, dict) else {}
        self.last_ranges = {
            key: _finite_range(ranges.get(key))
            for key in ("left", "front", "right")
        }
        front = self.last_ranges["front"]
        left = self.last_ranges["left"]
        right = self.last_ranges["right"]

        if self.state in {self.SHIFT_LEFT_DIRECT, self.SHIFT_RIGHT_DIRECT}:
            try:
                distance_delta = float(distance_delta_cm)
            except (TypeError, ValueError, OverflowError):
                distance_delta = 0.0
            if math.isfinite(distance_delta) and distance_delta > 0.0:
                self.direct_steering_distance_cm += distance_delta

        if self._handoff_plan is not None and not hall_handoff:
            self._set_state(
                self.BLOCKED, now,
                "Hall tracking was disabled or the active detector changed during a lane handoff; braking",
            )
            return self._brake(command, self.last_reason)

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
        clear_confirm_frames = max(
            1, min(20, self._integer("SIMULATOR_OBSTACLE_CLEAR_CONFIRM_FRAMES", 3))
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
                if self.clear_observations >= clear_confirm_frames:
                    self.clear_observations = 0
                    self.awaiting_clear = False
                    self._set_state(
                        self.CLEAR, now,
                        "forward clearance restored; maneuver controller re-armed",
                    )
                    self.config.SIMULATOR_ACTIVE_OBSTACLE_ROI = None
                else:
                    return self._brake(
                        command,
                        f"waiting for clear front range ({self.clear_observations}/{clear_confirm_frames} observations)",
                    )
            else:
                self.clear_observations = 0
                return self._brake(command, self.last_reason)

        if self.state == self.CLEAR:
            if self.awaiting_clear:
                if front >= clear_distance:
                    self.clear_observations += 1
                    if self.clear_observations >= clear_confirm_frames:
                        self.awaiting_clear = False
                        self.clear_observations = 0
                    else:
                        self.last_reason = (
                            f"waiting for clear front range before re-arming "
                            f"({self.clear_observations}/{clear_confirm_frames} observations)"
                        )
                        return command
                else:
                    self.clear_observations = 0
                    self.last_reason = (
                        f"waiting for the previous obstacle to clear before re-arming "
                        f"(0/{clear_confirm_frames} observations)"
                    )
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
            if hall_handoff:
                left_boundary = lane_tracking.get("left") if isinstance(lane_tracking, dict) else None
                try:
                    lane_width = float(lane_tracking.get("lane_width_px"))
                except (AttributeError, TypeError, ValueError, OverflowError):
                    lane_width = 0.0
                if (
                    not isinstance(left_boundary, dict)
                    or not left_boundary.get("observed")
                    or left_boundary.get("track_id") is None
                    or not math.isfinite(lane_width)
                    or lane_width <= 0.0
                ):
                    self._set_state(
                        self.BLOCKED, now,
                        "Hall bypass requires an observed left boundary and a calibrated lane-width model; braking",
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

        if self.state in {
            self.SHIFT_RIGHT_DIRECT, self.SEARCH_RIGHT_ROI, self.REJOIN_LANE_FOLLOW
        }:
            if right is None or right < minimum_side:
                self.return_clear_observations = 0
                return self._brake(
                    command,
                    "right-return paused until side clearance is restored "
                    f"(right range {right if right is not None else 'unavailable'} cm; "
                    f"required at least {minimum_side:.1f} cm)",
                )
            self.return_clear_observations += 1
            if self.return_clear_observations < clear_confirm_frames:
                return self._brake(
                    command,
                    "right-return waiting for consecutive side-clearance observations "
                    f"({self.return_clear_observations}/{clear_confirm_frames})",
                )

        if self.state == self.SHIFT_LEFT_DIRECT:
            return self._direct_phase(
                command, "left", now, roi_delay, self.SEARCH_LEFT_ROI
            )

        if self.state == self.SEARCH_LEFT_ROI:
            expected_side = "right" if hall_handoff else "left"
            observed = (
                isinstance(maneuver_roi, dict)
                and maneuver_roi.get("side") == expected_side
                and bool(maneuver_roi.get("observed"))
                and bool(perception_valid)
                and (
                    not hall_handoff
                    or bool(maneuver_roi.get("handoff_locked"))
                )
            )
            self.roi_confirmations = self.roi_confirmations + 1 if observed else 0
            self.last_maneuver_roi = expected_side if observed else None
            if self.roi_confirmations >= confirm_frames:
                self._set_state(
                    self.PASS_LANE_FOLLOW, now,
                    (
                        "Hall handoff locked the right ROI onto the previous left boundary; "
                        "following the passing lane with the lane controller"
                        if hall_handoff
                        else "left maneuver ROI confirmed a lane; handing steering back to lane PID"
                    ),
                )
                self._record_passing_lane_steering(command)
                self.config.SIMULATOR_ACTIVE_OBSTACLE_ROI = expected_side
                return command
            return self._direct_phase(
                command, "left", now, roi_delay, self.SEARCH_LEFT_ROI
            )

        if self.state == self.PASS_LANE_FOLLOW:
            passing_lane_roi = (
                "left" if self._hall_tracking_without_identity_handoff() else None
            )
            if hall_handoff and not self._handoff_anchor_available(maneuver_roi, "right"):
                self._set_state(
                    self.BLOCKED, now,
                    "Hall right-ROI handoff lost the tracked boundary for too many frames; braking",
                )
                return self._brake(command, self.last_reason)
            if not perception_valid or command.brake >= 0.5:
                self._set_state(
                    self.BLOCKED, now,
                    "passing-lane perception was lost; stopping instead of driving blind",
                )
                return self._brake(command, self.last_reason)

            # Only normal lane-following outputs enter this history; direct
            # bypass steering is never included in the return-stability mean.
            self._record_passing_lane_steering(command)
            hold_complete = now - self.pass_started_at >= lane_hold
            gate = self._return_steering_gate_stats()
            gate_max_wait = max(
                0.5,
                min(30.0, self._number(
                    "SIMULATOR_OBSTACLE_RETURN_STEERING_MAX_WAIT_SECONDS", 4.0
                )),
            )
            gate_wait_elapsed = max(0.0, now - self.pass_started_at - lane_hold)
            gate_timed_out = bool(
                hold_complete and gate["enabled"] and not gate["ready"]
                and gate_wait_elapsed >= gate_max_wait
            )

            if (
                hold_complete and gate["enabled"] and not gate["ready"]
                and not gate_timed_out
            ):
                mean_text = (
                    "collecting samples" if gate["mean_percent"] is None
                    else f"{gate['mean_percent']:+.1f}%"
                )
                self.last_reason = (
                    f"minimum passing-lane time complete; waiting for the mean of "
                    f"the last {gate['window']} lane steering commands to enter "
                    f"[{gate['minimum_percent']:+.1f}, {gate['maximum_percent']:+.1f}]% "
                    f"(current mean {mean_text}, {gate['sample_count']}/{gate['window']} samples; "
                    f"{gate_wait_elapsed:.1f}/{gate_max_wait:.1f}s maximum wait)"
                )
                self.config.SIMULATOR_ACTIVE_OBSTACLE_ROI = passing_lane_roi
                self.config.SIMULATOR_ACTIVE_OBSTACLE_HALL_HANDOFF = None
                return command

            if hold_complete:
                if right is None or right < minimum_side:
                    self.return_clear_observations = 0
                    self.last_reason = (
                        "passing-lane hold complete; continuing to follow the passing lane "
                        "until right-side clearance is proven "
                        f"(right range {right if right is not None else 'unavailable'} cm; "
                        f"required at least {minimum_side:.1f} cm)"
                    )
                    self.config.SIMULATOR_ACTIVE_OBSTACLE_ROI = passing_lane_roi
                    self.config.SIMULATOR_ACTIVE_OBSTACLE_HALL_HANDOFF = None
                    return command

                self.return_clear_observations += 1
                if self.return_clear_observations < clear_confirm_frames:
                    self.last_reason = (
                        "right-side clearance detected; confirming before return "
                        f"({self.return_clear_observations}/{clear_confirm_frames} observations)"
                    )
                    self.config.SIMULATOR_ACTIVE_OBSTACLE_ROI = passing_lane_roi
                    self.config.SIMULATOR_ACTIVE_OBSTACLE_HALL_HANDOFF = None
                    return command

                return_reason = (
                    "passing-lane hold and right-side clearance confirmed "
                    f"({self.return_clear_observations} observations)"
                )
                if gate["enabled"] and gate["ready"]:
                    return_reason += (
                        f"; mean steering {gate['mean_percent']:+.1f}% is inside "
                        f"[{gate['minimum_percent']:+.1f}, {gate['maximum_percent']:+.1f}]%"
                    )
                elif gate_timed_out:
                    return_reason += (
                        f"; steering-mean gate timed out after {gate_max_wait:.1f}s "
                        f"(mean {gate['mean_percent'] if gate['mean_percent'] is not None else 'unavailable'}%)"
                    )
                if hall_handoff and self._last_observed_track_ids.get("right") is None:
                    self._set_state(
                        self.BLOCKED, now,
                        "Hall return handoff has no confirmed right-boundary identity; braking",
                    )
                    return self._brake(command, self.last_reason)
                return_reason += "; beginning direct right return"
                self._set_state(self.SHIFT_RIGHT_DIRECT, now, return_reason)
                self.selected_side = "right"
                self.config.SIMULATOR_ACTIVE_OBSTACLE_ROI = None
                direct_reason = "obstacle lane change: direct right steering"
                if self.return_clear_observations >= clear_confirm_frames:
                    direct_reason += "; right-side clearance confirmed"
                if gate["enabled"] and gate["ready"]:
                    direct_reason += (
                        f"; mean steering {gate['mean_percent']:+.1f}% is inside "
                        f"[{gate['minimum_percent']:+.1f}, {gate['maximum_percent']:+.1f}]%"
                    )
                if gate_timed_out:
                    direct_reason += (
                        f" (return steering gate timed out after {gate_max_wait:.1f}s)"
                    )
                return self._direct_command(command, "right", direct_reason)

            self.last_reason = (
                "obstacle lane change: following the passing lane with normal lane PID"
            )
            # When Hall identity handoff is disabled, keep using the left
            # maneuver ROI as the passing-lane anchor. Other detector paths
            # continue with their ordinary lane-following ROI configuration.
            self.config.SIMULATOR_ACTIVE_OBSTACLE_ROI = passing_lane_roi
            self.config.SIMULATOR_ACTIVE_OBSTACLE_HALL_HANDOFF = None
            return command

        if self.state == self.SHIFT_RIGHT_DIRECT:
            if hall_handoff and not self._handoff_anchor_available(maneuver_roi, "right"):
                self._set_state(
                    self.BLOCKED, now,
                    "Hall right-ROI handoff was lost during the return steer; braking",
                )
                return self._brake(command, self.last_reason)
            return self._direct_phase(
                command, "right", now, roi_delay, self.SEARCH_RIGHT_ROI
            )

        if self.state == self.SEARCH_RIGHT_ROI:
            expected_side = "left" if hall_handoff else "right"
            observed = (
                isinstance(maneuver_roi, dict)
                and maneuver_roi.get("side") == expected_side
                and bool(maneuver_roi.get("observed"))
                and bool(perception_valid)
                and (
                    not hall_handoff
                    or bool(maneuver_roi.get("handoff_locked"))
                )
            )
            self.roi_confirmations = self.roi_confirmations + 1 if observed else 0
            self.last_maneuver_roi = expected_side if observed else None
            if self.roi_confirmations >= confirm_frames:
                if hall_handoff:
                    reason = (
                        "Hall handoff locked the left ROI onto the boundary tracked "
                        "by the right ROI; following the original lane"
                    )
                    rejoin_roi = "left"
                else:
                    reason = (
                        "right maneuver ROI confirmed the original lane; following "
                        "it with the lane controller before restoring normal ROIs"
                    )
                    rejoin_roi = "right"
                self._set_state(self.REJOIN_LANE_FOLLOW, now, reason)
                self._record_passing_lane_steering(command)
                self.config.SIMULATOR_ACTIVE_OBSTACLE_ROI = rejoin_roi
                return command
            return self._direct_phase(
                command, "right", now, roi_delay, self.SEARCH_RIGHT_ROI
            )

        if self.state == self.REJOIN_LANE_FOLLOW:
            if hall_handoff and not self._handoff_anchor_available(maneuver_roi, "left"):
                self._set_state(
                    self.BLOCKED, now,
                    "Hall left-ROI handoff lost the tracked boundary for too many frames; braking",
                )
                return self._brake(command, self.last_reason)
            if not perception_valid or command.brake >= 0.5:
                self._set_state(
                    self.BLOCKED, now,
                    "original-lane handoff perception was lost; stopping instead of driving blind",
                )
                return self._brake(command, self.last_reason)

            self._record_passing_lane_steering(command)
            hold_complete = now - self.pass_started_at >= lane_hold
            gate = self._return_steering_gate_stats()
            gate_max_wait = max(
                0.5,
                min(30.0, self._number(
                    "SIMULATOR_OBSTACLE_RETURN_STEERING_MAX_WAIT_SECONDS", 4.0
                )),
            )
            gate_wait_elapsed = max(0.0, now - self.pass_started_at - lane_hold)
            gate_timed_out = bool(
                hold_complete and gate["enabled"] and not gate["ready"]
                and gate_wait_elapsed >= gate_max_wait
            )
            if (
                hold_complete and gate["enabled"] and not gate["ready"]
                and not gate_timed_out
            ):
                mean_text = (
                    "collecting samples" if gate["mean_percent"] is None
                    else f"{gate['mean_percent']:+.1f}%"
                )
                self.last_reason = (
                    f"minimum original-lane follow time complete; waiting for the mean of "
                    f"the last {gate['window']} steering commands to enter "
                    f"[{gate['minimum_percent']:+.1f}, {gate['maximum_percent']:+.1f}]% "
                    f"(current mean {mean_text}, {gate['sample_count']}/{gate['window']} samples; "
                    f"{gate_wait_elapsed:.1f}/{gate_max_wait:.1f}s maximum wait)"
                )
                self.config.SIMULATOR_ACTIVE_OBSTACLE_ROI = None
                self.config.SIMULATOR_ACTIVE_OBSTACLE_HALL_HANDOFF = None
                return command

            if hold_complete:
                reason = "original-lane follow interval completed"
                if gate["enabled"] and gate["ready"]:
                    reason += (
                        f"; mean steering {gate['mean_percent']:+.1f}% is inside "
                        f"[{gate['minimum_percent']:+.1f}, {gate['maximum_percent']:+.1f}]%"
                    )
                elif gate_timed_out:
                    reason += f"; steering-mean gate timed out after {gate_max_wait:.1f}s"
                reason += "; restoring both normal lane ROIs"
                self.awaiting_clear = True
                self.clear_observations = 0
                self._set_state(self.CLEAR, now, reason)
                self.config.SIMULATOR_ACTIVE_OBSTACLE_ROI = None
                self.config.SIMULATOR_ACTIVE_OBSTACLE_HALL_HANDOFF = None
                return command

            self.last_reason = (
                "obstacle lane change: following the original lane with the handed-off left boundary"
                if hall_handoff else
                "obstacle lane change: following the original lane in the confirmed right maneuver ROI"
            )
            self.config.SIMULATOR_ACTIVE_OBSTACLE_ROI = None
            self.config.SIMULATOR_ACTIVE_OBSTACLE_HALL_HANDOFF = None
            return command

        self.config.SIMULATOR_ACTIVE_OBSTACLE_ROI = None
        self.config.SIMULATOR_ACTIVE_OBSTACLE_HALL_HANDOFF = None
        return command

    def snapshot(self):
        active_roi = self.prepare_vision()
        direction = (
            "left" if self.state in {
                self.SHIFT_LEFT_DIRECT, self.SEARCH_LEFT_ROI, self.PASS_LANE_FOLLOW
            } else "right" if self.state in {
                self.SHIFT_RIGHT_DIRECT, self.SEARCH_RIGHT_ROI, self.REJOIN_LANE_FOLLOW
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
        return_gate = self._return_steering_gate_stats()
        hold_elapsed = (
            max(0.0, time.monotonic() - self.pass_started_at)
            if self.state in {self.PASS_LANE_FOLLOW, self.REJOIN_LANE_FOLLOW} else 0.0
        )
        return_gate_max_wait = max(
            0.5,
            min(30.0, self._number(
                "SIMULATOR_OBSTACLE_RETURN_STEERING_MAX_WAIT_SECONDS", 4.0
            )),
        )
        return_gate_wait_elapsed = max(0.0, hold_elapsed - lane_hold)
        return_gate_timed_out = bool(
            self.state in {self.PASS_LANE_FOLLOW, self.REJOIN_LANE_FOLLOW}
            and hold_elapsed >= lane_hold
            and return_gate["enabled"]
            and not return_gate["ready"]
            and return_gate_wait_elapsed >= return_gate_max_wait
        )
        return_gate_waiting = bool(
            self.state in {self.PASS_LANE_FOLLOW, self.REJOIN_LANE_FOLLOW}
            and hold_elapsed >= lane_hold
            and return_gate["enabled"]
            and not return_gate["ready"]
            and not return_gate_timed_out
        )
        minimum_side = max(
            1.0, self._number("SIMULATOR_OBSTACLE_SIDE_CLEARANCE_CM", 75.0)
        )
        clear_confirmations = max(
            1, min(20, self._integer("SIMULATOR_OBSTACLE_CLEAR_CONFIRM_FRAMES", 3))
        )
        right_range = self.last_ranges.get("right")
        right_return_active = self.state in {
            self.PASS_LANE_FOLLOW, self.SHIFT_RIGHT_DIRECT,
            self.SEARCH_RIGHT_ROI, self.REJOIN_LANE_FOLLOW,
        }
        return_clearance_waiting = bool(
            right_return_active
            and (
                self.state != self.PASS_LANE_FOLLOW
                or hold_elapsed >= lane_hold
            )
            and (
                right_range is None or right_range < minimum_side
                or self.return_clear_observations < clear_confirmations
            )
        )
        return {
            "enabled": bool(getattr(self.config, "SIMULATOR_OBSTACLE_AVOIDANCE_ENABLED", False)),
            "state": self.state,
            "direction": direction,
            "active_maneuver_roi": active_roi,
            "hall_handoff_enabled": self._hall_handoff_enabled(),
            "hall_handoff": dict(self._handoff_plan) if self._handoff_plan else None,
            "hall_handoff_missed_frames": int(self._handoff_missed_frames),
            "roi_confirmations": int(self.roi_confirmations),
            "roi_confirmation_enabled": self._roi_confirmation_enabled(),
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
            "direct_steering_distance_mode": bool(getattr(
                self.config, "SIMULATOR_OBSTACLE_USE_DISTANCE_MODE", False
            )),
            "direct_steering_distance_cm": round(self.direct_steering_distance_cm, 1),
            "direct_steering_target_distance_cm": self._number(
                "SIMULATOR_OBSTACLE_DIRECT_STEERING_DISTANCE_CM", 100.0
            ),
            "direct_steering_watchdog_seconds": self._number(
                "SIMULATOR_OBSTACLE_PASS_TIMEOUT_SECONDS", 4.0
            ),
            "lane_hold_seconds": lane_hold,
            "lane_hold_elapsed_seconds": min(lane_hold, hold_elapsed),
            "return_steering_gate_enabled": return_gate["enabled"],
            "return_steering_sample_window": return_gate["window"],
            "return_steering_sample_count": return_gate["sample_count"],
            "return_steering_mean_percent": return_gate["mean_percent"],
            "return_steering_min_percent": return_gate["minimum_percent"],
            "return_steering_max_percent": return_gate["maximum_percent"],
            "return_steering_gate_ready": return_gate["ready"],
            "return_steering_gate_waiting": return_gate_waiting,
            "return_steering_gate_timed_out": return_gate_timed_out,
            "return_steering_gate_max_wait_seconds": return_gate_max_wait,
            "return_steering_gate_wait_seconds": (
                min(return_gate_max_wait, return_gate_wait_elapsed)
                if return_gate_waiting else 0.0
            ),
            "return_clearance_waiting": return_clearance_waiting,
            "return_clear_observations": int(self.return_clear_observations),
            "return_clear_observations_required": clear_confirmations,
            "return_minimum_side_clearance_cm": minimum_side,
            "ranges_cm": dict(self.last_ranges),
            "front_clear_observations": int(self.clear_observations),
            "front_clear_observations_required": max(
                1, min(20, self._integer("SIMULATOR_OBSTACLE_CLEAR_CONFIRM_FRAMES", 3))
            ),
            "awaiting_obstacle_clear": bool(self.awaiting_clear),
            "reason": self.last_reason,
        }

class AVISBehaviorCoordinator:
    """Coordinates optional AVIS City/Race behavior without physical I/O."""

    CROSSWALK_STOP_SPEED_KMH = 0.5
    CROSSWALK_STOP_CONFIRM_FRAMES = 3

    def __init__(self, config, vision_profile):
        self.config = config
        self.vision_profile = str(vision_profile).lower()
        self.is_city = self.vision_profile == "city"
        self.is_avis_city = (
            self.is_city
            and str(getattr(config, "SIMULATOR_BACKEND", "")).strip().lower() == "avis"
            and str(getattr(config, "MODE", "")).strip().lower() == "avis"
        )
        self.obstacles = RangeObstacleAvoidance(config)
        self.approach_speed = AVISObstacleApproachSpeedController(config)
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
        self.last_stop_line_detection = {"detected": False, "confidence": 0.0, "bbox": None}
        self.last_traffic_light_detections = []
        self.last_frame_token = None
        self.stop_sign_until = 0.0
        self.park_latched = False
        self.turn_direction = 0.0
        self.turn_until = 0.0
        self.last_sign_label = None
        self.last_direction_sign_label = None
        self.last_direction_sign_at = None
        self._last_turn_nudge_log_label = None
        self._last_sign_request_id = 0
        self._sign_frame_count = 0
        self._sign_blank_count = 0
        self.sign_detector = None
        self._sign_error = None
        self.last_sign_roi_status = {
            "valid": False,
            "reason": "waiting for the first sign frame",
        }
        self._last_sign_roi_error = None
        self.crosswalk_state = "idle"
        self.crosswalk_detect_count = 0
        self.crosswalk_stop_confirm_count = 0
        self.crosswalk_measured_speed_kmh = None
        self.crosswalk_absent_count = 0
        self.crosswalk_latched = False
        self.crosswalk_started_at = None
        self.crosswalk_route_name = None
        self.crosswalk_route_sign = None
        self.crosswalk_pending_sign = None
        self.crosswalk_route_frozen = False
        self.crosswalk_steps = []
        self.crosswalk_step_index = 0
        self.crosswalk_step_progress_cm = 0.0
        self.crosswalk_step_started_at = None
        self.crosswalk_reason = "crosswalk hardcode idle"

        self.deadlock_state = "idle"
        self.deadlock_abort_stop_pending = False
        self.deadlock_candidate = None
        self.deadlock_confirm_count = 0
        self.deadlock_clear_count = 0
        self.deadlock_last_frame_token = None
        self.deadlock_route = None
        self.deadlock_steps = []
        self.deadlock_step_index = 0
        self.deadlock_step_progress_cm = 0.0
        self.deadlock_step_started_at = None
        self.deadlock_reason = "deadlock detection disabled"
        self.deadlock_diagnostics = {
            "roi_valid": False,
            "reason": "waiting for the first AVIS City frame",
            "crosswalk_horizontal_lines": 0,
            "required_horizontal_lines": 1,
            "left_lane_lines": 0,
            "right_lane_lines": 0,
            "candidate": None,
        }

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

    @staticmethod
    def _deadlock_crop_roi(image, prefix, config):
        """Crop a normalized CW/ML/MR rectangle from the raw AVIS camera frame."""
        if image is None or not hasattr(image, "shape") or len(image.shape) < 2:
            return None, {"valid": False, "reason": "camera image is unavailable"}
        height, width = image.shape[:2]
        if height <= 0 or width <= 0:
            return None, {"valid": False, "reason": "camera image has invalid dimensions"}
        try:
            top = float(getattr(config, prefix + "_TOP_ROI"))
            bottom = float(getattr(config, prefix + "_BOTTOM_ROI"))
            left = float(getattr(config, prefix + "_LEFT_ROI"))
            right = float(getattr(config, prefix + "_RIGHT_ROI"))
        except (AttributeError, TypeError, ValueError, OverflowError):
            return None, {"valid": False, "reason": prefix + " ROI coordinates are unavailable"}
        if not all(math.isfinite(value) for value in (top, bottom, left, right)):
            return None, {"valid": False, "reason": prefix + " ROI coordinates are not finite"}
        if not (0.0 <= top < bottom <= 1.0 and 0.0 <= left < right <= 1.0):
            return None, {"valid": False, "reason": prefix + " ROI bounds are invalid"}
        x1, x2 = int(left * width), int(right * width)
        y1, y2 = int(top * height), int(bottom * height)
        crop = image[y1:y2, x1:x2]
        if crop.size == 0:
            return None, {"valid": False, "reason": prefix + " ROI crop is empty"}
        return crop, {
            "valid": True, "top": top, "bottom": bottom, "left": left, "right": right,
            "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "width": int(crop.shape[1]), "height": int(crop.shape[0]),
        }

    def _deadlock_horizontal_line_count(self, roi):
        """Count horizontal CW segments with the City's configured detector thresholds."""
        import cv2
        import numpy as np

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        threshold = max(0, min(255, int(getattr(self.config, "CROSSWALK_THRESHOLD", 180))))
        canny_low = max(0, min(255, int(getattr(self.config, "CROSSWALK_CANNY_LOW_THRESHOLD", 100))))
        canny_high = max(canny_low + 1, min(255, int(getattr(self.config, "CROSSWALK_CANNY_HIGH_THRESHOLD", 150))))
        _, binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
        edges = cv2.Canny(binary, canny_low, canny_high)

        # Match the City crosswalk mask so the same CW editor settings affect
        # both the normal crosswalk detector and this deadlock condition.
        if bool(getattr(self.config, "CW_TRAPEZOID_MODE", False)):
            height, width = roi.shape[:2]
            factor = max(0.0, min(
                1.0, float(getattr(self.config, "CW_TOP_WIDTH_FACTOR", 0.90))
            ))
            inset = int(width * (1.0 - factor) / 2.0)
            mask = np.zeros((height, width), dtype=np.uint8)
            polygon = np.array(
                [[inset, 0], [width - inset, 0], [width - 1, height - 1], [0, height - 1]],
                dtype=np.int32,
            )
            cv2.fillPoly(mask, [polygon], 255)
            edges = cv2.bitwise_and(edges, edges, mask=mask)

        if bool(getattr(self.config, "CW_OLD_METHOD", False)):
            lines = cv2.createLineSegmentDetector(0).detect(edges)[0]
        else:
            lines = cv2.HoughLinesP(
                edges,
                1,
                np.pi / 180,
                threshold=max(1, int(getattr(self.config, "CROSSWALK_HOUGH_THRESHOLD", 20))),
                minLineLength=max(1, int(getattr(self.config, "CROSSWALK_HOUGH_MIN_LINE_LENGTH", 5))),
                maxLineGap=max(0, int(getattr(self.config, "CROSSWALK_HOUGH_MAX_LINE_GAP", 5))),
            )

        height, width = roi.shape[:2]
        minimum_length = max(
            math.hypot(width, height) * max(
                0.01, min(1.0, float(getattr(self.config, "CROSSWALK_MIN_LINE_LENGTH_RATIO", 0.10)))
            ),
            max(1, int(getattr(self.config, "CROSSWALK_MIN_LINE_LENGTH_PX", 10))),
        )
        angle_tolerance = max(
            1.0,
            min(44.0, float(getattr(self.config, "CROSSWALK_LINE_ANGLE_TOLERANCE_DEG", 30))),
        )
        horizontal_count = 0
        if lines is not None:
            for line in lines:
                coordinates = np.asarray(line).reshape(-1)
                if coordinates.size != 4:
                    continue
                x1, y1, x2, y2 = [float(value) for value in coordinates]
                length = math.hypot(x2 - x1, y2 - y1)
                if length < minimum_length:
                    continue
                angle = abs(math.degrees(math.atan((y2 - y1) / (x2 - x1 + 1e-6))))
                if angle <= angle_tolerance:
                    horizontal_count += 1
        return horizontal_count

    def _deadlock_lane_line_count(self, roi):
        """Use the City's lane ROI preprocessing and Hough settings on ML or MR."""
        import cv2
        import numpy as np

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        if bool(getattr(self.config, "OLD_METHOD", False)):
            _, binary = cv2.threshold(
                gray, max(0, min(255, int(getattr(self.config, "LANE_THRESHOLD", 180)))),
                255, cv2.THRESH_BINARY,
            )
            edges = cv2.Canny(binary, 100, 150)
        else:
            blur_kernel = max(1, min(15, int(getattr(self.config, "HOUGH_BLUR_KERNEL", 3))))
            if blur_kernel > 1 and blur_kernel % 2 == 0:
                blur_kernel += 1
            if blur_kernel > 1:
                gray = cv2.GaussianBlur(gray, (blur_kernel, blur_kernel), 0)
            sobel_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
            sobel_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
            magnitude = cv2.convertScaleAbs(cv2.magnitude(sobel_x, sobel_y))
            _, edges = cv2.threshold(
                magnitude, max(0, min(255, int(getattr(self.config, "LANE_THRESHOLD", 180)))),
                255, cv2.THRESH_BINARY,
            )
            if bool(getattr(self.config, "HOUGH_MORPH_CLOSE", True)):
                edges = cv2.morphologyEx(
                    edges, cv2.MORPH_CLOSE, np.ones((3, 3), dtype=np.uint8), iterations=1
                )

        lines = cv2.HoughLinesP(
            edges,
            1,
            np.pi / 180,
            threshold=max(1, int(getattr(self.config, "HOUGH_THRESHOLD", 15))),
            minLineLength=max(1, int(getattr(self.config, "HOUGH_MIN_LINE_LENGTH", 5))),
            maxLineGap=max(0, int(getattr(self.config, "HOUGH_MAX_LINE_GAP", 20))),
        )
        if lines is None:
            return 0

        height, width = roi.shape[:2]
        minimum_length = max(
            5.0,
            math.hypot(width, height) * 0.06,
            float(max(1, int(getattr(self.config, "HOUGH_MIN_LINE_LENGTH", 5)))),
        )
        count = 0
        for line in lines:
            coordinates = np.asarray(line).reshape(-1)
            if coordinates.size != 4:
                continue
            x1, y1, x2, y2 = [float(value) for value in coordinates]
            length = math.hypot(x2 - x1, y2 - y1)
            angle = abs(math.degrees(math.atan2(y2 - y1, x2 - x1)))
            angle = min(angle, abs(180.0 - angle))
            # Ignore nearly-horizontal crosswalk stripes in the side ROIs;
            # lane-boundary evidence must be meaningfully slanted/vertical.
            if length >= minimum_length and angle >= 25.0:
                count += 1
        return count

    def _inspect_deadlock_pattern(self, frame):
        image = getattr(frame, "image", None) if frame is not None else None
        cw_roi, cw_status = self._deadlock_crop_roi(image, "CW", self.config)
        ml_roi, ml_status = self._deadlock_crop_roi(image, "ML", self.config)
        mr_roi, mr_status = self._deadlock_crop_roi(image, "MR", self.config)
        diagnostics = {
            "roi_valid": bool(cw_roi is not None and ml_roi is not None and mr_roi is not None),
            "cw_roi": cw_status,
            "ml_roi": ml_status,
            "mr_roi": mr_status,
            "crosswalk_horizontal_lines": 0,
            "required_horizontal_lines": max(
                1, int(getattr(self.config, "CROSSWALK_HORIZONTAL_MIN_LINES", 3))
            ),
            "left_lane_lines": 0,
            "right_lane_lines": 0,
            "left_has_line": False,
            "right_has_line": False,
            "candidate": None,
            "reason": "one or more deadlock ROIs are invalid",
        }
        if cw_roi is None or ml_roi is None or mr_roi is None:
            return None, diagnostics
        try:
            horizontal = self._deadlock_horizontal_line_count(cw_roi)
            left_lines = self._deadlock_lane_line_count(ml_roi)
            right_lines = self._deadlock_lane_line_count(mr_roi)
        except Exception as exc:
            diagnostics["reason"] = "ROI line extraction failed: {}: {}".format(
                type(exc).__name__, exc
            )
            return None, diagnostics

        required_horizontal = diagnostics["required_horizontal_lines"]
        left_present = left_lines >= 1
        right_present = right_lines >= 1
        candidate = None
        if horizontal >= required_horizontal:
            # A boundary found only on the right means the left side is the
            # available escape direction; the inverse pattern selects right.
            if right_present and not left_present:
                candidate = "left"
            elif left_present and not right_present:
                candidate = "right"

        diagnostics.update({
            "roi_valid": True,
            "crosswalk_horizontal_lines": int(horizontal),
            "left_lane_lines": int(left_lines),
            "right_lane_lines": int(right_lines),
            "left_has_line": bool(left_present),
            "right_has_line": bool(right_present),
            "candidate": candidate,
            "reason": (
                "right ROI has a lane line and left ROI is clear"
                if candidate == "left" else
                "left ROI has a lane line and right ROI is clear"
                if candidate == "right" else
                "crosswalk horizontal threshold or one-sided lane-line condition is not met"
            ),
        })
        return candidate, diagnostics

    def _start_deadlock_route(self, direction, now):
        self.deadlock_route = direction
        try:
            route_data = json.loads(str(getattr(
                self.config,
                "SIMULATOR_DEADLOCK_ROUTE_CHAINS",
                '{"left":[],"right":[]}',
            )))
            if not isinstance(route_data, dict):
                raise ValueError("route configuration must be an object")
            steps = route_data.get(direction, [])
            if not isinstance(steps, list):
                raise ValueError("route steps must be a list")
            self.deadlock_steps = list(steps)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            self.deadlock_steps = []
            self.deadlock_state = "blocked"
            self.deadlock_reason = "deadlock route configuration is invalid: " + str(exc)
            logger.exception("AVIS deadlock route configuration failed")
            return

        self.deadlock_step_index = 0
        self.deadlock_step_progress_cm = 0.0
        self.deadlock_step_started_at = now
        self.deadlock_clear_count = 0
        if not self.deadlock_steps:
            self.deadlock_state = "blocked"
            self.deadlock_reason = (
                "deadlock detected toward {}; no hardcode steps are configured"
            ).format(direction.upper())
            logger.error(
                "AVIS DEADLOCK CONFIRMED: maneuver=%s but its hardcode route is empty; holding brake",
                direction.upper(),
            )
            return

        self.deadlock_state = "running"
        first = self.deadlock_steps[0]
        self.deadlock_reason = "deadlock {} maneuver started".format(direction)
        logger.warning(
            "AVIS DEADLOCK CONFIRMED: maneuver=%s steps=%d confirmation=%d/%d; "
            "first_step=%s direction=%s distance_m=%s speed_percent=%s steering_percent=%s",
            direction.upper(), len(self.deadlock_steps), self.deadlock_confirm_count,
            max(1, min(20, int(getattr(self.config, "SIMULATOR_DEADLOCK_CONFIRM_FRAMES", 4)))),
            1, first.get("direction"), first.get("distance_m"),
            first.get("speed_percent"), first.get("steering_percent"),
        )

    def _observe_deadlock(self, frame, command, now):
        """Confirm the CW + one-sided ML/MR line pattern on consecutive AVIS City frames."""
        enabled = bool(
            self.is_avis_city
            and getattr(self.config, "SIMULATOR_DEADLOCK_ENABLED", False)
        )
        if not enabled:
            self.deadlock_candidate = None
            self.deadlock_confirm_count = 0
            self.deadlock_clear_count = 0
            if self.deadlock_state == "running":
                # Disabling the feature aborts the configured maneuver. Apply
                # one explicit brake cycle before returning to ordinary lane follow.
                self.deadlock_abort_stop_pending = True
                self.deadlock_reason = "deadlock maneuver aborted by operator; braking once before returning to lane follow"
                logger.error("AVIS deadlock maneuver aborted because its enable setting was switched off")
            else:
                self.deadlock_state = "idle"
                self.deadlock_route = None
                self.deadlock_steps = []
                self.deadlock_step_index = 0
                self.deadlock_step_progress_cm = 0.0
                self.deadlock_step_started_at = None
                self.deadlock_reason = "deadlock detection disabled"
            return

        if frame is None:
            return
        token = getattr(frame, "sequence", None) or getattr(frame, "captured_at", None)
        if token == self.deadlock_last_frame_token:
            return
        self.deadlock_last_frame_token = token

        candidate, diagnostics = self._inspect_deadlock_pattern(frame)
        self.deadlock_diagnostics = diagnostics

        if self.deadlock_state == "running":
            return
        if self.deadlock_state in {"completed", "blocked"}:
            if candidate is None:
                self.deadlock_clear_count += 1
                if self.deadlock_clear_count >= 8:
                    previous = self.deadlock_state
                    self.deadlock_state = "idle"
                    self.deadlock_route = None
                    self.deadlock_steps = []
                    self.deadlock_step_index = 0
                    self.deadlock_step_progress_cm = 0.0
                    self.deadlock_step_started_at = None
                    self.deadlock_candidate = None
                    self.deadlock_confirm_count = 0
                    self.deadlock_clear_count = 0
                    self.deadlock_reason = "deadlock pattern cleared; detector re-armed"
                    logger.info("AVIS deadlock detector re-armed after %d clear frames (previous=%s)", 8, previous)
            else:
                self.deadlock_clear_count = 0
            return

        safety_hold = (
            self.crosswalk_latched
            or self.crosswalk_state in {"braking", "stopping", "holding", "waiting_for_green", "running"}
            or self.traffic_light_hold
            or self.stop_line_waiting
            or self.park_latched
            or now < self.stop_sign_until
            or command.brake >= 0.5
            or self.obstacles.state != RangeObstacleAvoidance.CLEAR
        )
        if safety_hold:
            self.deadlock_candidate = None
            self.deadlock_confirm_count = 0
            self.deadlock_clear_count = 0
            diagnostics["reason"] = "deadlock confirmation paused by a higher-priority safety behavior"
            return

        required = max(
            1, min(20, int(getattr(self.config, "SIMULATOR_DEADLOCK_CONFIRM_FRAMES", 4)))
        )
        if candidate is None:
            self.deadlock_candidate = None
            self.deadlock_confirm_count = 0
            self.deadlock_clear_count = 0
            return

        if candidate == self.deadlock_candidate:
            self.deadlock_confirm_count += 1
        else:
            self.deadlock_candidate = candidate
            self.deadlock_confirm_count = 1

        logger.info(
            "AVIS deadlock candidate: direction=%s confirmation=%d/%d "
            "CW_horizontal=%d/%d ML_lines=%d MR_lines=%d",
            candidate.upper(), self.deadlock_confirm_count, required,
            diagnostics["crosswalk_horizontal_lines"],
            diagnostics["required_horizontal_lines"],
            diagnostics["left_lane_lines"], diagnostics["right_lane_lines"],
        )
        if self.deadlock_confirm_count >= required:
            self._start_deadlock_route(candidate, now)

    def _deadlock_route_command(self, command, distance_delta_cm, now):
        """Run the configured distance-based deadlock maneuver after frame confirmation."""
        if self.deadlock_abort_stop_pending:
            self.deadlock_abort_stop_pending = False
            self.deadlock_state = "idle"
            self.deadlock_route = None
            self.deadlock_steps = []
            self.deadlock_step_index = 0
            self.deadlock_step_progress_cm = 0.0
            self.deadlock_step_started_at = None
            return _brake(command, self.deadlock_reason)
        if self.deadlock_state == "blocked":
            return _brake(command, self.deadlock_reason)
        if self.deadlock_state != "running":
            return None
        if self.deadlock_step_index >= len(self.deadlock_steps):
            self.deadlock_state = "completed"
            self.deadlock_reason = "deadlock {} maneuver completed".format(self.deadlock_route)
            logger.info("%s", self.deadlock_reason)
            return None

        step = self.deadlock_steps[self.deadlock_step_index]
        try:
            target_cm = float(step["distance_m"]) * 100.0
            speed = float(step["speed_percent"]) / 100.0
            steering = float(step["steering_percent"]) / 100.0
            direction = str(step["direction"]).lower()
        except (KeyError, TypeError, ValueError, OverflowError):
            self.deadlock_state = "blocked"
            self.deadlock_reason = "deadlock hardcode blocked: route step values are invalid"
            logger.exception("AVIS deadlock route step is invalid")
            return _brake(command, self.deadlock_reason)

        if (
            direction not in {"forward", "reverse"}
            or not all(math.isfinite(value) for value in (target_cm, speed, steering))
            or target_cm <= 0
            or not 0 < speed <= 1
            or not -1 <= steering <= 1
        ):
            self.deadlock_state = "blocked"
            self.deadlock_reason = "deadlock hardcode blocked: route step is outside allowed limits"
            logger.error("%s", self.deadlock_reason)
            return _brake(command, self.deadlock_reason)

        try:
            delta = float(distance_delta_cm or 0.0)
        except (TypeError, ValueError, OverflowError):
            delta = 0.0
        if math.isfinite(delta) and delta > 0:
            self.deadlock_step_progress_cm += delta

        if self.deadlock_step_progress_cm >= target_cm:
            completed_step = self.deadlock_step_index + 1
            self.deadlock_step_index += 1
            self.deadlock_step_progress_cm = 0.0
            self.deadlock_step_started_at = now
            if self.deadlock_step_index >= len(self.deadlock_steps):
                self.deadlock_state = "completed"
                self.deadlock_reason = "deadlock {} maneuver completed".format(self.deadlock_route)
                logger.info(
                    "AVIS deadlock maneuver completed: direction=%s steps=%d",
                    self.deadlock_route, completed_step,
                )
                return None
            step = self.deadlock_steps[self.deadlock_step_index]
            target_cm = float(step["distance_m"]) * 100.0
            speed = float(step["speed_percent"]) / 100.0
            steering = float(step["steering_percent"]) / 100.0
            direction = str(step["direction"]).lower()
            logger.info(
                "AVIS deadlock maneuver step started: direction=%s step=%d/%d "
                "travel=%s distance_m=%s speed_percent=%s steering_percent=%s",
                self.deadlock_route, self.deadlock_step_index + 1, len(self.deadlock_steps),
                direction, step.get("distance_m"), step.get("speed_percent"),
                step.get("steering_percent"),
            )

        timeout = max(
            1.0, float(getattr(self.config, "SIMULATOR_DEADLOCK_STEP_TIMEOUT_SECONDS", 15.0))
        )
        elapsed = max(0.0, now - float(self.deadlock_step_started_at or now))
        if elapsed >= timeout and self.deadlock_step_progress_cm < target_cm:
            self.deadlock_state = "blocked"
            self.deadlock_reason = (
                "deadlock hardcode blocked: step {} did not reach its distance within {:.1f}s"
            ).format(self.deadlock_step_index + 1, elapsed)
            logger.error("%s", self.deadlock_reason)
            return _brake(command, self.deadlock_reason)

        throttle_limit = max(
            0.0, min(1.0, float(getattr(self.config, "SIMULATOR_THROTTLE_LIMIT", 0.35)))
        )
        throttle = min(speed, throttle_limit)
        if throttle <= 0:
            self.deadlock_state = "blocked"
            self.deadlock_reason = "deadlock hardcode blocked: global throttle limit is zero"
            logger.error("%s", self.deadlock_reason)
            return _brake(command, self.deadlock_reason)

        steering_limit = max(
            0.05, min(1.0, float(getattr(self.config, "SIMULATOR_STEERING_LIMIT", 1.0)))
        )
        steering = max(-steering_limit, min(steering_limit, steering))
        if bool(getattr(self.config, "SIMULATOR_STEERING_INVERTED", False)):
            steering = -steering
        servo_min = float(getattr(self.config, "MIN_SERVO_ANGLE", 55.0))
        servo_center = float(getattr(self.config, "SERVO_CENTER", 95.0))
        servo_max = float(getattr(self.config, "MAX_SERVO_ANGLE", 125.0))
        servo_angle = (
            servo_center + steering * (servo_max - servo_center)
            if steering >= 0 else servo_center + steering * (servo_center - servo_min)
        )
        signed_throttle = throttle if direction == "forward" else -throttle
        self.deadlock_reason = (
            "deadlock {} maneuver step {}/{} · {:.0f}/{:.0f}cm"
        ).format(
            self.deadlock_route, self.deadlock_step_index + 1,
            len(self.deadlock_steps), self.deadlock_step_progress_cm, target_cm,
        )
        return VehicleCommand(
            steering=steering, throttle=signed_throttle, brake=0.0,
            servo_angle=servo_angle, target_speed=0.0, reason=self.deadlock_reason,
        )

    def _crop_sign_roi(self, image):
        """Crop the configured normalized ST rectangle before AVIS YOLO inference."""
        if image is None or not hasattr(image, "shape") or len(image.shape) < 2:
            return None, {"valid": False, "reason": "camera image is unavailable"}

        height, width = image.shape[:2]
        if height <= 0 or width <= 0:
            return None, {"valid": False, "reason": "camera image has invalid dimensions"}

        try:
            top = float(getattr(self.config, "ST_TOP_ROI", 0.0))
            bottom = float(getattr(self.config, "ST_BOTTOM_ROI", 1.0))
            left = float(getattr(self.config, "ST_LEFT_ROI", 0.0))
            right = float(getattr(self.config, "ST_RIGHT_ROI", 1.0))
        except (TypeError, ValueError, OverflowError):
            return None, {"valid": False, "reason": "sign ROI coordinates are not numeric"}

        if not all(math.isfinite(value) for value in (top, bottom, left, right)):
            return None, {"valid": False, "reason": "sign ROI coordinates are not finite"}
        if not (0.0 <= top < bottom <= 1.0 and 0.0 <= left < right <= 1.0):
            return None, {"valid": False, "reason": "sign ROI bounds are invalid"}

        y1, y2 = int(top * height), int(bottom * height)
        x1, x2 = int(left * width), int(right * width)
        if x2 <= x1 or y2 <= y1:
            return None, {"valid": False, "reason": "sign ROI crop is empty"}

        cropped = image[y1:y2, x1:x2]
        if cropped.size == 0:
            return None, {"valid": False, "reason": "sign ROI crop is empty"}

        return cropped, {
            "valid": True,
            "top": top,
            "bottom": bottom,
            "left": left,
            "right": right,
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "width": int(cropped.shape[1]),
            "height": int(cropped.shape[0]),
        }

    def submit_sign_frame(self, frame):
        if self.sign_detector is None or frame is None:
            return
        sign_image, roi_status = self._crop_sign_roi(getattr(frame, "image", None))
        self.last_sign_roi_status = roi_status
        if sign_image is None:
            reason = roi_status.get("reason")
            if self._last_sign_roi_error != reason:
                logger.error("AVIS sign inference skipped: %s", reason)
            self._last_sign_roi_error = reason
            return
        self._last_sign_roi_error = None

        interval = max(1, int(getattr(self.config, "SIMULATOR_SIGN_SCAN_INTERVAL", 6)))
        self._sign_frame_count += 1
        if self._sign_frame_count % interval == 0:
            try:
                self.sign_detector.submit(
                    sign_image.copy(),
                    frame_captured_at=getattr(frame, "captured_at", None),
                )
            except Exception:
                logger.debug("Could not submit AVIS sign ROI frame", exc_info=True)
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

        # Repeated observations are still meaningful. Refresh timed STOP/TURN
        # actions on every fresh inference instead of ignoring an unchanged label.
        previous_label = self.last_sign_label
        self._sign_blank_count = 0
        self.last_sign_label = label
        now = time.monotonic()
        direction_labels = {"TURN LEFT", "TURN RIGHT", "STRAIGHT", "LEFT", "RIGHT"}
        if label in direction_labels:
            self.last_direction_sign_label = label
            self.last_direction_sign_at = now
            if (
                self.crosswalk_state in {"braking", "stopping", "holding", "waiting_for_green"}
                and not self.crosswalk_route_frozen
                and (
                    self.crosswalk_pending_sign != label
                    or self.crosswalk_route_name is None
                )
            ):
                self.crosswalk_pending_sign = label
                self._load_crosswalk_route(label, frozen=False)

        hold = max(
            0.1,
            float(getattr(self.config, "SIMULATOR_SIGN_STOP_HOLD_SECONDS", 2.0)),
        )
        turn_hold = max(
            0.1,
            float(getattr(self.config, "SIMULATOR_SIGN_TURN_HOLD_SECONDS", 0.6)),
        )
        if label == "STOP":
            self.stop_sign_until = max(self.stop_sign_until, now + hold)
        elif label == "PARK":
            self.park_latched = True
            self.turn_direction = 0.0
            self.turn_until = 0.0
        elif label in {"TURN LEFT", "LEFT"}:
            self.turn_direction = -1.0
            self.turn_until = now + turn_hold
        elif label in {"TURN RIGHT", "RIGHT"}:
            self.turn_direction = 1.0
            self.turn_until = now + turn_hold
        elif label == "STRAIGHT":
            self.park_latched = False
            self.turn_direction = 0.0
            self.turn_until = 0.0

        if previous_label != label:
            logger.info(
                "AVIS sign action accepted: %s (confidence %.3f)",
                label, confidence,
            )
        else:
            logger.debug(
                "AVIS sign action refreshed: %s (confidence %.3f)",
                label, confidence,
            )

    def _observe_road_rules(self, frame, now):
        if not self.is_city or frame is None:
            return
        token = getattr(frame, "sequence", None) or getattr(frame, "captured_at", None)
        if token == self.last_frame_token:
            return
        self.last_frame_token = token

        line_detected = False
        self.last_stop_line_detection = {"detected": False, "confidence": 0.0, "bbox": None}
        if self.stop_line_detector is not None:
            try:
                line_result = self.stop_line_detector.detect(frame.image)
                line_detected = bool(line_result.get("detected"))
                bbox = line_result.get("bbox")
                self.last_stop_line_detection = {
                    "detected": line_detected,
                    "confidence": float(line_result.get("confidence", 0.0) or 0.0),
                    "bbox": list(bbox) if isinstance(bbox, (list, tuple)) else None,
                }
            except Exception:
                logger.exception("AVIS stop-line detector failed; retaining any active stop")
                line_detected = False
                self.last_stop_line_detection = {"detected": False, "confidence": 0.0, "bbox": None}

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
                self.last_traffic_light_detections = [
                    dict(item) for item in getattr(self.traffic_detector, "last_detections", [])
                    if isinstance(item, dict)
                ]
            except Exception:
                logger.exception("AVIS traffic-light detector failed; treating signal as unknown")
                color = None
                self.last_traffic_light_detections = []
            self.last_light_color = color
            if color == "RED" and not self.traffic_light_hold:
                self.traffic_light_hold = True
                if self.green_window:
                    self.green_window.reset()
            crosswalk_waiting_for_green = (
                self.crosswalk_latched and self.crosswalk_state == "waiting_for_green"
            )
            if self.green_window and (
                self.traffic_light_hold or self.stop_line_waiting or crosswalk_waiting_for_green
            ):
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

    def _load_crosswalk_route(self, label=None, *, frozen=False):
        """Load the route for the newest direction sign; freeze only at release."""
        selected_label = label
        if selected_label is None:
            selected_label = (
                self.last_direction_sign_label
                or self.last_sign_label
                or "NO DIRECTION SIGN"
            )
        selected_label = str(selected_label or "NO DIRECTION SIGN").strip().upper()
        route_name = self._crosswalk_route_for_latest_sign(selected_label)
        try:
            route_data = json.loads(str(getattr(
                self.config,
                "SIMULATOR_CROSSWALK_ROUTE_CHAINS",
                '{"left":[],"straight":[],"right":[]}',
            )))
            if not isinstance(route_data, dict):
                raise ValueError("route configuration must be an object")
            route_steps = route_data.get(route_name, [])
            if not isinstance(route_steps, list):
                raise ValueError("route steps must be a list")
            steps = list(route_steps)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            steps = []
            self.crosswalk_reason = (
                "crosswalk hardcode blocked: invalid route configuration ({})"
            ).format(exc)

        self.crosswalk_route_sign = selected_label
        self.crosswalk_route_name = route_name
        self.crosswalk_steps = steps
        self.crosswalk_step_index = 0
        self.crosswalk_step_progress_cm = 0.0
        self.crosswalk_step_started_at = None
        self.crosswalk_route_frozen = bool(frozen)
        sign_age = (
            max(0.0, time.monotonic() - self.last_direction_sign_at)
            if self.last_direction_sign_at is not None else None
        )
        logger.log(
            logging.WARNING if frozen else logging.INFO,
            "AVIS City crosswalk route %s: sign=%s route=%s steps=%d "
            "direction_sign_age_s=%s",
            "LOCKED" if frozen else "candidate",
            selected_label,
            route_name,
            len(steps),
            "{:.2f}".format(sign_age) if sign_age is not None else "unknown",
        )
        return bool(steps)

    def _crosswalk_route_for_latest_sign(self, label=None):
        selected_label = self.last_sign_label if label is None else label
        label = str(selected_label or "").strip().upper()
        if label in {"TURN LEFT", "LEFT"}:
            return "left"
        if label in {"TURN RIGHT", "RIGHT"}:
            return "right"
        return "straight"

    def _observe_crosswalk(self, perception, now):
        """Debounce one City crosswalk and latch it until its route clears."""
        enabled = bool(
            self.is_city
            and getattr(self.config, "SIMULATOR_CROSSWALK_HARDCODE_ENABLED", True)
        )
        if not enabled:
            self.crosswalk_detect_count = 0
            if not self.crosswalk_latched and self.crosswalk_state == "braking":
                self.crosswalk_state = "idle"
                self.crosswalk_stop_confirm_count = 0
                self.crosswalk_reason = "crosswalk hardcode disabled before route confirmation"
            if self.crosswalk_latched and self.crosswalk_state in {"stopping", "holding", "waiting_for_green", "running"}:
                self.crosswalk_state = "blocked"
                self.crosswalk_reason = (
                    "crosswalk hardcode disabled during an active route; "
                    "vehicle remains stopped until the crossing clears"
                )
                logger.error("%s", self.crosswalk_reason)
            return
        detected = bool((perception or {}).get("crosswalk", False))
        if not detected:
            self.crosswalk_detect_count = 0
            if not self.crosswalk_latched and self.crosswalk_state == "braking":
                self.crosswalk_state = "idle"
                self.crosswalk_stop_confirm_count = 0
                self.crosswalk_pending_sign = None
                self.crosswalk_reason = "crosswalk hardcode detection cleared before confirmation"
            if self.crosswalk_latched and self.crosswalk_state in {"completed", "blocked"}:
                self.crosswalk_absent_count += 1
                if self.crosswalk_absent_count >= 8:
                    logger.info("AVIS City crosswalk cleared; releasing route latch (%s)", self.crosswalk_route_name)
                    self.crosswalk_state = "idle"
                    self.crosswalk_latched = False
                    self.crosswalk_started_at = None
                    self.crosswalk_route_name = None
                    self.crosswalk_route_sign = None
                    self.crosswalk_pending_sign = None
                    self.crosswalk_route_frozen = False
                    self.crosswalk_steps = []
                    self.crosswalk_step_index = 0
                    self.crosswalk_step_progress_cm = 0.0
                    self.crosswalk_step_started_at = None
                    self.crosswalk_stop_confirm_count = 0
                    self.crosswalk_measured_speed_kmh = None
                    self.crosswalk_reason = "crosswalk hardcode idle"
                    self.crosswalk_absent_count = 0
            return
        self.crosswalk_absent_count = 0
        if self.crosswalk_latched:
            return
        self.crosswalk_detect_count += 1
        required = max(1, min(20, int(getattr(self.config, "SIMULATOR_CROSSWALK_CONFIRM_FRAMES", 3))))
        if self.crosswalk_detect_count == 1:
            # Start stopping on the first positive detector frame. Confirmation
            # delays route selection only; it must never delay the stop command.
            self.crosswalk_state = "braking"
            self.crosswalk_stop_confirm_count = 0
            self.crosswalk_started_at = None
            self.crosswalk_pending_sign = str(
                self.last_direction_sign_label or self.last_sign_label or "NO DIRECTION SIGN"
            )
            self.crosswalk_route_frozen = False
            self.crosswalk_reason = (
                "crosswalk hardcode braking while confirming detection (1/{})"
            ).format(required)
        if self.crosswalk_detect_count < required:
            self.crosswalk_reason = (
                "crosswalk hardcode braking while confirming detection ({}/{})"
            ).format(self.crosswalk_detect_count, required)
            return

        self.crosswalk_latched = True
        self.crosswalk_state = "stopping"
        self.crosswalk_started_at = None
        self.crosswalk_stop_confirm_count = 0
        self.crosswalk_measured_speed_kmh = None
        self.crosswalk_pending_sign = str(
            self.last_direction_sign_label or self.last_sign_label or "NO DIRECTION SIGN"
        )
        self.crosswalk_route_frozen = False
        self._load_crosswalk_route(self.crosswalk_pending_sign, frozen=False)
        self.crosswalk_reason = "crosswalk hardcode holding before route; sign remains updateable"
        logger.warning(
            "AVIS City crosswalk confirmed (%d frames); stop %.1fs; current sign candidate=%s; "
            "route will be locked only when release is authorized",
            required,
            float(getattr(self.config, "SIMULATOR_CROSSWALK_DWELL_SECONDS", 3.0)),
            self.crosswalk_pending_sign,
        )

    def _crosswalk_route_command(self, frame, command, distance_delta_cm, now):
        """Stop, confirm a full stop, dwell, wait for green, then execute the frozen sign route."""
        if self.crosswalk_state == "braking":
            return _brake(command, self.crosswalk_reason)
        if not self.crosswalk_latched or self.crosswalk_state == "completed":
            return None

        if self.crosswalk_state in {"stopping", "holding"}:
            sensor_status = getattr(frame, "sensor_status", {}) if frame is not None else {}
            speed = None
            if not (isinstance(sensor_status, dict) and sensor_status.get("speed_available") is False):
                speed = _finite_range(getattr(frame, "speed_kmh", None)) if frame is not None else None
            self.crosswalk_measured_speed_kmh = speed
            if speed is None:
                self.crosswalk_state = "stopping"
                self.crosswalk_started_at = None
                self.crosswalk_stop_confirm_count = 0
                self.crosswalk_reason = (
                    "crosswalk hardcode stopping: AVIS speed feedback unavailable; "
                    "zero-speed command remains active"
                )
                return _brake(command, self.crosswalk_reason)
            if speed > self.CROSSWALK_STOP_SPEED_KMH:
                self.crosswalk_state = "stopping"
                self.crosswalk_started_at = None
                self.crosswalk_stop_confirm_count = 0
                self.crosswalk_reason = (
                    "crosswalk hardcode stopping: measured speed {:.1f} km/h; waiting for 0 km/h"
                ).format(speed)
                return _brake(command, self.crosswalk_reason)
            if self.crosswalk_state == "stopping":
                self.crosswalk_stop_confirm_count += 1
                if self.crosswalk_stop_confirm_count < self.CROSSWALK_STOP_CONFIRM_FRAMES:
                    self.crosswalk_reason = (
                        "crosswalk hardcode verifying full stop: {:.1f} km/h ({}/{})"
                    ).format(
                        speed, self.crosswalk_stop_confirm_count,
                        self.CROSSWALK_STOP_CONFIRM_FRAMES,
                    )
                    return _brake(command, self.crosswalk_reason)
                self.crosswalk_state = "holding"
                self.crosswalk_started_at = now
                self.crosswalk_reason = (
                    "crosswalk hardcode vehicle stopped at {:.1f} km/h; dwell started"
                ).format(speed)
                logger.info("AVIS City crosswalk stop confirmed; starting %.1fs dwell",
                            max(0.1, float(getattr(self.config, "SIMULATOR_CROSSWALK_DWELL_SECONDS", 3.0))))
                return _brake(command, self.crosswalk_reason)

        if self.crosswalk_state == "holding":
            dwell = max(0.1, float(getattr(self.config, "SIMULATOR_CROSSWALK_DWELL_SECONDS", 3.0)))
            elapsed = max(0.0, now - float(self.crosswalk_started_at or now))
            if elapsed < dwell:
                self.crosswalk_reason = "crosswalk hardcode holding {}/{}s".format(round(elapsed, 1), round(dwell, 1))
                return _brake(command, self.crosswalk_reason)
            if self.traffic_detector is None or self.green_window is None:
                # Traffic-light detection is a true opt-out: after the normal
                # full-stop dwell, commit the newest direction sign and start its route.
                if not self._load_crosswalk_route(frozen=True):
                    self.crosswalk_state = "blocked"
                    self.crosswalk_reason = (
                        "crosswalk hardcode blocked: no route steps configured for "
                        + str(self.crosswalk_route_name).upper()
                        + "; vehicle remains stopped"
                    )
                    logger.error("%s", self.crosswalk_reason)
                    return _brake(command, self.crosswalk_reason)
                self.crosswalk_state = "running"
                self.crosswalk_step_index = 0
                self.crosswalk_step_progress_cm = 0.0
                self.crosswalk_step_started_at = now
                first_step = self.crosswalk_steps[0]
                logger.info(
                    "AVIS City crosswalk route execution started: sign=%s route=%s "
                    "step=1/%d direction=%s steering_percent=%s speed_percent=%s distance_m=%s",
                    self.crosswalk_route_sign, self.crosswalk_route_name,
                    len(self.crosswalk_steps), first_step.get("direction"),
                    first_step.get("steering_percent"), first_step.get("speed_percent"),
                    first_step.get("distance_m"),
                )
                self.crosswalk_reason = (
                    "crosswalk hardcode traffic-light detection disabled; "
                    "starting {} route after full-stop dwell from sign={}"
                ).format(self.crosswalk_route_name, self.crosswalk_route_sign)
                logger.info(
                    "AVIS City crosswalk dwell complete; traffic-light detection is disabled, "
                    "starting %s route from sign=%s",
                    self.crosswalk_route_name, self.crosswalk_route_sign,
                )
            else:
                self.green_window.reset()
                self.crosswalk_state = "waiting_for_green"
                self.crosswalk_reason = (
                    "crosswalk hardcode dwell complete; waiting for a freshly confirmed GREEN signal"
                )
                logger.info(
                    "AVIS City crosswalk dwell complete; waiting for %d/%d fresh GREEN frames before %s route (sign=%s)",
                    self.green_window.required_green, self.green_window.window_size,
                    self.crosswalk_route_name, self.crosswalk_route_sign,
                )
                return _brake(command, self.crosswalk_reason)

        if self.crosswalk_state == "waiting_for_green":
            if self.traffic_detector is None or self.green_window is None:
                # Also recover safely if detector availability changes while
                # a route is already waiting for green.
                if not self._load_crosswalk_route(frozen=True):
                    self.crosswalk_state = "blocked"
                    self.crosswalk_reason = (
                        "crosswalk hardcode blocked: no route steps configured for "
                        + str(self.crosswalk_route_name).upper()
                        + "; vehicle remains stopped"
                    )
                    logger.error("%s", self.crosswalk_reason)
                    return _brake(command, self.crosswalk_reason)
                self.crosswalk_state = "running"
                self.crosswalk_step_index = 0
                self.crosswalk_step_progress_cm = 0.0
                self.crosswalk_step_started_at = now
                first_step = self.crosswalk_steps[0]
                logger.info(
                    "AVIS City crosswalk route execution started: sign=%s route=%s "
                    "step=1/%d direction=%s steering_percent=%s speed_percent=%s distance_m=%s",
                    self.crosswalk_route_sign, self.crosswalk_route_name,
                    len(self.crosswalk_steps), first_step.get("direction"),
                    first_step.get("steering_percent"), first_step.get("speed_percent"),
                    first_step.get("distance_m"),
                )
                self.crosswalk_reason = (
                    "crosswalk hardcode traffic-light detection disabled; "
                    "starting {} route after full-stop dwell from sign={}"
                ).format(self.crosswalk_route_name, self.crosswalk_route_sign)
                logger.info(
                    "AVIS City crosswalk green gate disabled; starting %s route from sign=%s",
                    self.crosswalk_route_name, self.crosswalk_route_sign,
                )
            elif not self.green_window.confirmed:
                self.crosswalk_reason = (
                    "crosswalk hardcode waiting for GREEN: {}/{} green frames in {}/{} observations"
                ).format(
                    self.green_window.green_count,
                    self.green_window.required_green,
                    len(self.green_window.observations),
                    self.green_window.window_size,
                )
                return _brake(command, self.crosswalk_reason)
            else:
                if not self._load_crosswalk_route(frozen=True):
                    self.crosswalk_state = "blocked"
                    self.crosswalk_reason = (
                        "crosswalk hardcode blocked: no route steps configured for "
                        + str(self.crosswalk_route_name).upper()
                        + "; vehicle remains stopped"
                    )
                    logger.error("%s", self.crosswalk_reason)
                    return _brake(command, self.crosswalk_reason)
                self.crosswalk_state = "running"
                self.crosswalk_step_index = 0
                self.crosswalk_step_progress_cm = 0.0
                self.crosswalk_step_started_at = now
                first_step = self.crosswalk_steps[0]
                logger.info(
                    "AVIS City crosswalk route execution started: sign=%s route=%s "
                    "step=1/%d direction=%s steering_percent=%s speed_percent=%s distance_m=%s",
                    self.crosswalk_route_sign, self.crosswalk_route_name,
                    len(self.crosswalk_steps), first_step.get("direction"),
                    first_step.get("steering_percent"), first_step.get("speed_percent"),
                    first_step.get("distance_m"),
                )
                self.crosswalk_reason = (
                    "crosswalk hardcode GREEN confirmed; starting {} route from sign={}"
                ).format(self.crosswalk_route_name, self.crosswalk_route_sign)
                logger.info(
                    "AVIS City crosswalk GREEN confirmed (%d/%d); starting %s route from sign=%s",
                    self.green_window.green_count, self.green_window.window_size,
                    self.crosswalk_route_name, self.crosswalk_route_sign,
                )

        if self.crosswalk_state == "blocked":
            return _brake(command, self.crosswalk_reason)
        if self.crosswalk_state != "running":
            return None
        if self.crosswalk_step_index >= len(self.crosswalk_steps):
            self.crosswalk_state = "completed"
            self.crosswalk_reason = "crosswalk hardcode route completed"
            return _brake(command, self.crosswalk_reason)

        step = self.crosswalk_steps[self.crosswalk_step_index]
        try:
            target_cm = float(step["distance_m"]) * 100.0
            requested_speed = float(step["speed_percent"]) / 100.0
            steering = float(step["steering_percent"]) / 100.0
            direction = str(step["direction"]).lower()
        except (KeyError, TypeError, ValueError, OverflowError):
            self.crosswalk_state = "blocked"
            self.crosswalk_reason = "crosswalk hardcode blocked: route step values are invalid"
            return _brake(command, self.crosswalk_reason)
        if (direction not in {"forward", "reverse"} or
                not all(math.isfinite(v) for v in (target_cm, requested_speed, steering)) or
                target_cm <= 0 or not 0 < requested_speed <= 1 or not -1 <= steering <= 1):
            self.crosswalk_state = "blocked"
            self.crosswalk_reason = "crosswalk hardcode blocked: route step is outside allowed limits"
            return _brake(command, self.crosswalk_reason)

        try:
            delta = float(distance_delta_cm or 0.0)
        except (TypeError, ValueError, OverflowError):
            delta = 0.0
        if math.isfinite(delta) and delta > 0:
            self.crosswalk_step_progress_cm += delta

        if self.crosswalk_step_progress_cm >= target_cm:
            self.crosswalk_step_index += 1
            self.crosswalk_step_progress_cm = 0.0
            self.crosswalk_step_started_at = now
            if self.crosswalk_step_index >= len(self.crosswalk_steps):
                self.crosswalk_state = "completed"
                self.crosswalk_reason = "crosswalk hardcode route completed"
                logger.info("AVIS City crosswalk route completed: %s", self.crosswalk_route_name)
                return _brake(command, self.crosswalk_reason)
            step = self.crosswalk_steps[self.crosswalk_step_index]
            target_cm = float(step["distance_m"]) * 100.0
            requested_speed = float(step["speed_percent"]) / 100.0
            steering = float(step["steering_percent"]) / 100.0
            direction = str(step["direction"]).lower()

        timeout = max(1.0, float(getattr(self.config, "SIMULATOR_CROSSWALK_STEP_TIMEOUT_SECONDS", 15.0)))
        elapsed = max(0.0, now - float(self.crosswalk_step_started_at or now))
        if elapsed >= timeout and self.crosswalk_step_progress_cm < target_cm:
            self.crosswalk_state = "blocked"
            self.crosswalk_reason = (
                "crosswalk hardcode blocked: step {} did not reach its distance within {:.1f}s"
            ).format(self.crosswalk_step_index + 1, elapsed)
            logger.error("%s", self.crosswalk_reason)
            return _brake(command, self.crosswalk_reason)

        throttle_limit = max(0.0, min(1.0, float(getattr(self.config, "SIMULATOR_THROTTLE_LIMIT", 0.35))))
        throttle = min(requested_speed, throttle_limit)
        if throttle <= 0:
            self.crosswalk_state = "blocked"
            self.crosswalk_reason = "crosswalk hardcode blocked: global throttle limit is zero"
            return _brake(command, self.crosswalk_reason)
        steering_limit = max(0.05, min(1.0, float(getattr(self.config, "SIMULATOR_STEERING_LIMIT", 1.0))))
        steering = max(-steering_limit, min(steering_limit, steering))
        if bool(getattr(self.config, "SIMULATOR_STEERING_INVERTED", False)):
            steering = -steering
        servo_min = float(getattr(self.config, "MIN_SERVO_ANGLE", 55.0))
        servo_center = float(getattr(self.config, "SERVO_CENTER", 95.0))
        servo_max = float(getattr(self.config, "MAX_SERVO_ANGLE", 125.0))
        servo_angle = (
            servo_center + steering * (servo_max - servo_center)
            if steering >= 0 else servo_center + steering * (servo_center - servo_min)
        )
        signed_throttle = throttle if direction == "forward" else -throttle
        self.crosswalk_reason = (
            "crosswalk hardcode {} step {}/{} · {:.0f}/{:.0f}cm"
        ).format(self.crosswalk_route_name, self.crosswalk_step_index + 1,
                 len(self.crosswalk_steps), self.crosswalk_step_progress_cm, target_cm)
        return VehicleCommand(
            steering=steering, throttle=signed_throttle, brake=0.0,
            servo_angle=servo_angle, target_speed=0.0, reason=self.crosswalk_reason,
        )

    def prepare_vision(self, now=None):
        if str(getattr(self.config, "SIMULATOR_BACKEND", "avis")).lower() != "avis":
            return None
        return self.obstacles.prepare_vision(now=now)

    def apply(self, frame, perception, command, *, distance_delta_cm=0.0, now=None):
        if str(getattr(self.config, "SIMULATOR_BACKEND", "avis")).lower() != "avis":
            return command
        now = time.monotonic() if now is None else float(now)
        self._observe_road_rules(frame, now)
        self._observe_crosswalk(perception, now)
        self._observe_deadlock(frame, command, now)

        # Keep the crosswalk stop/dwell/green-wait state machine running even
        # while the independent signal or stop-line gate is holding the car.
        # A red light must not pause the 3-second dwell after a confirmed stop.
        if self.crosswalk_state in {"stopping", "holding", "waiting_for_green"}:
            crosswalk_command = self._crosswalk_route_command(
                frame, command, distance_delta_cm, now
            )
            if crosswalk_command is not None:
                return crosswalk_command

        # During an already-running route, a new red/stop-line hold still has
        # priority and immediately brakes the vehicle.
        if self.traffic_light_hold or self.stop_line_waiting:
            reason = (
                "AVIS City stop line: waiting for confirmed green signal"
                if self.stop_line_waiting
                else "AVIS City traffic light is red or has not yet been confirmed green"
            )
            return _brake(command, reason)

        crosswalk_command = self._crosswalk_route_command(frame, command, distance_delta_cm, now)
        if crosswalk_command is not None:
            return crosswalk_command

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

        # Let current-frame range/ROI obstacle avoidance run before the deadlock
        # hardcode. A newly observed obstacle must be able to preempt the route.
        deadlock_command = self._deadlock_route_command(
            obstacle_command, distance_delta_cm, now
        )
        if deadlock_command is not None:
            return deadlock_command

        if self.turn_direction and now < self.turn_until and command.brake < 0.5 and perception_valid:
            offset = max(0.05, min(0.35, float(getattr(
                self.config, "SIMULATOR_SIGN_STEERING_OFFSET", 0.18
            ))))
            direction = self.turn_direction
            if bool(getattr(self.config, "SIMULATOR_STEERING_INVERTED", False)):
                direction = -direction
            adjusted_steering = max(-0.45, min(0.45, command.steering + direction * offset))
            if self._last_turn_nudge_log_label != self.last_sign_label:
                logger.info(
                    "AVIS sign command applied: sign=%s action=bounded_turn_steering_nudge "
                    "direction=%s steering_in=%.3f steering_out=%.3f throttle_cap=0.12",
                    self.last_sign_label,
                    "right" if direction > 0 else "left",
                    command.steering,
                    adjusted_steering,
                )
                self._last_turn_nudge_log_label = self.last_sign_label
            return VehicleCommand(
                steering=adjusted_steering,
                throttle=min(command.throttle, 0.12),
                brake=0.0,
                servo_angle=command.servo_angle,
                target_speed=min(command.target_speed, 15.0),
                reason=f"traffic sign {self.last_sign_label}: bounded turn-steering nudge",
            )
        if now >= self.turn_until:
            self.turn_direction = 0.0
            self._last_turn_nudge_log_label = None
        return obstacle_command

    def snapshot(self):
        return {
            "obstacle": self.obstacles.snapshot(),
            "approach_speed_control": self.approach_speed.snapshot(),
            "stop_line_enabled": self.stop_line_detector is not None,
            "stop_line_detection": dict(self.last_stop_line_detection),
            "stop_line_waiting": bool(self.stop_line_waiting),
            "stop_line_armed": bool(self.stop_line_armed),
            "traffic_light_enabled": self.traffic_detector is not None,
            "traffic_light": self.last_light_color,
            "traffic_light_detections": [dict(item) for item in self.last_traffic_light_detections],
            "traffic_light_hold": bool(self.traffic_light_hold),
            "sign_enabled": self.sign_detector is not None,
            "sign_label": self.last_sign_label,
            "last_direction_sign": self.last_direction_sign_label,
            "last_direction_sign_age_s": (
                max(0.0, time.monotonic() - self.last_direction_sign_at)
                if self.last_direction_sign_at is not None else None
            ),
            "sign_turn_action_active": bool(
                self.turn_direction and time.monotonic() < self.turn_until
            ),
            "sign_turn_direction": (
                "right" if self.turn_direction > 0 else
                "left" if self.turn_direction < 0 else None
            ),
            "sign_turn_seconds_remaining": max(
                0.0, self.turn_until - time.monotonic()
            ),
            "sign_roi": dict(self.last_sign_roi_status),
            "park_latched": bool(self.park_latched),
            "sign_detector_error": self._sign_error,
            "crosswalk_enabled": bool(getattr(self.config, "SIMULATOR_CROSSWALK_HARDCODE_ENABLED", True)),
            "crosswalk_detected": bool(self.crosswalk_detect_count),
            "crosswalk_detection_frames": int(self.crosswalk_detect_count),
            "crosswalk_detection_required": max(
                1, min(20, int(getattr(self.config, "SIMULATOR_CROSSWALK_CONFIRM_FRAMES", 3)))
            ),
            "crosswalk_state": self.crosswalk_state,
            "crosswalk_measured_speed_kmh": self.crosswalk_measured_speed_kmh,
            "crosswalk_stop_confirm_count": int(self.crosswalk_stop_confirm_count),
            "crosswalk_stop_confirm_required": self.CROSSWALK_STOP_CONFIRM_FRAMES,
            "crosswalk_route": self.crosswalk_route_name,
            "crosswalk_sign": self.crosswalk_route_sign,
            "crosswalk_pending_sign": self.crosswalk_pending_sign,
            "crosswalk_route_frozen": bool(self.crosswalk_route_frozen),
            "crosswalk_waiting_for_green": self.crosswalk_state == "waiting_for_green",
            "crosswalk_green_confirmed": bool(self.green_window and self.green_window.confirmed),
            "crosswalk_green_count": self.green_window.green_count if self.green_window else 0,
            "crosswalk_green_observations": len(self.green_window.observations) if self.green_window else 0,
            "crosswalk_green_required": self.green_window.required_green if self.green_window else 0,
            "crosswalk_green_window": self.green_window.window_size if self.green_window else 0,
            "crosswalk_step": self.crosswalk_step_index + 1 if self.crosswalk_state == "running" else 0,
            "crosswalk_steps": len(self.crosswalk_steps),
            "crosswalk_progress_cm": round(self.crosswalk_step_progress_cm, 1),
            "crosswalk_reason": self.crosswalk_reason,
            "deadlock_enabled": bool(
                self.is_avis_city and getattr(self.config, "SIMULATOR_DEADLOCK_ENABLED", False)
            ),
            "deadlock_state": self.deadlock_state,
            "deadlock_candidate": self.deadlock_candidate,
            "deadlock_confirmation_frames": int(self.deadlock_confirm_count),
            "deadlock_confirmation_required": max(
                1, min(20, int(getattr(self.config, "SIMULATOR_DEADLOCK_CONFIRM_FRAMES", 4)))
            ),
            "deadlock_route": self.deadlock_route,
            "deadlock_route_steps": len(self.deadlock_steps),
            "deadlock_step": (
                self.deadlock_step_index + 1 if self.deadlock_state == "running" else 0
            ),
            "deadlock_step_progress_cm": round(self.deadlock_step_progress_cm, 1),
            "deadlock_reason": self.deadlock_reason,
            "deadlock_diagnostics": dict(self.deadlock_diagnostics),
        }

    def close(self):
        detector, self.sign_detector = self.sign_detector, None
        if detector is not None:
            try:
                detector.close()
            except Exception:
                logger.debug("Could not close AVIS sign detector", exc_info=True)
