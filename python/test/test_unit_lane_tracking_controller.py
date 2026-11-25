import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from modes.simulation.controller import VirtualVehicleController


def make_config():
    return SimpleNamespace(
        MIN_SERVO_ANGLE=55.0,
        SERVO_CENTER=95.0,
        MAX_SERVO_ANGLE=125.0,
        USE_PID=False,
        SIMULATOR_TARGET_SPEED=20.0,
        SIMULATOR_THROTTLE_LIMIT=0.5,
        SIMULATOR_STOP_ON_LOST_LANE=True,
        SIMULATOR_STEERING_LIMIT=1.0,
        SIMULATOR_STEERING_RATE=10.0,
        SIMULATOR_THROTTLE_RISE_RATE=1.0,
        SIMULATOR_STEERING_INVERTED=False,
    )


class LaneTrackingControllerTests(unittest.TestCase):
    def test_single_boundary_tracking_continues_at_reduced_speed_for_both_backends(self):
        for backend in ("carla", "avis"):
            with self.subTest(backend=backend):
                with patch("modes.simulation.controller.time.monotonic", side_effect=[10.0, 10.2]):
                    controller = VirtualVehicleController(make_config(), backend)
                    command = controller.command_for({
                        "perception_valid": True,
                        "steering_angle": 98.0,
                        "line_tracking": {"enabled": True, "speed_factor": 0.55},
                    })
                self.assertEqual(command.target_speed, 11.0)
                self.assertEqual(command.brake, 0.0)
                self.assertGreater(command.throttle, 0.0)

    def test_two_boundary_tracking_keeps_configured_speed(self):
        controller = VirtualVehicleController(make_config(), "carla")
        command = controller.command_for({
            "perception_valid": True,
            "steering_angle": 95.0,
            "line_tracking": {"enabled": True, "speed_factor": 1.0},
        })
        self.assertEqual(command.target_speed, 20.0)

    def test_lost_perception_still_uses_existing_safe_brake_policy(self):
        controller = VirtualVehicleController(make_config(), "carla")
        command = controller.command_for({
            "perception_valid": False,
            "line_tracking": {"enabled": True, "speed_factor": 0.0},
        })
        self.assertEqual(command.throttle, 0.0)
        self.assertEqual(command.brake, 1.0)

    def test_other_detectors_are_not_speed_scaled(self):
        controller = VirtualVehicleController(make_config(), "avis")
        command = controller.command_for({
            "perception_valid": True,
            "steering_angle": 95.0,
            "line_tracking": {"enabled": False, "state": "DISABLED"},
        })
        self.assertEqual(command.target_speed, 20.0)


if __name__ == "__main__":
    unittest.main()
