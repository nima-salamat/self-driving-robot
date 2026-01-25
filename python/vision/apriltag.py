import cv2
from cv2 import aruco
import base_config as temp_conf

if temp_conf.CONFIG_MODULE is not None:
    conf = temp_conf.CONFIG_MODULE
else:
    conf = temp_conf

import logging

logger = logging.getLogger(__name__)

class ApriltagDetector:
    def __init__(self):
        self.aruco_dict = aruco.getPredefinedDictionary(aruco.DICT_APRILTAG_36h11)
        self.aruco_params = aruco.DetectorParameters()
        logger.info("ArUco AprilTag 36h11 dictionary initialized")

    def detect(self, frame, debug_frame):
        if frame is None or frame.size == 0:
            return [], frame, None

        h, w = frame.shape[:2]

        # -----------------------------
        # 1) Crop ROI from the frame
        # -----------------------------
        x1 = int(conf.AT_LEFT_ROI * w)
        y1 = int(conf.AT_TOP_ROI * h)
        x2 = int(conf.AT_RIGHT_ROI * w)
        y2 = int(conf.AT_BOTTOM_ROI * h)

        roi = frame[y1:y2, x1:x2]

        # -----------------------------
        # 2) Convert ROI to gray + threshold
        # -----------------------------
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

        # Adaptive/normal threshold for better tag detection
        _, gray_thr = cv2.threshold(gray, 220, 255, cv2.THRESH_BINARY)

        # -----------------------------
        # 3) Detect markers **in ROI**
        # -----------------------------
        corners, ids, _ = aruco.detectMarkers(
            gray_thr, 
            self.aruco_dict, 
            parameters=self.aruco_params
        )

        detected_tags = []

        # -----------------------------
        # 4) Process detected corners
        # -----------------------------
        if ids is not None and len(corners) > 0:
            for i in range(len(corners)):
                c = corners[i][0]  # shape (4,2) in ROI coordinates

                # Convert ROI corners ? global frame coordinates
                c_global = c.copy()
                c_global[:, 0] += x1
                
                c_global[:, 1] += y1

                min_x, max_x = c_global[:, 0].min(), c_global[:, 0].max()
                min_y, max_y = c_global[:, 1].min(), c_global[:, 1].max()

                detected_tags.append({
                    "id": ids[i][0],
                    "corners": c_global,
                    "center": [(min_x + max_x) / 2, (min_y + max_y) / 2]
                })
                
                if (conf.STREAM or conf.DEBUG) and debug_frame is not None:
                    # Draw box + ID on full frame
                    cv2.polylines(debug_frame, [c_global.astype(int)], True, (0,255,0), 2)
                    cv2.putText(
                        debug_frame, f"ID:{ids[i][0]}",
                        (int((min_x+max_x)/2), int((min_y+max_y)/2)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,0,255), 2
                    )

        max_area = 0
        largest_tag = None
        for i in detected_tags:
            contour = i["corners"].reshape((-1, 1, 2))
            area = cv2.contourArea(contour)
            if max_area < area:
                largest_tag = i
                max_area = area
            
        # -----------------------------
        # 5) Draw ROI box on the frame
        # -----------------------------
        if (conf.STREAM or conf.DEBUG) and debug_frame is not None:
            cv2.rectangle(debug_frame, (x1, y1), (x2, y2), (255, 0, 0), 2)

        return detected_tags, debug_frame, largest_tag
