"""Per-simulation-mode settings; never writes into city.json or race.json."""
import json
import math
import os
import tempfile
from pathlib import Path


SIMULATOR_KEYS = {
    "SIMULATOR_HOST", "SIMULATOR_PORT", "SIMULATOR_TIMEOUT_S",
    "SIMULATOR_VEHICLE_FILTER", "SIMULATOR_VEHICLE_BLUEPRINT", "SIMULATOR_MAP",
    "SIMULATOR_SPAWN_POINT_INDEX", "CITY_LANE_DETECTOR", "SIMULATOR_LIDAR_ENABLED",
    "SIMULATOR_LIDAR_RANGE_M", "SIMULATOR_LIDAR_CHANNELS",
    "SIMULATOR_LIDAR_POINTS_PER_SECOND", "SIMULATOR_LIDAR_ROTATION_FREQUENCY",
    "SIMULATOR_CAMERA_FOV", "SIMULATOR_CAMERA_X", "SIMULATOR_CAMERA_Y", "SIMULATOR_CAMERA_Z",
    "SIMULATOR_CAMERA_PITCH", "SIMULATOR_CAMERA_YAW", "SIMULATOR_CAMERA_ROLL", "SIMULATOR_TARGET_SPEED",
    "SIMULATOR_THROTTLE_LIMIT", "SIMULATOR_STOP_ON_LOST_LANE",
    "SIMULATOR_STOP_ON_CROSSWALK", "SIMULATOR_OBSTACLE_STOP_DISTANCE_CM",
    "SIMULATOR_STEERING_INVERTED", "SIMULATOR_AVIS_SENSOR_ANGLE",
    "MIN_SERVO_ANGLE", "SERVO_CENTER", "MAX_SERVO_ANGLE", "SERVO_DIRECTION",
    "ENCODER_PULSE_DISTANCE_CM", "ENCODER_WHEELBASE_CM",
    "USE_BEV", "USE_ML_LANE_DETECTOR", "ML_LANE_MODEL", "DEBUG",
    "LANE_THRESHOLD", "HOUGH_THRESHOLD", "HOUGH_MIN_LINE_LENGTH",
    "HOUGH_MAX_LINE_GAP", "HOUGH_BLUR_KERNEL", "HOUGH_MORPH_CLOSE",
    "CROSSWALK_THRESHOLD", "CROSSWALK_VERTICAL_MIN_LINES",
    "CROSSWALK_HORIZONTAL_MIN_LINES", "LANE_ROI_MODE", "CW_TRAPEZOID_MODE",
    "RL_TOP_WIDTH_FACTOR", "LL_TOP_WIDTH_FACTOR", "CW_TOP_WIDTH_FACTOR",
    "OLD_METHOD", "CW_OLD_METHOD", "CAMERA_PITCH_DEG", "CAMERA_HEIGHT", "LANE_WIDTH",
    "BEV_SRC_TL_X", "BEV_SRC_TL_Y", "BEV_SRC_TR_X", "BEV_SRC_TR_Y",
    "BEV_SRC_BR_X", "BEV_SRC_BR_Y", "BEV_SRC_BL_X", "BEV_SRC_BL_Y",
    "RL_TOP_ROI", "RL_BOTTOM_ROI", "RL_LEFT_ROI", "RL_RIGHT_ROI",
    "LL_TOP_ROI", "LL_BOTTOM_ROI", "LL_LEFT_ROI", "LL_RIGHT_ROI",
    "CW_TOP_ROI", "CW_BOTTOM_ROI", "CW_LEFT_ROI", "CW_RIGHT_ROI",
}
BOOL_KEYS = {
    "SIMULATOR_LIDAR_ENABLED", "SIMULATOR_STOP_ON_LOST_LANE",
    "SIMULATOR_STOP_ON_CROSSWALK", "SIMULATOR_STEERING_INVERTED", "USE_BEV",
    "USE_ML_LANE_DETECTOR", "DEBUG", "HOUGH_MORPH_CLOSE",
    "CW_TRAPEZOID_MODE", "OLD_METHOD", "CW_OLD_METHOD",
}
INT_KEYS = {
    "SIMULATOR_PORT", "SIMULATOR_LIDAR_CHANNELS",
    "SIMULATOR_LIDAR_POINTS_PER_SECOND", "SIMULATOR_AVIS_SENSOR_ANGLE",
    "SIMULATOR_SPAWN_POINT_INDEX", "LANE_THRESHOLD", "HOUGH_THRESHOLD",
    "HOUGH_MIN_LINE_LENGTH", "HOUGH_MAX_LINE_GAP", "HOUGH_BLUR_KERNEL",
    "CROSSWALK_THRESHOLD", "CROSSWALK_VERTICAL_MIN_LINES",
    "CROSSWALK_HORIZONTAL_MIN_LINES",
}
STRING_KEYS = {
    "SIMULATOR_HOST", "SIMULATOR_VEHICLE_FILTER", "SIMULATOR_VEHICLE_BLUEPRINT",
    "SIMULATOR_MAP", "CITY_LANE_DETECTOR", "ML_LANE_MODEL", "LANE_ROI_MODE", "SERVO_DIRECTION",
}
POSITIVE_KEYS = {
    "SIMULATOR_TIMEOUT_S", "SIMULATOR_LIDAR_RANGE_M",
    "SIMULATOR_LIDAR_ROTATION_FREQUENCY", "SIMULATOR_CAMERA_FOV",
    "ENCODER_PULSE_DISTANCE_CM", "CAMERA_HEIGHT", "LANE_WIDTH",
}
NONNEGATIVE_KEYS = {"SIMULATOR_TARGET_SPEED", "SIMULATOR_OBSTACLE_STOP_DISTANCE_CM"}
ROI_KEYS = {"RL_TOP_ROI", "RL_BOTTOM_ROI", "RL_LEFT_ROI", "RL_RIGHT_ROI",
            "LL_TOP_ROI", "LL_BOTTOM_ROI", "LL_LEFT_ROI", "LL_RIGHT_ROI",
            "CW_TOP_ROI", "CW_BOTTOM_ROI", "CW_LEFT_ROI", "CW_RIGHT_ROI"}
BEV_KEYS = {
    "BEV_SRC_TL_X", "BEV_SRC_TL_Y", "BEV_SRC_TR_X", "BEV_SRC_TR_Y",
    "BEV_SRC_BR_X", "BEV_SRC_BR_Y", "BEV_SRC_BL_X", "BEV_SRC_BL_Y",
}
ROI_FACTOR_KEYS = {"RL_TOP_WIDTH_FACTOR", "LL_TOP_WIDTH_FACTOR", "CW_TOP_WIDTH_FACTOR"}
NUMERIC_KEYS = POSITIVE_KEYS | NONNEGATIVE_KEYS | ROI_KEYS | BEV_KEYS | ROI_FACTOR_KEYS | {
    "SIMULATOR_THROTTLE_LIMIT", "ENCODER_WHEELBASE_CM", "SIMULATOR_CAMERA_X",
    "MIN_SERVO_ANGLE", "SERVO_CENTER", "MAX_SERVO_ANGLE",
    "SIMULATOR_CAMERA_Y", "SIMULATOR_CAMERA_Z", "SIMULATOR_CAMERA_PITCH",
    "SIMULATOR_CAMERA_YAW", "SIMULATOR_CAMERA_ROLL", "CAMERA_PITCH_DEG",
}


def settings_path(config, mode):
    base = getattr(config, "BASE_DIR", Path(__file__).resolve().parents[2])
    return Path(base) / (str(mode) + ".sim.json")


def _defaults(mode, backend):
    avis = backend == "avis"
    return {
        "SIMULATOR_HOST": "127.0.0.1",
        "SIMULATOR_PORT": 25001 if avis else 2000,
        "SIMULATOR_TIMEOUT_S": 1.0 if avis else 5.0,
        "SIMULATOR_VEHICLE_FILTER": "vehicle.*",
        "SIMULATOR_VEHICLE_BLUEPRINT": "auto",
        "SIMULATOR_MAP": "current",
        "SIMULATOR_SPAWN_POINT_INDEX": -1,
        "SIMULATOR_LIDAR_ENABLED": backend == "carla",
        "SIMULATOR_LIDAR_RANGE_M": 50.0,
        "SIMULATOR_LIDAR_CHANNELS": 32,
        "SIMULATOR_LIDAR_POINTS_PER_SECOND": 56000,
        "SIMULATOR_LIDAR_ROTATION_FREQUENCY": 10.0,
        "SIMULATOR_CAMERA_FOV": 90.0,
        "SIMULATOR_CAMERA_X": 1.45,
        "SIMULATOR_CAMERA_Y": 0.0,
        "SIMULATOR_CAMERA_Z": 1.8,
        "SIMULATOR_CAMERA_PITCH": -8.0,
        "SIMULATOR_CAMERA_YAW": 0.0,
        "SIMULATOR_CAMERA_ROLL": 0.0,
        # CARLA target speed is km/h; AVIS target speed is API percentage.
        "SIMULATOR_TARGET_SPEED": 25.0 if avis else 50.0,
        "SIMULATOR_THROTTLE_LIMIT": 0.35 if avis else 0.70,
        # Simulator City vision starts in the raw camera frame. BEV can be
        # enabled and tuned explicitly after checking the camera perspective.
        "USE_BEV": False,
        "DEBUG": False,
        "LANE_THRESHOLD": 180,
        "HOUGH_THRESHOLD": 15,
        "HOUGH_MIN_LINE_LENGTH": 5,
        "HOUGH_MAX_LINE_GAP": 20,
        "HOUGH_BLUR_KERNEL": 3,
        "HOUGH_MORPH_CLOSE": True,
        "CROSSWALK_THRESHOLD": 180,
        "CROSSWALK_VERTICAL_MIN_LINES": 6,
        "CROSSWALK_HORIZONTAL_MIN_LINES": 3,
        "LANE_ROI_MODE": "rectangle",
        "CW_TRAPEZOID_MODE": False,
        "RL_TOP_WIDTH_FACTOR": 0.85,
        "LL_TOP_WIDTH_FACTOR": 0.85,
        "CW_TOP_WIDTH_FACTOR": 0.90,
        "OLD_METHOD": False,
        "CW_OLD_METHOD": True,
        "CAMERA_PITCH_DEG": -8.0,
        "CAMERA_HEIGHT": 180.0,
        "LANE_WIDTH": 350.0,
        "BEV_SRC_TL_X": 0.35, "BEV_SRC_TL_Y": 0.60,
        "BEV_SRC_TR_X": 0.65, "BEV_SRC_TR_Y": 0.60,
        "BEV_SRC_BR_X": 1.00, "BEV_SRC_BR_Y": 1.00,
        "BEV_SRC_BL_X": 0.00, "BEV_SRC_BL_Y": 1.00,
        "SIMULATOR_STOP_ON_LOST_LANE": True,
        "SIMULATOR_STOP_ON_CROSSWALK": mode != "avis-race",
        "SIMULATOR_OBSTACLE_STOP_DISTANCE_CM": 35.0,
        "CITY_LANE_DETECTOR": "default",
        "USE_ML_LANE_DETECTOR": False,
        "ML_LANE_MODEL": "unet_depthwise_nano",
        "SIMULATOR_STEERING_INVERTED": False,
        "MIN_SERVO_ANGLE": 50.0,
        "SERVO_CENTER": 95.0,
        "MAX_SERVO_ANGLE": 130.0,
        "SERVO_DIRECTION": "ltr",
        "RL_TOP_ROI": 0.8, "RL_BOTTOM_ROI": 1.0, "RL_LEFT_ROI": 0.6, "RL_RIGHT_ROI": 0.9,
        "LL_TOP_ROI": 0.8, "LL_BOTTOM_ROI": 1.0, "LL_LEFT_ROI": 0.2, "LL_RIGHT_ROI": 0.5,
        "CW_TOP_ROI": 0.8, "CW_BOTTOM_ROI": 1.0, "CW_LEFT_ROI": 0.3, "CW_RIGHT_ROI": 0.9,
        "SIMULATOR_AVIS_SENSOR_ANGLE": 30,
        "ENCODER_PULSE_DISTANCE_CM": 0.5,
    }


def _validate_settings(data):
    if not isinstance(data, dict):
        raise ValueError("simulator settings must be a JSON object")
    clean = {}
    for key, value in data.items():
        if key not in SIMULATOR_KEYS:
            raise ValueError(f"unsupported simulator setting: {key}")
        if key in BOOL_KEYS:
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be boolean")
        elif key in STRING_KEYS:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{key} must be a non-empty string")
            if key == "SIMULATOR_VEHICLE_BLUEPRINT" and value.lower() != "auto" and not value.startswith("vehicle."):
                raise ValueError("SIMULATOR_VEHICLE_BLUEPRINT must be 'auto' or a vehicle.* blueprint id")
            if key == "CITY_LANE_DETECTOR" and value not in {"default", "blsf-beta"}:
                raise ValueError("CITY_LANE_DETECTOR must be default or blsf-beta")
            if key == "ML_LANE_MODEL" and value not in {"unet_depthwise_nano", "unet_depthwise_small"}:
                raise ValueError("ML_LANE_MODEL must be a supported Race lane model")
            if key == "LANE_ROI_MODE" and value not in {"rectangle", "trapezoid"}:
                raise ValueError("LANE_ROI_MODE must be rectangle or trapezoid")
            if key == "SERVO_DIRECTION" and value not in {"ltr", "rtl"}:
                raise ValueError("SERVO_DIRECTION must be ltr or rtl")
        elif key in INT_KEYS:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{key} must be an integer")
            if key == "SIMULATOR_PORT" and not 1 <= value <= 65535:
                raise ValueError("SIMULATOR_PORT must be between 1 and 65535")
            if key in {"SIMULATOR_LIDAR_CHANNELS", "SIMULATOR_LIDAR_POINTS_PER_SECOND"} and value <= 0:
                raise ValueError(f"{key} must be positive")
            if key == "SIMULATOR_LIDAR_CHANNELS" and value > 256:
                raise ValueError("SIMULATOR_LIDAR_CHANNELS must be at most 256")
            if key == "SIMULATOR_LIDAR_POINTS_PER_SECOND" and value > 2000000:
                raise ValueError("SIMULATOR_LIDAR_POINTS_PER_SECOND must be at most 2000000")
            if key == "SIMULATOR_AVIS_SENSOR_ANGLE" and not 0 <= value <= 90:
                raise ValueError("SIMULATOR_AVIS_SENSOR_ANGLE must be between 0 and 90")
            if key == "LANE_THRESHOLD" and not 0 <= value <= 255:
                raise ValueError("LANE_THRESHOLD must be between 0 and 255")
            if key == "HOUGH_THRESHOLD" and not 1 <= value <= 255:
                raise ValueError("HOUGH_THRESHOLD must be between 1 and 255")
            if key == "HOUGH_MIN_LINE_LENGTH" and not 1 <= value <= 500:
                raise ValueError("HOUGH_MIN_LINE_LENGTH must be between 1 and 500")
            if key == "HOUGH_MAX_LINE_GAP" and not 0 <= value <= 100:
                raise ValueError("HOUGH_MAX_LINE_GAP must be between 0 and 100")
            if key == "HOUGH_BLUR_KERNEL" and (not 1 <= value <= 15 or (value != 1 and value % 2 == 0)):
                raise ValueError("HOUGH_BLUR_KERNEL must be 1 or an odd integer from 3 to 15")
            if key == "CROSSWALK_THRESHOLD" and not 0 <= value <= 255:
                raise ValueError("CROSSWALK_THRESHOLD must be between 0 and 255")
            if key in {"CROSSWALK_VERTICAL_MIN_LINES", "CROSSWALK_HORIZONTAL_MIN_LINES"} and not 1 <= value <= 1000:
                raise ValueError(f"{key} must be between 1 and 1000")
            if key == "SIMULATOR_SPAWN_POINT_INDEX" and not -1 <= value <= 100000:
                raise ValueError("SIMULATOR_SPAWN_POINT_INDEX must be -1 (automatic) or a valid non-negative index")
        elif key in NUMERIC_KEYS:
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"{key} must be a finite number")
            if key in POSITIVE_KEYS and value <= 0:
                raise ValueError(f"{key} must be positive")
            if key in NONNEGATIVE_KEYS and value < 0:
                raise ValueError(f"{key} must be non-negative")
            if key == "SIMULATOR_TIMEOUT_S" and value > 60:
                raise ValueError("SIMULATOR_TIMEOUT_S must be at most 60 seconds")
            if key == "SIMULATOR_CAMERA_FOV" and not 10 <= value <= 150:
                raise ValueError("SIMULATOR_CAMERA_FOV must be between 10 and 150 degrees")
            if key == "SIMULATOR_LIDAR_ROTATION_FREQUENCY" and value > 50:
                raise ValueError("SIMULATOR_LIDAR_ROTATION_FREQUENCY must be at most 50 Hz")
            if key == "SIMULATOR_TARGET_SPEED" and value > 200:
                raise ValueError("SIMULATOR_TARGET_SPEED must be at most 200")
            if key == "SIMULATOR_LIDAR_RANGE_M" and value > 500:
                raise ValueError("SIMULATOR_LIDAR_RANGE_M must be at most 500 meters")
            if key == "SIMULATOR_OBSTACLE_STOP_DISTANCE_CM" and value > 500:
                raise ValueError("SIMULATOR_OBSTACLE_STOP_DISTANCE_CM must be at most 500 cm")
            if key == "SIMULATOR_THROTTLE_LIMIT" and not 0 <= value <= 1:
                raise ValueError("SIMULATOR_THROTTLE_LIMIT must be between 0 and 1")
            if key in ROI_KEYS | BEV_KEYS | ROI_FACTOR_KEYS and not 0 <= value <= 1:
                raise ValueError(f"{key} must be between 0 and 1")
            if key == "CAMERA_PITCH_DEG" and not -90 <= value <= 90:
                raise ValueError("CAMERA_PITCH_DEG must be between -90 and 90 degrees")
            if key in {"MIN_SERVO_ANGLE", "SERVO_CENTER", "MAX_SERVO_ANGLE"} and not 0 <= value <= 180:
                raise ValueError(f"{key} must be between 0 and 180 degrees")
            camera_axis = key.removeprefix("SIMULATOR_CAMERA_")
            if camera_axis in {"X", "Y"} and not -20 <= value <= 20:
                raise ValueError(f"{key} must be between -20 and 20 meters")
            if camera_axis == "Z" and not -5 <= value <= 15:
                raise ValueError("SIMULATOR_CAMERA_Z must be between -5 and 15 meters")
            if camera_axis == "PITCH" and not -90 <= value <= 90:
                raise ValueError("SIMULATOR_CAMERA_PITCH must be between -90 and 90 degrees")
            if camera_axis in {"YAW", "ROLL"} and not -180 <= value <= 180:
                raise ValueError(f"{key} must be between -180 and 180 degrees")
            if key == "ENCODER_WHEELBASE_CM" and value <= 0:
                raise ValueError("ENCODER_WHEELBASE_CM must be positive")
        clean[key] = value
    for left, right in (("RL_TOP_ROI", "RL_BOTTOM_ROI"), ("LL_TOP_ROI", "LL_BOTTOM_ROI"), ("CW_TOP_ROI", "CW_BOTTOM_ROI"),
                        ("RL_LEFT_ROI", "RL_RIGHT_ROI"), ("LL_LEFT_ROI", "LL_RIGHT_ROI"), ("CW_LEFT_ROI", "CW_RIGHT_ROI")):
        if left in clean and right in clean and clean[left] >= clean[right]:
            raise ValueError(f"{left} must be smaller than {right}")
    if all(key in clean for key in ("MIN_SERVO_ANGLE", "SERVO_CENTER", "MAX_SERVO_ANGLE")):
        if not clean["MIN_SERVO_ANGLE"] < clean["SERVO_CENTER"] < clean["MAX_SERVO_ANGLE"]:
            raise ValueError("MIN_SERVO_ANGLE must be smaller than SERVO_CENTER, which must be smaller than MAX_SERVO_ANGLE")
    return clean


def load_simulator_settings(config, mode, backend):
    """Initialize simulator defaults and overlay that mode's optional JSON file."""
    setattr(config, "SIMULATOR_BACKEND", backend)
    for key, value in _defaults(mode, backend).items():
        setattr(config, key, value)
    path = settings_path(config, mode)
    if path.is_file():
        with path.open("r", encoding="utf-8") as handle:
            values = _validate_settings(json.load(handle))
        for key, value in values.items():
            setattr(config, key, value)
    target = float(getattr(config, "SIMULATOR_TARGET_SPEED", 0))
    if backend == "avis" and target > 100:
        raise ValueError("AVIS Engine target speed must be between 0 and 100")
    if backend == "avis" and float(getattr(config, "SIMULATOR_TIMEOUT_S", 1.0)) > 1.0:
        raise ValueError("AVIS Engine request timeout must be at most 1 second")
    return path


def save_simulator_settings(config, mode, patch):
    """Atomically persist whitelisted settings in a mode-specific file."""
    path = settings_path(config, mode)
    path.parent.mkdir(parents=True, exist_ok=True)
    values = {}
    if path.is_file():
        with path.open("r", encoding="utf-8") as handle:
            values.update(_validate_settings(json.load(handle)))
    values.update(_validate_settings(patch))
    values = _validate_settings(values)
    if str(getattr(config, "SIMULATOR_BACKEND", "")) == "avis" and float(values.get("SIMULATOR_TARGET_SPEED", 0)) > 100:
        raise ValueError("AVIS Engine target speed must be between 0 and 100")
    if str(getattr(config, "SIMULATOR_BACKEND", "")) == "avis" and float(values.get("SIMULATOR_TIMEOUT_S", 1.0)) > 1.0:
        raise ValueError("AVIS Engine request timeout must be at most 1 second")
    fd, temporary = tempfile.mkstemp(prefix=".sim-settings-", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(values, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            if os.path.exists(temporary):
                os.unlink(temporary)
        except OSError:
            pass
    for key, value in values.items():
        setattr(config, key, value)
    return values
