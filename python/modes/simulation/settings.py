"""Per-simulation-mode settings; never writes into city.json or race.json."""
import json
import math
import os
import tempfile
from pathlib import Path


SIMULATOR_KEYS = {
    "SIMULATOR_HOST", "SIMULATOR_PORT", "SIMULATOR_TIMEOUT_S",
    "SIMULATOR_VEHICLE_FILTER", "CITY_LANE_DETECTOR", "SIMULATOR_LIDAR_ENABLED",
    "SIMULATOR_LIDAR_RANGE_M", "SIMULATOR_LIDAR_CHANNELS",
    "SIMULATOR_LIDAR_POINTS_PER_SECOND", "SIMULATOR_LIDAR_ROTATION_FREQUENCY",
    "SIMULATOR_CAMERA_FOV", "SIMULATOR_TARGET_SPEED",
    "SIMULATOR_THROTTLE_LIMIT", "SIMULATOR_STOP_ON_LOST_LANE",
    "SIMULATOR_STOP_ON_CROSSWALK", "SIMULATOR_OBSTACLE_STOP_DISTANCE_CM",
    "SIMULATOR_STEERING_INVERTED", "SIMULATOR_AVIS_SENSOR_ANGLE",
    "ENCODER_PULSE_DISTANCE_CM", "ENCODER_WHEELBASE_CM",
    "USE_BEV", "USE_ML_LANE_DETECTOR", "ML_LANE_MODEL", "DEBUG",
    "RL_TOP_ROI", "RL_BOTTOM_ROI", "RL_LEFT_ROI", "RL_RIGHT_ROI",
    "LL_TOP_ROI", "LL_BOTTOM_ROI", "LL_LEFT_ROI", "LL_RIGHT_ROI",
    "CW_TOP_ROI", "CW_BOTTOM_ROI", "CW_LEFT_ROI", "CW_RIGHT_ROI",
}
BOOL_KEYS = {
    "SIMULATOR_LIDAR_ENABLED", "SIMULATOR_STOP_ON_LOST_LANE",
    "SIMULATOR_STOP_ON_CROSSWALK", "SIMULATOR_STEERING_INVERTED", "USE_BEV",
    "USE_ML_LANE_DETECTOR", "DEBUG",
}
INT_KEYS = {"SIMULATOR_PORT", "SIMULATOR_LIDAR_CHANNELS",
            "SIMULATOR_LIDAR_POINTS_PER_SECOND", "SIMULATOR_AVIS_SENSOR_ANGLE"}
STRING_KEYS = {"SIMULATOR_HOST", "SIMULATOR_VEHICLE_FILTER", "CITY_LANE_DETECTOR", "ML_LANE_MODEL"}
POSITIVE_KEYS = {"SIMULATOR_TIMEOUT_S", "SIMULATOR_LIDAR_RANGE_M",
                 "SIMULATOR_LIDAR_ROTATION_FREQUENCY", "SIMULATOR_CAMERA_FOV",
                 "ENCODER_PULSE_DISTANCE_CM"}
NONNEGATIVE_KEYS = {"SIMULATOR_TARGET_SPEED", "SIMULATOR_OBSTACLE_STOP_DISTANCE_CM"}
ROI_KEYS = {"RL_TOP_ROI", "RL_BOTTOM_ROI", "RL_LEFT_ROI", "RL_RIGHT_ROI",
            "LL_TOP_ROI", "LL_BOTTOM_ROI", "LL_LEFT_ROI", "LL_RIGHT_ROI",
            "CW_TOP_ROI", "CW_BOTTOM_ROI", "CW_LEFT_ROI", "CW_RIGHT_ROI"}
NUMERIC_KEYS = POSITIVE_KEYS | NONNEGATIVE_KEYS | ROI_KEYS | {"SIMULATOR_THROTTLE_LIMIT", "ENCODER_WHEELBASE_CM"}


def settings_path(config, mode):
    base = getattr(config, "BASE_DIR", Path(__file__).resolve().parents[2])
    return Path(base) / (str(mode) + ".sim.json")


def _defaults(mode, backend):
    avis = backend == "avis"
    return {
        "SIMULATOR_HOST": "127.0.0.1",
        "SIMULATOR_PORT": 25001 if avis else 2000,
        "SIMULATOR_TIMEOUT_S": 5.0,
        "SIMULATOR_VEHICLE_FILTER": "vehicle.*",
        "SIMULATOR_LIDAR_ENABLED": backend == "carla",
        "SIMULATOR_LIDAR_RANGE_M": 50.0,
        "SIMULATOR_LIDAR_CHANNELS": 32,
        "SIMULATOR_LIDAR_POINTS_PER_SECOND": 56000,
        "SIMULATOR_LIDAR_ROTATION_FREQUENCY": 10.0,
        "SIMULATOR_CAMERA_FOV": 90.0,
        # CARLA target speed is km/h; AVIS target speed is API percentage.
        "SIMULATOR_TARGET_SPEED": 25.0 if avis else 20.0,
        "SIMULATOR_THROTTLE_LIMIT": 0.35,
        "SIMULATOR_STOP_ON_LOST_LANE": True,
        "SIMULATOR_STOP_ON_CROSSWALK": mode != "avis-race",
        "SIMULATOR_OBSTACLE_STOP_DISTANCE_CM": 35.0,
        "CITY_LANE_DETECTOR": "default",
        "USE_ML_LANE_DETECTOR": False,
        "ML_LANE_MODEL": "unet_depthwise_nano",
        "SIMULATOR_STEERING_INVERTED": False,
        "SIMULATOR_AVIS_SENSOR_ANGLE": 0,
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
            if key == "CITY_LANE_DETECTOR" and value not in {"default", "blsf-beta"}:
                raise ValueError("CITY_LANE_DETECTOR must be default or blsf-beta")
            if key == "ML_LANE_MODEL" and value not in {"unet_depthwise_nano", "unet_depthwise_small"}:
                raise ValueError("ML_LANE_MODEL must be a supported Race lane model")
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
            if key == "SIMULATOR_AVIS_SENSOR_ANGLE" and not -90 <= value <= 90:
                raise ValueError("SIMULATOR_AVIS_SENSOR_ANGLE must be between -90 and 90")
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
            if key == "SIMULATOR_TARGET_SPEED" and value > 100:
                raise ValueError("SIMULATOR_TARGET_SPEED must be at most 100")
            if key == "SIMULATOR_LIDAR_RANGE_M" and value > 500:
                raise ValueError("SIMULATOR_LIDAR_RANGE_M must be at most 500 meters")
            if key == "SIMULATOR_OBSTACLE_STOP_DISTANCE_CM" and value > 500:
                raise ValueError("SIMULATOR_OBSTACLE_STOP_DISTANCE_CM must be at most 500 cm")
            if key == "SIMULATOR_THROTTLE_LIMIT" and not 0 <= value <= 1:
                raise ValueError("SIMULATOR_THROTTLE_LIMIT must be between 0 and 1")
            if key in ROI_KEYS and not 0 <= value <= 1:
                raise ValueError(f"{key} must be between 0 and 1")
            if key == "ENCODER_WHEELBASE_CM" and value <= 0:
                raise ValueError("ENCODER_WHEELBASE_CM must be positive")
        clean[key] = value
    for left, right in (("RL_TOP_ROI", "RL_BOTTOM_ROI"), ("LL_TOP_ROI", "LL_BOTTOM_ROI"), ("CW_TOP_ROI", "CW_BOTTOM_ROI"),
                        ("RL_LEFT_ROI", "RL_RIGHT_ROI"), ("LL_LEFT_ROI", "LL_RIGHT_ROI"), ("CW_LEFT_ROI", "CW_RIGHT_ROI")):
        if left in clean and right in clean and clean[left] >= clean[right]:
            raise ValueError(f"{left} must be smaller than {right}")
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
