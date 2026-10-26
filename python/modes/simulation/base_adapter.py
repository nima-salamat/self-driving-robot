"""Common simulator adapter contracts and normalized sensor snapshots."""
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class SensorFrame:
    image: Any
    captured_at: float
    sequence: int
    speed_kmh: float = 0.0
    ranges_cm: Dict[str, Optional[float]] = field(default_factory=dict)
    lidar_points: Any = None
    distance_delta_cm: Optional[float] = None
    location: Optional[tuple] = None
    yaw_degrees: Optional[float] = None


@dataclass(frozen=True)
class VehicleCommand:
    steering: float
    throttle: float
    brake: float
    servo_angle: float
    target_speed: float
    reason: str = ""


class SimulatorAdapter:
    """Adapter interface. Implementations normalize sensors and actuator commands."""
    backend = "unknown"
    supports_lidar = False

    def __init__(self, config):
        self.config = config
        self.connected = False

    def connect(self):
        raise NotImplementedError

    def read(self, timeout=0.25):
        raise NotImplementedError

    def apply_control(self, command: VehicleCommand):
        raise NotImplementedError

    def close(self):
        self.connected = False
