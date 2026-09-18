import json
import logging
import os

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
}

BOOL_KEYS = {
    "WITHOUT_ARDUINO", "READ_ARDUINO_OUTPUT", "USE_PID", "AUTO_UPDATE_KP",
    "USE_BEV", "DETECT_OBJECT", "STREAM", "DEBUG", "SHOW_FPS",
    "WITH_SIGN", "WITH_APRILTAG", "RECORD_VIDEO", "TAKE_PICTURE",
}


def _validate(name, value):
    if name in BOOL_KEYS and not isinstance(value, bool):
        raise ValueError(f"{name} must be boolean")

    if name in RANGES:
        low, high = RANGES[name]
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{name} must be numeric")
        if not low <= value <= high:
            raise ValueError(f"{name} must be between {low} and {high}")

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

    if name == "CAMERA_MODE" and value not in ("picam", "webcam", "opencv"):
        raise ValueError("CAMERA_MODE must be picam or webcam")

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

    if getattr(config_module, "PID_MAX_DT", 0.0) < getattr(config_module, "PID_MIN_DT", 0.0):
        raise ValueError("PID_MAX_DT must be greater than or equal to PID_MIN_DT")


def load():
    import base_config
    import modes.city.config_city as config_city
    import modes.race.config_race as config_race

    config_module = config_city if base_config.MODE == "city" else config_race
    filename = "city.json" if base_config.MODE == "city" else "race.json"

    try:
        if getattr(config_module, "CHANGE_WITH_JSON", False):
            _load_into(config_module, filename)
    except json.JSONDecodeError:
        logger.exception("Invalid JSON configuration: %s", filename)
    except (OSError, ValueError, TypeError):
        logger.exception("Invalid configuration values in %s", filename)
