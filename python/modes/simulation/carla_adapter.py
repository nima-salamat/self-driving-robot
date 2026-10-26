"""CARLA client adapter with camera, ray-cast LiDAR and virtual odometry."""
import logging
import math
import threading
import time
import numpy as np
import cv2
from .base_adapter import SensorFrame, SimulatorAdapter

logger = logging.getLogger(__name__)


class CarlaAdapter(SimulatorAdapter):
    backend = "carla"
    supports_lidar = True

    def __init__(self, config):
        super().__init__(config)
        self.carla = self.client = self.world = self.vehicle = None
        self.camera = self.lidar = self.editor_camera = None
        self._editor_image = self._editor_image_at = None
        self._editor_transform = None
        self._camera_mount_preview = None
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
        self._camera_mount_preview = self._mount_values_from_config()
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
        camera_transform = self._vehicle_camera_transform()
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


    _CAMERA_DEFAULTS = {
        "SIMULATOR_CAMERA_X": 1.45,
        "SIMULATOR_CAMERA_Y": 0.0,
        "SIMULATOR_CAMERA_Z": 1.8,
        "SIMULATOR_CAMERA_PITCH": -8.0,
        "SIMULATOR_CAMERA_YAW": 0.0,
        "SIMULATOR_CAMERA_ROLL": 0.0,
    }

    def _mount_values_from_config(self):
        return {
            key: float(getattr(self.config, key, default))
            for key, default in self._CAMERA_DEFAULTS.items()
        }

    def _vehicle_camera_transform(self, values=None):
        values = values or self._camera_mount_preview or self._mount_values_from_config()
        return self.carla.Transform(
            self.carla.Location(
                x=float(values["SIMULATOR_CAMERA_X"]),
                y=float(values["SIMULATOR_CAMERA_Y"]),
                z=float(values["SIMULATOR_CAMERA_Z"]),
            ),
            self.carla.Rotation(
                pitch=float(values["SIMULATOR_CAMERA_PITCH"]),
                yaw=float(values["SIMULATOR_CAMERA_YAW"]),
                roll=float(values["SIMULATOR_CAMERA_ROLL"]),
            ),
        )

    def _mounted_camera_world_transform(self, values=None):
        if self.vehicle is None:
            raise RuntimeError("CARLA vehicle is not connected")
        vehicle_transform = self.vehicle.get_transform()
        values = values or self._camera_mount_preview or self._mount_values_from_config()
        location = self.carla.Location(
            x=float(values["SIMULATOR_CAMERA_X"]),
            y=float(values["SIMULATOR_CAMERA_Y"]),
            z=float(values["SIMULATOR_CAMERA_Z"]),
        )
        vehicle_transform.transform(location)
        vehicle_rotation = vehicle_transform.rotation
        return self.carla.Transform(
            location,
            self.carla.Rotation(
                pitch=float(vehicle_rotation.pitch) + float(values["SIMULATOR_CAMERA_PITCH"]),
                yaw=float(vehicle_rotation.yaw) + float(values["SIMULATOR_CAMERA_YAW"]),
                roll=float(vehicle_rotation.roll) + float(values["SIMULATOR_CAMERA_ROLL"]),
            ),
        )

    def preview_camera_mount(self, patch):
        """Apply a vehicle-relative camera transform immediately, without saving it."""
        values = dict(self._camera_mount_preview or self._mount_values_from_config())
        for key, value in patch.items():
            if key not in self._CAMERA_DEFAULTS:
                raise ValueError("unsupported CARLA camera mount setting: " + str(key))
            number = float(value)
            if not math.isfinite(number):
                raise ValueError(key + " must be finite")
            values[key] = number
        # The shared settings validator enforces the same bounds for saved and preview values.
        from .settings import _validate_settings
        values = _validate_settings(values)
        self._camera_mount_preview = values
        if self.camera is not None and self.vehicle is not None:
            self.camera.set_transform(self._mounted_camera_world_transform(values))
        return dict(values)

    def _on_editor_camera(self, image):
        try:
            raw = np.frombuffer(image.raw_data, dtype=np.uint8)
            frame = raw.reshape((int(image.height), int(image.width), 4))[:, :, :3].copy()
            with self._condition:
                self._editor_image = frame
                self._editor_image_at = time.monotonic()
                self._condition.notify_all()
        except Exception:
            logger.exception("Could not decode CARLA camera-editor frame")

    def start_camera_editor(self):
        """Create an independent world-space fly camera for the camera-placement studio."""
        if not self.connected or self.vehicle is None or self.world is None:
            raise RuntimeError("Connect CARLA and spawn the vehicle before opening camera placement")
        if self.editor_camera is not None:
            return self.camera_editor_state()
        library = self.world.get_blueprint_library()
        blueprint = library.find("sensor.camera.rgb")
        blueprint.set_attribute("image_size_x", str(int(getattr(self.config, "CAM_WIDTH", 640))))
        blueprint.set_attribute("image_size_y", str(int(getattr(self.config, "CAM_HEIGHT", 480))))
        blueprint.set_attribute("fov", str(float(getattr(self.config, "SIMULATOR_CAMERA_FOV", 90.0))))
        transform = self._mounted_camera_world_transform()
        self.editor_camera = self.world.spawn_actor(blueprint, transform)
        self._editor_transform = transform
        self._editor_image = self._editor_image_at = None
        try:
            self.editor_camera.listen(self._on_editor_camera)
        except Exception:
            try:
                self.editor_camera.destroy()
            finally:
                self.editor_camera = None
                self._editor_transform = None
            raise
        logger.info("CARLA camera placement studio opened")
        return self.camera_editor_state()

    def camera_editor_move(self, forward=0.0, right=0.0, up=0.0, yaw=0.0, pitch=0.0):
        """Move the independent preview camera in its local view plane."""
        if self.editor_camera is None or self._editor_transform is None:
            raise RuntimeError("Open the CARLA camera placement studio first")
        current = self._editor_transform
        front = current.get_forward_vector()
        side = current.get_right_vector()
        location = self.carla.Location(
            x=float(current.location.x) + front.x * forward + side.x * right,
            y=float(current.location.y) + front.y * forward + side.y * right,
            z=float(current.location.z) + front.z * forward + side.z * right + up,
        )
        rotation = self.carla.Rotation(
            pitch=max(-89.0, min(89.0, float(current.rotation.pitch) + pitch)),
            yaw=float(current.rotation.yaw) + yaw,
            roll=float(current.rotation.roll),
        )
        self._editor_transform = self.carla.Transform(location, rotation)
        self.editor_camera.set_transform(self._editor_transform)
        return self.camera_editor_state()

    def snap_camera_editor_to_mount(self):
        if self.editor_camera is None:
            raise RuntimeError("Open the CARLA camera placement studio first")
        self._editor_transform = self._mounted_camera_world_transform()
        self.editor_camera.set_transform(self._editor_transform)
        return self.camera_editor_state()

    def level_camera_editor_view(self):
        if self.editor_camera is None or self._editor_transform is None:
            raise RuntimeError("Open the CARLA camera placement studio first")
        current = self._editor_transform
        self._editor_transform = self.carla.Transform(
            self.carla.Location(x=current.location.x, y=current.location.y, z=current.location.z),
            self.carla.Rotation(pitch=0.0, yaw=current.rotation.yaw, roll=0.0),
        )
        self.editor_camera.set_transform(self._editor_transform)
        return self.camera_editor_state()

    def use_camera_editor_view_as_mount(self):
        """Convert the free camera's world pose into the vehicle's local mount pose."""
        if self.editor_camera is None or self._editor_transform is None or self.vehicle is None:
            raise RuntimeError("Open the CARLA camera placement studio first")
        vehicle_transform = self.vehicle.get_transform()
        matrix = np.asarray(vehicle_transform.get_inverse_matrix(), dtype=np.float64).reshape(4, 4)
        world_location = self._editor_transform.location
        local = matrix @ np.asarray(
            [world_location.x, world_location.y, world_location.z, 1.0],
            dtype=np.float64,
        )
        vehicle_rotation = vehicle_transform.rotation
        view_rotation = self._editor_transform.rotation

        def wrap(angle):
            return (float(angle) + 180.0) % 360.0 - 180.0

        patch = {
            "SIMULATOR_CAMERA_X": float(local[0]),
            "SIMULATOR_CAMERA_Y": float(local[1]),
            "SIMULATOR_CAMERA_Z": float(local[2]),
            "SIMULATOR_CAMERA_PITCH": wrap(view_rotation.pitch - vehicle_rotation.pitch),
            "SIMULATOR_CAMERA_YAW": wrap(view_rotation.yaw - vehicle_rotation.yaw),
            "SIMULATOR_CAMERA_ROLL": wrap(view_rotation.roll - vehicle_rotation.roll),
        }
        from .settings import _validate_settings
        patch = _validate_settings(patch)
        self.preview_camera_mount(patch)
        return self.camera_editor_state()

    def restore_camera_mount(self):
        values = self._mount_values_from_config()
        self.preview_camera_mount(values)
        if self.editor_camera is not None:
            self.snap_camera_editor_to_mount()
        return self.camera_editor_state()

    def camera_editor_state(self):
        with self._condition:
            image_at = self._editor_image_at
        age_ms = None if image_at is None else max(0.0, (time.monotonic() - image_at) * 1000.0)
        world = self._editor_transform
        return {
            "available": bool(self.connected and self.vehicle is not None),
            "active": self.editor_camera is not None,
            "preview_ready": self._editor_image is not None,
            "preview_age_ms": round(age_ms, 1) if age_ms is not None else None,
            "mount": dict(self._camera_mount_preview or self._mount_values_from_config()),
            "saved_mount": self._mount_values_from_config(),
            "world_transform": None if world is None else {
                "x": round(float(world.location.x), 3),
                "y": round(float(world.location.y), 3),
                "z": round(float(world.location.z), 3),
                "pitch": round(float(world.rotation.pitch), 2),
                "yaw": round(float(world.rotation.yaw), 2),
                "roll": round(float(world.rotation.roll), 2),
            },
        }

    def camera_editor_jpeg(self):
        with self._condition:
            frame = None if self._editor_image is None else self._editor_image.copy()
        if frame is None:
            return None
        success, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
        return encoded.tobytes() if success else None

    def close_camera_editor(self, restore_mount=True):
        if restore_mount and self.vehicle is not None and self.camera is not None:
            try:
                self.restore_camera_mount()
            except Exception:
                logger.debug("Could not restore saved CARLA camera mount", exc_info=True)
        sensor, self.editor_camera = self.editor_camera, None
        if sensor is not None:
            try:
                sensor.stop()
            except Exception:
                pass
            try:
                sensor.destroy()
            except Exception:
                logger.debug("Failed to destroy CARLA editor camera", exc_info=True)
        with self._condition:
            self._editor_image = self._editor_image_at = None
        self._editor_transform = None
        return True

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
        self.close_camera_editor(restore_mount=False)
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
