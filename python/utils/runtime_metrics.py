import math
import threading
import time
from collections import deque


DEFAULT_WINDOW_SIZE = 240


class RuntimeMetrics:
    """Low-overhead runtime measurements for the control process."""

    _TIMERS = ("loop", "camera", "perception", "control", "serial")

    def __init__(self, window_size=DEFAULT_WINDOW_SIZE):
        self.window_size = max(10, int(window_size))
        self._lock = threading.RLock()
        self._started_at = time.monotonic()
        self._timings = {
            name: deque(maxlen=self.window_size)
            for name in self._TIMERS
        }
        self._counters = {
            "frames": 0,
            "camera_failures": 0,
            "perception_failures": 0,
            "serial_failures": 0,
            "serial_commands": 0,
        }
        self._last = {
            "loop_started_at": None,
            "frame_at": None,
            "serial_command_at": None,
            "camera_at": None,
            "perception_at": None,
        }

    def _record_timing(self, name, duration_ms):
        if name not in self._timings:
            return
        duration_ms = max(0.0, float(duration_ms))
        with self._lock:
            self._timings[name].append(duration_ms)

    def record_loop(self, duration_ms):
        with self._lock:
            self._counters["frames"] += 1
            self._last["frame_at"] = time.monotonic()
        self._record_timing("loop", duration_ms)

    def record_camera(self, duration_ms, valid):
        with self._lock:
            self._last["camera_at"] = time.monotonic()
            if not valid:
                self._counters["camera_failures"] += 1
        self._record_timing("camera", duration_ms)

    def record_perception(self, duration_ms, valid):
        with self._lock:
            self._last["perception_at"] = time.monotonic()
            if not valid:
                self._counters["perception_failures"] += 1
        self._record_timing("perception", duration_ms)

    def record_control(self, duration_ms):
        self._record_timing("control", duration_ms)

    def record_serial(self, duration_ms, success):
        with self._lock:
            self._last["serial_command_at"] = time.monotonic()
            self._counters["serial_commands"] += 1
            if not success:
                self._counters["serial_failures"] += 1
        self._record_timing("serial", duration_ms)

    @staticmethod
    def _statistics(values):
        if not values:
            return {
                "count": 0,
                "mean_ms": 0.0,
                "min_ms": 0.0,
                "max_ms": 0.0,
                "p95_ms": 0.0,
            }

        ordered = sorted(values)
        count = len(ordered)
        p95_index = min(count - 1, max(0, math.ceil(count * 0.95) - 1))
        return {
            "count": count,
            "mean_ms": sum(ordered) / count,
            "min_ms": ordered[0],
            "max_ms": ordered[-1],
            "p95_ms": ordered[p95_index],
        }

    def snapshot(self):
        now = time.monotonic()
        with self._lock:
            timing = {
                name: self._statistics(list(values))
                for name, values in self._timings.items()
            }
            counters = dict(self._counters)
            last = dict(self._last)

        last_frame_age_ms = None
        if last["frame_at"] is not None:
            last_frame_age_ms = max(0.0, (now - last["frame_at"]) * 1000.0)

        last_serial_age_ms = None
        if last["serial_command_at"] is not None:
            last_serial_age_ms = max(0.0, (now - last["serial_command_at"]) * 1000.0)

        elapsed = max(0.0, now - self._started_at)
        avg_fps = counters["frames"] / elapsed if elapsed > 0 else 0.0

        return {
            "uptime_s": elapsed,
            "avg_fps": avg_fps,
            "counters": counters,
            "timing": timing,
            "last_frame_age_ms": last_frame_age_ms,
            "last_serial_command_age_ms": last_serial_age_ms,
        }
