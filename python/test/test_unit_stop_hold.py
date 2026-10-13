import sys
import time
import unittest
from unittest.mock import Mock, patch

import numpy as np

sys.path.insert(0, "python")

from traffic_sign_detector.stop_hold import StopSignHold


class StopSignHoldStateTests(unittest.TestCase):
    def test_stale_or_missing_results_never_release_stop(self):
        state = StopSignHold(clear_confirmations=3)
        self.assertTrue(state.observe(
            stop_present=True, fresh=True, observation_time=10.0, now=10.0
        ))

        for _ in range(8):
            self.assertTrue(state.observe(
                stop_present=False,
                fresh=False,
                observation_time=None,
                now=100.0,
            ))

        # An absence result from a frame submitted before the STOP was latched
        # is not valid evidence that the sign has disappeared.
        self.assertTrue(state.observe(
            stop_present=False, fresh=True, observation_time=9.9, now=100.0
        ))
        self.assertTrue(state.active)
        self.assertEqual(state.clear_observations, 0)

    def test_stop_is_held_until_three_fresh_absence_results(self):
        state = StopSignHold(clear_confirmations=3)
        state.observe(
            stop_present=True, fresh=True, observation_time=1.0, now=1.0
        )
        for timestamp in (1.1, 1.2):
            self.assertTrue(state.observe(
                stop_present=False,
                fresh=True,
                observation_time=timestamp,
                now=timestamp,
            ))
        self.assertTrue(state.active)
        self.assertFalse(state.observe(
            stop_present=False, fresh=True, observation_time=1.3, now=1.3
        ))
        self.assertFalse(state.active)

    def test_repeated_stop_detection_resets_absence_confirmation(self):
        state = StopSignHold(clear_confirmations=3)
        state.observe(
            stop_present=True, fresh=True, observation_time=2.0, now=2.0
        )
        state.observe(
            stop_present=False, fresh=True, observation_time=2.1, now=2.1
        )
        self.assertEqual(state.clear_observations, 1)
        self.assertTrue(state.observe(
            stop_present=True, fresh=True, observation_time=2.2, now=2.2
        ))
        self.assertEqual(state.clear_observations, 0)


class StopHoldRobotIntegrationTests(unittest.TestCase):
    def _assert_force_check_bypasses_frame_threshold(self, mode):
        if mode == "city":
            from modes.city import city as mode_module
            config = mode_module.config_city
        else:
            from modes.race import race as mode_module
            config = mode_module.config_race

        robot = mode_module.Robot.__new__(mode_module.Robot)
        robot.read_sign_counter = 0
        robot.last_sign_result_id = 0
        robot.last_tag = None
        robot.stop_last_seen = None
        robot.sign_detector = Mock()
        now = time.monotonic()
        robot.sign_detector.latest.return_value = (
            1,
            {
                "coordinate": None,
                "debug_frame": None,
                "text": "STOP",
            },
            now,
            now,
        )
        frame = np.zeros((240, 320, 3), dtype=np.uint8)

        with patch.object(config, "WITH_SIGN", True), patch.object(
            config, "WITH_APRILTAG", False
        ), patch.object(config, "READ_SIGN_THRESHOLD", 10000), patch.object(
            config, "ST_TOP_ROI", 0.0
        ), patch.object(config, "ST_BOTTOM_ROI", 1.0), patch.object(
            config, "ST_LEFT_ROI", 0.0
        ), patch.object(config, "ST_RIGHT_ROI", 1.0):
            result = robot.handle_read_sign_or_tag(
                frame, None, force_check=True
            )

        robot.sign_detector.submit.assert_called_once()
        self.assertEqual(result[0], 5)
        self.assertTrue(result[1])
        self.assertTrue(robot.stop_hold.active)
        self.assertEqual(robot.stop_hold_detector_kind, "sign")

    def test_city_stop_hold_checks_each_frame_without_read_threshold(self):
        self._assert_force_check_bypasses_frame_threshold("city")

    def test_race_stop_hold_checks_each_frame_without_read_threshold(self):
        self._assert_force_check_bypasses_frame_threshold("race")

    def _assert_stop_hold_frame_is_published(self, mode):
        if mode == "city":
            from modes.city import city as mode_module
            config = mode_module.config_city
        else:
            from modes.race import race as mode_module
            config = mode_module.config_race

        robot = mode_module.Robot.__new__(mode_module.Robot)
        robot.stop_hold = StopSignHold()
        robot.stop_hold.observe(
            stop_present=True, fresh=True, observation_time=time.monotonic()
        )
        robot.stop_hold_detector_kind = "sign"
        robot._last_stop_command_at = None
        robot.camera = Mock()
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        robot.camera.capture_frame.return_value = (frame, frame.copy())
        robot.camera.last_capture_valid = True
        robot.control = Mock()
        robot.control.set_motion_inhibited.return_value = True
        robot.handle_read_sign_or_tag = Mock(return_value=(None, False, None, None))
        robot.handle_debug_stream = Mock()
        robot._pace_control_loop = Mock()

        with patch.object(config, "STREAM", True), patch.object(config, "DEBUG", False):
            robot._run_stop_hold_cycle()

        self.assertEqual(robot.handle_read_sign_or_tag.call_count, 1)
        call = robot.handle_read_sign_or_tag.call_args
        self.assertIs(call.args[0], frame)
        np.testing.assert_array_equal(call.args[1], frame)
        self.assertTrue(call.kwargs["force_check"])
        robot.control.stop.assert_not_called()
        robot.control.set_motion_inhibited.assert_called_once_with(
            True, reason="traffic_sign_stop_hold"
        )
        robot.handle_debug_stream.assert_called_once()
        self.assertIn("STOP HOLD", str(robot.handle_debug_stream.call_args))
        robot._pace_control_loop.assert_called_once()

    def test_city_stop_state_keeps_stream_frames_live(self):
        self._assert_stop_hold_frame_is_published("city")

    def test_race_stop_state_keeps_stream_frames_live(self):
        self._assert_stop_hold_frame_is_published("race")

    def _assert_stop_clear_cycle_does_not_relock_hardware(self, mode):
        if mode == "city":
            from modes.city import city as mode_module
            config = mode_module.config_city
        else:
            from modes.race import race as mode_module
            config = mode_module.config_race

        robot = mode_module.Robot.__new__(mode_module.Robot)
        robot.stop_hold = StopSignHold()
        robot.stop_hold.observe(
            stop_present=True, fresh=True, observation_time=time.monotonic()
        )
        robot.stop_hold_detector_kind = "sign"
        robot._last_stop_command_at = time.monotonic()
        robot.camera = Mock()
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        robot.camera.capture_frame.return_value = (frame, frame.copy())
        robot.camera.last_capture_valid = True
        robot.control = Mock()
        robot.handle_read_sign_or_tag = Mock(
            side_effect=lambda *args, **kwargs: (
                setattr(robot.stop_hold, "active", False) or None,
                False,
                args[1],
                None,
            )
        )
        robot.handle_debug_stream = Mock()
        robot._pace_control_loop = Mock()

        with patch.object(config, "STREAM", True), patch.object(config, "DEBUG", False):
            robot._run_stop_hold_cycle()

        robot.control.stop.assert_not_called()
        robot.handle_debug_stream.assert_called_once()
        self.assertIn("STOP CLEARED", str(robot.handle_debug_stream.call_args))

    def test_city_stop_clear_cycle_does_not_send_stop_again(self):
        self._assert_stop_clear_cycle_does_not_relock_hardware("city")

    def test_race_stop_clear_cycle_does_not_send_stop_again(self):
        self._assert_stop_clear_cycle_does_not_relock_hardware("race")

    def _assert_stop_command_is_sent_each_cycle(self, mode):
        if mode == "city":
            from modes.city.city import Robot
        else:
            from modes.race.race import Robot

        robot = Robot.__new__(Robot)
        robot.control = Mock()
        robot.control.stop.return_value = True
        # Simulate having just sent STOP; the next cycle must still send it.
        robot._last_stop_command_at = time.monotonic()

        robot.control.set_motion_inhibited.return_value = True

        self.assertTrue(robot._keep_stop_hold())
        self.assertTrue(robot._keep_stop_hold())
        self.assertEqual(robot.control.set_motion_inhibited.call_count, 2)
        robot.control.set_motion_inhibited.assert_called_with(
            True, reason="traffic_sign_stop_hold"
        )
        # A healthy, already-latched STOP must not flood the UART with writes.
        robot.control.stop.assert_not_called()

    def test_city_stop_state_is_maintained_without_repeated_stop_writes(self):
        self._assert_stop_command_is_sent_each_cycle("city")

    def test_race_stop_state_is_maintained_without_repeated_stop_writes(self):
        self._assert_stop_command_is_sent_each_cycle("race")


    def _assert_detection_latches_controller_motion(self, mode):
        if mode == "city":
            from modes.city import city as mode_module
        else:
            from modes.race import race as mode_module

        robot = mode_module.Robot.__new__(mode_module.Robot)
        robot.stop_hold = StopSignHold(clear_confirmations=3)
        robot.stop_last_seen = None
        robot.stop_hold_detector_kind = None
        robot.last_sign_observation_fresh = True
        robot.last_sign_observation_at = 50.0
        robot._last_stop_command_at = None
        robot.control = Mock()
        robot.control.set_motion_inhibited.return_value = True

        self.assertTrue(robot._observe_stop_result(True, detector_kind="sign"))
        robot.control.set_motion_inhibited.assert_called_once_with(
            True, reason="traffic_sign_stop_hold"
        )

        robot.last_sign_observation_at = 50.1
        self.assertTrue(robot._observe_stop_result(False))
        robot.last_sign_observation_at = 50.2
        self.assertTrue(robot._observe_stop_result(False))
        robot.last_sign_observation_at = 50.3
        self.assertFalse(robot._observe_stop_result(False))
        robot.control.set_motion_inhibited.assert_called_with(
            False, reason="traffic_sign_cleared"
        )

    def test_city_stop_detection_latches_shared_controller(self):
        self._assert_detection_latches_controller_motion("city")

    def test_race_stop_detection_latches_shared_controller(self):
        self._assert_detection_latches_controller_motion("race")


if __name__ == "__main__":
    unittest.main()
