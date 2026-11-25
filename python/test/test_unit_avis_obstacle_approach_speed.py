"""Hardware-free tests for AVIS obstacle approach speed regulation."""
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modes.simulation.avis_behaviors import AVISObstacleApproachSpeedController
from modes.simulation.base_adapter import SensorFrame, VehicleCommand
from modes.simulation.settings import _defaults, _validate_settings


class AVISObstacleApproachSpeedTests(unittest.TestCase):
    def make_controller(self):
        config = types.SimpleNamespace(
            SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM=120.0,
            SIMULATOR_OBSTACLE_APPROACH_SPEED_KMH=10.0,
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
                controller = self.make_controller()
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
            self.make_frame({"left": 160, "front": 140, "right": 180}, speed=12.0),
            command,
            now=10.0,
        )
        self.assertIs(result, command)
        self.assertEqual(controller.snapshot()["state"], "clear")

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
        self.assertEqual(defaults["SIMULATOR_TARGET_SPEED"], 25.0)
        clean = _validate_settings(
            {"SIMULATOR_OBSTACLE_APPROACH_SPEED_KMH": 10.0}, backend="avis"
        )
        self.assertEqual(clean["SIMULATOR_OBSTACLE_APPROACH_SPEED_KMH"], 10.0)
        with self.assertRaises(ValueError):
            _validate_settings(
                {"SIMULATOR_OBSTACLE_APPROACH_SPEED_KMH": 101.0}, backend="avis"
            )


if __name__ == "__main__":
    unittest.main()
