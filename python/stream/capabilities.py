"""Runtime capability metadata for hardware and simulator modes."""
from __future__ import annotations
from typing import Any
from modes.registry import get_mode_spec, is_simulation_mode

MODE_CAPABILITIES = {
    "city": {
        "lane_detectors": ("default", "blsf-beta"), "supports_ml_lane": False,
        "supports_bev": True, "supports_lane_roi": True,
        "supports_crosswalk": True, "supports_crosswalk_trapezoid": True,
        "supports_stop_line": False, "supports_traffic_lights": False,
        "supports_obstacle_avoidance": False, "supports_sign_actions": False,
        "supports_sign": True, "supports_apriltag": True,
        "supports_object_detection": True, "supports_recording": True,
    },
    "race": {
        "lane_detectors": ("default", "ml"), "supports_ml_lane": True,
        "supports_bev": True, "supports_lane_roi": True,
        "supports_crosswalk": False, "supports_crosswalk_trapezoid": False,
        "supports_sign": True, "supports_apriltag": True,
        "supports_object_detection": True, "supports_recording": True,
    },
}
MODE_CAPABILITIES["carla"] = {**MODE_CAPABILITIES["city"], "supports_lidar": True, "supports_range_sensors": False}
MODE_CAPABILITIES["avis"] = {
    **MODE_CAPABILITIES["city"], "supports_lidar": False, "supports_range_sensors": True,
    "supports_crosswalk": False, "supports_crosswalk_trapezoid": False,
    "supports_stop_line": True, "supports_traffic_lights": True,
    "supports_obstacle_avoidance": True, "supports_sign_actions": True,
}
MODE_CAPABILITIES["avis-race"] = {
    **MODE_CAPABILITIES["race"], "supports_lidar": False, "supports_range_sensors": True,
    "supports_obstacle_avoidance": True, "supports_sign_actions": True,
}


def marker_mode(config: Any) -> str:
    if bool(getattr(config, "WITH_APRILTAG", False)):
        return "apriltag"
    if bool(getattr(config, "WITH_SIGN", False)):
        return "sign"
    return "none"


def set_marker_mode(config: Any, mode: str) -> str:
    mode = str(mode).lower()
    if mode not in {"sign", "apriltag", "none"}:
        raise ValueError("marker mode must be sign, apriltag, or none")
    callback = getattr(config, "apply_marker_mode", None)
    if callable(callback):
        callback(mode)
        return mode
    sign, tag = mode == "sign", mode == "apriltag"
    setattr(config, "WITH_SIGN", sign)
    setattr(config, "WITH_APRILTAG", tag)
    if hasattr(config, "USE_SIGN"):
        setattr(config, "USE_SIGN", sign)
    return mode


def mode_capabilities(config: Any) -> dict[str, Any]:
    mode = str(getattr(config, "MODE", "city")).lower()
    try:
        spec = get_mode_spec(mode)
    except ValueError:
        spec = get_mode_spec("city")
    simulation = is_simulation_mode(mode)
    profile = str(getattr(config, "SIMULATION_VISION_PROFILE", spec.vision_profile)).lower()
    if profile not in {"city", "race"}:
        profile = spec.vision_profile
    base = dict(MODE_CAPABILITIES.get(mode, MODE_CAPABILITIES.get(profile, {})))
    lane_detector = "default"
    if profile == "city":
        lane_detector = str(getattr(config, "CITY_LANE_DETECTOR", "default"))
        if lane_detector not in base.get("lane_detectors", ("default",)):
            lane_detector = "default"
    elif profile == "race" and bool(getattr(config, "USE_ML_LANE_DETECTOR", False)):
        lane_detector = "ml"
    ml_active = bool(profile == "race" and getattr(config, "USE_ML_LANE_DETECTOR", False))
    backend = str(getattr(config, "SIMULATOR_BACKEND", spec.simulator_backend)) if simulation else None
    base.update({
        "mode": mode, "vision_profile": profile,
        "editor_profile": "simulator" if simulation else "standard",
        "simulator_backend": backend, "uses_virtual_io": simulation,
        "supports_lidar": bool(simulation and spec.supports_lidar),
        "supports_range_sensors": bool(simulation and spec.supports_range_sensors),
        "lane_detector": lane_detector, "ml_lane_detector": ml_active,
        "supports_lane_roi": bool(base.get("supports_lane_roi", False) and not ml_active
                                  and not (simulation and lane_detector == "blsf-beta")),
        "supports_bev": bool(base.get("supports_bev", False) and not ml_active),
        "supports_crosswalk": bool(base.get("supports_crosswalk", False) and
                                   not (simulation and lane_detector == "blsf-beta")),
        "bev": bool(getattr(config, "USE_BEV", False)),
        "sign_enabled": bool(getattr(config, "WITH_SIGN", False)),
        "apriltag_enabled": bool(getattr(config, "WITH_APRILTAG", False)),
        "object_detection_enabled": bool(getattr(config, "DETECT_OBJECT", False)),
        "recording_enabled": bool(getattr(config, "RECORD_VIDEO", False)),
        "stream_enabled": bool(getattr(config, "STREAM", False)),
        "encoder_map_enabled": bool(getattr(config, "ENCODER_MAP_ENABLED", False)),
        "confidence_aware_enabled": bool(getattr(config, "CONFIDENCE_AWARE_ENABLED", False)),
        "adaptive_obstacle_avoidance_enabled": bool(getattr(config, "ADAPTIVE_OBSTACLE_AVOIDANCE_ENABLED", False)),
        "simulator_obstacle_avoidance_enabled": bool(getattr(config, "SIMULATOR_OBSTACLE_AVOIDANCE_ENABLED", False)),
        "simulator_stop_line_enabled": bool(getattr(config, "SIMULATOR_STOP_LINE_ENABLED", False)),
        "simulator_traffic_lights_enabled": bool(getattr(config, "SIMULATOR_TRAFFIC_LIGHTS_ENABLED", False)),
        "simulator_sign_actions_enabled": bool(getattr(config, "SIMULATOR_SIGN_ACTIONS_ENABLED", False)),
        "stream_control_enabled": bool(getattr(config, "STREAM_ALLOW_CONTROL", False)),
        "marker_runtime_control": callable(getattr(config, "apply_marker_mode", None)),
    })
    if simulation:
        # AVIS uses the shared sign/light detectors through a simulator-only
        # behavior coordinator. No Arduino, physical race gate or actuator
        # sequence is reused by the simulator runtime.
        avis_backend = backend == "avis"
        base["supports_sign"] = avis_backend
        base["supports_apriltag"] = False
        base["supports_object_detection"] = False
        base["supports_recording"] = False
        base["supports_sign_actions"] = avis_backend
        base["supports_obstacle_avoidance"] = avis_backend
        base["supports_traffic_lights"] = bool(avis_backend and profile == "city")
        base["supports_stop_line"] = bool(avis_backend and profile == "city")
        if avis_backend and profile == "city":
            base["supports_crosswalk"] = False
            base["supports_crosswalk_trapezoid"] = False
        profile_description = (
            "City lane and stop-line perception" if profile == "city" and avis_backend
            else "City lane and crosswalk image processing" if profile == "city"
            else "Race lane image processing; physical Race sign/phase orchestration is not copied"
        )
        base["option_groups"] = [
            {"title": "Shared vision", "description": profile_description + ". The image processor and steering semantics are shared with the corresponding physical mode."},
            {"title": "Mode-specific vision", "description": "AVIS City stop-line and traffic-light ROIs; crosswalk detection is disabled in this environment." if profile == "city" and avis_backend else "City lane ROI, BEV and crosswalk tuning." if profile == "city" else "Race lane geometry and optional ML lane model; no City crosswalk processing."},
            {"title": "AVIS behavior layer", "description": "Optional range-based obstacle bypass and asynchronous STOP, PARK, STRAIGHT and TURN sign actions." if avis_backend else "No AVIS behavior layer is available for this backend."},
            {"title": "Virtual vehicle I/O", "description": "Normalized steering, throttle and brake replace serial commands. A motion-derived virtual encoder replaces unavailable hardware telemetry."},
            {"title": "Simulator sensors", "description": "CARLA camera and ray-cast LiDAR." if backend == "carla" else "AVIS camera and its native left/front/right distance sensors; no LiDAR point cloud is exposed by this adapter."},
        ]
    else:
        base["option_groups"] = []
    return base
