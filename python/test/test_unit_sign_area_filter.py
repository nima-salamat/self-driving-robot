import sys
import json
import tempfile
import types
import unittest

sys.path.insert(0, "python")

from traffic_sign_detector.area_filter import (
    accepts_sign_detection,
    bounding_box_area,
)
from utils.json_config import _load_into, _validate


class SignAreaFilterTests(unittest.TestCase):
    def detection(self, *, text="STOP", class_id=1, coordinate=((0, 0), (11, 10))):
        return {"text": text, "sign_type": class_id, "coordinate": coordinate}

    def accepts(self, result, *, enabled=True, targets=None, threshold=100):
        return accepts_sign_detection(
            result,
            enabled=enabled,
            targets=["STOP"] if targets is None else targets,
            minimum_area_px2=threshold,
        )

    def test_target_above_threshold_is_accepted(self):
        self.assertTrue(self.accepts(self.detection(coordinate=((0, 0), (11, 10)))))

    def test_target_equal_to_or_below_threshold_is_rejected(self):
        self.assertFalse(self.accepts(self.detection(coordinate=((0, 0), (10, 10)))))
        self.assertFalse(self.accepts(self.detection(coordinate=((0, 0), (9, 10)))))

    def test_non_target_is_unaffected(self):
        self.assertTrue(
            self.accepts(
                self.detection(text="PARK", class_id=5, coordinate=((0, 0), (1, 1)))
            )
        )

    def test_name_matching_normalizes_case_and_whitespace(self):
        self.assertTrue(
            self.accepts(
                self.detection(text="  stop  ", coordinate=((0, 0), (11, 10))),
                targets=["  sToP  "],
            )
        )

    def test_numeric_targets_use_detector_ids(self):
        self.assertFalse(
            self.accepts(
                self.detection(text="STOP", class_id=1, coordinate=((0, 0), (1, 1))),
                targets=[1],
            )
        )
        self.assertTrue(
            self.accepts(
                self.detection(text="STOP", class_id=5, coordinate=((0, 0), (1, 1))),
                targets=[1],
            )
        )

    def test_disabled_or_empty_filter_preserves_detection(self):
        small = self.detection(coordinate=((0, 0), (1, 1)))
        self.assertTrue(self.accepts(small, enabled=False))
        self.assertTrue(self.accepts(small, targets=[]))

    def test_missing_malformed_and_degenerate_boxes_reject_targets(self):
        for coordinate in (None, [], ((0, 0),), ((0, 0), (0, 4)), ((0, 0), (float("nan"), 1)), "bad"):
            with self.subTest(coordinate=coordinate):
                self.assertFalse(
                    self.accepts(self.detection(coordinate=coordinate), threshold=0)
                )
        self.assertIsNone(bounding_box_area(((0, 0), (float("inf"), 2))))

    def test_invalid_configuration_is_rejected(self):
        invalid = (
            ("SIGN_AREA_FILTER_ENABLED", 1),
            ("SIGN_AREA_MIN_PX2", True),
            ("SIGN_AREA_MIN_PX2", -1),
            ("SIGN_AREA_MIN_PX2", float("nan")),
            ("SIGN_AREA_FILTER_TARGETS", "STOP"),
            ("SIGN_AREA_FILTER_TARGETS", [True]),
            ("SIGN_AREA_FILTER_TARGETS", [0]),
            ("SIGN_AREA_FILTER_TARGETS", [6]),
            ("SIGN_AREA_FILTER_TARGETS", [" "]),
            ("SIGN_AREA_FILTER_TARGETS", ["unknown"]),
            ("SIGN_AREA_FILTER_TARGETS", [1.0]),
        )
        for name, value in invalid:
            with self.subTest(name=name, value=value):
                with self.assertRaises(ValueError):
                    _validate(name, value)

    def test_valid_mixed_targets_pass_validation(self):
        self.assertEqual(
            _validate("SIGN_AREA_FILTER_TARGETS", [" stop ", 2]),
            [" stop ", 2],
        )

    def test_json_overlay_loads_mode_filter_settings(self):
        config = types.SimpleNamespace(PID_MIN_DT=0.001, PID_MAX_DT=0.2)
        settings = {
            "SIGN_AREA_FILTER_ENABLED": False,
            "SIGN_AREA_FILTER_TARGETS": [" turn left ", 3],
            "SIGN_AREA_MIN_PX2": 123.5,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/mode.json"
            with open(path, "w", encoding="utf-8") as file:
                json.dump(settings, file)
            _load_into(config, path)
        self.assertFalse(config.SIGN_AREA_FILTER_ENABLED)
        self.assertEqual(config.SIGN_AREA_FILTER_TARGETS, [" turn left ", 3])
        self.assertEqual(config.SIGN_AREA_MIN_PX2, 123.5)


if __name__ == "__main__":
    unittest.main()
