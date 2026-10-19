from modes.race.config_race import (
    MAX_SERVO_ANGLE, MIN_SERVO_ANGLE, SERVO_CENTER, SERVO_DIRECTION,
    CAMERA_HEIGHT, CAMERA_PITCH_DEG, LANE_WIDTH, OLD_METHOD, ROI_RESIZABLE
)

import modes.race.config_race as conf
from vision.ml_lane import create_ml_lane_detector
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
        self._bev_cache_key = None
        self.ml_lane_detector = create_ml_lane_detector(conf)
        self._bev_matrix = None
        self._morph_kernel = np.ones((3, 3), np.uint8)
        self._lsd = cv2.createLineSegmentDetector(0)

    @staticmethod
    def _extract_line(line):
        """Normalize OpenCV line-segment outputs to four coordinates.

        OpenCV detectors can return each segment as either (4,) or (1, 4).
        Flattening the segment supports both formats while rejecting malformed
        input with a useful error instead of failing later during unpacking.
        """
        coordinates = np.asarray(line).reshape(-1)
        if coordinates.size != 4:
            raise ValueError(
                "Expected a line segment with 4 coordinates, "
                f"got shape {np.asarray(line).shape}"
            )
        return coordinates

    @staticmethod
    def _angle_target_score(angle, target_angle, sigma):
        diff = abs(angle - target_angle)
        return math.exp(-(diff ** 2) / (2 * sigma ** 2))

    def _expected_lane_angle(self, side):
        if getattr(conf, "USE_BEV", False):
            return 90
        camera_pitch = math.radians(CAMERA_PITCH_DEG)
        y_projection = CAMERA_HEIGHT / math.tan(-camera_pitch)
        alpha = math.degrees(math.atan((LANE_WIDTH / 2) / y_projection))
        return 90 + alpha if side == "right" else 90 - alpha

    def _best_mid_x(self, lines, roi_w, roi_h, side=""):
        if lines is None:
            return None
        
        roi_w_center = roi_w / 2
        roi_h_bottom = roi_h
        max_length = math.sqrt(math.pow(roi_w,2)+math.pow(roi_h,2))
        
        best_x_mid = None
        best_score = -1
        
        for line in lines:
            x1, y1, x2, y2 = self._extract_line(line)

            slope = (y2 - y1) / (x2 - x1 + 1e-9)
            angle = abs(math.degrees(math.atan(slope)))
            
            length = math.hypot(x2 - x1, y2 - y1)

            x_mid = (x1 + x2) / 2
            y_mid = (y1 + y2) / 2
            
            norm_length = min(length / max_length , 1)
            norm_y = min(y_mid / roi_h_bottom, 1)
            
            if side == "right":
                norm_x_side = max(0.0, min(1.0, 1.0 - (x_mid / roi_w)))
            elif side == "left":
                norm_x_side = max(0.0, min(1.0, x_mid / roi_w))
            else:
                norm_x_side = max(0.0, min(1.0, 1.0 - abs(x_mid - roi_w_center) / roi_w_center))
            
            if side == "left":
                target_angle = self._expected_lane_angle("left")
                angle_score = self._angle_target_score(angle, target_angle, sigma=20)
            elif side == "right":
                target_angle = self._expected_lane_angle("right")
                angle_score = self._angle_target_score(angle, target_angle, sigma=20)
            else:
                angle_score = self._angle_target_score(angle, 90, sigma=25)

            score = (
                0.25 * norm_length +
                0.45 * norm_x_side +
                0.10 * norm_y +
                0.20 * angle_score
            )
            
            if score > best_score:
                best_x_mid = x_mid
                best_score = score

        return best_x_mid

    def detect(self, frame, debug_frame=None):
        if self.ml_lane_detector is not None:
            visualization_enabled = bool(conf.DEBUG or conf.STREAM)
            return self.ml_lane_detector.detect(
                frame, debug_frame if visualization_enabled else None
            )

        if frame is None:
            return {
                "steering_angle": SERVO_CENTER,
                "error": 0,
                "lane_type": "none",
                "perception_valid": False,
                "debug": None,
                "kp": 0
            }

        height, width = frame.shape[:2]

        # ----------------------
        # APPLY BEV
        # ----------------------
        if hasattr(conf, 'USE_BEV') and conf.USE_BEV:
            cache_key = (
                width, height,
                conf.BEV_SRC_TL_X, conf.BEV_SRC_TL_Y,
                conf.BEV_SRC_TR_X, conf.BEV_SRC_TR_Y,
                conf.BEV_SRC_BR_X, conf.BEV_SRC_BR_Y,
                conf.BEV_SRC_BL_X, conf.BEV_SRC_BL_Y,
            )
            if cache_key != self._bev_cache_key:
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
                self._bev_matrix = cv2.getPerspectiveTransform(src_pts, dst_pts)
                self._bev_cache_key = cache_key
            frame = cv2.warpPerspective(frame, self._bev_matrix, (width, height), flags=cv2.INTER_LINEAR)
            
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

        # --- Crop ROIs ---
        rl_frame = frame[rl_top:rl_bottom, rl_left:rl_right_].copy()
        ll_frame = frame[ll_top:ll_bottom, ll_left_:ll_right].copy()

        rl_frame = rl_frame if (rl_frame is not None and rl_frame.size != 0) else None
        ll_frame = ll_frame if (ll_frame is not None and ll_frame.size != 0) else None

        # ----------------------
        # GENERATE TRAPEZOID MASKS
        # ----------------------
        mask_rl = None
        mask_ll = None
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

        # --- Process ROI: gray -> blur -> edges -> mask -> HoughLinesP ---
        def process_roi(roi, mask=None):
            if bool(getattr(conf, "OLD_METHOD", OLD_METHOD)):
                if roi is None:
                    return None, None
                
                gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                _, gray = cv2.threshold(gray, conf.LANE_THRESHOLD, 255, cv2.THRESH_BINARY)
                edges = cv2.Canny(gray, 100, 150)
                
                if mask is not None:
                    edges = cv2.bitwise_and(edges, edges, mask=mask)
                    
                legacy_method = bool(getattr(conf, "OLD_METHOD", OLD_METHOD))
                lines = cv2.HoughLinesP(
                    edges,
                    1,
                    np.pi / 180,
                    threshold=int(getattr(conf, "HOUGH_THRESHOLD", 20 if legacy_method else 15)),
                    minLineLength=max(1, int(getattr(conf, "HOUGH_MIN_LINE_LENGTH", 5))),
                    maxLineGap=max(0, int(getattr(conf, "HOUGH_MAX_LINE_GAP", 5 if legacy_method else 20))),
                )
                return edges, lines
            else:
                if roi is None:
                    return None, None

                gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                blur_kernel = max(1, int(getattr(conf, "HOUGH_BLUR_KERNEL", 3)))
                if blur_kernel % 2 == 0:
                    blur_kernel += 1
                if blur_kernel > 1:
                    gray = cv2.GaussianBlur(gray, (blur_kernel, blur_kernel), 0)
                sobel_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
                sobel_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)

                magnitude = cv2.magnitude(sobel_x, sobel_y)
                magnitude = cv2.convertScaleAbs(magnitude)

                _, edges = cv2.threshold(
                    magnitude,
                    conf.LANE_THRESHOLD,
                    255,
                    cv2.THRESH_BINARY
                )
                if bool(getattr(conf, "HOUGH_MORPH_CLOSE", True)):
                    kernel = self._morph_kernel
                    edges = cv2.morphologyEx(
                        edges,
                        cv2.MORPH_CLOSE,
                        kernel,
                        iterations=1
                    )

                if mask is not None:
                    edges = cv2.bitwise_and(edges, edges, mask=mask)

                legacy_method = bool(getattr(conf, "OLD_METHOD", OLD_METHOD))
                lines = cv2.HoughLinesP(
                    edges,
                    1,
                    np.pi / 180,
                    threshold=int(getattr(conf, "HOUGH_THRESHOLD", 20 if legacy_method else 15)),
                    minLineLength=max(1, int(getattr(conf, "HOUGH_MIN_LINE_LENGTH", 5))),
                    maxLineGap=max(0, int(getattr(conf, "HOUGH_MAX_LINE_GAP", 5 if legacy_method else 20))),
                )
                return edges, lines

        rl_edge, rl_lines = process_roi(rl_frame, mask=mask_rl)
        ll_edge, ll_lines = process_roi(ll_frame, mask=mask_ll)

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
            # No new lane estimate: preserve the last visual steering estimate.
            steering_angle = self.last_steering
        else:
            steering_angle = self.last_steering * 0.3 + 0.7 * steering_angle
            self.last_steering = steering_angle

        self.last_error = error
        
        # --------------
        # DEBUG DRAWING
        # --------------
        # Package geometry only; the optional visualization layer draws it later.
        debug = None
        if (conf.DEBUG or conf.STREAM) and debug_frame is not None:
            frame_center = (conf.RL_LEFT_ROI + conf.LL_RIGHT_ROI) * width / 2.0
            draw_data = {
                "kind": "classical",
                "frame_width": int(width),
                "frame_height": int(height),
                "roi_bounds": {
                    "RL": (rl_left, rl_top, rl_right_, rl_bottom),
                    "LL": (ll_left_, ll_top, ll_right, ll_bottom),
                },
                "line_offsets": {
                    "RL": (rl_left, rl_top),
                    "LL": (ll_left_, ll_top),
                },
                "lines": {"RL": rl_lines, "LL": ll_lines},
                "midpoints": {"RL": rl_x_mid, "LL": ll_x_mid},
                "frame_center_x": float(frame_center),
                "lane_center_offset_px": float(lane_center),
            }
            debug = {
                "combined": debug_frame,
                "draw_data": draw_data,
                "rl_edges": rl_edge,
                "ll_edges": ll_edge,
                "rl_lines": rl_lines,
                "ll_lines": ll_lines,
                "rl_offset": (rl_left, rl_top),
                "ll_offset": (ll_left_, ll_top),
            }

        # Preserve actual Hough segment geometry in frame coordinates for
        # consumers that can justify camera-local obstacle relationships.
        lane_segments_px = []
        for lines, x_offset, y_offset in (
            (rl_lines, rl_left, rl_top),
            (ll_lines, ll_left_, ll_top),
        ):
            if lines is None:
                continue
            for line in lines:
                x1, y1, x2, y2 = self._extract_line(line)
                lane_segments_px.append([
                    float(x1 + x_offset), float(y1 + y_offset),
                    float(x2 + x_offset), float(y2 + y_offset),
                ])

        return {
            "steering_angle": steering_angle,
            "error": error,
            "lane_type": lane_type,
            "perception_valid": lane_type != "none",
            "debug": debug,
            "kp": kp
            ,"perception_quality": min(1.0, 0.65 + (0.2 if lane_type == "both" else 0.0))
            ,"observed_lane_boundaries": 2 if lane_type == "both" else 1 if lane_type in ("only_left", "only_right") else 0
            ,"lane_segments_px": lane_segments_px
            ,"frame_width_px": int(width)
            ,"frame_height_px": int(height)
        }
