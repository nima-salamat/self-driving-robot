import signal
import threading

from utils.parser import parse_args
from utils.config_mode import set_city_mode, set_race_mode
from utils import json_config
from utils.preflight import run_preflight
from utils.logging_setup import configure_logging
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

    config.DEBUG = args.debug
    config.STREAM = args.stream
    config.SHOW_FPS = args.fps
    config.PERFORMANCE = args.performance
    config.WITHOUT_ARDUINO = args.without_arduino
    config.READ_ARDUINO_OUTPUT = args.read_arduino_output
    config.STREAM_ALLOW_CONTROL = args.stream_control
    if args.stream_host:
        config.STREAM_HOST = args.stream_host

    config.MODE = args.mode
    base_config.MODE = args.mode

    json_config.load()
    configure_logging(debug=args.debug, log_dir=getattr(config, "OUTPUT_DIR", "output"))

    if args.preflight:
        report = run_preflight(config)
        print(report.format())
        raise SystemExit(0 if report.ok else 1)

    shutdown_event = threading.Event()
    config.SHUTDOWN_EVENT = shutdown_event
    base_config.SHUTDOWN_EVENT = shutdown_event
    _install_shutdown_handlers(shutdown_event)

    start()
