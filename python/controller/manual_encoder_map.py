"""Manual-drive encoder telemetry adapter for the standalone encoder map page.

The displayed XY trajectory is an odometry estimate, not ground-truth localization.
A pulse-distance calibration is required for distance; steering geometry is additionally
required for a meaningful two-dimensional trajectory.
"""
import math
import time
import threading

from controller.odometry import EncoderOdometry


class ManualEncoderMap:
    def __init__(
        self,
        controller=None,
        *,
        servo_center=95,
        servo_min=50,
        servo_max=130,
        calibration=None,
        max_sample_age_s=0.5,
        clock=time.monotonic,
    ):
        self.controller = controller
        self.servo_center = float(servo_center)
        self.servo_min = float(servo_min)
        self.servo_max = float(servo_max)
        self.max_sample_age_s = max(0.05, float(max_sample_age_s))
        self._clock = clock
        self._lock = threading.RLock()
        self._odometry = None
        self._calibration = {
            "pulse_distance_cm": None,
            "wheelbase_cm": None,
            "road_angle_min_deg": None,
            "road_angle_max_deg": None,
        }
        self._connection_state = None
        self._minimum_receive_at = None
        self._last_seen_record_at = None
        self._last_extended_at = None
        self._latest_sample = None
        self._last_error = None
        self.set_calibration(calibration or {})

    @staticmethod
    def _optional_number(value, name):
        if value is None or value == "":
            return None
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            raise ValueError(name + " must be a finite number or blank")
        if not math.isfinite(number):
            raise ValueError(name + " must be finite")
        return number

    def set_controller(self, controller):
        with self._lock:
            if controller is self.controller:
                return
            self.controller = controller
            self._connection_state = None
            self._minimum_receive_at = self._clock()
            self._last_seen_record_at = None
            self._last_extended_at = None
            self._latest_sample = None
            if self._odometry is not None:
                self._odometry.mark_discontinuity("manual controller instance changed")

    def set_calibration(self, values):
        if not isinstance(values, dict):
            raise ValueError("Calibration must be a JSON object")
        pulse = self._optional_number(values.get("pulse_distance_cm"), "pulse_distance_cm")
        wheelbase = self._optional_number(values.get("wheelbase_cm"), "wheelbase_cm")
        road_min = self._optional_number(values.get("road_angle_min_deg"), "road_angle_min_deg")
        road_max = self._optional_number(values.get("road_angle_max_deg"), "road_angle_max_deg")

        if pulse is not None and pulse <= 0:
            raise ValueError("pulse_distance_cm must be greater than zero")
        if wheelbase is not None and wheelbase <= 0:
            raise ValueError("wheelbase_cm must be greater than zero")
        if (road_min is None) != (road_max is None):
            raise ValueError("Provide both road-wheel angle calibration endpoints, or leave both blank")
        if road_min is not None:
            if not (-45.0 <= road_min < 0.0 < road_max <= 45.0):
                raise ValueError("Road-wheel angle endpoints must be within -45..45 degrees and straddle zero")
            if not (self.servo_min < self.servo_center < self.servo_max):
                raise ValueError("Servo min/center/max calibration is inconsistent")
        normalized = {
            "pulse_distance_cm": pulse,
            "wheelbase_cm": wheelbase,
            "road_angle_min_deg": road_min,
            "road_angle_max_deg": road_max,
        }

        with self._lock:
            self._calibration = normalized
            if pulse is None:
                self._odometry = None
            else:
                self._odometry = EncoderOdometry(
                    pulse,
                    wheelbase_cm=wheelbase,
                    servo_center=self.servo_center,
                    servo_min=self.servo_min,
                    servo_max=self.servo_max,
                    road_angle_min_deg=road_min,
                    road_angle_max_deg=road_max,
                    max_sample_age_s=self.max_sample_age_s,
                )
            self._minimum_receive_at = self._clock()
            self._last_seen_record_at = None
            self._last_extended_at = None
            self._latest_sample = None
            self._last_error = None
            return dict(self._calibration)

    def request_telemetry(self, timeout=0.5):
        with self._lock:
            controller = self.controller
        if controller is None or not self._connected(controller):
            return False
        request = getattr(controller, "request_encoder_telemetry", None)
        if not callable(request):
            return False
        try:
            ok = bool(request(timeout=max(0.0, min(2.0, float(timeout)))))
        except Exception as exc:
            with self._lock:
                self._last_error = type(exc).__name__ + ": " + str(exc)
            return False
        if not ok:
            with self._lock:
                self._last_error = "No ODOM1 acknowledgement received"
        return ok

    @staticmethod
    def _connected(controller):
        if controller is None or bool(getattr(controller, "without_arduino", False)):
            return False
        connection = getattr(controller, "connection", None)
        return bool(connection is not None and getattr(connection, "connected", False))

    def poll_once(self, now=None):
        now = self._clock() if now is None else float(now)
        with self._lock:
            controller = self.controller
            if controller is None:
                self._connection_state = False
                return False
            connected = self._connected(controller)

            if self._connection_state is None:
                self._connection_state = connected
                if connected:
                    self._minimum_receive_at = now
            elif connected != self._connection_state:
                if self._odometry is not None:
                    self._odometry.mark_discontinuity(
                        "serial connection lost/reconnected; motion during outage is unknown"
                    )
                self._connection_state = connected
                self._last_extended_at = None
                self._latest_sample = None
                self._minimum_receive_at = now if connected else None
                self._last_seen_record_at = None

            if not connected:
                return False
            reader = getattr(controller, "encoder_telemetry", None)
            if not callable(reader):
                self._last_error = "Controller does not expose encoder telemetry"
                return False
            try:
                records = reader(limit=100)
            except Exception as exc:
                self._last_error = type(exc).__name__ + ": " + str(exc)
                return False

            accepted = False

            def record_time(record):
                value = self._optional_number(record.get("received_at"), "received_at")
                return value if value is not None else -math.inf

            records = sorted(
                (record for record in records if isinstance(record, dict)),
                key=record_time,
            )
            for sample in records:
                received_at = self._optional_number(sample.get("received_at"), "received_at")
                if received_at is None:
                    continue
                if self._last_seen_record_at is not None and received_at <= self._last_seen_record_at:
                    continue
                self._last_seen_record_at = received_at
                if self._minimum_receive_at is not None and received_at < self._minimum_receive_at:
                    continue
                if not sample.get("extended", False):
                    continue
                self._latest_sample = dict(sample)
                self._last_extended_at = received_at
                if self._odometry is not None:
                    self._odometry.ingest(sample, received_at=received_at)
                self._last_error = None
                accepted = True
            return accepted

    def reset_origin(self):
        with self._lock:
            if self._odometry is None:
                raise RuntimeError("Enter a positive pulse-distance calibration before resetting the map origin")
            self._odometry.reset_display_origin()

    def snapshot(self, now=None):
        now = self._clock() if now is None else float(now)
        with self._lock:
            controller = self.controller
            connected = self._connected(controller)
            connection = getattr(controller, "connection", None) if controller is not None else None
            connection_state = (
                getattr(connection, "state", "CONNECTED" if connected else "DISCONNECTED")
                if connection is not None else "DISCONNECTED"
            )
            age = (
                max(0.0, now - self._last_extended_at)
                if self._last_extended_at is not None else None
            )
            telemetry_fresh = bool(age is not None and age <= self.max_sample_age_s)
            odom = self._odometry.snapshot(now=now) if self._odometry is not None else None
            trajectory = bool(odom and odom.get("trajectory_available"))
            telemetry_available = self._latest_sample is not None

            if not connected:
                message = "Arduino is disconnected; no live encoder samples can be read."
            elif not telemetry_available:
                message = "Waiting for ODOM1 encoder telemetry. Check the selected firmware or enable telemetry."
            elif not telemetry_fresh:
                message = "Encoder telemetry is stale; the displayed position is not a live estimate."
            elif self._odometry is None:
                message = "Encoder pulses are arriving. Enter pulse distance to calculate travel distance."
            elif not trajectory:
                message = "Travel distance is available; wheelbase and road-wheel angle calibration are needed for a 2D path."
            elif odom and not odom.get("valid"):
                message = str(odom.get("reason") or "Odometry continuity is not currently valid.")
            else:
                message = "Live estimated odometry; wheel slip and single-channel direction estimation can cause drift."

            payload = {
                "connected": connected,
                "connection_state": str(connection_state),
                "telemetry_available": telemetry_available,
                "telemetry_fresh": telemetry_fresh,
                "sample_age_s": age,
                "max_sample_age_s": self.max_sample_age_s,
                "servo_center": self.servo_center,
                "servo_min": self.servo_min,
                "servo_max": self.servo_max,
                "calibration": dict(self._calibration),
                "distance_calibrated": bool(self._odometry is not None),
                "trajectory_available": trajectory,
                "calibrated": trajectory,
                "message": message,
                "last_error": self._last_error,
                "signed_pulses": (
                    self._latest_sample.get("signed_pulses")
                    if self._latest_sample else None
                ),
                "raw_count": (
                    self._latest_sample.get("raw_count")
                    if self._latest_sample else None
                ),
                "servo_command": (
                    self._latest_sample.get("servo")
                    if self._latest_sample else None
                ),
                "epoch": self._latest_sample.get("epoch") if self._latest_sample else None,
                "history": [],
                "travel_cm": None,
                "signed_distance_cm": None,
                "x_cm": None,
                "y_cm": None,
                "heading_rad": None,
                "road_wheel_angle_deg": None,
                "pulse_distance_cm": self._calibration["pulse_distance_cm"],
                "wheelbase_cm": self._calibration["wheelbase_cm"],
            }
            if odom is not None:
                for key in (
                    "history", "travel_cm", "signed_distance_cm", "x_cm", "y_cm",
                    "heading_rad", "road_wheel_angle_deg", "pulse_distance_cm",
                    "wheelbase_cm", "reason",
                ):
                    payload[key] = odom.get(key)
                payload["odometry_valid"] = bool(
                    odom.get("valid") and telemetry_fresh
                )
            else:
                payload["odometry_valid"] = False
            payload["valid"] = bool(payload["odometry_valid"] and telemetry_fresh)
            return payload
