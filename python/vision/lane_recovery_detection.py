"""Bounded Sobel + Hough search used only by simulator lane recovery."""

import cv2
import numpy as np


def detect_recovery_lines(
    frame, roi, config, morph_kernel=None, *, side=None, mirrored=False
):
    """Run the simulator Sobel/Hough detector in a clipped full-frame ROI.

    Optional side-specific trapezoid masking and mirroring match the normal
    City/Race lane preprocessing, so recovery and tracking do not alternate
    between different detectors from one frame to the next.
    """
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

    mask = None
    roi_mode = str(getattr(config, "LANE_ROI_MODE", "rectangle")).lower()
    if side in {"left", "right"} and roi_mode == "trapezoid":
        prefix = "LL" if side == "left" else "RL"
        base_width = max(
            1,
            int(round(
                (float(getattr(config, prefix + "_RIGHT_ROI", 1.0))
                 - float(getattr(config, prefix + "_LEFT_ROI", 0.0)))
                * width
            )),
        )
        factor_name = "LL_TOP_WIDTH_FACTOR" if side == "left" else "RL_TOP_WIDTH_FACTOR"
        factor = float(getattr(config, factor_name, 0.85))
        factor = max(0.05, min(1.0, factor))
        crop_height, crop_width = crop.shape[:2]
        mask = np.zeros((crop_height, crop_width), dtype=np.uint8)
        if side == "left":
            top_left = crop_width - int(round(base_width * factor))
            polygon = np.asarray([[
                [max(0, min(crop_width - 1, top_left)), 0],
                [crop_width - 1, 0],
                [crop_width - 1, crop_height - 1],
                [0, crop_height - 1],
            ]], dtype=np.int32)
        else:
            top_right = int(round(base_width * factor))
            polygon = np.asarray([[
                [0, 0],
                [max(0, min(crop_width - 1, top_right)), 0],
                [crop_width - 1, crop_height - 1],
                [0, crop_height - 1],
            ]], dtype=np.int32)
        cv2.fillPoly(mask, polygon, 255)

    if mirrored:
        crop = cv2.flip(crop, 1)
        if mask is not None:
            mask = cv2.flip(mask, 1)

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
    if mask is not None:
        edges = cv2.bitwise_and(edges, edges, mask=mask)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180,
        threshold=max(1, int(getattr(config, "HOUGH_THRESHOLD", 15))),
        minLineLength=max(1, int(getattr(config, "HOUGH_MIN_LINE_LENGTH", 5))),
        maxLineGap=max(0, int(getattr(config, "HOUGH_MAX_LINE_GAP", 20))),
    )
    # OpenCV may return an empty (0, 4) array instead of None. Normalize both
    # representations so downstream tracking and diagnostics see no candidates.
    if lines is not None and len(lines) == 0:
        lines = None
    if mirrored:
        edges = cv2.flip(edges, 1)
        if lines is not None:
            restored = np.asarray(lines).copy()
            coordinates = restored.reshape(-1, 4)
            coordinates[:, [0, 2]] = (crop.shape[1] - 1) - coordinates[:, [0, 2]]
            lines = restored
    return edges, lines
