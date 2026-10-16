import json
import logging
import os
from pathlib import Path

from traffic_sign_detector.area_filter import validate_sign_area_filter

logger = logging.getLogger(__name__)


RANGES = {
    "DELAY": (0.0, 1.0),
    "CONTROL_PERIOD": (0.001, 1.0),
    "SERIAL_TIMEOUT": (0.01, 5.0),
    "SERIAL_MAX_RETRIES": (1, 10),
    "SERIAL_STARTUP_WAIT": (0.0, 10.0),
    "SERIAL_REBOOT_WAIT": (0.0, 10.0),
    "SERIAL_RECONNECT_INTERVAL": (0.05, 10.0),
    "SERIAL_RECONNECT_TIMEOUT": (0.05, 5.0),
    "SERIAL_TELEMETRY_BUFFER_SIZE": (1, 1000),
    "SIGN_RESULT_MAX_AGE": (0.05, 10.0),
    "STOP_COMMAND_REFRESH_INTERVAL": (0.05, 10.0),
    "KP": (-100.0, 100.0),
    "KI": (-100.0, 100.0),
    "KD": (-100.0, 100.0),
    "KT": (0.0, 10.0),
    "PID_MIN_DT": (0.0001, 1.0),
    "PID_MAX_DT": (0.001, 5.0),
    "PID_DERIVATIVE_FILTER": (0.0, 1.0),
    "MIN_SERVO_ANGLE": (0.0, 180.0),
    "MAX_SERVO_ANGLE": (0.0, 180.0),
    "CAM_WIDTH": (32, 4096),
    "CAM_HEIGHT": (32, 4096),
    "resize_width": (32, 4096),
    "resize_height": (32, 4096),
    "SPEED": (-255, 255),
    "MIN_FREE_DISK_MB": (0, 1024 * 1024),
    "STREAM_PORT": (1, 65535),
    "USBCAM_ADDR": (0, 64),
    "CAMERA_FPS": (1.0, 120.0),
    "TL_MIN_SATURATION": (0,255), "TL_MIN_VALUE": (0,255), "TL_MIN_CONTOUR_AREA": (0.0,1000000.0), "TL_MIN_ACTIVE_BRIGHTNESS": (0,255),
    "TL_CONFIRMATION_WINDOW": (1,100), "TL_CONFIRMATION_GREEN_REQUIRED": (1,100),
    "LANE_THRESHOLD": (0, 255),
    "HOUGH_THRESHOLD": (1, 255),
    "HOUGH_MIN_LINE_LENGTH": (1, 500),
    "HOUGH_MAX_LINE_GAP": (0, 100),
    "HOUGH_BLUR_KERNEL": (1, 15),
}

BOOL_KEYS = {
    "WITHOUT_ARDUINO", "READ_ARDUINO_OUTPUT", "USE_PID", "AUTO_UPDATE_KP",
    "OLD_METHOD", "HOUGH_MORPH_CLOSE",
    "USE_BEV", "DETECT_OBJECT", "STREAM", "DEBUG", "SHOW_FPS",
    "WITH_SIGN", "WITH_APRILTAG", "USE_SIGN", "RECORD_VIDEO", "TAKE_PICTURE",
    "STREAM_ALLOW_CONTROL", "PERFORMANCE", "CAMERA_FALLBACK_TO_OPENCV", "APPLY_CAMERA_CALIBRATION",
    "SEND_TRAFFIC_STOP_COMMAND", "TRAFFIC_LIGHTS_ENABLED", "TRAFFIC_LIGHT_WAIT_BEFORE_CHECK",
}

INT_KEYS = {
    "LANE_THRESHOLD", "HOUGH_THRESHOLD", "HOUGH_MIN_LINE_LENGTH",
    "HOUGH_MAX_LINE_GAP", "HOUGH_BLUR_KERNEL",
}


def _validate(name, value):
    if name in {
        "SIGN_AREA_FILTER_ENABLED",
        "SIGN_AREA_FILTER_TARGETS",
        "SIGN_AREA_MIN_PX2",
    }:
        return validate_sign_area_filter(name, value)

    if name in BOOL_KEYS and not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")
    if name in INT_KEYS and (not isinstance(value, int) or isinstance(value, bool)):
        raise ValueError(f"{name} must be an integer")
    if name == "HOUGH_BLUR_KERNEL" and value % 2 == 0:
        raise ValueError("HOUGH_BLUR_KERNEL must be an odd integer")

    if name in RANGES:
        low, high = RANGES[name]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{name} must be numeric")
        if not low <= value <= high:
            raise ValueError(f"{name} must be between {low} and {high}")

    if name in {"TL_TOP_ROI","TL_BOTTOM_ROI","TL_LEFT_ROI","TL_RIGHT_ROI"}:
        if not isinstance(value,(int,float)) or isinstance(value,bool) or not 0<=value<=1: raise ValueError(f"{name} must be between 0 and 1")
    if name in {"TL_CONFIRMATION_WINDOW","TL_CONFIRMATION_GREEN_REQUIRED"} and (not isinstance(value,int) or isinstance(value,bool)): raise ValueError(f"{name} must be an integer")
    if name in {"TL_RED_HSV_RANGES","TL_GREEN_HSV_RANGES"}:
        if not isinstance(value,(list,tuple)) or not value: raise ValueError(f"{name} must contain HSV ranges")
        for pair in value:
            if not isinstance(pair,(list,tuple)) or len(pair)!=2 or any(not isinstance(b,(list,tuple)) or len(b)!=3 or any(not isinstance(v,int) or isinstance(v,bool) or not 0<=v<=255 for v in b) for b in pair): raise ValueError(f"{name} entries must be lower/upper HSV integer triples")

    if name == "PID_MAX_DT" and value < 0.001:
        raise ValueError("PID_MAX_DT is too small")

    if name == "OUTPUT_LIMITS":
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError("OUTPUT_LIMITS must contain two numbers")
        if any(not isinstance(v, (int, float)) or isinstance(v, bool) for v in value):
            raise ValueError("OUTPUT_LIMITS must contain numeric values")
        if value[0] >= value[1]:
            raise ValueError("OUTPUT_LIMITS minimum must be below maximum")

    if name == "BAUD_RATE":
        if not isinstance(value, int) or value <= 0:
            raise ValueError("BAUD_RATE must be a positive integer")

    if name == "SERIAL_PORT":
        if not isinstance(value, str) or not value.strip():
            raise ValueError("SERIAL_PORT must be a non-empty string")

    if name in {"OUTPUT_DIR", "STREAM_HOST"}:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")

    if name == "CAMERA_MODE" and value not in ("picam", "webcam", "opencv"):
        raise ValueError("CAMERA_MODE must be one of: picam, webcam, opencv")

    if name == "CITY_LANE_DETECTOR" and value not in ("default", "blsf-beta"):
        raise ValueError("CITY_LANE_DETECTOR must be one of: default, blsf-beta")

    return value


def _load_into(config_module, filename):
    if not os.path.exists(filename):
        return

    with open(filename, "r", encoding="utf-8") as f:
        configs = json.load(f)

    if not isinstance(configs, dict):
        raise ValueError(f"{filename} must contain a JSON object")

    for name, value in configs.items():
        _validate(name, value)
        setattr(config_module, name, value)


    if any(
        key in configs
        for key in ("WITH_SIGN", "WITH_APRILTAG", "USE_SIGN")
    ):
        sign = bool(getattr(config_module, "WITH_SIGN", False))
        tag = bool(getattr(config_module, "WITH_APRILTAG", False))
        legacy = bool(getattr(config_module, "USE_SIGN", False))
        if sign and tag:
            raise ValueError(
                "WITH_SIGN and WITH_APRILTAG cannot both be true"
            )
        if (
            "WITH_SIGN" not in configs
            and "WITH_APRILTAG" not in configs
            and "USE_SIGN" in configs
        ):
            marker_name = "sign" if legacy else "none"
        elif sign:
            marker_name = "sign"
        elif tag:
            marker_name = "apriltag"
        else:
            marker_name = "none"
        from stream.capabilities import set_marker_mode
        set_marker_mode(config_module, marker_name)

    roi=tuple(getattr(config_module,n,d) for n,d in (("TL_TOP_ROI",0.),("TL_BOTTOM_ROI",1.),("TL_LEFT_ROI",0.),("TL_RIGHT_ROI",1.)))
    if not (0<=roi[0]<roi[1]<=1 and 0<=roi[2]<roi[3]<=1): raise ValueError("Invalid traffic-light ROI ordering/bounds")
    if getattr(config_module,"TL_CONFIRMATION_GREEN_REQUIRED",8)>getattr(config_module,"TL_CONFIRMATION_WINDOW",10): raise ValueError("TL_CONFIRMATION_GREEN_REQUIRED cannot exceed TL_CONFIRMATION_WINDOW")

    if getattr(config_module, "PID_MAX_DT", 0.0) < getattr(config_module, "PID_MIN_DT", 0.0):
        raise ValueError("PID_MAX_DT must be greater than or equal to PID_MIN_DT")


def load():
    import base_config
    import modes.city.config_city as config_city
    import modes.race.config_race as config_race

    config_module = config_city if base_config.MODE == "city" else config_race
    filename = Path(base_config.BASE_DIR) / (
        "city.json" if base_config.MODE == "city" else "race.json"
    )

    if getattr(config_module, "CHANGE_WITH_JSON", False):
        _load_into(config_module, str(filename))

    logger.info("Configuration loaded: %s", filename)
