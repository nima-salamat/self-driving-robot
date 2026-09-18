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


def _apply_cli_overrides(config, args):
    overrides = {
        "DEBUG": args.debug,
        "STREAM": args.stream,
        "SHOW_FPS": args.fps,
        "PERFORMANCE": args.performance,
        "WITHOUT_ARDUINO": args.without_arduino,
        "READ_ARDUINO_OUTPUT": args.read_arduino_output,
        "STREAM_ALLOW_CONTROL": args.stream_control,
        "CAMERA_MODE": args.camera_mode,
        "USBCAM_ADDR": args.camera_index,
        "ARDUINO_CONFIG": args.arduino_config,
        "ARDUINO_CONTRACT_TIMEOUT": args.arduino_contract_timeout,
    }

    for name, value in overrides.items():
        if value is not None:
            setattr(config, name, value)

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
    _apply_cli_overrides(config, args)

    if args.ml_lane_model is not None and args.mode != "race":
        raise SystemExit("--ml-lane-model is currently supported only in race mode")

    if args.arduino_config and args.without_arduino:
        raise SystemExit("--arduino-config cannot be used together with --without-arduino")

    if args.camera_index is not None and args.camera_index < 0:
        raise SystemExit("--camera-index must be a non-negative integer")

    config.MODE = args.mode
    base_config.MODE = args.mode

    configure_logging(
        debug=getattr(config, "DEBUG", False),
        log_dir=getattr(config, "OUTPUT_DIR", "output"),
    )

    if args.preflight:
        report = run_preflight(config)
        print(report.format())
        raise SystemExit(0 if report.ok else 1)

    config.runtime_metrics = RuntimeMetrics()
    config.health_monitor = HealthMonitor()

    shutdown_event = threading.Event()
    config.SHUTDOWN_EVENT = shutdown_event
    base_config.SHUTDOWN_EVENT = shutdown_event
    _install_shutdown_handlers(shutdown_event)

    try:
        start()
    except ArduinoHardwareConfigError as exc:
        print(f"[ARDUINO HARDWARE CONTRACT ERROR] {exc}", file=sys.stderr, flush=True)
        raise SystemExit(2)
