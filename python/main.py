import importlib
import os
import signal
import sys
import threading

from arduino.hardware_contract import ArduinoHardwareConfigError
from utils import json_config
from utils.config_mode import set_city_mode, set_race_mode
from utils.health import HealthMonitor
from utils.logging_setup import configure_logging
from utils.parser import parse_args
from utils.preflight import run_preflight
from utils.runtime_metrics import RuntimeMetrics
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
        "SEND_TRAFFIC_STOP_COMMAND": args.send_traffic_stop_command,
        "STREAM_ALLOW_CONTROL": args.stream_control,
        "CAMERA_MODE": args.camera_mode,
        "USBCAM_ADDR": args.camera_index,
        "ARDUINO_CONFIG": args.arduino_config,
        "ARDUINO_CONTRACT_TIMEOUT": args.arduino_contract_timeout,
        "CITY_LANE_DETECTOR": getattr(args, "city_lane_detector", None),
        "STREAM_HOST": getattr(args, "stream_host", None),
    }

    for name, value in overrides.items():
        if value is not None:
            setattr(config, name, value)

    config.TRAFFIC_LIGHTS_ENABLED = bool(getattr(args, "traffic_lights", False))
    config.TRAFFIC_LIGHT_WAIT_BEFORE_CHECK = bool(getattr(args, "traffic_light_wait_before_check", False))

    # Only an explicit CLI path may enable the strict hello/cfg handshake.
    # Do not allow a stale city.json/race.json value to turn it on implicitly.
    config.ARDUINO_CONFIG = args.arduino_config

    if args.ml_lane_model is not None:
        config.USE_ML_LANE_DETECTOR = True
        config.ML_LANE_MODEL = args.ml_lane_model


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
        debug=getattr(config, "DEBUG", False),
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
