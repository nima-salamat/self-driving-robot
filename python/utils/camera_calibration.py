import cv2
import numpy as np
import os
import logging

from base_config import BASE_DIR

logger = logging.getLogger(__name__)


class CameraCalibration:

    def __init__(self):

        self.enabled = False
        self.camera_matrix = None
        self.dist_coeffs = None
        self.new_camera_matrix = None

        calibration_file = os.path.join(
            BASE_DIR,
            "assets",
            "camera_calibration.npz"
        )

        if not os.path.exists(calibration_file):

            logger.warning(
                "Calibration file not found. Using raw camera frames."
            )

            return


        try:

            data = np.load(calibration_file)

            self.camera_matrix = data["cameraMatrix"]
            self.dist_coeffs = data["distCoeffs"]

            self.enabled = True

            logger.info(
                "Camera calibration loaded successfully."
            )

        except Exception as e:

            logger.error(
                f"Failed to load calibration file: {e}"
            )

            self.enabled = False



    def undistort(self, frame):

        # No calibration -> return original frame
        if not self.enabled:
            return frame


        h, w = frame.shape[:2]


        if self.new_camera_matrix is None:

            self.new_camera_matrix, self.roi = (
                cv2.getOptimalNewCameraMatrix(
                    self.camera_matrix,
                    self.dist_coeffs,
                    (w, h),
                    1,
                    (w, h)
                )
            )


        return cv2.undistort(
            frame,
            self.camera_matrix,
            self.dist_coeffs,
            None,
            self.new_camera_matrix
        )
    

