import signal
import sys
import threading

from utils.parser import parse_args
from utils.config_mode import set_city_mode, set_race_mode
from utils import json_config
from utils.preflight import run_preflight
from utils.logging_setup import configure_logging
from utils.runtime_metrics import RuntimeMetrics
from utils.health import HealthMonitor
from arduino.hardware_contract import ArduinoHardwareConfigError
import base_config


def _install_shutdown_handlers(shutdown_event):
    def request_shutdown(signum, _frame):
        shutdown_event.set()

    signal.signal(signal.SIGINT, request_shutdown)
    signal.signal(signal.SIGTERM, request_shutdown)


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

    # Load JSON first so explicit CLI flags remain authoritative.
    json_config.load()

    config.DEBUG = args.debug
    config.STREAM = args.stream
    config.SHOW_FPS = args.fps
    config.PERFORMANCE = args.performance
    config.WITHOUT_ARDUINO = args.without_arduino
    config.READ_ARDUINO_OUTPUT = args.read_arduino_output
    config.ARDUINO_CONFIG = args.arduino_config
    config.ARDUINO_CONTRACT_TIMEOUT = args.arduino_contract_timeout
    config.STREAM_ALLOW_CONTROL = args.stream_control
    config.USE_ML_LANE_DETECTOR = args.ml_lane_model is not None
    if args.ml_lane_model is not None:
        config.ML_LANE_MODEL = args.ml_lane_model
    if args.stream_host:
        config.STREAM_HOST = args.stream_host

    if args.ml_lane_model is not None and args.mode != "race":
        raise SystemExit("--ml-lane-model is currently supported only in race mode")

    config.MODE = args.mode
    base_config.MODE = args.mode

    configure_logging(debug=args.debug, log_dir=getattr(config, "OUTPUT_DIR", "output"))

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
