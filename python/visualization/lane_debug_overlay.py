"""Render lane-detection diagnostics outside the perception pipeline.

Perception engines return structured geometry in debug.draw_data only when
DEBUG or STREAM is enabled. This module owns all presentation drawing.
"""
from __future__ import annotations

import math

import cv2
import numpy as np


def _finite_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def resolve_visual_steering_angle(config, controller_angle, vision_angle):
    """Choose the angle to visualize without fabricating an actuator value.

    Non-legacy paths use the last successfully applied servo angle. The
    legacy angle calculation continues to show the detector's target.
    """
    # OLD_METHOD selects the legacy angle calculation. In every newer
    # path, visualize the controller's last successfully applied angle,
    # whether it came from PID error or a direct detector target.
    use_controller = not bool(getattr(config, "OLD_METHOD", False))
    if use_controller:
        return _finite_number(controller_angle)
    return _finite_number(vision_angle)


def _extract_segment(line):
    try:
        coords = np.asarray(line, dtype=np.float64).reshape(-1)
    except (TypeError, ValueError, OverflowError):
        return None
    if coords.size < 4 or not np.all(np.isfinite(coords[:4])):
        return None
    return tuple(int(round(float(value))) for value in coords[:4])


def _scaled_point(x, y, sx, sy):
    return int(round(float(x) * sx)), int(round(float(y) * sy))


def _draw_segment_list(canvas, segments, offset, sx, sy, color, thickness):
    if segments is None:
        return
    ox, oy = offset
    for item in segments:
        coords = _extract_segment(item)
        if coords is None:
            continue
        x1, y1, x2, y2 = coords
        p1 = _scaled_point(ox + x1, oy + y1, sx, sy)
        p2 = _scaled_point(ox + x2, oy + y2, sx, sy)
        cv2.line(canvas, p1, p2, color, thickness, cv2.LINE_AA)


def _scaled_box(box, sx, sy):
    left, top, right, bottom = box
    return (
        int(round(left * sx)),
        int(round(top * sy)),
        int(round(right * sx)),
        int(round(bottom * sy)),
    )


def _draw_classical(canvas, data, config):
    height, width = canvas.shape[:2]
    source_width = max(1, int(data.get("frame_width", width)))
    source_height = max(1, int(data.get("frame_height", height)))
    sx, sy = width / source_width, height / source_height
    boxes = data.get("roi_bounds") or {}
    if config is None:
        return

    lane_mode = str(getattr(config, "LANE_ROI_MODE", "rectangle")).lower()
    lane_is_trapezoid = lane_mode == "trapezoid"
    cw_is_trapezoid = bool(getattr(config, "CW_TRAPEZOID_MODE", False))

    rl_box = boxes.get("RL")
    ll_box = boxes.get("LL")
    cw_box = boxes.get("CW")
    if rl_box:
        left, top, right, bottom = _scaled_box(rl_box, sx, sy)
        if lane_is_trapezoid:
            base_width = (float(getattr(config, "RL_RIGHT_ROI", 0.9)) -
                          float(getattr(config, "RL_LEFT_ROI", 0.6))) * source_width * sx
            top_right = left + int(round(base_width * float(getattr(config, "RL_TOP_WIDTH_FACTOR", 0.85))))
            cv2.polylines(canvas, [np.asarray([
                [left, top], [top_right, top], [right, bottom], [left, bottom]
            ], dtype=np.int32)], True, (255, 0, 0), 1, cv2.LINE_AA)
        else:
            cv2.rectangle(canvas, (left, top), (right, bottom), (255, 0, 0), 1)
    if ll_box:
        left, top, right, bottom = _scaled_box(ll_box, sx, sy)
        if lane_is_trapezoid:
            base_width = (float(getattr(config, "LL_RIGHT_ROI", 0.5)) -
                          float(getattr(config, "LL_LEFT_ROI", 0.2))) * source_width * sx
            top_left = right - int(round(base_width * float(getattr(config, "LL_TOP_WIDTH_FACTOR", 0.85))))
            cv2.polylines(canvas, [np.asarray([
                [top_left, top], [right, top], [right, bottom], [left, bottom]
            ], dtype=np.int32)], True, (0, 255, 0), 1, cv2.LINE_AA)
        else:
            cv2.rectangle(canvas, (left, top), (right, bottom), (0, 255, 0), 1)
    if cw_box:
        left, top, right, bottom = _scaled_box(cw_box, sx, sy)
        if cw_is_trapezoid:
            factor = float(getattr(config, "CW_TOP_WIDTH_FACTOR", 0.9))
            box_width = right - left
            inset = int(round(box_width * (1.0 - factor) / 2.0))
            cv2.polylines(canvas, [np.asarray([
                [left + inset, top], [right - inset, top],
                [right, bottom], [left, bottom]
            ], dtype=np.int32)], True, (0, 255, 255), 1, cv2.LINE_AA)
        else:
            cv2.rectangle(canvas, (left + 1, top), (right - 1, bottom), (0, 255, 255), 1)

    offsets = data.get("line_offsets") or {}
    line_sets = data.get("lines") or {}
    for key, color, thickness in (
        ("RL", (0, 165, 255), 2),
        ("LL", (255, 255, 0), 2),
        ("CW", (0, 255, 255), 2),
    ):
        _draw_segment_list(
            canvas, line_sets.get(key), offsets.get(key, (0, 0)),
            sx, sy, color, thickness,
        )

    for key, color in (("RL", (0, 255, 0)), ("LL", (0, 255, 0))):
        mid_x = _finite_number((data.get("midpoints") or {}).get(key))
        box = boxes.get(key)
        if mid_x is None or not box:
            continue
        left, top, right, bottom = box
        local_x = left + mid_x
        point = _scaled_point(local_x, (top + bottom) / 2.0, sx, sy)
        cv2.circle(canvas, point, max(3, int(round(4 * min(sx, sy)))), color, -1)

    font_scale = max(0.24, min(0.38, height / 1400.0))
    thickness = max(1, int(round(height / 720.0)))
    settings = getattr(config, "stream_ui_settings", {}) if config is not None else {}
    selected = settings.get("frame_overlay", {}) if isinstance(settings, dict) else {}
    show_candidate_labels = selected.get("candidate_labels", True) is not False
    label = "Candidate:"
    (_, label_height), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
    candidate_label_items = (("RL", (0, 165, 255)), ("LL", (255, 255, 0))) if show_candidate_labels else ()
    for key, color in candidate_label_items:
        box = boxes.get(key)
        if not box:
            continue
        left, top, _, _ = _scaled_box(box, sx, sy)
        x = max(4, min(width - 4, left + 4))
        y = max(label_height + 4, min(height - 4, top + max(12, int(height * 0.04))))
        cv2.putText(canvas, label, (x, y), cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, thickness, cv2.LINE_AA)

    center_x = _finite_number(data.get("frame_center_x"))
    if center_x is None:
        center_x = source_width / 2.0
    center_x = int(round(center_x * sx))
    cv2.line(canvas, (center_x, 0), (center_x, height), (0, 0, 255), 1, cv2.LINE_AA)

    lane_center_x = _finite_number(data.get("lane_center_x"))
    center_offset = _finite_number(data.get("lane_center_offset_px"))
    if lane_center_x is not None:
        perception_x = int(round(lane_center_x * sx))
        perception_x = int(np.clip(perception_x, 0, width - 1))
        cv2.line(canvas, (perception_x, 0), (perception_x, height), (180, 0, 255), 1, cv2.LINE_AA)
    elif center_offset is not None:
        perception_center = _finite_number(data.get("frame_center_x"))
        if perception_center is None:
            perception_center = source_width / 2.0
        perception_x = int(round((perception_center - center_offset) * sx))
        perception_x = int(np.clip(perception_x, 0, width - 1))
        cv2.line(canvas, (perception_x, 0), (perception_x, height), (180, 0, 255), 1, cv2.LINE_AA)

def _draw_blsf(canvas, data):
    height, width = canvas.shape[:2]
    source_width = max(1, int(data.get("frame_width", width)))
    source_height = max(1, int(data.get("frame_height", height)))
    sx, sy = width / source_width, height / source_height
    y_values = np.arange(source_height, dtype=np.float32)
    for model in (data.get("left_model"), data.get("right_model")):
        if model is None:
            continue
        try:
            x_values = np.polyval(np.asarray(model, dtype=np.float64), y_values)
        except (TypeError, ValueError, np.linalg.LinAlgError):
            continue
        points = np.column_stack((x_values * sx, y_values * sy)).astype(np.int32)
        valid = (points[:, 0] >= 0) & (points[:, 0] < width) & (points[:, 1] >= 0) & (points[:, 1] < height)
        points = points[valid]
        if len(points) > 1:
            cv2.polylines(canvas, [points], False, (0, 255, 0), 2, cv2.LINE_AA)

    center_x = int(round(width / 2.0))
    cv2.line(canvas, (center_x, 0), (center_x, height), (0, 0, 255), 1, cv2.LINE_AA)

    source_center = _finite_number(data.get("lane_center_x"))
    if source_center is not None:
        x = int(np.clip(round(source_center * sx), 0, width - 1))
        cv2.line(canvas, (x, 0), (x, height), (180, 0, 255), 1, cv2.LINE_AA)

    roi = data.get("crosswalk_roi")
    if roi and len(roi) == 4:
        top, bottom, left, right = roi
        left, top, right, bottom = _scaled_box((left, top, right, bottom), sx, sy)
        cv2.rectangle(canvas, (left, top), (right, bottom), (0, 255, 255), 1)
        _draw_segment_list(
            canvas,
            data.get("crosswalk_lines"),
            (int(roi[2]), int(roi[0])),
            sx, sy, (0, 255, 255), 2,
        )
def _draw_ml(canvas, data):
    height, width = canvas.shape[:2]
    source_width = max(1, int(data.get("frame_width", width)))
    mask = data.get("mask")
    if mask is not None:
        try:
            mask_array = np.asarray(mask, dtype=np.float32)
            if mask_array.ndim == 2 and mask_array.size:
                if mask_array.shape != (height, width):
                    mask_array = cv2.resize(mask_array, (width, height), interpolation=cv2.INTER_LINEAR)
                mask_u8 = np.uint8(np.clip(mask_array, 0.0, 1.0) * 255.0)
                _, binary = cv2.threshold(mask_u8, 100, 255, cv2.THRESH_BINARY)
                contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                cv2.drawContours(canvas, contours, -1, (0, 255, 0), 2)
        except (TypeError, ValueError, cv2.error):
            pass
    frame_center = int(round(width / 2.0))
    cv2.line(canvas, (frame_center, 0), (frame_center, height), (0, 0, 255), 1, cv2.LINE_AA)
    center_x = _finite_number(data.get("center_x"))
    if center_x is not None:
        x = int(np.clip(round(center_x * width / source_width), 0, width - 1))
        cv2.line(canvas, (x, 0), (x, height), (180, 0, 255), 1, cv2.LINE_AA)


def steering_marker_x(width, config, steering_angle):
    """Return marker x as a function of actual servo angle/direction."""
    angle = _finite_number(steering_angle)
    center = _finite_number(getattr(config, "SERVO_CENTER", 95))
    minimum = _finite_number(getattr(config, "MIN_SERVO_ANGLE", 55))
    maximum = _finite_number(getattr(config, "MAX_SERVO_ANGLE", 125))
    if angle is None or center is None or minimum is None or maximum is None or not minimum < center < maximum:
        return None
    direction = str(getattr(config, "SERVO_DIRECTION", "ltr")).strip().lower()
    servo_sign = -1.0 if direction == "rtl" else 1.0
    physical_delta = (angle - center) * servo_sign
    if physical_delta >= 0:
        available = (center - minimum) if direction == "rtl" else (maximum - center)
    else:
        available = (maximum - center) if direction == "rtl" else (center - minimum)
    if available <= 0:
        return None
    ratio = float(np.clip(physical_delta / available, -1.0, 1.0))
    return int(np.clip(round(width / 2.0 + ratio * width * 0.22), 0, max(0, width - 1)))


def _draw_servo_guide(canvas, config, steering_angle):
    angle = _finite_number(steering_angle)
    if angle is None:
        return
    height, width = canvas.shape[:2]
    center = _finite_number(getattr(config, "SERVO_CENTER", 95))
    if center is None:
        return
    marker_x = steering_marker_x(width, config, angle)
    if marker_x is None:
        return
    marker_y = int(height * 0.58)
    center_x = int(round(width / 2.0))
    cv2.line(canvas, (marker_x, marker_y), (marker_x, height - 1), (255, 0, 255), 2, cv2.LINE_AA)
    cv2.line(canvas, (center_x, height - 10), (marker_x, marker_y), (255, 0, 255), 2, cv2.LINE_AA)
    direction_delta = (angle - center) * (-1 if str(getattr(config, "SERVO_DIRECTION", "ltr")).lower() == "rtl" else 1)
    direction_label = "CENTER" if abs(direction_delta) < 0.5 else ("RIGHT" if direction_delta > 0 else "LEFT")
    label = "Applied {:.0f} deg | Center {:.0f} deg | {}".format(angle, center, direction_label)
    font_scale = max(0.35, min(0.65, height / 800.0))
    thickness = max(1, int(round(height / 480.0)))
    (label_width, label_height), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
    label_x = int(np.clip(marker_x + 7, 4, max(4, width - label_width - 4)))
    label_y = max(label_height + 4, marker_y - 8)
    cv2.putText(canvas, label, (label_x, label_y), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 0, 255), thickness, cv2.LINE_AA)


def render_lane_debug_overlay(frame, draw_data=None, config=None, steering_angle=None):
    """Return a separate annotated frame; never mutate the camera/perception frame."""
    if frame is None:
        return None
    try:
        if getattr(frame, "size", 0) == 0 or len(frame.shape) < 2:
            return None
    except (AttributeError, TypeError):
        return None

    canvas = frame.copy()
    data = draw_data if isinstance(draw_data, dict) else {}
    kind = data.get("kind")
    if kind == "classical":
        _draw_classical(canvas, data, config)
    elif kind == "blsf":
        _draw_blsf(canvas, data)
    elif kind == "ml":
        _draw_ml(canvas, data)
    if config is not None:
        settings = getattr(config, "stream_ui_settings", {})
        selected = settings.get("frame_overlay", {}) if isinstance(settings, dict) else {}
        if selected.get("servo_guide", True) is not False:
            _draw_servo_guide(canvas, config, steering_angle)
    return canvas
