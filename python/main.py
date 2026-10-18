import importlib
import os
import signal
import sys
import threading
import math

from arduino.hardware_contract import ArduinoHardwareConfigError
from utils import json_config
from utils.config_mode import set_city_mode, set_race_mode
from utils.health import HealthMonitor
from utils.logging_setup import configure_logging
from utils.parser import parse_args
from utils.preflight import run_preflight
from utils.runtime_metrics import RuntimeMetrics
from utils.processing_rate import DEFAULT_TARGET_FPS
import base_config


def _install_shutdown_handlers(shutdown_event):
    def request_shutdown(signum, _frame):
        shutdown_event.set()

    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)


def _apply_platform_defaults(config, platform_name=None):
    """Apply operating-system defaults before per-run CLI overrides."""
    platform_name = os.name if platform_name is None else platform_name
    if platform_name == "nt":
        # The Arduino serial transport is intentionally disabled on Windows.
        config.WITHOUT_ARDUINO = True


def _validate_ml_lane_runtime(config):
    """Fail before opening hardware when the explicitly selected ML runtime is missing."""
    if not bool(getattr(config, "USE_ML_LANE_DETECTOR", False)):
        return

    try:
        importlib.import_module("ncnn")
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        raise SystemExit(
            "ML lane detection is enabled, but the NCNN Python runtime could "
            f"not be loaded ({detail}). Install the project dependencies in "
            "the same Python environment used to run this command. From the "
            "repository root run: python3 -m pip install -r requirements.txt"
        ) from None


def _apply_cli_overrides(config, args):
    overrides = {
        "DEBUG": args.debug,
        "STREAM": args.stream,
        "SHOW_FPS": args.fps,
        "PERFORMANCE": args.performance,
        "WITHOUT_ARDUINO": args.without_arduino,
        "READ_ARDUINO_OUTPUT": args.read_arduino_output,
        "SEND_TRAFFIC_STOP_COMMAND": getattr(args, "send_traffic_stop_command", None),
        "STREAM_ALLOW_CONTROL": args.stream_control,
        "CAMERA_MODE": args.camera_mode,
        "USBCAM_ADDR": args.camera_index,
        # Multiprocessing is a strict CLI opt-in, not a JSON default.
        # It isolates both camera capture and sign inference while keeping all
        # steering/control decisions in the owning mode process.
        "MULTIPROCESS_CAMERA": getattr(args, "multiprocess_camera", False),
        "MULTIPROCESS_SIGN_DETECTOR": getattr(args, "multiprocess_camera", False),
        "ARDUINO_CONFIG": args.arduino_config,
        "ARDUINO_CONTRACT_TIMEOUT": args.arduino_contract_timeout,
        "CITY_LANE_DETECTOR": getattr(args, "city_lane_detector", None),
        "STREAM_HOST": getattr(args, "stream_host", None),
        # Request access logs are a strict CLI opt-in. An omitted flag must
        # suppress noisy HTTP polling logs even if stale JSON sets it true.
        "STREAM_REQUEST_LOGS": getattr(args, "stream_request_logs", False),
        "TARGET_PROCESSING_FPS": getattr(args, "target_fps", DEFAULT_TARGET_FPS),
    }

    for name, value in overrides.items():
        if value is not None:
            setattr(config, name, value)

    if getattr(args, "mode", None) == "race":
        config.RACE_START_ON_STOP_SIGN = bool(
            getattr(args, "race_start_on_stop_sign", False)
        )
        # Timed finishing is a strict paired CLI opt-in; JSON cannot enable it.
        config.RACE_FINISH_AFTER_SECONDS = None
        config.RACE_FINISH_SPEED = None
        for name, value in (
            ("RACE_STOP_ABSENCE_SECONDS", getattr(args, "race_stop_absence_seconds", None)),
            ("RACE_STOP_CONFIDENCE_THRESHOLD", getattr(args, "race_stop_confidence_threshold", None)),
        ):
            if value is not None:
                setattr(config, name, value)
        finish_after = getattr(args, "race_finish_after_seconds", None)
        finish_speed = getattr(args, "race_finish_speed", None)
        if finish_after is not None or finish_speed is not None:
            config.RACE_FINISH_AFTER_SECONDS = finish_after
            config.RACE_FINISH_SPEED = finish_speed

    config.TRAFFIC_LIGHTS_ENABLED = bool(getattr(args, "traffic_lights", False))
    config.TRAFFIC_LIGHT_WAIT_BEFORE_CHECK = bool(getattr(args, "traffic_light_wait_before_check", False))

    # Feature enablement is a strict CLI opt-in; JSON values cannot turn these
    # capabilities on. Calibration values by themselves never enable them.
    config.ENCODER_MAP_ENABLED = bool(getattr(args, "encoder_map", False))
    config.CONFIDENCE_AWARE_ENABLED = bool(getattr(args, "confidence_aware", False))
    config.ADAPTIVE_OBSTACLE_AVOIDANCE_ENABLED = bool(
        getattr(args, "adaptive_obstacle_avoidance", False)
    )
    # Optional physical calibration values follow the normal precedence:
    # mode defaults -> mode JSON -> explicit CLI override. An omitted CLI
    # argument must not erase a calibration already set for this mode.
    for name, value in (
        ("ENCODER_PULSE_DISTANCE_CM", getattr(args, "encoder_pulse_distance_cm", None)),
        ("ENCODER_WHEELBASE_CM", getattr(args, "encoder_wheelbase_cm", None)),
        ("ENCODER_ROAD_ANGLE_MIN_DEG", getattr(args, "encoder_road_wheel_angle_at_servo_min_deg", None)),
        ("ENCODER_ROAD_ANGLE_MAX_DEG", getattr(args, "encoder_road_wheel_angle_at_servo_max_deg", None)),
    ):
        if value is not None:
            setattr(config, name, value)

    for name, value in (
        ("CONFIDENCE_SLOW_THRESHOLD", getattr(args, "confidence_slow_threshold", 0.65)),
        ("CONFIDENCE_STOP_THRESHOLD", getattr(args, "confidence_stop_threshold", 0.30)),
        ("OBSTACLE_TRIGGER_DISTANCE_CM", getattr(args, "obstacle_trigger_distance_cm", 35.0)),
        ("OBSTACLE_STOP_DISTANCE_CM", getattr(args, "obstacle_stop_distance_cm", 4.0)),
        ("OBSTACLE_LANE_WIDTH_CM", getattr(args, "obstacle_lane_width_cm", None)),
        ("OBSTACLE_ROBOT_WIDTH_CM", getattr(args, "obstacle_robot_width_cm", None)),
        ("OBSTACLE_CLEARANCE_CM", getattr(args, "obstacle_clearance_cm", None)),
    ):
        setattr(config, name, value)

    # Only an explicit CLI path may enable the strict hello/cfg handshake.
    # Do not allow a stale city.json/race.json value to turn it on implicitly.
    config.ARDUINO_CONFIG = getattr(args, "arduino_config", None)

    if getattr(args, "ml_lane_model", None) is not None:
        config.USE_ML_LANE_DETECTOR = True
        config.ML_LANE_MODEL = args.ml_lane_model


def _validate_opt_in_features(config, args):
    def positive(value, name):
        if value is None or not math.isfinite(float(value)) or float(value) <= 0:
            raise SystemExit(f"{name} must be supplied as a positive finite value")

    # Calibration has already been merged using active mode defaults, its JSON,
    # then explicit CLI overrides.
    encoder_pulse_distance = getattr(config, "ENCODER_PULSE_DISTANCE_CM", None)
    encoder_wheelbase = getattr(config, "ENCODER_WHEELBASE_CM", None)
    encoder_road_min = getattr(config, "ENCODER_ROAD_ANGLE_MIN_DEG", None)
    encoder_road_max = getattr(config, "ENCODER_ROAD_ANGLE_MAX_DEG", None)

    if (args.race_start_on_stop_sign or args.race_finish_after_seconds is not None or
            args.race_finish_speed is not None) and args.mode != "race":
        raise SystemExit("Race start/finish options are supported only in race mode")
    if args.race_finish_after_seconds is not None and args.race_finish_speed is None:
        raise SystemExit("--race-finish-after-seconds requires --race-finish-speed")
    if args.race_finish_speed is not None and args.race_finish_after_seconds is None:
        raise SystemExit("--race-finish-speed requires --race-finish-after-seconds")
    if args.race_finish_speed is not None and not -255 <= args.race_finish_speed <= 255:
        raise SystemExit("--race-finish-speed must be between -255 and 255")
    if args.mode == "race" and args.race_start_on_stop_sign:
        absence = float(getattr(config, "RACE_STOP_ABSENCE_SECONDS", 1.0))
        if not math.isfinite(absence) or absence < 0:
            raise SystemExit("Race STOP absence duration must be finite and non-negative")
    if args.mode == "race" and (
        args.race_start_on_stop_sign or args.race_finish_after_seconds is not None
    ):
        threshold = float(getattr(config, "RACE_STOP_CONFIDENCE_THRESHOLD", 0.2))
        if not math.isfinite(threshold) or not 0 <= threshold <= 1:
            raise SystemExit("Race STOP confidence threshold must be between 0 and 1")
    if (args.mode == "race" and
            (args.race_start_on_stop_sign or args.race_finish_after_seconds is not None) and
            getattr(config, "SIGN_DETECTOR_METHOD", "yolo") == "svm"):
        raise SystemExit(
            "Race STOP start/finish requires the YOLO detector, which exposes "
            "model confidence; the SVM detector does not expose confidence"
        )

    if args.encoder_map:
        if not args.stream:
            raise SystemExit("--encoder-map requires --stream")
        if args.without_arduino or getattr(config, "WITHOUT_ARDUINO", False):
            raise SystemExit("--encoder-map requires an active Arduino serial connection")
        positive(encoder_pulse_distance, "--encoder-pulse-distance-cm or active mode ENCODER_PULSE_DISTANCE_CM")
        wheelbase = encoder_wheelbase
        road_min = encoder_road_min
        road_max = encoder_road_max
        supplied = (wheelbase is not None, road_min is not None, road_max is not None)
        if any(supplied) and not all(supplied):
            raise SystemExit("2D odometry requires all of --encoder-wheelbase-cm and both --encoder-road-wheel-angle-at-servo-{min,max}-deg; omit all three for pulse/distance-only view")
        if all(supplied):
            positive(wheelbase, "--encoder-wheelbase-cm")
            if not (math.isfinite(road_min) and math.isfinite(road_max) and
                    -45 <= road_min < 0 < road_max <= 45):
                raise SystemExit("road-wheel calibration must be finite, signed, and satisfy -45 <= min < 0 < max <= 45 degrees")
        low = float(getattr(config, "MIN_SERVO_ANGLE", 55))
        high = float(getattr(config, "MAX_SERVO_ANGLE", 125))
        center = float(getattr(config, "SERVO_CENTER", 95))
        if not low < center < high:
            raise SystemExit("active servo limits must contain the calibrated SERVO_CENTER")
        if all(supplied):
            center_wheel_angle = road_min + (center - low) / (high - low) * (road_max - road_min)
            if abs(center_wheel_angle) > 5.0:
                raise SystemExit("steering calibration must map the active calibrated servo center to within 5 degrees of zero road-wheel angle")
    if args.confidence_aware:
        slow, stop = args.confidence_slow_threshold, args.confidence_stop_threshold
        if not (math.isfinite(slow) and math.isfinite(stop) and 0 <= stop < slow <= 1):
            raise SystemExit("confidence thresholds must satisfy 0 <= stop < slow <= 1")
    if args.adaptive_obstacle_avoidance:
        if args.mode != "race":
            raise SystemExit("--adaptive-obstacle-avoidance is currently supported only in race mode")
        if args.without_arduino or getattr(config, "WITHOUT_ARDUINO", False):
            raise SystemExit("--adaptive-obstacle-avoidance requires an active Arduino connection")
        positive(encoder_pulse_distance, "--encoder-pulse-distance-cm or active mode ENCODER_PULSE_DISTANCE_CM")
        if not args.stream:
            raise SystemExit("--adaptive-obstacle-avoidance currently requires --stream for live diagnostics")
        if getattr(config, "USE_ML_LANE_DETECTOR", False):
            raise SystemExit("--adaptive-obstacle-avoidance requires the default Race lane detector; ML geometry is not calibrated for corridor assessment")
        for value, name in ((args.obstacle_lane_width_cm, "--obstacle-lane-width-cm"),
                            (args.obstacle_robot_width_cm, "--obstacle-robot-width-cm"),
                            (args.obstacle_clearance_cm, "--obstacle-clearance-cm")):
            positive(value, name)
        if not (math.isfinite(args.obstacle_trigger_distance_cm) and
                math.isfinite(args.obstacle_stop_distance_cm) and
                0 < args.obstacle_stop_distance_cm < args.obstacle_trigger_distance_cm):
            raise SystemExit("obstacle distances must satisfy 0 < emergency stop < trigger distance")
        if args.obstacle_lane_width_cm <= args.obstacle_robot_width_cm + 2 * args.obstacle_clearance_cm:
            raise SystemExit("lane width must exceed robot width plus required clearance on both sides")
        if encoder_wheelbase is None or encoder_road_min is None or encoder_road_max is None:
            raise SystemExit("adaptive obstacle avoidance requires calibrated steering geometry in the active mode config or via --encoder-wheelbase-cm and both road-wheel-angle-at-servo-limit options")
        low = float(getattr(config, "MIN_SERVO_ANGLE", 55))
        high = float(getattr(config, "MAX_SERVO_ANGLE", 125))
        center = float(getattr(config, "SERVO_CENTER", 95))
        angle_at_center = encoder_road_min + (center - low) / (high - low) * (encoder_road_max - encoder_road_min)
        if abs(angle_at_center) > 5.0:
            raise SystemExit("steering calibration must map SERVO_CENTER to approximately zero road-wheel angle")


def _validate_selected_config(config):
    low = float(getattr(config, "MIN_SERVO_ANGLE", 55))
    high = float(getattr(config, "MAX_SERVO_ANGLE", 125))
    center = float(getattr(config, "SERVO_CENTER", 95))
    if not low < center < high:
        raise SystemExit("active servo limits must satisfy MIN_SERVO_ANGLE < SERVO_CENTER < MAX_SERVO_ANGLE")
    if getattr(config, "ADAPTIVE_OBSTACLE_AVOIDANCE_ENABLED", False):
        if getattr(config, "USE_ML_LANE_DETECTOR", False):
            raise SystemExit("adaptive obstacle avoidance requires the default Race classical lane processor")


if __name__ == "__main__":
    args = parse_args()

    if args.mode == "city":
        from modes.city import config_city as config
        from modes.city import start

        set_city_mode()
    else:
        from modes.race import config_race as config
        from modes.race import start

        set_race_mode()

    json_config.load()
    _apply_platform_defaults(config)
    _apply_cli_overrides(config, args)
    _validate_opt_in_features(config, args)
    _validate_selected_config(config)

    if args.traffic_lights and args.mode != "city":
        raise SystemExit("--traffic-lights is supported only in city mode")
    if args.traffic_light_wait_before_check and args.mode != "city":
        raise SystemExit("--traffic-light-wait-before-check is supported only in city mode")
    if args.traffic_light_wait_before_check and not args.traffic_lights:
        raise SystemExit("--traffic-light-wait-before-check requires --traffic-lights")

    if args.ml_lane_model is not None and args.mode != "race":
        raise SystemExit("--ml-lane-model is currently supported only in race mode")

    if args.city_lane_detector is not None and args.mode != "city":
        raise SystemExit("--city-lane-detector is currently supported only in city mode")

    if args.arduino_config and args.without_arduino:
        raise SystemExit("--arduino-config cannot be used together with --without-arduino")
    if os.name == "nt" and args.arduino_config:
        raise SystemExit(
            "--arduino-config is not supported on Windows because the Arduino "
            "serial transport is disabled on this platform."
        )

    if args.camera_index is not None and args.camera_index < 0:
        raise SystemExit("--camera-index must be a non-negative integer")

    config.MODE = args.mode
    base_config.MODE = args.mode

    configure_logging(
        level=args.log_level,
        log_dir=getattr(config, "OUTPUT_DIR", "output"),
    )
    if os.name == "nt":
        print("[Runtime] Windows detected; Arduino is disabled by default.", flush=True)

    if args.preflight:
        report = run_preflight(config)
        print(report.format())
        raise SystemExit(0 if report.ok else 1)

    config.runtime_metrics = RuntimeMetrics()
    config.health_monitor = HealthMonitor()

    _validate_ml_lane_runtime(config)

    shutdown_event = threading.Event()
    config.SHUTDOWN_EVENT = shutdown_event
    base_config.SHUTDOWN_EVENT = shutdown_event
    _install_shutdown_handlers(shutdown_event)

    try:
        start()
    except ArduinoHardwareConfigError as exc:
        print(f"[ARDUINO HARDWARE CONTRACT ERROR] {exc}", file=sys.stderr, flush=True)
        raise SystemExit(2)
