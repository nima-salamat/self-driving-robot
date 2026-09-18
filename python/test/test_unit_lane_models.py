import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from vision.ml_lane.detector import MLLaneDetector, create_ml_lane_detector
from vision.ml_lane.registry import list_models


class FakeNet:
    def __init__(self):
        self.inputs = []

    def setPreferableBackend(self, _value):
        pass

    def setPreferableTarget(self, _value):
        pass

    def getUnconnectedOutLayersNames(self):
        return ["out0"]

    def setInput(self, blob):
        self.inputs.append(blob)

    def forward(self):
        return np.ones((1, 1, 256, 256), dtype=np.float32)


class LaneModelTests(unittest.TestCase):
    def test_registry_contains_three_candidates(self):
        names = [spec.name for spec in list_models()]
        self.assertEqual(
            names,
            [
                "unet_depthwise_nano",
                "unet_depthwise_small",
            ],
        )

    def test_ml_detector_disabled_by_default(self):
        class Config:
            USE_ML_LANE_DETECTOR = False

        self.assertIsNone(create_ml_lane_detector(Config()))

    @patch("vision.ml_lane.detector.cv2.dnn.readNetFromONNX", return_value=FakeNet())
    @patch("vision.ml_lane.detector.Path.exists", return_value=True)
    def test_unet_detector_returns_common_result(self, _exists, _load):
        detector = MLLaneDetector("unet_depthwise_nano")
        frame = np.zeros((230, 380, 3), dtype=np.uint8)
        result = detector.detect(frame)
        self.assertIn("steering_angle", result)
        self.assertIn("error", result)
        self.assertIn("lane_type", result)
        self.assertIn("perception_valid", result)
        self.assertEqual(result["ml_model"], "unet_depthwise_nano")

if __name__ == "__main__":
    unittest.main()
