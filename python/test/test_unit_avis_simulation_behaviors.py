"""Hardware-free AVIS behavior, stop-line and profile-setting tests."""
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
        SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM=100.0,
        SIMULATOR_OBSTACLE_CLEAR_DISTANCE_CM=125.0,
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

    def test_right_roi_confirmation_restores_normal_lane_following(self):
        controller = RangeObstacleAvoidance(obstacle_config(
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
        self.assertEqual(controller.state, controller.CLEAR)
        self.assertIs(restored, lane_pid_command)
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
        self.assertTrue(city["supports_obstacle_avoidance"])
        self.assertTrue(city["supports_sign_actions"])
        self.assertFalse(race["supports_stop_line"])
        self.assertFalse(race["supports_traffic_lights"])
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
            # AVIS City uses the dedicated solid stop-line detector, not
            # the generic simulator crosswalk-braking path.
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

    def test_maximum_trigger_distance_is_valid_with_default_clear_hysteresis(self):
        clean = _validate_settings({
            "SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM": 500.0,
            "SIMULATOR_OBSTACLE_CLEAR_DISTANCE_CM": 150.0,
        }, backend="avis")
        self.assertEqual(clean["SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM"], 500.0)
        self.assertEqual(clean["SIMULATOR_OBSTACLE_CLEAR_DISTANCE_CM"], 150.0)

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

    def test_validation_rejects_invalid_hue_ranges(self):
        with self.assertRaisesRegex(ValueError, "TL_RED_HUE_MIN"):
            _validate_settings({"TL_RED_HUE_MIN": 30, "TL_RED_HUE_MAX": 10})
        with self.assertRaisesRegex(ValueError, "TL_RED_HUE_WRAP_MIN"):
            _validate_settings({"TL_RED_HUE_MAX": 10, "TL_RED_HUE_WRAP_MIN": 5})


if __name__ == "__main__":
    unittest.main()
