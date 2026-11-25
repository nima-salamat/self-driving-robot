"""AVIS Engine adapter with automatic reconnect and fresh-frame diagnostics."""
import logging
import math
import threading
import time

import numpy as np

from .base_adapter import SensorFrame, SimulatorAdapter

logger = logging.getLogger(__name__)

# Share status-log cooldowns across adapter instances. A camera can recover for
# one frame and fail again, or the application can recreate an adapter; neither
# should turn a transient camera outage into a console line on every cycle.
_GLOBAL_STATUS_LOG_LOCK = threading.Lock()
_GLOBAL_STATUS_LOG_AT = {}


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
        self._missing_image_log_active = False
        self._missing_image_started_at = None
        self._missing_image_error_logged = False
        self._status_log_at = {}
        self._ready_at = 0.0
        self._sensor_angle_applied = False

    def _request_timeout(self):
        # The legacy AVIS TCP client may need several seconds to return a full
        # camera frame. Respect the configured timeout instead of truncating it
        # to one second.
        try:
            configured = float(getattr(self.config, "SIMULATOR_TIMEOUT_S", 5.0))
        except (TypeError, ValueError, OverflowError):
            configured = 5.0
        if not math.isfinite(configured):
            configured = 5.0
        return min(60.0, max(0.1, configured))

    def _log_info_rate_limited(self, key, message, interval_s=30.0):
        now = time.monotonic()
        with _GLOBAL_STATUS_LOG_LOCK:
            previous = _GLOBAL_STATUS_LOG_AT.get(key)
            if previous is not None and now - previous < interval_s:
                return False
            _GLOBAL_STATUS_LOG_AT[key] = now
            self._status_log_at[key] = now
        logger.info("%s", message)
        return True

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
        # The legacy AVIS client example allows the simulator three seconds
        # to finish initializing after TCP connect. Defer the first protocol
        # command without blocking the runtime thread.
        try:
            startup_delay = float(getattr(self.config, "SIMULATOR_AVIS_STARTUP_DELAY_S", 3.0))
        except (TypeError, ValueError, OverflowError):
            startup_delay = 3.0
        if not math.isfinite(startup_delay):
            startup_delay = 3.0
        self._ready_at = time.monotonic() + min(15.0, max(0.0, startup_delay))
        self._sensor_angle_applied = False
        logger.info(
            "Connected to legacy AVIS TCP Engine at %s:%s (ready in %.1fs)",
            host, port, max(0.0, self._ready_at - time.monotonic())
        )
        return True

    @staticmethod
    def _close_transport(car):
        if car is None:
            return
        # Prefer the protocol-level disconnect before touching the raw socket.
        # Legacy AVIS servers may keep the previous client session allocated
        # until they receive the literal "stop" token.
        for name in ("stop", "disconnect", "close"):
            method = getattr(car, name, None)
            if callable(method):
                try:
                    if name == "disconnect":
                        method(send_stop=True)
                    else:
                        method()
                    return
                except TypeError:
                    try:
                        method()
                        return
                    except Exception:
                        logger.debug("AVIS %s failed while closing a lost connection", name, exc_info=True)
                except Exception:
                    logger.debug("AVIS %s failed while closing a lost connection", name, exc_info=True)
        sock = getattr(car, "sock", None)
        if sock is not None:
            try:
                sock.shutdown(2)
            except Exception:
                pass
            try:
                sock.close()
            except Exception:
                pass

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
        self._log_info_rate_limited(
            "reconnect-scheduled",
            "AVIS connection lost; scheduling a safe reconnect in %.2fs: %s" % (delay, self._last_error),
        )

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
            self._log_info_rate_limited(
                "reconnect-failed",
                "AVIS connection attempt failed; retrying in %.2fs: %s" % (delay, self._last_error),
            )
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
        if time.monotonic() < self._ready_at:
            return None
        if not self._sensor_angle_applied:
            if not self.set_sensor_angle(int(getattr(self.config, "SIMULATOR_AVIS_SENSOR_ANGLE", 30))):
                return None
            self._sensor_angle_applied = True

        old_generation = getattr(car, "image_sequence", None)
        try:
            # The bundled AVIS client updates image, ranges and speed here.
            car.getData()
        except Exception as exc:
            self._consecutive_failures += 1
            self._last_error = f"{type(exc).__name__}: {exc}"[:300]
            if self._consecutive_failures == 1:
                self._log_info_rate_limited(
                    "data-request-failed",
                    "AVIS camera request failed; checking the TCP session: " + self._last_error,
                )
            if self._consecutive_failures >= 2:
                logger.error(
                    "AVIS camera request failed twice consecutively; reconnecting: %s",
                    self._last_error,
                )
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
            self._last_error = (
                "AVIS response contained no fresh image; "
                + "bytes=" + str(response_info.get("response_bytes", 0))
                + ", transport=" + str(response_info.get("image_transport_encoding", "unknown"))
                + ", magic=" + str(response_info.get("image_payload_magic", "unknown"))
                + ", prefix_hex=" + str(response_info.get("image_payload_prefix_hex", ""))
                + ", error=" + str(response_info.get("decode_error", "unknown"))[:180]
            )
            # A missing image is not automatically a dead TCP connection. Keep
            # the session alive and brake while waiting for a valid camera frame.
            # Report the transition once at INFO; if decoding remains broken
            # for several seconds, emit one actionable ERROR (not one warning
            # per packet). Full, privacy-safe diagnostics remain in the Stream.
            now = time.monotonic()
            if not self._missing_image_log_active:
                self._missing_image_started_at = now
                self._missing_image_error_logged = False
                self._log_info_rate_limited(
                    "camera-no-decodable-frame",
                    "AVIS camera stream has not produced a decodable frame; retaining TCP session and holding the vehicle stopped.",
                    interval_s=60.0,
                )
            self._missing_image_log_active = True
            outage_age = (
                max(0.0, now - self._missing_image_started_at)
                if self._missing_image_started_at is not None else 0.0
            )
            if self._missing_images >= 30 and outage_age >= 5.0 and not self._missing_image_error_logged:
                logger.error(
                    "AVIS has returned %d consecutive responses without a valid image over %.1fs; "
                    "the vehicle remains braked. Last response: %s",
                    self._missing_images, outage_age, self._last_error,
                )
                self._missing_image_error_logged = True
            return None

        self._missing_images = 0
        self._missing_image_log_active = False
        self._missing_image_started_at = None
        self._missing_image_error_logged = False
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
        speed_available = False
        try:
            speed = float(car.getSpeed())
            speed_available = math.isfinite(speed) and speed >= 0.0
            if not speed_available:
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
        response_info = dict(getattr(car, "last_response_info", {}) or {})
        sensor_status = {
            "ranges_available": bool(response_info.get("sensor_tag"))
            and len(values) >= 3
            and all(value is not None for value in ranges.values()),
            "front_range_available": ranges["front"] is not None,
            "range_sensor_count": len(values),
            "sensor_tag_present": bool(response_info.get("sensor_tag")),
            "speed_available": bool(speed_available),
        }
        return SensorFrame(
            image=image,
            captured_at=now,
            sequence=self._sequence,
            speed_kmh=max(0.0, speed),
            ranges_cm=ranges,
            lidar_points=None,
            distance_delta_cm=distance_delta,
            sensor_status=sensor_status,
        )

    def apply_control(self, command):
        with self._io_lock:
            if self.car is None or not self.connected:
                return False
            # A reconnect may happen immediately after AVIS stop() closes the
            # previous socket. Do not write actuator commands during the
            # server's startup window; sensor requests use the same delay.
            if time.monotonic() < self._ready_at:
                return False
            # SimulatorController expresses steering as normalized [-1, 1].
            # Legacy AVIS expects a signed percentage: -100 = full left,
            # 0 = straight, +100 = full right.
            normalized_steering = float(command.steering)
            if not math.isfinite(normalized_steering):
                normalized_steering = 0.0
            normalized_steering = max(-1.0, min(1.0, normalized_steering))
            steering = int(round(normalized_steering * 100.0))
            speed = 0 if float(command.brake) >= 0.5 else max(
                0, min(100, int(round(float(command.throttle) * 100.0)))
            )
            try:
                # Prefer one packet containing both values. Sending steering
                # and speed separately can briefly resend the previous throttle
                # between the two legacy calls during an emergency stop.
                drive_setter = getattr(self.car, "setDriveCommand", None)
                if callable(drive_setter):
                    drive_setter(steering, speed)
                else:
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
                "missing_image_duration_s": (
                    None if self._missing_image_started_at is None
                    else round(max(0.0, now - self._missing_image_started_at), 2)
                ),
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
                    logger.error("%s", self._last_error)
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
