import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))


class HoughParameterTests(unittest.TestCase):
    def _assert_mode_reads_runtime_hough_parameters(self, config, processor_class):
        values = {
            "DEBUG": True,
            "STREAM": False,
            "USE_BEV": False,
            "OLD_METHOD": False,
            "LANE_THRESHOLD": 111,
            "HOUGH_THRESHOLD": 31,
            "HOUGH_MIN_LINE_LENGTH": 23,
            "HOUGH_MAX_LINE_GAP": 7,
            "HOUGH_BLUR_KERNEL": 3,
            "HOUGH_MORPH_CLOSE": True,
        }
        with patch.multiple(config, create=True, **values), patch.object(
            cv2, "HoughLinesP", return_value=None
        ) as hough:
            processor = processor_class()
            frame = np.zeros((230, 380, 3), dtype=np.uint8)
            result = processor.detect(frame, frame.copy())

        self.assertEqual(result["lane_type"], "none")
        self.assertEqual(hough.call_count, 2)
        for call in hough.call_args_list:
            self.assertEqual(call.kwargs["threshold"], 31)
            self.assertEqual(call.kwargs["minLineLength"], 23)
            self.assertEqual(call.kwargs["maxLineGap"], 7)

    def test_race_reads_hough_parameters_from_config(self):
        from modes.race import config_race
        from vision.race_vision_processing import VisionProcessor

        self._assert_mode_reads_runtime_hough_parameters(config_race, VisionProcessor)

    def test_city_reads_hough_parameters_from_config(self):
        from modes.city import config_city
        from vision.city_vision_processing import VisionProcessor

        self._assert_mode_reads_runtime_hough_parameters(config_city, VisionProcessor)


if __name__ == "__main__":
    unittest.main()
