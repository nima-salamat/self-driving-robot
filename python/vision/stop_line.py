"""Conservative camera-based detector for a solid horizontal City stop line."""
import cv2
import numpy as np


class StopLineDetector:
    """Detect a wide, near-horizontal road marking inside a calibrated image ROI.

    This is intentionally a geometry/threshold detector rather than a learned
    classifier. It reports image evidence only; the runtime owns stop-line
    latching and traffic-light decisions.
    """

    def __init__(self, config):
        self.config = config

    def _value(self, name, default):
        return getattr(self.config, name, default)

    def detect(self, frame):
        if not isinstance(frame, np.ndarray) or frame.size == 0 or frame.ndim != 3:
            return {"detected": False, "confidence": 0.0, "bbox": None}

        height, width = frame.shape[:2]
        top = float(self._value("SIMULATOR_STOP_LINE_TOP_ROI", 0.72))
        bottom = float(self._value("SIMULATOR_STOP_LINE_BOTTOM_ROI", 0.98))
        left = float(self._value("SIMULATOR_STOP_LINE_LEFT_ROI", 0.10))
        right = float(self._value("SIMULATOR_STOP_LINE_RIGHT_ROI", 0.90))
        if not (0 <= top < bottom <= 1 and 0 <= left < right <= 1):
            return {"detected": False, "confidence": 0.0, "bbox": None}

        y1, y2 = int(top * height), int(bottom * height)
        x1, x2 = int(left * width), int(right * width)
        roi = frame[y1:y2, x1:x2]
        if roi.size == 0:
            return {"detected": False, "confidence": 0.0, "bbox": None}

        threshold = int(self._value("SIMULATOR_STOP_LINE_THRESHOLD", 190))
        minimum_width = float(self._value("SIMULATOR_STOP_LINE_MIN_WIDTH_RATIO", 0.55))
        minimum_area = float(self._value("SIMULATOR_STOP_LINE_MIN_AREA", 120.0))
        max_angle = float(self._value("SIMULATOR_STOP_LINE_MAX_ANGLE_DEG", 12.0))
        if not (0 <= threshold <= 255 and 0 < minimum_width <= 1
                and minimum_area >= 1 and 0 < max_angle <= 45):
            return {"detected": False, "confidence": 0.0, "bbox": None}

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
        kernel_width = max(5, min(41, int(round(roi.shape[1] * 0.08)) | 1))
        horizontal_kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT, (kernel_width, 3)
        )
        mask = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, horizontal_kernel)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        best = None
        best_score = 0.0
        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < minimum_area:
                continue
            rect = cv2.minAreaRect(contour)
            (center_x, center_y), (rect_width, rect_height), angle = rect
            if rect_width <= 0 or rect_height <= 0:
                continue
            long_side = max(rect_width, rect_height)
            short_side = min(rect_width, rect_height)
            long_angle = angle if rect_width >= rect_height else angle + 90.0
            horizontal_angle = abs(((long_angle + 90.0) % 180.0) - 90.0)
            width_ratio = long_side / max(1.0, float(roi.shape[1]))
            aspect_ratio = long_side / max(1.0, short_side)
            if width_ratio < minimum_width or aspect_ratio < 4.0 or horizontal_angle > max_angle:
                continue
            # Favor broad, thin markings near the lower half of the calibrated ROI.
            vertical_position = center_y / max(1.0, float(roi.shape[0]))
            if vertical_position < 0.25:
                continue
            score = min(1.0, width_ratio) * min(1.0, aspect_ratio / 8.0)
            if score > best_score:
                box = cv2.boxPoints(rect).astype(np.int32)
                bx, by, bw, bh = cv2.boundingRect(box)
                best = (x1 + bx, y1 + by, bw, bh)
                best_score = score

        return {
            "detected": best is not None,
            "confidence": float(best_score),
            "bbox": best,
        }
