"""Dependency-light matching and area checks for runtime sign detections."""

import math
import numbers
import re

from train_sign_detector.labels import SIGN_LABELS


_RECOGNIZED_LABELS = {
    class_id: name for class_id, name in SIGN_LABELS.items() if class_id != 0
}
_LABEL_TO_ID = {name: class_id for class_id, name in _RECOGNIZED_LABELS.items()}


def normalize_sign_name(value):
    """Return a case and whitespace normalized name, or an empty string."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value.strip()).upper()


def validate_sign_area_filter(name, value):
    """Validate one area-filter setting using detector label contracts."""
    if name == "SIGN_AREA_FILTER_ENABLED":
        if not isinstance(value, bool):
            raise ValueError("SIGN_AREA_FILTER_ENABLED must be boolean")
    elif name == "SIGN_AREA_MIN_PX2":
        if (
            not isinstance(value, numbers.Real)
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError("SIGN_AREA_MIN_PX2 must be a finite non-negative number")
    elif name == "SIGN_AREA_FILTER_TARGETS":
        if not isinstance(value, list):
            raise ValueError("SIGN_AREA_FILTER_TARGETS must be a list")
        for target in value:
            if isinstance(target, bool):
                raise ValueError("sign area filter targets cannot be booleans")
            if isinstance(target, numbers.Integral):
                if int(target) not in _RECOGNIZED_LABELS:
                    raise ValueError(
                        "sign area filter numeric targets must be detector class IDs 1 through 5"
                    )
            elif isinstance(target, str):
                normalized = normalize_sign_name(target)
                if normalized not in _LABEL_TO_ID:
                    raise ValueError(
                        f"unsupported sign area filter target: {target!r}"
                    )
            else:
                raise ValueError(
                    "sign area filter targets must be detector class IDs or sign names"
                )
    return value


def bounding_box_area(coordinate):
    """Return box area in square pixels; malformed or degenerate boxes are None."""
    try:
        (x1, y1), (x2, y2) = coordinate
        values = (x1, y1, x2, y2)
        if any(
            isinstance(value, bool)
            or not isinstance(value, numbers.Real)
            or not math.isfinite(value)
            for value in values
        ):
            return None
        width = abs(x2 - x1)
        height = abs(y2 - y1)
        area = width * height
        return area if area > 0 and math.isfinite(area) else None
    except (TypeError, ValueError, OverflowError):
        return None


def accepts_sign_detection(
    sign_result,
    *,
    enabled,
    targets,
    minimum_area_px2,
):
    """Check target-specific area filtering against detector text/class IDs.

    The shared detector contract uses IDs 1..5 from ``SIGN_LABELS``. YOLO's
    zero-based model classes are converted to these IDs in its result; SVM
    results use the same label IDs directly. Operational/AprilTag IDs are
    mode-specific and are intentionally not used here.
    """
    if not enabled or not targets:
        return True

    text = normalize_sign_name(sign_result.get("text", ""))
    class_id = sign_result.get("sign_type")
    numeric_id = (
        int(class_id)
        if isinstance(class_id, numbers.Integral) and not isinstance(class_id, bool)
        else None
    )

    is_target = any(
        (
            normalize_sign_name(target) == text
            if isinstance(target, str)
            else numeric_id == target
        )
        for target in targets
    )
    if not is_target:
        return True

    area = bounding_box_area(sign_result.get("coordinate"))
    return area is not None and area > minimum_area_px2
