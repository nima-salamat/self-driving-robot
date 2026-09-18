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

    CAMERA_MAX_AGE_S = 1.0
    PERCEPTION_MAX_AGE_S = 1.0
    SERIAL_TELEMETRY_MAX_AGE_S = 1.0

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
        lifecycle = snapshot["lifecycle"]

        connection = getattr(config, "arduino_connection", None)
        if connection is not None:
            telemetry_status = None
            try:
                status_fn = getattr(connection, "telemetry_status", None)
                if callable(status_fn):
                    telemetry_status = status_fn(limit=0)
            except Exception:
                telemetry_status = None

            connected = bool(getattr(connection, "connected", False))
            enabled = not bool(getattr(config, "WITHOUT_ARDUINO", False))
            connection_state = (
                telemetry_status.get("state")
                if telemetry_status is not None
                else getattr(connection, "state", "UNKNOWN")
            )
            telemetry_age = (
                telemetry_status.get("last_line_age_s")
                if telemetry_status is not None
                else None
            )
            resources["arduino"] = {
                "enabled": enabled,
                "connected": connected,
                "state": connection_state,
                "telemetry_fresh": (
                    telemetry_age is not None
                    and telemetry_age <= self.SERIAL_TELEMETRY_MAX_AGE_S
                ) if enabled else None,
                "last_line_age_s": telemetry_age,
                "last_error": getattr(connection, "last_error", None),
            }
            if enabled and not connected:
                faults["arduino_serial"] = {
                    "severity": FaultSeverity.CRITICAL,
                    "message": getattr(connection, "last_error", None)
                    or connection_state
                    or "DISCONNECTED",
                    "age_s": 0.0,
                }
            elif enabled and telemetry_age is None:
                connected_age = (
                    telemetry_status.get("connected_age_s")
                    if telemetry_status is not None
                    else None
                )
                if (
                    connected_age is not None
                    and connected_age > self.SERIAL_TELEMETRY_MAX_AGE_S
                ):
                    faults["arduino_telemetry_missing"] = {
                        "severity": FaultSeverity.WARNING,
                        "message": "Arduino is connected but no telemetry has arrived",
                        "age_s": connected_age,
                    }
            elif (
                enabled
                and telemetry_age is not None
                and telemetry_age > self.SERIAL_TELEMETRY_MAX_AGE_S
            ):
                faults["arduino_telemetry_stale"] = {
                    "severity": FaultSeverity.WARNING,
                    "message": (
                        f"latest telemetry is {telemetry_age:.2f}s old"
                    ),
                    "age_s": telemetry_age,
                }

        metrics = getattr(config, "runtime_metrics", None)
        if metrics is not None:
            metric_snapshot = metrics.snapshot()
            perception_valid = metric_snapshot.get("last_perception_valid")
            perception_age_ms = metric_snapshot.get("last_perception_age_ms")
            resources["perception"] = {
                "last_valid": perception_valid,
                "last_age_ms": perception_age_ms,
            }
            if perception_valid is False:
                faults["perception"] = {
                    "severity": FaultSeverity.CRITICAL,
                    "message": "latest perception result is invalid",
                    "age_s": (perception_age_ms or 0.0) / 1000.0,
                }
            elif (
                lifecycle == HealthState.RUNNING
                and perception_age_ms is not None
                and perception_age_ms > self.PERCEPTION_MAX_AGE_S * 1000.0
            ):
                faults["perception_stale"] = {
                    "severity": FaultSeverity.CRITICAL,
                    "message": (
                        f"latest perception result is "
                        f"{perception_age_ms / 1000.0:.2f}s old"
                    ),
                    "age_s": perception_age_ms / 1000.0,
                }

        camera = getattr(config, "camera", None)
        if camera is not None:
            initialized = bool(getattr(camera, "camera_initialized", False))
            last_capture_at = getattr(camera, "last_capture_at", None)
            last_capture_age_s = (
                max(0.0, time.monotonic() - last_capture_at)
                if last_capture_at is not None
                else None
            )
            last_capture_valid = bool(
                getattr(camera, "last_capture_valid", False)
            )
            resources["camera"] = {
                "initialized": initialized,
                "last_capture_valid": last_capture_valid,
                "last_capture_age_s": last_capture_age_s,
                "consecutive_failures": int(
                    getattr(camera, "consecutive_failures", 0)
                ),
            }
            if not initialized:
                faults["camera"] = {
                    "severity": FaultSeverity.CRITICAL,
                    "message": "camera not initialized",
                    "age_s": 0.0,
                }
            elif last_capture_at is not None and not last_capture_valid:
                faults["camera"] = {
                    "severity": FaultSeverity.CRITICAL,
                    "message": "latest camera capture failed",
                    "age_s": last_capture_age_s or 0.0,
                }
            elif (
                lifecycle == HealthState.RUNNING
                and last_capture_age_s is not None
                and last_capture_age_s > self.CAMERA_MAX_AGE_S
            ):
                faults["camera_stale"] = {
                    "severity": FaultSeverity.CRITICAL,
                    "message": (
                        f"latest camera frame is {last_capture_age_s:.2f}s old"
                    ),
                    "age_s": last_capture_age_s,
                }

        sign_detector = getattr(config, "sign_detector", None)
        sign_enabled = bool(getattr(config, "WITH_SIGN", False))
        if sign_detector is not None and sign_enabled:
            try:
                sign_status = sign_detector.status()
            except Exception as exc:
                sign_status = {
                    "worker_alive": False,
                    "last_error": f"{type(exc).__name__}: {exc}",
                }
            resources["sign_detector"] = sign_status
            if not sign_status.get("worker_alive", False):
                faults["sign_worker"] = {
                    "severity": FaultSeverity.CRITICAL,
                    "message": sign_status.get(
                        "last_error", "sign detector worker is not alive"
                    ),
                    "age_s": 0.0,
                }
            elif (
                sign_status.get("inference_in_flight")
                and sign_status.get("last_submit_age_s") is not None
                and sign_status["last_submit_age_s"] > float(
                    getattr(config, "SIGN_RESULT_MAX_AGE", 0.75)
                )
            ):
                faults["sign_worker_stalled"] = {
                    "severity": FaultSeverity.WARNING,
                    "message": (
                        f"sign inference has been in flight for "
                        f"{sign_status['last_submit_age_s']:.2f}s"
                    ),
                    "age_s": sign_status["last_submit_age_s"],
                }
            elif (
                sign_status.get("last_result_age_s") is not None
                and sign_status["last_result_age_s"] > float(
                    getattr(config, "SIGN_RESULT_MAX_AGE", 0.75)
                )
            ):
                faults["sign_result_stale"] = {
                    "severity": FaultSeverity.WARNING,
                    "message": (
                        f"latest sign result is "
                        f"{sign_status['last_result_age_s']:.2f}s old"
                    ),
                    "age_s": sign_status["last_result_age_s"],
                }

        output_manager = getattr(config, "output_manager", None)
        if output_manager is not None:
            try:
                output_status = output_manager.stats()
            except Exception as exc:
                output_status = {
                    "writer_alive": False,
                    "last_error": f"{type(exc).__name__}: {exc}",
                }
            resources["recording"] = output_status
            if output_status.get("recording") and not output_status.get(
                "writer_alive", False
            ):
                faults["recording_worker"] = {
                    "severity": FaultSeverity.WARNING,
                    "message": output_status.get(
                        "last_error", "recording writer is not alive"
                    ),
                    "age_s": 0.0,
                }
            elif output_status.get("last_error"):
                faults["recording"] = {
                    "severity": FaultSeverity.WARNING,
                    "message": output_status["last_error"],
                    "age_s": 0.0,
                }

        if lifecycle == HealthState.SHUTTING_DOWN:
            state = HealthState.SHUTTING_DOWN
        elif any(
            fault["severity"] == FaultSeverity.CRITICAL
            for fault in faults.values()
        ):
            state = HealthState.FAULT
        elif faults:
            state = HealthState.DEGRADED
        elif lifecycle == HealthState.STARTING:
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
