"""Per-simulation-mode settings; never writes into city.json or race.json."""
import json
import math
import os
import tempfile
from pathlib import Path


SIMULATOR_KEYS = {
    "SIMULATOR_HOST", "SIMULATOR_PORT", "SIMULATOR_TIMEOUT_S", "SIMULATOR_TUNING_PROFILE_VERSION", "SIMULATOR_AVIS_SAFETY_PROFILE_VERSION",
    "SIMULATOR_VEHICLE_FILTER", "SIMULATOR_VEHICLE_BLUEPRINT", "SIMULATOR_MAP",
    "SIMULATOR_SPAWN_POINT_INDEX", "CITY_LANE_DETECTOR", "SIMULATOR_LIDAR_ENABLED",
    "SIMULATOR_LIDAR_RANGE_M", "SIMULATOR_LIDAR_CHANNELS",
    "SIMULATOR_LIDAR_POINTS_PER_SECOND", "SIMULATOR_LIDAR_ROTATION_FREQUENCY",
    "SIMULATOR_CAMERA_FOV", "SIMULATOR_CAMERA_X", "SIMULATOR_CAMERA_Y", "SIMULATOR_CAMERA_Z",
    "SIMULATOR_CAMERA_PITCH", "SIMULATOR_CAMERA_YAW", "SIMULATOR_CAMERA_ROLL", "SIMULATOR_TARGET_SPEED",
    "SIMULATOR_THROTTLE_LIMIT", "SIMULATOR_STEERING_LIMIT",
    "SIMULATOR_STEERING_RATE", "SIMULATOR_THROTTLE_RISE_RATE",
    "SIMULATOR_STOP_ON_LOST_LANE",
    "SIMULATOR_STOP_ON_CROSSWALK", "SIMULATOR_CROSSWALK_HARDCODE_ENABLED",
    "SIMULATOR_CROSSWALK_CONFIRM_FRAMES", "SIMULATOR_CROSSWALK_DWELL_SECONDS",
    "SIMULATOR_CROSSWALK_STEP_TIMEOUT_SECONDS", "SIMULATOR_CROSSWALK_ROUTE_CHAINS",
    "SIMULATOR_DEADLOCK_ENABLED", "SIMULATOR_DEADLOCK_CONFIRM_FRAMES",
    "SIMULATOR_DEADLOCK_STEP_TIMEOUT_SECONDS", "SIMULATOR_DEADLOCK_ROUTE_CHAINS",
    "SIMULATOR_DEADLOCK_CW_THRESHOLD", "SIMULATOR_DEADLOCK_CW_CANNY_LOW_THRESHOLD",
    "SIMULATOR_DEADLOCK_CW_CANNY_HIGH_THRESHOLD", "SIMULATOR_DEADLOCK_CW_HOUGH_THRESHOLD",
    "SIMULATOR_DEADLOCK_CW_HOUGH_MIN_LINE_LENGTH", "SIMULATOR_DEADLOCK_CW_HOUGH_MAX_LINE_GAP",
    "SIMULATOR_DEADLOCK_CW_LINE_ANGLE_TOLERANCE_DEG",
    "SIMULATOR_DEADLOCK_CW_HORIZONTAL_MIN_LINES",
    "SIMULATOR_DEADLOCK_CW_MIN_LINE_LENGTH_PX", "SIMULATOR_DEADLOCK_CW_MIN_LINE_LENGTH_RATIO",
    "SIMULATOR_OBSTACLE_STOP_DISTANCE_CM",
    "SIMULATOR_OBSTACLE_AVOIDANCE_ENABLED", "SIMULATOR_OBSTACLE_HALL_HANDOFF_ENABLED", "SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM",
    "SIMULATOR_OBSTACLE_APPROACH_SPEED_KMH", "SIMULATOR_OBSTACLE_SPEED_LIMIT_DISTANCE_CM",
    "SIMULATOR_OBSTACLE_SPEED_LIMIT_LEFT_SENSOR_ENABLED",
    "SIMULATOR_OBSTACLE_SPEED_LIMIT_FRONT_SENSOR_ENABLED",
    "SIMULATOR_OBSTACLE_SPEED_LIMIT_RIGHT_SENSOR_ENABLED",
    "SIMULATOR_OBSTACLE_SPEED_LIMIT_BRAKE_ENABLED",
    "SIMULATOR_OBSTACLE_CLEAR_DISTANCE_CM", "SIMULATOR_OBSTACLE_SIDE_CLEARANCE_CM",
    "SIMULATOR_OBSTACLE_SHIFT_SECONDS", "SIMULATOR_OBSTACLE_REJOIN_SECONDS",
    "SIMULATOR_OBSTACLE_PASS_TIMEOUT_SECONDS", "SIMULATOR_OBSTACLE_STEERING_OFFSET",
    "SIMULATOR_OBSTACLE_THROTTLE_LIMIT", "SIMULATOR_OBSTACLE_LEFT_STEERING_PERCENT",
    "SIMULATOR_OBSTACLE_RIGHT_STEERING_PERCENT", "SIMULATOR_OBSTACLE_ROI_DELAY_SECONDS",
    "SIMULATOR_OBSTACLE_LANE_HOLD_SECONDS", "SIMULATOR_OBSTACLE_ROI_SEARCH_TIMEOUT_SECONDS",
    "SIMULATOR_OBSTACLE_USE_DISTANCE_MODE", "SIMULATOR_OBSTACLE_DIRECT_STEERING_DISTANCE_CM",
    "SIMULATOR_OBSTACLE_ROI_CONFIRMATION_ENABLED", "SIMULATOR_OBSTACLE_ROI_CONFIRM_FRAMES",
    "SIMULATOR_OBSTACLE_CLEAR_CONFIRM_FRAMES",
    "SIMULATOR_AVIS_FRONT_RANGE_INVALID_GRACE_SECONDS",
    "SIMULATOR_OBSTACLE_RETURN_STEERING_GATE_ENABLED",
    "SIMULATOR_OBSTACLE_RETURN_STEERING_MAX_WAIT_SECONDS",
    "SIMULATOR_OBSTACLE_HALL_HANDOFF_ENABLED",
    "SIMULATOR_OBSTACLE_RETURN_STEERING_SAMPLE_COUNT",
    "SIMULATOR_OBSTACLE_RETURN_STEERING_MIN_PERCENT",
    "SIMULATOR_OBSTACLE_RETURN_STEERING_MAX_PERCENT",
    "ML_TOP_ROI", "ML_BOTTOM_ROI", "ML_LEFT_ROI", "ML_RIGHT_ROI",
    "MR_TOP_ROI", "MR_BOTTOM_ROI", "MR_LEFT_ROI", "MR_RIGHT_ROI",
    "ST_TOP_ROI", "ST_BOTTOM_ROI", "ST_LEFT_ROI", "ST_RIGHT_ROI",
    "SIMULATOR_STOP_LINE_ENABLED",
    "SIMULATOR_TRAFFIC_LIGHTS_ENABLED", "SIMULATOR_STOP_LINE_THRESHOLD",
    "SIMULATOR_STOP_LINE_MIN_WIDTH_RATIO", "SIMULATOR_STOP_LINE_MIN_AREA",
    "SIMULATOR_STOP_LINE_MAX_ANGLE_DEG", "SIMULATOR_STOP_LINE_CONFIRM_FRAMES",
    "SIMULATOR_STOP_LINE_DWELL_SECONDS", "SIMULATOR_SIGN_ACTIONS_ENABLED",
    "SIMULATOR_STOP_SIGN_HSV_ENABLED", "SIMULATOR_STOP_SIGN_RED_HUE_MIN",
    "SIMULATOR_STOP_SIGN_RED_HUE_MAX", "SIMULATOR_STOP_SIGN_RED_HUE_WRAP_MIN",
    "SIMULATOR_STOP_SIGN_MIN_SATURATION", "SIMULATOR_STOP_SIGN_MIN_VALUE",
    "SIMULATOR_STOP_SIGN_MIN_CONTOUR_AREA", "SIMULATOR_STOP_SIGN_MIN_AREA_RATIO",
    "SIMULATOR_STOP_SIGN_MIN_SHAPE_FILL_RATIO", "SIMULATOR_STOP_SIGN_ASPECT_TOLERANCE",
    "SIMULATOR_STOP_SIGN_MIN_VERTICES", "SIMULATOR_STOP_SIGN_MAX_VERTICES",
    "SIMULATOR_STOP_SIGN_CONFIRM_FRAMES",
    "SIMULATOR_SIGN_CONFIDENCE", "SIMULATOR_SIGN_SCAN_INTERVAL",
    "SIMULATOR_SIGN_STOP_HOLD_SECONDS", "SIMULATOR_SIGN_TURN_HOLD_SECONDS",
    "SIMULATOR_SIGN_STEERING_OFFSET", "TL_TOP_ROI", "TL_BOTTOM_ROI",
    "TL_LEFT_ROI", "TL_RIGHT_ROI", "TL_MIN_SATURATION", "TL_MIN_VALUE",
    "TL_MIN_CONTOUR_AREA", "TL_MIN_ACTIVE_BRIGHTNESS", "TL_RED_HUE_MIN",
    "TL_RED_HUE_MAX", "TL_RED_HUE_WRAP_MIN", "TL_GREEN_HUE_MIN", "TL_GREEN_HUE_MAX",
    "SIMULATOR_TL_CONFIRMATION_WINDOW", "SIMULATOR_TL_GREEN_REQUIRED",
    "SIMULATOR_STOP_LINE_TOP_ROI", "SIMULATOR_STOP_LINE_BOTTOM_ROI",
    "SIMULATOR_STOP_LINE_LEFT_ROI", "SIMULATOR_STOP_LINE_RIGHT_ROI",
    "SIMULATOR_STEERING_INVERTED", "SIMULATOR_AVIS_SENSOR_ANGLE",
    "MIN_SERVO_ANGLE", "SERVO_CENTER", "MAX_SERVO_ANGLE", "SERVO_DIRECTION",
    "ENCODER_PULSE_DISTANCE_CM", "ENCODER_WHEELBASE_CM",
    "USE_BEV", "USE_ML_LANE_DETECTOR", "ML_LANE_MODEL", "DEBUG",
    "LANE_THRESHOLD", "HOUGH_THRESHOLD", "HOUGH_MIN_LINE_LENGTH",
    "HOUGH_MAX_LINE_GAP", "HOUGH_BLUR_KERNEL", "HOUGH_MORPH_CLOSE",
    "ROI_RESIZABLE",
    "CROSSWALK_THRESHOLD", "CROSSWALK_VERTICAL_MIN_LINES",
    "CROSSWALK_HORIZONTAL_MIN_LINES", "CROSSWALK_CANNY_LOW_THRESHOLD",
    "CROSSWALK_CANNY_HIGH_THRESHOLD", "CROSSWALK_HOUGH_THRESHOLD",
    "CROSSWALK_HOUGH_MIN_LINE_LENGTH", "CROSSWALK_HOUGH_MAX_LINE_GAP",
    "CROSSWALK_LINE_ANGLE_TOLERANCE_DEG", "CROSSWALK_MIN_LINE_LENGTH_RATIO",
    "CROSSWALK_MIN_LINE_LENGTH_PX", "CROSSWALK_MIN_BOTTOM_DISTANCE_RATIO",
    "LANE_ROI_MODE", "CW_TRAPEZOID_MODE",
    "RL_TOP_WIDTH_FACTOR", "LL_TOP_WIDTH_FACTOR", "CW_TOP_WIDTH_FACTOR",
    "OLD_METHOD", "CW_OLD_METHOD", "CAMERA_PITCH_DEG", "CAMERA_HEIGHT", "LANE_WIDTH",
    "BEV_SRC_TL_X", "BEV_SRC_TL_Y", "BEV_SRC_TR_X", "BEV_SRC_TR_Y",
    "BEV_SRC_BR_X", "BEV_SRC_BR_Y", "BEV_SRC_BL_X", "BEV_SRC_BL_Y",
    "RL_TOP_ROI", "RL_BOTTOM_ROI", "RL_LEFT_ROI", "RL_RIGHT_ROI", "RL_MIRRORED",
    "LL_TOP_ROI", "LL_BOTTOM_ROI", "LL_LEFT_ROI", "LL_RIGHT_ROI", "LL_MIRRORED",
    "CW_TOP_ROI", "CW_BOTTOM_ROI", "CW_LEFT_ROI", "CW_RIGHT_ROI",
    "HALL_LINE_TRACKING_ENABLED", "HALL_LINE_TRACKING_MAX_MISSED",
    "HALL_LINE_TRACKING_REACQUIRE_FRAMES",
    "USE_PID", "AUTO_UPDATE_KP", "KP", "KI", "KD", "KT", "OUTPUT_LIMITS",
    "PID_MIN_DT", "PID_MAX_DT", "PID_DERIVATIVE_FILTER",
}
BOOL_KEYS = {
    "SIMULATOR_LIDAR_ENABLED", "SIMULATOR_STOP_ON_LOST_LANE", "RL_MIRRORED", "LL_MIRRORED",
    "SIMULATOR_STOP_ON_CROSSWALK", "SIMULATOR_CROSSWALK_HARDCODE_ENABLED",
    "SIMULATOR_DEADLOCK_ENABLED",
    "SIMULATOR_STEERING_INVERTED", "USE_BEV",
    "SIMULATOR_OBSTACLE_AVOIDANCE_ENABLED",
    "SIMULATOR_OBSTACLE_SPEED_LIMIT_LEFT_SENSOR_ENABLED",
    "SIMULATOR_OBSTACLE_SPEED_LIMIT_FRONT_SENSOR_ENABLED",
    "SIMULATOR_OBSTACLE_SPEED_LIMIT_RIGHT_SENSOR_ENABLED",
    "SIMULATOR_OBSTACLE_SPEED_LIMIT_BRAKE_ENABLED",
    "SIMULATOR_OBSTACLE_RETURN_STEERING_GATE_ENABLED",
    "SIMULATOR_OBSTACLE_USE_DISTANCE_MODE",
    "SIMULATOR_OBSTACLE_ROI_CONFIRMATION_ENABLED",
    "SIMULATOR_STOP_LINE_ENABLED",
    "SIMULATOR_TRAFFIC_LIGHTS_ENABLED", "SIMULATOR_SIGN_ACTIONS_ENABLED",
    "SIMULATOR_STOP_SIGN_HSV_ENABLED",
    "HALL_LINE_TRACKING_ENABLED", "USE_PID", "AUTO_UPDATE_KP",
    "USE_ML_LANE_DETECTOR", "DEBUG", "HOUGH_MORPH_CLOSE",
    "CW_TRAPEZOID_MODE", "OLD_METHOD", "CW_OLD_METHOD", "ROI_RESIZABLE",
}
INT_KEYS = {
    "SIMULATOR_PORT", "SIMULATOR_TUNING_PROFILE_VERSION", "SIMULATOR_AVIS_SAFETY_PROFILE_VERSION", "SIMULATOR_LIDAR_CHANNELS",
    "SIMULATOR_LIDAR_POINTS_PER_SECOND", "SIMULATOR_AVIS_SENSOR_ANGLE",
    "SIMULATOR_SPAWN_POINT_INDEX", "LANE_THRESHOLD", "HOUGH_THRESHOLD",
    "HOUGH_MIN_LINE_LENGTH", "HOUGH_MAX_LINE_GAP", "HOUGH_BLUR_KERNEL",
    "CROSSWALK_THRESHOLD", "CROSSWALK_VERTICAL_MIN_LINES",
    "CROSSWALK_HORIZONTAL_MIN_LINES", "CROSSWALK_CANNY_LOW_THRESHOLD",
    "CROSSWALK_CANNY_HIGH_THRESHOLD", "CROSSWALK_HOUGH_THRESHOLD",
    "CROSSWALK_HOUGH_MIN_LINE_LENGTH", "CROSSWALK_HOUGH_MAX_LINE_GAP",
    "CROSSWALK_LINE_ANGLE_TOLERANCE_DEG", "CROSSWALK_MIN_LINE_LENGTH_PX",
    "SIMULATOR_DEADLOCK_CW_THRESHOLD", "SIMULATOR_DEADLOCK_CW_CANNY_LOW_THRESHOLD",
    "SIMULATOR_DEADLOCK_CW_CANNY_HIGH_THRESHOLD", "SIMULATOR_DEADLOCK_CW_HOUGH_THRESHOLD",
    "SIMULATOR_DEADLOCK_CW_HOUGH_MIN_LINE_LENGTH", "SIMULATOR_DEADLOCK_CW_HOUGH_MAX_LINE_GAP",
    "SIMULATOR_DEADLOCK_CW_LINE_ANGLE_TOLERANCE_DEG",
    "SIMULATOR_DEADLOCK_CW_HORIZONTAL_MIN_LINES", "SIMULATOR_DEADLOCK_CW_MIN_LINE_LENGTH_PX",
    "HALL_LINE_TRACKING_MAX_MISSED",
    "HALL_LINE_TRACKING_REACQUIRE_FRAMES", "SIMULATOR_STOP_LINE_THRESHOLD",
    "SIMULATOR_STOP_LINE_CONFIRM_FRAMES", "SIMULATOR_CROSSWALK_CONFIRM_FRAMES",
    "SIMULATOR_SIGN_SCAN_INTERVAL", "SIMULATOR_DEADLOCK_CONFIRM_FRAMES",
    "SIMULATOR_OBSTACLE_ROI_CONFIRM_FRAMES",
    "SIMULATOR_OBSTACLE_CLEAR_CONFIRM_FRAMES",
    "SIMULATOR_OBSTACLE_RETURN_STEERING_SAMPLE_COUNT",
    "TL_MIN_SATURATION", "TL_MIN_VALUE", "TL_RED_HUE_MIN", "TL_RED_HUE_MAX",
    "TL_RED_HUE_WRAP_MIN", "TL_GREEN_HUE_MIN", "TL_GREEN_HUE_MAX",
    "SIMULATOR_TL_CONFIRMATION_WINDOW", "SIMULATOR_TL_GREEN_REQUIRED",
    "SIMULATOR_STOP_SIGN_RED_HUE_MIN", "SIMULATOR_STOP_SIGN_RED_HUE_MAX",
    "SIMULATOR_STOP_SIGN_RED_HUE_WRAP_MIN", "SIMULATOR_STOP_SIGN_MIN_SATURATION",
    "SIMULATOR_STOP_SIGN_MIN_VALUE", "SIMULATOR_STOP_SIGN_MIN_VERTICES",
    "SIMULATOR_STOP_SIGN_MAX_VERTICES", "SIMULATOR_STOP_SIGN_CONFIRM_FRAMES",
}
STRING_KEYS = {
    "SIMULATOR_HOST", "SIMULATOR_VEHICLE_FILTER", "SIMULATOR_VEHICLE_BLUEPRINT",
    "SIMULATOR_MAP", "CITY_LANE_DETECTOR", "ML_LANE_MODEL", "LANE_ROI_MODE", "SERVO_DIRECTION",
    "SIMULATOR_CROSSWALK_ROUTE_CHAINS", "SIMULATOR_DEADLOCK_ROUTE_CHAINS",
}
POSITIVE_KEYS = {
    "SIMULATOR_TIMEOUT_S", "SIMULATOR_LIDAR_RANGE_M",
    "SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM", "SIMULATOR_OBSTACLE_CLEAR_DISTANCE_CM",
    "SIMULATOR_OBSTACLE_APPROACH_SPEED_KMH", "SIMULATOR_OBSTACLE_SPEED_LIMIT_DISTANCE_CM",
    "SIMULATOR_OBSTACLE_RETURN_STEERING_MAX_WAIT_SECONDS",
    "SIMULATOR_OBSTACLE_DIRECT_STEERING_DISTANCE_CM",
    "SIMULATOR_OBSTACLE_SIDE_CLEARANCE_CM", "SIMULATOR_STOP_LINE_MIN_AREA",
    "SIMULATOR_STOP_LINE_DWELL_SECONDS", "SIMULATOR_CROSSWALK_DWELL_SECONDS",
    "SIMULATOR_CROSSWALK_STEP_TIMEOUT_SECONDS", "SIMULATOR_DEADLOCK_STEP_TIMEOUT_SECONDS",
    "SIMULATOR_STOP_SIGN_MIN_CONTOUR_AREA",
    "TL_MIN_CONTOUR_AREA",
    "SIMULATOR_LIDAR_ROTATION_FREQUENCY", "SIMULATOR_CAMERA_FOV",
    "SIMULATOR_STEERING_RATE", "SIMULATOR_THROTTLE_RISE_RATE",
    "ENCODER_PULSE_DISTANCE_CM", "CAMERA_HEIGHT", "LANE_WIDTH",
    "PID_MIN_DT", "PID_MAX_DT",
}
NONNEGATIVE_KEYS = {"SIMULATOR_TARGET_SPEED", "SIMULATOR_OBSTACLE_STOP_DISTANCE_CM", "SIMULATOR_AVIS_FRONT_RANGE_INVALID_GRACE_SECONDS", "KT"}
ROI_KEYS = {"RL_TOP_ROI", "RL_BOTTOM_ROI", "RL_LEFT_ROI", "RL_RIGHT_ROI",
            "LL_TOP_ROI", "LL_BOTTOM_ROI", "LL_LEFT_ROI", "LL_RIGHT_ROI",
            "CW_TOP_ROI", "CW_BOTTOM_ROI", "CW_LEFT_ROI", "CW_RIGHT_ROI",
            "TL_TOP_ROI", "TL_BOTTOM_ROI", "TL_LEFT_ROI", "TL_RIGHT_ROI",
            "SIMULATOR_STOP_LINE_TOP_ROI", "SIMULATOR_STOP_LINE_BOTTOM_ROI",
            "SIMULATOR_STOP_LINE_LEFT_ROI", "SIMULATOR_STOP_LINE_RIGHT_ROI",
            "ST_TOP_ROI", "ST_BOTTOM_ROI", "ST_LEFT_ROI", "ST_RIGHT_ROI",
            "ML_TOP_ROI", "ML_BOTTOM_ROI", "ML_LEFT_ROI", "ML_RIGHT_ROI",
            "MR_TOP_ROI", "MR_BOTTOM_ROI", "MR_LEFT_ROI", "MR_RIGHT_ROI"}
BEV_KEYS = {
    "BEV_SRC_TL_X", "BEV_SRC_TL_Y", "BEV_SRC_TR_X", "BEV_SRC_TR_Y",
    "BEV_SRC_BR_X", "BEV_SRC_BR_Y", "BEV_SRC_BL_X", "BEV_SRC_BL_Y",
}
ROI_FACTOR_KEYS = {"RL_TOP_WIDTH_FACTOR", "LL_TOP_WIDTH_FACTOR", "CW_TOP_WIDTH_FACTOR",
                   "SIMULATOR_STOP_LINE_MIN_WIDTH_RATIO",
                   "SIMULATOR_STOP_SIGN_MIN_AREA_RATIO",
                   "SIMULATOR_STOP_SIGN_MIN_SHAPE_FILL_RATIO",
                   "SIMULATOR_STOP_SIGN_ASPECT_TOLERANCE"}
NUMERIC_KEYS = POSITIVE_KEYS | NONNEGATIVE_KEYS | ROI_KEYS | BEV_KEYS | ROI_FACTOR_KEYS | {
    "SIMULATOR_THROTTLE_LIMIT", "SIMULATOR_STEERING_LIMIT",
    "SIMULATOR_OBSTACLE_SHIFT_SECONDS", "SIMULATOR_OBSTACLE_REJOIN_SECONDS",
    "SIMULATOR_OBSTACLE_PASS_TIMEOUT_SECONDS", "SIMULATOR_OBSTACLE_STEERING_OFFSET",
    "SIMULATOR_OBSTACLE_THROTTLE_LIMIT", "SIMULATOR_OBSTACLE_LEFT_STEERING_PERCENT",
    "SIMULATOR_OBSTACLE_RIGHT_STEERING_PERCENT", "SIMULATOR_OBSTACLE_ROI_DELAY_SECONDS",
    "SIMULATOR_OBSTACLE_RETURN_STEERING_MIN_PERCENT",
    "SIMULATOR_OBSTACLE_RETURN_STEERING_MAX_PERCENT",
    "SIMULATOR_OBSTACLE_LANE_HOLD_SECONDS", "SIMULATOR_OBSTACLE_ROI_SEARCH_TIMEOUT_SECONDS",
    "SIMULATOR_STOP_LINE_MAX_ANGLE_DEG",
    "TL_MIN_ACTIVE_BRIGHTNESS", "SIMULATOR_SIGN_CONFIDENCE",
    "SIMULATOR_SIGN_STOP_HOLD_SECONDS", "SIMULATOR_SIGN_TURN_HOLD_SECONDS",
    "SIMULATOR_SIGN_STEERING_OFFSET",
    "KP", "KI", "KD", "PID_DERIVATIVE_FILTER",
    "ENCODER_WHEELBASE_CM", "SIMULATOR_CAMERA_X",
    "MIN_SERVO_ANGLE", "SERVO_CENTER", "MAX_SERVO_ANGLE",
    "SIMULATOR_CAMERA_Y", "SIMULATOR_CAMERA_Z", "SIMULATOR_CAMERA_PITCH",
    "SIMULATOR_CAMERA_YAW", "SIMULATOR_CAMERA_ROLL", "CAMERA_PITCH_DEG",
    "CROSSWALK_MIN_LINE_LENGTH_RATIO", "CROSSWALK_MIN_BOTTOM_DISTANCE_RATIO",
    "SIMULATOR_DEADLOCK_CW_MIN_LINE_LENGTH_RATIO",
}


def settings_path(config, mode):
    base = getattr(config, "BASE_DIR", Path(__file__).resolve().parents[2])
    return Path(base) / (str(mode) + ".sim.json")


def _defaults(mode, backend):
    avis = backend == "avis"
    return {
        "SIMULATOR_HOST": "127.0.0.1",
        "SIMULATOR_TUNING_PROFILE_VERSION": 2,
        "SIMULATOR_AVIS_SAFETY_PROFILE_VERSION": 3 if avis else 0,
        "SIMULATOR_PORT": 25001 if avis else 2000,
        # Legacy AVIS camera responses need a realistic TCP read window.
        "SIMULATOR_TIMEOUT_S": 5.0,
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
        # CARLA starts at walking speed; AVIS target remains an API percentage.
        "SIMULATOR_TARGET_SPEED": 25.0 if avis else 5.0,
        "SIMULATOR_THROTTLE_LIMIT": 0.35 if avis else 0.12,
        "SIMULATOR_STEERING_LIMIT": 1.0 if avis else 0.28,
        "SIMULATOR_STEERING_RATE": 2.0 if avis else 0.80,
        "SIMULATOR_THROTTLE_RISE_RATE": 1.0 if avis else 0.12,
        # Simulator City vision starts in the raw camera frame. BEV can be
        # enabled and tuned explicitly after checking the camera perspective.
        "USE_BEV": False,
        "HALL_LINE_TRACKING_ENABLED": False,
        "HALL_LINE_TRACKING_MAX_MISSED": 4,
        "HALL_LINE_TRACKING_REACQUIRE_FRAMES": 2,
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
        "CROSSWALK_CANNY_LOW_THRESHOLD": 100,
        "CROSSWALK_CANNY_HIGH_THRESHOLD": 150,
        "CROSSWALK_HOUGH_THRESHOLD": 20,
        "CROSSWALK_HOUGH_MIN_LINE_LENGTH": 5,
        "CROSSWALK_HOUGH_MAX_LINE_GAP": 5,
        "CROSSWALK_LINE_ANGLE_TOLERANCE_DEG": 30,
        "CROSSWALK_MIN_LINE_LENGTH_RATIO": 0.10,
        "CROSSWALK_MIN_LINE_LENGTH_PX": 10,
        "CROSSWALK_MIN_BOTTOM_DISTANCE_RATIO": 0.70,
        "LANE_ROI_MODE": "rectangle",
        "CW_TRAPEZOID_MODE": False,
        "ROI_RESIZABLE": False,
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
        "SIMULATOR_STOP_ON_CROSSWALK": mode != "avis-race" and backend != "avis",
        "SIMULATOR_CROSSWALK_HARDCODE_ENABLED": avis and mode == "avis",
        "SIMULATOR_CROSSWALK_CONFIRM_FRAMES": 3,
        "SIMULATOR_CROSSWALK_DWELL_SECONDS": 3.0,
        "SIMULATOR_CROSSWALK_STEP_TIMEOUT_SECONDS": 15.0,
        "SIMULATOR_CROSSWALK_ROUTE_CHAINS": '{"left":[],"straight":[],"right":[]}',
        "SIMULATOR_DEADLOCK_ENABLED": False,
        "SIMULATOR_DEADLOCK_CONFIRM_FRAMES": 4,
        "SIMULATOR_DEADLOCK_STEP_TIMEOUT_SECONDS": 15.0,
        "SIMULATOR_DEADLOCK_ROUTE_CHAINS": '{"left":[],"right":[]}',
        # Dedicated, deliberately more permissive CW-line detector for deadlock.
        # These settings never affect the normal City crosswalk braking detector.
        "SIMULATOR_DEADLOCK_CW_THRESHOLD": 120,
        "SIMULATOR_DEADLOCK_CW_CANNY_LOW_THRESHOLD": 30,
        "SIMULATOR_DEADLOCK_CW_CANNY_HIGH_THRESHOLD": 80,
        "SIMULATOR_DEADLOCK_CW_HOUGH_THRESHOLD": 4,
        "SIMULATOR_DEADLOCK_CW_HOUGH_MIN_LINE_LENGTH": 2,
        "SIMULATOR_DEADLOCK_CW_HOUGH_MAX_LINE_GAP": 30,
        "SIMULATOR_DEADLOCK_CW_LINE_ANGLE_TOLERANCE_DEG": 44,
        "SIMULATOR_DEADLOCK_CW_HORIZONTAL_MIN_LINES": 1,
        "SIMULATOR_DEADLOCK_CW_MIN_LINE_LENGTH_PX": 2,
        "SIMULATOR_DEADLOCK_CW_MIN_LINE_LENGTH_RATIO": 0.005,
        "SIMULATOR_OBSTACLE_STOP_DISTANCE_CM": 60.0 if avis else 35.0,
        # AVIS enables range-based bypass by default; an independent fail-safe
        # forward guard brakes whenever its front reading is missing or unsafe.
        "SIMULATOR_OBSTACLE_AVOIDANCE_ENABLED": avis,
        "SIMULATOR_OBSTACLE_HALL_HANDOFF_ENABLED": False,
        "SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM": 120.0 if avis else 100.0,
        "SIMULATOR_OBSTACLE_APPROACH_SPEED_KMH": 10.0,
        "SIMULATOR_OBSTACLE_SPEED_LIMIT_DISTANCE_CM": 1500.0,
        "SIMULATOR_OBSTACLE_SPEED_LIMIT_LEFT_SENSOR_ENABLED": False,
        "SIMULATOR_OBSTACLE_SPEED_LIMIT_FRONT_SENSOR_ENABLED": True,
        "SIMULATOR_OBSTACLE_SPEED_LIMIT_RIGHT_SENSOR_ENABLED": False,
        "SIMULATOR_OBSTACLE_SPEED_LIMIT_BRAKE_ENABLED": False,
        "SIMULATOR_OBSTACLE_CLEAR_DISTANCE_CM": 150.0 if avis else 125.0,
        "SIMULATOR_OBSTACLE_SIDE_CLEARANCE_CM": 75.0,
        "SIMULATOR_OBSTACLE_SHIFT_SECONDS": 0.35,
        "SIMULATOR_OBSTACLE_REJOIN_SECONDS": 0.35,
        "SIMULATOR_OBSTACLE_PASS_TIMEOUT_SECONDS": 4.0,
        "SIMULATOR_OBSTACLE_STEERING_OFFSET": 0.28,
        "SIMULATOR_OBSTACLE_THROTTLE_LIMIT": 0.12,
        "SIMULATOR_OBSTACLE_LEFT_STEERING_PERCENT": 80.0,
        "SIMULATOR_OBSTACLE_RIGHT_STEERING_PERCENT": 80.0,
        "SIMULATOR_OBSTACLE_ROI_DELAY_SECONDS": 1.0,
        "SIMULATOR_OBSTACLE_USE_DISTANCE_MODE": False,
        "SIMULATOR_OBSTACLE_ROI_CONFIRMATION_ENABLED": True,
        "SIMULATOR_OBSTACLE_DIRECT_STEERING_DISTANCE_CM": 100.0,
        "SIMULATOR_OBSTACLE_LANE_HOLD_SECONDS": 3.0,
        "SIMULATOR_OBSTACLE_ROI_SEARCH_TIMEOUT_SECONDS": 4.0,
        "SIMULATOR_OBSTACLE_ROI_CONFIRM_FRAMES": 2,
        "SIMULATOR_OBSTACLE_CLEAR_CONFIRM_FRAMES": 3,
        "SIMULATOR_AVIS_FRONT_RANGE_INVALID_GRACE_SECONDS": 1.5,
        "SIMULATOR_OBSTACLE_RETURN_STEERING_GATE_ENABLED": True,
        "SIMULATOR_OBSTACLE_RETURN_STEERING_MAX_WAIT_SECONDS": 4.0,
        "SIMULATOR_OBSTACLE_RETURN_STEERING_SAMPLE_COUNT": 10,
        "SIMULATOR_OBSTACLE_RETURN_STEERING_MIN_PERCENT": -10.0,
        "SIMULATOR_OBSTACLE_RETURN_STEERING_MAX_PERCENT": 10.0,
        "ML_TOP_ROI": 0.62, "ML_BOTTOM_ROI": 0.98,
        "ML_LEFT_ROI": 0.02, "ML_RIGHT_ROI": 0.42,
        "MR_TOP_ROI": 0.62, "MR_BOTTOM_ROI": 0.98,
        "MR_LEFT_ROI": 0.58, "MR_RIGHT_ROI": 0.98,
        # AVIS City uses a solid stop line, not the physical crosswalk pipeline.
        "SIMULATOR_STOP_LINE_ENABLED": avis and mode == "avis",
        "SIMULATOR_TRAFFIC_LIGHTS_ENABLED": avis and mode == "avis",
        "SIMULATOR_STOP_LINE_THRESHOLD": 190,
        "SIMULATOR_STOP_LINE_MIN_WIDTH_RATIO": 0.55,
        "SIMULATOR_STOP_LINE_MIN_AREA": 120.0,
        "SIMULATOR_STOP_LINE_MAX_ANGLE_DEG": 12.0,
        "SIMULATOR_STOP_LINE_CONFIRM_FRAMES": 3,
        "SIMULATOR_STOP_LINE_DWELL_SECONDS": 1.0,
        "SIMULATOR_STOP_LINE_TOP_ROI": 0.72,
        "SIMULATOR_STOP_LINE_BOTTOM_ROI": 0.98,
        "SIMULATOR_STOP_LINE_LEFT_ROI": 0.10,
        "SIMULATOR_STOP_LINE_RIGHT_ROI": 0.90,
        "TL_TOP_ROI": 0.03, "TL_BOTTOM_ROI": 0.55,
        "TL_LEFT_ROI": 0.15, "TL_RIGHT_ROI": 0.85,
        "TL_MIN_SATURATION": 50, "TL_MIN_VALUE": 50,
        "TL_MIN_CONTOUR_AREA": 5.0, "TL_MIN_ACTIVE_BRIGHTNESS": 180.0,
        "TL_RED_HUE_MIN": 0, "TL_RED_HUE_MAX": 10, "TL_RED_HUE_WRAP_MIN": 170,
        "TL_GREEN_HUE_MIN": 40, "TL_GREEN_HUE_MAX": 90,
        "SIMULATOR_TL_CONFIRMATION_WINDOW": 10,
        "SIMULATOR_TL_GREEN_REQUIRED": 8,
        "SIMULATOR_SIGN_ACTIONS_ENABLED": False,
        # Red HSV + convex polygon detector runs independently of optional YOLO.
        "SIMULATOR_STOP_SIGN_HSV_ENABLED": avis and mode == "avis",
        "SIMULATOR_STOP_SIGN_RED_HUE_MIN": 0,
        "SIMULATOR_STOP_SIGN_RED_HUE_MAX": 12,
        "SIMULATOR_STOP_SIGN_RED_HUE_WRAP_MIN": 168,
        "SIMULATOR_STOP_SIGN_MIN_SATURATION": 80,
        "SIMULATOR_STOP_SIGN_MIN_VALUE": 60,
        "SIMULATOR_STOP_SIGN_MIN_CONTOUR_AREA": 120.0,
        "SIMULATOR_STOP_SIGN_MIN_AREA_RATIO": 0.012,
        "SIMULATOR_STOP_SIGN_MIN_SHAPE_FILL_RATIO": 0.45,
        "SIMULATOR_STOP_SIGN_ASPECT_TOLERANCE": 0.40,
        "SIMULATOR_STOP_SIGN_MIN_VERTICES": 6,
        "SIMULATOR_STOP_SIGN_MAX_VERTICES": 10,
        "SIMULATOR_STOP_SIGN_CONFIRM_FRAMES": 2,
        "SIMULATOR_SIGN_CONFIDENCE": 0.45,
        "SIMULATOR_SIGN_SCAN_INTERVAL": 6,
        "SIMULATOR_SIGN_STOP_HOLD_SECONDS": 2.0,
        "SIMULATOR_SIGN_TURN_HOLD_SECONDS": 0.6,
        "SIMULATOR_SIGN_STEERING_OFFSET": 0.18,
        # Full-frame defaults preserve the current AVIS sign-detector behavior.
        "ST_TOP_ROI": 0.0,
        "ST_BOTTOM_ROI": 1.0,
        "ST_LEFT_ROI": 0.0,
        "ST_RIGHT_ROI": 1.0,
        "CITY_LANE_DETECTOR": "default",
        "USE_ML_LANE_DETECTOR": False,
        "ML_LANE_MODEL": "unet_depthwise_nano",
        "SIMULATOR_STEERING_INVERTED": False,
        "MIN_SERVO_ANGLE": 55.0,
        "SERVO_CENTER": 95.0,
        "MAX_SERVO_ANGLE": 125.0,
        "SERVO_DIRECTION": "ltr",
        # Match the City/Race Stream PID defaults. The simulator applies this
        # controller to lane-centering error before virtual steering output.
        "USE_PID": True, "AUTO_UPDATE_KP": False,
        "KP": 0.35, "KI": 0.0, "KD": 0.01, "KT": 0.01,
        "OUTPUT_LIMITS": [-80.0, 80.0],
        "PID_MIN_DT": 0.001, "PID_MAX_DT": 0.2,
        "PID_DERIVATIVE_FILTER": 0.25,
        "RL_MIRRORED": False, "LL_MIRRORED": False,
        "RL_TOP_ROI": 0.8, "RL_BOTTOM_ROI": 1.0, "RL_LEFT_ROI": 0.6, "RL_RIGHT_ROI": 0.9,
        "LL_TOP_ROI": 0.8, "LL_BOTTOM_ROI": 1.0, "LL_LEFT_ROI": 0.2, "LL_RIGHT_ROI": 0.5,
        "CW_TOP_ROI": 0.8, "CW_BOTTOM_ROI": 1.0, "CW_LEFT_ROI": 0.3, "CW_RIGHT_ROI": 0.9,
        "SIMULATOR_AVIS_SENSOR_ANGLE": 30,
        "ENCODER_PULSE_DISTANCE_CM": 0.5,
    }


def _validate_settings(data, backend=None, mode=None):
    if not isinstance(data, dict):
        raise ValueError("simulator settings must be a JSON object")
    avis_backend = str(backend or "").strip().lower() == "avis"
    avis_city_mode = avis_backend and str(mode or "").strip().lower() == "avis"
    clean = {}
    for key, value in data.items():
        if key not in SIMULATOR_KEYS:
            raise ValueError(f"unsupported simulator setting: {key}")
        if key == "OUTPUT_LIMITS":
            if not isinstance(value, (list, tuple)) or len(value) != 2:
                raise ValueError("OUTPUT_LIMITS must contain two numeric values")
            if any(
                isinstance(item, bool)
                or not isinstance(item, (int, float))
                or not math.isfinite(float(item))
                for item in value
            ):
                raise ValueError("OUTPUT_LIMITS must contain two finite numbers")
            low, high = float(value[0]), float(value[1])
            if not -255.0 <= low < high <= 255.0:
                raise ValueError("OUTPUT_LIMITS must be ordered and within -255..255")
            clean[key] = [low, high]
            continue
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
            if key == "SIMULATOR_CROSSWALK_ROUTE_CHAINS":
                try:
                    routes = json.loads(value)
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ValueError("SIMULATOR_CROSSWALK_ROUTE_CHAINS must be valid JSON") from exc
                if not isinstance(routes, dict):
                    raise ValueError("crosswalk route chains must be a JSON object")
                normalized_routes = {}
                for route_name in ("left", "straight", "right"):
                    route_steps = routes.get(route_name, [])
                    if not isinstance(route_steps, list) or len(route_steps) > 16:
                        raise ValueError(route_name + " crosswalk route must contain 0 to 16 steps")
                    normalized_steps = []
                    for index, step in enumerate(route_steps):
                        if not isinstance(step, dict):
                            raise ValueError(route_name + " step " + str(index + 1) + " must be an object")
                        direction = str(step.get("direction", "")).lower()
                        distance, speed, steering = step.get("distance_m"), step.get("speed_percent"), step.get("steering_percent")
                        if direction not in {"forward", "reverse"}:
                            raise ValueError(route_name + " step " + str(index + 1) + " direction must be forward or reverse")
                        if any(isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)) for item in (distance, speed, steering)):
                            raise ValueError(route_name + " step " + str(index + 1) + " values must be finite numbers")
                        if not float(speed).is_integer() or not float(steering).is_integer():
                            raise ValueError(route_name + " step " + str(index + 1) + " speed and steering must be integers")
                        distance, speed, steering = float(distance), int(speed), int(steering)
                        if not 0.05 <= distance <= 40:
                            raise ValueError(route_name + " step " + str(index + 1) + " distance must be 0.05 to 40 metres")
                        if not 1 <= speed <= 100:
                            raise ValueError(route_name + " step " + str(index + 1) + " speed must be 1 to 100 percent")
                        if not -100 <= steering <= 100:
                            raise ValueError(route_name + " step " + str(index + 1) + " steering must be -100 to 100 percent")
                        normalized_steps.append({"direction": direction, "distance_m": distance, "speed_percent": speed, "steering_percent": steering})
                    normalized_routes[route_name] = normalized_steps
                value = json.dumps(normalized_routes, separators=(",", ":"))
            if key == "SIMULATOR_DEADLOCK_ROUTE_CHAINS":
                try:
                    routes = json.loads(value)
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ValueError("SIMULATOR_DEADLOCK_ROUTE_CHAINS must be valid JSON") from exc
                if not isinstance(routes, dict):
                    raise ValueError("deadlock route chains must be a JSON object")
                normalized_routes = {}
                for route_name in ("left", "right"):
                    route_steps = routes.get(route_name, [])
                    if not isinstance(route_steps, list) or len(route_steps) > 16:
                        raise ValueError(route_name + " deadlock route must contain 0 to 16 steps")
                    normalized_steps = []
                    for index, step in enumerate(route_steps):
                        if not isinstance(step, dict):
                            raise ValueError(route_name + " deadlock step " + str(index + 1) + " must be an object")
                        direction = str(step.get("direction", "")).lower()
                        distance = step.get("distance_m")
                        speed = step.get("speed_percent")
                        steering = step.get("steering_percent")
                        if direction not in {"forward", "reverse"}:
                            raise ValueError(route_name + " deadlock step " + str(index + 1) + " direction must be forward or reverse")
                        if any(
                            isinstance(item, bool) or not isinstance(item, (int, float))
                            or not math.isfinite(float(item))
                            for item in (distance, speed, steering)
                        ):
                            raise ValueError(route_name + " deadlock step " + str(index + 1) + " values must be finite numbers")
                        if not float(speed).is_integer() or not float(steering).is_integer():
                            raise ValueError(route_name + " deadlock step " + str(index + 1) + " speed and steering must be integers")
                        distance, speed, steering = float(distance), int(speed), int(steering)
                        if not 0.05 <= distance <= 40:
                            raise ValueError(route_name + " deadlock step " + str(index + 1) + " distance must be 0.05 to 40 metres")
                        if not 1 <= speed <= 100:
                            raise ValueError(route_name + " deadlock step " + str(index + 1) + " speed must be 1 to 100 percent")
                        if not -100 <= steering <= 100:
                            raise ValueError(route_name + " deadlock step " + str(index + 1) + " steering must be -100 to 100 percent")
                        normalized_steps.append({
                            "direction": direction, "distance_m": distance,
                            "speed_percent": speed, "steering_percent": steering,
                        })
                    normalized_routes[route_name] = normalized_steps
                value = json.dumps(normalized_routes, separators=(",", ":"))
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
            if key == "SIMULATOR_DEADLOCK_CW_THRESHOLD" and not 0 <= value <= 255:
                raise ValueError("SIMULATOR_DEADLOCK_CW_THRESHOLD must be between 0 and 255")
            if key == "SIMULATOR_DEADLOCK_CW_CANNY_LOW_THRESHOLD" and not 0 <= value <= 254:
                raise ValueError("SIMULATOR_DEADLOCK_CW_CANNY_LOW_THRESHOLD must be between 0 and 254")
            if key == "SIMULATOR_DEADLOCK_CW_CANNY_HIGH_THRESHOLD" and not 1 <= value <= 255:
                raise ValueError("SIMULATOR_DEADLOCK_CW_CANNY_HIGH_THRESHOLD must be between 1 and 255")
            if key == "SIMULATOR_DEADLOCK_CW_HOUGH_THRESHOLD" and not 1 <= value <= 255:
                raise ValueError("SIMULATOR_DEADLOCK_CW_HOUGH_THRESHOLD must be between 1 and 255")
            if key == "SIMULATOR_DEADLOCK_CW_HOUGH_MIN_LINE_LENGTH" and not 1 <= value <= 500:
                raise ValueError("SIMULATOR_DEADLOCK_CW_HOUGH_MIN_LINE_LENGTH must be between 1 and 500")
            if key == "SIMULATOR_DEADLOCK_CW_HOUGH_MAX_LINE_GAP" and not 0 <= value <= 100:
                raise ValueError("SIMULATOR_DEADLOCK_CW_HOUGH_MAX_LINE_GAP must be between 0 and 100")
            if key == "SIMULATOR_DEADLOCK_CW_LINE_ANGLE_TOLERANCE_DEG" and not 1 <= value <= 44:
                raise ValueError("SIMULATOR_DEADLOCK_CW_LINE_ANGLE_TOLERANCE_DEG must be between 1 and 44 degrees")
            if key == "SIMULATOR_DEADLOCK_CW_HORIZONTAL_MIN_LINES" and not 1 <= value <= 1000:
                raise ValueError("SIMULATOR_DEADLOCK_CW_HORIZONTAL_MIN_LINES must be between 1 and 1000")
            if key == "SIMULATOR_DEADLOCK_CW_MIN_LINE_LENGTH_PX" and not 1 <= value <= 500:
                raise ValueError("SIMULATOR_DEADLOCK_CW_MIN_LINE_LENGTH_PX must be between 1 and 500")
            if key in {"CROSSWALK_CANNY_LOW_THRESHOLD", "CROSSWALK_CANNY_HIGH_THRESHOLD"} and not 0 <= value <= 255:
                raise ValueError(f"{key} must be between 0 and 255")
            if key == "CROSSWALK_HOUGH_THRESHOLD" and not 1 <= value <= 255:
                raise ValueError("CROSSWALK_HOUGH_THRESHOLD must be between 1 and 255")
            if key == "CROSSWALK_HOUGH_MIN_LINE_LENGTH" and not 1 <= value <= 500:
                raise ValueError("CROSSWALK_HOUGH_MIN_LINE_LENGTH must be between 1 and 500")
            if key == "CROSSWALK_HOUGH_MAX_LINE_GAP" and not 0 <= value <= 100:
                raise ValueError("CROSSWALK_HOUGH_MAX_LINE_GAP must be between 0 and 100")
            if key == "CROSSWALK_LINE_ANGLE_TOLERANCE_DEG" and not 1 <= value <= 44:
                raise ValueError("CROSSWALK_LINE_ANGLE_TOLERANCE_DEG must be between 1 and 44 degrees")
            if key == "CROSSWALK_MIN_LINE_LENGTH_PX" and not 1 <= value <= 500:
                raise ValueError("CROSSWALK_MIN_LINE_LENGTH_PX must be between 1 and 500")
            if key in {"CROSSWALK_VERTICAL_MIN_LINES", "CROSSWALK_HORIZONTAL_MIN_LINES"} and not 0 <= value <= 1000:
                raise ValueError(f"{key} must be between 0 and 1000")
            if key == "SIMULATOR_STOP_LINE_THRESHOLD" and not 0 <= value <= 255:
                raise ValueError("SIMULATOR_STOP_LINE_THRESHOLD must be between 0 and 255")
            if key == "SIMULATOR_STOP_LINE_CONFIRM_FRAMES" and not 1 <= value <= 20:
                raise ValueError("SIMULATOR_STOP_LINE_CONFIRM_FRAMES must be between 1 and 20")
            if key == "SIMULATOR_SIGN_SCAN_INTERVAL" and not 1 <= value <= 120:
                raise ValueError("SIMULATOR_SIGN_SCAN_INTERVAL must be between 1 and 120")
            if key == "SIMULATOR_CROSSWALK_CONFIRM_FRAMES" and not 1 <= value <= 20:
                raise ValueError("SIMULATOR_CROSSWALK_CONFIRM_FRAMES must be between 1 and 20")
            if key == "SIMULATOR_DEADLOCK_CONFIRM_FRAMES" and not 1 <= value <= 20:
                raise ValueError("SIMULATOR_DEADLOCK_CONFIRM_FRAMES must be between 1 and 20")
            if key == "SIMULATOR_OBSTACLE_ROI_CONFIRM_FRAMES" and not 1 <= value <= 10:
                raise ValueError("SIMULATOR_OBSTACLE_ROI_CONFIRM_FRAMES must be between 1 and 10")
            if key == "SIMULATOR_OBSTACLE_CLEAR_CONFIRM_FRAMES" and not 1 <= value <= 20:
                raise ValueError("SIMULATOR_OBSTACLE_CLEAR_CONFIRM_FRAMES must be between 1 and 20")
            if key == "SIMULATOR_OBSTACLE_RETURN_STEERING_SAMPLE_COUNT" and not 1 <= value <= 100:
                raise ValueError("SIMULATOR_OBSTACLE_RETURN_STEERING_SAMPLE_COUNT must be between 1 and 100")
            if key in {"TL_MIN_SATURATION", "TL_MIN_VALUE"} and not 0 <= value <= 255:
                raise ValueError(f"{key} must be between 0 and 255")
            if key in {"TL_RED_HUE_MIN", "TL_RED_HUE_MAX", "TL_RED_HUE_WRAP_MIN",
                       "TL_GREEN_HUE_MIN", "TL_GREEN_HUE_MAX"} and not 0 <= value <= 180:
                raise ValueError(f"{key} must be between 0 and 180")
            if key == "SIMULATOR_TL_CONFIRMATION_WINDOW" and not 1 <= value <= 60:
                raise ValueError("SIMULATOR_TL_CONFIRMATION_WINDOW must be between 1 and 60")
            if key == "SIMULATOR_TL_GREEN_REQUIRED" and not 1 <= value <= 60:
                raise ValueError("SIMULATOR_TL_GREEN_REQUIRED must be between 1 and 60")
            if key in {
                "SIMULATOR_STOP_SIGN_RED_HUE_MIN",
                "SIMULATOR_STOP_SIGN_RED_HUE_MAX",
                "SIMULATOR_STOP_SIGN_RED_HUE_WRAP_MIN",
            } and not 0 <= value <= 179:
                raise ValueError(f"{key} must be between 0 and 179 (OpenCV HSV hue)")
            if key in {"SIMULATOR_STOP_SIGN_MIN_SATURATION", "SIMULATOR_STOP_SIGN_MIN_VALUE"} and not 0 <= value <= 255:
                raise ValueError(f"{key} must be between 0 and 255")
            if key == "SIMULATOR_STOP_SIGN_MIN_VERTICES" and not 4 <= value <= 10:
                raise ValueError("SIMULATOR_STOP_SIGN_MIN_VERTICES must be between 4 and 10")
            if key == "SIMULATOR_STOP_SIGN_MAX_VERTICES" and not 5 <= value <= 12:
                raise ValueError("SIMULATOR_STOP_SIGN_MAX_VERTICES must be between 5 and 12")
            if key == "SIMULATOR_STOP_SIGN_CONFIRM_FRAMES" and not 1 <= value <= 10:
                raise ValueError("SIMULATOR_STOP_SIGN_CONFIRM_FRAMES must be between 1 and 10")
            if key == "SIMULATOR_SPAWN_POINT_INDEX" and not -1 <= value <= 100000:
                raise ValueError("SIMULATOR_SPAWN_POINT_INDEX must be -1 (automatic) or a valid non-negative index")
            if key == "HALL_LINE_TRACKING_MAX_MISSED" and not 1 <= value <= 12:
                raise ValueError("HALL_LINE_TRACKING_MAX_MISSED must be between 1 and 12")
            if key == "HALL_LINE_TRACKING_REACQUIRE_FRAMES" and not 1 <= value <= 10:
                raise ValueError("HALL_LINE_TRACKING_REACQUIRE_FRAMES must be between 1 and 10")
            if key == "SIMULATOR_TUNING_PROFILE_VERSION" and value not in {1, 2}:
                raise ValueError("SIMULATOR_TUNING_PROFILE_VERSION must be 1 or 2")
            if key == "SIMULATOR_AVIS_SAFETY_PROFILE_VERSION" and value not in {0, 1, 2, 3}:
                raise ValueError("SIMULATOR_AVIS_SAFETY_PROFILE_VERSION must be 0, 1, 2, or 3")
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
            if key == "SIMULATOR_TARGET_SPEED":
                maximum = 100 if str(backend or "").lower() == "avis" else 200
                if value > maximum:
                    label = "AVIS percentage" if maximum == 100 else "200 km/h"
                    raise ValueError(
                        f"SIMULATOR_TARGET_SPEED must be between 0 and {maximum} ({label})"
                    )
            if key == "SIMULATOR_LIDAR_RANGE_M" and value > 500:
                raise ValueError("SIMULATOR_LIDAR_RANGE_M must be at most 500 meters")
            if key == "SIMULATOR_OBSTACLE_APPROACH_SPEED_KMH" and value > 100:
                raise ValueError("SIMULATOR_OBSTACLE_APPROACH_SPEED_KMH must be between 1 and 100 km/h")
            if key == "SIMULATOR_OBSTACLE_SPEED_LIMIT_DISTANCE_CM" and value > 10000:
                raise ValueError("SIMULATOR_OBSTACLE_SPEED_LIMIT_DISTANCE_CM must be at most 10000 cm")
            if key == "SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM":
                # The AVIS range-sensor bypass is shared by City and Race profiles.
                maximum = 1500 if avis_backend else 500
                if value > maximum:
                    raise ValueError(f"{key} must be at most {maximum} cm")
            if key in {"SIMULATOR_OBSTACLE_STOP_DISTANCE_CM",
                       "SIMULATOR_OBSTACLE_CLEAR_DISTANCE_CM",
                       "SIMULATOR_OBSTACLE_SIDE_CLEARANCE_CM"}:
                maximum = 500
                if avis_city_mode:
                    maximum = {
                        "SIMULATOR_OBSTACLE_STOP_DISTANCE_CM": 1000,
                        "SIMULATOR_OBSTACLE_CLEAR_DISTANCE_CM": 2000,
                        "SIMULATOR_OBSTACLE_SIDE_CLEARANCE_CM": 500,
                    }[key]
                if value > maximum:
                    raise ValueError(f"{key} must be at most {maximum} cm")
            if key in {"SIMULATOR_OBSTACLE_SHIFT_SECONDS", "SIMULATOR_OBSTACLE_REJOIN_SECONDS"} and not 0.05 <= value <= 2.0:
                raise ValueError(f"{key} must be between 0.05 and 2 seconds")
            if key == "SIMULATOR_OBSTACLE_PASS_TIMEOUT_SECONDS" and not 0.2 <= value <= 10.0:
                raise ValueError("SIMULATOR_OBSTACLE_PASS_TIMEOUT_SECONDS must be between 0.2 and 10 seconds")
            if key == "SIMULATOR_OBSTACLE_STEERING_OFFSET" and not 0.05 <= value <= 1.0:
                raise ValueError("SIMULATOR_OBSTACLE_STEERING_OFFSET must be between 0.05 and 1")
            if key in {"SIMULATOR_OBSTACLE_LEFT_STEERING_PERCENT", "SIMULATOR_OBSTACLE_RIGHT_STEERING_PERCENT"} and not 0 <= value <= 100:
                raise ValueError(f"{key} must be between 0 and 100 percent")
            if key in {"SIMULATOR_OBSTACLE_RETURN_STEERING_MIN_PERCENT", "SIMULATOR_OBSTACLE_RETURN_STEERING_MAX_PERCENT"} and not -100 <= value <= 100:
                raise ValueError(f"{key} must be between -100 and 100 AVIS percent")
            if key == "SIMULATOR_OBSTACLE_ROI_DELAY_SECONDS" and not 0 <= value <= 5:
                raise ValueError("SIMULATOR_OBSTACLE_ROI_DELAY_SECONDS must be between 0 and 5 seconds")
            if key == "SIMULATOR_OBSTACLE_DIRECT_STEERING_DISTANCE_CM" and value > 2000:
                raise ValueError("SIMULATOR_OBSTACLE_DIRECT_STEERING_DISTANCE_CM must be at most 2000 cm")
            if key == "SIMULATOR_OBSTACLE_LANE_HOLD_SECONDS" and not 0.2 <= value <= 10:
                raise ValueError("SIMULATOR_OBSTACLE_LANE_HOLD_SECONDS must be between 0.2 and 10 seconds")
            if key == "SIMULATOR_OBSTACLE_ROI_SEARCH_TIMEOUT_SECONDS" and not 0.5 <= value <= 15:
                raise ValueError("SIMULATOR_OBSTACLE_ROI_SEARCH_TIMEOUT_SECONDS must be between 0.5 and 15 seconds")
            if key == "SIMULATOR_AVIS_FRONT_RANGE_INVALID_GRACE_SECONDS" and not 0 <= value <= 10:
                raise ValueError("SIMULATOR_AVIS_FRONT_RANGE_INVALID_GRACE_SECONDS must be between 0 and 10 seconds")
            if key == "SIMULATOR_SIGN_STEERING_OFFSET" and not 0.05 <= value <= 0.35:
                raise ValueError("SIMULATOR_SIGN_STEERING_OFFSET must be between 0.05 and 0.35")
            if key == "SIMULATOR_OBSTACLE_THROTTLE_LIMIT":
                maximum = 1.0 if avis_city_mode else 0.25
                if not 0 <= value <= maximum:
                    raise ValueError(
                        f"SIMULATOR_OBSTACLE_THROTTLE_LIMIT must be between 0 and {maximum}"
                    )
            if key == "SIMULATOR_STOP_LINE_MAX_ANGLE_DEG" and not 1 <= value <= 45:
                raise ValueError("SIMULATOR_STOP_LINE_MAX_ANGLE_DEG must be between 1 and 45 degrees")
            if key == "SIMULATOR_CROSSWALK_DWELL_SECONDS" and not 0.1 <= value <= 30:
                raise ValueError("SIMULATOR_CROSSWALK_DWELL_SECONDS must be between 0.1 and 30 seconds")
            if key == "SIMULATOR_CROSSWALK_STEP_TIMEOUT_SECONDS" and not 1 <= value <= 120:
                raise ValueError("SIMULATOR_CROSSWALK_STEP_TIMEOUT_SECONDS must be between 1 and 120 seconds")
            if key == "SIMULATOR_DEADLOCK_STEP_TIMEOUT_SECONDS" and not 1 <= value <= 120:
                raise ValueError("SIMULATOR_DEADLOCK_STEP_TIMEOUT_SECONDS must be between 1 and 120 seconds")
            if key == "CROSSWALK_MIN_LINE_LENGTH_RATIO" and not 0.01 <= value <= 1:
                raise ValueError("CROSSWALK_MIN_LINE_LENGTH_RATIO must be between 0.01 and 1")
            if key == "SIMULATOR_DEADLOCK_CW_MIN_LINE_LENGTH_RATIO" and not 0.005 <= value <= 1:
                raise ValueError("SIMULATOR_DEADLOCK_CW_MIN_LINE_LENGTH_RATIO must be between 0.005 and 1")
            if key == "CROSSWALK_MIN_BOTTOM_DISTANCE_RATIO" and not 0 <= value <= 1:
                raise ValueError("CROSSWALK_MIN_BOTTOM_DISTANCE_RATIO must be between 0 and 1")
            if key == "TL_MIN_ACTIVE_BRIGHTNESS" and not 0 <= value <= 255:
                raise ValueError("TL_MIN_ACTIVE_BRIGHTNESS must be between 0 and 255")
            if key == "SIMULATOR_SIGN_CONFIDENCE" and not 0.05 <= value <= 1:
                raise ValueError("SIMULATOR_SIGN_CONFIDENCE must be between 0.05 and 1")
            if key == "SIMULATOR_STOP_SIGN_MIN_CONTOUR_AREA" and value > 1000000:
                raise ValueError("SIMULATOR_STOP_SIGN_MIN_CONTOUR_AREA must be at most 1000000 px²")
            if key == "SIMULATOR_STOP_SIGN_MIN_AREA_RATIO" and not 0.0001 <= value <= 0.5:
                raise ValueError("SIMULATOR_STOP_SIGN_MIN_AREA_RATIO must be between 0.0001 and 0.5")
            if key == "SIMULATOR_STOP_SIGN_MIN_SHAPE_FILL_RATIO" and not 0.1 <= value <= 1:
                raise ValueError("SIMULATOR_STOP_SIGN_MIN_SHAPE_FILL_RATIO must be between 0.1 and 1")
            if key == "SIMULATOR_STOP_SIGN_ASPECT_TOLERANCE" and not 0.05 <= value <= 0.75:
                raise ValueError("SIMULATOR_STOP_SIGN_ASPECT_TOLERANCE must be between 0.05 and 0.75")
            if key in {"SIMULATOR_SIGN_STOP_HOLD_SECONDS", "SIMULATOR_SIGN_TURN_HOLD_SECONDS"} and not 0.1 <= value <= 10:
                raise ValueError(f"{key} must be between 0.1 and 10 seconds")
            if key == "SIMULATOR_THROTTLE_LIMIT" and not 0 <= value <= 1:
                raise ValueError("SIMULATOR_THROTTLE_LIMIT must be between 0 and 1")
            if key == "SIMULATOR_STEERING_LIMIT" and not 0.05 <= value <= 1:
                raise ValueError("SIMULATOR_STEERING_LIMIT must be between 0.05 and 1")
            if key == "SIMULATOR_STEERING_RATE" and value > 10:
                raise ValueError("SIMULATOR_STEERING_RATE must be at most 10 normalized units per second")
            if key == "SIMULATOR_THROTTLE_RISE_RATE" and value > 1:
                raise ValueError("SIMULATOR_THROTTLE_RISE_RATE must be at most 1 throttle unit per second")
            if key in {"KP", "KI", "KD"} and not -100 <= value <= 100:
                raise ValueError(f"{key} must be between -100 and 100")
            if key == "KT" and value > 10:
                raise ValueError("KT must be at most 10 seconds")
            if key == "PID_DERIVATIVE_FILTER" and not 0 <= value <= 1:
                raise ValueError("PID_DERIVATIVE_FILTER must be between 0 and 1")
            if key == "PID_MIN_DT" and value > 1:
                raise ValueError("PID_MIN_DT must be at most 1 second")
            if key == "PID_MAX_DT" and value > 5:
                raise ValueError("PID_MAX_DT must be at most 5 seconds")
            if key in ROI_KEYS | ROI_FACTOR_KEYS and not 0 <= value <= 1:
                raise ValueError(f"{key} must be between 0 and 1")
            if key in BEV_KEYS and not -0.15 <= value <= 1.15:
                raise ValueError(f"{key} must be between -0.15 and 1.15 (BEV source may extend outside the frame)")
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
                        ("RL_LEFT_ROI", "RL_RIGHT_ROI"), ("LL_LEFT_ROI", "LL_RIGHT_ROI"), ("CW_LEFT_ROI", "CW_RIGHT_ROI"),
                        ("TL_TOP_ROI", "TL_BOTTOM_ROI"), ("TL_LEFT_ROI", "TL_RIGHT_ROI"),
                        ("SIMULATOR_STOP_LINE_TOP_ROI", "SIMULATOR_STOP_LINE_BOTTOM_ROI"),
                        ("SIMULATOR_STOP_LINE_LEFT_ROI", "SIMULATOR_STOP_LINE_RIGHT_ROI"),
                        ("ST_TOP_ROI", "ST_BOTTOM_ROI"),
                        ("ST_LEFT_ROI", "ST_RIGHT_ROI")):
        if left in clean and right in clean and clean[left] >= clean[right]:
            raise ValueError(f"{left} must be smaller than {right}")
    if all(key in clean for key in ("MIN_SERVO_ANGLE", "SERVO_CENTER", "MAX_SERVO_ANGLE")):
        if not clean["MIN_SERVO_ANGLE"] < clean["SERVO_CENTER"] < clean["MAX_SERVO_ANGLE"]:
            raise ValueError("MIN_SERVO_ANGLE must be smaller than SERVO_CENTER, which must be smaller than MAX_SERVO_ANGLE")
    if "CROSSWALK_CANNY_LOW_THRESHOLD" in clean and "CROSSWALK_CANNY_HIGH_THRESHOLD" in clean:
        if clean["CROSSWALK_CANNY_LOW_THRESHOLD"] >= clean["CROSSWALK_CANNY_HIGH_THRESHOLD"]:
            raise ValueError("CROSSWALK_CANNY_LOW_THRESHOLD must be smaller than CROSSWALK_CANNY_HIGH_THRESHOLD")
    if (
        "SIMULATOR_DEADLOCK_CW_CANNY_LOW_THRESHOLD" in clean
        and "SIMULATOR_DEADLOCK_CW_CANNY_HIGH_THRESHOLD" in clean
        and clean["SIMULATOR_DEADLOCK_CW_CANNY_LOW_THRESHOLD"]
        >= clean["SIMULATOR_DEADLOCK_CW_CANNY_HIGH_THRESHOLD"]
    ):
        raise ValueError(
            "SIMULATOR_DEADLOCK_CW_CANNY_LOW_THRESHOLD must be smaller than "
            "SIMULATOR_DEADLOCK_CW_CANNY_HIGH_THRESHOLD"
        )
    for low, high in (("TL_RED_HUE_MIN", "TL_RED_HUE_MAX"), ("TL_GREEN_HUE_MIN", "TL_GREEN_HUE_MAX")):
        if low in clean and high in clean and clean[low] >= clean[high]:
            raise ValueError(f"{low} must be smaller than {high}")
    if "TL_RED_HUE_WRAP_MIN" in clean and "TL_RED_HUE_MAX" in clean:
        if clean["TL_RED_HUE_WRAP_MIN"] <= clean["TL_RED_HUE_MAX"]:
            raise ValueError("TL_RED_HUE_WRAP_MIN must exceed TL_RED_HUE_MAX")
    if (
        "SIMULATOR_STOP_SIGN_RED_HUE_MIN" in clean
        and "SIMULATOR_STOP_SIGN_RED_HUE_MAX" in clean
        and clean["SIMULATOR_STOP_SIGN_RED_HUE_MIN"]
        >= clean["SIMULATOR_STOP_SIGN_RED_HUE_MAX"]
    ):
        raise ValueError("SIMULATOR_STOP_SIGN_RED_HUE_MIN must be smaller than RED_HUE_MAX")
    if (
        "SIMULATOR_STOP_SIGN_RED_HUE_WRAP_MIN" in clean
        and "SIMULATOR_STOP_SIGN_RED_HUE_MAX" in clean
        and clean["SIMULATOR_STOP_SIGN_RED_HUE_WRAP_MIN"]
        <= clean["SIMULATOR_STOP_SIGN_RED_HUE_MAX"]
    ):
        raise ValueError("SIMULATOR_STOP_SIGN_RED_HUE_WRAP_MIN must exceed RED_HUE_MAX")
    if (
        "SIMULATOR_STOP_SIGN_MIN_VERTICES" in clean
        and "SIMULATOR_STOP_SIGN_MAX_VERTICES" in clean
        and clean["SIMULATOR_STOP_SIGN_MIN_VERTICES"]
        >= clean["SIMULATOR_STOP_SIGN_MAX_VERTICES"]
    ):
        raise ValueError("SIMULATOR_STOP_SIGN_MIN_VERTICES must be smaller than MAX_VERTICES")
    if "SIMULATOR_STOP_LINE_MIN_WIDTH_RATIO" in clean and not 0 < clean["SIMULATOR_STOP_LINE_MIN_WIDTH_RATIO"] <= 1:
        raise ValueError("SIMULATOR_STOP_LINE_MIN_WIDTH_RATIO must be greater than 0 and at most 1")
    stop_sign_hsv_keys = {
        "SIMULATOR_STOP_SIGN_HSV_ENABLED",
        "SIMULATOR_STOP_SIGN_RED_HUE_MIN", "SIMULATOR_STOP_SIGN_RED_HUE_MAX",
        "SIMULATOR_STOP_SIGN_RED_HUE_WRAP_MIN", "SIMULATOR_STOP_SIGN_MIN_SATURATION",
        "SIMULATOR_STOP_SIGN_MIN_VALUE", "SIMULATOR_STOP_SIGN_MIN_CONTOUR_AREA",
        "SIMULATOR_STOP_SIGN_MIN_AREA_RATIO", "SIMULATOR_STOP_SIGN_MIN_SHAPE_FILL_RATIO",
        "SIMULATOR_STOP_SIGN_ASPECT_TOLERANCE", "SIMULATOR_STOP_SIGN_MIN_VERTICES",
        "SIMULATOR_STOP_SIGN_MAX_VERTICES", "SIMULATOR_STOP_SIGN_CONFIRM_FRAMES",
    }
    if stop_sign_hsv_keys.intersection(clean) and not avis_city_mode:
        raise ValueError("HSV STOP-sign detection settings are available only for AVIS City")
    deadlock_keys = {
        "SIMULATOR_DEADLOCK_ENABLED", "SIMULATOR_DEADLOCK_CONFIRM_FRAMES",
        "SIMULATOR_DEADLOCK_STEP_TIMEOUT_SECONDS", "SIMULATOR_DEADLOCK_ROUTE_CHAINS",
        "SIMULATOR_DEADLOCK_CW_THRESHOLD", "SIMULATOR_DEADLOCK_CW_CANNY_LOW_THRESHOLD",
        "SIMULATOR_DEADLOCK_CW_CANNY_HIGH_THRESHOLD", "SIMULATOR_DEADLOCK_CW_HOUGH_THRESHOLD",
        "SIMULATOR_DEADLOCK_CW_HOUGH_MIN_LINE_LENGTH", "SIMULATOR_DEADLOCK_CW_HOUGH_MAX_LINE_GAP",
        "SIMULATOR_DEADLOCK_CW_LINE_ANGLE_TOLERANCE_DEG",
        "SIMULATOR_DEADLOCK_CW_HORIZONTAL_MIN_LINES",
        "SIMULATOR_DEADLOCK_CW_MIN_LINE_LENGTH_PX", "SIMULATOR_DEADLOCK_CW_MIN_LINE_LENGTH_RATIO",
    }
    if deadlock_keys.intersection(clean) and not avis_city_mode:
        raise ValueError("deadlock detection and hardcode routes are available only for AVIS City")
    if "SIMULATOR_CROSSWALK_HARDCODE_ENABLED" in clean and clean["SIMULATOR_CROSSWALK_HARDCODE_ENABLED"] and not avis_city_mode:
        raise ValueError("crosswalk hardcode routes are available only for AVIS City")
    if "SIMULATOR_CROSSWALK_ROUTE_CHAINS" in clean and not avis_city_mode:
        route_data = json.loads(clean["SIMULATOR_CROSSWALK_ROUTE_CHAINS"])
        if any(route_data.get(name) for name in ("left", "straight", "right")):
            raise ValueError("crosswalk hardcode routes are available only for AVIS City")
    if "SIMULATOR_TL_CONFIRMATION_WINDOW" in clean and "SIMULATOR_TL_GREEN_REQUIRED" in clean:
        if clean["SIMULATOR_TL_GREEN_REQUIRED"] > clean["SIMULATOR_TL_CONFIRMATION_WINDOW"]:
            raise ValueError("SIMULATOR_TL_GREEN_REQUIRED cannot exceed SIMULATOR_TL_CONFIRMATION_WINDOW")
    if "SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM" in clean and "SIMULATOR_OBSTACLE_STOP_DISTANCE_CM" in clean:
        if clean["SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM"] <= clean["SIMULATOR_OBSTACLE_STOP_DISTANCE_CM"]:
            raise ValueError("SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM must exceed the emergency stop distance")
    steering_band = (
        "SIMULATOR_OBSTACLE_RETURN_STEERING_MIN_PERCENT",
        "SIMULATOR_OBSTACLE_RETURN_STEERING_MAX_PERCENT",
    )
    if all(key in clean for key in steering_band):
        if clean[steering_band[0]] >= clean[steering_band[1]]:
            raise ValueError("return steering minimum must be smaller than its maximum")
    # Clear-distance hysteresis is clamped at runtime to at least
    # trigger_distance + 1 cm. Do not reject a high trigger setting merely
    # because the editable clear-distance field has a 500 cm upper bound.
    pid_min_dt = clean.get("PID_MIN_DT")
    pid_max_dt = clean.get("PID_MAX_DT")
    if pid_min_dt is not None and pid_max_dt is not None and pid_max_dt < pid_min_dt:
        raise ValueError("PID_MAX_DT must be greater than or equal to PID_MIN_DT")
    return clean


def load_simulator_settings(config, mode, backend):
    """Initialize simulator defaults and overlay that mode's optional JSON file."""
    setattr(config, "SIMULATOR_BACKEND", backend)
    for key, value in _defaults(mode, backend).items():
        setattr(config, key, value)
    path = settings_path(config, mode)
    saved_values = {}
    if path.is_file():
        with path.open("r", encoding="utf-8") as handle:
            saved_values = _validate_settings(json.load(handle), backend=backend, mode=mode)
        for key, value in saved_values.items():
            setattr(config, key, value)
    if backend == "carla" and path.is_file() and int(saved_values.get("SIMULATOR_TUNING_PROFILE_VERSION", 0)) < 2:
        # One-time migration: clamp only profiles written before the safety
        # envelope became editable. Persist the migration so users can raise
        # values later without having them silently clamped on every restart.
        migration = {"SIMULATOR_TUNING_PROFILE_VERSION": 2}
        legacy_limits = {
            "SIMULATOR_TARGET_SPEED": (8.0, 5.0),
            "SIMULATOR_THROTTLE_LIMIT": (0.18, 0.12),
            "SIMULATOR_STEERING_LIMIT": (0.50, 0.28),
            "SIMULATOR_STEERING_RATE": (1.50, 0.80),
            "SIMULATOR_THROTTLE_RISE_RATE": (0.50, 0.12),
        }
        for key, (old_limit, safe_default) in legacy_limits.items():
            if float(getattr(config, key, safe_default)) > old_limit:
                migration[key] = safe_default
        save_simulator_settings(config, mode, migration)

    if backend == "avis" and path.is_file() and int(
        saved_values.get("SIMULATOR_AVIS_SAFETY_PROFILE_VERSION", 0)
    ) < 1:
        # Previous AVIS profiles inherited a disabled bypass and a 35/100/125 cm
        # stop/trigger/clear profile. Upgrade that legacy default once; preserve
        # custom distances unless they conflict with the new safety envelope.
        migration = {
            "SIMULATOR_AVIS_SAFETY_PROFILE_VERSION": 1,
            "SIMULATOR_OBSTACLE_AVOIDANCE_ENABLED": True,
        }
        old_stop = float(saved_values.get("SIMULATOR_OBSTACLE_STOP_DISTANCE_CM", 35.0))
        new_stop = old_stop
        if math.isclose(old_stop, 35.0) or old_stop < 20.0:
            new_stop = 60.0 if math.isclose(old_stop, 35.0) else 20.0
            migration["SIMULATOR_OBSTACLE_STOP_DISTANCE_CM"] = new_stop

        old_trigger = float(saved_values.get("SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM", 100.0))
        new_trigger = old_trigger
        if math.isclose(old_trigger, 100.0) or old_trigger <= new_stop:
            new_trigger = max(120.0, new_stop + 20.0)
            migration["SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM"] = new_trigger

        old_clear = float(saved_values.get("SIMULATOR_OBSTACLE_CLEAR_DISTANCE_CM", 125.0))
        if math.isclose(old_clear, 125.0) or old_clear <= new_trigger:
            migration["SIMULATOR_OBSTACLE_CLEAR_DISTANCE_CM"] = max(150.0, new_trigger + 30.0)
        save_simulator_settings(config, mode, migration)

    if backend == "avis" and path.is_file() and int(
        saved_values.get("SIMULATOR_AVIS_SAFETY_PROFILE_VERSION", 0)
    ) < 2:
        # Enable the near-straight return gate once for existing AVIS profiles.
        # Preserve custom sample windows and steering bands when present.
        migration = {
            "SIMULATOR_AVIS_SAFETY_PROFILE_VERSION": 2,
            "SIMULATOR_OBSTACLE_RETURN_STEERING_GATE_ENABLED": True,
        }
        if "SIMULATOR_OBSTACLE_RETURN_STEERING_MAX_WAIT_SECONDS" not in saved_values:
            migration["SIMULATOR_OBSTACLE_RETURN_STEERING_MAX_WAIT_SECONDS"] = 4.0
        if "SIMULATOR_OBSTACLE_RETURN_STEERING_SAMPLE_COUNT" not in saved_values:
            migration["SIMULATOR_OBSTACLE_RETURN_STEERING_SAMPLE_COUNT"] = 10
        if "SIMULATOR_OBSTACLE_RETURN_STEERING_MIN_PERCENT" not in saved_values:
            migration["SIMULATOR_OBSTACLE_RETURN_STEERING_MIN_PERCENT"] = -10.0
        if "SIMULATOR_OBSTACLE_RETURN_STEERING_MAX_PERCENT" not in saved_values:
            migration["SIMULATOR_OBSTACLE_RETURN_STEERING_MAX_PERCENT"] = 10.0
        save_simulator_settings(config, mode, migration)

    if backend == "avis" and path.is_file() and int(
        saved_values.get("SIMULATOR_AVIS_SAFETY_PROFILE_VERSION", 0)
    ) < 3:
        # Keep approach-speed limiting focused on the forward path by default.
        # Side rays can legitimately see nearby lane boundaries or scenery.
        # This one-time migration also resets the all-enabled defaults introduced
        # by the previous profile version; users can re-enable either side ray.
        migration = {
            "SIMULATOR_AVIS_SAFETY_PROFILE_VERSION": 3,
            "SIMULATOR_OBSTACLE_SPEED_LIMIT_LEFT_SENSOR_ENABLED": False,
            "SIMULATOR_OBSTACLE_SPEED_LIMIT_FRONT_SENSOR_ENABLED": True,
            "SIMULATOR_OBSTACLE_SPEED_LIMIT_RIGHT_SENSOR_ENABLED": False,
        }
        save_simulator_settings(config, mode, migration)
    return path


def save_simulator_settings(config, mode, patch):
    """Atomically persist whitelisted settings in a mode-specific file."""
    backend = str(getattr(config, "SIMULATOR_BACKEND", "")).lower()
    path = settings_path(config, mode)
    path.parent.mkdir(parents=True, exist_ok=True)
    values = {}
    if path.is_file():
        with path.open("r", encoding="utf-8") as handle:
            values.update(_validate_settings(json.load(handle), backend=backend, mode=mode))
    values.update(_validate_settings(patch, backend=backend, mode=mode))
    if backend == "carla":
        # Mark all newly written CARLA profiles as migrated. This prevents a
        # future restart from applying the one-time legacy safety clamp again.
        values["SIMULATOR_TUNING_PROFILE_VERSION"] = 2
    elif backend == "avis":
        # Persist the current AVIS profile schema marker so a freshly created
        # profile does not re-run one-time migrations and override user choices.
        values.setdefault("SIMULATOR_AVIS_SAFETY_PROFILE_VERSION", 3)
    values = _validate_settings(values, backend=backend, mode=mode)
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
