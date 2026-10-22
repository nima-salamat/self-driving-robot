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


    def test_live_vision_debug_marks_old_and_recent_snapshots(self):
        import time
        from flask import Flask

        app = Flask(__name__)
        for age_seconds, expected in ((2.0, "stale"), (0.02, "fresh")):
            api = self.api()
            api.config.stream_vision_debug_snapshot = {
                "mode": "city",
                "timestamp": time.time() - age_seconds,
                "monotonic_at": time.monotonic() - age_seconds,
                "result": {"lane_type": "none"},
                "debug": {},
            }
            api.config.stream_vision_debug_lock = None
            with app.test_request_context("/api/vision/live"):
                response = api.live_vision_debug_api()
                payload = response.get_json()
            self.assertFalse(payload["available"])
            self.assertEqual(payload["summary"]["freshness"], expected)
            self.assertGreaterEqual(payload["summary"]["age_ms"], 0)
            self.assertEqual(payload["summary"]["stale_after_ms"], 1500.0)

    def test_vision_preview_exposes_candidates_without_actuating_robot(self):
        import base64
        import cv2
        import numpy as np
        from flask import Flask

        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.line(frame, (145, 82), (60, 238), (255, 255, 255), 5)
        cv2.line(frame, (175, 82), (260, 238), (255, 255, 255), 5)
        ok, encoded = cv2.imencode(".jpg", frame)
        self.assertTrue(ok)
        module = SimpleNamespace(
            USE_BEV=False, OLD_METHOD=False, LANE_ROI_MODE="rectangle",
            LL_TOP_ROI=0.25, LL_BOTTOM_ROI=1.0, LL_LEFT_ROI=0.0, LL_RIGHT_ROI=0.5,
            RL_TOP_ROI=0.25, RL_BOTTOM_ROI=1.0, RL_LEFT_ROI=0.5, RL_RIGHT_ROI=1.0,
        )
        settings = {
            "LANE_THRESHOLD": 25,
            "HOUGH_THRESHOLD": 4,
            "HOUGH_MIN_LINE_LENGTH": 8,
            "HOUGH_MAX_LINE_GAP": 12,
            "HOUGH_BLUR_KERNEL": 3,
            "HOUGH_MORPH_CLOSE": False,
            "CITY_LANE_DETECTOR": "default",
        }
        api = self.api()
        api._vision_mode_module = lambda: module
        api._vision_tuning_snapshot = lambda: dict(settings)
        data_url = "data:image/jpeg;base64," + base64.b64encode(encoded.tobytes()).decode("ascii")
        app = Flask(__name__)
        with app.test_request_context("/api/vision/preview", method="POST", json={"image": data_url}):
            response = api.vision_preview_api()
            payload = response.get_json()
        self.assertTrue(payload["success"], payload)
        self.assertFalse(payload["summary"]["motion_commands_sent"])
        self.assertIn("candidates", payload["stages"])
        self.assertIn("left_edges", payload["stages"])
        self.assertIn("right_edges", payload["stages"])
        self.assertGreater(payload["summary"]["candidate_count_left"], 0)
        self.assertGreater(payload["summary"]["candidate_count_right"], 0)
        self.assertIn("Green = Hough candidates", payload["summary"]["preview_note"])

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
