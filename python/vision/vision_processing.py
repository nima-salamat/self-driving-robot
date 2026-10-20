import math
from base_config import (
    RL_TOP_ROI, RL_BOTTOM_ROI, RL_RIGHT_ROI, RL_LEFT_ROI,
    LL_TOP_ROI, LL_BOTTOM_ROI, LL_RIGHT_ROI, LL_LEFT_ROI,
    CW_TOP_ROI, CW_BOTTOM_ROI, CW_RIGHT_ROI, CW_LEFT_ROI,
    LOW_KP, HIGH_KP, MAX_SERVO_ANGLE, MIN_SERVO_ANGLE
)
import base_config
import cv2
import numpy as np

class VisionProcessor:
    def __init__(self):
        self.last_steering = 90

    def _largest_mid_x(self, lines):
        if lines is None:
            return None
        max_length = 0
        x_mid = None
        for line in lines:
            x1, y1, x2, y2 = line[0]
            if x1 == x2:
                continue
            slope = (y2 - y1) / (x2 - x1 + 1e-9)
            if abs(slope) > 0.1:
                length = math.hypot(x2 - x1, y2 - y1)
                if length > max_length:
                    max_length = length
                    x_mid = (x1 + x2) / 2.0
        return x_mid

    def detect(self, frame):
        height, width = frame.shape[:2]

        # --- ROI pixel bounds ---
        rl_top, rl_bottom = int(RL_TOP_ROI * height), int(RL_BOTTOM_ROI * height)
        rl_left, rl_right = int(RL_LEFT_ROI * width), int(RL_RIGHT_ROI * width)
        ll_top, ll_bottom = int(LL_TOP_ROI * height), int(LL_BOTTOM_ROI * height)
        ll_left, ll_right = int(LL_LEFT_ROI * width), int(LL_RIGHT_ROI * width)

        cw_top, cw_bottom = int(CW_TOP_ROI * height), int(CW_BOTTOM_ROI * height)
        cw_left, cw_right = int(CW_LEFT_ROI * width), int(CW_RIGHT_ROI * width)

        # --- Crop ROIs (ROI-local coordinate space) ---
        rl_frame = frame[rl_top:rl_bottom, rl_left:rl_right].copy()
        ll_frame = frame[ll_top:ll_bottom, ll_left:ll_right].copy()
        cw_frame = frame[cw_top:cw_bottom, cw_left:cw_right].copy()

        rl_frame = rl_frame if (rl_frame is not None and rl_frame.size != 0) else None
        ll_frame = ll_frame if (ll_frame is not None and ll_frame.size != 0) else None
        cw_frame = cw_frame if (cw_frame is not None and cw_frame.size != 0) else None

        # --- Process ROI: gray -> blur -> edges -> HoughLinesP ---
        def process_roi(roi):
            if roi is None:
                return None, None, None
            roi_copy = roi.copy()
            gray = cv2.cvtColor(roi_copy, cv2.COLOR_BGR2GRAY)
            _, gray = cv2.threshold(gray, 230, 255, cv2.THRESH_BINARY)
            gray = cv2.GaussianBlur(gray, (5, 5), 0)
            # Step 3: Apply dilation to thicken the edges
            dilated_image = cv2.dilate(gray, None, iterations=1)

            # Step 4: Apply erosion to refine the edges
            eroded_image = cv2.erode(dilated_image, None, iterations=1)
            edges = cv2.Canny(eroded_image, 50, 100)
        
            lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=20,
                        minLineLength=5, maxLineGap=5)

            return roi_copy, edges, lines

        rl_draw, rl_edge, rl_lines = process_roi(rl_frame)
        ll_draw, ll_edge, ll_lines = process_roi(ll_frame)

        # -------------------------
        # CROSSWALK DETECTION USING LSD
        # -------------------------
        crosswalk = False
        cw_debug = None

        if cw_frame is not None:
            gray = cv2.cvtColor(cw_frame, cv2.COLOR_BGR2GRAY)
            _, gray = cv2.threshold(gray, 230, 255, cv2.THRESH_BINARY)
            gray = cv2.GaussianBlur(gray, (5, 5), 0)
            # Step 3: Apply dilation to thicken the edges
            dilated_image = cv2.dilate(gray, None, iterations=1)

            # Step 4: Apply erosion to refine the edges
            eroded_image = cv2.erode(dilated_image, None, iterations=1)
            edges = cv2.Canny(eroded_image, 50, 100)
            lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=20,
                        minLineLength=5, maxLineGap=5)

            vertical = 0
            horizontal = 0
            if lines is not None:
                for line in lines:
                    x0, y0, x1, y1 = line[0]
                    slope = (y1 - y0) / (x1 - x0 + 1e-6)
                    angle = abs(np.arctan(slope) * 180 / np.pi)

                    if angle < 30:
                        horizontal += 1
                    elif angle > 60:
                        vertical += 1
            
            if vertical > 2 and horizontal > 2:
                crosswalk = True


                            
        # -------------------------
        # LANE MIDPOINT (unchanged)
        # -------------------------
        rl_x_mid = self._largest_mid_x(rl_lines)
        ll_x_mid = self._largest_mid_x(ll_lines)

        rl_x_mid_full = (rl_left + rl_x_mid) if rl_x_mid is not None else None
        ll_x_mid_full = (ll_left + ll_x_mid) if ll_x_mid is not None else None

        frame_center = (width * (RL_RIGHT_ROI + LL_LEFT_ROI) / 2)
        if (rl_x_mid_full is not None) and (ll_x_mid_full is not None):
            lane_type = "both"
        elif (rl_x_mid_full is None) and (ll_x_mid_full is not None):
            lane_type = "only_left"
            frame_center = (width * (RL_RIGHT_ROI + LL_LEFT_ROI) / 2) - 20
        elif (rl_x_mid_full is not None) and (ll_x_mid_full is None):
            lane_type = "only_right"
            # frame_center = (width * (RL_RIGHT_ROI + LL_LEFT_ROI) / 2) - 20
        else:
            lane_type = "none"

        

        rl_roi_center = (rl_left + rl_right) / 2.0
        ll_roi_center = (ll_left + ll_right) / 2.0

        if rl_x_mid_full is None and ll_x_mid_full is not None:
            rl_x_mid_full = rl_roi_center
        if ll_x_mid_full is None and rl_x_mid_full is not None:
            ll_x_mid_full = ll_roi_center

        if lane_type in ("both", "only_right", "only_left"):
            lane_center = (rl_x_mid_full + ll_x_mid_full) / 2.0
        else:
            lane_center = frame_center

        error = frame_center - lane_center
        kp = LOW_KP if abs(error) < 25 else HIGH_KP
        steering_angle = 90.0 - kp * error
        if lane_type == "none":
            steering_angle = 150
        steering_angle = int(max(MIN_SERVO_ANGLE, min(MAX_SERVO_ANGLE, steering_angle)))

        # Rendering is opt-in and delegated to visualization.lane_debug_overlay.
        debug = None
        if base_config.DEBUG:
            crosswalk_lines = lines if cw_frame is not None else None
            debug = {
                "combined": frame.copy(),
                "draw_data": {
                    "kind": "classical",
                    "frame_width": int(width),
                    "frame_height": int(height),
                    "roi_bounds": {
                        "RL": (rl_left, rl_top, rl_right, rl_bottom),
                        "LL": (ll_left, ll_top, ll_right, ll_bottom),
                        "CW": (cw_left, cw_top, cw_right, cw_bottom),
                    },
                    "line_offsets": {
                        "RL": (rl_left, rl_top),
                        "LL": (ll_left, ll_top),
                        "CW": (cw_left, cw_top),
                    },
                    "lines": {
                        "RL": rl_lines, "LL": ll_lines, "CW": crosswalk_lines,
                    },
                    "midpoints": {
                        "RL": (rl_x_mid_full - rl_left) if rl_x_mid_full is not None else None,
                        "LL": (ll_x_mid_full - ll_left) if ll_x_mid_full is not None else None,
                    },
                    "frame_center_x": float(frame_center),
                    "lane_center_x": float(lane_center),
                    "crosswalk": crosswalk,
                },
            }

        return {
            "steering_angle": steering_angle,
            "error": error,
            "lane_type": lane_type,
            "crosswalk": crosswalk,
            "crosswalk_debug": cw_debug,
            "debug": debug
        }
