"""HSV traffic-light classifier preserving the legacy (color, debug_frame) API."""
import logging
from collections import deque

import cv2
import numpy as np
import modes.city.config_city as config_city

logger = logging.getLogger(__name__)


class TrafficLightDetector:
    def __init__(self, config=None):
        self.config = config

    def _get(self, key, default):
        return getattr(self.config or config_city, key, default)

    def detect(self, frame):
        if not isinstance(frame, np.ndarray) or frame.size == 0 or frame.ndim != 3 or frame.shape[2] != 3:
            return None, None
        height, width = frame.shape[:2]
        roi = tuple(self._get(key, default) for key, default in (
            ("TL_TOP_ROI", 0.0), ("TL_BOTTOM_ROI", 1.0),
            ("TL_LEFT_ROI", 0.0), ("TL_RIGHT_ROI", 1.0),
        ))
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in roi):
            return None, None
        top, bottom, left, right = roi
        if not (0 <= top < bottom <= 1 and 0 <= left < right <= 1):
            logger.warning("Invalid traffic-light ROI; returning UNKNOWN")
            return None, frame.copy() if self._get("DEBUG", False) else None
        y1, y2 = int(top * height), int(bottom * height)
        x1, x2 = int(left * width), int(right * width)
        if y1 < 0 or x1 < 0 or y2 > height or x2 > width or y1 >= y2 or x1 >= x2:
            return None, None
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return None, None
        debug = crop.copy() if self._get("DEBUG", False) else None
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        min_sat = int(self._get("TL_MIN_SATURATION", 50))
        min_value = int(self._get("TL_MIN_VALUE", 50))
        min_area = float(self._get("TL_MIN_CONTOUR_AREA", 5.0))
        min_brightness = float(self._get("TL_MIN_ACTIVE_BRIGHTNESS", 180))
        color_ranges = (
            ("RED", self._get("TL_RED_HSV_RANGES", (
                ((0, 100, 100), (10, 255, 255)),
                ((170, 100, 100), (180, 255, 255)),
            ))),
            ("GREEN", self._get("TL_GREEN_HSV_RANGES", (
                ((40, 50, 50), (90, 255, 255)),
            ))),
        )
        evidence = {}
        for color_name, ranges in color_ranges:
            mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
            for lower, upper in ranges:
                lower = (int(lower[0]), max(int(lower[1]), min_sat), max(int(lower[2]), min_value))
                mask = cv2.bitwise_or(
                    mask,
                    cv2.inRange(hsv, np.array(lower, np.uint8), np.array(upper, np.uint8)),
                )
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            candidates = []
            for contour in contours:
                area = cv2.contourArea(contour)
                if area < min_area:
                    continue
                region = np.zeros(mask.shape, dtype=np.uint8)
                cv2.drawContours(region, [contour], -1, 255, -1)
                mean_value = cv2.mean(hsv[:, :, 2], mask=region)[0]
                if mean_value >= min_brightness:
                    candidates.append((area, mean_value, contour))
            if candidates:
                evidence[color_name] = max(candidates, key=lambda item: item[0])
        # Conflicting red/green regions are ambiguous, never a permission to move.
        color = next(iter(evidence)) if len(evidence) == 1 else None
        if debug is not None:
            for name, (_, value, contour) in evidence.items():
                (cx, cy), radius = cv2.minEnclosingCircle(contour)
                cv2.circle(debug, (int(cx), int(cy)), max(1, int(radius)), (0, 255, 255), 2)
                cv2.putText(debug, f"{name} V={value:.0f}", (int(cx), max(12, int(cy) - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
        return color, debug


class GreenConfirmationWindow:
    """Rolling window; count distinct fresh GREEN frames and require newest GREEN."""
    def __init__(self, window_size=10, required_green=8):
        if not isinstance(window_size, int) or isinstance(window_size, bool) or window_size < 1:
            raise ValueError("window_size must be positive")
        if not isinstance(required_green, int) or isinstance(required_green, bool) or not 1 <= required_green <= window_size:
            raise ValueError("required_green must be within window")
        self.window_size = window_size
        self.required_green = required_green
        self.observations = deque(maxlen=window_size)
        self.last_frame_token = None

    def reset(self):
        self.observations.clear()
        self.last_frame_token = None

    def observe(self, color, frame_token):
        if frame_token is None or frame_token == self.last_frame_token:
            return self.confirmed
        self.last_frame_token = frame_token
        self.observations.append(color if color in ("RED", "GREEN") else None)
        return self.confirmed

    @property
    def green_count(self):
        return sum(value == "GREEN" for value in self.observations)

    @property
    def confirmed(self):
        return bool(self.observations and self.observations[-1] == "GREEN"
                    and self.green_count >= self.required_green)
