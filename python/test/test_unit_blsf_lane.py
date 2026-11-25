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
        SERVO_CENTER = 95
        MIN_SERVO_ANGLE = 55
        MAX_SERVO_ANGLE = 125

    def test_empty_frame_returns_common_result(self):
        detector = BLSFLaneDetector(self.Config())
        result = detector.detect(
            np.zeros((120, 160, 3), dtype=np.uint8)
        )

        self.assertIsNone(result["debug"])
        self.assertFalse(result["perception_valid"])
        self.assertEqual(result["lane_type"], "none")
        self.assertEqual(result["lane_detector"], "blsf-beta")
        self.assertIn("crosswalk", result)

    def test_missing_lane_preserves_last_steering_angle(self):
        detector = BLSFLaneDetector(self.Config())
        detector.last_steering = 111.0

        angle, error = detector._steering(None, "none", 160)

        self.assertEqual(angle, 111)
        self.assertEqual(error, 0.0)

    def test_active_maneuver_roi_crops_the_requested_window_and_reports_line_lock(self):
        class ManeuverConfig(self.Config):
            SIMULATOR_ACTIVE_OBSTACLE_ROI = "left"
            ML_TOP_ROI = 0.25
            ML_BOTTOM_ROI = 0.75
            ML_LEFT_ROI = 0.10
            ML_RIGHT_ROI = 0.50

        detector = BLSFLaneDetector(ManeuverConfig())
        seen_shapes = []
        detector._weighted_gray = lambda crop: (
            seen_shapes.append(crop.shape) or np.zeros(crop.shape[:2], dtype=np.uint8)
        )
        detector._median_local_threshold = lambda gray: gray
        detector._segments = lambda _binary: []
        detector._blsf_band = lambda _segments: (None, 0)
        detector._blsf_binary = lambda thresholded, _segments, _band: thresholded
        detector._seeds = lambda binary: (
            None, None, np.zeros(binary.shape[1], dtype=np.int32)
        )
        detector._track = lambda _binary, _seed, _window: np.empty((0, 2))
        detector._ransac_parabola = lambda _points: None
        detector._lane_state = lambda _left, _right, width, _height: (
            width / 2.0, "only_left", width / 2.0, None
        )
        detector._steering = lambda _center, _lane_type, _width: (95, 0.0)
        detector._detect_crosswalk = lambda _frame: self.fail(
            "Crosswalk detection must not run against a cropped maneuver ROI"
        )

        result = detector.detect(np.zeros((120, 160, 3), dtype=np.uint8))

        self.assertEqual(seen_shapes, [(60, 64, 3)])
        self.assertTrue(result["perception_valid"])
        self.assertEqual(result["maneuver_roi"], {"side": "left", "observed": True})


    def test_weighted_grayscale(self):
        frame = np.zeros((1, 1, 3), dtype=np.uint8)
        frame[0, 0] = (10, 20, 30)

        gray = BLSFLaneDetector._weighted_gray(frame)

        self.assertEqual(
            int(gray[0, 0]),
            int(0.1 * 10 + 0.4 * 20 + 0.5 * 30),
        )

    def test_segments_normalizes_supported_opencv_line_shapes(self):
        detector = BLSFLaneDetector(self.Config())
        canonical = np.array(
            [
                [[10.0, 100.0, 20.0, 70.0]],
                [[30.0, 100.0, 40.0, 70.0]],
            ],
            dtype=np.float32,
        )
        shapes = (
            canonical,                       # OpenCV's common (N, 1, 4)
            canonical.reshape(-1, 4),        # (N, 4)
            canonical.reshape(1, 2, 1, 4),   # wrapped singleton dimensions
        )
        binary = np.zeros((120, 160), dtype=np.uint8)

        for raw_lines in shapes:
            with self.subTest(shape=raw_lines.shape):
                detector._lsd = types.SimpleNamespace(
                    detect=lambda _binary, lines=raw_lines: (
                        lines,
                        None,
                        None,
                        None,
                    )
                )
                segments = detector._segments(binary)
                self.assertEqual(len(segments), 2)
                self.assertEqual(len(segments[0]), 6)

    def test_segments_ignore_empty_malformed_and_nonfinite_line_outputs(self):
        detector = BLSFLaneDetector(self.Config())
        binary = np.zeros((120, 160), dtype=np.uint8)
        invalid_outputs = (
            None,
            np.asarray([], dtype=np.float32),
            np.float32(1.0),
            np.asarray([1.0, 2.0, 3.0], dtype=np.float32),
            np.asarray([[np.nan, 10.0, 20.0, 30.0]], dtype=np.float32),
        )

        for raw_lines in invalid_outputs:
            with self.subTest(output=repr(raw_lines)):
                detector._lsd = types.SimpleNamespace(
                    detect=lambda _binary, lines=raw_lines: (
                        lines,
                        None,
                        None,
                        None,
                    )
                )
                self.assertEqual(detector._segments(binary), [])

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
