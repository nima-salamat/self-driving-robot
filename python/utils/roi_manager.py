import cv2
import numpy as np


def crop_image(
    frame,
    TOP_ROI,
    BOTTOM_ROI,
    LEFT_ROI,
    RIGHT_ROI,
    LEFT_TOP_WIDTH_FACTOR=None,
    RIGHT_TOP_WIDTH_FACTOR=None,
    TOP_WIDTH_FACTOR=None,
):
    """
    Crop a rectangular ROI and optionally apply a trapezoidal mask.

    Parameters
    ----------
    TOP_ROI, BOTTOM_ROI, LEFT_ROI, RIGHT_ROI : float
        ROI boundaries as ratios in the range [0, 1].

    LEFT_TOP_WIDTH_FACTOR : float, optional
        Width ratio of the top-left side of the trapezoid.

    RIGHT_TOP_WIDTH_FACTOR : float, optional
        Width ratio of the top-right side of the trapezoid.

    TOP_WIDTH_FACTOR : float, optional
        Symmetric top width ratio. Overrides individual left/right values.
    """

    height, width = frame.shape[:2]

    # Convert normalized ROI coordinates to pixel coordinates
    top = int(TOP_ROI * height)
    bottom = int(BOTTOM_ROI * height)
    left = int(LEFT_ROI * width)
    right = int(RIGHT_ROI * width)

    # Crop rectangular ROI
    roi = frame[top:bottom, left:right]

    # Return immediately if no trapezoidal mask is requested
    if (
        LEFT_TOP_WIDTH_FACTOR is None
        and RIGHT_TOP_WIDTH_FACTOR is None
        and TOP_WIDTH_FACTOR is None
    ):
        return roi

    h, w = roi.shape[:2]

    # Use the same width factor for both sides if specified
    if TOP_WIDTH_FACTOR is not None:
        LEFT_TOP_WIDTH_FACTOR = TOP_WIDTH_FACTOR
        RIGHT_TOP_WIDTH_FACTOR = TOP_WIDTH_FACTOR

    # Default to full width if one side is not specified
    if LEFT_TOP_WIDTH_FACTOR is None:
        LEFT_TOP_WIDTH_FACTOR = 1.0

    if RIGHT_TOP_WIDTH_FACTOR is None:
        RIGHT_TOP_WIDTH_FACTOR = 1.0

    # Compute top-left and top-right x coordinates
    left_top = int((1 - LEFT_TOP_WIDTH_FACTOR) * w / 2)
    right_top = int((1 + RIGHT_TOP_WIDTH_FACTOR) * w / 2)

    # Define trapezoid vertices
    pts = np.array(
        [
            [left_top, 0],
            [right_top, 0],
            [w, h],
            [0, h],
        ],
        dtype=np.int32,
    )

    # Create trapezoidal mask
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.fillPoly(mask, [pts], 255)

    # Apply mask to the cropped ROI
    return cv2.bitwise_and(roi, roi, mask=mask)
