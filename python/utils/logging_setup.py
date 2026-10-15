import logging
import os
from logging.handlers import RotatingFileHandler


_LOGGER_CONFIGURED = "_self_driving_robot_logging_configured"


def _configure_dependency_log_levels():
    """Keep high-frequency Picamera2 internals at WARNING."""
    # Picamera2 can emit an "Execute job" DEBUG record for nearly every frame.
    # Keep these library internals at WARNING to avoid noise in the real-time loop.
    for name in ("picamera2", "picamera2.picamera2"):
        logging.getLogger(name).setLevel(logging.WARNING)


def configure_logging(debug=False, log_dir="output"):
    """Configure INFO-and-higher logging in every runtime mode.

    The debug argument remains in the signature for compatibility with callers.
    Mode-level debug flags control diagnostic visualizations; they do not lower
    the log verbosity threshold.
    """
    logging.disable(logging.NOTSET)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    _configure_dependency_log_levels()

    if getattr(root, _LOGGER_CONFIGURED, False):
        # Reconfiguration must not re-enable DEBUG records or leave old handlers
        # with a more permissive threshold.
        for handler in root.handlers:
            handler.setLevel(logging.INFO)
        return

    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "robot.log")
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    root.addHandler(console)
    root.addHandler(file_handler)
    setattr(root, _LOGGER_CONFIGURED, True)

    logging.getLogger(__name__).info("Logging initialized: %s", log_path)
