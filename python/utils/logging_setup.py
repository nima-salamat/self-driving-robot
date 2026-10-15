import logging
import os
from logging.handlers import RotatingFileHandler


_LOGGER_CONFIGURED = "_self_driving_robot_logging_configured"
_LOG_LEVEL_NAMES = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def _configure_dependency_log_levels():
    """Keep high-frequency Picamera2 internals at WARNING."""
    # Picamera2 can emit an "Execute job" DEBUG record for nearly every frame.
    # Keep this noisy camera-library logger at WARNING even when application
    # DEBUG logging is explicitly requested.
    for name in ("picamera2", "picamera2.picamera2"):
        logging.getLogger(name).setLevel(logging.WARNING)


def configure_logging(level="INFO", log_dir="output"):
    """Configure console and rotating-file logging at the selected severity."""
    if not isinstance(level, str) or level.upper() not in _LOG_LEVEL_NAMES:
        choices = ", ".join(_LOG_LEVEL_NAMES)
        raise ValueError(f"Invalid log level {level!r}; expected one of: {choices}")

    normalized_level = level.upper()
    numeric_level = getattr(logging, normalized_level)

    logging.disable(logging.NOTSET)
    root = logging.getLogger()
    root.setLevel(numeric_level)
    _configure_dependency_log_levels()

    if getattr(root, _LOGGER_CONFIGURED, False):
        # Keep both output destinations in sync if logging is configured again.
        for handler in root.handlers:
            handler.setLevel(numeric_level)
        return

    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "robot.log")
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setLevel(numeric_level)
    console.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(formatter)

    root.addHandler(console)
    root.addHandler(file_handler)
    setattr(root, _LOGGER_CONFIGURED, True)

    logging.getLogger(__name__).info(
        "Logging initialized at %s: %s", normalized_level, log_path
    )
