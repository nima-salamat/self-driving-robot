"""Hardware-free tests for simulator mode registration, settings and controls."""
import base64
import json
import re
import sys
import tempfile
import types
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from avisengine import Car

from modes.registry import (
    CITY_VISION_MODES, RACE_VISION_MODES, SIMULATOR_MODES, get_mode_spec,
    is_simulation_mode, register_mode, ModeSpec,
)
from modes.simulation.base_adapter import VehicleCommand
from modes.simulation.controller import VirtualVehicleController
from modes.simulation.settings import (
    SIMULATOR_KEYS, _validate_settings, load_simulator_settings, save_simulator_settings,
)
from modes.simulation.avis_adapter import AvisAdapter
from utils.parser import parse_args


class AvisEngineProtocolTests(unittest.TestCase):
    def test_get_data_decodes_tagged_jpeg_using_legacy_avis_protocol(self):
        class FakeSocket:
            def __init__(self, payload):
                self.payload = payload
            def sendall(self, data):
                pass
            def recv(self, size):
                payload, self.payload = self.payload, b""
                return payload

        source = np.full((12, 16, 3), 127, dtype=np.uint8)
        ok, encoded = cv2.imencode(".jpg", source)
        self.assertTrue(ok)
        payload = (
            b"<image>" + base64.b64encode(encoded.tobytes()) + b"</image>"
            + b"<sensor>21,30,42</sensor><speed>0</speed><EOF>"
        )
        car = Car()
        car.sock = FakeSocket(payload)
        self.assertTrue(car.getData())
        self.assertEqual(car.image.shape[:2], (12, 16))
        self.assertEqual(car.image_sequence, 1)
        self.assertTrue(car.last_response_info["image_tag"])
        self.assertEqual(car.last_response_info["image_payload_format"], "tagged-base64")
        car.sock = None

    def test_get_data_accepts_wrapped_base64_inside_image_tag(self):
        class FakeSocket:
            def __init__(self, payload):
                self.payload = payload
            def sendall(self, data):
                pass
            def recv(self, size):
                payload, self.payload = self.payload, b""
                return payload

        source = np.full((12, 16, 3), 127, dtype=np.uint8)
        ok, encoded = cv2.imencode(".jpg", source)
        self.assertTrue(ok)
        base64_text = base64.b64encode(encoded.tobytes()).decode("ascii")
        wrapped = "\n".join(base64_text[index:index + 48] for index in range(0, len(base64_text), 48))
        payload = (
            "<image>\n" + wrapped + "\n</image>"
            "<sensor>21,30,42</sensor><speed>0</speed><EOF>"
        ).encode("utf-8")
        car = Car()
        car.sock = FakeSocket(payload)
        self.assertTrue(car.getData())
        self.assertEqual(car.image.shape[:2], (12, 16))
        self.assertEqual(car.last_response_info["image_payload_format"], "tagged-base64")
        car.sock = None

    def test_get_data_decodes_bare_base64_jpeg_before_legacy_sensor_metadata(self):
        class FakeSocket:
            def __init__(self, payload):
                self.payload = payload
            def sendall(self, data):
                pass
            def recv(self, size):
                payload, self.payload = self.payload, b""
                return payload

        source = np.full((12, 16, 3), 127, dtype=np.uint8)
        ok, encoded = cv2.imencode(".jpg", source)
        self.assertTrue(ok)
        payload = (
            base64.b64encode(encoded.tobytes())
            + b"<sensor>21,30,42</sensor><speed>0</speed><EOF>"
        )
        car = Car()
        car.sock = FakeSocket(payload)
        self.assertTrue(car.getData())
        self.assertEqual(car.image.shape[:2], (12, 16))
        self.assertEqual(car.image_sequence, 1)
        self.assertFalse(car.last_response_info["image_tag"])
        self.assertTrue(car.last_response_info["sensor_tag"])
        self.assertTrue(car.last_response_info["speed_tag"])
        self.assertEqual(car.last_response_info["image_payload_format"], "leading-base64")
        car.sock = None

    def test_get_data_accepts_unpadded_urlsafe_base64_png(self):
        class FakeSocket:
            def __init__(self, payload):
                self.payload = payload
            def sendall(self, data):
                pass
            def recv(self, size):
                payload, self.payload = self.payload, b""
                return payload

        source = np.full((9, 13, 3), 91, dtype=np.uint8)
        ok, encoded = cv2.imencode(".png", source)
        self.assertTrue(ok)
        payload = base64.urlsafe_b64encode(encoded.tobytes()).rstrip(b"=")
        payload += b"<sensor>21,30,42</sensor><speed>0</speed><EOF>"
        car = Car()
        car.sock = FakeSocket(payload)
        self.assertTrue(car.getData())
        self.assertEqual(car.image.shape[:2], (9, 13))
        self.assertEqual(car.last_response_info["image_payload_format"], "leading-base64")
        self.assertEqual(car.last_response_info["image_format"], "png")
        car.sock = None

    def test_get_data_decodes_zlib_compressed_base64_jpeg(self):
        class FakeSocket:
            def __init__(self, payload):
                self.payload = payload
            def sendall(self, data):
                pass
            def recv(self, size):
                payload, self.payload = self.payload, b""
                return payload

        source = np.full((15, 19, 3), 111, dtype=np.uint8)
        ok, encoded = cv2.imencode(".jpg", source)
        self.assertTrue(ok)
        compressed = zlib.compress(encoded.tobytes())
        payload = (
            base64.b64encode(compressed)
            + b"<sensor>21,30,42</sensor><speed>0</speed><EOF>"
        )
        car = Car()
        car.sock = FakeSocket(payload)
        self.assertTrue(car.getData())
        self.assertEqual(car.image.shape[:2], (15, 19))
        self.assertEqual(car.last_response_info["image_transport_encoding"], "zlib")
        self.assertEqual(car.last_response_info["image_format"], "jpeg")
        car.sock = None

    def test_get_data_decodes_image_after_validated_transport_header(self):
        class FakeSocket:
            def __init__(self, payload):
                self.payload = payload
            def sendall(self, data):
                pass
            def recv(self, size):
                payload, self.payload = self.payload, b""
                return payload

        source = np.full((11, 17, 3), 153, dtype=np.uint8)
        ok, encoded = cv2.imencode(".jpg", source)
        self.assertTrue(ok)
        raw = b"AVIS\x01\x00" + encoded.tobytes()
        payload = base64.b64encode(raw) + b"<sensor>21,30,42</sensor><speed>0</speed><EOF>"
        car = Car()
        car.sock = FakeSocket(payload)
        self.assertTrue(car.getData())
        self.assertEqual(car.image.shape[:2], (11, 17))
        self.assertEqual(car.last_response_info["image_payload_offset_bytes"], 6)
        self.assertEqual(car.last_response_info["image_format"], "jpeg")
        car.sock = None

    def test_get_data_does_not_send_unknown_base64_to_opencv(self):
        class FakeSocket:
            def __init__(self, payload):
                self.payload = payload
            def sendall(self, data):
                pass
            def recv(self, size):
                payload, self.payload = self.payload, b""
                return payload

        raw = b"telemetry-is-not-an-image-BM-not-a-bitmap-header"
        payload = (
            base64.b64encode(raw)
            + b"<sensor>21,30,42</sensor><speed>0</speed><EOF>"
        )
        car = Car()
        car.sock = FakeSocket(payload)
        with patch("avisengine.cv2.imdecode") as decode:
            self.assertFalse(car.getData())
            decode.assert_not_called()
        self.assertEqual(car.last_response_info["image_payload_magic"], "unknown")
        self.assertEqual(car.last_response_info["image_payload_prefix_hex"], raw[:12].hex())
        self.assertIn("Unsupported AVIS image payload signature", car.last_response_info["decode_error"])
        car.sock = None

    def test_get_data_rejects_base64_payload_that_is_not_a_jpeg(self):
        class FakeSocket:
            def __init__(self, payload):
                self.payload = payload
            def sendall(self, data):
                pass
            def recv(self, size):
                payload, self.payload = self.payload, b""
                return payload

        payload = (
            base64.b64encode(b"not an image" * 30)
            + b"<sensor>21,30,42</sensor><speed>0</speed><EOF>"
        )
        car = Car()
        car.sock = FakeSocket(payload)
        self.assertFalse(car.getData())
        self.assertIsNone(car.image)
        self.assertFalse(car.last_response_info["image_decoded"])
        self.assertIn("Unsupported AVIS image payload signature", car.last_response_info["decode_error"])
        car.sock = None

    def test_get_data_decodes_raw_binary_jpeg_without_utf8_conversion(self):
        class FakeSocket:
            def __init__(self, payload):
                self.payload = payload
            def sendall(self, data):
                pass
            def recv(self, size):
                payload, self.payload = self.payload, b""
                return payload

        source = np.full((12, 16, 3), 127, dtype=np.uint8)
        ok, encoded = cv2.imencode(".jpg", source)
        self.assertTrue(ok)
        payload = (
            b"\x00\xffAVIS" + encoded.tobytes()
            + b"<sensor>21,30,42</sensor><speed>0</speed><EOF>"
        )
        car = Car()
        car.sock = FakeSocket(payload)
        self.assertTrue(car.getData())
        self.assertEqual(car.image.shape[:2], (12, 16))
        self.assertEqual(car.last_response_info["image_payload_format"], "raw-binary")
        self.assertEqual(car.last_response_info["response_bytes"], len(payload))
        car.sock = None

    def test_get_data_keeps_unrecognized_binary_response_as_a_decode_diagnostic(self):
        class FakeSocket:
            def __init__(self, payload):
                self.payload = payload
            def sendall(self, data):
                pass
            def recv(self, size):
                payload, self.payload = self.payload, b""
                return payload

        payload = b"\x89\xff\x00\x17binary-data<sensor>10,20,30</sensor><EOF>"
        car = Car()
        car.sock = FakeSocket(payload)
        self.assertFalse(car.getData())
        self.assertFalse(car.last_response_info["image_decoded"])
        self.assertIn("Unsupported AVIS image payload signature", car.last_response_info["decode_error"])
        self.assertEqual(car.last_response_info["response_bytes"], len(payload))
        car.sock = None

    def test_get_data_does_not_treat_sensor_only_response_as_a_fresh_image(self):
        class FakeSocket:
            def __init__(self, payload):
                self.payload = payload
            def sendall(self, data):
                pass
            def recv(self, size):
                payload, self.payload = self.payload, b""
                return payload

        car = Car()
        car.sock = FakeSocket(b"<sensor>21,30,42</sensor><speed>0</speed><EOF>")
        self.assertFalse(car.getData())
        self.assertIsNone(car.image)
        self.assertEqual(car.image_sequence, 0)
        self.assertTrue(car.last_response_info["sensor_tag"])
        self.assertFalse(car.last_response_info["image_decoded"])
        car.sock = None


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
    def test_avis_uses_configured_tcp_timeout_without_one_second_cap(self):
        self.assertEqual(AvisAdapter(SimpleNamespace())._request_timeout(), 5.0)
        self.assertEqual(
            AvisAdapter(SimpleNamespace(SIMULATOR_TIMEOUT_S=8.5))._request_timeout(),
            8.5,
        )
        self.assertEqual(
            AvisAdapter(SimpleNamespace(SIMULATOR_TIMEOUT_S=90.0))._request_timeout(),
            60.0,
        )

    def test_settings_are_mode_specific_and_update_config(self):
        with tempfile.TemporaryDirectory() as directory:
            config = SimpleNamespace(BASE_DIR=directory)
            carla_path = load_simulator_settings(config, "carla", "carla")
            self.assertEqual(config.SIMULATOR_TARGET_SPEED, 5.0)
            self.assertEqual(config.SIMULATOR_THROTTLE_LIMIT, 0.12)
            self.assertEqual(config.SIMULATOR_STEERING_LIMIT, 0.28)
            self.assertEqual(config.SIMULATOR_STEERING_RATE, 0.80)
            self.assertEqual(config.SIMULATOR_THROTTLE_RISE_RATE, 0.12)
            self.assertFalse(config.USE_BEV)
            self.assertEqual(config.LANE_THRESHOLD, 180)
            self.assertEqual(config.CROSSWALK_VERTICAL_MIN_LINES, 6)
            self.assertFalse(config.ROI_RESIZABLE)
            self.assertEqual(config.MIN_SERVO_ANGLE, 55.0)
            self.assertEqual(config.SERVO_CENTER, 95.0)
            self.assertEqual(config.MAX_SERVO_ANGLE, 125.0)
            save_simulator_settings(config, "carla", {
                "SIMULATOR_TARGET_SPEED": 7.0, "SIMULATOR_THROTTLE_LIMIT": 0.15,
                "SIMULATOR_STEERING_LIMIT": 0.35, "SIMULATOR_STEERING_RATE": 1.0,
                "SIMULATOR_THROTTLE_RISE_RATE": 0.20, "SIMULATOR_LIDAR_ENABLED": False,
                "CITY_LANE_DETECTOR": "blsf-beta", "LANE_THRESHOLD": 145,
                "HOUGH_THRESHOLD": 24, "CROSSWALK_THRESHOLD": 160,
                "LANE_ROI_MODE": "trapezoid", "RL_TOP_WIDTH_FACTOR": 0.7,
                "ROI_RESIZABLE": True, "MIN_SERVO_ANGLE": 45.0,
                "SERVO_CENTER": 92.0, "MAX_SERVO_ANGLE": 135.0,
                "SERVO_DIRECTION": "rtl",
            })
            self.assertTrue(carla_path.is_file())
            payload = json.loads(carla_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["SIMULATOR_TARGET_SPEED"], 7.0)
            self.assertEqual(payload["SIMULATOR_THROTTLE_LIMIT"], 0.15)
            self.assertEqual(config.SIMULATOR_STEERING_LIMIT, 0.35)
            self.assertEqual(config.SIMULATOR_STEERING_RATE, 1.0)
            self.assertFalse(payload["SIMULATOR_LIDAR_ENABLED"])
            self.assertEqual(config.CITY_LANE_DETECTOR, "blsf-beta")
            self.assertEqual(config.LANE_THRESHOLD, 145)
            self.assertEqual(config.HOUGH_THRESHOLD, 24)
            self.assertEqual(config.CROSSWALK_THRESHOLD, 160)
            self.assertEqual(config.LANE_ROI_MODE, "trapezoid")
            self.assertEqual(config.RL_TOP_WIDTH_FACTOR, 0.7)
            self.assertTrue(config.ROI_RESIZABLE)
            self.assertEqual(config.MIN_SERVO_ANGLE, 45.0)
            self.assertEqual(config.SERVO_CENTER, 92.0)
            self.assertEqual(config.MAX_SERVO_ANGLE, 135.0)
            self.assertEqual(config.SERVO_DIRECTION, "rtl")
            self.assertFalse((Path(directory) / "city.json").exists())
            self.assertFalse((Path(directory) / "race.json").exists())
            avis_path = load_simulator_settings(config, "avis", "avis")
            self.assertEqual(config.SIMULATOR_PORT, 25001)
            self.assertEqual(config.SIMULATOR_STEERING_LIMIT, 1.0)
            self.assertEqual(config.SIMULATOR_STEERING_RATE, 2.0)
            self.assertTrue(config.SIMULATOR_LIDAR_ENABLED is False)
            self.assertNotEqual(carla_path, avis_path)

    def test_carla_map_load_uses_long_timeout_and_restores_client_timeout(self):
        from modes.simulation.carla_adapter import CarlaAdapter

        class FakeClient:
            def __init__(self):
                self.timeouts = []
                self.world = object()
            def set_timeout(self, value):
                self.timeouts.append(float(value))
            def load_world(self, map_name):
                self.map_name = map_name
                return self.world

        adapter = CarlaAdapter(SimpleNamespace(SIMULATOR_TIMEOUT_S=5.0))
        client = FakeClient()
        adapter.client = client
        self.assertIs(adapter._load_world_with_timeout("Town05"), client.world)
        self.assertEqual(client.map_name, "Town05")
        self.assertEqual(client.timeouts, [120.0, 5.0])

    def test_legacy_carla_profile_is_clamped_to_safe_motion_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "carla.sim.json"
            profile.write_text(json.dumps({
                "SIMULATOR_TARGET_SPEED": 50.0,
                "SIMULATOR_THROTTLE_LIMIT": 0.70,
                "SIMULATOR_STEERING_LIMIT": 1.0,
                "SIMULATOR_STEERING_RATE": 5.0,
                "SIMULATOR_THROTTLE_RISE_RATE": 1.0,
            }), encoding="utf-8")
            config = SimpleNamespace(BASE_DIR=directory)
            load_simulator_settings(config, "carla", "carla")
            self.assertEqual(config.SIMULATOR_TARGET_SPEED, 5.0)
            self.assertEqual(config.SIMULATOR_THROTTLE_LIMIT, 0.12)
            self.assertEqual(config.SIMULATOR_STEERING_LIMIT, 0.28)
            self.assertEqual(config.SIMULATOR_STEERING_RATE, 0.80)
            self.assertEqual(config.SIMULATOR_THROTTLE_RISE_RATE, 0.12)

    def test_carla_user_tuning_exceeds_old_caps_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            config = SimpleNamespace(BASE_DIR=directory)
            load_simulator_settings(config, "carla", "carla")
            path = save_simulator_settings(config, "carla", {
                "SIMULATOR_TARGET_SPEED": 12.5,
                "SIMULATOR_THROTTLE_LIMIT": 0.42,
                "SIMULATOR_STEERING_LIMIT": 0.75,
                "SIMULATOR_STEERING_RATE": 3.5,
                "SIMULATOR_THROTTLE_RISE_RATE": 0.65,
                "RL_TOP_ROI": 0.1,
                "RL_MIRRORED": True,
                "LL_MIRRORED": True,
            })
            self.assertEqual(path["SIMULATOR_TARGET_SPEED"], 12.5)
            self.assertEqual(path["SIMULATOR_THROTTLE_LIMIT"], 0.42)
            profile = json.loads((Path(directory) / "carla.sim.json").read_text(encoding="utf-8"))
            self.assertEqual(profile["SIMULATOR_TUNING_PROFILE_VERSION"], 2)
            self.assertEqual(profile["RL_TOP_ROI"], 0.1)
            self.assertTrue(profile["RL_MIRRORED"])
            self.assertTrue(profile["LL_MIRRORED"])
            restarted = SimpleNamespace(BASE_DIR=directory)
            load_simulator_settings(restarted, "carla", "carla")
            self.assertEqual(restarted.SIMULATOR_TARGET_SPEED, 12.5)
            self.assertEqual(restarted.SIMULATOR_THROTTLE_LIMIT, 0.42)
            self.assertEqual(restarted.RL_TOP_ROI, 0.1)
            self.assertEqual(restarted.SIMULATOR_STEERING_LIMIT, 0.75)
            self.assertEqual(restarted.SIMULATOR_STEERING_RATE, 3.5)
            self.assertEqual(restarted.SIMULATOR_THROTTLE_RISE_RATE, 0.65)
            self.assertTrue(restarted.RL_MIRRORED)
            self.assertTrue(restarted.LL_MIRRORED)

    def test_avis_and_avis_race_default_stream_settings_are_valid(self):
        # Mirror the shared settings submitted by the Stream editor. Race must
        # not submit City-only RL/LL mirror toggles when those controls are hidden.
        common_stream_settings = {
            "SIMULATOR_HOST": "127.0.0.1",
            "SIMULATOR_PORT": 25001,
            "SIMULATOR_TIMEOUT_S": 5.0,
            "SIMULATOR_TARGET_SPEED": 25.0,
            "SIMULATOR_THROTTLE_LIMIT": 0.35,
            "SIMULATOR_STOP_ON_LOST_LANE": True,
            "SIMULATOR_STEERING_INVERTED": False,
            "DEBUG": False,
            "HALL_LINE_TRACKING_ENABLED": False,
            "HALL_LINE_TRACKING_MAX_MISSED": 4,
            "MIN_SERVO_ANGLE": 55.0,
            "SERVO_CENTER": 95.0,
            "MAX_SERVO_ANGLE": 125.0,
            "SERVO_DIRECTION": "ltr",
            "SIMULATOR_OBSTACLE_STOP_DISTANCE_CM": 35.0,
            "ENCODER_PULSE_DISTANCE_CM": 0.5,
            "RL_TOP_ROI": 0.8, "RL_BOTTOM_ROI": 1.0,
            "RL_LEFT_ROI": 0.6, "RL_RIGHT_ROI": 0.9,
            "LL_TOP_ROI": 0.8, "LL_BOTTOM_ROI": 1.0,
            "LL_LEFT_ROI": 0.2, "LL_RIGHT_ROI": 0.5,
            "USE_BEV": False,
        }
        for mode in ("avis", "avis-race"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                config = SimpleNamespace(BASE_DIR=directory, SIMULATOR_BACKEND="avis")
                load_simulator_settings(config, mode, "avis")
                saved = save_simulator_settings(config, mode, common_stream_settings)
                self.assertEqual(saved["SIMULATOR_TIMEOUT_S"], 5.0)
                self.assertEqual(saved["SIMULATOR_TARGET_SPEED"], 25.0)
                self.assertEqual(saved["SIMULATOR_THROTTLE_LIMIT"], 0.35)
                self.assertNotIn("RL_MIRRORED", saved)
                self.assertNotIn("LL_MIRRORED", saved)

    def test_backend_aware_target_speed_validation_uses_aviss_percentage_range(self):
        self.assertEqual(
            _validate_settings({"SIMULATOR_TARGET_SPEED": 100}, backend="avis")["SIMULATOR_TARGET_SPEED"],
            100,
        )
        with self.assertRaisesRegex(ValueError, "AVIS percentage"):
            _validate_settings({"SIMULATOR_TARGET_SPEED": 100.1}, backend="avis")
        self.assertEqual(
            _validate_settings({"SIMULATOR_TARGET_SPEED": 200}, backend="carla")["SIMULATOR_TARGET_SPEED"],
            200,
        )
        with self.assertRaisesRegex(ValueError, "200 km/h"):
            _validate_settings({"SIMULATOR_TARGET_SPEED": 200.1}, backend="carla")

    def test_avis_target_speed_remains_percentage_limited_and_timeout_is_configurable(self):
        with tempfile.TemporaryDirectory() as directory:
            config = SimpleNamespace(BASE_DIR=directory, SIMULATOR_BACKEND="avis")
            with self.assertRaisesRegex(ValueError, "AVIS percentage"):
                save_simulator_settings(config, "avis", {"SIMULATOR_TARGET_SPEED": 150})
            saved = save_simulator_settings(config, "avis", {"SIMULATOR_TIMEOUT_S": 5.0})
            self.assertEqual(saved["SIMULATOR_TIMEOUT_S"], 5.0)
            restarted = SimpleNamespace(BASE_DIR=directory)
            load_simulator_settings(restarted, "avis", "avis")
            self.assertEqual(restarted.SIMULATOR_TIMEOUT_S, 5.0)

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
        with self.assertRaisesRegex(ValueError, "HOUGH_BLUR_KERNEL"):
            _validate_settings({"HOUGH_BLUR_KERNEL": 4})
        with self.assertRaisesRegex(ValueError, "LANE_ROI_MODE"):
            _validate_settings({"LANE_ROI_MODE": "ellipse"})
        with self.assertRaisesRegex(ValueError, "CROSSWALK_THRESHOLD"):
            _validate_settings({"CROSSWALK_THRESHOLD": 300})
        self.assertEqual(_validate_settings({"BEV_SRC_TL_X": 0.25})["BEV_SRC_TL_X"], 0.25)
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

        self.assertEqual(_validate_settings({"SIMULATOR_MAP": "current"})["SIMULATOR_MAP"], "current")
        self.assertEqual(_validate_settings({"SIMULATOR_VEHICLE_BLUEPRINT": "vehicle.tesla.model3"})["SIMULATOR_VEHICLE_BLUEPRINT"], "vehicle.tesla.model3")
        self.assertEqual(_validate_settings({"SIMULATOR_SPAWN_POINT_INDEX": -1})["SIMULATOR_SPAWN_POINT_INDEX"], -1)
        with self.assertRaisesRegex(ValueError, "SPAWN_POINT_INDEX"):
            _validate_settings({"SIMULATOR_SPAWN_POINT_INDEX": -2})
        with self.assertRaisesRegex(ValueError, "blueprint"):
            _validate_settings({"SIMULATOR_VEHICLE_BLUEPRINT": "walker.pedestrian.*"})


class SimulatorSettingsApiTests(unittest.TestCase):
    def test_avis_default_stream_payload_passes_api_for_city_and_race(self):
        from flask import Flask
        from stream.simulator_api import register_simulator_routes

        class StreamStub:
            def __init__(self, config):
                self.config = config
            def _control_allowed(self):
                return True
            def _control_denied(self):
                raise AssertionError("Control should be enabled for this test")

        # Build the body the browser submits from the active mode's defaults.
        common = (
            "SIMULATOR_HOST", "SIMULATOR_PORT", "SIMULATOR_TIMEOUT_S",
            "SIMULATOR_TARGET_SPEED", "SIMULATOR_THROTTLE_LIMIT",
            "SIMULATOR_STOP_ON_LOST_LANE", "SIMULATOR_STEERING_INVERTED",
            "DEBUG", "HALL_LINE_TRACKING_ENABLED", "HALL_LINE_TRACKING_MAX_MISSED",
            "MIN_SERVO_ANGLE", "SERVO_CENTER", "MAX_SERVO_ANGLE", "SERVO_DIRECTION",
            "SIMULATOR_OBSTACLE_STOP_DISTANCE_CM", "ENCODER_PULSE_DISTANCE_CM",
            "SIMULATOR_AVIS_SENSOR_ANGLE",
        )
        lane_roi = (
            "RL_TOP_ROI", "RL_BOTTOM_ROI", "RL_LEFT_ROI", "RL_RIGHT_ROI",
            "LL_TOP_ROI", "LL_BOTTOM_ROI", "LL_LEFT_ROI", "LL_RIGHT_ROI",
        )
        city_only = (
            "CITY_LANE_DETECTOR", "LANE_THRESHOLD", "HOUGH_THRESHOLD",
            "HOUGH_MIN_LINE_LENGTH", "HOUGH_MAX_LINE_GAP", "HOUGH_BLUR_KERNEL",
            "LANE_ROI_MODE", "CAMERA_PITCH_DEG", "CAMERA_HEIGHT", "LANE_WIDTH",
            "HOUGH_MORPH_CLOSE", "OLD_METHOD", "ROI_RESIZABLE",
            "RL_TOP_WIDTH_FACTOR", "LL_TOP_WIDTH_FACTOR",
            "CROSSWALK_THRESHOLD", "CROSSWALK_VERTICAL_MIN_LINES",
            "CROSSWALK_HORIZONTAL_MIN_LINES", "CW_TOP_WIDTH_FACTOR",
            "CW_TRAPEZOID_MODE", "CW_OLD_METHOD",
            "CW_TOP_ROI", "CW_BOTTOM_ROI", "CW_LEFT_ROI", "CW_RIGHT_ROI",
            "SIMULATOR_STOP_ON_CROSSWALK", "RL_MIRRORED", "LL_MIRRORED",
        )
        bev = (
            "USE_BEV", "BEV_SRC_TL_X", "BEV_SRC_TL_Y", "BEV_SRC_TR_X",
            "BEV_SRC_TR_Y", "BEV_SRC_BR_X", "BEV_SRC_BR_Y",
            "BEV_SRC_BL_X", "BEV_SRC_BL_Y",
        )

        for mode, profile in (("avis", "city"), ("avis-race", "race")):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                config = SimpleNamespace(
                    BASE_DIR=directory, MODE=mode,
                    SIMULATION_VISION_PROFILE=profile, SIMULATOR_BACKEND="avis",
                    STREAM_ALLOW_CONTROL=True,
                )
                load_simulator_settings(config, mode, "avis")
                defaults = {key: getattr(config, key) for key in SIMULATOR_KEYS if hasattr(config, key)}
                payload = {key: defaults[key] for key in common + lane_roi}
                payload.update({key: defaults[key] for key in bev})
                if profile == "city":
                    payload.update({key: defaults[key] for key in city_only})
                else:
                    payload["USE_ML_LANE_DETECTOR"] = defaults["USE_ML_LANE_DETECTOR"]
                    payload["ML_LANE_MODEL"] = defaults["ML_LANE_MODEL"]

                app = Flask(__name__)
                register_simulator_routes(app, StreamStub(config))
                response = app.test_client().post(
                    "/api/simulation/settings",
                    json={"settings": payload},
                )
                self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
                saved = response.get_json()["settings"]
                self.assertEqual(saved["SIMULATOR_TIMEOUT_S"], 5.0)
                self.assertEqual(saved["SIMULATOR_TARGET_SPEED"], 25.0)
                self.assertEqual(saved["SIMULATOR_THROTTLE_LIMIT"], 0.35)

    def test_simulator_editor_does_not_save_before_load_or_coerce_empty_numbers(self):
        from pathlib import Path

        template = (
            Path(__file__).resolve().parents[1]
            / "stream" / "templates" / "simulator_editor.html"
        ).read_text(encoding="utf-8")
        self.assertIn("function readSettingNumber(id)", template)
        self.assertIn("function collectSimulatorSettings()", template)
        self.assertIn('control.closest(".section-hide")', template)
        self.assertIn("camera-stale-overlay", template)
        self.assertIn("simulatorSettingsReady=false", template)
        self.assertIn('id="save-settings" disabled', template)
        self.assertIn("is empty. Reload saved defaults", template)
        decimal_settings = (
            "SIMULATOR_LIDAR_RANGE_M", "SIMULATOR_LIDAR_ROTATION_FREQUENCY",
            "SIMULATOR_CAMERA_FOV", "SIMULATOR_OBSTACLE_STOP_DISTANCE_CM",
            "ENCODER_PULSE_DISTANCE_CM", "CAMERA_PITCH_DEG", "CAMERA_HEIGHT",
            "LANE_WIDTH", "MIN_SERVO_ANGLE", "SERVO_CENTER", "MAX_SERVO_ANGLE",
        )
        for name in decimal_settings:
            with self.subTest(setting=name):
                match = re.search(
                    r'<input\b(?=[^>]*\bname="' + re.escape(name) + r'")[^>]*>',
                    template,
                )
                self.assertIsNotNone(match, name + " input was not found")
                self.assertIn('step="any"', match.group(0), name + " rejects decimal values in the browser")


class CityRoiMirroringTests(unittest.TestCase):
    def test_lane_roi_mirror_flips_crop_mask_and_restores_detection_coordinates(self):
        from vision.city_vision_processing import VisionProcessor

        roi = np.arange(18, dtype=np.uint8).reshape(2, 3, 3)
        mask = np.asarray([[0, 64, 255], [255, 64, 0]], dtype=np.uint8)
        mirrored_roi, mirrored_mask = VisionProcessor._prepare_lane_roi(roi, mask, True)
        np.testing.assert_array_equal(mirrored_roi, roi[:, ::-1])
        np.testing.assert_array_equal(mirrored_mask, mask[:, ::-1])

        lines = np.asarray([[[0, 1, 2, 1]], [[1, 0, 2, 0]]], dtype=np.int32)
        restored = VisionProcessor._restore_lane_roi_lines(lines, roi_width=3, mirrored=True)
        expected = np.asarray([[[2, 1, 0, 1]], [[1, 0, 0, 0]]], dtype=np.int32)
        np.testing.assert_array_equal(restored, expected)

    def test_mirroring_changes_lateral_score_but_keeps_original_angle_reference(self):
        from vision.city_vision_processing import VisionProcessor

        processor = VisionProcessor()
        lines = np.asarray([[[10, 90, 20, 10]]], dtype=np.float32)
        with patch.object(processor, "_expected_lane_angle", return_value=80.0) as angle_reference, patch.object(
            processor, "_angle_target_score", return_value=1.0
        ):
            processor._best_mid_x(lines, roi_w=100, roi_h=100, side="left", angle_side="right")
        angle_reference.assert_called_once_with("right")


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
                        ROI_RESIZABLE=True,
                        LANE_ROI_MODE="trapezoid",
                        CW_TRAPEZOID_MODE=True,
                        RL_TOP_WIDTH_FACTOR=0.72,
                        LL_TOP_WIDTH_FACTOR=0.68,
                        CW_TOP_WIDTH_FACTOR=0.8,
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
                    self.assertIn('id="save-settings" disabled', page_text)
                    if backend == "carla":
                        self.assertIn('id="steering-authority"', page_text)
                        self.assertIn('id="steering-rate"', page_text)
                        self.assertIn('id="throttle-rise-rate"', page_text)
                    self.assertIn('id="camera-feed-status"', page_text)
                    self.assertIn('id="camera-diagnostic"', page_text)
                    self.assertIn("/video_feed_frame", page_text)
                    self.assertIn(mode.upper(), page_text)
                    self.assertIn("no-store", page.headers.get("Cache-Control", ""))
                    if backend == "carla":
                        self.assertIn("Open camera placement studio", page_text)
                        self.assertIn("Autonomous run control", page_text)
                        self.assertIn('id="carla-run-start"', page_text)
                        self.assertIn('id="carla-run-stop"', page_text)
                        self.assertIn('id="lane-threshold"', page_text)
                        self.assertIn('id="crosswalk-threshold"', page_text)
                        self.assertIn('id="bev-tl-x"', page_text)
                        self.assertIn('id="roi-resizable"', page_text)
                        self.assertIn('id="min-servo"', page_text)
                        self.assertIn('id="servo-direction"', page_text)
                        self.assertIn("camera-editor-modal", page_text)
                        self.assertIn('id="camera-mount-readout"', page_text)
                        self.assertIn('id="camera-stream-readout"', page_text)
                        self.assertIn("CARLA WORLD", page_text)
                        self.assertIn("cameraPreviewChain", page_text)
                        self.assertIn("FREE-FLY · WORLD ROTATION", page_text)
                        self.assertIn("MOUNT PREVIEW · VEHICLE-LOCAL", page_text)
                        self.assertIn("STREAM MOUNT · APPLIED", page_text)
                        self.assertIn("The main Stream sensor is unchanged until you click Save mount", page_text)
                        self.assertIn("Save mount recreates the Stream RGB sensor", page_text)
                        self.assertIn("lidar-expand", page_text)
                        self.assertIn("CARLA · World & Spawn Studio", page_text)
                        self.assertIn('id="sim-roi-canvas"', page_text)
                        self.assertIn('id="sim-roi-mirror-selected"', page_text)
                        self.assertIn("Lane loop ", page_text)
                        self.assertIn("Debug render ", page_text)
                        self.assertIn("Changes are saved automatically", page_text)
                        self.assertIn('id="target-speed" type="number" min="0" max="200" step="any"', page_text)
                        self.assertIn('id="throttle-limit" type="number" min="0" max="1" step="any"', page_text)
                        self.assertIn('id="rl-top" type="number" min="0" max="1" step="any"', page_text)
                        self.assertIn("background:transparent!important", page_text)
                        self.assertIn('data-sim-roi-select="RL"', page_text)
                        self.assertIn("drag inside to move it", page_text.lower())
                        self.assertIn('id="carla-map-select"', page_text)
                        self.assertIn('id="carla-vehicle-grid"', page_text)
                        self.assertIn('id="carla-spawn-map"', page_text)
                        self.assertIn('id="carla-reset-spawn"', page_text)
                    else:
                        self.assertNotIn('id="camera-editor-modal"', page_text)
                        self.assertIn("AVIS Engine · Top-down range sensors", page_text)
                        self.assertIn('id="avis-sensor-view"', page_text)
                        self.assertIn('id="avis-sensor-expand"', page_text)
                        self.assertIn("No valid reading", page_text)

                    state = client.get("/api/simulation/settings")
                    self.assertEqual(state.status_code, 200, state.get_data(as_text=True))
                    payload = state.get_json()
                    self.assertEqual(payload["backend"], backend)
                    self.assertEqual(payload["vision_profile"], profile)
                    if backend == "carla":
                        self.assertEqual(payload["roi_geometry"]["lane_roi_mode"], "trapezoid")
                        self.assertTrue(payload["roi_geometry"]["cw_trapezoid_mode"])
                        self.assertTrue(payload["roi_geometry"]["roi_resizable"])
                        self.assertEqual(payload["roi_geometry"]["rl_top_width_factor"], 0.72)
                    self.assertFalse(payload["controls_enabled"])

                    denied = client.post(
                        "/api/simulation/settings",
                        json={"SIMULATOR_TARGET_SPEED": 5.0},
                    )
                    self.assertEqual(denied.status_code, 403)
                    if backend == "carla":
                        run_denied = client.post("/api/simulation/run-mode", json={"action": "start"})
                        self.assertEqual(run_denied.status_code, 403)
                    if backend == "carla":
                        camera_denied = client.post(
                            "/api/simulation/carla-camera",
                            json={"action": "open"},
                        )
                        self.assertEqual(camera_denied.status_code, 403)
                        scene_denied = client.post(
                            "/api/simulation/carla/scene",
                            json={"action": "reset_to_spawn"},
                        )
                        self.assertEqual(scene_denied.status_code, 403)

    def test_camera_editor_state_reports_actual_stream_sensor_transform(self):
        from modes.simulation.carla_adapter import CarlaAdapter

        stream_transform = SimpleNamespace(
            location=SimpleNamespace(x=104.25, y=-32.5, z=3.8),
            rotation=SimpleNamespace(pitch=-7.0, yaw=91.0, roll=0.5),
        )
        adapter = CarlaAdapter(SimpleNamespace())
        adapter.connected = True
        adapter.vehicle = object()
        adapter.camera = SimpleNamespace(get_transform=lambda: stream_transform)
        adapter.editor_camera = object()
        adapter._editor_transform = SimpleNamespace(
            location=SimpleNamespace(x=105.0, y=-33.0, z=4.0),
            rotation=SimpleNamespace(pitch=-6.0, yaw=92.0, roll=0.0),
        )

        state = adapter.camera_editor_state()

        self.assertEqual(state["stream_camera_transform"], {
            "x": 104.25, "y": -32.5, "z": 3.8,
            "pitch": -7.0, "yaw": 91.0, "roll": 0.5,
        })
        self.assertEqual(state["world_transform"]["x"], 105.0)
        self.assertEqual(state["mount"]["SIMULATOR_CAMERA_X"], 1.45)

    def test_camera_mount_world_local_round_trip_uses_full_rotation_matrices(self):
        import math
        from modes.simulation.carla_adapter import CarlaAdapter

        class FakeLocation:
            def __init__(self, x=0.0, y=0.0, z=0.0):
                self.x, self.y, self.z = float(x), float(y), float(z)

        class FakeRotation:
            def __init__(self, pitch=0.0, yaw=0.0, roll=0.0):
                self.pitch, self.yaw, self.roll = float(pitch), float(yaw), float(roll)

        class FakeTransform:
            def __init__(self, location=None, rotation=None):
                self.location = location or FakeLocation()
                self.rotation = rotation or FakeRotation()

            def get_matrix(self):
                pitch, yaw, roll = map(
                    math.radians,
                    (self.rotation.pitch, self.rotation.yaw, self.rotation.roll),
                )
                cp, sp = math.cos(pitch), math.sin(pitch)
                cy, sy = math.cos(yaw), math.sin(yaw)
                cr, sr = math.cos(roll), math.sin(roll)
                return np.asarray([
                    [cp * cy, cy * sp * sr - sy * cr, -cy * sp * cr - sy * sr, self.location.x],
                    [cp * sy, sy * sp * sr + cy * cr, -sy * sp * cr + cy * sr, self.location.y],
                    [sp, -cp * sr, cp * cr, self.location.z],
                    [0.0, 0.0, 0.0, 1.0],
                ], dtype=np.float64)

            def get_inverse_matrix(self):
                return np.linalg.inv(self.get_matrix())

        class FakeCamera:
            def __init__(self):
                self.transform = None
                self.set_transform_calls = []

            def set_transform(self, transform):
                self.set_transform_calls.append(transform)
                self.transform = transform

            def get_transform(self):
                return self.transform

        config = SimpleNamespace(
            SIMULATOR_CAMERA_X=1.45, SIMULATOR_CAMERA_Y=0.0, SIMULATOR_CAMERA_Z=1.8,
            SIMULATOR_CAMERA_PITCH=-8.0, SIMULATOR_CAMERA_YAW=0.0,
            SIMULATOR_CAMERA_ROLL=0.0,
        )
        adapter = CarlaAdapter(config)
        adapter.carla = SimpleNamespace(
            Location=FakeLocation, Rotation=FakeRotation, Transform=FakeTransform,
        )
        vehicle_transform = FakeTransform(
            FakeLocation(10.0, -3.0, 1.0),
            FakeRotation(pitch=17.0, yaw=63.0, roll=-12.0),
        )
        adapter.vehicle = SimpleNamespace(get_transform=lambda: vehicle_transform)
        adapter.connected = True
        adapter.camera = FakeCamera()
        adapter._camera_mount_preview = adapter._mount_values_from_config()

        # The mounted world pose must equal parent_world * mount_local, not
        # the invalid component-wise sum of the two Euler-angle triplets.
        local_mount = adapter._vehicle_camera_transform()
        expected_world = vehicle_transform.get_matrix() @ local_mount.get_matrix()
        actual_world = adapter._mounted_camera_world_transform().get_matrix()
        np.testing.assert_allclose(actual_world, expected_world, atol=1e-7)

        # An arbitrary free-fly world pose must survive world->local->world
        # conversion exactly, including coupled pitch/yaw/roll rotations.
        desired_world_camera = FakeTransform(
            FakeLocation(13.0, -1.0, 4.2),
            FakeRotation(pitch=26.0, yaw=118.0, roll=31.0),
        )
        adapter.editor_camera = object()
        adapter._editor_transform = desired_world_camera
        adapter.use_camera_editor_view_as_mount()
        reconstructed = adapter._mounted_camera_world_transform()
        np.testing.assert_allclose(
            reconstructed.get_matrix(), desired_world_camera.get_matrix(), atol=1e-6,
        )
        # The live Stream sensor is attached to the vehicle and is deliberately
        # not moved with a world-space Actor.set_transform call during preview.
        self.assertEqual(adapter.camera.set_transform_calls, [])
        self.assertIsNone(adapter.camera.get_transform())

    def test_apply_camera_mount_respawns_rgb_sensor_with_vehicle_relative_transform(self):
        from modes.simulation.carla_adapter import CarlaAdapter

        class FakeLocation:
            def __init__(self, x=0.0, y=0.0, z=0.0):
                self.x, self.y, self.z = float(x), float(y), float(z)

        class FakeRotation:
            def __init__(self, pitch=0.0, yaw=0.0, roll=0.0):
                self.pitch, self.yaw, self.roll = float(pitch), float(yaw), float(roll)

        class FakeTransform:
            def __init__(self, location=None, rotation=None):
                self.location = location or FakeLocation()
                self.rotation = rotation or FakeRotation()

        class FakeBlueprint:
            def __init__(self):
                self.attributes = {}
            def set_attribute(self, key, value):
                self.attributes[key] = value

        class FakeLibrary:
            def __init__(self):
                self.blueprint = FakeBlueprint()
            def find(self, blueprint_id):
                if blueprint_id != "sensor.camera.rgb":
                    raise AssertionError(blueprint_id)
                return self.blueprint

        class FakeSensor:
            def __init__(self, transform, parent):
                self.transform = transform
                self.parent = parent
                self.callback = None
                self.stopped = False
                self.destroyed = False
                self.set_transform_calls = []
            def listen(self, callback):
                self.callback = callback
            def stop(self):
                self.stopped = True
            def destroy(self):
                self.destroyed = True
            def set_transform(self, transform):
                self.set_transform_calls.append(transform)

        class FakeWorld:
            def __init__(self):
                self.library = FakeLibrary()
                self.spawned = []
            def get_blueprint_library(self):
                return self.library
            def spawn_actor(self, blueprint, transform, attach_to=None):
                sensor = FakeSensor(transform, attach_to)
                self.spawned.append(sensor)
                return sensor

        config = SimpleNamespace(
            SIMULATOR_CAMERA_X=1.45, SIMULATOR_CAMERA_Y=0.0, SIMULATOR_CAMERA_Z=1.8,
            SIMULATOR_CAMERA_PITCH=-8.0, SIMULATOR_CAMERA_YAW=0.0,
            SIMULATOR_CAMERA_ROLL=0.0, CAM_WIDTH=640, CAM_HEIGHT=480,
            SIMULATOR_CAMERA_FOV=90.0,
        )
        adapter = CarlaAdapter(config)
        adapter.carla = SimpleNamespace(
            Location=FakeLocation, Rotation=FakeRotation, Transform=FakeTransform,
        )
        adapter.world = FakeWorld()
        adapter.vehicle = object()
        adapter.connected = True
        original = FakeSensor(FakeTransform(), adapter.vehicle)
        adapter.camera = original
        adapter._camera_mount_preview = adapter._mount_values_from_config()
        adapter._camera_mount_applied = adapter._mount_values_from_config()

        selected_mount = {
            "SIMULATOR_CAMERA_X": 2.4,
            "SIMULATOR_CAMERA_Y": -0.35,
            "SIMULATOR_CAMERA_Z": 2.15,
            "SIMULATOR_CAMERA_PITCH": -14.5,
            "SIMULATOR_CAMERA_YAW": 27.0,
            "SIMULATOR_CAMERA_ROLL": 8.0,
        }
        adapter.apply_camera_mount(selected_mount)

        self.assertEqual(len(adapter.world.spawned), 1)
        replacement = adapter.world.spawned[0]
        self.assertIsNot(replacement, original)
        self.assertIs(replacement.parent, adapter.vehicle)
        self.assertEqual(replacement.transform.location.x, 2.4)
        self.assertEqual(replacement.transform.location.y, -0.35)
        self.assertEqual(replacement.transform.location.z, 2.15)
        self.assertEqual(replacement.transform.rotation.pitch, -14.5)
        self.assertEqual(replacement.transform.rotation.yaw, 27.0)
        self.assertEqual(replacement.transform.rotation.roll, 8.0)
        self.assertIsNotNone(replacement.callback)
        self.assertTrue(original.stopped)
        self.assertTrue(original.destroyed)
        self.assertEqual(original.set_transform_calls, [])
        self.assertIs(adapter.camera, replacement)
        self.assertEqual(adapter._camera_mount_applied, selected_mount)

    def test_carla_settings_api_accepts_user_tuning_and_mirror_flags(self):
        import os
        import stream
        from stream import WebStreamer

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(stream, "BASE_DIR", directory), patch.dict(
                os.environ, {"STREAM_USERNAME": "", "STREAM_PASSWORD": ""}
            ):
                config = SimpleNamespace(
                    BASE_DIR=directory, MODE="carla", SIMULATOR_BACKEND="carla",
                    SIMULATION_VISION_PROFILE="city", STREAM=True,
                    STREAM_HOST="127.0.0.1", STREAM_PORT=41991,
                    STREAM_ALLOW_CONTROL=True, RECORD_VIDEO=False,
                    USE_BEV=False, USE_ML_LANE_DETECTOR=False,
                    CITY_LANE_DETECTOR="default", ROI_RESIZABLE=False,
                    LANE_ROI_MODE="rectangle", CW_TRAPEZOID_MODE=False,
                    RL_TOP_WIDTH_FACTOR=0.85, LL_TOP_WIDTH_FACTOR=0.85,
                    CW_TOP_WIDTH_FACTOR=0.9, WITHOUT_ARDUINO=True,
                    READ_ARDUINO_OUTPUT=False, SEND_AUTOMATIC_ARDUINO_COMMANDS=False,
                    MIN_SERVO_ANGLE=50, SERVO_CENTER=95, MAX_SERVO_ANGLE=130,
                    debug_frames_list=[None, None], stream_frame_seq=1,
                    OUTPUT_DIR=directory,
                )
                client = WebStreamer(config).app.test_client()
                response = client.post("/api/simulation/settings", json={"settings": {
                    "SIMULATOR_TARGET_SPEED": 12.5,
                    "SIMULATOR_THROTTLE_LIMIT": 0.42,
                    "SIMULATOR_STEERING_LIMIT": 0.75,
                    "SIMULATOR_STEERING_RATE": 3.5,
                    "SIMULATOR_THROTTLE_RISE_RATE": 0.65,
                    "RL_TOP_ROI": 0.1, "RL_BOTTOM_ROI": 0.9,
                    "RL_LEFT_ROI": 0.6, "RL_RIGHT_ROI": 0.9,
                    "RL_MIRRORED": True, "LL_MIRRORED": True,
                }})
                self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
                saved = response.get_json()["settings"]
                self.assertEqual(saved["SIMULATOR_TARGET_SPEED"], 12.5)
                self.assertEqual(saved["SIMULATOR_THROTTLE_LIMIT"], 0.42)
                self.assertEqual(saved["RL_TOP_ROI"], 0.1)
                self.assertTrue(saved["RL_MIRRORED"])
                self.assertTrue(saved["LL_MIRRORED"])


class SimulatorFramePipelineTests(unittest.TestCase):
    def test_carla_camera_callback_never_overwrites_lane_debug_stream_frame(self):
        from modes.simulation.carla_adapter import CarlaAdapter

        annotated_frame = np.full((3, 4, 3), 90, dtype=np.uint8)
        config = SimpleNamespace(
            STREAM=True,
            debug_frames_list=[None, annotated_frame],
            stream_frame_seq=41,
        )
        adapter = CarlaAdapter(config)
        bgra = np.zeros((3, 4, 4), dtype=np.uint8)
        bgra[:, :, 2] = 180
        bgra[:, :, 3] = 255
        camera_image = SimpleNamespace(
            raw_data=bgra.tobytes(), width=4, height=3, frame=101, timestamp=12.0
        )

        adapter._on_camera(camera_image)

        self.assertIs(config.debug_frames_list[-1], annotated_frame)
        self.assertEqual(config.stream_frame_seq, 41)
        self.assertEqual(adapter.camera_diagnostics()["callback_count"], 1)
        self.assertEqual(adapter.camera_diagnostics()["callback_fps"], 0.0)
        self.assertEqual(adapter._image.shape, (3, 4, 3))

    def test_video_feed_frame_returns_no_content_when_sequence_is_unchanged(self):
        import os
        import stream
        from stream import WebStreamer

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(stream, "BASE_DIR", directory), patch.dict(
                os.environ, {"STREAM_USERNAME": "", "STREAM_PASSWORD": ""}
            ):
                class CopySpy:
                    copied = False
                    def copy(self):
                        self.copied = True
                        return np.full((12, 16, 3), 80, dtype=np.uint8)

                frame = CopySpy()
                config = SimpleNamespace(
                    BASE_DIR=directory, MODE="carla", SIMULATOR_BACKEND="carla",
                    SIMULATION_VISION_PROFILE="city", STREAM=True,
                    STREAM_HOST="127.0.0.1", STREAM_PORT=41992,
                    STREAM_ALLOW_CONTROL=False, RECORD_VIDEO=False,
                    debug_frames_list=[None, frame],
                    stream_frame_seq=77, OUTPUT_DIR=directory,
                )
                client = WebStreamer(config).app.test_client()
                unchanged = client.get("/video_feed_frame?since=77")
                self.assertEqual(unchanged.status_code, 204)
                self.assertEqual(unchanged.headers.get("X-Stream-Frame-Sequence"), "77")
                self.assertFalse(frame.copied, "unchanged frame polling should not copy or JPEG-encode")

                newer = client.get("/video_feed_frame?since=76")
                self.assertEqual(newer.status_code, 200)
                self.assertEqual(newer.headers.get("X-Stream-Frame-Sequence"), "77")
                self.assertTrue(frame.copied)
                self.assertTrue(newer.data.startswith(bytes((255, 216))))

    def test_simulator_debug_renderer_coalesces_to_latest_pending_frame(self):
        import threading
        from modes.simulation.runtime import SimulationRuntime

        config = SimpleNamespace(
            MODE="carla", SIMULATOR_BACKEND="carla", SIMULATION_VISION_PROFILE="city",
            CITY_LANE_DETECTOR="default", MIN_SERVO_ANGLE=50, SERVO_CENTER=95,
            MAX_SERVO_ANGLE=130, SIMULATOR_TARGET_SPEED=5.0,
            SIMULATOR_THROTTLE_LIMIT=0.12, SIMULATOR_STEERING_LIMIT=0.28,
            SIMULATOR_STEERING_RATE=0.8, SIMULATOR_THROTTLE_RISE_RATE=0.12,
            SIMULATOR_STOP_ON_LOST_LANE=True, SIMULATOR_STEERING_INVERTED=False,
            STREAM=False, debug_frames_list=[None, None],
        )
        runtime = SimulationRuntime(config)
        first_render_started = threading.Event()
        release_first_render = threading.Event()
        latest_render_finished = threading.Event()
        rendered_sequences = []

        def fake_render(sensor_frame, perception, command):
            rendered_sequences.append(sensor_frame.sequence)
            if sensor_frame.sequence == 1:
                first_render_started.set()
                release_first_render.wait(2.0)
            elif sensor_frame.sequence == 3:
                latest_render_finished.set()

        runtime._publish_frame = fake_render
        runtime._start_visualization_worker()
        try:
            runtime._queue_frame_for_stream(SimpleNamespace(sequence=1), {}, None)
            self.assertTrue(first_render_started.wait(1.0))
            runtime._queue_frame_for_stream(SimpleNamespace(sequence=2), {}, None)
            runtime._queue_frame_for_stream(SimpleNamespace(sequence=3), {}, None)
            release_first_render.set()
            self.assertTrue(latest_render_finished.wait(1.0))
        finally:
            release_first_render.set()
            runtime._stop_visualization_worker()

        self.assertEqual(rendered_sequences, [1, 3])


class VirtualControllerTests(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace(
            MIN_SERVO_ANGLE=50, SERVO_CENTER=95, MAX_SERVO_ANGLE=130,
            SIMULATOR_TARGET_SPEED=5.0, SIMULATOR_THROTTLE_LIMIT=0.12,
            SIMULATOR_STEERING_LIMIT=0.28, SIMULATOR_STEERING_RATE=0.80,
            SIMULATOR_THROTTLE_RISE_RATE=0.12,
            SIMULATOR_STOP_ON_LOST_LANE=True, SIMULATOR_STEERING_INVERTED=False,
        )

    def test_simulator_stream_renders_shared_vision_roi_debug_frame(self):
        import time
        from modes.simulation.base_adapter import SensorFrame, VehicleCommand
        from modes.simulation.runtime import SimulationRuntime

        config = SimpleNamespace(
            MODE="carla", SIMULATOR_BACKEND="carla", SIMULATION_VISION_PROFILE="city",
            CITY_LANE_DETECTOR="default", MIN_SERVO_ANGLE=50, SERVO_CENTER=95, MAX_SERVO_ANGLE=130,
            SIMULATOR_TARGET_SPEED=20.0, SIMULATOR_THROTTLE_LIMIT=0.3,
            SIMULATOR_STOP_ON_LOST_LANE=True, SIMULATOR_STEERING_INVERTED=False,
            USE_BEV=True, ENCODER_MAP_ENABLED=False, STREAM=True, debug_frames_list=[None, None],
            stream_frame_seq=0,
        )
        runtime = SimulationRuntime(config)
        raw_frame = np.zeros((8, 12, 3), dtype=np.uint8)
        vision_frame = np.full((8, 12, 3), 20, dtype=np.uint8)
        rendered_frame = np.full((8, 12, 3), 90, dtype=np.uint8)
        sensor = SensorFrame(image=raw_frame, captured_at=time.monotonic(), sequence=1)
        debug = {"combined": vision_frame, "draw_data": {"kind": "classical", "frame_width": 12, "frame_height": 8}}
        command = VehicleCommand(0.0, 0.1, 0.0, 95.0, 20.0, "test")
        with patch("modes.simulation.runtime.render_lane_debug_overlay", side_effect=lambda *args: rendered_frame.copy()) as render:
            runtime._publish_frame(sensor, {"debug": debug, "lane_type": "both", "perception_valid": True}, command)
        render.assert_called_once()
        np.testing.assert_array_equal(render.call_args.args[0], vision_frame)
        self.assertEqual(config.debug_frames_list[-1].shape, raw_frame.shape)
        np.testing.assert_array_equal(config.debug_frames_list[-1], rendered_frame)

    def test_carla_run_mode_is_disarmed_until_explicit_start(self):
        from modes.simulation.runtime import SimulationRuntime

        class FakeAdapter:
            connected = True
            def __init__(self): self.commands = []
            def control_ready(self): return True
            def apply_control(self, command): self.commands.append(command); return True

        config = SimpleNamespace(
            MODE="carla", SIMULATOR_BACKEND="carla", SIMULATION_VISION_PROFILE="city",
            CITY_LANE_DETECTOR="default", MIN_SERVO_ANGLE=50, SERVO_CENTER=95, MAX_SERVO_ANGLE=130,
            SIMULATOR_TARGET_SPEED=5.0, SIMULATOR_THROTTLE_LIMIT=0.12,
            SIMULATOR_STEERING_LIMIT=0.28, SIMULATOR_STEERING_RATE=0.80,
            SIMULATOR_THROTTLE_RISE_RATE=0.12,
            SIMULATOR_STOP_ON_LOST_LANE=True, SIMULATOR_STEERING_INVERTED=False,
            ENCODER_MAP_ENABLED=False, STREAM=False, debug_frames_list=[None, None],
        )
        adapter = FakeAdapter()
        with patch("modes.simulation.runtime.create_adapter", return_value=adapter):
            runtime = SimulationRuntime(config)
        self.assertFalse(runtime.snapshot()["run_enabled"])
        self.assertEqual(runtime.snapshot()["run_mode"], "stopped")
        self.assertTrue(runtime.set_run_enabled(True))
        self.assertTrue(runtime.snapshot()["run_enabled"])
        self.assertFalse(runtime.set_run_enabled(False))
        self.assertEqual(adapter.commands[-1].brake, 1.0)
        self.assertEqual(adapter.commands[-1].throttle, 0.0)

    def test_carla_bev_blank_frame_falls_back_to_raw_camera(self):
        import time
        from modes.simulation.base_adapter import SensorFrame, VehicleCommand
        from modes.simulation.runtime import SimulationRuntime

        config = SimpleNamespace(
            MODE="carla", SIMULATOR_BACKEND="carla", SIMULATION_VISION_PROFILE="city",
            CITY_LANE_DETECTOR="default", MIN_SERVO_ANGLE=50, SERVO_CENTER=95, MAX_SERVO_ANGLE=130,
            SIMULATOR_TARGET_SPEED=5.0, SIMULATOR_THROTTLE_LIMIT=0.12,
            SIMULATOR_STEERING_LIMIT=0.28, SIMULATOR_STEERING_RATE=0.80,
            SIMULATOR_THROTTLE_RISE_RATE=0.12,
            SIMULATOR_STOP_ON_LOST_LANE=True, SIMULATOR_STEERING_INVERTED=False,
            USE_BEV=True, ENCODER_MAP_ENABLED=False, STREAM=True, debug_frames_list=[None, None],
            stream_frame_seq=0,
        )
        runtime = SimulationRuntime(config)
        raw = np.full((8, 12, 3), 80, dtype=np.uint8)
        blank_bev = np.zeros((8, 12, 3), dtype=np.uint8)
        sensor = SensorFrame(image=raw, captured_at=time.monotonic(), sequence=1)
        command = VehicleCommand(0.0, 0.0, 1.0, 95.0, 0.0, "stopped")
        runtime._publish_frame(sensor, {"debug": {"combined": blank_bev}}, command)
        self.assertEqual(runtime._last_image_diagnostics["source"], "camera")
        self.assertFalse(runtime._last_image_diagnostics["looks_black"])
        self.assertGreater(int(config.debug_frames_list[-1].mean()), 70)

    def test_invalid_perception_brakes_and_retains_steering(self):
        controller = VirtualVehicleController(self.config, "carla")
        before = controller.last_servo
        command = controller.command_for({"perception_valid": False}, speed_kmh=0.0)
        self.assertEqual(command.brake, 1.0)
        self.assertEqual(command.throttle, 0.0)
        self.assertEqual(command.servo_angle, before)

    def test_carla_steering_and_throttle_are_slew_limited(self):
        with patch("modes.simulation.controller.time.monotonic", side_effect=[10.0, 10.1, 10.2]):
            controller = VirtualVehicleController(self.config, "carla")
            first = controller.command_for({"perception_valid": True, "steering_angle": 180}, speed_kmh=0.0)
            second = controller.command_for({"perception_valid": True, "steering_angle": 180}, speed_kmh=0.0)
        self.assertEqual(first.servo_angle, 130)
        self.assertAlmostEqual(first.steering, 0.08, places=3)
        self.assertAlmostEqual(second.steering, 0.16, places=3)
        self.assertAlmostEqual(first.throttle, 0.012, places=3)
        self.assertAlmostEqual(second.throttle, 0.024, places=3)
        self.assertLessEqual(abs(second.steering), 0.28)

    def test_avis_steering_is_slew_limited_against_alternating_vision_noise(self):
        self.config.SIMULATOR_STEERING_LIMIT = 1.0
        self.config.SIMULATOR_STEERING_RATE = 2.0
        with patch("modes.simulation.controller.time.monotonic", side_effect=[10.0, 10.1, 10.2, 10.3]):
            controller = VirtualVehicleController(self.config, "avis")
            right = controller.command_for({"perception_valid": True, "steering_angle": 130})
            left = controller.command_for({"perception_valid": True, "steering_angle": 50})
            right_again = controller.command_for({"perception_valid": True, "steering_angle": 130})

        # A raw vision estimate flips between +/-1.0, but the actuator command
        # moves by at most 0.2 per 100 ms tick instead of snapping across lanes.
        self.assertAlmostEqual(right.steering, 0.2, places=3)
        self.assertAlmostEqual(left.steering, 0.0, places=3)
        self.assertAlmostEqual(right_again.steering, 0.2, places=3)

    def test_settings_panel_is_bounded_and_scrollable(self):
        template = (
            Path(__file__).resolve().parents[1]
            / "stream" / "templates" / "simulator_editor.html"
        ).read_text(encoding="utf-8")
        scroll_styles = template[
            template.index(".sim-settings-panel{"):
            template.index("camera-stale-overlay")
        ]
        self.assertIn("height:min(82vh,820px)", scroll_styles)
        self.assertIn("overflow-y:auto", scroll_styles)
        self.assertNotIn("overflow-y:visible", scroll_styles)
        self.assertNotIn("overflow:visible", scroll_styles)

    def test_carla_honors_user_configured_values_above_old_ui_caps(self):
        self.config.SIMULATOR_TARGET_SPEED = 20.0
        self.config.SIMULATOR_THROTTLE_LIMIT = 0.60
        self.config.SIMULATOR_STEERING_LIMIT = 0.80
        self.config.SIMULATOR_STEERING_RATE = 5.0
        self.config.SIMULATOR_THROTTLE_RISE_RATE = 0.60
        with patch("modes.simulation.controller.time.monotonic", side_effect=[30.0, 30.25]):
            controller = VirtualVehicleController(self.config, "carla")
            command = controller.command_for({"perception_valid": True, "steering_angle": 130}, speed_kmh=0.0)
        self.assertEqual(command.target_speed, 20.0)
        self.assertAlmostEqual(command.steering, 0.80, places=3)
        self.assertAlmostEqual(command.throttle, 0.15, places=3)

    def test_carla_brakes_when_above_low_target_speed(self):
        with patch("modes.simulation.controller.time.monotonic", side_effect=[20.0, 20.1]):
            controller = VirtualVehicleController(self.config, "carla")
            command = controller.command_for({"perception_valid": True, "steering_angle": 95}, speed_kmh=7.0)
        self.assertEqual(command.throttle, 0.0)
        self.assertGreater(command.brake, 0.0)
        self.assertLessEqual(command.target_speed, 8.0)

    def test_carla_adapter_applies_final_actuator_safety_caps(self):
        from modes.simulation.carla_adapter import CarlaAdapter

        class FakeVehicle:
            def apply_control(self, control): self.control = control
        class FakeCarla:
            @staticmethod
            def VehicleControl(**kwargs): return SimpleNamespace(**kwargs)

        adapter = CarlaAdapter(SimpleNamespace(
            SIMULATOR_THROTTLE_LIMIT=0.42, SIMULATOR_STEERING_LIMIT=0.75
        ))
        adapter.vehicle = FakeVehicle()
        adapter.carla = FakeCarla()
        command = VehicleCommand(1.0, 1.0, 0.0, 130.0, 50.0, "oversized request")
        self.assertTrue(adapter.apply_control(command))
        self.assertEqual(adapter.vehicle.control.steer, 0.75)
        self.assertEqual(adapter.vehicle.control.throttle, 0.42)

    def test_valid_perception_is_clamped_and_throttle_limited(self):
        controller = VirtualVehicleController(self.config, "carla")
        command = controller.command_for({"perception_valid": True, "steering_angle": 180}, speed_kmh=0.0)
        self.assertEqual(command.servo_angle, 130)
        self.assertLessEqual(abs(command.steering), 0.28)
        self.assertLessEqual(command.throttle, 0.12)
        self.assertGreaterEqual(command.throttle, 0.0)

    def test_avis_adapter_waits_for_legacy_engine_startup_before_commands(self):
        class FakeCar:
            def __init__(self):
                self.angle = None
            def connect(self, host, port):
                return True
            def setSensorAngle(self, angle):
                self.angle = angle
            def stop(self):
                pass

        fake = FakeCar()
        module = types.SimpleNamespace(Car=lambda: fake)
        config = SimpleNamespace(
            SIMULATOR_HOST="127.0.0.1", SIMULATOR_PORT=25001,
            SIMULATOR_TIMEOUT_S=5.0, SIMULATOR_AVIS_SENSOR_ANGLE=30,
            SIMULATOR_AVIS_STARTUP_DELAY_S=3.0,
        )
        with patch.dict(sys.modules, {"avisengine": module}), patch(
            "modes.simulation.avis_adapter.time.monotonic", return_value=100.0
        ):
            adapter = AvisAdapter(config)
            adapter.connect()
            self.assertIsNone(fake.angle)
            self.assertEqual(adapter._ready_at, 103.0)
            adapter.close()

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
                                 SIMULATOR_TIMEOUT_S=5.0, SIMULATOR_AVIS_SENSOR_ANGLE=15,
            SIMULATOR_AVIS_STARTUP_DELAY_S=0.0)
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

    def test_avis_adapter_does_not_write_actuators_before_reconnect_startup_delay(self):
        class FakeCar:
            def __init__(self):
                self.commands = []
            def setSteering(self, value):
                self.commands.append(("steering", value))
            def setSpeed(self, value):
                self.commands.append(("speed", value))

        car = FakeCar()
        adapter = AvisAdapter(SimpleNamespace())
        adapter.car = car
        adapter.connected = True
        adapter._ready_at = 103.0
        with patch("modes.simulation.avis_adapter.time.monotonic", return_value=102.0):
            command = VehicleCommand(0.0, 0.0, 1.0, 95.0, 0.0, "startup safety stop")
            self.assertFalse(adapter.apply_control(command))
        self.assertEqual(car.commands, [])

    def test_avis_adapter_maps_signed_steering_to_legacy_percent_range(self):
        from modes.simulation.base_adapter import VehicleCommand

        class FakeCar:
            def __init__(self):
                self.steering = []
                self.speeds = []
            def setSteering(self, value):
                self.steering.append(value)
            def setSpeed(self, value):
                self.speeds.append(value)

        car = FakeCar()
        adapter = AvisAdapter(SimpleNamespace())
        adapter.car = car
        adapter.connected = True

        for normalized, expected in ((-1.0, -100), (0.0, 0), (1.0, 100),
                                     (-1.5, -100), (1.5, 100)):
            command = VehicleCommand(
                steering=normalized, throttle=0.0, brake=0.0,
                servo_angle=95.0, target_speed=0.0, reason="steering test",
            )
            self.assertTrue(adapter.apply_control(command))
            self.assertEqual(car.steering[-1], expected)

    def test_avis_adapter_returns_none_when_server_has_no_camera_frame(self):
        class EmptyCar:
            def getImage(self):
                return None
            def getData(self):
                return None
        adapter = AvisAdapter(SimpleNamespace())
        adapter.car = EmptyCar()
        adapter.connected = True
        adapter._sensor_angle_applied = True
        self.assertIsNone(adapter.read())

    def test_avis_missing_frame_status_is_info_once_per_outage(self):
        class FakeCar:
            def __init__(self):
                self.image_sequence = 0
                self.last_response_info = {}
                self.index = 0
            def setSensorAngle(self, angle):
                return None
            def getData(self):
                self.index += 1
                error = (
                    "Base64 image payload could not be decoded: invalid Base64 length"
                    if self.index % 2 else
                    "Unsupported AVIS image payload signature (decoded prefix 00112233)"
                )
                self.last_response_info = {
                    "response_bytes": 24000 + self.index,
                    "image_tag": False, "sensor_tag": True, "speed_tag": True,
                    "image_decoded": False, "image_payload_format": "leading-base64",
                    "image_payload_magic": "unknown", "image_payload_prefix_hex": "00112233",
                    "response_prefix_kind": "base64-like", "decode_error": error,
                }
            def getImage(self):
                return None

        fake = FakeCar()
        adapter = AvisAdapter(SimpleNamespace(SIMULATOR_AVIS_SENSOR_ANGLE=30))
        adapter.car = fake
        adapter.connected = True
        adapter._ready_at = 0.0
        adapter._sensor_angle_applied = True
        with patch("modes.simulation.avis_adapter.logger.warning") as warning, patch(
            "modes.simulation.avis_adapter.logger.info"
        ) as info:
            for _ in range(12):
                self.assertIsNone(adapter.read())
        self.assertEqual(warning.call_count, 0)
        self.assertEqual(info.call_count, 1)
        diagnostics = adapter.camera_diagnostics()["response"]
        self.assertEqual(diagnostics["image_payload_prefix_hex"], "00112233")
        self.assertEqual(adapter.camera_diagnostics()["missing_images"], 12)

    def test_avis_persistent_bad_frames_raise_one_error_without_warning_spam(self):
        class FakeCar:
            image_sequence = 0
            last_response_info = {
                "response_bytes": 24000,
                "decode_error": "Unsupported AVIS image payload signature",
                "image_payload_magic": "unknown",
                "image_payload_prefix_hex": "00112233",
            }
            def getData(self):
                return False
            def getImage(self):
                return None

        adapter = AvisAdapter(SimpleNamespace(SIMULATOR_AVIS_SENSOR_ANGLE=30))
        adapter.car = FakeCar()
        adapter.connected = True
        adapter._ready_at = 0.0
        adapter._sensor_angle_applied = True
        adapter._missing_images = 29
        adapter._missing_image_log_active = True
        adapter._missing_image_started_at = 0.0
        with patch("modes.simulation.avis_adapter.time.monotonic", return_value=10.0), patch(
            "modes.simulation.avis_adapter.logger.warning"
        ) as warning, patch("modes.simulation.avis_adapter.logger.error") as error:
            self.assertIsNone(adapter.read())
            self.assertIsNone(adapter.read())
        self.assertEqual(warning.call_count, 0)
        self.assertEqual(error.call_count, 1)
        self.assertEqual(adapter.camera_diagnostics()["missing_images"], 31)

    def test_avis_adapter_keeps_tcp_connection_when_response_has_no_image_tag(self):
        class ConnectedWithoutImages:
            def __init__(self):
                self.image_sequence = 0
                self.image = np.zeros((8, 10, 3), dtype=np.uint8)
                self.last_response_info = {
                    "response_bytes": 42, "image_tag": False,
                    "sensor_tag": True, "image_decoded": False,
                    "response_prefix": "<sensor>10,20,30</sensor><EOF>",
                }
            def getData(self):
                # Simulates a valid TCP reply carrying sensor data but no image.
                return False
            def getImage(self):
                return self.image
            def getSensors(self):
                return [10, 20, 30]
            def getSpeed(self):
                return 0

        car = ConnectedWithoutImages()
        adapter = AvisAdapter(SimpleNamespace())
        adapter.car = car
        adapter.connected = True
        adapter._sensor_angle_applied = True
        for _ in range(6):
            self.assertIsNone(adapter.read())
        self.assertTrue(adapter.connected)
        self.assertIs(adapter.car, car)
        self.assertEqual(adapter.camera_diagnostics()["missing_images"], 6)
        self.assertEqual(adapter.camera_diagnostics()["response"]["image_tag"], False)

    def test_carla_camera_callback_keeps_raw_frames_out_of_lane_debug_stream(self):
        import threading
        from modes.simulation.carla_adapter import CarlaAdapter

        pixels = np.zeros((6, 8, 4), dtype=np.uint8)
        pixels[:, :, 0] = 25
        pixels[:, :, 1] = 90
        pixels[:, :, 2] = 180
        pixels[:, :, 3] = 255
        previous_debug_frame = np.full((6, 8, 3), 70, dtype=np.uint8)
        config = SimpleNamespace(
            STREAM=True, debug_frames_list=[None, previous_debug_frame], stream_frame_seq=0,
            stream_frame_lock=threading.RLock(),
        )
        adapter = CarlaAdapter(config)
        adapter._world_synchronous_mode = True
        image = SimpleNamespace(
            raw_data=pixels.tobytes(), width=8, height=6, frame=17, timestamp=1.25,
        )

        adapter._on_camera(image)

        self.assertEqual(config.stream_frame_seq, 0)
        self.assertIs(config.debug_frames_list[-1], previous_debug_frame)
        np.testing.assert_array_equal(adapter._image, pixels[:, :, :3])
        diagnostics = adapter.camera_diagnostics()
        self.assertEqual(diagnostics["callback_count"], 1)
        self.assertEqual(diagnostics["frame_number"], 17)
        self.assertTrue(diagnostics["synchronous_mode"])
        self.assertFalse(diagnostics["looks_black"])

    def test_carla_adapter_marks_old_lidar_packets_stale(self):
        from modes.simulation.carla_adapter import CarlaAdapter

        class FakeVehicle:
            def get_transform(self):
                return SimpleNamespace(
                    location=SimpleNamespace(x=0.0, y=0.0, z=0.0),
                    rotation=SimpleNamespace(yaw=0.0),
                )
            def get_velocity(self):
                return SimpleNamespace(x=0.0, y=0.0, z=0.0)

        config = SimpleNamespace(
            SIMULATOR_LIDAR_ENABLED=True,
            SIMULATOR_LIDAR_ROTATION_FREQUENCY=10.0,
        )
        adapter = CarlaAdapter(config)
        adapter.connected = True
        adapter.vehicle = FakeVehicle()
        adapter._image = np.zeros((8, 12, 3), dtype=np.uint8)
        adapter._image_at = __import__("time").monotonic()
        adapter._sequence = 1
        adapter._points = np.asarray([[1.0, 0.0, 0.0]], dtype=np.float32)
        adapter._points_at = __import__("time").monotonic() - 5.0

        stale = adapter.read(timeout=0)
        self.assertIsNotNone(stale)
        self.assertFalse(stale.sensor_status["lidar_fresh"])
        self.assertIsNone(stale.lidar_points)
        self.assertNotIn("front", stale.ranges_cm)

        adapter._image_at = __import__("time").monotonic()
        adapter._points_at = __import__("time").monotonic()
        adapter._sequence = 2
        fresh = adapter.read(timeout=0)
        self.assertTrue(fresh.sensor_status["lidar_fresh"])
        self.assertEqual(fresh.sensor_status["lidar_reason"], "ok")
        self.assertIsNotNone(fresh.lidar_points)
        self.assertAlmostEqual(fresh.ranges_cm["front"], 100.0, places=3)

        # A recent but empty packet is not evidence that the path ahead is clear.
        adapter._image_at = __import__("time").monotonic()
        adapter._points_at = __import__("time").monotonic()
        adapter._points = np.empty((0, 3), dtype=np.float32)
        adapter._sequence = 3
        empty = adapter.read(timeout=0)
        self.assertFalse(empty.sensor_status["lidar_fresh"])
        self.assertEqual(empty.sensor_status["lidar_reason"], "empty or invalid point cloud")
        self.assertIsNone(empty.lidar_points)

    def test_avis_runtime_retries_startup_without_warning_tracebacks(self):
        import threading
        from modes.simulation.runtime import SimulationRuntime

        shutdown = threading.Event()

        class RetryingAdapter:
            connected = False
            def __init__(self):
                self.connect_calls = 0
                self.commands = []
            def connect(self):
                self.connect_calls += 1
                if self.connect_calls < 3:
                    raise ConnectionError("AVIS Engine is not listening yet")
                self.connected = True
                return True
            def read(self, timeout=0.25):
                shutdown.set()
                return None
            def apply_control(self, command):
                self.commands.append(command)
                return True
            def close(self):
                self.connected = False

        adapter = RetryingAdapter()
        config = SimpleNamespace(
            MODE="avis", SIMULATOR_BACKEND="avis", SIMULATION_VISION_PROFILE="city",
            CITY_LANE_DETECTOR="default", MIN_SERVO_ANGLE=55, SERVO_CENTER=95, MAX_SERVO_ANGLE=125,
            SIMULATOR_TARGET_SPEED=25.0, SIMULATOR_THROTTLE_LIMIT=0.35,
            SIMULATOR_STEERING_LIMIT=1.0, SIMULATOR_STEERING_RATE=2.0,
            SIMULATOR_STOP_ON_LOST_LANE=True, SIMULATOR_STEERING_INVERTED=False,
            ENCODER_MAP_ENABLED=False, STREAM=False, debug_frames_list=[None, None],
            SHUTDOWN_EVENT=shutdown,
        )
        with patch("modes.simulation.runtime.create_adapter", return_value=adapter):
            runtime = SimulationRuntime(config)
        with patch.object(shutdown, "wait", side_effect=lambda _seconds: False), patch(
            "modes.simulation.runtime.logger.warning"
        ) as warning:
            runtime.run()
        self.assertEqual(adapter.connect_calls, 3)
        self.assertEqual(warning.call_count, 0)
        self.assertTrue(adapter.commands)
        self.assertTrue(all(command.throttle == 0.0 for command in adapter.commands))

    def test_carla_runtime_brakes_when_enabled_lidar_is_stale(self):
        import threading
        from modes.simulation.base_adapter import SensorFrame
        from modes.simulation.runtime import SimulationRuntime
        from vision.city_vision_processing import VisionProcessor

        shutdown = threading.Event()
        frame = SensorFrame(
            image=np.zeros((8, 12, 3), dtype=np.uint8),
            captured_at=__import__("time").monotonic(),
            sequence=1,
            ranges_cm={},
            lidar_points=None,
            sensor_status={"lidar_enabled": True, "lidar_fresh": False, "lidar_age_s": 3.0},
        )

        class FakeAdapter:
            connected = True
            def __init__(self):
                self.commands = []
            def connect(self):
                return None
            def read(self, timeout=0.25):
                shutdown.set()
                return frame
            def apply_control(self, command):
                self.commands.append(command)
                return True
            def close(self):
                self.connected = False

        class FakeVision:
            def detect(self, image):
                return {"perception_valid": True, "lane_type": "both", "steering_angle": 95.0}

        config = SimpleNamespace(
            MODE="carla", SIMULATOR_BACKEND="carla", SIMULATION_VISION_PROFILE="city",
            CITY_LANE_DETECTOR="default", MIN_SERVO_ANGLE=50, SERVO_CENTER=95, MAX_SERVO_ANGLE=130,
            SIMULATOR_TARGET_SPEED=20.0, SIMULATOR_THROTTLE_LIMIT=0.3,
            SIMULATOR_STOP_ON_LOST_LANE=True, SIMULATOR_STEERING_INVERTED=False,
            SIMULATOR_OBSTACLE_STOP_DISTANCE_CM=35.0, SIMULATOR_LIDAR_ENABLED=True,
            SIMULATOR_STOP_ON_CROSSWALK=False, TARGET_PROCESSING_FPS=30.0,
            ENCODER_MAP_ENABLED=False, STREAM=False, debug_frames_list=[None, None],
            SHUTDOWN_EVENT=shutdown,
        )
        adapter = FakeAdapter()
        with patch("modes.simulation.runtime.create_adapter", return_value=adapter), patch(
            "vision.city_vision_processing.VisionProcessor", return_value=FakeVision()
        ):
            runtime = SimulationRuntime(config)
            runtime.run()

        self.assertTrue(adapter.commands)
        self.assertTrue(all(command.throttle == 0.0 and command.brake == 1.0 for command in adapter.commands))
        self.assertTrue(any("LiDAR is missing or stale" in command.reason for command in adapter.commands))

    def test_carla_runtime_waits_when_vehicle_actor_is_temporarily_unavailable(self):
        import threading
        import time
        from modes.simulation.base_adapter import SensorFrame
        from modes.simulation.runtime import SimulationRuntime

        shutdown = threading.Event()
        frame = SensorFrame(
            image=np.zeros((8, 12, 3), dtype=np.uint8),
            captured_at=time.monotonic(),
            sequence=1,
        )

        class FakeAdapter:
            connected = True
            def __init__(self):
                self.commands = []
                self.closed = False
            def connect(self):
                pass
            def control_ready(self):
                return False
            def read(self, timeout=0.25):
                shutdown.set()
                return frame
            def apply_control(self, command):
                self.commands.append(command)
                return False
            def close(self):
                self.closed = True
                self.connected = False

        class FakeVision:
            def detect(self, image):
                return {"perception_valid": True, "lane_type": "both", "steering_angle": 95.0}

        config = SimpleNamespace(
            MODE="carla", SIMULATOR_BACKEND="carla", SIMULATION_VISION_PROFILE="city",
            CITY_LANE_DETECTOR="default", MIN_SERVO_ANGLE=50, SERVO_CENTER=95, MAX_SERVO_ANGLE=130,
            SIMULATOR_TARGET_SPEED=20.0, SIMULATOR_THROTTLE_LIMIT=0.3,
            SIMULATOR_STOP_ON_LOST_LANE=True, SIMULATOR_STEERING_INVERTED=False,
            SIMULATOR_OBSTACLE_STOP_DISTANCE_CM=35.0, SIMULATOR_LIDAR_ENABLED=False,
            SIMULATOR_STOP_ON_CROSSWALK=False, TARGET_PROCESSING_FPS=30.0,
            ENCODER_MAP_ENABLED=False, STREAM=False, debug_frames_list=[None, None],
            SHUTDOWN_EVENT=shutdown,
        )
        adapter = FakeAdapter()
        with patch("modes.simulation.runtime.create_adapter", return_value=adapter), patch(
            "vision.city_vision_processing.VisionProcessor", return_value=FakeVision()
        ):
            runtime = SimulationRuntime(config)
            runtime.run()

        self.assertTrue(adapter.closed)
        self.assertIsNotNone(runtime._last_command)
        self.assertEqual(runtime._last_command.brake, 1.0)

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
