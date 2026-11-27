"""Central application logging for the main process and spawned workers."""
from __future__ import annotations

import atexit
import logging
import multiprocessing as mp
import os
import threading
from logging.handlers import QueueHandler, QueueListener, RotatingFileHandler

_LOGGER_CONFIGURED = "_self_driving_robot_logging_configured"
_LOGGING_STATE = "_self_driving_robot_logging_state"
_LOG_LEVEL_NAMES = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_FLUSH_LOGGER = "_self_driving_robot_internal_flush"
_FLUSH_WAITERS: dict[str, threading.Event] = {}
_FLUSH_WAITERS_LOCK = threading.Lock()
_ATEXIT_REGISTERED = False


def _normalize_level(level: str) -> tuple[str, int]:
    if not isinstance(level, str) or level.upper() not in _LOG_LEVEL_NAMES:
        choices = ", ".join(_LOG_LEVEL_NAMES)
        raise ValueError(f"Invalid log level {level!r}; expected one of: {choices}")
    normalized = level.upper()
    return normalized, getattr(logging, normalized)


def _configure_dependency_log_levels() -> None:
    """Keep high-frequency Picamera2 internals at WARNING, even in DEBUG."""
    for name in ("picamera2", "picamera2.picamera2"):
        logging.getLogger(name).setLevel(logging.WARNING)


class _RootHandlerDispatcher(logging.Handler):
    """Deliver worker records to the main process' current root handlers."""

    def __init__(self, root: logging.Logger) -> None:
        super().__init__(logging.NOTSET)
        self.root = root

    def emit(self, record: logging.LogRecord) -> None:
        if record.name == _FLUSH_LOGGER:
            token = str(record.getMessage())
            with _FLUSH_WAITERS_LOCK:
                waiter = _FLUSH_WAITERS.pop(token, None)
            if waiter is not None:
                waiter.set()
            return

        for handler in tuple(self.root.handlers):
            if isinstance(handler, QueueHandler):
                continue
            if record.levelno < handler.level:
                continue
            try:
                handler.handle(record)
            except Exception:
                self.handleError(record)


def configure_logging(level: str = "INFO", log_dir: str | os.PathLike[str] = "output") -> str:
    """Configure one durable log sink and a process-safe worker log queue."""
    global _ATEXIT_REGISTERED
    normalized_level, numeric_level = _normalize_level(level)
    normalized_dir = os.path.abspath(os.path.expanduser(os.fspath(log_dir)))

    logging.disable(logging.NOTSET)
    root = logging.getLogger()
    root.setLevel(numeric_level)
    _configure_dependency_log_levels()

    state = getattr(root, _LOGGING_STATE, None)
    if state is not None:
        if state["log_dir"] != normalized_dir:
            raise RuntimeError(
                "Central logging is already active at " + state["log_dir"] +
                "; stop the runtime before changing the log directory to " + normalized_dir
            )
        state["level"] = normalized_level
        for handler in state["managed_handlers"]:
            handler.setLevel(numeric_level)
        return state["log_path"]

    os.makedirs(normalized_dir, exist_ok=True)
    log_path = os.path.join(normalized_dir, "robot.log")
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(processName)s[%(process)d] | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console = logging.StreamHandler()
    console.setLevel(numeric_level)
    console.setFormatter(formatter)
    file_handler = RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=10,
        encoding="utf-8", delay=True,
    )
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(formatter)

    context = mp.get_context("spawn")
    log_queue = context.Queue()
    dispatcher = _RootHandlerDispatcher(root)
    listener = QueueListener(log_queue, dispatcher, respect_handler_level=True)
    root.addHandler(console)
    root.addHandler(file_handler)
    state = {
        "log_dir": normalized_dir, "log_path": log_path,
        "level": normalized_level, "queue": log_queue,
        "listener": listener, "dispatcher": dispatcher,
        "managed_handlers": (console, file_handler),
    }
    setattr(root, _LOGGING_STATE, state)
    setattr(root, _LOGGER_CONFIGURED, True)
    listener.start()

    if not _ATEXIT_REGISTERED:
        atexit.register(shutdown_logging)
        _ATEXIT_REGISTERED = True
    logging.getLogger(__name__).info(
        "Central logging initialized at %s; worker records use the main-process collector",
        log_path,
    )
    return log_path


def get_logging_context():
    """Return the active multiprocessing queue and severity for child workers."""
    state = getattr(logging.getLogger(), _LOGGING_STATE, None)
    return (state["queue"], state["level"]) if state is not None else (None, "INFO")


def get_managed_handlers():
    """Return the console/file handlers owned by this central logger."""
    state = getattr(logging.getLogger(), _LOGGING_STATE, None)
    return tuple(state["managed_handlers"]) if state is not None else ()


def configure_worker_logging(log_queue, level: str = "INFO") -> bool:
    """Route a spawned worker's root logger to the central main-process queue."""
    if log_queue is None:
        return False
    _normalized_level, numeric_level = _normalize_level(level)
    logging.disable(logging.NOTSET)
    root = logging.getLogger()
    for handler in tuple(root.handlers):
        root.removeHandler(handler)
        if isinstance(handler, QueueHandler):
            handler.close()
    root.setLevel(numeric_level)
    queue_handler = QueueHandler(log_queue)
    queue_handler.setLevel(numeric_level)
    root.addHandler(queue_handler)
    _configure_dependency_log_levels()
    multiprocessing_logger = logging.getLogger("multiprocessing")
    multiprocessing_logger.setLevel(logging.WARNING)
    multiprocessing_logger.propagate = False
    return True


def flush_logging(timeout: float = 3.0) -> bool:
    """Wait until records already queued by child processes reach all sinks."""
    state = getattr(logging.getLogger(), _LOGGING_STATE, None)
    if state is None:
        return True
    token = os.urandom(16).hex()
    waiter = threading.Event()
    with _FLUSH_WAITERS_LOCK:
        _FLUSH_WAITERS[token] = waiter
    record = logging.LogRecord(_FLUSH_LOGGER, logging.INFO, __file__, 0, token, None, None)
    try:
        state["queue"].put(record)
    except Exception:
        with _FLUSH_WAITERS_LOCK:
            _FLUSH_WAITERS.pop(token, None)
        return False
    completed = waiter.wait(max(0.0, float(timeout)))
    if not completed:
        with _FLUSH_WAITERS_LOCK:
            _FLUSH_WAITERS.pop(token, None)
    return completed


def shutdown_logging() -> None:
    """Drain the worker queue and close the central handlers cleanly."""
    root = logging.getLogger()
    state = getattr(root, _LOGGING_STATE, None)
    if state is None:
        return
    try:
        state["listener"].stop()
    except Exception:
        logging.getLogger(__name__).exception("Could not stop central log listener cleanly")
    for handler in state["managed_handlers"]:
        root.removeHandler(handler)
        try:
            handler.flush()
        finally:
            handler.close()
    try:
        state["queue"].close()
        state["queue"].join_thread()
    except (AttributeError, OSError, ValueError):
        pass
    for name in (_LOGGING_STATE, _LOGGER_CONFIGURED):
        if hasattr(root, name):
            delattr(root, name)


__all__ = [
    "configure_logging", "configure_worker_logging", "get_logging_context",
    "get_managed_handlers", "flush_logging", "shutdown_logging",
]
