"""Hardware-free tests for simulator mode registration, settings and controls."""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from modes.registry import (
    CITY_VISION_MODES, RACE_VISION_MODES, SIMULATOR_MODES, get_mode_spec,
    is_simulation_mode, register_mode, ModeSpec,
)
from modes.simulation.base_adapter import VehicleCommand
from modes.simulation.controller import VirtualVehicleController
from modes.simulation.settings import (
    _validate_settings, load_simulator_settings, save_simulator_settings,
)
from modes.simulation.avis_adapter import AvisAdapter
from utils.parser import parse_args


class ModeRegistryTests(unittest.TestCase):
    def test_sim_modes_choose_city_and_race_vision_profiles(self):
        self.assertEqual(get_mode_spec("city").vision_profile, "city")
        self.assertEqual(get_mode_spec("race").vision_profile, "race")
        self.assertEqual(get_mode_spec("carla").vision_profile, "city")
        self.assertEqual(get_mode_spec("avis").vision_profile, "city")
        self.assertEqual(get_mode_spec("avis-race").vision_profile, "race")
        self.assertTrue({"carla", "avis", "avis-race"}.issubset(SIMULATOR_MODES))
        self.assertTrue({"city", "carla", "avis"}.issubset(CITY_VISION_MODES))
        self.assertTrue({"race", "avis-race"}.issubset(RACE_VISION_MODES))
        self.assertTrue(is_simulation_mode("CARLA"))
        self.assertFalse(is_simulation_mode("race"))

    def test_registry_validation_and_duplicates(self):
        with self.assertRaises(ValueError):
            register_mode(ModeSpec("invalid-test", "city", "city", runtime_kind="simulation"))
        with self.assertRaises(ValueError):
            register_mode(get_mode_spec("city"))


class SimulatorSettingsTests(unittest.TestCase):
    def test_settings_are_mode_specific_and_update_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config = SimpleNamespace(BASE_DIR=directory)
            carla_path = load_simulator_settings(config, "carla", "carla")
            save_simulator_settings(config, "carla", {
                "SIMULATOR_TARGET_SPEED": 12.0, "SIMULATOR_LIDAR_ENABLED": False,
                "CITY_LANE_DETECTOR": "blsf-beta",
            })
            self.assertTrue(carla_path.is_file())
            payload = json.loads(carla_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["SIMULATOR_TARGET_SPEED"], 12.0)
            self.assertFalse(payload["SIMULATOR_LIDAR_ENABLED"])
            self.assertEqual(config.CITY_LANE_DETECTOR, "blsf-beta")
            self.assertFalse((Path(directory) / "city.json").exists())
            self.assertFalse((Path(directory) / "race.json").exists())
            avis_path = load_simulator_settings(config, "avis", "avis")
            self.assertEqual(config.SIMULATOR_PORT, 25001)
            self.assertTrue(config.SIMULATOR_LIDAR_ENABLED is False)
            self.assertNotEqual(carla_path, avis_path)

    def test_avis_target_speed_remains_percentage_limited(self):
        with tempfile.TemporaryDirectory() as directory:
            config = SimpleNamespace(BASE_DIR=directory, SIMULATOR_BACKEND="avis")
            with self.assertRaisesRegex(ValueError, "AVIS Engine target speed"):
                save_simulator_settings(config, "avis", {"SIMULATOR_TARGET_SPEED": 150})
            with self.assertRaisesRegex(ValueError, "request timeout"):
                save_simulator_settings(config, "avis", {"SIMULATOR_TIMEOUT_S": 2.0})

    def test_settings_reject_unknown_invalid_and_cross_field_values(self):
        with self.assertRaises(ValueError):
            _validate_settings({"SIMULATOR_PASSWORD": "unexpected"})
        with self.assertRaises(ValueError):
            _validate_settings({"SIMULATOR_PORT": 99999})
        with self.assertRaises(ValueError):
            _validate_settings({"SIMULATOR_TARGET_SPEED": -1})
        self.assertEqual(_validate_settings({"SIMULATOR_TARGET_SPEED": 150})["SIMULATOR_TARGET_SPEED"], 150)
        with self.assertRaises(ValueError):
            _validate_settings({"SIMULATOR_OBSTACLE_STOP_DISTANCE_CM": 501})
        self.assertEqual(_validate_settings({"SIMULATOR_OBSTACLE_STOP_DISTANCE_CM": 0})["SIMULATOR_OBSTACLE_STOP_DISTANCE_CM"], 0)
        with self.assertRaises(ValueError):
            _validate_settings({"SIMULATOR_AVIS_SENSOR_ANGLE": -1})
        with self.assertRaises(ValueError):
            _validate_settings({"SIMULATOR_AVIS_SENSOR_ANGLE": 91})
        with self.assertRaises(ValueError):
            _validate_settings({"CITY_LANE_DETECTOR": "not-a-detector"})
        with self.assertRaises(ValueError):
            _validate_settings({"RL_TOP_ROI": 0.8, "RL_BOTTOM_ROI": 0.3})
        self.assertEqual(
            _validate_settings({
                "SIMULATOR_CAMERA_X": 1.45,
                "SIMULATOR_CAMERA_Y": 0.0,
                "SIMULATOR_CAMERA_Z": 1.8,
                "SIMULATOR_CAMERA_PITCH": -8.0,
                "SIMULATOR_CAMERA_YAW": 0.0,
                "SIMULATOR_CAMERA_ROLL": 0.0,
            })["SIMULATOR_CAMERA_Z"],
            1.8,
        )
        with self.assertRaisesRegex(ValueError, "CAMERA_X"):
            _validate_settings({"SIMULATOR_CAMERA_X": 20.1})
        with self.assertRaisesRegex(ValueError, "PITCH"):
            _validate_settings({"SIMULATOR_CAMERA_PITCH": 91})


class SimulatorEditorTests(unittest.TestCase):
    def test_simulator_editor_renders_with_mode_specific_capabilities(self):
        import os
        import stream
        from stream import WebStreamer

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(stream, "BASE_DIR", directory), patch.dict(
                os.environ, {"STREAM_USERNAME": "", "STREAM_PASSWORD": ""}
            ):
                for mode, backend, profile in (
                    ("carla", "carla", "city"),
                    ("avis", "avis", "city"),
                    ("avis-race", "avis", "race"),
                ):
                    config = SimpleNamespace(
                        BASE_DIR=directory,
                        MODE=mode,
                        SIMULATOR_BACKEND=backend,
                        SIMULATION_VISION_PROFILE=profile,
                        STREAM=True,
                        STREAM_HOST="127.0.0.1",
                        STREAM_PORT=41990,
                        STREAM_ALLOW_CONTROL=False,
                        RECORD_VIDEO=False,
                        USE_BEV=False,
                        USE_ML_LANE_DETECTOR=False,
                        CITY_LANE_DETECTOR="default",
                        WITHOUT_ARDUINO=True,
                        READ_ARDUINO_OUTPUT=False,
                        SEND_AUTOMATIC_ARDUINO_COMMANDS=False,
                        MIN_SERVO_ANGLE=50,
                        SERVO_CENTER=95,
                        MAX_SERVO_ANGLE=130,
                        debug_frames_list=[None, None],
                        stream_frame_seq=1,
                        OUTPUT_DIR=directory,
                    )
                    client = WebStreamer(config).app.test_client()
                    page = client.get("/")
                    self.assertEqual(page.status_code, 200, page.data[:300])
                    page_text = page.get_data(as_text=True)
                    self.assertIn("Simulator camera", page_text)
                    self.assertIn(mode.upper(), page_text)
                    self.assertIn("no-store", page.headers.get("Cache-Control", ""))
                    if backend == "carla":
                        self.assertIn("Open camera placement studio", page_text)
                        self.assertIn("camera-editor-modal", page_text)
                        self.assertIn("lidar-expand", page_text)
                    else:
                        self.assertNotIn("camera-editor-modal", page_text)

                    state = client.get("/api/simulation/settings")
                    self.assertEqual(state.status_code, 200, state.get_data(as_text=True))
                    payload = state.get_json()
                    self.assertEqual(payload["backend"], backend)
                    self.assertEqual(payload["vision_profile"], profile)
                    self.assertFalse(payload["controls_enabled"])

                    denied = client.post(
                        "/api/simulation/settings",
                        json={"SIMULATOR_TARGET_SPEED": 5.0},
                    )
                    self.assertEqual(denied.status_code, 403)
                    if backend == "carla":
                        camera_denied = client.post(
                            "/api/simulation/carla-camera",
                            json={"action": "open"},
                        )
                        self.assertEqual(camera_denied.status_code, 403)


class VirtualControllerTests(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace(
            MIN_SERVO_ANGLE=50, SERVO_CENTER=95, MAX_SERVO_ANGLE=130,
            SIMULATOR_TARGET_SPEED=20.0, SIMULATOR_THROTTLE_LIMIT=0.3,
            SIMULATOR_STOP_ON_LOST_LANE=True, SIMULATOR_STEERING_INVERTED=False,
        )

    def test_invalid_perception_brakes_and_retains_steering(self):
        controller = VirtualVehicleController(self.config, "carla")
        before = controller.last_servo
        command = controller.command_for({"perception_valid": False}, speed_kmh=0.0)
        self.assertEqual(command.brake, 1.0)
        self.assertEqual(command.throttle, 0.0)
        self.assertEqual(command.servo_angle, before)

    def test_valid_perception_is_clamped_and_throttle_limited(self):
        controller = VirtualVehicleController(self.config, "carla")
        command = controller.command_for({"perception_valid": True, "steering_angle": 180}, speed_kmh=0.0)
        self.assertEqual(command.servo_angle, 130)
        self.assertEqual(command.steering, 1.0)
        self.assertLessEqual(command.throttle, 0.3)
        self.assertGreaterEqual(command.throttle, 0.0)

    def test_avis_adapter_normalizes_sensor_values_and_outputs(self):
        class FakeCar:
            def __init__(self):
                self.commands = []
                self.angle = None
            def connect(self, host, port):
                self.commands.append(("connect", host, port))
            def setSensorAngle(self, angle):
                self.angle = angle
            def getData(self):
                return None
            def getImage(self):
                return np.zeros((12, 16, 3), dtype=np.uint8)
            def getSensors(self):
                return [21.0, 30.5, -1.0]
            def getSpeed(self):
                return 4.0
            def setSteering(self, steering):
                self.commands.append(("steering", steering))
            def setSpeed(self, speed):
                self.commands.append(("speed", speed))
            def stop(self):
                self.commands.append(("stop",))
        fake = FakeCar()
        module = types.SimpleNamespace(Car=lambda: fake)
        config = SimpleNamespace(SIMULATOR_HOST="127.0.0.1", SIMULATOR_PORT=25001,
                                 SIMULATOR_TIMEOUT_S=1.0, SIMULATOR_AVIS_SENSOR_ANGLE=15)
        with patch.dict(sys.modules, {"avisengine": module}):
            adapter = AvisAdapter(config)
            adapter.connect()
            frame = adapter.read()
            self.assertEqual(frame.image.shape, (12, 16, 3))
            self.assertEqual(frame.ranges_cm, {"left": 21.0, "front": 30.5, "right": None})
            self.assertIsNone(frame.lidar_points)
            command = VehicleCommand(0.25, 0.2, 0.0, 105, 20, "test")
            self.assertTrue(adapter.apply_control(command))
            self.assertIn(("steering", 25), fake.commands)
            self.assertIn(("speed", 20), fake.commands)
            self.assertEqual(fake.angle, 15)
            adapter.close()
            self.assertIn(("stop",), fake.commands)

    def test_avis_adapter_returns_none_when_server_has_no_camera_frame(self):
        class EmptyCar:
            def getImage(self):
                return None
            def getData(self):
                return None
        adapter = AvisAdapter(SimpleNamespace())
        adapter.car = EmptyCar()
        adapter.connected = True
        self.assertIsNone(adapter.read())

    def test_cli_accepts_simulation_modes_and_options(self):
        args = parse_args(["--mode", "carla", "--simulator-host", "10.0.0.2",
                           "--simulator-port", "2100", "--simulator-lidar",
                           "--simulator-target-speed", "7",
                           "--simulator-stop-on-crosswalk",
                           "--simulator-obstacle-stop-distance-cm", "42"])
        self.assertEqual(args.mode, "carla")
        self.assertEqual(args.simulator_host, "10.0.0.2")
        self.assertEqual(args.simulator_port, 2100)
        self.assertTrue(args.simulator_lidar)
        self.assertEqual(args.simulator_target_speed, 7.0)
        self.assertTrue(args.simulator_stop_on_crosswalk)
        self.assertEqual(args.simulator_obstacle_stop_distance_cm, 42.0)
        self.assertEqual(parse_args(["--mode", "avis-race"]).mode, "avis-race")


if __name__ == "__main__":
    unittest.main()
