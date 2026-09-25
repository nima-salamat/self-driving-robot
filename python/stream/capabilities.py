"""Runtime capability metadata for the active robot mode."""

from __future__ import annotations

from typing import Any

MODE_CAPABILITIES = {
    "city": {
        "lane_detectors": ("default", "blsf-beta"),
        "supports_ml_lane": False,
        "supports_bev": True,
        "supports_lane_roi": True,
        "supports_crosswalk": True,
        "supports_crosswalk_trapezoid": True,
        "supports_sign": True,
        "supports_apriltag": True,
        "supports_object_detection": True,
        "supports_recording": True,
    },
    "race": {
        "lane_detectors": ("default", "ml"),
        "supports_ml_lane": True,
        "supports_bev": True,
        "supports_lane_roi": True,
        "supports_crosswalk": False,
        "supports_crosswalk_trapezoid": False,
        "supports_sign": True,
        "supports_apriltag": True,
        "supports_object_detection": True,
        "supports_recording": True,
    },
}


def marker_mode(config: Any) -> str:
    if bool(getattr(config, "WITH_APRILTAG", False)):
        return "apriltag"
    if bool(getattr(config, "WITH_SIGN", False)):
        return "sign"
    return "none"


def set_marker_mode(config: Any, mode: str) -> str:
    mode = str(mode).lower()
    if mode not in {"sign", "apriltag", "none"}:
        raise ValueError("marker mode must be sign, apriltag, or none")
    callback = getattr(config, "apply_marker_mode", None)
    if callable(callback):
        callback(mode)
        return mode
    sign = mode == "sign"
    tag = mode == "apriltag"
    setattr(config, "WITH_SIGN", sign)
    setattr(config, "WITH_APRILTAG", tag)
    if hasattr(config, "USE_SIGN"):
        setattr(config, "USE_SIGN", sign)
    return mode


def mode_capabilities(config: Any) -> dict[str, Any]:
    mode = str(getattr(config, "MODE", "")).lower()
    base = dict(MODE_CAPABILITIES.get(mode, {}))
    lane_detector = "default"
    if mode == "city":
        lane_detector = str(getattr(config, "CITY_LANE_DETECTOR", "default"))
        if lane_detector not in base.get("lane_detectors", ()):
            lane_detector = "default"
    elif mode == "race" and bool(getattr(config, "USE_ML_LANE_DETECTOR", False)):
        lane_detector = "ml"

    ml_active = bool(
        mode == "race" and getattr(config, "USE_ML_LANE_DETECTOR", False)
    )
    base.update({
        "mode": mode,
        "lane_detector": lane_detector,
        "ml_lane_detector": ml_active,
        "supports_lane_roi": bool(
            base.get("supports_lane_roi", False) and not ml_active
        ),
        "supports_bev": bool(
            base.get("supports_bev", False) and not ml_active
        ),
        "bev": bool(getattr(config, "USE_BEV", False)),
        "sign_enabled": bool(getattr(config, "WITH_SIGN", False)),
        "apriltag_enabled": bool(getattr(config, "WITH_APRILTAG", False)),
        "object_detection_enabled": bool(
            getattr(config, "DETECT_OBJECT", False)
        ),
        "recording_enabled": bool(getattr(config, "RECORD_VIDEO", False)),
        "stream_enabled": bool(getattr(config, "STREAM", False)),
        "stream_control_enabled": bool(
            getattr(config, "STREAM_ALLOW_CONTROL", False)
        ),
        "marker_runtime_control": callable(
            getattr(config, "apply_marker_mode", None)
        ),
    })
    return base
