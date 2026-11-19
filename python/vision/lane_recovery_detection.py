"""Bounded Sobel + Hough search used only by simulator lane recovery."""

import cv2
import numpy as np


def detect_recovery_lines(frame, roi, config, morph_kernel=None):
    """Run the configured Sobel/Hough detector inside a clipped full-frame ROI."""
    if frame is None or not isinstance(frame, np.ndarray) or frame.ndim < 2:
        return None, None
    height, width = frame.shape[:2]
    left, top, right, bottom = map(int, roi)
    left, top = max(0, left), max(0, top)
    right, bottom = min(width, right), min(height, bottom)
    if right <= left or bottom <= top:
        return None, None
    crop = frame[top:bottom, left:right]
    if crop.size == 0:
        return None, None
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    blur = max(1, int(getattr(config, "HOUGH_BLUR_KERNEL", 3)))
    if blur % 2 == 0:
        blur += 1
    if blur > 1:
        gray = cv2.GaussianBlur(gray, (blur, blur), 0)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    magnitude = cv2.convertScaleAbs(cv2.magnitude(gx, gy))
    _, edges = cv2.threshold(
        magnitude, int(getattr(config, "LANE_THRESHOLD", 180)), 255,
        cv2.THRESH_BINARY,
    )
    if bool(getattr(config, "HOUGH_MORPH_CLOSE", True)):
        kernel = morph_kernel if morph_kernel is not None else np.ones((3, 3), np.uint8)
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=1)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180,
        threshold=max(1, int(getattr(config, "HOUGH_THRESHOLD", 15))),
        minLineLength=max(1, int(getattr(config, "HOUGH_MIN_LINE_LENGTH", 5))),
        maxLineGap=max(0, int(getattr(config, "HOUGH_MAX_LINE_GAP", 20))),
    )
    return edges, lines
