import os
import glob
import logging

import cv2
import numpy as np

from base_config import BASE_DIR

# ===========================================
# Configuration
# ===========================================

CHECKERBOARD = (11, 7)

IMAGE_DIR = os.path.join(BASE_DIR, "assets", "images")

OUTPUT_FILE = os.path.join(
    BASE_DIR,
    "assets",
    "camera_calibration.npz"
)

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s"
)

logger = logging.getLogger(__name__)


def main():

    logger.info("Searching calibration images...")

    image_paths = sorted(
        glob.glob(os.path.join(IMAGE_DIR, "*.jpg"))
    )

    if len(image_paths) == 0:
        logger.error("No calibration images found.")
        return

    logger.info(f"Found {len(image_paths)} images.")

    criteria = (
        cv2.TERM_CRITERIA_EPS +
        cv2.TERM_CRITERIA_MAX_ITER,
        30,
        0.001
    )

    objp = np.zeros(
        (CHECKERBOARD[0] * CHECKERBOARD[1], 3),
        np.float32
    )

    objp[:, :2] = np.mgrid[
        0:CHECKERBOARD[0],
        0:CHECKERBOARD[1]
    ].T.reshape(-1, 2)

    objpoints = []
    imgpoints = []

    image_size = None

    success = 0
    failed = 0

    for image_path in image_paths:

        filename = os.path.basename(image_path)

        logger.info(f"Processing {filename}")

        image = cv2.imread(image_path)

        if image is None:
            logger.warning("Unable to load image.")
            failed += 1
            continue

        gray = cv2.cvtColor(
            image,
            cv2.COLOR_BGR2GRAY
        )

        image_size = gray.shape[::-1]

        found, corners = cv2.findChessboardCorners(
            gray,
            CHECKERBOARD
        )

        if not found:
            logger.warning("Chessboard not detected.")
            failed += 1
            continue

        corners = cv2.cornerSubPix(
            gray,
            corners,
            (11, 11),
            (-1, -1),
            criteria
        )

        objpoints.append(objp)
        imgpoints.append(corners)

        success += 1

        logger.info("Chessboard detected.")

    logger.info(f"Valid images : {success}")
    logger.info(f"Invalid images : {failed}")

    if success < 10:
        logger.error(
            "At least 10 valid calibration images are required."
        )
        return

    logger.info("Running camera calibration...")

    rms, cameraMatrix, distCoeffs, rvecs, tvecs = cv2.calibrateCamera(
        objpoints,
        imgpoints,
        image_size,
        None,
        None
    )

    logger.info(f"Calibration RMS Error : {rms:.6f}")

    logger.info("Camera Matrix:")
    logger.info(f"\n{cameraMatrix}")

    logger.info("Distortion Coefficients:")
    logger.info(f"\n{distCoeffs}")

    np.savez(
        OUTPUT_FILE,
        cameraMatrix=cameraMatrix,
        distCoeffs=distCoeffs
    )

    logger.info(f"Calibration saved successfully.")
    logger.info(f"Output file: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()