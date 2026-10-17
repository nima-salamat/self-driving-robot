import math
import unittest
from unittest.mock import Mock, patch

from utils.processing_rate import ProcessingRateController
from modes.city.city import Robot as CityRobot
from modes.race.race import Robot as RaceRobot
from modes.city import config_city
from modes.race import config_race


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class ProcessingRateControllerTests(unittest.TestCase):
    def test_waits_only_remaining_interval(self):
        clock = FakeClock()
        limiter = ProcessingRateController(25, clock, clock.sleep)

        self.assertTrue(limiter.wait_for_slot())
        clock.now += 0.012  # capture/preprocess/inference work
        self.assertTrue(limiter.wait_for_slot())

        self.assertAlmostEqual(clock.sleeps[-1], 0.028)
        self.assertAlmostEqual(limiter.last_start, 0.04)

    def test_slow_cycles_do_not_catch_up_or_accumulate_debt(self):
        clock = FakeClock()
        limiter = ProcessingRateController(25, clock, clock.sleep)

        limiter.wait_for_slot()
        clock.now += 0.090
        limiter.wait_for_slot()
        self.assertEqual(len(clock.sleeps), 0)
        self.assertAlmostEqual(limiter.last_start, 0.090)

        clock.now += 0.010
        limiter.wait_for_slot()
        self.assertAlmostEqual(clock.sleeps[-1], 0.030)
        self.assertAlmostEqual(limiter.last_start, 0.130)

    def test_variable_durations_keep_start_spacing_at_or_above_interval(self):
        clock = FakeClock()
        limiter = ProcessingRateController(30, clock, clock.sleep)
        for duration in (0.005, 0.020, 0.050, 0.001, 0.010):
            self.assertTrue(limiter.wait_for_slot())
            started = limiter.last_start
            clock.now += duration
            self.assertTrue(limiter.wait_for_slot())
            self.assertGreaterEqual(
                limiter.last_start - started, 1 / 30 - 1e-9
            )

    def test_live_rate_update_resets_deadline_without_catch_up_debt(self):
        clock = FakeClock()
        limiter = ProcessingRateController(30, clock, clock.sleep)
        self.assertTrue(limiter.wait_for_slot())
        clock.now += 0.010
        self.assertTrue(limiter.wait_for_slot())

        snapshot = limiter.set_target_fps(20)
        self.assertEqual(snapshot["target_fps"], 20)
        self.assertAlmostEqual(limiter.interval, 0.05)
        self.assertIsNone(limiter._next_start)
        self.assertTrue(limiter.wait_for_slot())
        self.assertAlmostEqual(limiter.last_start, clock.now)

    def test_live_rate_update_rejects_out_of_range_values(self):
        limiter = ProcessingRateController(30)
        for rate in (0, -1, 0.5, 60.1, math.inf, math.nan):
            with self.subTest(rate=rate), self.assertRaises(ValueError):
                limiter.set_target_fps(rate)

    def test_rejects_non_positive_and_non_finite_rates(self):
        for rate in (0, -1, math.inf, -math.inf, math.nan):
            with self.subTest(rate=rate), self.assertRaises(ValueError):
                ProcessingRateController(rate)


class ModeProcessingRateIntegrationTests(unittest.TestCase):
    def _assert_mode_uses_configured_rate(self, robot_type, config, module_name):
        robot = robot_type.__new__(robot_type)
        shutdown = object()
        limiter = Mock()
        limiter.wait_for_slot.return_value = True
        target = 17.5
        with patch.object(config, "TARGET_PROCESSING_FPS", target, create=True), \
                patch.object(config, "SHUTDOWN_EVENT", shutdown, create=True), \
                patch.object(config, "processing_rate_controller", None, create=True), \
                patch(f"{module_name}.ProcessingRateController", return_value=limiter) as factory:
            self.assertTrue(robot._wait_for_processing_slot())
            self.assertIs(config.processing_rate_controller, limiter)

        factory.assert_called_once_with(target)
        limiter.wait_for_slot.assert_called_once_with(shutdown)

    def test_city_runtime_uses_configured_rate_controller(self):
        self._assert_mode_uses_configured_rate(
            CityRobot, config_city, "modes.city.city"
        )

    def test_race_runtime_uses_configured_rate_controller(self):
        self._assert_mode_uses_configured_rate(
            RaceRobot, config_race, "modes.race.race"
        )


if __name__ == "__main__":
    unittest.main()
