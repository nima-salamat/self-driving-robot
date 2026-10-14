import cv2
import numpy as np


class ObjectDetector:
    def __init__(
        self,
        lower_hsv=(5, 100, 100),
        upper_hsv=(20, 255, 255),
        min_area_percent=10,
    ):
        """
        Parameters
        ----------
        lower_hsv : tuple
            Lower HSV bound for orange.

        upper_hsv : tuple
            Upper HSV bound for orange.

        min_area_percent : float
            Minimum percentage of orange pixels required
            to report detection.
        """
        self.lower = np.array(lower_hsv, dtype=np.uint8)
        self.upper = np.array(upper_hsv, dtype=np.uint8)
        self.min_area_percent = min_area_percent

    def detect(self, frame):
        """
        Detect whether the image contains enough orange pixels.

        Parameters
        ----------
        frame : np.ndarray
            BGR image.

        Returns
        -------
        detected : bool
            True if orange percentage exceeds threshold.

        orange_percent : float
            Percentage of orange pixels.

        mask : np.ndarray
            Binary mask of detected orange regions.
        """
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        mask = cv2.inRange(hsv, self.lower, self.upper)

        # Remove small noisy regions
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

        orange_pixels = cv2.countNonZero(mask)
        total_pixels = mask.size

        orange_percent = 100.0 * orange_pixels / total_pixels

        detected = orange_percent >= self.min_area_percent

        return detected, orange_percent, mask

    @staticmethod
    def localize(frame, mask, min_component_area=16):
        """Return measurable orange-mask components in image coordinates.

        Coordinates are image pixels only. Without a calibrated camera/ground
        plane this does not estimate physical obstacle distance or clearance.
        """
        if frame is None or mask is None or getattr(mask, "size", 0) == 0:
            return None
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        components = []
        full_height, full_width = frame.shape[:2]
        scale_x = full_width / max(1, mask.shape[1])
        scale_y = full_height / max(1, mask.shape[0])
        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < float(min_component_area):
                continue
            x, y, width, height = cv2.boundingRect(contour)
            moments = cv2.moments(contour)
            if moments["m00"] <= 0:
                continue
            components.append({
                "area_px": area,
                "bbox_px": [int(x * scale_x), int(y * scale_y),
                            int(width * scale_x), int(height * scale_y)],
                "centroid_px": [moments["m10"] / moments["m00"] * scale_x,
                                moments["m01"] / moments["m00"] * scale_y],
                "quality": min(1.0, area / max(1.0, mask.size * 0.02)),
            })
        if not components:
            return None
        best = max(components, key=lambda item: item["area_px"])
        image_center = full_width / 2.0
        best["valid"] = True
        best["intersects_center"] = (
            best["bbox_px"][0] <= image_center <= best["bbox_px"][0] + best["bbox_px"][2]
        )
        best["coordinate_space"] = "image pixels; not physical range"
        best["component_count"] = len(components)
        return best

    @staticmethod
    def relates_to_lane(component, lane_segments_px, frame_shape):
        """Estimate image-plane relation to observed lane segments, not cm."""
        if not component or not lane_segments_px or frame_shape is None:
            return {"valid": False, "reason": "orange component or lane segments unavailable"}
        height, width = frame_shape[:2]
        x, y = component["centroid_px"]
        # Use nearby detected lane line endpoints as an image-plane corridor
        # approximation at obstacle row. Require both sides to interpolate.
        intersections = []
        for x1, y1, x2, y2 in lane_segments_px:
            if min(y1, y2) <= y <= max(y1, y2) and abs(y2 - y1) > 1e-6:
                intersections.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
        if len(intersections) < 2:
            return {"valid": False, "reason": "two lane boundaries not measurable at obstacle row"}
        left, right = sorted(intersections)[0], sorted(intersections)[-1]
        if right <= left:
            return {"valid": False, "reason": "invalid lane boundary ordering"}
        bx, by, bw, bh = component["bbox_px"]
        intersects = bx + bw >= left and bx <= right
        return {
            "valid": True,
            "relation": "inside_lane" if intersects else "outside_lane",
            "left_boundary_px": left,
            "right_boundary_px": right,
            "obstacle_centroid_px": [x, y],
            "image_fraction_across_lane": (x - left) / (right - left),
            "coordinate_space": "image pixels; not physical corridor clearance",
            "frame_width_px": width,
            "frame_height_px": height,
        }
