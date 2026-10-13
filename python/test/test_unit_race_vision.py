import sys
import unittest
from pathlib import Path

import numpy as np

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from vision.race_vision_processing import VisionProcessor


class RaceVisionLaneLossTests(unittest.TestCase):
    def test_no_lane_result_preserves_last_steering_angle(self):
        processor = VisionProcessor()
        processor.last_steering = 116
        blank_frame = np.zeros((230, 380, 3), dtype=np.uint8)

        result = processor.detect(blank_frame)

        self.assertEqual(result["lane_type"], "none")
        self.assertFalse(result["perception_valid"])
        self.assertEqual(result["steering_angle"], 116)


if __name__ == "__main__":
    unittest.main()
