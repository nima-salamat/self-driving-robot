"""Configurable, compact telemetry text for the City/Race Stream frame overlay."""
from __future__ import annotations

import math


DEFAULT_FRAME_OVERLAY = {
    "fps": True,
    "realfps": False,
    "status": True,
    "applied_angle": True,
    "vision_angle": True,
    "servo_center": True,
    "crosswalk": False,
    "sign": False,
    "last_tag": False,
    "error": False,
    "lane_type": False,
    "speed": False,
    "confidence": False,
    "obstacle": False,
    "servo_guide": True,
    "candidate_labels": True,
}
FRAME_OVERLAY_LABELS = {
    "fps": "Processing FPS",
    "realfps": "Camera FPS",
    "status": "Mode status",
    "applied_angle": "Applied servo angle",
    "vision_angle": "Vision steering target",
    "servo_center": "Servo center",
    "crosswalk": "Crosswalk state",
    "sign": "Detected sign",
    "last_tag": "Last sign/tag",
    "error": "Lane error",
    "lane_type": "Lane detection type",
    "speed": "Commanded speed",
    "confidence": "Perception confidence",
    "obstacle": "Obstacle planner state",
    "servo_guide": "Servo steering guide",
    "candidate_labels": "Lane ROI candidate labels",
}


def _safe_text(value, limit=28):
    text = str(value if value is not None else "N/A")
    return " ".join(text.replace("\r", " ").replace("\n", " ").split())[:limit]


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _format_number(value, decimals=1):
    number = _number(value)
    if number is None:
        return "N/A"
    return f"{number:.{decimals}f}"


def build_frame_telemetry(
    config,
    *,
    instant_fps=None,
    real_fps=None,
    status=None,
    applied_angle=None,
    vision_angle=None,
    crosswalk=None,
    sign=None,
    last_tag=None,
    error=None,
    lane_type=None,
    speed=None,
    confidence=None,
    obstacle=None,
    max_line_length=58,
):
    """Return only selected data fields, wrapped into short overlay lines."""
    settings = getattr(config, "stream_ui_settings", {})
    selected = settings.get("frame_overlay", {}) if isinstance(settings, dict) else {}
    enabled = dict(DEFAULT_FRAME_OVERLAY)
    if isinstance(selected, dict):
        enabled.update({
            key: value for key, value in selected.items()
            if key in enabled and isinstance(value, bool)
        })

    tokens = []
    if enabled["fps"]:
        tokens.append("FPS:" + _format_number(instant_fps))
    if enabled["realfps"]:
        tokens.append("RealFPS:" + _format_number(real_fps))
    if enabled["status"]:
        tokens.append("Status:" + _safe_text(status, 22))
    if enabled["applied_angle"]:
        tokens.append("Applied:" + _format_number(applied_angle))
    if enabled["vision_angle"]:
        tokens.append("Target:" + _format_number(vision_angle))
    if enabled["servo_center"]:
        tokens.append("Center:" + _format_number(getattr(config, "SERVO_CENTER", 95), 0))
    if enabled["crosswalk"] and crosswalk is not None:
        tokens.append("Crosswalk:" + ("yes" if bool(crosswalk) else "no"))
    if enabled["sign"] and sign not in (None, "", "None"):
        tokens.append("Sign:" + _safe_text(sign, 18))
    if enabled["last_tag"] and last_tag not in (None, "", "None"):
        tokens.append("Tag:" + _safe_text(last_tag, 18))
    if enabled["error"]:
        tokens.append("Error:" + _format_number(error))
    if enabled["lane_type"] and lane_type not in (None, ""):
        tokens.append("Lane:" + _safe_text(lane_type, 18))
    if enabled["speed"]:
        tokens.append("Speed:" + _format_number(speed, 0))
    if enabled["confidence"] and isinstance(confidence, dict):
        score = _number(confidence.get("score"))
        if score is not None:
            name = _safe_text(confidence.get("name", ""), 12)
            tokens.append("Conf:" + f"{score:.2f}" + ((" " + name) if name else ""))
    if enabled["obstacle"] and isinstance(obstacle, dict):
        state = _safe_text(obstacle.get("state", "N/A"), 12)
        reason = _safe_text(obstacle.get("reason", ""), 16)
        tokens.append("Obstacle:" + state + ((" " + reason) if reason else ""))

    lines = []
    current = ""
    for token in tokens:
        candidate = token if not current else current + "  ·  " + token
        if current and len(candidate) > max(20, int(max_line_length)):
            lines.append(current)
            current = token
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines
