"""CARLA client adapter with camera, ray-cast LiDAR and virtual odometry."""
import logging
import math
import threading
import time
import numpy as np
from .base_adapter import SensorFrame, SimulatorAdapter

logger = logging.getLogger(__name__)


class CarlaAdapter(SimulatorAdapter):
    backend = "carla"
    supports_lidar = True

    def __init__(self, config):
        super().__init__(config)
        self.carla = self.client = self.world = self.vehicle = None
        self.camera = self.lidar = None
        self._condition = threading.Condition()
        self._image = self._image_at = None
        self._sequence = self._read_sequence = 0
        self._points = np.empty((0, 3), dtype=np.float32)
        self._previous_location = None

    def connect(self):
        try:
            import carla
        except Exception as exc:
            raise RuntimeError(
                "CARLA Python API is unavailable. Install a compatible wheel using "
                "python -m pip install -r requirements-simulators.txt."
            ) from exc
        self.carla = carla
        host = str(getattr(self.config, "SIMULATOR_HOST", "127.0.0.1"))
        port = int(getattr(self.config, "SIMULATOR_PORT", 2000))
        self.client = carla.Client(host, port)
        self.client.set_timeout(float(getattr(self.config, "SIMULATOR_TIMEOUT_S", 5.0)))
        self.world = self.client.get_world()
        try:
            self._spawn_vehicle_and_sensors()
        except Exception:
            self.close()
            raise
        self.connected = True
        logger.info("Connected to CARLA at %s:%s", host, port)

    def _spawn_vehicle_and_sensors(self):
        library = self.world.get_blueprint_library()
        vehicle_filter = str(getattr(self.config, "SIMULATOR_VEHICLE_FILTER", "vehicle.*"))
        candidates = list(library.filter(vehicle_filter))
        candidates.sort(key=lambda bp: bp.id != "vehicle.tesla.model3")
        spawn_points = list(self.world.get_map().get_spawn_points())
        if not candidates:
            raise RuntimeError("CARLA has no vehicle blueprint matching " + vehicle_filter)
        if not spawn_points:
            raise RuntimeError("CARLA map has no vehicle spawn points")
        for transform in spawn_points:
            self.vehicle = self.world.try_spawn_actor(candidates[0], transform)
            if self.vehicle is not None:
                break
        if self.vehicle is None:
            raise RuntimeError("Could not spawn a CARLA vehicle at an available spawn point")

        camera_bp = library.find("sensor.camera.rgb")
        camera_bp.set_attribute("image_size_x", str(int(getattr(self.config, "CAM_WIDTH", 640))))
        camera_bp.set_attribute("image_size_y", str(int(getattr(self.config, "CAM_HEIGHT", 480))))
        camera_bp.set_attribute("fov", str(float(getattr(self.config, "SIMULATOR_CAMERA_FOV", 90.0))))
        camera_transform = self.carla.Transform(
            self.carla.Location(x=1.45, z=1.8), self.carla.Rotation(pitch=-8.0)
        )
        self.camera = self.world.spawn_actor(camera_bp, camera_transform, attach_to=self.vehicle)
        self.camera.listen(self._on_camera)

        if bool(getattr(self.config, "SIMULATOR_LIDAR_ENABLED", True)):
            lidar_bp = library.find("sensor.lidar.ray_cast")
            for key, value in {
                "range": str(float(getattr(self.config, "SIMULATOR_LIDAR_RANGE_M", 50.0))),
                "channels": str(int(getattr(self.config, "SIMULATOR_LIDAR_CHANNELS", 32))),
                "points_per_second": str(int(getattr(self.config, "SIMULATOR_LIDAR_POINTS_PER_SECOND", 56000))),
                "rotation_frequency": str(float(getattr(self.config, "SIMULATOR_LIDAR_ROTATION_FREQUENCY", 10.0))),
            }.items():
                lidar_bp.set_attribute(key, value)
            transform = self.carla.Transform(self.carla.Location(x=0.0, z=2.0))
            self.lidar = self.world.spawn_actor(lidar_bp, transform, attach_to=self.vehicle)
            self.lidar.listen(self._on_lidar)

    def _on_camera(self, image):
        try:
            raw = np.frombuffer(image.raw_data, dtype=np.uint8)
            frame = raw.reshape((int(image.height), int(image.width), 4))[:, :, :3].copy()
            with self._condition:
                self._image = frame
                self._image_at = time.monotonic()
                self._sequence += 1
                self._condition.notify_all()
        except Exception:
            logger.exception("Could not decode CARLA camera frame")

    def _on_lidar(self, measurement):
        try:
            raw = np.frombuffer(measurement.raw_data, dtype=np.float32)
            points = raw.reshape((-1, 4))[:, :3].copy() if raw.size else np.empty((0, 3), dtype=np.float32)
            with self._condition:
                self._points = points
                self._condition.notify_all()
        except Exception:
            logger.exception("Could not decode CARLA LiDAR packet")

    @staticmethod
    def _speed_kmh(actor):
        velocity = actor.get_velocity()
        return math.sqrt(velocity.x ** 2 + velocity.y ** 2 + velocity.z ** 2) * 3.6

    @staticmethod
    def _location_tuple(actor):
        p = actor.get_transform().location
        return float(p.x), float(p.y), float(p.z)

    def read(self, timeout=0.25):
        deadline = time.monotonic() + max(0.0, float(timeout))
        with self._condition:
            while self._sequence <= self._read_sequence and self.connected:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(remaining)
            if self._image is None or self._image_at is None or self.vehicle is None:
                return None
            frame, captured_at, sequence = self._image.copy(), self._image_at, self._sequence
            self._read_sequence = sequence
            points = self._points.copy()
        location = self._location_tuple(self.vehicle)
        transform = self.vehicle.get_transform()
        delta_cm = None
        if self._previous_location is not None:
            delta_cm = math.dist(location, self._previous_location) * 100.0
        self._previous_location = location
        ranges = {}
        if len(points):
            distances = np.linalg.norm(points[:, :2], axis=1)
            finite = np.isfinite(distances)
            if finite.any():
                ranges["nearest"] = float(distances[finite].min() * 100.0)
                front = finite & (points[:, 0] > 0) & (np.abs(points[:, 1]) < 1.5)
                left, right = finite & (points[:, 1] < -0.8), finite & (points[:, 1] > 0.8)
                ranges["front"] = float(distances[front].min() * 100.0) if front.any() else None
                ranges["left"] = float(distances[left].min() * 100.0) if left.any() else None
                ranges["right"] = float(distances[right].min() * 100.0) if right.any() else None
        return SensorFrame(
            image=frame, captured_at=captured_at, sequence=sequence,
            speed_kmh=self._speed_kmh(self.vehicle), ranges_cm=ranges,
            lidar_points=points, distance_delta_cm=delta_cm, location=location,
            yaw_degrees=float(transform.rotation.yaw),
        )

    def apply_control(self, command):
        if self.vehicle is None:
            return False
        self.vehicle.apply_control(self.carla.VehicleControl(
            steer=max(-1.0, min(1.0, float(command.steering))),
            throttle=max(0.0, min(1.0, float(command.throttle))),
            brake=max(0.0, min(1.0, float(command.brake))),
            hand_brake=False, reverse=False, manual_gear_shift=False,
        ))
        return True

    def close(self):
        for sensor in (self.lidar, self.camera):
            if sensor is not None:
                try:
                    sensor.stop()
                except Exception:
                    pass
                try:
                    sensor.destroy()
                except Exception:
                    logger.debug("Failed to destroy a CARLA sensor", exc_info=True)
        self.lidar = self.camera = None
        if self.vehicle is not None:
            try:
                if self.carla is not None:
                    self.vehicle.apply_control(self.carla.VehicleControl(throttle=0.0, brake=1.0))
            except Exception:
                pass
            try:
                self.vehicle.destroy()
            except Exception:
                logger.debug("Failed to destroy CARLA vehicle", exc_info=True)
        self.vehicle = None
        self.connected = False
        with self._condition:
            self._condition.notify_all()
