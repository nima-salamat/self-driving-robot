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
        robot.handle_read_sign_or_tag = Mock(return_value=(None, False, None, None))
        robot.handle_debug_stream = Mock()
        robot._pace_control_loop = Mock()

        with patch.object(config, "STREAM", True), patch.object(config, "DEBUG", False):
            robot._run_stop_hold_cycle()

        robot.handle_read_sign_or_tag.assert_called_once_with(
            frame, frame, force_check=True
        )
        robot.control.stop.assert_called_once_with(reason="traffic_sign_stop_hold")
        robot.handle_debug_stream.assert_called_once()
        self.assertIn("STOP HOLD", str(robot.handle_debug_stream.call_args))
        robot._pace_control_loop.assert_called_once()

    def test_city_stop_state_keeps_stream_frames_live(self):
        self._assert_stop_hold_frame_is_published("city")

    def test_race_stop_state_keeps_stream_frames_live(self):
        self._assert_stop_hold_frame_is_published("race")


if __name__ == "__main__":
    unittest.main()
