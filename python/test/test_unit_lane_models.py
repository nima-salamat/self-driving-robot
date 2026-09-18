import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from vision.ml_lane.detector import MLLaneDetector, create_ml_lane_detector
from vision.ml_lane.registry import list_models


class FakeMat:
    def __init__(self, value):
        self.value = value


class FakeNet:
    def __init__(self):
        self.opt = types.SimpleNamespace(use_vulkan_compute=False, num_threads=0)

    def load_param(self, _path):
        return 0

    def load_model(self, _path):
        return 0

    def create_extractor(self):
        return self

    def input(self, _name, _mat):
        return 0

    def extract(self, _name):
        output = np.ones((256, 256), dtype=np.float32)
        output[150:256, 70:80] = 0.0
        output[150:256, 176:186] = 0.0
        return 0, output


class LaneModelTests(unittest.TestCase):
    def test_registry_contains_two_candidates(self):
        names = [spec.name for spec in list_models()]
        self.assertEqual(names, ["unet_depthwise_nano", "unet_depthwise_small"])

    def test_ml_detector_disabled_by_default(self):
        class Config:
            USE_ML_LANE_DETECTOR = False

        self.assertIsNone(create_ml_lane_detector(Config()))

    @patch("vision.ml_lane.detector.ensure_model_materialized")
    def test_unet_detector_returns_common_result(self, ensure_assets):
        ensure_assets.return_value = (
            Path("nano.param"),
            Path("nano.bin"),
        )
        fake_ncnn = types.SimpleNamespace(
            Net=FakeNet,
            Mat=FakeMat,
        )

        with patch.dict(sys.modules, {"ncnn": fake_ncnn}):
            detector = MLLaneDetector("unet_depthwise_nano", cpu_threads=4)

        frame = np.zeros((230, 380, 3), dtype=np.uint8)
        result = detector.detect(frame)

        self.assertEqual(result["ml_model"], "unet_depthwise_nano")
        self.assertTrue(result["perception_valid"])
        self.assertEqual(result["lane_type"], "both")
        self.assertIn("ml_latency_ms", result)
        self.assertEqual(detector.net.opt.num_threads, 4)


if __name__ == "__main__":
    unittest.main()
