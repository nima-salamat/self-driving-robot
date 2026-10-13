import sys
import unittest
from types import SimpleNamespace

import cv2
import numpy as np

sys.path.insert(0, "python")

from vision.traffic_light import GreenConfirmationWindow, TrafficLightDetector


def config(**overrides):
    values = dict(
        TL_TOP_ROI=0.0, TL_BOTTOM_ROI=1.0, TL_LEFT_ROI=0.0, TL_RIGHT_ROI=1.0,
        TL_RED_HSV_RANGES=(((0, 100, 100), (10, 255, 255)), ((170, 100, 100), (180, 255, 255))),
        TL_GREEN_HSV_RANGES=(((40, 50, 50), (90, 255, 255)),),
        TL_MIN_SATURATION=50, TL_MIN_VALUE=50, TL_MIN_CONTOUR_AREA=5,
        TL_MIN_ACTIVE_BRIGHTNESS=180, DEBUG=False,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


class TrafficLightDetectorTests(unittest.TestCase):
    def setUp(self):
        self.detector = TrafficLightDetector(config())

    def frame(self, bgr):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        cv2.circle(frame, (50, 50), 15, bgr, -1)
        return frame

    def test_detects_red_and_green(self):
        self.assertEqual(self.detector.detect(self.frame((0, 0, 255)))[0], "RED")
        self.assertEqual(self.detector.detect(self.frame((0, 255, 0)))[0], "GREEN")

    def test_no_signal_and_dim_signal_are_unknown(self):
        self.assertIsNone(self.detector.detect(np.zeros((100, 100, 3), np.uint8))[0])
        self.assertIsNone(self.detector.detect(self.frame((0, 0, 70)))[0])

    def test_conflicting_red_and_green_evidence_is_unknown(self):
        frame = self.frame((0, 0, 255))
        cv2.circle(frame, (20, 20), 10, (0, 255, 0), -1)
        self.assertIsNone(self.detector.detect(frame)[0])

    def test_red_hue_wraparound(self):
        hsv = np.zeros((100, 100, 3), np.uint8)
        cv2.circle(hsv, (50, 50), 15, (179, 255, 255), -1)
        bgr = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        self.assertEqual(self.detector.detect(bgr)[0], "RED")

    def test_roi_excludes_pixels_outside_region(self):
        roi_config = config(TL_TOP_ROI=0.5, TL_BOTTOM_ROI=1.0, TL_LEFT_ROI=0.5, TL_RIGHT_ROI=1.0)
        detector = TrafficLightDetector(roi_config)
        frame = np.zeros((100, 100, 3), np.uint8)
        cv2.circle(frame, (20, 20), 15, (0, 255, 0), -1)
        self.assertIsNone(detector.detect(frame)[0])

    def test_invalid_roi_is_unknown(self):
        detector = TrafficLightDetector(config(TL_TOP_ROI=0.9, TL_BOTTOM_ROI=0.2))
        self.assertIsNone(detector.detect(self.frame((0, 255, 0)))[0])

    def test_legacy_tuple_contract(self):
        result = self.detector.detect(self.frame((0, 255, 0)))
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)


class GreenConfirmationWindowTests(unittest.TestCase):
    def test_one_or_seven_green_observations_do_not_confirm(self):
        gate = GreenConfirmationWindow(10, 8)
        self.assertFalse(gate.observe("GREEN", 1))
        for token in range(2, 8):
            self.assertFalse(gate.observe("GREEN", token))
        self.assertEqual(gate.green_count, 7)

    def test_eight_of_ten_confirm_only_with_newest_green(self):
        gate = GreenConfirmationWindow(10, 8)
        for token in range(1, 9):
            confirmed = gate.observe("GREEN", token)
        self.assertTrue(confirmed)
        self.assertFalse(gate.observe("RED", 9))
        self.assertFalse(gate.confirmed)

    def test_duplicate_frame_does_not_inflate_count(self):
        gate = GreenConfirmationWindow(10, 8)
        gate.observe("GREEN", "frame-1")
        gate.observe("GREEN", "frame-1")
        self.assertEqual(gate.green_count, 1)

    def test_unknown_and_old_window_do_not_authorize_next_cycle(self):
        gate = GreenConfirmationWindow(10, 8)
        for token in range(10):
            gate.observe("GREEN", token)
        self.assertTrue(gate.confirmed)
        gate.reset()
        self.assertFalse(gate.confirmed)
        for token in range(10, 17):
            gate.observe("GREEN", token)
        self.assertFalse(gate.observe(None, 17))
        self.assertFalse(gate.confirmed)

    def test_red_or_unknown_newest_observation_never_confirms(self):
        for latest in ("RED", None, "AMBIGUOUS"):
            gate = GreenConfirmationWindow(10, 8)
            for token in range(7):
                gate.observe("GREEN", token)
            gate.observe(latest, 7)
            self.assertFalse(gate.confirmed)


if __name__ == "__main__":
    unittest.main()
