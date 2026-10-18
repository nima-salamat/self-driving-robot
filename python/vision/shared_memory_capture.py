"""Opt-in process-isolated camera capture using a shared-memory latest-frame slot."""
from __future__ import annotations

import logging
import multiprocessing as mp
import queue
import threading
import time
from multiprocessing.shared_memory import SharedMemory
from types import SimpleNamespace

import numpy as np

logger = logging.getLogger(__name__)

_SEQ, _CAPTURE_AT, _MEASURED_FPS, _VALID, _FAILURES = range(5)
_CAPTURE_MS, _PI_MODE, _INITIALIZED, _MIN_FPS, _MAX_FPS = range(5, 10)


def _state(metadata):
    return {
        "sequence": int(metadata[_SEQ]),
        "capture_at": float(metadata[_CAPTURE_AT]) if metadata[_CAPTURE_AT] > 0 else None,
        "fps": float(metadata[_MEASURED_FPS]) if metadata[_MEASURED_FPS] > 0 else None,
        "valid": bool(metadata[_VALID]),
        "failures": int(metadata[_FAILURES]),
        "duration_ms": max(0.0, float(metadata[_CAPTURE_MS])),
        "pi_mode": bool(metadata[_PI_MODE]),
        "initialized": int(metadata[_INITIALIZED]) == 1,
    }


def _queue_replace(target, item):
    try:
        target.put_nowait(item)
    except queue.Full:
        try:
            target.get_nowait()
        except queue.Empty:
            pass
        try:
            target.put_nowait(item)
        except queue.Full:
            pass


def _capture_process(config_values, shared_name, frame_shape, resized_shape,
                     raw_nbytes, lock, stop_event, frame_event, ready_event,
                     metadata, errors, commands, responses, capabilities):
    """The sole camera owner; publishes frame bytes only through shared memory."""
    shared = None
    camera = None
    raw_view = None
    resized_view = None
    ready_sent = False
    try:
        # Import inside the child so imports do not initialize hardware.
        from vision.camera import Camera

        shared = SharedMemory(name=shared_name)
        raw_view = np.ndarray(frame_shape, dtype=np.uint8, buffer=shared.buf, offset=0)
        resized_view = np.ndarray(
            resized_shape, dtype=np.uint8, buffer=shared.buf, offset=raw_nbytes
        )
        camera = Camera(config=SimpleNamespace(**config_values))
        limits = camera.get_frame_rate_limits()
        supported_controls = (
            getattr(camera.picam, "camera_controls", {})
            if camera.pi_mode and getattr(camera, "picam", None) is not None
            else {}
        )
        capabilities.put(
            {"camera_controls": supported_controls, "pi_mode": bool(camera.pi_mode)},
            timeout=2.0,
        )
        with lock:
            metadata[_PI_MODE] = 1.0 if camera.pi_mode else 0.0
            metadata[_MIN_FPS] = float(limits[0]) if limits else -1.0
            metadata[_MAX_FPS] = float(limits[1]) if limits else -1.0
            metadata[_INITIALIZED] = 1.0
        ready_event.set()
        ready_sent = True

        while not stop_event.is_set():
            while True:
                try:
                    request_id, operation, value = commands.get_nowait()
                except queue.Empty:
                    break
                try:
                    if operation == "set_frame_rate":
                        camera.set_frame_rate(float(value))
                        payload = camera.requested_frame_rate
                    elif operation == "set_controls":
                        if not camera.pi_mode or getattr(camera, "picam", None) is None:
                            raise RuntimeError("Runtime camera controls require Picamera2")
                        camera.picam.set_controls(value)
                        payload = True
                    else:
                        raise ValueError(f"Unsupported camera command: {operation}")
                    limits = camera.get_frame_rate_limits()
                    with lock:
                        metadata[_PI_MODE] = 1.0 if camera.pi_mode else 0.0
                        metadata[_MIN_FPS] = float(limits[0]) if limits else -1.0
                        metadata[_MAX_FPS] = float(limits[1]) if limits else -1.0
                    _queue_replace(responses, (request_id, True, payload))
                except Exception as exc:
                    logger.exception("Shared-memory camera command failed")
                    _queue_replace(
                        responses, (request_id, False, f"{type(exc).__name__}: {exc}")
                    )

            frame, resized = camera.capture_frame(with_resize=True)
            valid = bool(
                camera.last_capture_valid and frame is not None and resized is not None
                and getattr(frame, "dtype", None) == np.uint8
                and getattr(resized, "dtype", None) == np.uint8
            )
            if valid and tuple(frame.shape) != tuple(frame_shape):
                raise RuntimeError(
                    f"Camera frame shape changed: expected {frame_shape}, got {tuple(frame.shape)}"
                )
            if valid and tuple(resized.shape) != tuple(resized_shape):
                raise RuntimeError(
                    f"Resized frame shape changed: expected {resized_shape}, got {tuple(resized.shape)}"
                )

            with lock:
                if valid:
                    np.copyto(raw_view, frame)
                    np.copyto(resized_view, resized)
                metadata[_SEQ] += 1.0
                metadata[_CAPTURE_AT] = float(camera.last_capture_at or time.monotonic())
                measured = camera.measured_frame_rate
                metadata[_MEASURED_FPS] = float(measured) if measured is not None else -1.0
                metadata[_VALID] = 1.0 if valid else 0.0
                metadata[_FAILURES] = float(camera.consecutive_failures)
                metadata[_CAPTURE_MS] = float(camera.last_capture_duration_ms or 0.0)
                metadata[_PI_MODE] = 1.0 if camera.pi_mode else 0.0
            frame_event.set()
            if not valid:
                stop_event.wait(0.005)

    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        logger.exception("Multiprocessing camera worker failed")
        _queue_replace(errors, detail)
        with lock:
            metadata[_INITIALIZED] = -1.0
            metadata[_VALID] = 0.0
            metadata[_SEQ] += 1.0
            metadata[_CAPTURE_AT] = time.monotonic()
        frame_event.set()
        if not ready_sent:
            ready_event.set()
    finally:
        if camera is not None:
            try:
                camera.release()
            except Exception:
                logger.exception("Failed to release camera in capture worker")
        # NumPy views export the shared buffer. Drop them before closing the
        # SharedMemory mapping, particularly important on Windows.
        raw_view = None
        resized_view = None
        if shared is not None:
            try:
                shared.close()
            except Exception:
                logger.exception("Failed to detach shared-memory camera buffer")


class SharedMemoryCapture:
    """Parent-side reader for the camera worker's latest-frame shared buffer."""

    STARTUP_TIMEOUT_S = 20.0
    FRAME_TIMEOUT_S = 2.0

    def __init__(self, *, width, height, resize_width, resize_height, mode,
                 camera_index, camera_fallback, camera_fps, apply_calibration,
                 runtime_mode):
        self.width, self.height = int(width), int(height)
        self.resize_width, self.resize_height = int(resize_width), int(resize_height)
        if min(self.width, self.height, self.resize_width, self.resize_height) <= 0:
            raise ValueError("Shared-memory camera dimensions must all be positive")

        self.frame_shape = (self.height, self.width, 3)
        self.resized_shape = (self.resize_height, self.resize_width, 3)
        self._raw_nbytes = int(np.prod(self.frame_shape))
        resized_nbytes = int(np.prod(self.resized_shape))
        self._context = mp.get_context("spawn")
        self._lock = self._context.Lock()
        self._stop_event = self._context.Event()
        self._frame_event = self._context.Event()
        self._ready_event = self._context.Event()
        self._metadata = self._context.Array(
            "d", [0.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0, 0.0, -1.0, -1.0],
            lock=False,
        )
        self._errors = self._context.Queue(maxsize=1)
        self._commands = self._context.Queue(maxsize=2)
        self._responses = self._context.Queue(maxsize=2)
        self._capabilities = self._context.Queue(maxsize=1)
        self._command_lock = threading.Lock()
        self._command_id = 0
        self._last_sequence = 0
        self._closed = False
        self._shared = SharedMemory(create=True, size=self._raw_nbytes + resized_nbytes)

        config_values = {
            "CAM_WIDTH": self.width,
            "CAM_HEIGHT": self.height,
            "resize_width": self.resize_width,
            "resize_height": self.resize_height,
            "CAMERA_MODE": str(mode),
            "USBCAM_ADDR": int(camera_index),
            "CAMERA_FALLBACK_TO_OPENCV": bool(camera_fallback),
            "CAMERA_FPS": camera_fps,
            "APPLY_CAMERA_CALIBRATION": bool(apply_calibration),
            "MULTIPROCESS_CAMERA": False,
            "MODE": runtime_mode,
        }
        self._process = self._context.Process(
            target=_capture_process,
            name="robot-camera-capture",
            args=(
                config_values, self._shared.name, self.frame_shape, self.resized_shape,
                self._raw_nbytes, self._lock, self._stop_event, self._frame_event,
                self._ready_event, self._metadata, self._errors, self._commands,
                self._responses, self._capabilities,
            ),
            daemon=True,
        )
        try:
            self._process.start()
            if not self._ready_event.wait(self.STARTUP_TIMEOUT_S):
                raise RuntimeError(
                    f"Camera worker did not initialize within {self.STARTUP_TIMEOUT_S:.0f} seconds"
                )
            with self._lock:
                initialized = int(self._metadata[_INITIALIZED])
            if initialized != 1:
                try:
                    detail = self._errors.get_nowait()
                except queue.Empty:
                    detail = "camera worker exited during initialization"
                raise RuntimeError(f"Multiprocessing camera startup failed: {detail}")
            try:
                startup = self._capabilities.get(timeout=2.0)
                self.camera_controls = startup.get("camera_controls", {})
            except queue.Empty:
                self.camera_controls = {}
        except Exception:
            self.close()
            raise

    @property
    def pi_mode(self):
        with self._lock:
            return bool(self._metadata[_PI_MODE])

    def get_frame_rate_limits(self):
        with self._lock:
            minimum, maximum = float(self._metadata[_MIN_FPS]), float(self._metadata[_MAX_FPS])
        return (minimum, maximum) if minimum > 0 and maximum >= minimum else None

    def _request(self, operation, value):
        with self._command_lock:
            if self._closed or not self._process.is_alive():
                raise RuntimeError("Multiprocessing camera worker is not running")
            self._command_id += 1
            request_id = self._command_id
            self._commands.put((request_id, operation, value), timeout=1.0)
            deadline = time.monotonic() + 3.0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"Timed out waiting for camera command: {operation}")
                try:
                    response_id, success, payload = self._responses.get(timeout=remaining)
                except queue.Empty:
                    raise TimeoutError(f"Timed out waiting for camera command: {operation}")
                if response_id != request_id:
                    continue
                if not success:
                    raise RuntimeError(f"Camera command {operation} failed: {payload}")
                return payload

    def set_frame_rate(self, fps):
        fps = float(fps)
        if fps <= 0:
            raise ValueError("fps must be greater than zero")
        actual = self._request("set_frame_rate", fps)
        return float(actual) if actual is not None else fps

    @property
    def camera_controls(self):
        return self._camera_controls

    @camera_controls.setter
    def camera_controls(self, value):
        self._camera_controls = dict(value or {})

    def set_controls(self, controls):
        return self._request("set_controls", dict(controls))

    def capture_frame(self, with_resize=True):
        deadline = time.monotonic() + self.FRAME_TIMEOUT_S
        while True:
            with self._lock:
                sequence = int(self._metadata[_SEQ])
                initialized = int(self._metadata[_INITIALIZED]) == 1
                if sequence > self._last_sequence:
                    state = _state(self._metadata)
                    self._last_sequence = sequence
                    if state["valid"] and initialized:
                        frame = np.ndarray(
                            self.frame_shape, dtype=np.uint8,
                            buffer=self._shared.buf, offset=0,
                        ).copy()
                        resized = None
                        if with_resize:
                            resized = np.ndarray(
                                self.resized_shape, dtype=np.uint8,
                                buffer=self._shared.buf, offset=self._raw_nbytes,
                            ).copy()
                        return frame, resized, state
                    return None, None, state

                if not initialized:
                    return None, None, _state(self._metadata)
                self._frame_event.clear()
                alive = self._process.is_alive()

            if not alive:
                state = _state(self._metadata)
                state["valid"] = False
                state["initialized"] = False
                return None, None, state
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                state = _state(self._metadata)
                state["valid"] = False
                return None, None, state
            self._frame_event.wait(min(0.25, remaining))

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._stop_event.set()
        self._frame_event.set()
        process = getattr(self, "_process", None)
        if process is not None:
            try:
                if process.is_alive():
                    process.join(timeout=2.0)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=1.0)
            except Exception:
                logger.exception("Failed to stop multiprocessing camera worker")
        for channel in (
            getattr(self, "_commands", None), getattr(self, "_responses", None),
            getattr(self, "_errors", None), getattr(self, "_capabilities", None),
        ):
            if channel is not None:
                try:
                    channel.close()
                except Exception:
                    pass
        shared = getattr(self, "_shared", None)
        if shared is not None:
            try:
                shared.close()
            except Exception:
                pass
            try:
                shared.unlink()
            except FileNotFoundError:
                pass
            except Exception:
                logger.exception("Failed to unlink shared-memory camera buffer")
