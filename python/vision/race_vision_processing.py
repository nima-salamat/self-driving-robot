import math
from modes.race.config_race import (
    RL_TOP_ROI, RL_BOTTOM_ROI, RL_RIGHT_ROI, RL_LEFT_ROI,
    LL_TOP_ROI, LL_BOTTOM_ROI, LL_RIGHT_ROI, LL_LEFT_ROI,
    CW_TOP_ROI, CW_BOTTOM_ROI, CW_RIGHT_ROI, CW_LEFT_ROI,
    LOW_KP, HIGH_KP, MAX_SERVO_ANGLE, MIN_SERVO_ANGLE
)
import modes.race.config_race as config_race
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

        

        # --- Crop ROIs (ROI-local coordinate space) ---
        rl_frame = frame[rl_top:rl_bottom, rl_left:rl_right].copy()
        ll_frame = frame[ll_top:ll_bottom, ll_left:ll_right].copy()

        rl_frame = rl_frame if (rl_frame is not None and rl_frame.size != 0) else None
        ll_frame = ll_frame if (ll_frame is not None and ll_frame.size != 0) else None

        # --- Process ROI: gray -> blur -> edges -> HoughLinesP ---
        def process_roi(roi):
            if roi is None:
                return None, None, None
            roi_copy = roi.copy()
            gray = cv2.cvtColor(roi_copy, cv2.COLOR_BGR2GRAY)
            _, gray = cv2.threshold(gray, 220, 255, cv2.THRESH_BINARY)
            #gray = cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_MEAN_C,\
              #cv2.THRESH_BINARY,11,2)
            #gray = cv2.GaussianBlur(gray, (9, 9), 0)
            # Step 3: Apply dilation to thicken the edges
            #dilated_image = cv2.dilate(gray, None, iterations=1)

            # Step 4: Apply erosion to refine the edges
            #eroded_image = cv2.erode(dilated_image, None, iterations=1)
            edges = cv2.Canny(gray, 100, 150)
        
            lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=20,
                        minLineLength=5, maxLineGap=5)

            return roi_copy, edges, lines

        rl_draw, rl_edge, rl_lines = process_roi(rl_frame)
        ll_draw, ll_edge, ll_lines = process_roi(ll_frame)
 
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
            #frame_center = (width * (RL_RIGHT_ROI + LL_LEFT_ROI) / 2)
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

        # -------------------------
        # DEBUG DRAWING
        # -------------------------
        debug = {"rl_draw": None, "ll_draw": None, "combined": None}

        if config_race.DEBUG:
            vis = frame.copy()

            # ROI boxes
            cv2.rectangle(vis, (rl_left, rl_top), (rl_right, rl_bottom), (255, 0, 0), 1)
            cv2.rectangle(vis, (ll_left, ll_top), (ll_right, ll_bottom), (0, 255, 0), 1)

            # draw Hough lines from RL ROI (into global image)
            if rl_lines is not None:
                for line in rl_lines:
                    x1, y1, x2, y2 = line[0]
                    # draw on rl ROI copy if available
                    if rl_draw is not None:
                        cv2.line(rl_draw, (int(x1), int(y1)), (int(x2), int(y2)), (0,255,0), 1)
                    # draw on global vis (with offset)
                    cv2.line(vis, (rl_left + int(x1), rl_top + int(y1)), (rl_left + int(x2), rl_top + int(y2)), (0,255,0), 2)
                if rl_x_mid_full is not None:
                    cv2.circle(vis, (int(rl_x_mid_full), int((rl_top + rl_bottom)/2)), 4, (0,255,0), -1)

            # draw Hough lines from LL ROI
            if ll_lines is not None:
                for line in ll_lines:
                    x1, y1, x2, y2 = line[0]
                    if ll_draw is not None:
                        cv2.line(ll_draw, (int(x1), int(y1)), (int(x2), int(y2)), (0,255,0), 1)
                    cv2.line(vis, (ll_left + int(x1), ll_top + int(y1)), (ll_left + int(x2), ll_top + int(y2)), (0,255,0), 2)
                if ll_x_mid_full is not None:
                    cv2.circle(vis, (int(ll_x_mid_full), int((ll_top + ll_bottom)/2)), 4, (0,255,0), -1)

            # show lane center / frame center
            cv2.line(vis, (int(frame_center), 0), (int(frame_center), height), (0,0,255), 1)
            cv2.line(vis, (int(lane_center), 0), (int(lane_center), height), (255,0,255), 1)

           

            debug["rl_draw"] = rl_draw
            debug["ll_draw"] = ll_draw
            debug["combined"] = vis

        return {
            "steering_angle": steering_angle,
            "error": error,
            "lane_type": lane_type,
            "debug": debug
        }
