"""APIs for the simulator-specific editor and virtual sensor console."""
import math
from flask import jsonify, request

from modes.simulation.settings import SIMULATOR_KEYS, save_simulator_settings
from stream.capabilities import mode_capabilities


RESTART_KEYS = {
    "SIMULATOR_HOST", "SIMULATOR_PORT", "SIMULATOR_TIMEOUT_S",
    "SIMULATOR_VEHICLE_FILTER", "SIMULATOR_LIDAR_ENABLED",
    "SIMULATOR_LIDAR_RANGE_M", "SIMULATOR_LIDAR_CHANNELS",
    "SIMULATOR_LIDAR_POINTS_PER_SECOND", "SIMULATOR_LIDAR_ROTATION_FREQUENCY",
    "SIMULATOR_CAMERA_FOV", "CITY_LANE_DETECTOR",
    "USE_ML_LANE_DETECTOR", "ML_LANE_MODEL",
    "ENCODER_PULSE_DISTANCE_CM", "ENCODER_WHEELBASE_CM",
}
LIVE_KEYS = {
    "SIMULATOR_TARGET_SPEED", "SIMULATOR_THROTTLE_LIMIT",
    "SIMULATOR_STOP_ON_LOST_LANE", "SIMULATOR_STOP_ON_CROSSWALK",
    "SIMULATOR_OBSTACLE_STOP_DISTANCE_CM", "SIMULATOR_STEERING_INVERTED",
    "SIMULATOR_AVIS_SENSOR_ANGLE", "USE_BEV", "DEBUG",
    "RL_TOP_ROI", "RL_BOTTOM_ROI", "RL_LEFT_ROI", "RL_RIGHT_ROI",
    "LL_TOP_ROI", "LL_BOTTOM_ROI", "LL_LEFT_ROI", "LL_RIGHT_ROI",
    "CW_TOP_ROI", "CW_BOTTOM_ROI", "CW_LEFT_ROI", "CW_RIGHT_ROI",
}


def _get_config_values(config):
    return {key: getattr(config, key) for key in SIMULATOR_KEYS if hasattr(config, key)}


def register_simulator_routes(app, streamer):
    @app.get("/api/simulation/state")
    def simulator_state():
        runtime = getattr(streamer.config, "simulation_runtime", None)
        if runtime is None:
            return jsonify(success=False, message="simulation runtime is not initialized"), 503
        return jsonify(runtime.snapshot())

    @app.get("/api/simulation/settings")
    def simulator_settings():
        caps = mode_capabilities(streamer.config)
        return jsonify(
            success=True,
            mode=getattr(streamer.config, "MODE", "simulation"),
            backend=caps.get("simulator_backend"),
            vision_profile=caps.get("vision_profile"),
            controls_enabled=bool(getattr(streamer.config, "STREAM_ALLOW_CONTROL", False)),
            settings=_get_config_values(streamer.config),
            option_groups=caps.get("option_groups", []),
        )

    @app.post("/api/simulation/settings")
    def update_simulator_settings():
        if not streamer._control_allowed():
            return streamer._control_denied()
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(success=False, message="JSON object required"), 400
        patch = body.get("settings", body)
        if not isinstance(patch, dict) or not patch:
            return jsonify(success=False, message="settings must be a non-empty object"), 400
        unknown = set(patch) - SIMULATOR_KEYS
        if unknown:
            return jsonify(success=False, message="unsupported settings: " + ", ".join(sorted(unknown))), 400
        backend = str(getattr(streamer.config, "SIMULATOR_BACKEND", ""))
        caps = mode_capabilities(streamer.config)
        profile = caps.get("vision_profile", "city")
        carla_only = {"SIMULATOR_VEHICLE_FILTER", "SIMULATOR_CAMERA_FOV"} | {
            key for key in patch if key.startswith("SIMULATOR_LIDAR_")
        }
        if backend != "carla" and (set(patch) & carla_only):
            return jsonify(success=False, message="Vehicle blueprint, camera FOV and LiDAR settings are available only in CARLA mode"), 400
        if backend != "avis" and "SIMULATOR_AVIS_SENSOR_ANGLE" in patch:
            return jsonify(success=False, message="Distance-sensor angle is available only in AVIS Engine modes"), 400
        if profile != "city" and "CITY_LANE_DETECTOR" in patch:
            return jsonify(success=False, message="CITY_LANE_DETECTOR is available only for the City vision profile"), 400
        if profile != "race" and ({"USE_ML_LANE_DETECTOR", "ML_LANE_MODEL"} & set(patch)):
            return jsonify(success=False, message="ML lane settings are available only for the Race vision profile"), 400
        if "SIMULATOR_TARGET_SPEED" in patch:
            try:
                target_speed = float(patch["SIMULATOR_TARGET_SPEED"])
            except (TypeError, ValueError, OverflowError):
                return jsonify(success=False, message="SIMULATOR_TARGET_SPEED must be numeric"), 400
            maximum_speed = 100 if backend == "avis" else 200
            if not math.isfinite(target_speed) or target_speed < 0 or target_speed > maximum_speed:
                return jsonify(success=False, message=f"Target speed must be between 0 and {maximum_speed} for {backend.upper()}"), 400
            patch["SIMULATOR_TARGET_SPEED"] = target_speed
        if profile != "city" and "SIMULATOR_STOP_ON_CROSSWALK" in patch:
            return jsonify(success=False, message="Crosswalk braking is available only for the City vision profile"), 400
        if "SIMULATOR_OBSTACLE_STOP_DISTANCE_CM" in patch:
            try:
                obstacle_distance = float(patch["SIMULATOR_OBSTACLE_STOP_DISTANCE_CM"])
            except (TypeError, ValueError, OverflowError):
                return jsonify(success=False, message="SIMULATOR_OBSTACLE_STOP_DISTANCE_CM must be numeric"), 400
            if not math.isfinite(obstacle_distance) or not 0 <= obstacle_distance <= 500:
                return jsonify(success=False, message="Obstacle stop distance must be between 0 and 500 cm"), 400
            patch["SIMULATOR_OBSTACLE_STOP_DISTANCE_CM"] = obstacle_distance
        if "SIMULATOR_PORT" in patch:
            value = patch["SIMULATOR_PORT"]
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
                return jsonify(success=False, message="SIMULATOR_PORT must be an integer from 1 to 65535"), 400
        for key in ("SIMULATOR_TIMEOUT_S", "SIMULATOR_LIDAR_RANGE_M",
                    "SIMULATOR_LIDAR_ROTATION_FREQUENCY", "SIMULATOR_CAMERA_FOV",
                    "ENCODER_PULSE_DISTANCE_CM"):
            if key in patch:
                try:
                    value = float(patch[key])
                except (TypeError, ValueError, OverflowError):
                    return jsonify(success=False, message=key + " must be numeric"), 400
                if not math.isfinite(value) or value <= 0:
                    return jsonify(success=False, message=key + " must be positive and finite"), 400
                patch[key] = value
        if "SIMULATOR_THROTTLE_LIMIT" in patch:
            try:
                value = float(patch["SIMULATOR_THROTTLE_LIMIT"])
            except (TypeError, ValueError, OverflowError):
                return jsonify(success=False, message="SIMULATOR_THROTTLE_LIMIT must be numeric"), 400
            if not math.isfinite(value) or not 0 <= value <= 1:
                return jsonify(success=False, message="SIMULATOR_THROTTLE_LIMIT must be between 0 and 1"), 400
            patch["SIMULATOR_THROTTLE_LIMIT"] = value
        for key in ("SIMULATOR_LIDAR_ENABLED", "SIMULATOR_STOP_ON_LOST_LANE",
                    "SIMULATOR_STOP_ON_CROSSWALK", "SIMULATOR_STEERING_INVERTED",
                    "USE_BEV", "USE_ML_LANE_DETECTOR", "DEBUG"):
            if key in patch and not isinstance(patch[key], bool):
                return jsonify(success=False, message=key + " must be boolean"), 400
        for key in ("RL_TOP_ROI", "RL_BOTTOM_ROI", "RL_LEFT_ROI", "RL_RIGHT_ROI",
                    "LL_TOP_ROI", "LL_BOTTOM_ROI", "LL_LEFT_ROI", "LL_RIGHT_ROI",
                    "CW_TOP_ROI", "CW_BOTTOM_ROI", "CW_LEFT_ROI", "CW_RIGHT_ROI"):
            if key in patch:
                try:
                    value = float(patch[key])
                except (TypeError, ValueError, OverflowError):
                    return jsonify(success=False, message=key + " must be numeric"), 400
                if not math.isfinite(value) or not 0 <= value <= 1:
                    return jsonify(success=False, message=key + " must be between 0 and 1"), 400
                patch[key] = value
        if patch.get("WITH_SIGN") and patch.get("WITH_APRILTAG"):
            return jsonify(success=False, message="Choose traffic signs or AprilTags, not both"), 400
        try:
            saved = save_simulator_settings(streamer.config, getattr(streamer.config, "MODE", "simulation"), patch)
        except (TypeError, ValueError, OSError) as exc:
            return jsonify(success=False, message=str(exc)), 400

        runtime = getattr(streamer.config, "simulation_runtime", None)
        sensor_angle_applied = False
        if "SIMULATOR_AVIS_SENSOR_ANGLE" in patch and runtime is not None:
            setter = getattr(runtime.adapter, "set_sensor_angle", None)
            if callable(setter):
                try:
                    sensor_angle_applied = bool(setter(int(patch["SIMULATOR_AVIS_SENSOR_ANGLE"])))
                except Exception:
                    sensor_angle_applied = False
        restart_required = sorted(set(patch) & RESTART_KEYS)
        return jsonify(
            success=True,
            settings=saved,
            restart_required=restart_required,
            live_applied=sorted(set(patch) & LIVE_KEYS),
            sensor_angle_applied=sensor_angle_applied,
            message=("Saved. Reconnect/restart is required for connection or sensor hardware changes."
                     if restart_required else "Settings saved and applied to the active simulator."),
        )

