"""Hardware-free tests for AVIS obstacle approach speed regulation."""
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modes.simulation.avis_behaviors import AVISObstacleApproachSpeedController
from modes.simulation.base_adapter import SensorFrame, VehicleCommand
from modes.simulation.settings import (
    _defaults,
    _validate_settings,
    load_simulator_settings,
    save_simulator_settings,
)


class AVISObstacleApproachSpeedTests(unittest.TestCase):
    def make_controller(self, enabled_sensors=None):
        config = types.SimpleNamespace(
            SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM=120.0,
            SIMULATOR_OBSTACLE_APPROACH_SPEED_KMH=10.0,
            SIMULATOR_OBSTACLE_SPEED_LIMIT_DISTANCE_CM=1500.0,
            SIMULATOR_OBSTACLE_SPEED_LIMIT_LEFT_SENSOR_ENABLED=(enabled_sensors or {}).get("left", False),
            SIMULATOR_OBSTACLE_SPEED_LIMIT_FRONT_SENSOR_ENABLED=(enabled_sensors or {}).get("front", True),
            SIMULATOR_OBSTACLE_SPEED_LIMIT_RIGHT_SENSOR_ENABLED=(enabled_sensors or {}).get("right", False),
            SIMULATOR_THROTTLE_LIMIT=0.35,
        )
        return AVISObstacleApproachSpeedController(config)

    def make_frame(self, ranges, speed=0.0, speed_available=True):
        return SensorFrame(
            image=None,
            captured_at=10.0,
            sequence=1,
            speed_kmh=speed,
            ranges_cm=ranges,
            sensor_status={"speed_available": speed_available},
        )

    @staticmethod
    def make_command(throttle=0.25, brake=0.0):
        return VehicleCommand(
            steering=0.0,
            throttle=throttle,
            brake=brake,
            servo_angle=95.0,
            target_speed=25.0,
            reason="lane estimate accepted",
        )

    def test_each_of_the_three_sensors_independently_enables_10_kmh_approach_control(self):
        for sensor in ("left", "front", "right"):
            with self.subTest(sensor=sensor):
                controller = self.make_controller(
                    enabled_sensors={"left": True, "front": True, "right": True}
                )
                ranges = {"left": 180.0, "front": 180.0, "right": 180.0}
                ranges[sensor] = 90.0
                command = self.make_command()
                result = controller.apply(
                    self.make_frame(ranges, speed=4.0),
                    command,
                    now=10.0,
                )
                snapshot = controller.snapshot()
                self.assertEqual(snapshot["state"], "approach_speed_control")
                self.assertEqual(snapshot["target_speed_kmh"], 10.0)
                self.assertEqual(snapshot["nearest_sensor"], sensor)
                self.assertEqual(snapshot["nearest_distance_cm"], 90.0)
                self.assertGreater(result.throttle, 0.0)
                self.assertLessEqual(result.throttle, command.throttle)
                self.assertEqual(result.target_speed, command.target_speed)


    def test_only_selected_sensors_can_trigger_approach_speed_limiting(self):
        controller = self.make_controller(
            enabled_sensors={"left": False, "front": True, "right": False}
        )
        command = self.make_command()
        disabled_sensor_obstacles = controller.apply(
            self.make_frame({"left": 80, "front": 1800, "right": 90}, speed=12.0),
            command,
            now=10.0,
        )
        self.assertIs(disabled_sensor_obstacles, command)
        self.assertEqual(controller.snapshot()["state"], "clear")
        self.assertEqual(
            controller.snapshot()["speed_limit_sensors_enabled"],
            {"left": False, "front": True, "right": False},
        )

        enabled_sensor_obstacle = controller.apply(
            self.make_frame({"left": 80, "front": 1499, "right": 90}, speed=12.0),
            command,
            now=10.1,
        )
        self.assertNotEqual(enabled_sensor_obstacle, command)
        self.assertEqual(controller.snapshot()["state"], "approach_speed_control")
        self.assertEqual(controller.snapshot()["nearest_sensor"], "front")

    def test_front_sensor_is_the_only_speed_limit_default_and_selectors_validate_as_booleans(self):
        defaults = _defaults("avis", "avis")
        keys = (
            "SIMULATOR_OBSTACLE_SPEED_LIMIT_LEFT_SENSOR_ENABLED",
            "SIMULATOR_OBSTACLE_SPEED_LIMIT_FRONT_SENSOR_ENABLED",
            "SIMULATOR_OBSTACLE_SPEED_LIMIT_RIGHT_SENSOR_ENABLED",
        )
        self.assertIs(defaults[keys[0]], False)
        self.assertIs(defaults[keys[1]], True)
        self.assertIs(defaults[keys[2]], False)
        for key in keys:
            with self.subTest(key=key):
                self.assertIs(_validate_settings({key: False}, backend="avis")[key], False)
                with self.assertRaises(ValueError):
                    _validate_settings({key: 1}, backend="avis")

    def test_sensor_speed_limit_choices_persist_and_reload(self):
        choices = {
            "SIMULATOR_OBSTACLE_SPEED_LIMIT_LEFT_SENSOR_ENABLED": False,
            "SIMULATOR_OBSTACLE_SPEED_LIMIT_FRONT_SENSOR_ENABLED": True,
            "SIMULATOR_OBSTACLE_SPEED_LIMIT_RIGHT_SENSOR_ENABLED": False,
        }
        with tempfile.TemporaryDirectory() as directory:
            config = types.SimpleNamespace(
                BASE_DIR=Path(directory),
                SIMULATOR_BACKEND="avis",
            )
            save_simulator_settings(
                config,
                "avis",
                choices,
            )
            self.assertEqual(config.SIMULATOR_AVIS_SAFETY_PROFILE_VERSION, 3)
            reloaded = types.SimpleNamespace(BASE_DIR=Path(directory))
            load_simulator_settings(reloaded, "avis", "avis")
            for key, expected in choices.items():
                with self.subTest(key=key):
                    self.assertIs(getattr(reloaded, key), expected)


    def test_side_sensor_obstacles_do_not_limit_speed_with_forward_only_defaults(self):
        controller = self.make_controller()
        command = self.make_command()
        result = controller.apply(
            self.make_frame({"left": 120, "front": 1800, "right": 95}, speed=16.0),
            command,
            now=10.0,
        )
        self.assertIs(result, command)
        snapshot = controller.snapshot()
        self.assertEqual(snapshot["state"], "clear")
        self.assertEqual(snapshot["speed_limit_sensors_enabled"],
                         {"left": False, "front": True, "right": False})

    def test_speed_above_10_kmh_reduces_avis_speed_command(self):
        controller = self.make_controller()
        command = self.make_command()
        result = controller.apply(
            self.make_frame({"left": 150, "front": 70, "right": 150}, speed=16.0),
            command,
            now=10.0,
        )
        self.assertEqual(controller.snapshot()["target_speed_kmh"], 10.0)
        self.assertEqual(controller.snapshot()["measured_speed_kmh"], 16.0)
        self.assertLess(result.throttle, command.throttle)
        self.assertEqual(result.throttle, 0.0)

    def test_no_object_inside_trigger_distance_leaves_command_unchanged(self):
        controller = self.make_controller()
        command = self.make_command()
        result = controller.apply(
            self.make_frame({"left": 1600, "front": 1500, "right": 1800}, speed=12.0),
            command,
            now=10.0,
        )
        self.assertIs(result, command)
        self.assertEqual(controller.snapshot()["state"], "clear")

    def test_speed_limit_activates_only_below_independent_1500_cm_threshold(self):
        controller = self.make_controller()
        command = self.make_command()
        at_boundary = controller.apply(
            self.make_frame({"left": 1800, "front": 1500, "right": 1800}, speed=12.0),
            command,
            now=10.0,
        )
        self.assertIs(at_boundary, command)
        inside = controller.apply(
            self.make_frame({"left": 1800, "front": 1499, "right": 1800}, speed=12.0),
            command,
            now=10.1,
        )
        self.assertEqual(controller.snapshot()["state"], "approach_speed_control")
        self.assertEqual(controller.snapshot()["speed_limit_distance_cm"], 1500.0)
        self.assertEqual(controller.snapshot()["nearest_sensor"], "front")
        self.assertLess(inside.throttle, command.throttle)

    def test_missing_speed_feedback_holds_a_safe_stop_near_an_object(self):
        controller = self.make_controller()
        result = controller.apply(
            self.make_frame({"left": 100, "front": 180, "right": 180},
                            speed=0.0, speed_available=False),
            self.make_command(),
            now=10.0,
        )
        self.assertEqual(result.throttle, 0.0)
        self.assertEqual(result.brake, 1.0)
        self.assertEqual(controller.snapshot()["state"], "speed_unavailable")

    def test_existing_brake_has_priority_over_approach_speed_control(self):
        controller = self.make_controller()
        command = self.make_command(throttle=0.0, brake=1.0)
        result = controller.apply(
            self.make_frame({"left": 90, "front": 180, "right": 180}, speed=5.0),
            command,
            now=10.0,
        )
        self.assertIs(result, command)
        self.assertEqual(controller.snapshot()["state"], "braking")

    def test_approach_target_is_separate_from_avis_percentage_speed_command(self):
        defaults = _defaults("avis", "avis")
        self.assertEqual(defaults["SIMULATOR_OBSTACLE_APPROACH_SPEED_KMH"], 10.0)
        self.assertEqual(defaults["SIMULATOR_OBSTACLE_SPEED_LIMIT_DISTANCE_CM"], 1500.0)
        self.assertEqual(defaults["SIMULATOR_TARGET_SPEED"], 25.0)
        clean = _validate_settings(
            {"SIMULATOR_OBSTACLE_APPROACH_SPEED_KMH": 10.0}, backend="avis"
        )
        self.assertEqual(clean["SIMULATOR_OBSTACLE_APPROACH_SPEED_KMH"], 10.0)
        distance = _validate_settings(
            {"SIMULATOR_OBSTACLE_SPEED_LIMIT_DISTANCE_CM": 1500.0}, backend="avis"
        )
        self.assertEqual(distance["SIMULATOR_OBSTACLE_SPEED_LIMIT_DISTANCE_CM"], 1500.0)
        with self.assertRaises(ValueError):
            _validate_settings(
                {"SIMULATOR_OBSTACLE_APPROACH_SPEED_KMH": 101.0}, backend="avis"
            )


if __name__ == "__main__":
    unittest.main()
