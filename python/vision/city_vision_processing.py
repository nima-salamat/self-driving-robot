# ویژن 
from modes.city.config_city import (
    MAX_SERVO_ANGLE, MIN_SERVO_ANGLE, SERVO_CENTER, SERVO_DIRECTION,
    CAMERA_HEIGHT, CAMERA_PITCH_DEG, LANE_WIDTH, OLD_METHOD, ROI_RESIZABLE,
    CW_OLD_METHOD
)

import modes.city.config_city as conf
import math
import cv2
import numpy as np

class VisionProcessor:
    def __init__(self):
        self.last_steering = SERVO_CENTER
        self.last_error = 0
        self.rroi_unseen_counter = 0
        self.lroi_unseen_counter = 0
        self.max_unseen_counter = 10
        

    def _best_mid_x(self, lines, roi_w, roi_h, side=""):
        if lines is None:
            return None
        
        roi_w_center = roi_w / 2
        roi_h_bottom = roi_h
        max_length = math.sqrt(math.pow(roi_w,2)+math.pow(roi_h,2))
        
        best_x_mid = None
        best_score = -1
        
        for line in lines:
            x1, y1, x2, y2 = line[0]

            slope = (y2 - y1) / (x2 - x1 + 1e-9)
            angle = abs(math.degrees(math.atan(slope)))
            
            length = math.hypot(x2 - x1, y2 - y1)

            x_mid = (x1 + x2) / 2
            y_mid = (y1 + y2) / 2
            
            norm_length = min(length / max_length , 1)
            norm_y = min(y_mid / roi_h_bottom, 1)
            norm_x_dist = min(1 - abs(x_mid - roi_w_center) / roi_w_center, 1)
            
            def angle_target_score(angle, target_angle, sigma=15):
                diff = abs(angle - target_angle)
                return math.exp(-(diff ** 2) / (2 * sigma ** 2))

            def expected_lane_angle(side, h=CAMERA_HEIGHT, lane_width=LANE_WIDTH, camera_pitch_deg=CAMERA_PITCH_DEG):
 
                camera_pitch = math.radians(camera_pitch_deg)

                Yp = h / math.tan(-camera_pitch)  

                alpha = math.degrees(math.atan((lane_width / 2) / Yp))

                # اگر BEV فعال باشد، خطوط تقریباً عمودی (90 درجه) خواهند بود
                if hasattr(conf, 'USE_BEV') and conf.USE_BEV:
                    return 90

                if side == "right":
                    return 90 + alpha
                else:
                    return 90 - alpha

            if side == "left":
                target_angle = expected_lane_angle("left")
                angle_score = angle_target_score(angle, target_angle, sigma=20)
            elif side == "right":
                target_angle = expected_lane_angle("right")
                angle_score = angle_target_score(angle, target_angle, sigma=20)
            else:
                angle_score = angle_target_score(angle, 90, sigma=25)

            score = (
                0.4 * norm_length +
                0.3 * (norm_x_dist)+
                0.2 * norm_y +
                0.1 * angle_score
            )
            
            if score > best_score:
                best_x_mid = x_mid
                best_score = score

        return best_x_mid

    def detect(self, frame, debug_frame = None):
        if frame is None:
            print("Warning: Frame is None. Returning last known steering angle.")
            return {
                "steering_angle": self.last_steering,
                "error": self.last_error,
                "lane_type": "none",
                "crosswalk": False,
                "debug": {"rl_draw": None, "ll_draw": None, "combined": None, "cw_draw": None},
                "kp": 0
            }

        height, width = frame.shape[:2]

        # ----------------------
        # APPLY BEV (Bird's Eye View)
        # ----------------------
        if hasattr(conf, 'USE_BEV') and conf.USE_BEV:
            src_pts = np.float32([
                [width * conf.BEV_SRC_TL_X, height * conf.BEV_SRC_TL_Y],
                [width * conf.BEV_SRC_TR_X, height * conf.BEV_SRC_TR_Y],
                [width * conf.BEV_SRC_BR_X, height * conf.BEV_SRC_BR_Y],
                [width * conf.BEV_SRC_BL_X, height * conf.BEV_SRC_BL_Y]
            ])
            
            dst_pts = np.float32([
                [0, 0],
                [width, 0],
                [width, height],
                [0, height]
            ])
            
            matrix = cv2.getPerspectiveTransform(src_pts, dst_pts)
            frame = cv2.warpPerspective(frame, matrix, (width, height), flags=cv2.INTER_LINEAR)
            
            
        debug_frame = frame.copy() if conf.DEBUG or conf.STREAM else None

        # --- ROI pixel bounds ---
        rl_top, rl_bottom = int(conf.RL_TOP_ROI * height), int(conf.RL_BOTTOM_ROI * height)
        rl_left, rl_right = int(conf.RL_LEFT_ROI * width), int(conf.RL_RIGHT_ROI * width)
        ll_top, ll_bottom = int(conf.LL_TOP_ROI * height), int(conf.LL_BOTTOM_ROI * height)
        ll_left, ll_right = int(conf.LL_LEFT_ROI * width), int(conf.LL_RIGHT_ROI * width)
        
        if ROI_RESIZABLE:
            rl_right_ = rl_right + int((1 - conf.RL_RIGHT_ROI) * width * 1 / self.max_unseen_counter * self.rroi_unseen_counter)
            ll_left_ = ll_left + int((0 - conf.LL_LEFT_ROI) * width * 1 / self.max_unseen_counter * self.lroi_unseen_counter)
        else:
            rl_right_ = rl_right
            ll_left_ = ll_left

        cw_top, cw_bottom = int(conf.CW_TOP_ROI * height), int(conf.CW_BOTTOM_ROI * height)
        cw_left, cw_right = int(conf.CW_LEFT_ROI * width), int(conf.CW_RIGHT_ROI * width)

        # --- Crop ROIs ---
        rl_frame = frame[rl_top:rl_bottom, rl_left:rl_right_].copy()
        ll_frame = frame[ll_top:ll_bottom, ll_left_:ll_right].copy()
        cw_frame = frame[cw_top:cw_bottom, cw_left:cw_right].copy()

        rl_frame = rl_frame if (rl_frame is not None and rl_frame.size != 0) else None
        ll_frame = ll_frame if (ll_frame is not None and ll_frame.size != 0) else None
        cw_frame = cw_frame if (cw_frame is not None and cw_frame.size != 0) else None

        # ----------------------
        # APPLY TRAPEZOID MASKS 
        # ----------------------
        if hasattr(conf, 'LANE_ROI_MODE') and conf.LANE_ROI_MODE == "trapezoid":
            if rl_frame is not None:
                rl_h, rl_w = rl_frame.shape[:2]
                rl_base_w = int((conf.RL_RIGHT_ROI - conf.RL_LEFT_ROI) * width)
                pts_rl = np.array([
                    [0, 0],                                             
                    [int(rl_base_w * conf.RL_TOP_WIDTH_FACTOR), 0],     
                    [rl_w, rl_h],                                       
                    [0, rl_h]                                           
                ], np.int32)
                mask_rl = np.zeros((rl_h, rl_w), dtype=np.uint8)
                cv2.fillPoly(mask_rl, [pts_rl], 255)
                rl_frame = cv2.bitwise_and(rl_frame, rl_frame, mask=mask_rl)

            if ll_frame is not None:
                ll_h, ll_w = ll_frame.shape[:2]
                ll_base_w = int((conf.LL_RIGHT_ROI - conf.LL_LEFT_ROI) * width)
                pts_ll = np.array([
                    [ll_w - int(ll_base_w * conf.LL_TOP_WIDTH_FACTOR), 0], 
                    [ll_w, 0],                                             
                    [ll_w, ll_h],                                          
                    [0, ll_h]                                              
                ], np.int32)
                mask_ll = np.zeros((ll_h, ll_w), dtype=np.uint8)
                cv2.fillPoly(mask_ll, [pts_ll], 255)
                ll_frame = cv2.bitwise_and(ll_frame, ll_frame, mask=mask_ll)

        if hasattr(conf, 'CW_TRAPEZOID_MODE') and conf.CW_TRAPEZOID_MODE:
            if cw_frame is not None:
                cw_h, cw_w = cw_frame.shape[:2]
                pts_cw = np.array([
                    [int(cw_w * (1 - conf.CW_TOP_WIDTH_FACTOR) / 2), 0], 
                    [int(cw_w * (1 + conf.CW_TOP_WIDTH_FACTOR) / 2), 0], 
                    [cw_w, cw_h],                                        
                    [0, cw_h]                                            
                ], np.int32)
                mask_cw = np.zeros((cw_h, cw_w), dtype=np.uint8)
                cv2.fillPoly(mask_cw, [pts_cw], 255)
                cw_frame = cv2.bitwise_and(cw_frame, cw_frame, mask=mask_cw)

        # --- Process ROI: gray -> blur -> edges -> HoughLinesP ---
        def process_roi(roi):
            if OLD_METHOD:
                if roi is None:
                    return None, None
                
                gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                _, gray = cv2.threshold(gray, conf.LANE_THRESHOLD, 255, cv2.THRESH_BINARY)
                edges = cv2.Canny(gray, 100, 150)
                lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=20,
                                    minLineLength=5, maxLineGap=5)
                return edges, lines
            else:
                if roi is None:
                    return None, None

                gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                gray = cv2.GaussianBlur(gray, (5, 5), 0)
                sobel_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
                sobel_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)

                magnitude = cv2.magnitude(sobel_x, sobel_y)
                magnitude = cv2.convertScaleAbs(magnitude)

                _, edges = cv2.threshold(magnitude, conf.LANE_THRESHOLD, 255, cv2.THRESH_BINARY)
                kernel = np.ones((3, 3), np.uint8)
                edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=1)

                lines = cv2.HoughLinesP(edges, rho=1, theta=np.pi / 180, threshold=20,
                                    minLineLength=5, maxLineGap=5)
                return edges, lines

        rl_edge, rl_lines = process_roi(rl_frame)
        ll_edge, ll_lines = process_roi(ll_frame)

        # ---------------------
        # CROSSWALK DETECTION
        # ---------------------
        crosswalk = False
        cw_lines = []

        if cw_frame is not None:
            if CW_OLD_METHOD:
                gray = cv2.cvtColor(cw_frame, cv2.COLOR_BGR2GRAY)
                _, gray = cv2.threshold(gray, conf.CROSSWALK_THRESHOLD, 255, cv2.THRESH_BINARY)
                edges = cv2.Canny(gray, 100, 150)

                lsd = cv2.createLineSegmentDetector(0)
                lines, _, _, _ = lsd.detect(edges)
            else:
                gray = cv2.cvtColor(cw_frame, cv2.COLOR_BGR2GRAY)
                _, gray = cv2.threshold(gray, conf.CROSSWALK_THRESHOLD, 255, cv2.THRESH_BINARY)
                edges = cv2.Canny(gray, 100, 150)
                lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=20,
                                    minLineLength=5, maxLineGap=5)
            
            vertical = 0
            horizontal = 0
            cw_roi_diagonal = math.sqrt(math.pow(cw_right - cw_left, 2) + math.pow(cw_bottom - cw_top, 2))
            crosswalk_pixel_dist = (3.5 / 5) * (cw_bottom - cw_top) 
            line_min_length = max(cw_roi_diagonal / 20, 10)
            lowest_horizontal_line = None
            if lines is not None:
                for line in lines:
                    x0, y0, x1, y1 = line[0] 
                    slope = (y1 - y0) / (x1 - x0 + 1e-6)
                    angle = abs(np.arctan(slope) * 180 / np.pi)
                    length = math.hypot(x1 - x0, y1 - y0)
                    
                    if length >= line_min_length:
                        if angle <= 30:
                            horizontal += 1
                            cw_lines.append(line)
                            if lowest_horizontal_line is not None:
                                if max(y0, y1) > max(lowest_horizontal_line[0][1],lowest_horizontal_line[0][3]):
                                    lowest_horizontal_line = line
                            else:
                                lowest_horizontal_line = line
                                    
                        elif angle >= 60:
                            vertical += 1
                            cw_lines.append(line)
                        
            if vertical >= 3 and horizontal >= 2:
                if lowest_horizontal_line is not None:
                    if max(lowest_horizontal_line[0][1],lowest_horizontal_line[0][3]) > crosswalk_pixel_dist:
                        crosswalk = True
            
        # --------------
        # LANE MIDPOINT 
        # --------------
        rl_current_w = rl_right_ - rl_left
        ll_current_w = ll_right - ll_left_

        rl_x_mid = self._best_mid_x(rl_lines, rl_current_w, height * abs(conf.RL_BOTTOM_ROI - conf.RL_TOP_ROI), "right")
        ll_x_mid = self._best_mid_x(ll_lines, ll_current_w, height * abs(conf.LL_BOTTOM_ROI - conf.LL_TOP_ROI), "left")

        rl_x_mid_full = rl_x_mid
        ll_x_mid_full = ll_x_mid

        frame_center = (conf.RL_LEFT_ROI + conf.LL_RIGHT_ROI) * width / 2

        if (rl_x_mid_full is not None) and (ll_x_mid_full is not None):
            lane_type = "both"
            self.rroi_unseen_counter -= 1
            self.lroi_unseen_counter -= 1
        elif (rl_x_mid_full is None) and (ll_x_mid_full is not None):
            lane_type = "only_left"
            self.rroi_unseen_counter += 2
        elif (rl_x_mid_full is not None) and (ll_x_mid_full is None):
            lane_type = "only_right"
            self.lroi_unseen_counter += 2
        else:
            lane_type = "none"
            self.rroi_unseen_counter += 2
            self.lroi_unseen_counter += 2  
        
        self.rroi_unseen_counter = max(0, min(self.max_unseen_counter, self.rroi_unseen_counter))
        self.lroi_unseen_counter = max(0, min(self.max_unseen_counter, self.lroi_unseen_counter))

        rl_roi_center = abs(rl_left - rl_right_) / 2.0
        ll_roi_center = abs(ll_left_ - ll_right) / 2.0

        if rl_x_mid_full is None and ll_x_mid_full is not None:
            rl_x_mid_full = ll_x_mid_full
        if ll_x_mid_full is None and rl_x_mid_full is not None:
            ll_x_mid_full = rl_x_mid_full

        if lane_type in ("both", "only_right", "only_left"):
            lane_center = (rl_roi_center - rl_x_mid_full + ll_roi_center - ll_x_mid_full) / 2.0
        else:
            lane_center = frame_center
            
        min_error = frame_center - (ll_right + rl_right) / 2
        max_error = frame_center - (ll_left + rl_left) / 2 
        
        error = -lane_center
        
        if error < 0:
            kp = (180 - SERVO_CENTER) / abs(min_error) 
        elif error > 0:
            kp = SERVO_CENTER / abs(max_error)
        else:
            kp = 0

        if SERVO_DIRECTION == "ltr":
            steering_angle = SERVO_CENTER - kp * error
        elif SERVO_DIRECTION == "rtl":
            steering_angle = SERVO_CENTER + kp * error
        else:
            steering_angle = SERVO_CENTER - kp * error
        
        steering_angle = int(max(MIN_SERVO_ANGLE, min(MAX_SERVO_ANGLE, steering_angle)))
        
        if lane_type == "none":
               steering_angle = 150
        else:
          steering_angle = self.last_steering * 0.3 + 0.7 * steering_angle
          self.last_steering = steering_angle

        self.last_error = error
        
        # --------------
        # DEBUG DRAWING
        # --------------
        debug = {"rl_draw": None, "ll_draw": None, "combined": None, "crosswalk_draw": None}
        
        if (conf.DEBUG or conf.STREAM) and debug_frame is not None:    
            def scale(points):
                result = []
                for x in points:
                    result.append((w_dbg / width) * x)
                return result
            vis = debug_frame
            h_dbg, w_dbg = vis.shape[:2]
            
            rl_top, rl_bottom = int(conf.RL_TOP_ROI * h_dbg), int(conf.RL_BOTTOM_ROI * h_dbg)
            rl_left, rl_right = int(conf.RL_LEFT_ROI * w_dbg), int(conf.RL_RIGHT_ROI * w_dbg)
            ll_top, ll_bottom = int(conf.LL_TOP_ROI * h_dbg), int(conf.LL_BOTTOM_ROI * h_dbg)
            ll_left, ll_right = int(conf.LL_LEFT_ROI * w_dbg), int(conf.LL_RIGHT_ROI * w_dbg)
            cw_top, cw_bottom = int(conf.CW_TOP_ROI * h_dbg), int(conf.CW_BOTTOM_ROI * h_dbg)
            cw_left, cw_right = int(conf.CW_LEFT_ROI * w_dbg), int(conf.CW_RIGHT_ROI * w_dbg)
            
            if ROI_RESIZABLE:
                rl_right += int((1 - conf.RL_RIGHT_ROI) * w_dbg * 1 / self.max_unseen_counter * self.rroi_unseen_counter)
                ll_left += int((0 - conf.LL_LEFT_ROI) * w_dbg * 1 / self.max_unseen_counter * self.lroi_unseen_counter)

            rl_draw = debug_frame[rl_top:rl_bottom, rl_left:rl_right].copy()
            ll_draw = debug_frame[ll_top:ll_bottom, ll_left:ll_right].copy()
            cw_draw = debug_frame[cw_top:cw_bottom, cw_left:cw_right].copy()
            
            frame_center = (conf.RL_LEFT_ROI + conf.LL_RIGHT_ROI) * w_dbg / 2
            
            rl_roi_center = abs(rl_left - rl_right) / 2.0
            ll_roi_center = abs(ll_left - ll_right) / 2.0
            if rl_x_mid_full is None and ll_x_mid_full is None:
                lane_center = frame_center
            else:
                rl_x_mid_full = (w_dbg / width)*rl_x_mid_full
                ll_x_mid_full = (w_dbg / width)*ll_x_mid_full
                lane_center = (rl_roi_center-rl_x_mid_full + ll_roi_center-ll_x_mid_full) / 2.0

            if hasattr(conf, 'LANE_ROI_MODE') and conf.LANE_ROI_MODE == "trapezoid":
                rl_base_w_dbg = int((conf.RL_RIGHT_ROI - conf.RL_LEFT_ROI) * w_dbg)
                pts_rl_vis = np.array([
                    [rl_left, rl_top],
                    [rl_left + int(rl_base_w_dbg * conf.RL_TOP_WIDTH_FACTOR), rl_top],
                    [rl_right, rl_bottom],
                    [rl_left, rl_bottom]
                ], np.int32)
                cv2.polylines(vis, [pts_rl_vis], True, (255, 0, 0), 1)

                ll_base_w_dbg = int((conf.LL_RIGHT_ROI - conf.LL_LEFT_ROI) * w_dbg)
                pts_ll_vis = np.array([
                    [ll_right - int(ll_base_w_dbg * conf.LL_TOP_WIDTH_FACTOR), ll_top],
                    [ll_right, ll_top],
                    [ll_right, ll_bottom],
                    [ll_left, ll_bottom]
                ], np.int32)
                cv2.polylines(vis, [pts_ll_vis], True, (0, 255, 0), 1)
            else:
                cv2.rectangle(vis, (rl_left, rl_top), (rl_right, rl_bottom), (255, 0, 0), 1)
                cv2.rectangle(vis, (ll_left, ll_top), (ll_right, ll_bottom), (0, 255, 0), 1)

            if hasattr(conf, 'CW_TRAPEZOID_MODE') and conf.CW_TRAPEZOID_MODE:
                cw_w_dbg = cw_right - cw_left
                pts_cw_vis = np.array([
                    [cw_left + int(cw_w_dbg * (1 - conf.CW_TOP_WIDTH_FACTOR) / 2), cw_top],
                    [cw_left + int(cw_w_dbg * (1 + conf.CW_TOP_WIDTH_FACTOR) / 2), cw_top],
                    [cw_right, cw_bottom],
                    [cw_left, cw_bottom]
                ], np.int32)
                cv2.polylines(vis, [pts_cw_vis], True, (0, 255, 255), 1)
            else:
                cv2.rectangle(vis, (cw_left + 1, cw_top), (cw_right - 1, cw_bottom), (0, 255, 255), 1)

            # draw Hough lines from RL ROI
            if rl_lines is not None:
                for line in rl_lines:
                    x1, y1, x2, y2 = scale(line[0])
                    if rl_draw is not None:
                        cv2.line(rl_draw, (int(x1), int(y1)), (int(x2), int(y2)), (0,255,0), 1)
                    cv2.line(vis, (rl_left + int(x1), rl_top + int(y1)), (rl_left + int(x2), rl_top + int(y2)), (0,255,0), 2)
                if rl_x_mid is not None:
                    cv2.circle(vis, (int(rl_x_mid), int((rl_top + rl_bottom)/2)), 4, (0,255,0), -1)

            # draw Hough lines from LL ROI
            if ll_lines is not None:
                for line in ll_lines:
                    x1, y1, x2, y2 = scale(line[0])
                    if ll_draw is not None:
                        cv2.line(ll_draw, (int(x1), int(y1)), (int(x2), int(y2)), (0,255,0), 1)
                    cv2.line(vis, (ll_left + int(x1), ll_top + int(y1)), (ll_left + int(x2), ll_top + int(y2)), (0,255,0), 2)
                if ll_x_mid is not None:
                    cv2.circle(vis, (int(ll_x_mid), int((ll_top + ll_bottom)/2)), 4, (0,255,0), -1)

            # show lane center / frame center
            cv2.line(vis, (int(frame_center), 0), (int(frame_center), h_dbg), (0,0,255), 1)
            cv2.line(vis, (int(lane_center), 0), (int(lane_center), h_dbg), (255,0,255), 1)
                        
            if cw_lines is not None:
                for line in cw_lines:
                    x1, y1, x2, y2 = scale(line[0])
                    if cw_draw is not None:
                        cv2.line(cw_draw, (int(x1), int(y1)), (int(x2), int(y2)), (0,255,0), 1)
                    cv2.line(vis, (cw_left + (int(x1)), cw_top + int(y1)), (cw_left + int(x2), cw_top + int(y2)), (0,255,255), 2)
                
            debug["rl_draw"] = rl_draw
            debug["ll_draw"] = ll_draw
            debug["cw_draw"] = cw_draw
            debug["combined"] = vis

        return {
            "steering_angle": steering_angle,
            "error": error,
            "lane_type": lane_type,
            "crosswalk": crosswalk,
            "debug": debug,
            "kp": kp
        }