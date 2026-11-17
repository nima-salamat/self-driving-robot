"""AVIS Engine adapter with automatic reconnect and fresh-frame diagnostics."""
import logging
import math
import threading
import time

import numpy as np

from .base_adapter import SensorFrame, SimulatorAdapter

logger = logging.getLogger(__name__)


class AvisAdapter(SimulatorAdapter):
    backend = "avis"
    supports_lidar = False

    def __init__(self, config):
        super().__init__(config)
        self.car = None
        self._io_lock = threading.RLock()
        self._sequence = 0
        self._previous_at = None
        self._previous_frame_object = None
        self._consecutive_failures = 0
        self._missing_images = 0
        self._reconnect_attempts = 0
        self._last_error = ""
        self._last_connected_at = None
        self._last_frame_at = None
        self._next_reconnect_at = 0.0
        self._reconnect_delay_s = 0.5
        self._last_image_stats = {}
        self._last_response_signature = None
        self._missing_image_log_active = False
        self._last_missing_image_log_at = 0.0

    def _request_timeout(self):
        return min(1.0, max(0.1, float(getattr(self.config, "SIMULATOR_TIMEOUT_S", 1.0))))

    def connect(self):
        with self._io_lock:
            return self._connect_locked()

    def _connect_locked(self):
        import avisengine

        car = avisengine.Car()
        host = str(getattr(self.config, "SIMULATOR_HOST", "127.0.0.1"))
        port = int(getattr(self.config, "SIMULATOR_PORT", 25001))
        timeout = self._request_timeout()
        car.timeout = timeout
        try:
            result = car.connect(host, port)
            if result is False:
                raise RuntimeError(f"AVIS Engine connection to {host}:{port} failed")
            sock = getattr(car, "sock", None)
            if sock is not None and callable(getattr(sock, "settimeout", None)):
                sock.settimeout(timeout)
        except Exception:
            self._close_transport(car)
            raise

        self.car = car
        self.connected = True
        self._consecutive_failures = 0
        self._missing_images = 0
        self._previous_frame_object = None
        self._last_error = ""
        self._last_connected_at = time.monotonic()
        self._next_reconnect_at = 0.0
        self._reconnect_delay_s = 0.5
        self.set_sensor_angle(int(getattr(self.config, "SIMULATOR_AVIS_SENSOR_ANGLE", 30)))
        logger.info("Connected to AVIS Engine at %s:%s", host, port)
        return True

    @staticmethod
    def _close_transport(car):
        if car is None:
            return
        sock = getattr(car, "sock", None)
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
        for name in ("disconnect", "close"):
            method = getattr(car, name, None)
            if callable(method):
                try:
                    method()
                except Exception:
                    logger.debug("AVIS %s failed while closing a lost connection", name, exc_info=True)

    def _schedule_reconnect_locked(self, reason, *, immediate=False):
        car, self.car = self.car, None
        self.connected = False
        self._last_error = str(reason)[:300]
        self._reconnect_attempts += 1
        delay = 0.0 if immediate else self._reconnect_delay_s
        self._next_reconnect_at = time.monotonic() + delay
        if not immediate:
            self._reconnect_delay_s = min(5.0, self._reconnect_delay_s * 2.0)
        self._close_transport(car)
        logger.warning("AVIS reconnect scheduled in %.2fs: %s", delay, self._last_error)

    def request_reconnect(self):
        """Force a new TCP socket after the AVIS simulator was reset."""
        with self._io_lock:
            self._schedule_reconnect_locked("Manual reconnect requested from Stream.", immediate=True)
            return {
                "connected": False,
                "reconnect_attempts": int(self._reconnect_attempts),
                "message": "Reconnect scheduled. Autonomous run remains disarmed.",
            }

    def _ensure_connected_locked(self):
        if self.connected and self.car is not None:
            return True
        if time.monotonic() < self._next_reconnect_at:
            return False
        try:
            return bool(self._connect_locked())
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"[:300]
            self._reconnect_attempts += 1
            delay = self._reconnect_delay_s
            self._next_reconnect_at = time.monotonic() + delay
            self._reconnect_delay_s = min(5.0, self._reconnect_delay_s * 2.0)
            self.connected = False
            self.car = None
            logger.warning("AVIS reconnect failed; retrying in %.2fs: %s", delay, self._last_error)
            return False

    def set_sensor_angle(self, angle):
        with self._io_lock:
            if self.car is None or not self.connected:
                return False
            method = getattr(self.car, "setSensorAngle", None)
            if not callable(method):
                return False
            try:
                method(max(0, min(90, int(angle))))
                return True
            except Exception as exc:
                self._schedule_reconnect_locked(f"AVIS sensor-angle command failed: {exc}")
                return False

    @staticmethod
    def _range(value):
        try:
            distance = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return distance if math.isfinite(distance) and distance >= 0 else None

    def read(self, timeout=0.25):
        # AVIS has one synchronous request/response socket. Serialize it with
        # sensor-angle updates and vehicle commands.
        with self._io_lock:
            if not self._ensure_connected_locked():
                return None
            return self._read_locked(timeout)

    def _read_locked(self, timeout=0.25):
        car = self.car
        if not self.connected or car is None:
            return None

        old_generation = getattr(car, "image_sequence", None)
        try:
            # The bundled AVIS client updates image, ranges and speed here.
            car.getData()
        except Exception as exc:
            self._consecutive_failures += 1
            self._last_error = f"{type(exc).__name__}: {exc}"[:300]
            logger.warning("AVIS data request failed (%s consecutive): %s", self._consecutive_failures, self._last_error)
            if self._consecutive_failures >= 2:
                self._schedule_reconnect_locked(self._last_error)
            return None

        self._consecutive_failures = 0
        try:
            frame = car.getImage()
        except Exception as exc:
            frame = None
            self._last_error = f"getImage: {type(exc).__name__}: {exc}"[:300]

        new_generation = getattr(car, "image_sequence", None)
        if old_generation is not None and new_generation is not None:
            is_fresh = int(new_generation) > int(old_generation)
        else:
            # Compatibility for third-party AVIS clients without image_sequence.
            is_fresh = frame is not None and frame is not self._previous_frame_object
        self._previous_frame_object = frame

        if frame is None or not is_fresh:
            self._missing_images += 1
            response_info = dict(getattr(car, "last_response_info", {}) or {})
            # Sensor values in response_prefix change on every sample; do
            # not include them in the log-deduplication key or warnings spam
            # once per frame when the image tag is consistently absent.
            signature = (
                bool(response_info.get("image_tag")),
                bool(response_info.get("image_decoded")),
                response_info.get("decode_error"),
            )
            self._last_error = (
                "AVIS response contained no fresh image; "
                + str(response_info)[:220]
            )
            # A missing image tag is not proof that the TCP connection is dead.
            # Keep the socket alive and request the next sample instead of
            # entering an endless close/reconnect loop.
            # Report the transition into the missing-frame state once.
            # Sensor metadata can vary on every sample; logging each variant
            # performs synchronous console I/O in the camera/control loop.
            now = time.monotonic()
            if now - self._last_missing_image_log_at >= 5.0:
                logger.warning(
                    "AVIS camera frame unavailable; retaining TCP connection. Latest response: %s",
                    self._last_error,
                )
                self._last_missing_image_log_at = now
            self._last_response_signature = signature
            self._missing_image_log_active = True
            return None

        self._missing_images = 0
        self._missing_image_log_active = False
        self._last_response_signature = None
        self._last_error = ""

        image = np.asarray(frame)
        if image.ndim != 3 or image.shape[2] < 3 or not image.size:
            self._missing_images += 1
            if self._missing_images >= 4:
                self._schedule_reconnect_locked("AVIS returned an invalid camera image.")
            return None

        self._missing_images = 0
        image = image[:, :, :3].copy()
        now = time.monotonic()
        try:
            speed = float(car.getSpeed())
            if not math.isfinite(speed):
                speed = 0.0
        except Exception:
            speed = 0.0
        try:
            values = list(car.getSensors() or [])
        except Exception:
            values = []
            logger.debug("AVIS range-sensor data unavailable", exc_info=True)

        ranges = {
            "left": self._range(values[0]) if len(values) > 0 else None,
            "front": self._range(values[1]) if len(values) > 1 else None,
            "right": self._range(values[2]) if len(values) > 2 else None,
        }
        dt = max(0.0, now - self._previous_at) if self._previous_at is not None else 0.0
        distance_delta = max(0.0, speed) * 100000.0 / 3600.0 * dt
        self._previous_at = now
        self._last_frame_at = now
        self._sequence += 1
        sample = image[::16, ::16]
        self._last_image_stats = {
            "width": int(image.shape[1]),
            "height": int(image.shape[0]),
            "mean_intensity": round(float(np.mean(sample)), 2) if sample.size else 0.0,
            "max_intensity": int(np.max(sample)) if sample.size else 0,
            "looks_black": bool(not sample.size or float(np.mean(sample)) < 1.0 or int(np.max(sample)) < 4),
        }
        return SensorFrame(
            image=image,
            captured_at=now,
            sequence=self._sequence,
            speed_kmh=max(0.0, speed),
            ranges_cm=ranges,
            lidar_points=None,
            distance_delta_cm=distance_delta,
        )

    def apply_control(self, command):
        with self._io_lock:
            if self.car is None or not self.connected:
                return False
            steering = max(-100, min(100, int(round(float(command.steering) * 100.0))))
            speed = 0 if float(command.brake) >= 0.5 else max(
                0, min(100, int(round(float(command.throttle) * 100.0)))
            )
            try:
                self.car.setSteering(steering)
                self.car.setSpeed(speed)
                return True
            except Exception as exc:
                self._schedule_reconnect_locked(
                    f"AVIS actuator write failed: {type(exc).__name__}: {exc}"
                )
                return False

    def camera_diagnostics(self):
        with self._io_lock:
            now = time.monotonic()
            age = None if self._last_frame_at is None else max(0.0, now - self._last_frame_at)
            connected_for = None if self._last_connected_at is None else max(0.0, now - self._last_connected_at)
            return {
                **dict(self._last_image_stats),
                "connected": bool(self.connected),
                "frame_count": int(self._sequence),
                "last_frame_age_ms": None if age is None else round(age * 1000.0, 1),
                "connected_for_s": None if connected_for is None else round(connected_for, 2),
                "reconnect_attempts": int(self._reconnect_attempts),
                "consecutive_failures": int(self._consecutive_failures),
                "missing_images": int(self._missing_images),
                "last_error": self._last_error or None,
                "response": dict(getattr(self.car, "last_response_info", {}) or {}) if self.car is not None else {},
            }

    def stop_vehicle(self):
        """Issue AVIS Engine's explicit stop command, then let the runtime reconnect.

        The bundled Car.stop() sends zero speed/steering plus the protocol stop
        token and closes the socket. This is stronger than repeatedly setting
        the throttle percentage to zero.
        """
        with self._io_lock:
            car, self.car = self.car, None
            self.connected = False
            if car is None:
                return False
            stopper = getattr(car, "stop", None)
            if callable(stopper):
                try:
                    stopper()
                    return True
                except Exception as exc:
                    self._last_error = f"AVIS stop command failed: {type(exc).__name__}: {exc}"[:300]
                    logger.warning("%s", self._last_error)
            self._close_transport(car)
            return False

    def close(self):
        with self._io_lock:
            car, self.car = self.car, None
            self.connected = False
            if car is not None:
                for method_name, args in (("setSpeed", (0,)), ("setSteering", (0,))):
                    method = getattr(car, method_name, None)
                    if callable(method):
                        try:
                            method(*args)
                        except Exception:
                            pass
                self._close_transport(car)
