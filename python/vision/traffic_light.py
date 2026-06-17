import cv2
import numpy as np
from modes.city.config_city import (
    TL_TOP_ROI,
    TL_BOTTOM_ROI,
    TL_LEFT_ROI,
    TL_RIGHT_ROI,
)
import modes.city.config_city as config_city

class TrafficLightDetector:
    def __init__(self):
        pass
    
    def detect(self, frame):
        
        if frame is None:
            return None, None
        
        height, width = frame.shape[:2]
        
        # FIX: convert to int
        tl_left   = int(TL_LEFT_ROI   * width)
        tl_right  = int(TL_RIGHT_ROI  * width)
        tl_top    = int(TL_TOP_ROI    * height)
        tl_bottom = int(TL_BOTTOM_ROI * height)
        
        frame = frame[tl_top:tl_bottom, tl_left:tl_right]
        
        debug_frame = frame.copy() if config_city.DEBUG else None
        
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        
        colors = {
            "RED": [
                ([0,100,100], [10,255,255]),
                ([170,100,100], [180,255,255])
            ],
            "GREEN": [
                ([40,50,50], [90,255,255])
            ]
        }
        
        light_color = None
        
        for color_name, ranges in colors.items():
            mask_color = None
            
            for lower, upper in ranges:
                lower = np.array(lower)
                upper = np.array(upper)
                m = cv2.inRange(hsv, lower, upper)
                
                if mask_color is None:
                    mask_color = m
                else:
                    mask_color = cv2.bitwise_or(mask_color, m)

            mask_color = cv2.medianBlur(mask_color, 5)

            contours, _ = cv2.findContours(mask_color, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            
            for c in contours:
                if cv2.contourArea(c) < 5:
                    continue
                
                mask_temp = np.zeros_like(mask_color)
                cv2.drawContours(mask_temp, [c], -1, 255, -1)
                
                mean_val = cv2.mean(hsv[:,:,2], mask=mask_temp)[0]
                if mean_val < 180:
                    continue
                
                light_color = color_name
                
                if config_city.DEBUG:
                    (cx, cy), radius = cv2.minEnclosingCircle(c)
                    center = (int(cx), int(cy))
                    radius = int(radius)
                    cv2.circle(debug_frame, center, radius, (0,255,0), 2)
                    cv2.putText(debug_frame, f"{color_name} ({int(mean_val)})",
                                (center[0]-radius, center[1]-radius-5),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 1)

            if light_color is not None:
                break
        
        return light_color, debug_frame
