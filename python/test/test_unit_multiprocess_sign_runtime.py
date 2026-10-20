import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from modes.city import city as city_module
from modes.race import race as race_module


class MultiprocessSignCadenceTests(unittest.TestCase):
    def _robot(self, module):
        robot = module.Robot.__new__(module.Robot)
        robot.metrics = None
        robot.sign_detector = Mock()
        robot.sign_detector.latest.return_value = None
        robot.read_sign_counter = 0
        robot.last_sign_result_id = 0
        robot.last_sign_observation_fresh = False
        robot.last_sign_observation_at = None
        robot.last_tag = None
        robot.stop_hold = SimpleNamespace(active=False)
        robot.stop_hold_detector_kind = None
        robot._observe_stop_result = Mock()
        return robot

    def _assert_every_loop_frame_is_submitted(self, module, config, race=False):
        robot = self._robot(module)
        frame = np.zeros((120, 160, 3), dtype=np.uint8)
        patches = [
            patch.object(config, "MULTIPROCESS_SIGN_DETECTOR", True, create=True),
            patch.object(config, "WITH_SIGN", True),
            patch.object(config, "WITH_APRILTAG", False),
            patch.object(config, "READ_SIGN_THRESHOLD", 100),
            patch.object(config, "ST_TOP_ROI", 0.0),
            patch.object(config, "ST_BOTTOM_ROI", 1.0),
            patch.object(config, "ST_LEFT_ROI", 0.0),
            patch.object(config, "ST_RIGHT_ROI", 1.0),
        ]
        if race:
            patches.append(patch.object(config, "SIGN_RESULT_MAX_AGE", 0.75, create=True))
        entered = []
        try:
            for p in patches:
                entered.append(p)
                p.start()
            robot.handle_read_sign_or_tag(frame, None)
        finally:
            for p in reversed(entered):
                p.stop()

        robot.sign_detector.submit.assert_called_once()
        submitted_frame = robot.sign_detector.submit.call_args.args[0]
        self.assertEqual(submitted_frame.shape, frame.shape)
        self.assertEqual(robot.read_sign_counter, 0)

    def test_city_multiprocess_signs_bypass_read_sign_threshold(self):
        self._assert_every_loop_frame_is_submitted(
            city_module, city_module.config_city
        )

    def test_race_multiprocess_signs_bypass_read_sign_threshold(self):
        self._assert_every_loop_frame_is_submitted(
            race_module, race_module.config_race, race=True
        )


if __name__ == "__main__":
    unittest.main()
