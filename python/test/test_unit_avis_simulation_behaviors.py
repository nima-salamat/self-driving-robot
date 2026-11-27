"""Hardware-free AVIS behavior, stop-line and profile-setting tests."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modes.simulation.avis_behaviors import AVISBehaviorCoordinator, RangeObstacleAvoidance
from modes.simulation.base_adapter import SensorFrame, VehicleCommand
from modes.simulation.settings import _validate_settings, load_simulator_settings, save_simulator_settings
from stream.capabilities import mode_capabilities
from vision.stop_line import StopLineDetector


def base_command():
    return VehicleCommand(
        steering=0.0,
        throttle=0.25,
        brake=0.0,
        servo_angle=95.0,
        target_speed=25.0,
        reason="lane following",
    )


def obstacle_config(**overrides):
    values = dict(
        SIMULATOR_OBSTACLE_AVOIDANCE_ENABLED=True,
        SIMULATOR_OBSTACLE_HALL_HANDOFF_ENABLED=False,
        SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM=100.0,
        SIMULATOR_OBSTACLE_CLEAR_DISTANCE_CM=125.0,
        SIMULATOR_OBSTACLE_CLEAR_CONFIRM_FRAMES=1,
        SIMULATOR_OBSTACLE_SIDE_CLEARANCE_CM=75.0,
        SIMULATOR_OBSTACLE_STOP_DISTANCE_CM=35.0,
        SIMULATOR_OBSTACLE_SHIFT_SECONDS=0.35,
        SIMULATOR_OBSTACLE_REJOIN_SECONDS=0.35,
        SIMULATOR_OBSTACLE_PASS_TIMEOUT_SECONDS=4.0,
        SIMULATOR_OBSTACLE_STEERING_OFFSET=0.28,
        SIMULATOR_OBSTACLE_THROTTLE_LIMIT=0.12,
        SIMULATOR_STEERING_INVERTED=False,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def city_config(**overrides):
    values = dict(
        SIMULATOR_BACKEND="avis",
        SIMULATOR_STOP_LINE_ENABLED=True,
        SIMULATOR_TRAFFIC_LIGHTS_ENABLED=True,
        SIMULATOR_STOP_LINE_TOP_ROI=0.72,
        SIMULATOR_STOP_LINE_BOTTOM_ROI=0.98,
        SIMULATOR_STOP_LINE_LEFT_ROI=0.10,
        SIMULATOR_STOP_LINE_RIGHT_ROI=0.90,
        SIMULATOR_STOP_LINE_THRESHOLD=190,
        SIMULATOR_STOP_LINE_MIN_WIDTH_RATIO=0.55,
        SIMULATOR_STOP_LINE_MIN_AREA=120.0,
        SIMULATOR_STOP_LINE_MAX_ANGLE_DEG=12.0,
        SIMULATOR_STOP_LINE_CONFIRM_FRAMES=2,
        SIMULATOR_STOP_LINE_DWELL_SECONDS=1.0,
        SIMULATOR_TL_CONFIRMATION_WINDOW=4,
        SIMULATOR_TL_GREEN_REQUIRED=3,
        TL_TOP_ROI=0.0,
        TL_BOTTOM_ROI=0.30,
        TL_LEFT_ROI=0.35,
        TL_RIGHT_ROI=0.65,
        TL_MIN_SATURATION=50,
        TL_MIN_VALUE=50,
        TL_MIN_CONTOUR_AREA=5.0,
        TL_MIN_ACTIVE_BRIGHTNESS=180.0,
        TL_RED_HUE_MIN=0,
        TL_RED_HUE_MAX=10,
        TL_RED_HUE_WRAP_MIN=170,
        TL_GREEN_HUE_MIN=40,
        TL_GREEN_HUE_MAX=90,
        SIMULATOR_SIGN_ACTIONS_ENABLED=False,
        SIMULATOR_OBSTACLE_AVOIDANCE_ENABLED=False,
        SIMULATOR_OBSTACLE_STOP_DISTANCE_CM=35.0,
        SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM=100.0,
        SIMULATOR_OBSTACLE_CLEAR_DISTANCE_CM=125.0,
        SIMULATOR_OBSTACLE_SIDE_CLEARANCE_CM=75.0,
        SIMULATOR_OBSTACLE_SHIFT_SECONDS=0.35,
        SIMULATOR_OBSTACLE_REJOIN_SECONDS=0.35,
        SIMULATOR_OBSTACLE_PASS_TIMEOUT_SECONDS=4.0,
        SIMULATOR_OBSTACLE_STEERING_OFFSET=0.28,
        SIMULATOR_OBSTACLE_THROTTLE_LIMIT=0.12,
        SIMULATOR_STEERING_INVERTED=False,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def avis_frame(sequence, *, line=False, light="GREEN"):
    image = np.zeros((240, 320, 3), dtype=np.uint8)
    if line:
        cv2.rectangle(image, (42, 210), (278, 218), (255, 255, 255), -1)
    if light == "GREEN":
        cv2.circle(image, (160, 35), 11, (0, 255, 0), -1)
    elif light == "RED":
        cv2.circle(image, (160, 35), 11, (0, 0, 255), -1)
    return SensorFrame(
        image=image,
        captured_at=float(sequence),
        sequence=sequence,
        speed_kmh=5.0,
        ranges_cm={"left": 150.0, "front": 200.0, "right": 130.0},
    )


class StopLineDetectorTests(unittest.TestCase):
    def test_detects_wide_horizontal_line_in_configured_roi(self):
        config = city_config(SIMULATOR_TRAFFIC_LIGHTS_ENABLED=False)
        detector = StopLineDetector(config)
        result = detector.detect(avis_frame(1, line=True, light=None).image)
        self.assertTrue(result["detected"])
        self.assertGreaterEqual(result["confidence"], 0.55)
        self.assertIsNotNone(result["bbox"])

    def test_rejects_a_short_marking_and_a_vertical_marking(self):
        detector = StopLineDetector(city_config())
        short = avis_frame(1, light=None).image
        cv2.rectangle(short, (80, 210), (130, 218), (255, 255, 255), -1)
        self.assertFalse(detector.detect(short)["detected"])

        vertical = avis_frame(2, light=None).image
        cv2.rectangle(vertical, (150, 185), (158, 232), (255, 255, 255), -1)
        self.assertFalse(detector.detect(vertical)["detected"])

    def test_invalid_roi_fails_closed_without_exception(self):
        detector = StopLineDetector(city_config(
            SIMULATOR_STOP_LINE_TOP_ROI=0.9,
            SIMULATOR_STOP_LINE_BOTTOM_ROI=0.2,
        ))
        result = detector.detect(avis_frame(1, line=True).image)
        self.assertFalse(result["detected"])


class RangeObstacleAvoidanceTests(unittest.TestCase):
    def test_500_cm_trigger_is_inclusive_and_starts_only_at_or_below_threshold(self):
        ranges_at_threshold = {"left": 180.0, "front": 500.0, "right": 180.0}
        controller = RangeObstacleAvoidance(obstacle_config(
            SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM=500.0,
            SIMULATOR_OBSTACLE_CLEAR_DISTANCE_CM=150.0,
        ))
        command = controller.apply(
            base_command(), ranges_at_threshold, perception_valid=True, now=1.0,
        )
        self.assertEqual(controller.state, controller.SHIFT_LEFT_DIRECT)
        self.assertLess(command.steering, 0.0)

        above = RangeObstacleAvoidance(obstacle_config(
            SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM=500.0,
            SIMULATOR_OBSTACLE_CLEAR_DISTANCE_CM=150.0,
        ))
        idle_command = base_command()
        unchanged = above.apply(
            idle_command,
            {"left": 180.0, "front": 500.1, "right": 180.0},
            perception_valid=True,
            now=1.0,
        )
        self.assertEqual(above.state, above.CLEAR)
        self.assertIs(unchanged, idle_command)

    def test_avis_city_bypass_throttle_cap_can_be_raised_above_quarter_scale(self):
        controller = RangeObstacleAvoidance(obstacle_config(
            MODE="avis",
            SIMULATOR_THROTTLE_LIMIT=1.0,
            SIMULATOR_OBSTACLE_THROTTLE_LIMIT=0.8,
            SIMULATOR_OBSTACLE_LEFT_STEERING_PERCENT=88.0,
            SIMULATOR_STEERING_LIMIT=1.0,
        ))
        command = controller.apply(
            base_command(),
            {"left": 180.0, "front": 80.0, "right": 180.0},
            perception_valid=True,
            now=1.0,
        )
        self.assertEqual(controller.state, controller.SHIFT_LEFT_DIRECT)
        self.assertAlmostEqual(command.throttle, 0.8)

    def test_direct_left_steering_is_negative_and_roi_waits_for_delay(self):
        controller = RangeObstacleAvoidance(obstacle_config(
            SIMULATOR_OBSTACLE_LEFT_STEERING_PERCENT=92.0,
            SIMULATOR_OBSTACLE_ROI_DELAY_SECONDS=1.0,
            SIMULATOR_STEERING_LIMIT=1.0,
        ))
        ranges = {"left": 180.0, "front": 80.0, "right": 180.0}

        command = controller.apply(
            base_command(), ranges, perception_valid=True, now=1.0,
        )
        self.assertEqual(controller.state, controller.SHIFT_LEFT_DIRECT)
        self.assertAlmostEqual(command.steering, -0.92)
        self.assertIsNone(controller.prepare_vision())

        command = controller.apply(
            base_command(), ranges, perception_valid=True, now=1.9,
        )
        self.assertLess(command.steering, 0.0)
        self.assertIsNone(controller.prepare_vision())

        controller.apply(
            base_command(), ranges, perception_valid=True, now=2.05,
        )
        self.assertEqual(controller.state, controller.SEARCH_LEFT_ROI)
        self.assertEqual(controller.prepare_vision(), "left")


    def test_disabling_roi_confirmation_hands_left_departure_to_normal_lane_pid(self):
        controller = RangeObstacleAvoidance(obstacle_config(
            SIMULATOR_OBSTACLE_ROI_CONFIRMATION_ENABLED=False,
            SIMULATOR_OBSTACLE_USE_DISTANCE_MODE=True,
            SIMULATOR_OBSTACLE_DIRECT_STEERING_DISTANCE_CM=100.0,
            SIMULATOR_OBSTACLE_LEFT_STEERING_PERCENT=88.0,
            SIMULATOR_STEERING_LIMIT=1.0,
        ))
        ranges = {"left": 180.0, "front": 80.0, "right": 180.0}
        first = controller.apply(
            base_command(), ranges, perception_valid=True, now=1.0,
        )
        self.assertEqual(controller.state, controller.SHIFT_LEFT_DIRECT)
        self.assertAlmostEqual(first.steering, -0.88)

        completed = controller.apply(
            base_command(), ranges, perception_valid=True,
            distance_delta_cm=100.0, now=1.4,
        )
        self.assertEqual(controller.state, controller.PASS_LANE_FOLLOW)
        self.assertLess(completed.steering, 0.0)
        self.assertIsNone(controller.prepare_vision())
        self.assertFalse(controller.snapshot()["roi_confirmation_enabled"])

        lane_pid = VehicleCommand(
            steering=0.14, throttle=0.12, brake=0.0,
            servo_angle=101.0, target_speed=15.0, reason="normal lane PID",
        )
        handed_off = controller.apply(
            lane_pid, ranges, perception_valid=True, now=1.5,
        )
        self.assertIs(handed_off, lane_pid)
        self.assertEqual(controller.state, controller.PASS_LANE_FOLLOW)

    def test_disabling_roi_confirmation_restores_normal_lane_detection_after_right_return(self):
        controller = RangeObstacleAvoidance(obstacle_config(
            SIMULATOR_OBSTACLE_ROI_CONFIRMATION_ENABLED=False,
            SIMULATOR_OBSTACLE_ROI_DELAY_SECONDS=1.0,
            SIMULATOR_OBSTACLE_CLEAR_CONFIRM_FRAMES=1,
            SIMULATOR_OBSTACLE_RIGHT_STEERING_PERCENT=73.0,
            SIMULATOR_STEERING_LIMIT=1.0,
        ))
        controller.state = controller.SHIFT_RIGHT_DIRECT
        controller.state_since = 1.0
        controller.return_clear_observations = 0
        ranges = {"left": 180.0, "front": 180.0, "right": 180.0}

        returned = controller.apply(
            base_command(), ranges, perception_valid=True, now=2.1,
        )
        self.assertEqual(controller.state, controller.CLEAR)
        self.assertTrue(controller.awaiting_clear)
        self.assertAlmostEqual(returned.steering, 0.73)
        self.assertIsNone(controller.prepare_vision())
        self.assertFalse(controller.snapshot()["roi_confirmation_enabled"])

    def test_disabling_roi_confirmation_keeps_front_emergency_braking_active(self):
        controller = RangeObstacleAvoidance(obstacle_config(
            SIMULATOR_OBSTACLE_ROI_CONFIRMATION_ENABLED=False,
            SIMULATOR_OBSTACLE_STOP_DISTANCE_CM=60.0,
        ))
        result = controller.apply(
            base_command(),
            {"left": 180.0, "front": 45.0, "right": 180.0},
            perception_valid=True,
            now=1.0,
        )
        self.assertEqual(controller.state, controller.BLOCKED)
        self.assertEqual(result.brake, 1.0)
        self.assertEqual(result.throttle, 0.0)

    def test_sensor_gated_direct_departure_can_start_after_normal_lane_is_lost(self):
        controller = RangeObstacleAvoidance(obstacle_config(
            SIMULATOR_OBSTACLE_LEFT_STEERING_PERCENT=88.0,
            SIMULATOR_STEERING_LIMIT=1.0,
        ))
        lost_lane = VehicleCommand(
            steering=0.0, throttle=0.0, brake=1.0,
            servo_angle=95.0, target_speed=0.0,
            reason="no valid lane; simulator braking",
        )
        command = controller.apply(
            lost_lane,
            {"left": 180.0, "front": 80.0, "right": 180.0},
            perception_valid=False,
            now=1.0,
        )

        self.assertEqual(controller.state, controller.SHIFT_LEFT_DIRECT)
        self.assertAlmostEqual(command.steering, -0.88)
        self.assertEqual(command.brake, 0.0)
        self.assertGreater(command.throttle, 0.0)

    def test_left_roi_needs_confirmed_frames_then_pid_tracks_passing_lane(self):
        controller = RangeObstacleAvoidance(obstacle_config(
            SIMULATOR_OBSTACLE_ROI_DELAY_SECONDS=1.0,
            SIMULATOR_OBSTACLE_ROI_CONFIRM_FRAMES=2,
        SIMULATOR_OBSTACLE_RETURN_STEERING_GATE_ENABLED=False,
        SIMULATOR_OBSTACLE_RETURN_STEERING_SAMPLE_COUNT=10,
        SIMULATOR_OBSTACLE_RETURN_STEERING_MIN_PERCENT=-10.0,
        SIMULATOR_OBSTACLE_RETURN_STEERING_MAX_PERCENT=10.0,
            SIMULATOR_OBSTACLE_LANE_HOLD_SECONDS=0.5,
            SIMULATOR_OBSTACLE_LEFT_STEERING_PERCENT=80.0,
            SIMULATOR_OBSTACLE_RIGHT_STEERING_PERCENT=65.0,
            SIMULATOR_STEERING_LIMIT=1.0,
        ))
        ranges = {"left": 180.0, "front": 80.0, "right": 180.0}
        controller.apply(
            base_command(), ranges, perception_valid=True, now=1.0,
        )
        controller.apply(
            base_command(), ranges, perception_valid=True, now=2.05,
        )
        self.assertEqual(controller.state, controller.SEARCH_LEFT_ROI)
        self.assertEqual(controller.prepare_vision(), "left")

        first = controller.apply(
            base_command(), ranges, perception_valid=True,
            maneuver_roi={"side": "left", "observed": True}, now=2.10,
        )
        self.assertEqual(controller.state, controller.SEARCH_LEFT_ROI)
        self.assertLess(first.steering, 0.0)

        lane_pid_command = VehicleCommand(
            steering=0.12, throttle=0.10, brake=0.0,
            servo_angle=100.0, target_speed=12.0, reason="lane PID",
        )
        followed = controller.apply(
            lane_pid_command, ranges, perception_valid=True,
            maneuver_roi={"side": "left", "observed": True}, now=2.20,
        )
        self.assertEqual(controller.state, controller.PASS_LANE_FOLLOW)
        self.assertIs(followed, lane_pid_command)
        self.assertIsNone(controller.prepare_vision())

        controller.apply(
            lane_pid_command, ranges, perception_valid=True, now=2.69,
        )
        self.assertEqual(controller.state, controller.PASS_LANE_FOLLOW)

        returning = controller.apply(
            lane_pid_command, ranges, perception_valid=True, now=2.71,
        )
        self.assertEqual(controller.state, controller.SHIFT_RIGHT_DIRECT)
        self.assertAlmostEqual(returning.steering, 0.65)
        self.assertIsNone(controller.prepare_vision())

    def test_return_steering_gate_waits_for_mean_band_after_minimum_lane_hold(self):
        controller = RangeObstacleAvoidance(obstacle_config(
            SIMULATOR_OBSTACLE_LANE_HOLD_SECONDS=0.5,
            SIMULATOR_OBSTACLE_RETURN_STEERING_GATE_ENABLED=True,
            SIMULATOR_OBSTACLE_RETURN_STEERING_SAMPLE_COUNT=3,
            SIMULATOR_OBSTACLE_RETURN_STEERING_MIN_PERCENT=-10.0,
            SIMULATOR_OBSTACLE_RETURN_STEERING_MAX_PERCENT=10.0,
            SIMULATOR_OBSTACLE_RIGHT_STEERING_PERCENT=70.0,
            SIMULATOR_STEERING_LIMIT=1.0,
        ))
        controller.state = controller.PASS_LANE_FOLLOW
        controller.pass_started_at = 10.0
        controller.state_since = 10.0
        ranges = {"left": 180.0, "front": 180.0, "right": 180.0}

        def lane_command(steering):
            return VehicleCommand(
                steering=steering, throttle=0.1, brake=0.0,
                servo_angle=95.0, target_speed=12.0, reason="lane PID",
            )

        # Time is already elapsed but the configured sample window is still filling.
        for index in range(2):
            command = lane_command(0.30)
            result = controller.apply(command, ranges, perception_valid=True, now=10.6 + index * 0.1)
            self.assertIs(result, command)
            self.assertEqual(controller.state, controller.PASS_LANE_FOLLOW)

        # A complete window outside the configured band must keep following the curve.
        command = lane_command(0.30)
        result = controller.apply(command, ranges, perception_valid=True, now=10.8)
        self.assertIs(result, command)
        self.assertEqual(controller.state, controller.PASS_LANE_FOLLOW)
        stats = controller._return_steering_gate_stats()
        self.assertEqual(stats["sample_count"], 3)
        self.assertAlmostEqual(stats["mean_percent"], 30.0)
        self.assertFalse(stats["ready"])

        controller.apply(lane_command(-0.08), ranges, perception_valid=True, now=10.9)
        self.assertEqual(controller.state, controller.PASS_LANE_FOLLOW)
        returning = controller.apply(lane_command(0.04), ranges, perception_valid=True, now=11.0)
        self.assertEqual(controller.state, controller.SHIFT_RIGHT_DIRECT)
        self.assertAlmostEqual(returning.steering, 0.70)
        self.assertTrue(controller._return_steering_gate_stats()["ready"])

    def test_pass_lane_waits_for_right_clearance_then_retries_return(self):
        controller = RangeObstacleAvoidance(obstacle_config(
            SIMULATOR_BACKEND="avis",
            HALL_LINE_TRACKING_ENABLED=True,
            SIMULATOR_OBSTACLE_HALL_HANDOFF_ENABLED=False,
            SIMULATOR_OBSTACLE_LANE_HOLD_SECONDS=0.5,
            SIMULATOR_OBSTACLE_RETURN_STEERING_GATE_ENABLED=False,
            SIMULATOR_OBSTACLE_CLEAR_CONFIRM_FRAMES=3,
            SIMULATOR_OBSTACLE_SIDE_CLEARANCE_CM=75.0,
            SIMULATOR_OBSTACLE_RIGHT_STEERING_PERCENT=70.0,
            SIMULATOR_STEERING_LIMIT=1.0,
        ))
        controller.state = controller.PASS_LANE_FOLLOW
        controller.pass_started_at = 10.0
        controller.state_since = 10.0
        lane_command = VehicleCommand(
            steering=0.04, throttle=0.1, brake=0.0,
            servo_angle=95.0, target_speed=12.0, reason="lane PID",
        )
        ranges_blocked = {"left": 180.0, "front": 180.0, "right": 55.0}

        waiting = controller.apply(
            lane_command, ranges_blocked,
            perception_valid=True, now=10.6,
        )
        self.assertEqual(controller.state, controller.PASS_LANE_FOLLOW)
        self.assertIs(waiting, lane_command)
        self.assertIn("until right-side clearance", controller.last_reason.lower())
        self.assertEqual(controller.return_clear_observations, 0)

        ranges_clear = {"left": 180.0, "front": 180.0, "right": 120.0}
        for index in range(2):
            result = controller.apply(
                lane_command, ranges_clear,
                perception_valid=True, now=10.7 + index * 0.1,
            )
            self.assertEqual(controller.state, controller.PASS_LANE_FOLLOW)
            self.assertIs(result, lane_command)

        returning = controller.apply(
            lane_command, ranges_clear,
            perception_valid=True, now=10.9,
        )
        self.assertEqual(controller.state, controller.SHIFT_RIGHT_DIRECT)
        self.assertAlmostEqual(returning.steering, 0.70)
        self.assertIn("clearance confirmed", returning.reason.lower())

    def test_right_return_pauses_and_resumes_without_permanently_blocking(self):
        controller = RangeObstacleAvoidance(obstacle_config(
            SIMULATOR_BACKEND="avis",
            HALL_LINE_TRACKING_ENABLED=True,
            SIMULATOR_OBSTACLE_HALL_HANDOFF_ENABLED=False,
            SIMULATOR_OBSTACLE_ROI_DELAY_SECONDS=1.0,
            SIMULATOR_OBSTACLE_CLEAR_CONFIRM_FRAMES=3,
            SIMULATOR_OBSTACLE_SIDE_CLEARANCE_CM=75.0,
            SIMULATOR_OBSTACLE_RIGHT_STEERING_PERCENT=70.0,
            SIMULATOR_STEERING_LIMIT=1.0,
        ))
        controller.state = controller.SHIFT_RIGHT_DIRECT
        controller.state_since = 10.0
        controller.return_clear_observations = 3
        lane_command = VehicleCommand(
            steering=0.0, throttle=0.1, brake=0.0,
            servo_angle=95.0, target_speed=12.0, reason="lane PID",
        )

        paused = controller.apply(
            lane_command,
            {"left": 180.0, "front": 180.0, "right": 50.0},
            perception_valid=True, now=10.1,
        )
        self.assertEqual(controller.state, controller.SHIFT_RIGHT_DIRECT)
        self.assertGreaterEqual(paused.brake, 0.5)
        self.assertIn("paused until side clearance", paused.reason.lower())

        for current_time in (10.2, 10.3):
            paused = controller.apply(
                lane_command,
                {"left": 180.0, "front": 180.0, "right": 120.0},
                perception_valid=True, now=current_time,
            )
            self.assertEqual(controller.state, controller.SHIFT_RIGHT_DIRECT)
            self.assertGreaterEqual(paused.brake, 0.5)

        resumed = controller.apply(
            lane_command,
            {"left": 180.0, "front": 180.0, "right": 120.0},
            perception_valid=True, now=10.4,
        )
        self.assertNotEqual(controller.state, controller.BLOCKED)
        self.assertEqual(controller.state, controller.SHIFT_RIGHT_DIRECT)
        self.assertAlmostEqual(resumed.steering, 0.70)
        self.assertEqual(resumed.brake, 0.0)

    def test_hall_without_identity_handoff_keeps_passing_roi_until_timed_return(self):
        controller = RangeObstacleAvoidance(obstacle_config(
            SIMULATOR_BACKEND="avis",
            HALL_LINE_TRACKING_ENABLED=True,
            SIMULATOR_OBSTACLE_HALL_HANDOFF_ENABLED=False,
            OLD_METHOD=False,
            CITY_LANE_DETECTOR="default",
            USE_ML_LANE_DETECTOR=False,
            SIMULATOR_OBSTACLE_LANE_HOLD_SECONDS=0.5,
            SIMULATOR_OBSTACLE_RETURN_STEERING_GATE_ENABLED=True,
            SIMULATOR_OBSTACLE_RETURN_STEERING_MAX_WAIT_SECONDS=3.0,
            SIMULATOR_OBSTACLE_CLEAR_CONFIRM_FRAMES=1,
            SIMULATOR_OBSTACLE_RETURN_STEERING_SAMPLE_COUNT=3,
            SIMULATOR_OBSTACLE_RETURN_STEERING_MIN_PERCENT=-10.0,
            SIMULATOR_OBSTACLE_RETURN_STEERING_MAX_PERCENT=10.0,
            SIMULATOR_OBSTACLE_RIGHT_STEERING_PERCENT=70.0,
            SIMULATOR_STEERING_LIMIT=1.0,
        ))
        controller.state = controller.PASS_LANE_FOLLOW
        controller.pass_started_at = 10.0
        controller.state_since = 10.0
        ranges = {"left": 180.0, "front": 180.0, "right": 180.0}
        lane_command = VehicleCommand(
            steering=0.30, throttle=0.1, brake=0.0,
            servo_angle=95.0, target_speed=12.0, reason="Hall lane PID",
        )

        # With identity handoff disabled, Hall must keep tracking the newly
        # entered left lane throughout PASS; reverting to the original LL/RL
        # pair here can lose the passing lane before the steering gate fires.
        self.assertEqual(controller.prepare_vision(), "left")
        waiting = controller.apply(
            lane_command, ranges, perception_valid=True, now=10.6,
        )
        self.assertEqual(controller.state, controller.PASS_LANE_FOLLOW)
        self.assertIs(waiting, lane_command)
        self.assertEqual(controller.config.SIMULATOR_ACTIVE_OBSTACLE_ROI, "left")
        self.assertIn("waiting for the mean", controller.last_reason.lower())

        waiting = controller.apply(
            lane_command, ranges, perception_valid=True, now=10.8,
        )
        self.assertEqual(controller.state, controller.PASS_LANE_FOLLOW)
        self.assertIs(waiting, lane_command)
        self.assertEqual(controller.prepare_vision(), "left")

        # The complete sample window is still outside the band, so the car
        # must remain on the passing lane instead of returning prematurely.
        waiting = controller.apply(
            lane_command, ranges, perception_valid=True, now=10.9,
        )
        self.assertEqual(controller.state, controller.PASS_LANE_FOLLOW)
        self.assertIs(waiting, lane_command)
        self.assertEqual(controller.config.SIMULATOR_ACTIVE_OBSTACLE_ROI, "left")

        # Once the rolling mean reaches the configured +10% boundary, Hall
        # mode without identity handoff must issue the right-return command.
        centered_lane_command = VehicleCommand(
            steering=0.0, throttle=0.1, brake=0.0,
            servo_angle=95.0, target_speed=12.0, reason="centered lane PID",
        )
        controller.apply(
            centered_lane_command, ranges, perception_valid=True, now=11.0,
        )
        returning = controller.apply(
            centered_lane_command, ranges, perception_valid=True, now=11.1,
        )
        self.assertEqual(controller.state, controller.SHIFT_RIGHT_DIRECT)
        self.assertGreater(returning.steering, 0.0)
        self.assertIn("mean steering +10.0% is inside", returning.reason.lower())
        self.assertIsNone(controller.prepare_vision())

    def test_return_steering_gate_timeout_releases_right_return_with_hall_tracking(self):
        controller = RangeObstacleAvoidance(obstacle_config(
            SIMULATOR_BACKEND="avis",
            HALL_LINE_TRACKING_ENABLED=True,
            SIMULATOR_OBSTACLE_HALL_HANDOFF_ENABLED=False,
            OLD_METHOD=False,
            CITY_LANE_DETECTOR="default",
            USE_ML_LANE_DETECTOR=False,
            SIMULATOR_OBSTACLE_LANE_HOLD_SECONDS=0.5,
            SIMULATOR_OBSTACLE_RETURN_STEERING_GATE_ENABLED=True,
            SIMULATOR_OBSTACLE_RETURN_STEERING_MAX_WAIT_SECONDS=0.5,
            SIMULATOR_OBSTACLE_RETURN_STEERING_SAMPLE_COUNT=3,
            SIMULATOR_OBSTACLE_RETURN_STEERING_MIN_PERCENT=-10.0,
            SIMULATOR_OBSTACLE_RETURN_STEERING_MAX_PERCENT=10.0,
            SIMULATOR_OBSTACLE_RIGHT_STEERING_PERCENT=70.0,
            SIMULATOR_STEERING_LIMIT=1.0,
        ))
        controller.state = controller.PASS_LANE_FOLLOW
        controller.pass_started_at = 10.0
        controller.state_since = 10.0
        ranges = {"left": 180.0, "front": 180.0, "right": 180.0}

        def lane_command():
            return VehicleCommand(
                steering=0.30, throttle=0.1, brake=0.0,
                servo_angle=95.0, target_speed=12.0, reason="lane PID",
            )

        for current_time in (10.6, 10.7, 10.8):
            command = controller.apply(
                lane_command(), ranges, perception_valid=True, now=current_time
            )
            self.assertEqual(controller.state, controller.PASS_LANE_FOLLOW)
            self.assertEqual(command.reason, "lane PID")

        returning = controller.apply(
            lane_command(), ranges, perception_valid=True, now=11.0
        )
        self.assertEqual(controller.state, controller.SHIFT_RIGHT_DIRECT)
        self.assertAlmostEqual(returning.steering, 0.70)
        self.assertIn("return steering gate timed out", returning.reason.lower())
        self.assertFalse(controller._hall_handoff_enabled())

    def test_prepare_vision_marks_non_handoff_hall_bypass_for_independent_roi_tracking(self):
        controller = RangeObstacleAvoidance(obstacle_config(
            SIMULATOR_BACKEND="avis",
            HALL_LINE_TRACKING_ENABLED=True,
            SIMULATOR_OBSTACLE_HALL_HANDOFF_ENABLED=False,
            OLD_METHOD=False,
            CITY_LANE_DETECTOR="default",
            USE_ML_LANE_DETECTOR=False,
        ))
        controller.state = controller.SEARCH_LEFT_ROI
        self.assertEqual(controller.prepare_vision(), "left")
        self.assertTrue(controller.config.SIMULATOR_ACTIVE_OBSTACLE_BYPASS)
        self.assertIsNone(controller.config.SIMULATOR_ACTIVE_OBSTACLE_HALL_HANDOFF)

        controller.state = controller.REJOIN_LANE_FOLLOW
        self.assertEqual(controller.prepare_vision(), "right")
        self.assertIsNone(controller.config.SIMULATOR_ACTIVE_OBSTACLE_HALL_HANDOFF)

        controller.state = controller.CLEAR
        controller.prepare_vision()
        self.assertFalse(controller.config.SIMULATOR_ACTIVE_OBSTACLE_BYPASS)

    def test_return_steering_gate_uses_signed_avis_percent_and_inclusive_band(self):
        controller = RangeObstacleAvoidance(obstacle_config(
            SIMULATOR_OBSTACLE_RETURN_STEERING_GATE_ENABLED=True,
            SIMULATOR_OBSTACLE_RETURN_STEERING_SAMPLE_COUNT=2,
            SIMULATOR_OBSTACLE_RETURN_STEERING_MIN_PERCENT=-10.0,
            SIMULATOR_OBSTACLE_RETURN_STEERING_MAX_PERCENT=10.0,
        ))
        controller.return_steering_history.extend([-10.0, 10.0])
        stats = controller._return_steering_gate_stats()
        self.assertAlmostEqual(stats["mean_percent"], 0.0)
        self.assertTrue(stats["ready"])

    def test_return_steering_gate_settings_are_validated(self):
        clean = _validate_settings({
            "SIMULATOR_OBSTACLE_RETURN_STEERING_GATE_ENABLED": True,
            "SIMULATOR_OBSTACLE_RETURN_STEERING_SAMPLE_COUNT": 10,
            "SIMULATOR_OBSTACLE_RETURN_STEERING_MIN_PERCENT": -10.0,
            "SIMULATOR_OBSTACLE_RETURN_STEERING_MAX_PERCENT": 10.0,
        }, backend="avis")
        self.assertTrue(clean["SIMULATOR_OBSTACLE_RETURN_STEERING_GATE_ENABLED"])
        self.assertEqual(clean["SIMULATOR_OBSTACLE_RETURN_STEERING_SAMPLE_COUNT"], 10)
        with self.assertRaisesRegex(ValueError, "between 1 and 100"):
            _validate_settings({"SIMULATOR_OBSTACLE_RETURN_STEERING_SAMPLE_COUNT": 0}, backend="avis")
        with self.assertRaisesRegex(ValueError, "minimum must be smaller"):
            _validate_settings({
                "SIMULATOR_OBSTACLE_RETURN_STEERING_MIN_PERCENT": 10.0,
                "SIMULATOR_OBSTACLE_RETURN_STEERING_MAX_PERCENT": -10.0,
            }, backend="avis")
        with self.assertRaises(ValueError):
            _validate_settings({"SIMULATOR_OBSTACLE_RETURN_STEERING_MAX_PERCENT": 100.1}, backend="avis")

    def test_right_roi_confirmation_keeps_following_original_lane_before_restore(self):
        controller = RangeObstacleAvoidance(obstacle_config(
            SIMULATOR_BACKEND="avis",
            HALL_LINE_TRACKING_ENABLED=True,
            SIMULATOR_OBSTACLE_HALL_HANDOFF_ENABLED=False,
            SIMULATOR_OBSTACLE_ROI_CONFIRMATION_ENABLED=False,
            OLD_METHOD=False,
            CITY_LANE_DETECTOR="default",
            USE_ML_LANE_DETECTOR=False,
            SIMULATOR_OBSTACLE_ROI_DELAY_SECONDS=0.5,
            SIMULATOR_OBSTACLE_LANE_HOLD_SECONDS=0.2,
            SIMULATOR_OBSTACLE_ROI_CONFIRM_FRAMES=2,
            SIMULATOR_OBSTACLE_RIGHT_STEERING_PERCENT=73.0,
            SIMULATOR_STEERING_LIMIT=1.0,
        ))
        ranges = {"left": 180.0, "front": 80.0, "right": 180.0}
        lane_pid_command = VehicleCommand(
            steering=-0.1, throttle=0.08, brake=0.0,
            servo_angle=90.0, target_speed=10.0, reason="lane PID",
        )
        controller.apply(base_command(), ranges, perception_valid=True, now=1.0)
        controller.apply(base_command(), ranges, perception_valid=True, now=1.6)
        controller.apply(
            lane_pid_command, ranges, perception_valid=True,
            maneuver_roi={"side": "left", "observed": True}, now=1.7,
        )
        controller.apply(
            lane_pid_command, ranges, perception_valid=True,
            maneuver_roi={"side": "left", "observed": True}, now=1.8,
        )
        self.assertEqual(controller.state, controller.PASS_LANE_FOLLOW)
        controller.apply(lane_pid_command, ranges, perception_valid=True, now=2.01)
        self.assertEqual(controller.state, controller.SHIFT_RIGHT_DIRECT)
        self.assertAlmostEqual(
            controller.last_reason.startswith("obstacle lane change"), True,
        )
        direct = controller.apply(
            lane_pid_command, ranges, perception_valid=True, now=2.6,
        )
        self.assertEqual(controller.state, controller.SEARCH_RIGHT_ROI)
        self.assertAlmostEqual(direct.steering, 0.73)
        self.assertEqual(controller.prepare_vision(), "right")

        controller.apply(
            lane_pid_command, ranges, perception_valid=True,
            maneuver_roi={"side": "right", "observed": True}, now=2.7,
        )
        restored = controller.apply(
            lane_pid_command, ranges, perception_valid=True,
            maneuver_roi={"side": "right", "observed": True}, now=2.8,
        )
        self.assertEqual(controller.state, controller.REJOIN_LANE_FOLLOW)
        self.assertIs(restored, lane_pid_command)
        self.assertTrue(controller._roi_confirmation_enabled())
        self.assertEqual(controller.prepare_vision(), "right")

        controller.apply(
            lane_pid_command, ranges, perception_valid=True, now=2.9,
        )
        self.assertEqual(controller.state, controller.REJOIN_LANE_FOLLOW)
        self.assertEqual(controller.prepare_vision(), "right")

        controller.apply(
            lane_pid_command, ranges, perception_valid=True, now=3.01,
        )
        self.assertEqual(controller.state, controller.CLEAR)
        self.assertIsNone(controller.prepare_vision())

    def test_direct_steering_is_clamped_by_global_authority_and_keeps_signs(self):
        controller = RangeObstacleAvoidance(obstacle_config(
            SIMULATOR_OBSTACLE_LEFT_STEERING_PERCENT=100.0,
            SIMULATOR_OBSTACLE_RIGHT_STEERING_PERCENT=100.0,
            SIMULATOR_STEERING_LIMIT=0.45,
            SIMULATOR_OBSTACLE_ROI_DELAY_SECONDS=4.0,
        ))
        left_ranges = {"left": 180.0, "front": 80.0, "right": 180.0}
        left = controller.apply(
            base_command(), left_ranges, perception_valid=True, now=1.0,
        )
        self.assertAlmostEqual(left.steering, -0.45)

        # Put a separate controller directly into the right departure phase.
        controller = RangeObstacleAvoidance(obstacle_config(
            SIMULATOR_OBSTACLE_RIGHT_STEERING_PERCENT=100.0,
            SIMULATOR_STEERING_LIMIT=0.45,
        ))
        controller.state = controller.SHIFT_RIGHT_DIRECT
        controller.state_since = 1.0
        right = controller.apply(
            base_command(),
            {"left": 180.0, "front": 80.0, "right": 180.0},
            perception_valid=True, now=1.1,
        )
        self.assertAlmostEqual(right.steering, 0.45)

    def test_search_timeout_brakes_instead_of_steering_forever(self):
        controller = RangeObstacleAvoidance(obstacle_config(
            SIMULATOR_OBSTACLE_ROI_DELAY_SECONDS=0.5,
            SIMULATOR_OBSTACLE_ROI_SEARCH_TIMEOUT_SECONDS=0.5,
        ))
        ranges = {"left": 180.0, "front": 80.0, "right": 180.0}
        controller.apply(base_command(), ranges, perception_valid=True, now=1.0)
        controller.apply(base_command(), ranges, perception_valid=True, now=1.6)
        self.assertEqual(controller.state, controller.SEARCH_LEFT_ROI)
        stopped = controller.apply(
            base_command(), ranges, perception_valid=True,
            maneuver_roi={"side": "left", "observed": False}, now=2.2,
        )
        self.assertEqual(controller.state, controller.BLOCKED)
        self.assertEqual(stopped.brake, 1.0)
        self.assertEqual(stopped.throttle, 0.0)

    def test_clear_front_confirmation_count_is_configurable(self):
        controller = RangeObstacleAvoidance(obstacle_config(
            SIMULATOR_OBSTACLE_CLEAR_CONFIRM_FRAMES=4,
        ))
        controller.state = controller.BLOCKED
        ranges = {"left": 180.0, "front": 180.0, "right": 180.0}

        for observed in range(1, 4):
            stopped = controller.apply(
                base_command(), ranges, perception_valid=True, now=10.0 + observed * 0.1,
            )
            self.assertEqual(stopped.brake, 1.0)
            self.assertEqual(controller.state, controller.BLOCKED)
            self.assertIn(f"({observed}/4 observations)", stopped.reason)

        recovered = controller.apply(
            base_command(), ranges, perception_valid=True, now=10.4,
        )
        self.assertEqual(controller.state, controller.CLEAR)
        self.assertEqual(recovered.brake, 0.0)
        self.assertEqual(controller.snapshot()["front_clear_observations_required"], 4)

    def test_clear_confirmation_count_settings_are_validated(self):
        clean = _validate_settings({
            "SIMULATOR_OBSTACLE_CLEAR_CONFIRM_FRAMES": 5,
            "SIMULATOR_AVIS_FRONT_RANGE_INVALID_GRACE_SECONDS": 2.5,
        }, backend="avis")
        self.assertEqual(clean["SIMULATOR_OBSTACLE_CLEAR_CONFIRM_FRAMES"], 5)
        self.assertEqual(clean["SIMULATOR_AVIS_FRONT_RANGE_INVALID_GRACE_SECONDS"], 2.5)
        with self.assertRaisesRegex(ValueError, "between 1 and 20"):
            _validate_settings({"SIMULATOR_OBSTACLE_CLEAR_CONFIRM_FRAMES": 0}, backend="avis")
        with self.assertRaisesRegex(ValueError, "between 0 and 10"):
            _validate_settings({"SIMULATOR_AVIS_FRONT_RANGE_INVALID_GRACE_SECONDS": 10.1}, backend="avis")

    def test_missing_front_range_and_unclear_departure_side_fail_closed(self):
        controller = RangeObstacleAvoidance(obstacle_config())
        missing_front = controller.apply(
            base_command(), {"left": 180.0, "front": None, "right": 180.0},
            perception_valid=True, now=1.0,
        )
        self.assertEqual(missing_front.brake, 1.0)
        self.assertEqual(controller.state, controller.BLOCKED)

        controller = RangeObstacleAvoidance(obstacle_config())
        unclear_left = controller.apply(
            base_command(), {"left": 40.0, "front": 80.0, "right": 180.0},
            perception_valid=True, now=1.0,
        )
        self.assertEqual(unclear_left.brake, 1.0)
        self.assertEqual(controller.state, controller.BLOCKED)

    def test_missing_lane_during_passing_lane_follow_brakes(self):
        controller = RangeObstacleAvoidance(obstacle_config(
            SIMULATOR_OBSTACLE_ROI_DELAY_SECONDS=0.1,
        ))
        ranges = {"left": 180.0, "front": 80.0, "right": 180.0}
        controller.apply(base_command(), ranges, perception_valid=True, now=1.0)
        controller.apply(base_command(), ranges, perception_valid=True, now=1.2)
        command = controller.apply(
            base_command(), ranges, perception_valid=True,
            maneuver_roi={"side": "left", "observed": True}, now=1.3,
        )
        self.assertEqual(command.brake, 0.0)
        command = controller.apply(
            base_command(), ranges, perception_valid=True,
            maneuver_roi={"side": "left", "observed": True}, now=1.4,
        )
        self.assertEqual(controller.state, controller.PASS_LANE_FOLLOW)
        stopped = controller.apply(
            base_command(), ranges, perception_valid=False, now=1.5,
        )
        self.assertEqual(controller.state, controller.BLOCKED)
        self.assertEqual(stopped.brake, 1.0)



    def test_direct_steering_percent_settings_accept_full_range_only(self):
        clean = _validate_settings({
            "SIMULATOR_OBSTACLE_LEFT_STEERING_PERCENT": 100.0,
            "SIMULATOR_OBSTACLE_RIGHT_STEERING_PERCENT": 0.0,
        }, backend="avis")
        self.assertEqual(clean["SIMULATOR_OBSTACLE_LEFT_STEERING_PERCENT"], 100.0)
        self.assertEqual(clean["SIMULATOR_OBSTACLE_RIGHT_STEERING_PERCENT"], 0.0)
        with self.assertRaises(ValueError):
            _validate_settings(
                {"SIMULATOR_OBSTACLE_LEFT_STEERING_PERCENT": 100.1},
                backend="avis",
            )
        with self.assertRaises(ValueError):
            _validate_settings(
                {"SIMULATOR_OBSTACLE_RIGHT_STEERING_PERCENT": -0.1},
                backend="avis",
            )

    def test_maneuver_roi_timing_and_confirmation_settings_are_bounded(self):
        clean = _validate_settings({
            "SIMULATOR_OBSTACLE_ROI_DELAY_SECONDS": 1.0,
            "SIMULATOR_OBSTACLE_LANE_HOLD_SECONDS": 3.0,
            "SIMULATOR_OBSTACLE_ROI_SEARCH_TIMEOUT_SECONDS": 4.0,
            "SIMULATOR_OBSTACLE_ROI_CONFIRM_FRAMES": 2,
            "ML_TOP_ROI": 0.60,
            "ML_BOTTOM_ROI": 0.98,
            "ML_LEFT_ROI": 0.02,
            "ML_RIGHT_ROI": 0.42,
            "MR_TOP_ROI": 0.60,
            "MR_BOTTOM_ROI": 0.98,
            "MR_LEFT_ROI": 0.58,
            "MR_RIGHT_ROI": 0.98,
        }, backend="avis")
        self.assertEqual(clean["SIMULATOR_OBSTACLE_ROI_CONFIRM_FRAMES"], 2)
        self.assertEqual(clean["ML_LEFT_ROI"], 0.02)
        self.assertEqual(clean["MR_RIGHT_ROI"], 0.98)
        with self.assertRaises(ValueError):
            _validate_settings(
                {"SIMULATOR_OBSTACLE_ROI_CONFIRM_FRAMES": 0},
                backend="avis",
            )
        with self.assertRaises(ValueError):
            _validate_settings(
                {"SIMULATOR_OBSTACLE_ROI_SEARCH_TIMEOUT_SECONDS": 15.1},
                backend="avis",
            )

    def test_failed_hall_handoff_refreshes_expected_id_from_observed_source(self):
        controller = RangeObstacleAvoidance(obstacle_config(
            SIMULATOR_OBSTACLE_HALL_HANDOFF_ENABLED=True,
            HALL_LINE_TRACKING_ENABLED=False,
            OLD_METHOD=False,
            SIMULATOR_BACKEND="avis",
            CITY_LANE_DETECTOR="default",
            USE_ML_LANE_DETECTOR=False,
        ))
        controller.state = controller.SEARCH_LEFT_ROI
        controller.state_since = 10.0
        controller._handoff_plan = {
            "enabled": True,
            "source_side": "left",
            "target_side": "right",
            "token": "test-session:1",
            "expected_track_id": 41,
        }
        lane_tracking = {
            "hall_handoff": {
                "token": "test-session:1",
                "transfer_ok": False,
                "transfer_reason": "source_boundary_identity_mismatch",
            },
            "left": {"observed": True, "track_id": 57},
            "right": {"observed": False, "track_id": 42},
            "lane_width_px": 200.0,
        }
        controller.apply(
            base_command(),
            {"left": 180.0, "front": 80.0, "right": 180.0},
            perception_valid=True,
            lane_tracking=lane_tracking,
            now=10.1,
        )
        self.assertEqual(controller._handoff_plan["expected_track_id"], 57)
        self.assertEqual(controller._last_observed_track_ids["left"], 57)

    def test_failed_hall_handoff_does_not_refresh_from_unobserved_source(self):
        controller = RangeObstacleAvoidance(obstacle_config(
            SIMULATOR_OBSTACLE_HALL_HANDOFF_ENABLED=True,
            HALL_LINE_TRACKING_ENABLED=False,
            OLD_METHOD=False,
            SIMULATOR_BACKEND="avis",
            CITY_LANE_DETECTOR="default",
            USE_ML_LANE_DETECTOR=False,
        ))
        controller.state = controller.SEARCH_LEFT_ROI
        controller._handoff_plan = {
            "enabled": True,
            "source_side": "left",
            "target_side": "right",
            "token": "test-session:1",
            "expected_track_id": 41,
        }
        lane_tracking = {
            "hall_handoff": {
                "token": "test-session:1",
                "transfer_ok": False,
                "transfer_reason": "source_boundary_identity_mismatch",
            },
            "left": {"observed": False, "track_id": 57},
            "right": {"observed": False, "track_id": 42},
            "lane_width_px": 200.0,
        }
        controller._refresh_handoff_expected_track(lane_tracking)
        self.assertEqual(controller._handoff_plan["expected_track_id"], 41)

    def test_hall_bypass_hands_off_right_then_left_and_restores_both_rois(self):
        controller = RangeObstacleAvoidance(obstacle_config(
            SIMULATOR_OBSTACLE_HALL_HANDOFF_ENABLED=True,
            HALL_LINE_TRACKING_ENABLED=False,
            SIMULATOR_OBSTACLE_ROI_CONFIRMATION_ENABLED=False,
            OLD_METHOD=False,
            SIMULATOR_BACKEND="avis",
            CITY_LANE_DETECTOR="default",
            USE_ML_LANE_DETECTOR=False,
            SIMULATOR_OBSTACLE_ROI_DELAY_SECONDS=0.5,
            SIMULATOR_OBSTACLE_ROI_CONFIRM_FRAMES=1,
            SIMULATOR_OBSTACLE_LANE_HOLD_SECONDS=0.2,
            SIMULATOR_OBSTACLE_RETURN_STEERING_GATE_ENABLED=False,
            SIMULATOR_OBSTACLE_LEFT_STEERING_PERCENT=80.0,
            SIMULATOR_OBSTACLE_RIGHT_STEERING_PERCENT=70.0,
            SIMULATOR_STEERING_LIMIT=1.0,
        ))
        self.assertTrue(controller._roi_confirmation_enabled())
        ranges = {"left": 180.0, "front": 80.0, "right": 180.0}
        left_track = {
            "left": {"observed": True, "track_id": 41},
            "right": {"observed": True, "track_id": 42},
            "lane_width_px": 200.0,
        }
        controller.apply(
            base_command(), ranges, perception_valid=True,
            lane_tracking=left_track, now=1.0,
        )
        controller.apply(
            base_command(), ranges, perception_valid=True,
            lane_tracking=left_track, now=1.6,
        )
        self.assertEqual(controller.state, controller.SEARCH_LEFT_ROI)
        self.assertEqual(controller.prepare_vision(), "right")
        first_plan = controller.config.SIMULATOR_ACTIVE_OBSTACLE_HALL_HANDOFF
        self.assertEqual(first_plan["source_side"], "left")
        self.assertEqual(first_plan["target_side"], "right")
        self.assertEqual(first_plan["expected_track_id"], 41)

        right_lock = {
            "side": "right", "observed": True, "handoff_locked": True,
            "track_id": 41,
        }
        right_track = {
            "left": {"observed": False},
            "right": {"observed": True, "track_id": 41},
            "lane_width_px": 200.0,
        }
        lane_pid = VehicleCommand(
            steering=0.08, throttle=0.10, brake=0.0,
            servo_angle=100.0, target_speed=12.0, reason="lane PID",
        )
        controller.apply(
            lane_pid, ranges, perception_valid=True,
            lane_tracking=right_track, maneuver_roi=right_lock, now=1.7,
        )
        self.assertEqual(controller.state, controller.PASS_LANE_FOLLOW)
        self.assertEqual(controller.prepare_vision(), "right")

        controller.apply(
            lane_pid, ranges, perception_valid=True,
            lane_tracking=right_track, maneuver_roi=right_lock, now=1.95,
        )
        self.assertEqual(controller.state, controller.SHIFT_RIGHT_DIRECT)
        controller.apply(
            base_command(), ranges, perception_valid=True,
            lane_tracking=right_track, now=2.5,
        )
        self.assertEqual(controller.state, controller.SEARCH_RIGHT_ROI)
        self.assertEqual(controller.prepare_vision(), "left")
        second_plan = controller.config.SIMULATOR_ACTIVE_OBSTACLE_HALL_HANDOFF
        self.assertEqual(second_plan["source_side"], "right")
        self.assertEqual(second_plan["target_side"], "left")
        self.assertEqual(second_plan["expected_track_id"], 41)

        left_lock = {
            "side": "left", "observed": True, "handoff_locked": True,
            "track_id": 41,
        }
        left_track = {
            "left": {"observed": True, "track_id": 41},
            "right": {"observed": False},
            "lane_width_px": 200.0,
        }
        controller.apply(
            lane_pid, ranges, perception_valid=True,
            lane_tracking=left_track, maneuver_roi=left_lock, now=2.6,
        )
        self.assertEqual(controller.state, controller.REJOIN_LANE_FOLLOW)
        self.assertEqual(controller.prepare_vision(), "left")

        controller.apply(
            lane_pid, ranges, perception_valid=True,
            lane_tracking=left_track, maneuver_roi=left_lock, now=2.85,
        )
        self.assertEqual(controller.state, controller.CLEAR)
        self.assertIsNone(controller.prepare_vision())
        self.assertIsNone(controller.config.SIMULATOR_ACTIVE_OBSTACLE_HALL_HANDOFF)

    def test_hall_identity_is_kept_during_direct_right_return_steer(self):
        controller = RangeObstacleAvoidance(obstacle_config(
            SIMULATOR_OBSTACLE_HALL_HANDOFF_ENABLED=True,
            HALL_LINE_TRACKING_ENABLED=False,
            OLD_METHOD=False,
            SIMULATOR_BACKEND="avis",
            CITY_LANE_DETECTOR="default",
            USE_ML_LANE_DETECTOR=False,
            SIMULATOR_OBSTACLE_ROI_DELAY_SECONDS=5.0,
            SIMULATOR_OBSTACLE_RIGHT_STEERING_PERCENT=70.0,
            SIMULATOR_STEERING_LIMIT=1.0,
        ))
        controller.state = controller.SHIFT_RIGHT_DIRECT
        controller.state_since = 0.0
        controller._handoff_plan = {
            "enabled": True,
            "source_side": "left",
            "target_side": "right",
            "token": 7,
            "expected_track_id": 41,
        }
        controller._last_observed_track_ids = {"left": 41, "right": 41}

        self.assertEqual(controller.prepare_vision(), "right")
        descriptor = controller.config.SIMULATOR_ACTIVE_OBSTACLE_HALL_HANDOFF
        self.assertEqual(descriptor["source_side"], "left")
        self.assertEqual(descriptor["target_side"], "right")

        ranges = {"left": 180.0, "front": 180.0, "right": 180.0}
        lane_tracking = {
            "left": {"observed": False},
            "right": {"observed": True, "track_id": 41},
            "lane_width_px": 200.0,
        }
        lock = {
            "side": "right", "observed": True,
            "handoff_locked": True, "track_id": 41,
        }
        controller.apply(
            base_command(), ranges, perception_valid=True,
            lane_tracking=lane_tracking, maneuver_roi=lock, now=1.0,
        )
        self.assertEqual(controller._handoff_missed_frames, 0)

        missing_lock = {
            "side": "right", "observed": False,
            "handoff_locked": False, "track_id": 41,
        }
        for current_time in (1.1, 1.2):
            command = controller.apply(
                base_command(), ranges, perception_valid=True,
                lane_tracking={"left": {"observed": False}, "right": {"observed": False}},
                maneuver_roi=missing_lock, now=current_time,
            )
            self.assertEqual(controller.state, controller.SHIFT_RIGHT_DIRECT)
            self.assertAlmostEqual(command.steering, 0.70)
            self.assertEqual(command.brake, 0.0)

        stopped = controller.apply(
            base_command(), ranges, perception_valid=True,
            lane_tracking={"left": {"observed": False}, "right": {"observed": False}},
            maneuver_roi=missing_lock, now=1.3,
        )
        self.assertEqual(controller.state, controller.BLOCKED)
        self.assertEqual(stopped.brake, 1.0)
        self.assertEqual(stopped.throttle, 0.0)

    def test_general_hall_tracking_does_not_enable_obstacle_handoff_by_itself(self):
        controller = RangeObstacleAvoidance(obstacle_config(
            HALL_LINE_TRACKING_ENABLED=True,
            SIMULATOR_OBSTACLE_HALL_HANDOFF_ENABLED=False,
            OLD_METHOD=False,
            SIMULATOR_BACKEND="avis",
            CITY_LANE_DETECTOR="default",
            USE_ML_LANE_DETECTOR=False,
        ))
        self.assertFalse(controller._hall_handoff_enabled())
        controller.config.SIMULATOR_OBSTACLE_HALL_HANDOFF_ENABLED = True
        self.assertTrue(controller._hall_handoff_enabled())

    def test_hall_handoff_is_not_used_by_ml_or_blsf_detectors(self):
        controller = RangeObstacleAvoidance(obstacle_config(
            SIMULATOR_OBSTACLE_HALL_HANDOFF_ENABLED=True,
            HALL_LINE_TRACKING_ENABLED=False,
            OLD_METHOD=False,
            SIMULATOR_BACKEND="avis",
            CITY_LANE_DETECTOR="default",
            USE_ML_LANE_DETECTOR=False,
        ))
        self.assertTrue(controller._hall_handoff_enabled())
        controller.config.SIMULATOR_OBSTACLE_ROI_CONFIRMATION_ENABLED = False
        controller.config.USE_ML_LANE_DETECTOR = True
        self.assertFalse(controller._hall_handoff_enabled())
        self.assertFalse(controller._roi_confirmation_enabled())
        controller.config.USE_ML_LANE_DETECTOR = False
        controller.config.CITY_LANE_DETECTOR = "blsf-beta"
        self.assertFalse(controller._hall_handoff_enabled())
        self.assertFalse(controller._roi_confirmation_enabled())



class AVISCitySignalGateTests(unittest.TestCase):
    def test_stop_line_holds_until_distinct_green_frames_are_confirmed(self):
        coordinator = AVISBehaviorCoordinator(city_config(), "city")
        try:
            perception = {"perception_valid": True}
            frames = [
                avis_frame(1, line=True, light="GREEN"),
                avis_frame(2, line=True, light="GREEN"),
                avis_frame(3, line=True, light="GREEN"),
                avis_frame(4, line=True, light="GREEN"),
            ]
            first = coordinator.apply(frames[0], perception, base_command(), now=0.1)
            self.assertEqual(first.brake, 0.0)
            for index, frame in enumerate(frames[1:3], start=2):
                command = coordinator.apply(frame, perception, base_command(), now=index * 0.1)
                self.assertEqual(command.brake, 1.0)
                self.assertTrue(coordinator.stop_line_waiting)
            released = coordinator.apply(frames[3], perception, base_command(), now=0.4)
            self.assertFalse(coordinator.stop_line_waiting)
            self.assertGreater(released.throttle, 0.0)
        finally:
            coordinator.close()

    def test_red_signal_latches_brake_and_unknown_does_not_release_it(self):
        coordinator = AVISBehaviorCoordinator(city_config(
            SIMULATOR_STOP_LINE_ENABLED=False,
            SIMULATOR_TL_CONFIRMATION_WINDOW=3,
            SIMULATOR_TL_GREEN_REQUIRED=2,
        ), "city")
        try:
            perception = {"perception_valid": True}
            red = coordinator.apply(
                avis_frame(1, line=False, light="RED"), perception, base_command(), now=0.1
            )
            self.assertEqual(red.brake, 1.0)
            unknown = SensorFrame(
                image=np.zeros((240, 320, 3), dtype=np.uint8),
                captured_at=2.0, sequence=2, ranges_cm={"front": 200, "left": 150, "right": 150},
            )
            self.assertEqual(
                coordinator.apply(unknown, perception, base_command(), now=0.2).brake,
                1.0,
            )
            green = coordinator.apply(
                avis_frame(3, light="GREEN"), perception, base_command(), now=0.3
            )
            self.assertEqual(green.brake, 1.0)
            released = coordinator.apply(
                avis_frame(4, light="GREEN"), perception, base_command(), now=0.4
            )
            self.assertEqual(released.brake, 0.0)
        finally:
            coordinator.close()


class AVISTrafficSignActionTests(unittest.TestCase):
    class FakeSignDetector:
        def __init__(self, label, confidence=0.95):
            self.request_id = 1
            self.payload = {"text": label, "confidence": confidence}

        def submit(self, *_args, **_kwargs):
            return self.request_id

        def latest(self, **_kwargs):
            return (self.request_id, self.payload, 0.0, 0.0, 0.0)

        def set_label(self, label):
            self.request_id += 1
            self.payload = {"text": label, "confidence": 0.95}

        def close(self):
            pass

    def test_low_confidence_sign_is_ignored(self):
        coordinator = AVISBehaviorCoordinator(city_config(), "city")
        coordinator.sign_detector = self.FakeSignDetector("STOP", confidence=0.10)
        try:
            coordinator.submit_sign_frame(avis_frame(1, light=None))
            self.assertEqual(coordinator.stop_sign_until, 0.0)
            self.assertIsNone(coordinator.last_sign_label)
        finally:
            coordinator.close()

    def test_stop_park_straight_and_turn_sign_actions_are_bounded(self):
        coordinator = AVISBehaviorCoordinator(city_config(), "city")
        fake = self.FakeSignDetector("STOP")
        coordinator.sign_detector = fake
        try:
            frame = avis_frame(1, light=None)
            coordinator.submit_sign_frame(frame)
            stopped = coordinator.apply(
                frame, {"perception_valid": True}, base_command(),
                now=coordinator.stop_sign_until - 0.1,
            )
            self.assertEqual(stopped.brake, 1.0)
            coordinator.stop_sign_until = 0.0

            fake.set_label("PARK")
            coordinator.submit_sign_frame(avis_frame(2, light=None))
            self.assertTrue(coordinator.park_latched)
            parked = coordinator.apply(
                avis_frame(3, light=None), {"perception_valid": True}, base_command(),
                now=time.monotonic() + 0.1,
            )
            self.assertEqual(parked.brake, 1.0)

            fake.set_label("STRAIGHT")
            coordinator.submit_sign_frame(avis_frame(4, light=None))
            self.assertFalse(coordinator.park_latched)

            fake.set_label("TURN RIGHT")
            coordinator.submit_sign_frame(avis_frame(5, light=None))
            turning = coordinator.apply(
                avis_frame(6, light=None), {"perception_valid": True}, base_command(),
                now=time.monotonic() + 0.1,
            )
            self.assertIn("TURN RIGHT", turning.reason)
            self.assertLessEqual(turning.throttle, 0.12)
        finally:
            coordinator.close()


class AVISCapabilityTests(unittest.TestCase):
    def test_city_race_and_carla_capabilities_are_not_conflated(self):
        city = mode_capabilities(SimpleNamespace(
            MODE="avis", SIMULATOR_BACKEND="avis", SIMULATION_VISION_PROFILE="city",
            CITY_LANE_DETECTOR="default", USE_ML_LANE_DETECTOR=False,
        ))
        race = mode_capabilities(SimpleNamespace(
            MODE="avis-race", SIMULATOR_BACKEND="avis", SIMULATION_VISION_PROFILE="race",
            CITY_LANE_DETECTOR="default", USE_ML_LANE_DETECTOR=False,
        ))
        carla = mode_capabilities(SimpleNamespace(
            MODE="carla", SIMULATOR_BACKEND="carla", SIMULATION_VISION_PROFILE="city",
            CITY_LANE_DETECTOR="default", USE_ML_LANE_DETECTOR=False,
        ))
        self.assertTrue(city["supports_stop_line"])
        self.assertTrue(city["supports_traffic_lights"])
        self.assertFalse(city["supports_crosswalk"])
        self.assertTrue(city["supports_crosswalk_roi"])
        self.assertTrue(city["supports_obstacle_avoidance"])
        self.assertTrue(city["supports_sign_actions"])
        self.assertFalse(race["supports_stop_line"])
        self.assertFalse(race["supports_traffic_lights"])
        self.assertFalse(race["supports_crosswalk_roi"])
        self.assertTrue(race["supports_obstacle_avoidance"])
        self.assertTrue(race["supports_sign_actions"])
        self.assertFalse(carla["supports_obstacle_avoidance"])
        self.assertFalse(carla["supports_sign_actions"])


class AVISModeSettingsTests(unittest.TestCase):
    def test_city_and_race_settings_are_isolated_and_feature_defaults_are_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            config = SimpleNamespace(BASE_DIR=directory)
            city_path = load_simulator_settings(config, "avis", "avis")
            self.assertTrue(config.SIMULATOR_STOP_LINE_ENABLED)
            self.assertTrue(config.SIMULATOR_TRAFFIC_LIGHTS_ENABLED)
            # AVIS City exposes crosswalk perception/ROI debugging but keeps
            # generic crosswalk braking separate from its stop-line/light gate.
            self.assertFalse(config.SIMULATOR_STOP_ON_CROSSWALK)
            self.assertTrue(config.SIMULATOR_OBSTACLE_AVOIDANCE_ENABLED)
            self.assertFalse(config.SIMULATOR_SIGN_ACTIONS_ENABLED)
            save_simulator_settings(config, "avis", {
                "SIMULATOR_OBSTACLE_AVOIDANCE_ENABLED": True,
                "TL_GREEN_HUE_MIN": 42,
            })
            race_path = load_simulator_settings(config, "avis-race", "avis")
            self.assertFalse(config.SIMULATOR_STOP_LINE_ENABLED)
            self.assertFalse(config.SIMULATOR_TRAFFIC_LIGHTS_ENABLED)
            self.assertTrue(config.SIMULATOR_OBSTACLE_AVOIDANCE_ENABLED)
            self.assertNotEqual(city_path, race_path)
            load_simulator_settings(config, "carla", "carla")
            self.assertTrue(config.SIMULATOR_STOP_ON_CROSSWALK)
            self.assertTrue((Path(directory) / "avis.sim.json").is_file())

    def test_avis_race_trigger_distance_supports_1500_cm_but_carla_stays_at_500(self):
        clean = _validate_settings({
            "SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM": 1500.0,
            "SIMULATOR_OBSTACLE_CLEAR_DISTANCE_CM": 150.0,
        }, backend="avis", mode="avis-race")
        self.assertEqual(clean["SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM"], 1500.0)
        self.assertEqual(clean["SIMULATOR_OBSTACLE_CLEAR_DISTANCE_CM"], 150.0)
        with self.assertRaisesRegex(ValueError, "TRIGGER_DISTANCE_CM.*1500"):
            _validate_settings(
                {"SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM": 1500.1},
                backend="avis", mode="avis-race",
            )
        with self.assertRaisesRegex(ValueError, "TRIGGER_DISTANCE_CM.*500"):
            _validate_settings(
                {"SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM": 500.1},
                backend="carla", mode="carla",
            )

    def test_roi_confirmation_setting_is_boolean_and_persists_for_avis_race(self):
        clean = _validate_settings({
            "SIMULATOR_OBSTACLE_ROI_CONFIRMATION_ENABLED": False,
        }, backend="avis", mode="avis-race")
        self.assertIs(clean["SIMULATOR_OBSTACLE_ROI_CONFIRMATION_ENABLED"], False)
        with self.assertRaisesRegex(ValueError, "ROI_CONFIRMATION_ENABLED must be boolean"):
            _validate_settings({
                "SIMULATOR_OBSTACLE_ROI_CONFIRMATION_ENABLED": "false",
            }, backend="avis", mode="avis-race")

        with tempfile.TemporaryDirectory() as directory:
            config = SimpleNamespace(BASE_DIR=directory, SIMULATOR_BACKEND="avis")
            load_simulator_settings(config, "avis-race", "avis")
            save_simulator_settings(config, "avis-race", clean)
            restored = SimpleNamespace(BASE_DIR=directory, SIMULATOR_BACKEND="avis")
            load_simulator_settings(restored, "avis-race", "avis")
            self.assertIs(restored.SIMULATOR_OBSTACLE_ROI_CONFIRMATION_ENABLED, False)

    def test_obstacle_settings_template_uses_avis_backend_limit_and_exposes_roi_toggle(self):
        template = (
            Path(__file__).resolve().parents[1]
            / "stream" / "templates" / "simulator" / "partials" / "_settings_stack.html"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'max="{% if caps.simulator_backend == \'avis\' %}1500{% else %}500{% endif %}"',
            template,
        )
        self.assertIn(
            'name="SIMULATOR_OBSTACLE_ROI_CONFIRMATION_ENABLED"',
            template,
        )

    def test_500_cm_trigger_setting_is_persisted_without_changing_clear_field(self):
        with tempfile.TemporaryDirectory() as directory:
            config = SimpleNamespace(BASE_DIR=directory)
            load_simulator_settings(config, "avis", "avis")
            saved = save_simulator_settings(config, "avis", {
                "SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM": 500.0,
                "SIMULATOR_OBSTACLE_CLEAR_DISTANCE_CM": 150.0,
            })
            persisted = json.loads((Path(directory) / "avis.sim.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM"], 500.0)
            self.assertEqual(persisted["SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM"], 500.0)
            self.assertEqual(config.SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM, 500.0)

    def test_avis_city_accepts_extended_distance_and_bypass_throttle_limits(self):
        clean = _validate_settings({
            "SIMULATOR_OBSTACLE_STOP_DISTANCE_CM": 1000.0,
            "SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM": 1500.0,
            "SIMULATOR_OBSTACLE_CLEAR_DISTANCE_CM": 2000.0,
            "SIMULATOR_OBSTACLE_THROTTLE_LIMIT": 1.0,
        }, backend="avis", mode="avis")
        self.assertEqual(clean["SIMULATOR_OBSTACLE_STOP_DISTANCE_CM"], 1000.0)
        self.assertEqual(clean["SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM"], 1500.0)
        self.assertEqual(clean["SIMULATOR_OBSTACLE_CLEAR_DISTANCE_CM"], 2000.0)
        self.assertEqual(clean["SIMULATOR_OBSTACLE_THROTTLE_LIMIT"], 1.0)

        with self.assertRaisesRegex(ValueError, "STOP_DISTANCE_CM.*1000"):
            _validate_settings(
                {"SIMULATOR_OBSTACLE_STOP_DISTANCE_CM": 1000.1},
                backend="avis", mode="avis",
            )
        with self.assertRaisesRegex(ValueError, "TRIGGER_DISTANCE_CM.*1500"):
            _validate_settings(
                {"SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM": 1500.1},
                backend="avis", mode="avis",
            )
        with self.assertRaisesRegex(ValueError, "CLEAR_DISTANCE_CM.*2000"):
            _validate_settings(
                {"SIMULATOR_OBSTACLE_CLEAR_DISTANCE_CM": 2000.1},
                backend="avis", mode="avis",
            )
        with self.assertRaisesRegex(ValueError, "THROTTLE_LIMIT.*1.0"):
            _validate_settings(
                {"SIMULATOR_OBSTACLE_THROTTLE_LIMIT": 1.01},
                backend="avis", mode="avis",
            )

        # The expanded envelope is intentionally limited to the AVIS City mode.
        with self.assertRaisesRegex(ValueError, "STOP_DISTANCE_CM.*500"):
            _validate_settings(
                {"SIMULATOR_OBSTACLE_STOP_DISTANCE_CM": 501.0},
                backend="avis", mode="avis-race",
            )
        with self.assertRaisesRegex(ValueError, "THROTTLE_LIMIT.*0.25"):
            _validate_settings(
                {"SIMULATOR_OBSTACLE_THROTTLE_LIMIT": 0.26},
                backend="avis", mode="avis-race",
            )

    def test_validation_rejects_invalid_hue_ranges(self):
        with self.assertRaisesRegex(ValueError, "TL_RED_HUE_MIN"):
            _validate_settings({"TL_RED_HUE_MIN": 30, "TL_RED_HUE_MAX": 10})
        with self.assertRaisesRegex(ValueError, "TL_RED_HUE_WRAP_MIN"):
            _validate_settings({"TL_RED_HUE_MAX": 10, "TL_RED_HUE_WRAP_MIN": 5})


if __name__ == "__main__":
    unittest.main()
