"""Unit tests for Stream vision settings validation."""
from types import SimpleNamespace
import unittest

from stream.vision_api import StreamVisionMixin


class StreamVisionSettingsTests(unittest.TestCase):
    def api(self, mode="city"):
        value = object.__new__(StreamVisionMixin)
        value.config = SimpleNamespace(MODE=mode)
        value._mode_slug = lambda: mode
        return value

    def test_hough_validation_and_odd_blur(self):
        clean = self.api()._normalize_vision_settings({
            "HOUGH_THRESHOLD": 31,
            "HOUGH_BLUR_KERNEL": 5,
            "HOUGH_MORPH_CLOSE": False,
        })
        self.assertEqual(clean, {
            "HOUGH_THRESHOLD": 31,
            "HOUGH_BLUR_KERNEL": 5,
            "HOUGH_MORPH_CLOSE": False,
        })
        with self.assertRaisesRegex(ValueError, "odd integer"):
            self.api()._normalize_vision_settings({"HOUGH_BLUR_KERNEL": 4})

    def test_blsf_settings_are_city_only_and_kernel_is_odd(self):
        self.assertEqual(self.api()._normalize_vision_settings({"BLSF_MEDIAN_KERNEL": 11})["BLSF_MEDIAN_KERNEL"], 11)
        with self.assertRaisesRegex(ValueError, "odd integer"):
            self.api()._normalize_vision_settings({"BLSF_MEDIAN_KERNEL": 8})
        with self.assertRaisesRegex(ValueError, "unknown vision setting"):
            self.api("race")._normalize_vision_settings({"BLSF_MIN_SEGMENT_LENGTH": 20})

    def test_detector_selection_and_sign_filter_contracts(self):
        self.assertEqual(self.api()._normalize_vision_settings({"CITY_LANE_DETECTOR": "blsf-beta"})["CITY_LANE_DETECTOR"], "blsf-beta")
        with self.assertRaisesRegex(ValueError, "City lane detector"):
            self.api()._normalize_vision_settings({"CITY_LANE_DETECTOR": "bad"})
        valid = self.api("race")._normalize_vision_settings({
            "SIGN_AREA_FILTER_ENABLED": True,
            "SIGN_AREA_FILTER_TARGETS": ["STOP"],
            "SIGN_AREA_MIN_PX2": 900,
        })
        self.assertIs(valid["SIGN_AREA_FILTER_ENABLED"], True)
        with self.assertRaisesRegex(ValueError, "must be boolean"):
            self.api("race")._normalize_vision_settings({"SIGN_AREA_FILTER_ENABLED": "true"})
        with self.assertRaises(ValueError):
            self.api("race")._normalize_vision_settings({"SIGN_AREA_FILTER_TARGETS": ["UNKNOWN"]})


if __name__ == "__main__":
    unittest.main()
