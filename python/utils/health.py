import threading
import time


class HealthState:
    STARTING = "STARTING"
    READY = "READY"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    FAULT = "FAULT"
    SHUTTING_DOWN = "SHUTTING_DOWN"


class FaultSeverity:
    WARNING = "warning"
    CRITICAL = "critical"


class HealthMonitor:
    """Small explicit lifecycle/fault state tracker shared by runtime diagnostics."""

    def __init__(self):
        self._lock = threading.RLock()
        self._lifecycle = HealthState.STARTING
        self._faults = {}
        self._created_at = time.monotonic()

    def set_lifecycle(self, state):
        with self._lock:
            self._lifecycle = state

    def set_fault(self, name, active, severity=FaultSeverity.WARNING, message=None):
        with self._lock:
            if active:
                self._faults[name] = {
                    "severity": severity,
                    "message": message or name,
                    "since_monotonic": self._faults.get(name, {}).get(
                        "since_monotonic", time.monotonic()
                    ),
                }
            else:
                self._faults.pop(name, None)

    def snapshot_runtime(self, config):
        """Return health plus current hardware resource state."""
        snapshot = self.snapshot()
        faults = dict(snapshot["faults"])
        resources = {}

        connection = getattr(config, "arduino_connection", None)
        if connection is not None:
            connected = bool(getattr(connection, "connected", False))
            enabled = not bool(getattr(config, "WITHOUT_ARDUINO", False))
            resources["arduino"] = {
                "enabled": enabled,
                "connected": connected,
                "state": getattr(connection, "state", "UNKNOWN"),
                "last_error": getattr(connection, "last_error", None),
            }
            if enabled and not connected:
                faults["arduino_serial"] = {
                    "severity": FaultSeverity.CRITICAL,
                    "message": getattr(connection, "last_error", None) or getattr(connection, "state", "DISCONNECTED"),
                    "age_s": 0.0,
                }

        metrics = getattr(config, "runtime_metrics", None)
        if metrics is not None:
            metric_snapshot = metrics.snapshot()
            perception_valid = metric_snapshot.get("last_perception_valid")
            resources["perception"] = {
                "last_valid": perception_valid,
                "last_age_ms": metric_snapshot.get("last_perception_age_ms"),
            }
            if perception_valid is False:
                faults["perception"] = {
                    "severity": FaultSeverity.CRITICAL,
                    "message": "latest perception result is invalid",
                    "age_s": 0.0,
                }
        camera = getattr(config, "camera", None)
        if camera is not None:
            initialized = bool(getattr(camera, "camera_initialized", False))
            resources["camera"] = {
                "initialized": initialized,
                "last_capture_valid": bool(getattr(camera, "last_capture_valid", False)),
                "consecutive_failures": int(getattr(camera, "consecutive_failures", 0)),
            }
            if not initialized:
                faults["camera"] = {
                    "severity": FaultSeverity.CRITICAL,
                    "message": "camera not initialized",
                    "age_s": 0.0,
                }

        if any(fault["severity"] == FaultSeverity.CRITICAL for fault in faults.values()):
            state = HealthState.FAULT
        elif faults:
            state = HealthState.DEGRADED
        elif snapshot["lifecycle"] == HealthState.STARTING:
            state = HealthState.READY
        else:
            state = snapshot["state"]

        return {
            **snapshot,
            "state": state,
            "faults": faults,
            "resources": resources,
        }
    def snapshot(self):
        with self._lock:
            faults = {
                name: {
                    "severity": value["severity"],
                    "message": value["message"],
                    "age_s": max(0.0, time.monotonic() - value["since_monotonic"]),
                }
                for name, value in self._faults.items()
            }
            lifecycle = self._lifecycle

        if lifecycle in (HealthState.STARTING, HealthState.READY, HealthState.SHUTTING_DOWN):
            effective = lifecycle
        elif any(
            fault["severity"] == FaultSeverity.CRITICAL
            for fault in faults.values()
        ):
            effective = HealthState.FAULT
        elif faults:
            effective = HealthState.DEGRADED
        else:
            effective = HealthState.RUNNING

        return {
            "state": effective,
            "lifecycle": lifecycle,
            "faults": faults,
            "uptime_s": max(0.0, time.monotonic() - self._created_at),
        }
