from types import SimpleNamespace

from modes.city import config_city


def create_camera_config(
    camera_mode=None,
    camera_index=None,
    width=None,
    height=None,
    target_fps=None,
):
    """
    Build a camera-only configuration for calibration.

    Calibration always captures raw frames, so applying an existing camera
    calibration during image collection is explicitly disabled.
    """

    config = SimpleNamespace()

    for name in (
        "CAM_WIDTH",
        "CAM_HEIGHT",
        "resize_width",
        "resize_height",
        "CAMERA_MODE",
        "USBCAM_ADDR",
        "CAMERA_FALLBACK_TO_OPENCV",
    ):
        setattr(
            config,
            name,
            getattr(config_city, name),
        )

    if camera_mode is not None:
        config.CAMERA_MODE = camera_mode
    if camera_index is not None:
        config.USBCAM_ADDR = int(camera_index)
    if width is not None:
        config.CAM_WIDTH = int(width)
    if height is not None:
        config.CAM_HEIGHT = int(height)

    config.resize_width = config.CAM_WIDTH
    config.resize_height = config.CAM_HEIGHT
    config.APPLY_CAMERA_CALIBRATION = False
    config.runtime_metrics = None
    config.MODE = "calibration"
    config.CALIBRATION_TARGET_FPS = (
        float(target_fps) if target_fps is not None else 30.0
    )

    return config
