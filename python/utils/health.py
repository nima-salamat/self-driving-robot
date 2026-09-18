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
