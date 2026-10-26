"""AVIS Engine adapter; its distance sensors are not presented as LiDAR."""
import logging
import math
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
        self._sequence = 0
        self._previous_at = None

    def connect(self):
        try:
            import avisengine
        except Exception as exc:
            raise RuntimeError(
                "AVIS Engine Python API is unavailable. Install it using "
                "python -m pip install -r requirements-simulators.txt."
            ) from exc
        self.car = avisengine.Car()
        host = str(getattr(self.config, "SIMULATOR_HOST", "127.0.0.1"))
        port = int(getattr(self.config, "SIMULATOR_PORT", 25001))
        result = self.car.connect(host, port)
        if result is False:
            raise RuntimeError(f"AVIS Engine connection to {host}:{port} failed")
        # getData() is a synchronous request/response call in the current AVIS
        # TCP API. Bound its blocking time so a dead server cannot leave the
        # last throttle command active for the API's default five seconds.
        sock = getattr(self.car, "sock", None)
        if sock is not None and callable(getattr(sock, "settimeout", None)):
            sock.settimeout(min(1.0, max(0.1, float(getattr(self.config, "SIMULATOR_TIMEOUT_S", 5.0)))))
        self.connected = True
        self.set_sensor_angle(int(getattr(self.config, "SIMULATOR_AVIS_SENSOR_ANGLE", 0)))
        logger.info("Connected to AVIS Engine at %s:%s", host, port)

    def set_sensor_angle(self, angle):
        if self.car is None:
            return False
        method = getattr(self.car, "setSensorAngle", None)
        if callable(method):
            method(max(-90, min(90, int(angle))))
            return True
        return False

    @staticmethod
    def _range(value):
        try:
            distance = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return distance if math.isfinite(distance) and distance >= 0 else None

    def read(self, timeout=0.25):
        if not self.connected or self.car is None:
            return None
        try:
            previous_frame = self.car.getImage()
        except Exception:
            previous_frame = None
        try:
            # getData() updates the bundled API's image, sensors and speed fields.
            # None is its normal return value on a successful response.
            self.car.getData()
        except Exception:
            logger.debug("AVIS getData failed for one cycle", exc_info=True)
            return None
        try:
            frame = self.car.getImage()
        except Exception:
            frame = None
            logger.debug("AVIS getImage failed for one cycle", exc_info=True)
        # Do not re-stamp a cached frame as fresh when a response had no image.
        if frame is not None and frame is previous_frame:
            return None
        if frame is None:
            return None
        frame = np.asarray(frame)
        if frame.ndim != 3 or frame.shape[2] < 3 or not frame.size:
            logger.warning("AVIS returned an invalid image shape: %s", getattr(frame, "shape", None))
            return None
        frame = frame[:, :, :3].copy()
        now = time.monotonic()
        try:
            speed = float(self.car.getSpeed())
            if not math.isfinite(speed):
                speed = 0.0
        except Exception:
            speed = 0.0
        try:
            values = list(self.car.getSensors() or [])
        except Exception:
            values = []
            logger.debug("AVIS distance sensor read failed", exc_info=True)
        # AVIS API order: left, middle/front, right; distances are in centimeters.
        ranges = {
            "left": self._range(values[0]) if len(values) > 0 else None,
            "front": self._range(values[1]) if len(values) > 1 else None,
            "right": self._range(values[2]) if len(values) > 2 else None,
        }
        dt = max(0.0, now - self._previous_at) if self._previous_at is not None else 0.0
        distance_delta = max(0.0, speed) * 100000.0 / 3600.0 * dt
        self._previous_at = now
        self._sequence += 1
        return SensorFrame(
            image=frame, captured_at=now, sequence=self._sequence,
            speed_kmh=max(0.0, speed), ranges_cm=ranges,
            lidar_points=None, distance_delta_cm=distance_delta,
        )

    def apply_control(self, command):
        if self.car is None or not self.connected:
            return False
        steering = max(-100, min(100, int(round(float(command.steering) * 100.0))))
        speed = 0 if float(command.brake) >= 0.5 else max(
            0, min(100, int(round(float(command.throttle) * 100.0)))
        )
        self.car.setSteering(steering)
        self.car.setSpeed(speed)
        return True

    def close(self):
        car, self.car = self.car, None
        if car is not None:
            try:
                car.stop()
            except Exception:
                try:
                    car.setSpeed(0)
                except Exception:
                    pass
            for name in ("disconnect", "close"):
                method = getattr(car, name, None)
                if callable(method):
                    try:
                        method()
                    except Exception:
                        logger.debug("AVIS %s failed during shutdown", name, exc_info=True)
        self.connected = False
