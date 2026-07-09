import os
import cv2
import logging

from base_config import BASE_DIR
from camera import Camera

# ===========================================
# Configuration
# ===========================================

IMAGE_DIR = os.path.join(BASE_DIR, "assets", "images")
os.makedirs(IMAGE_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s"
)

logger = logging.getLogger(__name__)


def get_next_filename():

    files = [
        f for f in os.listdir(IMAGE_DIR)
        if f.startswith("calib_") and f.endswith(".jpg")
    ]

    if not files:
        return os.path.join(IMAGE_DIR, "calib_001.jpg")

    numbers = [
        int(f[6:-4])
        for f in files
    ]

    return os.path.join(
        IMAGE_DIR,
        f"calib_{max(numbers)+1:03d}.jpg"
    )


def main():

    logger.info("Initializing camera...")

    camera = Camera()

    logger.info("Camera initialized successfully.")
    logger.info("Press SPACE to save an image.")
    logger.info("Press Q to quit.")

    try:

        while True:

            frame, _ = camera.capture_frame(with_resize=False)

            if frame is None:
                logger.warning("Failed to capture frame.")
                continue

            cv2.imshow("Camera Calibration", frame)

            key = cv2.waitKey(1) & 0xFF

            if key == ord(" "):

                filename = get_next_filename()

                cv2.imwrite(filename, frame)

                logger.info(
                    f"Saved calibration image: {os.path.basename(filename)}"
                )

            elif key == ord("q"):

                break

    finally:

        logger.info("Releasing camera...")

        camera.release()

        cv2.destroyAllWindows()

        logger.info("Done.")


if __name__ == "__main__":
    main()