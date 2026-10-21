import sys
import time
import types
import unittest
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, "python")

from modes.city import city as city_module
from modes.race import race as race_module
from traffic_sign_detector.stop_hold import StopSignHold


MODE_CASES = (
    ("city", city_module, city_module.config_city),
    ("race", race_module, race_module.config_race),
)


class FakeControl:
    """Serial-free controller that records every attempted command."""

    def __init__(self):
        self.without_arduino = False
        self.connection = types.SimpleNamespace(connected=True)
        self.motion_inhibited = False
        self.fail_writes = False
        self.commands = []
        self.motion_calls = []

    def set_motion_inhibited(self, inhibited, reason=None):
        if not inhibited and self.motion_inhibited:
            if not self._write("motion enable\n"):
                return False
        self.motion_inhibited = bool(inhibited)
        return True

    def stop(self, reason=None):
        return self._write("stop\n")

    def _write(self, command):
        if not self.connection.connected or self.fail_writes:
            return False
        self.commands.append(command)
        return True

    def set_angle(self, angle):
        self.motion_calls.append(("angle", angle))
        return not self.motion_inhibited

    def set_angle_by_error(self, error, lane_type):
        self.motion_calls.append(("angle_by_error", error, lane_type))
        return not self.motion_inhibited

    def set_speed(self, speed):
        self.motion_calls.append(("speed", speed))
        return not self.motion_inhibited

    def motor(self, speed):
        self.motion_calls.append(("motor", speed))
        return not self.motion_inhibited

    def forward_pulse(self, command, **kwargs):
        self.motion_calls.append(("forward_pulse", command))
        return not self.motion_inhibited

    def backward_pulse(self, command, **kwargs):
        self.motion_calls.append(("backward_pulse", command))
        return not self.motion_inhibited


class StopSignHoldStateTests(unittest.TestCase):
    def start(self, state, activation=10.0, observation=9.0):
        self.assertTrue(
            state.observe(
                stop_present=True,
                fresh=True,
                observation_time=observation,
                now=activation,
            )
        )

    def absent(self, state, timestamp, now=None, fresh=True):
        return state.observe(
            stop_present=False,
            fresh=fresh,
            observation_time=timestamp,
            now=timestamp if now is None else now,
        )

    def test_stop_activates_at_acceptance_time_and_stays_active_at_2_99(self):
        state = StopSignHold(clear_confirmations=3, minimum_duration_s=3.0)
        self.start(state, activation=10.0, observation=1.0)
        for timestamp in (10.1, 10.2, 10.3):
            self.absent(state, timestamp, now=12.0)

        self.assertEqual(state.started_at, 10.0)
        self.assertEqual(state.clear_observations, 3)
        self.assertFalse(state.can_release(now=12.99))
        self.assertFalse(state.release(now=12.99))
        self.assertTrue(state.active)

    def test_negative_minimum_duration_is_rejected(self):
        with self.assertRaises(ValueError):
            StopSignHold(minimum_duration_s=-0.01)

    def test_default_stop_requires_minimum_duration_after_fresh_absence(self):
        state = StopSignHold()
        self.start(state)
        self.absent(state, 10.1, now=10.1)
        self.assertFalse(state.can_release(now=10.1))
        self.assertFalse(state.release(now=10.1))
        self.assertTrue(state.active)
        self.assertTrue(state.can_release(now=13.1))
        self.assertTrue(state.release(now=13.1))
        self.assertFalse(state.active)

    def test_timer_alone_never_releases_stop(self):
        state = StopSignHold(clear_confirmations=3)
        self.start(state)
        self.assertFalse(state.can_release(now=100.0))
        self.assertTrue(state.active)

    def test_stale_duplicate_missing_and_failed_results_do_not_confirm_absence(self):
        state = StopSignHold(clear_confirmations=3)
        self.start(state, activation=10.0, observation=10.0)
        self.absent(state, 9.9, now=13.0)  # predates activation
        self.absent(state, 10.1, now=13.0)
        self.absent(state, 10.1, now=13.0)  # duplicate frame timestamp
        state.observe(
            stop_present=False,
            fresh=False,
            observation_time=10.2,
            now=13.0,
        )  # failed/stale result
        state.observe(stop_present=False, fresh=True, observation_time=None, now=13.0)

        self.assertEqual(state.clear_observations, 1)
        self.assertFalse(state.can_release(now=13.0))
        self.assertTrue(state.active)

    def test_renewed_positive_stop_resets_absence_confirmations(self):
        state = StopSignHold()
        self.start(state)
        self.absent(state, 10.1)
        self.absent(state, 10.2)
        state.observe(
            stop_present=True,
            fresh=True,
            observation_time=10.3,
            now=10.3,
        )
        self.assertEqual(state.clear_observations, 0)
        self.absent(state, 10.4)
        self.assertEqual(state.clear_observations, 1)
        self.assertTrue(state.active)

    def test_default_hold_remains_active_until_minimum_duration_elapses(self):
        state = StopSignHold()
        self.start(state)
        self.absent(state, 10.1, now=10.1)
        self.assertEqual(state.clear_observations, 1)
        self.assertFalse(state.can_release(now=13.09))
        self.assertFalse(state.release(now=13.09))
        self.assertTrue(state.active)
        self.assertTrue(state.can_release(now=13.1))
        self.assertTrue(state.release(now=13.1))
        self.assertFalse(state.active)


class StopHoldModeTests(unittest.TestCase):
    @staticmethod
    def make_robot(mode_module):
        robot = mode_module.Robot.__new__(mode_module.Robot)
        robot.stop_hold = StopSignHold()
        robot.stop_hold_detector_kind = None
        robot.stop_last_seen = None
        robot.last_sign_observation_fresh = False
        robot.last_sign_observation_at = None
        robot.last_sign_result_id = 0
        robot.last_tag = None
        robot.read_sign_counter = 0
        robot._last_stop_command_at = None
        robot._last_stop_release_attempt_at = None
        robot._mcu_stop_latched = False
        robot._stop_connection_state = None
        robot.metrics = None
        robot.camera = types.SimpleNamespace(last_capture_at=None)
        # Normal Race sign reads are gated to start/finish phases or an active
        # STOP hold; this fixture models the inactive mid-race phase.
        robot.race_finish = types.SimpleNamespace(finishing=False)
        robot._race_timer_started = False
        robot.control = FakeControl()
        return robot

    @staticmethod
    def fresh_result(label="STOP", result_id=1, submitted_at=None):
        submitted_at = time.monotonic() - 0.01 if submitted_at is None else submitted_at
        return (
            result_id,
            {"coordinate": ((0, 0), (40, 40)), "debug_frame": None, "text": label, "sign_type": 1},
            submitted_at,
            time.monotonic(),
        )

    def test_city_operator_stop_keeps_debug_stream_signature_valid(self):
        robot = self.make_robot(city_module)
        robot.health = None
        robot.runtime_exception = None
        robot._next_control_time = 0.0
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        robot.fps = Mock()
        robot.camera = Mock()
        robot.camera.capture_frame.return_value = (frame, None)
        robot.camera.last_capture_valid = True
        robot.handle_debug_stream = Mock()
        robot._pace_control_loop = Mock()
        robot.close = Mock()

        with patch.object(city_module.config_city, "RUN_LVL", "STOP"), patch.object(
            city_module.config_city, "STREAM", True
        ), patch.object(city_module.config_city, "DEBUG", False), patch.object(
            robot, "_shutdown_requested", side_effect=[False, True]
        ):
            robot.run()

        robot.handle_debug_stream.assert_called_once()
        args = robot.handle_debug_stream.call_args.args
        self.assertEqual(len(args), 6)
        self.assertEqual(args[4], "stopped")
        self.assertEqual(args[5], "")
        robot.close.assert_called_once()

    def test_completed_stop_is_consumed_without_threshold_submission_and_blocks_motion(self):
        frame = np.zeros((240, 320, 3), dtype=np.uint8)

        for name, mode_module, config in MODE_CASES:
            with self.subTest(mode=name):
                robot = self.make_robot(mode_module)
                robot.health = None
                robot.metrics = None
                robot.runtime_exception = None
                robot._next_control_time = 0.0
                robot.fps = Mock()
                robot.fps.instant_fps = 30
                robot.fps.second_fps = 30
                robot.fps.avg_fps = 30
                robot.camera = Mock()
                robot.camera.capture_frame.return_value = (frame, frame.copy())
                robot.camera.last_capture_valid = True
                robot.vision = Mock()
                robot.vision.detect.return_value = {
                    "perception_valid": False,
                    "lane_type": "invalid",
                    "steering_angle": 90,
                    "crosswalk": False,
                    "error": 0,
                }
                robot.sign_detector = Mock()
                robot.sign_detector.latest.return_value = self.fresh_result()
                robot.handle_debug_stream = Mock()
                robot._pace_control_loop = Mock()
                robot._wait_for_processing_slot = Mock(return_value=True)
                robot.close = Mock()

                if name == "city":
                    robot.crosswalk_time_start = 0
                    robot.crosswalk_last_seen = 0
                else:
                    # Race sign inference is disabled in the middle phase.
                    robot.odometry = None

                with patch.object(config, "RUN_LVL", "MOVE"), patch.object(
                    config, "WITH_SIGN", True
                ), patch.object(config, "WITH_APRILTAG", False), patch.object(
                    config, "READ_SIGN_THRESHOLD", 10000
                ), patch.object(config, "STREAM", False), patch.object(
                    config, "DEBUG", False
                ), patch.object(
                    config, "ST_TOP_ROI", 0.0
                ), patch.object(config, "ST_BOTTOM_ROI", 1.0), patch.object(
                    config, "ST_LEFT_ROI", 0.0
                ), patch.object(config, "ST_RIGHT_ROI", 1.0), patch.object(
                    robot, "_shutdown_requested", side_effect=[False, True]
                ):
                    robot.run()

                if name == "race":
                    # A STOP result must not even be consumed in the middle
                    # of Race; only the start gate and timed finish may infer signs.
                    robot.sign_detector.latest.assert_not_called()
                    robot.sign_detector.submit.assert_not_called()
                    self.assertFalse(robot.stop_hold.active)
                    self.assertEqual(robot.control.commands, ["stop\n"])
                    self.assertEqual(robot.control.motion_calls, [])
                    robot.close.assert_called_once()
                    continue

                robot.sign_detector.latest.assert_called_once()
                robot.sign_detector.submit.assert_not_called()
                self.assertTrue(robot.stop_hold.active)
                self.assertEqual(robot.control.commands, ["stop\n"])
                self.assertEqual(robot.control.motion_calls, [])
                robot.close.assert_called_once()

    def test_disconnection_then_reconnect_keeps_python_gate_and_reasserts_stop(self):
        for name, mode_module, _ in MODE_CASES:
            with self.subTest(mode=name):
                robot = self.make_robot(mode_module)
                robot.control.connection.connected = False

                self.assertFalse(robot._set_mcu_stop_latched(True))
                self.assertTrue(robot.control.motion_inhibited)
                self.assertTrue(robot._mcu_stop_latched)
                self.assertEqual(robot.control.commands, [])

                robot.control.connection.connected = True
                self.assertTrue(robot._set_mcu_stop_latched(True))
                self.assertEqual(robot.control.commands, ["stop\n"])
                self.assertTrue(robot.control.motion_inhibited)

    def test_stop_command_refresh_uses_configured_interval(self):
        for name, mode_module, config in MODE_CASES:
            with self.subTest(mode=name):
                robot = self.make_robot(mode_module)
                with patch.object(
                    config, "STOP_COMMAND_REFRESH_INTERVAL", 0.25
                ), patch.object(
                    mode_module.time,
                    "monotonic",
                    side_effect=[1.0, 1.1, 1.26],
                ):
                    self.assertTrue(robot._set_mcu_stop_latched(True))
                    self.assertTrue(robot._set_mcu_stop_latched(True))
                    self.assertTrue(robot._set_mcu_stop_latched(True))
                self.assertEqual(
                    robot.control.commands,
                    ["stop\n", "stop\n"],
                )

    def test_duplicate_completed_absence_result_counts_only_once(self):
        base = time.monotonic()
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        result = (
            2,
            {"coordinate": None, "debug_frame": None, "text": ""},
            base + 0.01,
            base + 0.02,
        )

        for name, mode_module, config in MODE_CASES:
            with self.subTest(mode=name):
                robot = self.make_robot(mode_module)
                robot.stop_hold.observe(
                    stop_present=True,
                    fresh=True,
                    observation_time=base,
                    now=base,
                )
                robot.stop_hold_detector_kind = "sign"
                robot.last_sign_result_id = 1
                robot.sign_detector = Mock()
                robot.sign_detector.latest.return_value = result

                with patch.object(config, "WITH_SIGN", True), patch.object(
                    config, "WITH_APRILTAG", False
                ), patch.object(config, "READ_SIGN_THRESHOLD", 10000), patch.object(
                    config, "ST_TOP_ROI", 0.0
                ), patch.object(config, "ST_BOTTOM_ROI", 1.0), patch.object(
                    config, "ST_LEFT_ROI", 0.0
                ), patch.object(config, "ST_RIGHT_ROI", 1.0):
                    robot.handle_read_sign_or_tag(frame, None, force_check=True)
                    robot.handle_read_sign_or_tag(frame, None, force_check=True)

                self.assertEqual(robot.stop_hold.clear_observations, 1)
                self.assertTrue(robot.stop_hold.active)

    def _handle_sign_result(self, mode_module, config, robot, result, **overrides):
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        robot.sign_detector = Mock()
        robot.sign_detector.latest.return_value = result
        settings = {
            "WITH_SIGN": True,
            "WITH_APRILTAG": False,
            "READ_SIGN_THRESHOLD": 10000,
            "ST_TOP_ROI": 0.0,
            "ST_BOTTOM_ROI": 1.0,
            "ST_LEFT_ROI": 0.0,
            "ST_RIGHT_ROI": 1.0,
            "SIGN_AREA_FILTER_ENABLED": True,
            "SIGN_AREA_FILTER_TARGETS": ["STOP"],
            "SIGN_AREA_MIN_PX2": 100,
        }
        settings.update(overrides)
        with patch.multiple(config, **settings):
            return robot.handle_read_sign_or_tag(frame, None, force_check=True)

    def test_area_filter_in_both_modes_blocks_small_stop_and_accepts_large_stop(self):
        for name, mode_module, config in MODE_CASES:
            with self.subTest(mode=name, size="small"):
                robot = self.make_robot(mode_module)
                item = self.fresh_result()
                small = (item[0], {**item[1], "coordinate": ((0, 0), (10, 10))}, item[2], item[3])
                result = self._handle_sign_result(mode_module, config, robot, small)
                self.assertIsNone(result[0])
                self.assertFalse(result[1])
                self.assertIsNone(robot.last_tag)
                self.assertFalse(robot.stop_hold.active)
                self.assertEqual(robot.control.commands, [])
                self.assertFalse(robot.last_sign_observation_fresh)

            with self.subTest(mode=name, size="accepted"):
                robot = self.make_robot(mode_module)
                result = self._handle_sign_result(
                    mode_module, config, robot, self.fresh_result(result_id=2)
                )
                self.assertEqual(result[0], config.STOP)
                self.assertTrue(result[1])
                self.assertTrue(robot.stop_hold.active)
                self.assertEqual(robot.control.commands, ["stop\n"])

    def test_filtered_stop_does_not_count_as_clearance_or_duplicate_observation(self):
        for name, mode_module, config in MODE_CASES:
            with self.subTest(mode=name):
                robot = self.make_robot(mode_module)
                started = time.monotonic()
                robot.stop_hold.observe(
                    stop_present=True,
                    fresh=True,
                    observation_time=started,
                    now=started,
                )
                robot.stop_hold_detector_kind = "sign"
                item = self.fresh_result(result_id=2, submitted_at=started + 0.01)
                tiny_stop = (
                    item[0],
                    {**item[1], "coordinate": ((0, 0), (1, 1))},
                    item[2],
                    item[3],
                )
                self._handle_sign_result(mode_module, config, robot, tiny_stop)
                self._handle_sign_result(mode_module, config, robot, tiny_stop)
                self.assertTrue(robot.stop_hold.active)
                self.assertEqual(robot.stop_hold.clear_observations, 0)
                self.assertEqual(robot.last_sign_result_id, 2)

    def test_non_target_small_sign_still_triggers_and_apriltag_is_unfiltered(self):
        for name, mode_module, config in MODE_CASES:
            with self.subTest(mode=name, kind="sign"):
                robot = self.make_robot(mode_module)
                item = self.fresh_result(label="TURN LEFT")
                small_left = (
                    item[0],
                    {**item[1], "coordinate": ((0, 0), (1, 1)), "sign_type": 3},
                    item[2],
                    item[3],
                )
                result = self._handle_sign_result(mode_module, config, robot, small_left)
                self.assertEqual(result[0], config.TURN_LEFT)
                self.assertTrue(robot.last_sign_observation_fresh)

            with self.subTest(mode=name, kind="apriltag"):
                robot = self.make_robot(mode_module)
                robot.apriltag_detector = Mock()
                robot.apriltag_detector.detect.return_value = (
                    [], None, {"id": config.STOP, "corners": [(0, 0), (0, 0)]}, None
                )
                frame = np.zeros((240, 320, 3), dtype=np.uint8)
                with patch.multiple(
                    config,
                    WITH_SIGN=False,
                    WITH_APRILTAG=True,
                    ST_TOP_ROI=0.0,
                    ST_BOTTOM_ROI=1.0,
                    ST_LEFT_ROI=0.0,
                    ST_RIGHT_ROI=1.0,
                    SIGN_AREA_FILTER_ENABLED=True,
                    SIGN_AREA_FILTER_TARGETS=["STOP"],
                    SIGN_AREA_MIN_PX2=100000,
                ):
                    result = robot.handle_read_sign_or_tag(frame, None)
                self.assertEqual(result[0], config.STOP)
                self.assertTrue(result[1])

    def test_failed_stop_write_does_not_clear_gate_and_retries(self):
        for name, mode_module, _ in MODE_CASES:
            with self.subTest(mode=name):
                robot = self.make_robot(mode_module)
                robot.control.fail_writes = True

                self.assertFalse(robot._set_mcu_stop_latched(True))
                self.assertTrue(robot.control.motion_inhibited)
                self.assertTrue(robot._mcu_stop_latched)

                robot.control.fail_writes = False
                robot._last_stop_command_at -= 1.0
                self.assertTrue(robot._set_mcu_stop_latched(True))
                self.assertEqual(robot.control.commands, ["stop\n"])
                self.assertNotIn("safety stop\n", robot.control.commands)

    def test_failed_release_keeps_hold_active_and_blocks_resume(self):
        for name, mode_module, _ in MODE_CASES:
            with self.subTest(mode=name):
                robot = self.make_robot(mode_module)
                robot.stop_hold.observe(
                    stop_present=True,
                    fresh=True,
                    observation_time=1.0,
                    now=1.0,
                )
                for stamp in (1.1, 1.2, 1.3):
                    robot.stop_hold.observe(
                        stop_present=False,
                        fresh=True,
                        observation_time=stamp,
                        now=stamp,
                    )
                robot._mcu_stop_latched = True
                robot.control.motion_inhibited = True
                robot.control.fail_writes = True

                with patch.object(mode_module.time, "monotonic", return_value=5.0):
                    self.assertFalse(robot._release_stop_hold_if_ready())
                self.assertTrue(robot.stop_hold.active)
                self.assertTrue(robot.control.motion_inhibited)

                robot.control.fail_writes = False
                with patch.object(mode_module.time, "monotonic", return_value=5.3):
                    self.assertTrue(robot._release_stop_hold_if_ready())
                self.assertFalse(robot.stop_hold.active)
                self.assertFalse(robot.control.motion_inhibited)
                self.assertEqual(
                    robot.control.commands,
                    ["motion enable\n"],
                )

    def test_stop_hold_repeats_without_motion_and_keeps_debug_stream_live(self):
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        for name, mode_module, config in MODE_CASES:
            with self.subTest(mode=name):
                robot = self.make_robot(mode_module)
                robot.stop_hold.observe(
                    stop_present=True,
                    fresh=True,
                    observation_time=1.0,
                    now=1.0,
                )
                robot.stop_hold_detector_kind = "sign"
                robot.camera = Mock()
                robot.camera.capture_frame.return_value = (frame, frame.copy())
                robot.camera.last_capture_valid = True
                robot.handle_read_sign_or_tag = Mock(
                    return_value=("", False, None, None)
                )
                robot.handle_debug_stream = Mock()
                robot._pace_control_loop = Mock()
                robot._set_mcu_stop_latched(True, force=True)

                with patch.object(config, "STREAM", True), patch.object(
                    config, "DEBUG", False
                ):
                    robot._run_stop_hold_cycle()
                    robot._run_stop_hold_cycle()

                self.assertTrue(robot.stop_hold.active)
                self.assertTrue(robot.control.motion_inhibited)
                self.assertEqual(robot.control.motion_calls, [])
                self.assertEqual(robot.control.commands, ["stop\n"])
                self.assertEqual(robot.handle_read_sign_or_tag.call_count, 2)
                self.assertEqual(robot.handle_debug_stream.call_count, 2)

    def test_operator_stop_uses_same_exact_stop_command(self):
        for name, mode_module, _ in MODE_CASES:
            with self.subTest(mode=name):
                robot = self.make_robot(mode_module)
                self.assertTrue(robot._set_mcu_stop_latched(True, force=True))
                self.assertEqual(robot.control.commands, ["stop\n"])
                self.assertNotIn("safety stop\n", robot.control.commands)

    def test_unrelated_controller_stop_remains_temporary(self):
        from controller import controller as controller_module

        class Connection:
            def __init__(self, *args, **kwargs):
                self.connected = True
                self.commands = []

            def set_print_telemetry(self, enabled):
                pass

            def send_command(self, command):
                self.commands.append(command)
                return True

            def close(self):
                pass

        config = types.SimpleNamespace(
            MODE="city",
            WITHOUT_ARDUINO=False,
            SERIAL_STARTUP_WAIT=0,
        )
        with patch.object(controller_module, "ArduinoConnection", Connection):
            control = controller_module.RobotController(config)
        self.assertTrue(control.stop())
        self.assertFalse(control.motion_inhibited)
        self.assertTrue(control.motor(100))
        self.assertEqual(control.connection.commands, ["stop\n", "motor 100\n"])


if __name__ == "__main__":
    unittest.main()
