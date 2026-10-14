import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arduino.arduino_connection import ArduinoConnection
from controller.adaptive_obstacle import AdaptiveObstaclePlanner
from controller.controller import RobotController
from controller.odometry import EncoderOdometry
from controller.perception_confidence import ConfidenceSpeedLimiter, PerceptionConfidenceEstimator
from main import _apply_cli_overrides
from stream import WebStreamer


class FakeConnection:
    def __init__(self, *args, **kwargs):
        self.connected = True
        self.commands = []
    def set_print_telemetry(self, _): pass
    def send_command(self, command): self.commands.append(command); return True
    def wait_until_connected(self, _): return True
    def close(self): pass
    def telemetry_records(self, limit=None): return []
    def telemetry_status(self, limit=50): return {"lines_received": 0}
    def telemetry_snapshot(self, limit=None): return []


class OptInFeatureTests(unittest.TestCase):
    def test_cli_features_are_disabled_even_if_old_json_set_them(self):
        config = types.SimpleNamespace(ENCODER_MAP_ENABLED=True,
                                       CONFIDENCE_AWARE_ENABLED=True,
                                       ADAPTIVE_OBSTACLE_AVOIDANCE_ENABLED=True)
        args = types.SimpleNamespace(debug=None, stream=False, fps=None,
            performance=None, without_arduino=None, read_arduino_output=None,
            send_traffic_stop_command=None, stream_control=None, camera_mode=None,
            camera_index=None, arduino_config=None, arduino_contract_timeout=None,
            city_lane_detector=None, stream_host=None, ml_lane_model=None,
            traffic_lights=False, traffic_light_wait_before_check=False,
            encoder_map=False, confidence_aware=False,
            adaptive_obstacle_avoidance=False,
            encoder_pulse_distance_cm=2.0, encoder_wheelbase_cm=None,
            encoder_road_wheel_angle_at_servo_min_deg=None,
            encoder_road_wheel_angle_at_servo_max_deg=None,
            confidence_slow_threshold=0.65, confidence_stop_threshold=0.30,
            obstacle_trigger_distance_cm=35, obstacle_stop_distance_cm=4,
            obstacle_lane_width_cm=None, obstacle_robot_width_cm=None,
            obstacle_clearance_cm=None)
        _apply_cli_overrides(config, args)
        self.assertFalse(config.ENCODER_MAP_ENABLED)
        self.assertFalse(config.CONFIDENCE_AWARE_ENABLED)
        self.assertFalse(config.ADAPTIVE_OBSTACLE_AVOIDANCE_ENABLED)

    def test_controller_initialization_and_reconnect_center_are_configured(self):
        config = types.SimpleNamespace(MODE="race", KP=1, KI=0, KD=0, KT=0,
            OUTPUT_LIMITS=(-80, 80), MIN_SERVO_ANGLE=55, MAX_SERVO_ANGLE=125,
            SERVO_CENTER=95, SERVO_DIRECTION="ltr", WITHOUT_ARDUINO=False,
            SERIAL_STARTUP_WAIT=0, ARDUINO_CONFIG=None)
        with patch("controller.controller.ArduinoConnection", FakeConnection):
            robot = RobotController(config)
        self.assertEqual(robot.current_angle, 95)
        self.assertEqual(robot.servo_center, 95)

        class Serial:
            is_open = True
            def __init__(self): self.writes = []
            def write(self, data): self.writes.append(data)
            def flush(self): pass
        connection = ArduinoConnection(enabled=False, servo_center=95)
        try:
            fake = Serial()
            connection.serial_connection = fake
            self.assertTrue(connection._establish_safe_state())
            self.assertEqual(fake.writes, [b"stop\n", b"servo 95\n"])
        finally:
            connection.close()

    def test_old_and_extended_status_contract(self):
        old = RobotController.parse_status_line("R F 25 -1 30 1000 0")
        self.assertEqual(old["right_ultrasonic_dist"], 25)
        self.assertEqual(old["left_ultrasonic_dist"], -1)
        self.assertFalse(old["extended"])
        ext = RobotController.parse_status_line(
            "R F 25 -1 30 1000 0 ODOM1 12 2 95 1 1 4 10 0 2 180"
        )
        self.assertTrue(ext["extended"])
        self.assertTrue(ext["front_valid"])
        self.assertFalse(ext["side_valid"])
        self.assertIsNone(RobotController.parse_status_line("R F nope -1 30 1000 0"))

    def test_odometry_counts_signed_distance_gaps_and_calibrated_path(self):
        odom = EncoderOdometry(0.5, wheelbase_cm=20, servo_center=95,
            servo_min=55, servo_max=125, road_angle_min_deg=-20,
            road_angle_max_deg=20)
        self.assertTrue(odom.ingest({"extended": True, "valid": True,
                                     "epoch": 1, "signed_pulses": 0, "servo": 95}, 1.0))
        self.assertTrue(odom.ingest({"extended": True, "valid": True,
                                     "epoch": 1, "signed_pulses": 4, "servo": 95}, 1.1))
        snap = odom.snapshot(1.1)
        self.assertEqual(snap["travel_cm"], 2.0)
        self.assertAlmostEqual(snap["x_cm"], 2.0, places=4)
        self.assertEqual(snap["servo_center"], 95)
        self.assertFalse(odom.ingest({"extended": True, "valid": True,
                                      "epoch": 2, "signed_pulses": 0, "servo": 95}, 1.2))
        self.assertTrue(odom.snapshot(1.2)["history"][-1]["gap"])

    def test_pulse_distance_only_has_no_fabricated_xy(self):
        odom = EncoderOdometry(0.25)
        odom.ingest({"extended": True, "valid": True, "epoch": 1,
                     "signed_pulses": 0, "servo": 95}, 1.0)
        odom.ingest({"extended": True, "valid": True, "epoch": 1,
                     "signed_pulses": 4, "servo": 95}, 1.1)
        state = odom.snapshot(1.1)
        self.assertEqual(state["travel_cm"], 1.0)
        self.assertIsNone(state["x_cm"])
        self.assertFalse(state["trajectory_available"])

    def test_confidence_temporal_observations_and_speed_hysteresis(self):
        estimator = PerceptionConfidenceEstimator()
        result = {"perception_valid": True, "lane_type": "both", "error": 1}
        good = estimator.evaluate(result, frame_at=1, now=1, observation_token=1)
        one_lane = estimator.evaluate({**result, "lane_type": "only_left"},
                                      frame_at=2, now=2, observation_token=2)
        stale = estimator.evaluate(result, frame_at=0, now=2, observation_token=3)
        self.assertGreater(good["score"], one_lane["score"])
        self.assertFalse(stale["fresh"])
        limiter = ConfidenceSpeedLimiter()
        self.assertEqual(limiter.limit(200, good)[0], 200)
        self.assertEqual(limiter.limit(200, {"valid": False, "score": 0})[0], 0)

    def test_adaptive_planner_fails_closed_and_does_not_use_left_sonar(self):
        planner = AdaptiveObstaclePlanner(35, 4, 40, 12, 3)
        observation = {"front_right_cm": 25, "front_age_s": 0.1,
                       "left_cm": -1, "orange_obstacle_detected": True,
                       "obstacle_lane_relation": "center", "camera_fresh": True,
                       "camera_geometry_valid": True, "feasible_sides": [],
                       "steering_calibrated": False, "configured_speed": 200,
                       "slow_speed": 70, "lane_servo": 95, "servo_center": 95}
        planner.update(observation, now=1)
        candidate = planner.update(observation, now=1.1)
        self.assertEqual(candidate["state"], "APPROACH_SLOW")
        stopped = planner.update(observation, now=1.2)
        self.assertEqual(stopped["state"], "SAFE_STOP")
        self.assertEqual(stopped["speed"], 0)
        self.assertEqual(stopped["steering"], 95)

    def test_stream_map_routes_are_strictly_opt_in(self):
        config = types.SimpleNamespace(MODE="race", STREAM=True,
            STREAM_ALLOW_CONTROL=False, debug_frames_list=[], OUTPUT_DIR="output",
            ENCODER_MAP_ENABLED=False)
        client = WebStreamer(config).app.test_client()
        self.assertEqual(client.get("/encoder-map").status_code, 404)
        config.ENCODER_MAP_ENABLED = True
        odom = EncoderOdometry(0.5)
        config.encoder_odometry = odom
        client = WebStreamer(config).app.test_client()
        self.assertEqual(client.get("/encoder-map").status_code, 200)
        self.assertEqual(client.get("/api/encoder-map").status_code, 200)
        self.assertEqual(client.post("/api/encoder-map/reset-origin").status_code, 403)

    def test_exact_firmware_neutral_and_legacy_sensor_guard_contract(self):
        firmware = (ROOT.parent / "arduino" / "new_main_adaptive_pwm_with_savingPulseInEEPROM").read_bytes().decode("latin-1")
        self.assertIn("const int SERVO_CENTER = 95;", firmware)
        self.assertIn("int servoCurrent = 95;", firmware)
        self.assertIn("startServoMoveImmediate(SERVO_CENTER);", firmware)
        self.assertIn("ultraSide.sampleValid && (millis() - ultraSide.lastReadMs)", firmware)
        self.assertNotIn("distSide > SIDE_RETURN_DISTANCE_CM || distSide == -1", firmware)
        self.assertIn("abs(getPulseCount()) >= targetPulses", firmware)


if __name__ == "__main__":
    unittest.main()
