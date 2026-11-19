"""Relaxed Sobel + Hough detection used only during lane reacquisition.

The normal detector remains untouched. When a tracked boundary disappears,
this fallback widens its search ROI and slightly relaxes edge/Hough thresholds.
The temporal lane tracker still validates every candidate against predicted
position, lane width, side identity and multi-frame reacquisition.
"""
from __future__ import annotations

import math

import cv2
import numpy as np


def detect_recovery_lines(frame, roi, config, morph_kernel=None):
    """Return (edges, lines) for a clipped full-frame ROI."""
    if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
        return None, None
    try:
        left, top, right, bottom = (int(round(float(value))) for value in roi)
    except (TypeError, ValueError, OverflowError):
        return None, None
    height, width = frame.shape[:2]
    left = max(0, min(width - 1, left))
    right = max(left + 1, min(width, right))
    top = max(0, min(height - 1, top))
    bottom = max(top + 1, min(height, bottom))
    crop = frame[top:bottom, left:right]
    if crop.size == 0:
        return None, None

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    try:
        blur_kernel = int(getattr(config, "HOUGH_BLUR_KERNEL", 3))
    except (TypeError, ValueError, OverflowError):
        blur_kernel = 3
    blur_kernel = max(1, min(15, blur_kernel))
    if blur_kernel > 1:
        if blur_kernel % 2 == 0:
            blur_kernel += 1
        gray = cv2.GaussianBlur(gray, (blur_kernel, blur_kernel), 0)

    grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    magnitude = cv2.convertScaleAbs(cv2.magnitude(grad_x, grad_y))

    try:
        base_edge_threshold = float(getattr(config, "LANE_THRESHOLD", 180))
    except (TypeError, ValueError, OverflowError):
        base_edge_threshold = 180.0
    if not math.isfinite(base_edge_threshold):
        base_edge_threshold = 180.0
    edge_threshold = max(20, min(255, int(round(base_edge_threshold * 0.78))))
    _, edges = cv2.threshold(
        magnitude, edge_threshold, 255, cv2.THRESH_BINARY
    )

    if bool(getattr(config, "HOUGH_MORPH_CLOSE", True)):
        kernel = morph_kernel
        if kernel is None or not isinstance(kernel, np.ndarray) or kernel.size == 0:
            kernel = np.ones((3, 3), dtype=np.uint8)
        edges = cv2.morphologyEx(
            edges, cv2.MORPH_CLOSE, kernel, iterations=1
        )

    def bounded_int(name, default, minimum, maximum):
        try:
            value = int(getattr(config, name, default))
        except (TypeError, ValueError, OverflowError):
            value = int(default)
        return max(minimum, min(maximum, value))

    base_hough = bounded_int("HOUGH_THRESHOLD", 15, 1, 255)
    base_min_length = bounded_int("HOUGH_MIN_LINE_LENGTH", 5, 1, 500)
    base_max_gap = bounded_int("HOUGH_MAX_LINE_GAP", 20, 0, 100)

    # Recover faint or fragmented markings, but keep the relaxation bounded.
    hough_threshold = max(5, int(round(base_hough * 0.70)))
    min_line_length = max(4, int(round(base_min_length * 0.70)))
    max_line_gap = min(100, max(base_max_gap, int(round(base_max_gap * 1.50)) + 2))
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 180,
        threshold=hough_threshold,
        minLineLength=min_line_length,
        maxLineGap=max_line_gap,
    )
    return edges, lines
