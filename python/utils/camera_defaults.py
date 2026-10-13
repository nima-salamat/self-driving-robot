"""Shared camera defaults for City, Race, and calibration entry points.

Keep hardware/backend defaults in a dependency-light module so importing the
camera or calibration packages never needs to import a mode runtime.
"""

CAM_WIDTH = 640
CAM_HEIGHT = 480

resize_width = 380
resize_height = 230

USBCAM_ADDR = 0
CAMERA_MODE = "picam"
CAMERA_FALLBACK_TO_OPENCV = False
