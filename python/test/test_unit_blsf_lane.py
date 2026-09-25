import sys
import types
import unittest
from pathlib import Path

import numpy as np

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from vision.blsf_lane.detector import BLSFLaneDetector


class BLSFLaneDetectorTests(unittest.TestCase):
    class Config:
        USE_BEV = False
        DEBUG = False
        STREAM = False
        CW_OLD_METHOD = True
        CW_TRAPEZOID_MODE = False
        CROSSWALK_THRESHOLD = 180
        CW_TOP_ROI = 0.8
        CW_BOTTOM_ROI = 1.0
        CW_LEFT_ROI = 0.3
        CW_RIGHT_ROI = 0.9
        SERVO_CENTER = 90
        MIN_SERVO_ANGLE = 55
        MAX_SERVO_ANGLE = 125

    def test_empty_frame_returns_common_result(self):
        detector = BLSFLaneDetector(self.Config())
        result = detector.detect(
            np.zeros((120, 160, 3), dtype=np.uint8)
        )

        self.assertFalse(result["perception_valid"])
        self.assertEqual(result["lane_type"], "none")
        self.assertEqual(result["lane_detector"], "blsf-beta")
        self.assertIn("crosswalk", result)

    def test_weighted_grayscale(self):
        frame = np.zeros((1, 1, 3), dtype=np.uint8)
        frame[0, 0] = (10, 20, 30)

        gray = BLSFLaneDetector._weighted_gray(frame)

        self.assertEqual(
            int(gray[0, 0]),
            int(0.1 * 10 + 0.4 * 20 + 0.5 * 30),
        )

    def test_ransac_recovers_quadratic_lane(self):
        detector = BLSFLaneDetector(self.Config())
        y = np.linspace(0, 100, 60)
        x = 0.002 * y * y + 0.1 * y + 40
        points = np.column_stack((x, y))

        coeff = detector._ransac_parabola(points)

        self.assertIsNotNone(coeff)
        self.assertAlmostEqual(coeff[0], 0.002, places=3)
        self.assertAlmostEqual(coeff[1], 0.1, places=2)
        self.assertAlmostEqual(coeff[2], 40, places=1)


if __name__ == "__main__":
    unittest.main()
