"""Unit tests for Stream vision settings validation."""
from types import SimpleNamespace
import pytest
from stream.vision_api import StreamVisionMixin


def api(mode="city"):
    value=object.__new__(StreamVisionMixin)
    value.config=SimpleNamespace(MODE=mode)
    return value


def test_hough_validation_and_odd_blur():
    assert api()._normalize_vision_settings({"HOUGH_THRESHOLD":31,"HOUGH_BLUR_KERNEL":5,"HOUGH_MORPH_CLOSE":False})=={"HOUGH_THRESHOLD":31,"HOUGH_BLUR_KERNEL":5,"HOUGH_MORPH_CLOSE":False}
    with pytest.raises(ValueError,match="odd integer"):
        api()._normalize_vision_settings({"HOUGH_BLUR_KERNEL":4})


def test_blsf_settings_are_city_only_and_kernel_is_odd():
    assert api()._normalize_vision_settings({"BLSF_MEDIAN_KERNEL":11})["BLSF_MEDIAN_KERNEL"]==11
    with pytest.raises(ValueError,match="odd integer"):
        api()._normalize_vision_settings({"BLSF_MEDIAN_KERNEL":8})
    with pytest.raises(ValueError,match="unknown vision setting"):
        api("race")._normalize_vision_settings({"BLSF_MIN_SEGMENT_LENGTH":20})


def test_detector_selection_and_sign_filter_contracts():
    assert api()._normalize_vision_settings({"CITY_LANE_DETECTOR":"blsf-beta"})["CITY_LANE_DETECTOR"]=="blsf-beta"
    with pytest.raises(ValueError,match="City lane detector"):
        api()._normalize_vision_settings({"CITY_LANE_DETECTOR":"bad"})
    valid=api("race")._normalize_vision_settings({"SIGN_AREA_FILTER_ENABLED":True,"SIGN_AREA_FILTER_TARGETS":["STOP"],"SIGN_AREA_MIN_PX2":900})
    assert valid["SIGN_AREA_FILTER_ENABLED"] is True
    with pytest.raises(ValueError,match="must be boolean"):
        api("race")._normalize_vision_settings({"SIGN_AREA_FILTER_ENABLED":"true"})
    with pytest.raises(ValueError):
        api("race")._normalize_vision_settings({"SIGN_AREA_FILTER_TARGETS":["UNKNOWN"]})
