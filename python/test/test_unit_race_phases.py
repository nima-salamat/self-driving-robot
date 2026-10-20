import argparse
import time
import types
import unittest
from unittest.mock import Mock, patch

import numpy as np

from main import _apply_cli_overrides, _validate_opt_in_features
from traffic_sign_detector.race_start_gate import RaceFinishState, RaceStartGate
from traffic_sign_detector.stop_hold import StopSignHold
from traffic_sign_detector.async_detector import AsyncSignDetector
from utils.parser import parse_args


class RaceStartGateTests(unittest.TestCase):
    def setUp(self):
        self.gate = RaceStartGate()

    def observation(self, result_id, stop, observed_at, now, valid=True):
        return self.gate.observe(
            result_id=result_id,
            stop_present=stop,
            observation_at=observed_at,
            now=now,
            valid=valid,
        )

    def test_requires_stop_then_default_full_absence_interval(self):
        self.assertFalse(self.observation(1, False, 0.0, 0.0))
        self.assertFalse(self.observation(2, True, 0.1, 0.1))
        self.assertFalse(self.observation(3, False, 0.2, 0.2))
        self.assertFalse(self.observation(4, False, 0.9, 0.9))
        self.assertFalse(self.observation(5, False, 1.19, 1.19))
        self.assertTrue(self.observation(6, False, 1.21, 1.21))

    def test_stop_reappearance_resets_and_custom_interval_is_respected(self):
        gate = RaceStartGate(absence_seconds=0.4)
        gate.observe(result_id=1, stop_present=True, observation_at=0, now=0)
        gate.observe(result_id=2, stop_present=False, observation_at=0.1, now=0.1)
        gate.observe(result_id=3, stop_present=True, observation_at=0.3, now=0.3)
        self.assertFalse(gate.observe(result_id=4, stop_present=False, observation_at=0.4, now=0.4))
        self.assertFalse(gate.observe(result_id=5, stop_present=False, observation_at=0.79, now=0.79))
        self.assertTrue(gate.observe(result_id=6, stop_present=False, observation_at=0.81, now=0.81))

    def test_duplicate_stale_missing_and_failed_results_never_confirm_absence(self):
        gate = RaceStartGate(absence_seconds=0.2, max_observation_age_s=0.1)
        gate.observe(result_id=1, stop_present=True, observation_at=0, now=0)
        gate.observe(result_id=2, stop_present=False, observation_at=0.01, now=0.01)
        self.assertFalse(gate.observe(result_id=2, stop_present=False, observation_at=0.01, now=0.05))
        self.assertFalse(gate.observe(result_id=None, stop_present=False, observation_at=None, now=0.2, valid=False))
        self.assertFalse(gate.observe(result_id=3, stop_present=False, observation_at=0.0, now=0.21))
        self.assertFalse(gate.released)


class RaceFinishStateTests(unittest.TestCase):
    def test_timer_and_terminal_transition_are_monotonic_and_one_way(self):
        state = RaceFinishState(5, 42)
        self.assertFalse(state.update(20))
        state.start(100)
        self.assertFalse(state.update(104.99))
        self.assertTrue(state.update(105))
        self.assertEqual(state.finish_speed, 42)
        self.assertTrue(state.finish())
        self.assertFalse(state.finish())
        self.assertTrue(state.finished)


class RacePhaseModeTests(unittest.TestCase):
    def test_gate_keeps_controller_inhibited_until_fresh_stop_then_absence(self):
        from modes.race import race as mode

        class Control:
            def __init__(self):
                self.motion_inhibited = False
                self.motion_inhibit_reason = None
                self.inhibitions = []
                self.stops = []

            def set_motion_inhibited(self, inhibited, reason=None):
                self.motion_inhibited = inhibited
                self.motion_inhibit_reason = reason if inhibited else None
                self.inhibitions.append((inhibited, reason))
                return True

            def stop(self, reason=None):
                self.stops.append(reason)
                return True

        robot = mode.Robot.__new__(mode.Robot)
        robot.race_start_gate = RaceStartGate(absence_seconds=1.0)
        robot._race_timer_started = False
        robot.control = Control()
        robot.camera = Mock()
        robot.camera.capture_frame.return_value = (object(), None)
        robot.camera.last_capture_valid = True
        robot._pace_control_loop = Mock()
        observations = iter([
            (False, False, None, None),
            (True, True, 2, 0.1),
            (True, False, 3, 0.2),
            (True, False, 4, 0.8),
            (True, False, 5, 1.21),
        ])

        def handle(*_args, **_kwargs):
            fresh, stop, result_id, at = next(observations)
            robot.last_sign_observation_fresh = fresh
            robot.last_sign_result_id = result_id
            robot.last_sign_observation_at = at
            return None, stop, None, None

        robot.handle_read_sign_or_tag = handle
        with patch.object(mode.time, "monotonic", side_effect=[0.0, 0.1, 0.2, 0.8, 1.21]):
            for _ in range(5):
                robot._run_race_start_gate_cycle()
                if not robot.race_start_gate.released:
                    self.assertTrue(robot.control.motion_inhibited)

        self.assertTrue(robot.race_start_gate.released)
        self.assertFalse(robot.control.motion_inhibited)
        self.assertFalse(robot._race_timer_started)
        self.assertEqual(robot.control.stops, ["race_start_gate"])

    def make_robot(self, label, confidence=0.8, result_id=1):
        from modes.race import race as mode

        class FakeControl:
            def __init__(self):
                self.without_arduino = True
                self.motion_inhibited = False
                self.motion_inhibit_reason = None
                self.stops = []

            def set_motion_inhibited(self, inhibited, reason=None):
                self.motion_inhibited = inhibited
                self.motion_inhibit_reason = reason if inhibited else None
                return True

            def stop(self, reason=None):
                self.stops.append(reason)
                return True

        robot = mode.Robot.__new__(mode.Robot)
        robot.stop_hold = StopSignHold()
        robot.stop_hold_detector_kind = None
        robot.last_sign_observation_fresh = False
        robot.last_sign_observation_at = None
        robot.last_sign_result_id = 0
        robot.last_tag = None
        robot.read_sign_counter = 0
        robot.sign_detector = Mock()
        robot.sign_detector.latest.return_value = (
            result_id,
            {"coordinate": ((0, 0), (40, 40)), "debug_frame": None,
             "text": label, "sign_type": 1 if label == "STOP" else 3,
             "confidence": confidence},
            10.0,
            10.01,
        )
        robot.control = FakeControl()
        robot.race_finish = RaceFinishState(1.0, 25)
        robot.race_finish.start(0.0)
        robot.race_finish.update(1.0)
        robot._last_stop_command_at = None
        robot._last_stop_release_attempt_at = None
        robot._mcu_stop_latched = False
        robot._stop_connection_state = None
        robot._set_race_inhibited = lambda inhibited, reason: mode.Robot._set_race_inhibited(robot, inhibited, reason)
        robot.last_tag = None
        robot._mode_module = mode
        return robot

    def run_phase_result(self, robot, label, threshold=0.2, confidence=0.8,
                         observation_at=None):
        config = robot._mode_module.config_race
        if observation_at is None:
            observation_at = time.monotonic()
        robot.sign_detector.latest.return_value = (
            robot.last_sign_result_id + 1,
            {"coordinate": ((0, 0), (40, 40)), "debug_frame": None,
             "text": label, "sign_type": 1 if label == "STOP" else 3,
             "confidence": confidence},
            observation_at,
            observation_at + 0.01,
        )
        with patch.multiple(
            config,
            WITH_SIGN=True,
            WITH_APRILTAG=False,
            READ_SIGN_THRESHOLD=100,
            ST_TOP_ROI=0.0,
            ST_BOTTOM_ROI=1.0,
            ST_LEFT_ROI=0.0,
            ST_RIGHT_ROI=1.0,
            SIGN_AREA_FILTER_ENABLED=False,
            RACE_STOP_CONFIDENCE_THRESHOLD=threshold,
        ):
            return robot.handle_read_sign_or_tag(
                np.zeros((240, 320, 3), dtype=np.uint8),
                None,
                phase_only="monitor",
            )

    def test_sign_detector_monitors_stop_during_middle_race(self):
        from modes.race import race as mode

        robot = mode.Robot.__new__(mode.Robot)
        robot.sign_detector = Mock()
        robot.handle_read_sign_or_tag = Mock(
            return_value=("STOP", True, None, None)
        )
        frame = object()

        with patch.multiple(
            mode.config_race,
            WITH_SIGN=True,
            WITH_APRILTAG=False,
        ):
            sign_text, debug_frame = mode.Robot._read_stop_sign_if_active(
                robot, frame, None
            )
        self.assertEqual(sign_text, "STOP")
        self.assertIsNone(debug_frame)
        robot.sign_detector.resume.assert_called_once()
        robot.handle_read_sign_or_tag.assert_called_once_with(
            frame, None, force_check=True, phase_only="monitor"
        )

    def test_finish_stop_hold_releases_when_stop_disappears(self):
        robot = self.make_robot("TURN LEFT")
        # This test checks finish-phase STOP observation routing, not the
        # independently tested 3-second StopSignHold timing policy.
        robot.stop_hold.minimum_duration_s = 0.0
        self.run_phase_result(robot, "TURN LEFT")
        self.assertEqual(robot.control.stops, [])

        self.run_phase_result(robot, "STOP")
        self.assertTrue(robot.stop_hold.active)
        self.assertTrue(robot.control.motion_inhibited)

        self.run_phase_result(robot, "TURN RIGHT")
        self.assertTrue(robot._release_stop_hold_if_ready())
        self.assertFalse(robot.stop_hold.active)
        self.assertFalse(robot.control.motion_inhibited)

    def test_stop_below_phase_confidence_threshold_cannot_finish(self):
        robot = self.make_robot("STOP")
        self.run_phase_result(robot, "STOP", threshold=0.7, confidence=0.69)
        self.assertFalse(robot.stop_hold.active)
        self.assertEqual(robot.control.stops, [])

    def test_stop_is_monitored_before_finish_speed_phase(self):
        robot = self.make_robot("STOP")
        self.run_phase_result(robot, "STOP", observation_at=0.5)
        self.assertTrue(robot.stop_hold.active)
        self.assertTrue(robot.control.motion_inhibited)

    def test_async_detector_pause_discards_work_and_resume_reenables_inference(self):
        import threading

        completed = threading.Event()
        calls = []

        class Detector:
            def process_frame(self, frame, debug_frame=None, confidence_threshold=None,
                              target_sign_types=None):
                calls.append(frame)
                completed.set()
                return {"text": ""}

        worker = AsyncSignDetector(Detector())
        try:
            worker.pause()
            self.assertIsNone(worker.submit("middle-race-frame"))
            self.assertTrue(worker.wait_until_idle(timeout=0.2))
            self.assertFalse(completed.is_set())
            self.assertEqual(calls, [])

            worker.resume()
            self.assertIsNotNone(worker.submit("finish-phase-frame"))
            self.assertTrue(completed.wait(2.0))
            worker.pause()
            self.assertTrue(worker.wait_until_idle(timeout=2.0))
            self.assertEqual(calls, ["finish-phase-frame"])
        finally:
            worker.close()

    def test_async_inference_receives_phase_scoped_stop_filter_and_threshold(self):
        import threading

        completed = threading.Event()

        class Detector:
            def process_frame(self, frame, debug_frame=None, confidence_threshold=None,
                              target_sign_types=None):
                self.options = (confidence_threshold, target_sign_types)
                completed.set()
                return {"text": ""}

        detector = Detector()
        worker = AsyncSignDetector(detector)
        try:
            worker.submit(object(), confidence_threshold=0.65, target_sign_types=(1,))
            self.assertTrue(completed.wait(2.0))
            self.assertEqual(detector.options, (0.65, (1,)))
        finally:
            worker.close()


class RacePhaseCliTests(unittest.TestCase):
    def test_options_are_opt_in_and_omitted_tuning_preserves_config(self):
        args = parse_args(["--mode", "race"])
        self.assertFalse(args.race_start_on_stop_sign)
        self.assertIsNone(args.race_stop_absence_seconds)
        self.assertIsNone(args.race_finish_after_seconds)
        config = types.SimpleNamespace(RACE_STOP_ABSENCE_SECONDS=2.0,
                                       RACE_STOP_CONFIDENCE_THRESHOLD=0.4)
        _apply_cli_overrides(config, args)
        self.assertFalse(config.RACE_START_ON_STOP_SIGN)
        self.assertEqual(config.RACE_STOP_ABSENCE_SECONDS, 2.0)
        self.assertEqual(config.RACE_STOP_CONFIDENCE_THRESHOLD, 0.4)

    def test_tuning_overrides_and_city_does_not_get_race_settings(self):
        args = parse_args(["--mode", "race", "--race-start-on-stop-sign",
                           "--race-stop-absence-seconds", "1.5",
                           "--race-stop-confidence-threshold", "0.7"])
        config = types.SimpleNamespace()
        _apply_cli_overrides(config, args)
        self.assertTrue(config.RACE_START_ON_STOP_SIGN)
        self.assertEqual(config.RACE_STOP_ABSENCE_SECONDS, 1.5)
        self.assertEqual(config.RACE_STOP_CONFIDENCE_THRESHOLD, 0.7)

        city = types.SimpleNamespace()
        _apply_cli_overrides(city, parse_args(["--mode", "city"]))
        self.assertFalse(hasattr(city, "RACE_START_ON_STOP_SIGN"))

    def test_cli_rejects_invalid_values_and_unpaired_finish_options(self):
        for flag, value in (("--race-stop-absence-seconds", "-1"),
                            ("--race-stop-confidence-threshold", "1.1"),
                            ("--race-stop-confidence-threshold", "nan"),
                            ("--race-finish-after-seconds", "inf")):
            with self.subTest(flag=flag, value=value), self.assertRaises(SystemExit):
                parse_args(["--mode", "race", flag, value])

        args = parse_args(["--mode", "race", "--race-finish-after-seconds", "10"])
        with self.assertRaisesRegex(SystemExit, "requires --race-finish-speed"):
            _validate_opt_in_features(types.SimpleNamespace(), args)
        args = parse_args(["--mode", "race", "--race-finish-speed", "20"])
        with self.assertRaisesRegex(SystemExit, "requires --race-finish-after-seconds"):
            _validate_opt_in_features(types.SimpleNamespace(), args)


if __name__ == "__main__":
    unittest.main()
