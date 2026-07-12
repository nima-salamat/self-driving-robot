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
