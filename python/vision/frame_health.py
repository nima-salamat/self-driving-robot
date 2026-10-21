"""Cheap camera-frame health checks shared by the City and Race control loops."""

import numpy as np


def is_camera_frame_obscured(frame):
    """Return True only for an effectively all-black/covered camera frame.

    Sampling a small grid keeps the check cheap enough for every control cycle.
    A dark scene with a meaningful number of brighter pixels is not treated as
    an occlusion. Invalid/missing frames are handled by Camera.capture_frame's
    existing validity path and therefore return False here.
    """
    if not isinstance(frame, np.ndarray) or frame.size == 0 or frame.ndim not in (2, 3):
        return False
    height, width = frame.shape[:2]
    if height <= 0 or width <= 0:
        return False
    step_y = max(1, height // 48)
    step_x = max(1, width // 64)
    sample = frame[::step_y, ::step_x]
    if sample.ndim == 3:
        if sample.shape[2] < 3:
            sample = sample[..., 0]
        else:
            sample = np.max(sample[..., :3], axis=2)
    try:
        brightness = np.asarray(sample, dtype=np.float32)
    except (TypeError, ValueError, OverflowError):
        return False
    if brightness.size == 0 or not np.isfinite(brightness).all():
        return False
    mean_brightness = float(np.mean(brightness))
    bright_fraction = float(np.count_nonzero(brightness > 16.0)) / float(brightness.size)
    return mean_brightness <= 4.0 and bright_fraction <= 0.002
