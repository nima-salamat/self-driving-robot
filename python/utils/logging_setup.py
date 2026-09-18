import logging
import os
from logging.handlers import RotatingFileHandler


_LOGGER_CONFIGURED = "_self_driving_robot_logging_configured"


def configure_logging(debug=False, log_dir="output"):
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)

    if getattr(root, _LOGGER_CONFIGURED, False):
        for handler in root.handlers:
            if isinstance(handler, logging.StreamHandler):
                handler.setLevel(logging.DEBUG if debug else logging.INFO)
        return

    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "robot.log")
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if debug else logging.INFO)
    console.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    root.addHandler(console)
    root.addHandler(file_handler)
    setattr(root, _LOGGER_CONFIGURED, True)

    logging.getLogger(__name__).info("Logging initialized: %s", log_path)
