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
    def test_selects_clearer_side_and_limits_bypass_motion(self):
        controller = RangeObstacleAvoidance(obstacle_config())
        ranges = {"left": 150.0, "front": 80.0, "right": 60.0}
        controller.apply(base_command(), ranges, perception_valid=True, now=0.1)
        command = controller.apply(
            base_command(), ranges, perception_valid=True, now=0.2,
        )
        self.assertEqual(controller.state, controller.SHIFT)
        self.assertEqual(controller.direction, -1.0)
        self.assertLess(command.steering, 0.0)
        self.assertLessEqual(command.throttle, 0.12)
        self.assertEqual(command.brake, 0.0)

    def test_lane_change_requires_front_and_side_ranges_and_uses_clearer_side(self):
        controller = RangeObstacleAvoidance(obstacle_config())
        first = controller.apply(
            base_command(),
            {"left": 180.0, "front": 80.0, "right": 90.0},
            perception_valid=True,
            now=1.0,
        )
        self.assertEqual(controller.state, controller.SHIFT)
        self.assertEqual(controller.direction, -1.0)
        self.assertIn("shifting left", first.reason)

    def test_inverted_steering_does_not_swap_the_selected_range_sensor(self):
        controller = RangeObstacleAvoidance(obstacle_config(
            SIMULATOR_STEERING_INVERTED=True,
        ))
        controller.apply(
            base_command(),
            {"left": 180.0, "front": 80.0, "right": 90.0},
            perception_valid=True,
            now=1.0,
        )
        self.assertEqual(controller.selected_side, "left")
        self.assertEqual(controller.direction, 1.0)
        stopped = controller.apply(
            base_command(),
            {"left": 40.0, "front": 80.0, "right": 90.0},
            perception_valid=True,
            now=1.1,
        )
        self.assertEqual(stopped.brake, 1.0)
        self.assertEqual(controller.state, controller.BLOCKED)

    def test_lane_geometry_guides_adjacent_lane_shift_and_rejoin(self):
        config = obstacle_config(
            KP=0.4,
            SERVO_DIRECTION="rtl",
            MIN_SERVO_ANGLE=55.0,
            SERVO_CENTER=95.0,
            MAX_SERVO_ANGLE=125.0,
            SIMULATOR_STEERING_LIMIT=1.0,
            SIMULATOR_STEERING_RATE=2.0,
        )
        controller = RangeObstacleAvoidance(config)
        obstacle = {"left": 180.0, "front": 80.0, "right": 90.0}
        geometry = {
            "enabled": True,
            "lane_error_px": 0.0,
            "lane_width_px": 100.0,
            "perception_valid": True,
        }
        controller.apply(
            base_command(), obstacle, perception_valid=True,
            lane_quality=0.9, lane_kp=0.4, lane_tracking=geometry, now=1.0,
        )
        shifted = controller.apply(
            base_command(), obstacle, perception_valid=True,
            lane_quality=0.9, lane_kp=0.4, lane_tracking=geometry, now=1.175,
        )
        self.assertTrue(controller.snapshot()["lane_geometry_active"])
        self.assertEqual(controller.snapshot()["lane_width_px"], 100.0)
        self.assertLess(shifted.steering, 0.0)

        clear = {"left": 180.0, "front": 150.0, "right": 90.0}
        for now in (1.5, 1.6, 1.7, 1.8):
            controller.apply(
                base_command(), clear, perception_valid=True,
                distance_delta_cm=30.0, lane_quality=0.9, lane_kp=0.4,
                lane_tracking=geometry, now=now,
            )
        self.assertEqual(controller.state, controller.REJOIN)
        returning = controller.apply(
            base_command(), clear, perception_valid=True,
            lane_quality=0.9, lane_kp=0.4, lane_tracking=geometry, now=1.95,
        )
        self.assertIn("rejoining original lane", returning.reason)

    def test_lane_geometry_steers_toward_both_sides_and_back_for_servo_orientations(self):
        for servo_direction in ("ltr", "rtl"):
            for side, lane_direction, return_error in (
                ("left", -1.0, 100.0),
                ("right", 1.0, -100.0),
            ):
                with self.subTest(servo_direction=servo_direction, side=side):
                    controller = RangeObstacleAvoidance(obstacle_config(
                        SERVO_DIRECTION=servo_direction,
                        KP=0.4,
                        MIN_SERVO_ANGLE=55.0,
                        SERVO_CENTER=95.0,
                        MAX_SERVO_ANGLE=125.0,
                        SIMULATOR_STEERING_INVERTED=False,
                    ))
                    controller.lane_direction = lane_direction
                    controller.last_lane_quality = 0.9
                    controller.last_lane_kp = 0.4
                    geometry = {
                        "enabled": True,
                        "lane_error_px": 0.0,
                        "lane_width_px": 100.0,
                    }
                    shifting = controller._target_lane_steering(
                        base_command(), geometry, 0.5, 0.0,
                        steering_authority=1.0,
                    )
                    returning_geometry = {
                        **geometry,
                        "lane_error_px": return_error,
                    }
                    returning = controller._target_lane_steering(
                        base_command(), returning_geometry, 0.5, 0.0,
                        steering_authority=1.0,
                    )
                    self.assertGreater(
                        shifting * lane_direction, 0.0,
                        f"must steer toward the {side} lane",
                    )
                    self.assertLess(
                        returning * lane_direction, 0.0,
                        f"must steer back toward the original lane from {side}",
                    )

    def test_lane_change_authority_can_use_full_range_in_both_fallback_directions(self):
        for side, ranges, expected_sign in (
            ("left", {"left": 180.0, "front": 80.0, "right": 90.0}, -1.0),
            ("right", {"left": 90.0, "front": 80.0, "right": 180.0}, 1.0),
        ):
            with self.subTest(side=side):
                controller = RangeObstacleAvoidance(obstacle_config(
                    SIMULATOR_OBSTACLE_STEERING_OFFSET=1.0,
                    SIMULATOR_STEERING_LIMIT=1.0,
                    SIMULATOR_STEERING_RATE=10.0,
                ))
                controller.apply(
                    base_command(), ranges, perception_valid=True, now=1.0,
                )
                shifted = controller.apply(
                    base_command(), ranges, perception_valid=True, now=1.175,
                )
                self.assertGreater(
                    shifted.steering * expected_sign, 0.35,
                    f"{side} fallback maneuver should exceed the former 0.35 cap",
                )

    def test_lane_change_setting_accepts_full_normalized_authority(self):
        clean = _validate_settings(
            {"SIMULATOR_OBSTACLE_STEERING_OFFSET": 1.0},
            backend="avis",
        )
        self.assertEqual(clean["SIMULATOR_OBSTACLE_STEERING_OFFSET"], 1.0)
        with self.assertRaises(ValueError):
            _validate_settings(
                {"SIMULATOR_OBSTACLE_STEERING_OFFSET": 1.01},
                backend="avis",
            )

    def test_lane_change_waits_for_valid_lane_and_reports_why(self):
        controller = RangeObstacleAvoidance(obstacle_config())
        command = base_command()
        result = controller.apply(
            command,
            {"left": 180.0, "front": 160.0, "right": 90.0},
            perception_valid=False,
            now=1.0,
        )
        self.assertIs(result, command)
        self.assertEqual(controller.state, controller.CLEAR)
        self.assertIn("waiting for valid lane perception", controller.snapshot()["reason"])

    def test_obstacle_inside_bypass_trigger_brakes_when_lane_perception_is_invalid(self):
        controller = RangeObstacleAvoidance(obstacle_config())
        result = controller.apply(
            base_command(),
            {"left": 180.0, "front": 80.0, "right": 90.0},
            perception_valid=False,
            now=1.0,
        )
        self.assertEqual(result.throttle, 0.0)
        self.assertEqual(result.brake, 1.0)
        self.assertEqual(controller.state, controller.BLOCKED)
        self.assertIn("lane perception is invalid", controller.snapshot()["reason"])

    def test_rejoin_requires_three_clear_frames_and_minimum_travel_distance(self):
        controller = RangeObstacleAvoidance(obstacle_config())
        obstacle = {"left": 180.0, "front": 80.0, "right": 90.0}
        controller.apply(
            base_command(), obstacle, perception_valid=True,
            distance_delta_cm=0.0, now=1.0,
        )
        controller.apply(
            base_command(), obstacle, perception_valid=True,
            distance_delta_cm=0.0, now=1.5,
        )
        self.assertEqual(controller.state, controller.PASS)

        clear = {"left": 180.0, "front": 150.0, "right": 90.0}
        for now in (1.6, 1.7, 1.8):
            controller.apply(
                base_command(), clear, perception_valid=True,
                distance_delta_cm=10.0, now=now,
            )
        self.assertEqual(controller.state, controller.PASS)
        self.assertEqual(controller.snapshot()["front_clear_observations"], 3)

        controller.apply(
            base_command(), clear, perception_valid=True,
            distance_delta_cm=60.0, now=1.9,
        )
        self.assertEqual(controller.state, controller.REJOIN)

    def test_lane_rejoin_is_smooth_and_returns_to_clear(self):
        controller = RangeObstacleAvoidance(obstacle_config())
        obstacle = {"left": 180.0, "front": 80.0, "right": 90.0}
        controller.apply(base_command(), obstacle, perception_valid=True, now=1.0)
        controller.apply(base_command(), obstacle, perception_valid=True, now=1.5)
        clear = {"left": 180.0, "front": 150.0, "right": 90.0}
        for now in (1.6, 1.7, 1.8):
            controller.apply(
                base_command(), clear, perception_valid=True,
                distance_delta_cm=30.0, now=now,
            )
        self.assertEqual(controller.state, controller.REJOIN)
        returning = controller.apply(
            base_command(), clear, perception_valid=True, now=2.1,
        )
        self.assertIn("rejoining original lane", returning.reason)
        completed = controller.apply(
            base_command(), clear, perception_valid=True, now=2.3,
        )
        self.assertEqual(controller.state, controller.CLEAR)
        self.assertEqual(completed.reason, "lane following")

    def test_missing_sensor_tag_is_unknown_not_fake_clearance(self):
        from avisengine import Car

        class FakeSocket:
            def __init__(self, payload):
                self.payload = payload

            def sendall(self, _data):
                pass

            def recv(self, _size):
                payload, self.payload = self.payload, b""
                return payload

        car = Car()
        car.sock = FakeSocket(b"<speed>0</speed><EOF>")
        self.assertFalse(car.getData())
        self.assertEqual(car.getSensors(), [None, None, None])
        car.sock = None

    def test_unknown_front_or_insufficient_side_clearance_brakes(self):
        controller = RangeObstacleAvoidance(obstacle_config())
        unknown = controller.apply(
            base_command(),
            {"left": 150.0, "front": None, "right": 130.0},
            perception_valid=True,
            now=0.1,
        )
        self.assertEqual(unknown.brake, 1.0)
        self.assertEqual(controller.state, controller.BLOCKED)

        controller = RangeObstacleAvoidance(obstacle_config())
        blocked = controller.apply(
            base_command(),
            {"left": 40.0, "front": 80.0, "right": 60.0},
            perception_valid=True,
            now=0.1,
        )
        self.assertEqual(blocked.brake, 1.0)
        self.assertEqual(controller.state, controller.BLOCKED)

    def test_invalid_lane_never_gets_overridden_by_avoidance(self):
        controller = RangeObstacleAvoidance(obstacle_config())
        stopped = VehicleCommand(0, 0, 1, 95, 0, "lane lost")
        result = controller.apply(
            stopped,
            {"left": 150, "front": 70, "right": 120},
            perception_valid=False,
            now=0.1,
        )
        self.assertIs(result, stopped)
        self.assertEqual(controller.state, controller.CLEAR)

    def test_pass_timeout_enters_a_braked_blocked_state(self):
        controller = RangeObstacleAvoidance(obstacle_config())
        ranges = {"left": 150, "front": 80, "right": 50}
        controller.apply(base_command(), ranges, perception_valid=True, now=0.1)
        controller.apply(base_command(), ranges, perception_valid=True, now=0.6)
        self.assertEqual(controller.state, controller.PASS)
        result = controller.apply(base_command(), ranges, perception_valid=True, now=5.0)
        self.assertEqual(controller.state, controller.BLOCKED)
        self.assertEqual(result.brake, 1.0)

    def test_disabling_bypass_during_a_maneuver_latches_braking(self):
        config = obstacle_config()
        controller = RangeObstacleAvoidance(config)
        controller.apply(
            base_command(), {"left": 150, "front": 80, "right": 50},
            perception_valid=True, now=0.1,
        )
        config.SIMULATOR_OBSTACLE_AVOIDANCE_ENABLED = False
        stopped = controller.apply(
            base_command(), {"left": 150, "front": 80, "right": 50},
            perception_valid=True, now=0.2,
        )
        self.assertEqual(controller.state, controller.BLOCKED)
        self.assertEqual(stopped.brake, 1.0)

    def test_losing_selected_side_clearance_during_a_bypass_brakes(self):
        controller = RangeObstacleAvoidance(obstacle_config())
        controller.apply(
            base_command(), {"left": 150, "front": 80, "right": 50},
            perception_valid=True, now=0.1,
        )
        stopped = controller.apply(
            base_command(), {"left": 40, "front": 80, "right": 50},
            perception_valid=True, now=0.2,
        )
        self.assertEqual(controller.state, controller.BLOCKED)
        self.assertEqual(stopped.brake, 1.0)

    def test_losing_lane_during_a_bypass_latches_braking(self):
        controller = RangeObstacleAvoidance(obstacle_config())
        ranges = {"left": 150, "front": 80, "right": 50}
        controller.apply(base_command(), ranges, perception_valid=True, now=0.1)
        stopped = controller.apply(
            base_command(), ranges, perception_valid=False, now=0.2
        )
        self.assertEqual(controller.state, controller.BLOCKED)
        self.assertEqual(stopped.brake, 1.0)

    def test_disabling_bypass_preserves_lane_following_command(self):
        controller = RangeObstacleAvoidance(obstacle_config(
            SIMULATOR_OBSTACLE_AVOIDANCE_ENABLED=False
        ))
        command = base_command()
        result = controller.apply(
            command,
            {"left": 30, "front": 60, "right": 30},
            perception_valid=True,
            now=0.1,
        )
        self.assertIs(result, command)


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
            self.assertFalse(config.SIMULATOR_OBSTACLE_AVOIDANCE_ENABLED)
            self.assertFalse(config.SIMULATOR_SIGN_ACTIONS_ENABLED)
            save_simulator_settings(config, "avis", {
                "SIMULATOR_OBSTACLE_AVOIDANCE_ENABLED": True,
                "TL_GREEN_HUE_MIN": 42,
            })
            race_path = load_simulator_settings(config, "avis-race", "avis")
            self.assertFalse(config.SIMULATOR_STOP_LINE_ENABLED)
            self.assertFalse(config.SIMULATOR_TRAFFIC_LIGHTS_ENABLED)
            self.assertFalse(config.SIMULATOR_OBSTACLE_AVOIDANCE_ENABLED)
            self.assertNotEqual(city_path, race_path)
            load_simulator_settings(config, "carla", "carla")
            self.assertTrue(config.SIMULATOR_STOP_ON_CROSSWALK)
            self.assertTrue((Path(directory) / "avis.sim.json").is_file())

    def test_validation_rejects_unsafe_ordering_and_invalid_hue_ranges(self):
        with self.assertRaisesRegex(ValueError, "trigger distance"):
            _validate_settings({
                "SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM": 100.0,
                "SIMULATOR_OBSTACLE_CLEAR_DISTANCE_CM": 90.0,
            })
        with self.assertRaisesRegex(ValueError, "TL_RED_HUE_MIN"):
            _validate_settings({"TL_RED_HUE_MIN": 30, "TL_RED_HUE_MAX": 10})
        with self.assertRaisesRegex(ValueError, "TL_RED_HUE_WRAP_MIN"):
            _validate_settings({"TL_RED_HUE_MAX": 10, "TL_RED_HUE_WRAP_MIN": 5})


if __name__ == "__main__":
    unittest.main()
