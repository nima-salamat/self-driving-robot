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
            return [], frame, None, None

        h, w = frame.shape[:2]

        x1 = int(conf.AT_LEFT_ROI * w)
        y1 = int(conf.AT_TOP_ROI * h)
        x2 = int(conf.AT_RIGHT_ROI * w)
        y2 = int(conf.AT_BOTTOM_ROI * h)

        roi = frame[y1:y2, x1:x2]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        _, gray_thr = cv2.threshold(gray, 220, 255, cv2.THRESH_BINARY)

        corners, ids, _ = aruco.detectMarkers(
            gray_thr,
            self.aruco_dict,
            parameters=self.aruco_params
        )

        detected_tags = []

        if ids is not None and len(corners) > 0:
            for i in range(len(corners)):
                c = corners[i][0]

                c_global = c.copy()
                c_global[:, 0] += x1
                c_global[:, 1] += y1

                min_x, max_x = c_global[:, 0].min(), c_global[:, 0].max()
                min_y, max_y = c_global[:, 1].min(), c_global[:, 1].max()

                center_x = (min_x + max_x) / 2
                center_y = (min_y + max_y) / 2

                detected_tags.append({
                    "id": int(ids[i][0]),
                    "corners": c_global,
                    "center": (center_x, center_y),
                    "coordinate": [(int(min_x), int(min_y)), (int(max_x), int(max_y))]
                })

                if (conf.STREAM or conf.DEBUG) and debug_frame is not None:
                    cv2.polylines(debug_frame, [c_global.astype(int)], True, (0, 255, 0), 2)
                    cv2.putText(
                        debug_frame,
                        f"ID:{ids[i][0]}",
                        (int(center_x), int(center_y)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.5,
                        (0, 0, 255),
                        2
                    )

        max_area = 0
        largest_tag = None
        for tag in detected_tags:
            contour = tag["corners"].reshape((-1, 1, 2))
            area = cv2.contourArea(contour)
            if area > max_area:
                max_area = area
                largest_tag = tag

        coor = largest_tag["coordinate"] if largest_tag is not None else None

        if (conf.STREAM or conf.DEBUG) and debug_frame is not None:
            cv2.rectangle(debug_frame, (x1, y1), (x2, y2), (255, 0, 0), 2)

        return detected_tags, debug_frame, largest_tag, coor
