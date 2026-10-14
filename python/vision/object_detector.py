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
    def lane_bounds_at_y(lane_segments_px, frame_shape, y_px):
        """Interpolate the visible left/right lane boundaries at one image row."""
        if not lane_segments_px or frame_shape is None:
            return None
        height, width = frame_shape[:2]
        try:
            y_px = float(y_px)
        except (TypeError, ValueError):
            return None
        if not np.isfinite(y_px) or not 0 <= y_px < height:
            return None
        intersections = []
        for segment in lane_segments_px:
            if not isinstance(segment, (tuple, list)) or len(segment) != 4:
                continue
            try:
                x1, y1, x2, y2 = map(float, segment)
            except (TypeError, ValueError):
                continue
            if not all(np.isfinite(v) for v in (x1, y1, x2, y2)):
                continue
            if abs(y2 - y1) < 1e-6 or not min(y1, y2) <= y_px <= max(y1, y2):
                continue
            x = x1 + (y_px - y1) * (x2 - x1) / (y2 - y1)
            if 0 <= x < width:
                intersections.append(x)
        center = width / 2.0
        left_values = [x for x in intersections if x < center]
        right_values = [x for x in intersections if x >= center]
        if left_values and right_values:
            left, right = max(left_values), min(right_values)
            if right > left:
                return left, right
        unique = sorted(intersections)
        if len(unique) >= 2 and unique[-1] > unique[0]:
            return unique[0], unique[-1]
        return None

    @classmethod
    def passage_options(cls, component, lane_segments_px, frame_shape,
                        lane_width_cm, robot_width_cm, clearance_cm):
        """Estimate side gaps from visible lane width and measured dimensions.

        This remains an image-plane estimate, not proof of physical clearance.
        The caller must also require fresh sensor data, calibrated steering, and
        continuous encoder data, and must stop on ambiguity.
        """
        if not component or frame_shape is None:
            return {}
        try:
            lane_width_cm = float(lane_width_cm)
            robot_width_cm = float(robot_width_cm)
            clearance_cm = float(clearance_cm)
            x, y, width, height = map(float, component["bbox_px"])
        except (KeyError, TypeError, ValueError):
            return {}
        numeric = (lane_width_cm, robot_width_cm, clearance_cm, x, y, width, height)
        if not all(np.isfinite(v) for v in numeric) or min(
            lane_width_cm, robot_width_cm, clearance_cm, width, height
        ) <= 0:
            return {}
        frame_height, _frame_width = frame_shape[:2]
        contact_y = min(float(frame_height - 1), max(0.0, y + height - 1))
        bounds = cls.lane_bounds_at_y(lane_segments_px, frame_shape, contact_y)
        if bounds is None:
            return {}
        left_bound, right_bound = bounds
        lane_px = right_bound - left_bound
        if lane_px <= 1:
            return {}
        cm_per_px = lane_width_cm / lane_px
        object_left = max(left_bound, x)
        object_right = min(right_bound, x + width)
        if object_right <= object_left:
            return {}
        required_gap_cm = robot_width_cm + 2.0 * clearance_cm
        left_gap_cm = max(0.0, object_left - left_bound) * cm_per_px
        right_gap_cm = max(0.0, right_bound - object_right) * cm_per_px
        options = {}
        if left_gap_cm >= required_gap_cm:
            target_x = (left_bound + object_left) / 2.0
            options["left"] = {
                "target_fraction": (target_x - left_bound) / lane_px,
                "clearance_cm": left_gap_cm,
                "gap_px": object_left - left_bound,
            }
        if right_gap_cm >= required_gap_cm:
            target_x = (object_right + right_bound) / 2.0
            options["right"] = {
                "target_fraction": (target_x - left_bound) / lane_px,
                "clearance_cm": right_gap_cm,
                "gap_px": right_bound - object_right,
            }
        return options

    @staticmethod
    def relates_to_lane(component, lane_segments_px, frame_shape):
        """Estimate image-plane relation to observed lane segments, not cm."""
        if not component or not lane_segments_px or frame_shape is None:
            return {"valid": False, "reason": "orange component or lane segments unavailable"}
        height, width = frame_shape[:2]
        x, _centroid_y = component["centroid_px"]
        bx, by, bw, bh = component["bbox_px"]
        # The bottom edge is a better image-plane proxy for road contact than
        # the vertical midpoint of a tall object; it is still not metric depth.
        contact_y = min(float(height - 1), max(0.0, float(by + bh - 1)))
        bounds = ObjectDetector.lane_bounds_at_y(
            lane_segments_px, frame_shape, contact_y
        )
        if bounds is None:
            return {"valid": False, "reason": "two lane boundaries not measurable at obstacle ground-contact row"}
        left, right = bounds
        if right <= left:
            return {"valid": False, "reason": "invalid lane boundary ordering"}
        intersects = bx + bw >= left and bx <= right
        fraction = (x - left) / (right - left)
        return {
            "valid": True,
            "relation": "inside_lane" if intersects else "outside_lane",
            "left_boundary_px": left,
            "right_boundary_px": right,
            "obstacle_centroid_px": [x, float(contact_y)],
            "image_fraction_across_lane": fraction,
            "coordinate_space": "image pixels; not physical corridor clearance",
            "frame_width_px": width,
            "frame_height_px": height,
        }
