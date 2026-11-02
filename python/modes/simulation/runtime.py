"""Mode-aware simulation loop with virtual actuators, telemetry and dashboard frames."""
import logging
import math
import threading
import time
from collections import deque

import cv2
import numpy as np

from controller.odometry import EncoderOdometry
from utils.processing_rate import DEFAULT_TARGET_FPS
from stream import start_stream, stop_stream
from .adapter_registry import create_adapter
from .base_adapter import VehicleCommand
from .controller import VirtualVehicleController
from visualization.lane_debug_overlay import render_lane_debug_overlay

logger = logging.getLogger(__name__)


class SimulationRuntime:
    def __init__(self, config):
        self.config = config
        self.mode = str(getattr(config, "MODE", "carla"))
        self.backend = str(getattr(config, "SIMULATOR_BACKEND", "carla")).lower()
        self.vision_profile = str(getattr(config, "SIMULATION_VISION_PROFILE", "city")).lower()
        if self.vision_profile == "race":
            from vision.race_vision_processing import VisionProcessor
            self.vision = VisionProcessor()
        elif str(getattr(config, "CITY_LANE_DETECTOR", "default")) == "blsf-beta":
            from vision.blsf_lane import create_blsf_lane_detector
            self.vision = create_blsf_lane_detector(config)
        else:
            from vision.city_vision_processing import VisionProcessor
            self.vision = VisionProcessor()
        self.adapter = create_adapter(self.backend, config)
        self.controller = VirtualVehicleController(config, self.backend)
        self.shutdown_event = getattr(config, "SHUTDOWN_EVENT", None)
        if self.shutdown_event is None:
            self.shutdown_event = threading.Event()
        self.target_fps = float(getattr(config, "TARGET_PROCESSING_FPS", DEFAULT_TARGET_FPS))
        self._frame_period = 1.0 / max(1.0, self.target_fps)
        self._next_cycle_at = time.monotonic()
        self.frame_lock = threading.RLock()
        config.stream_frame_lock = self.frame_lock
        if not isinstance(getattr(config, "debug_frames_list", None), list) or len(config.debug_frames_list) < 2:
            config.debug_frames_list = [None, None]
        self._events = deque(maxlen=120)
        self._state_lock = threading.RLock()
        self._started_at = None
        self._last_frame_at = None
        self._last_sequence = 0
        self._last_result = {}
        self._last_sensor_frame = None
        self._last_command = self.controller.last_command
        self._last_error = None
        self._last_event_key = None
        self._last_cycle_at = None
        self._stop_event_active = False
        self._camera_editor_active = False
        self._scene_edit_active = False
        # CARLA is deliberately disarmed on every process start. AVIS keeps
        # its historical auto-run behavior until it gains a separate run UI.
        self._run_enabled = self.backend != "carla"
        self._last_image_diagnostics = {}
        self._distance_accumulator_cm = 0.0
        self._encoder_pulses = 0
        self._encoder_delta = 0
        self._last_distance_cm = 0.0
        self.odometry = None
        if bool(getattr(config, "ENCODER_MAP_ENABLED", False)):
            wheelbase = getattr(config, "ENCODER_WHEELBASE_CM", None)
            road_min = getattr(config, "ENCODER_ROAD_ANGLE_MIN_DEG", None)
            road_max = getattr(config, "ENCODER_ROAD_ANGLE_MAX_DEG", None)
            if wheelbase is None or road_min is None or road_max is None:
                wheelbase = None
                max_wheel_angle = 25.0
            else:
                max_wheel_angle = max(abs(float(road_min)), abs(float(road_max)))
            self.odometry = EncoderOdometry(
                float(getattr(config, "ENCODER_PULSE_DISTANCE_CM", 0.5)),
                wheelbase_cm=wheelbase,
                servo_center=getattr(config, "SERVO_CENTER", 95),
                servo_min=getattr(config, "MIN_SERVO_ANGLE", 50),
                servo_max=getattr(config, "MAX_SERVO_ANGLE", 130),
                max_wheel_angle_deg=max_wheel_angle,
            )
            config.encoder_odometry = self.odometry
        config.simulation_runtime = self
        config.SIMULATED_IO = True
        config.simulator_backend = self.backend
        self._record_event("info", "Virtual actuator/encoder initialized; no physical Arduino is attached.")

    def _record_event(self, level, message, *, log=True):
        event = {"timestamp": time.time(), "level": str(level).upper(), "message": str(message)[:500]}
        with self._state_lock:
            self._events.append(event)
        if log:
            getattr(logger, str(level).lower(), logger.info)("SIM/%s: %s", self.backend, message)

    def _publish_frame(self, sensor_frame, perception, command):
        debug = perception.get("debug") if isinstance(perception, dict) else None
        debug_frame = debug.get("combined") if isinstance(debug, dict) else None
        # Use the adapter's raw camera image by default. When BEV is enabled,
        # show its processing frame only when it contains real image content;
        # a blank warp must never replace an otherwise valid camera image.
        display = sensor_frame.image.copy()
        frame_source = "camera"
        if bool(getattr(self.config, "USE_BEV", False)) and isinstance(debug_frame, np.ndarray) and debug_frame.size:
            sample = debug_frame[::16, ::16]
            if sample.size and float(np.mean(sample)) > 1.0:
                display = debug_frame.copy()
                frame_source = "bev"
        sample = display[::16, ::16]
        self._last_image_diagnostics = {
            "width": int(display.shape[1]),
            "height": int(display.shape[0]),
            "mean_intensity": round(float(np.mean(sample)), 2) if sample.size else 0.0,
            "max_intensity": int(np.max(sample)) if sample.size else 0,
            "source": frame_source,
            "looks_black": bool(not sample.size or float(np.mean(sample)) < 1.0 or int(np.max(sample)) < 4),
        }
        draw_data = debug.get("draw_data") if isinstance(debug, dict) else None
        can_draw_processing_geometry = frame_source == "bev" or not bool(getattr(self.config, "USE_BEV", False))
        if isinstance(draw_data, dict) and can_draw_processing_geometry:
            try:
                # The City/Race processors return the actual post-BEV ROI geometry.
                # Render it here so the simulator Stream shows the same diagnostics
                # as the physical City/Race Stream without modifying perception input.
                display = render_lane_debug_overlay(
                    display, draw_data, self.config, command.servo_angle
                )
            except Exception:
                logger.debug("Could not render simulator lane debug overlay", exc_info=True)
        cv2.putText(display, f"MODE {self.mode.upper()} | {self.vision_profile.upper()} VISION",
                    (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (40, 220, 255), 2, cv2.LINE_AA)
        cv2.putText(display, "Lane: " + str(perception.get("lane_type", "none")) +
                    "  valid=" + str(bool(perception.get("perception_valid", False))),
                    (12, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (40, 220, 255), 1, cv2.LINE_AA)
        cv2.putText(display, f"Steer: {command.servo_angle:.1f}  Speed: {sensor_frame.speed_kmh:.1f} km/h",
                    (12, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (40, 220, 255), 1, cv2.LINE_AA)
        if perception.get("crosswalk"):
            cv2.putText(display, "CROSSWALK DETECTED", (12, 94),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 230, 255), 2, cv2.LINE_AA)
        with self.frame_lock:
            self.config.debug_frames_list = [None, display]
            self.config.stream_frame_seq = int(getattr(self.config, "stream_frame_seq", 0)) + 1

    def _update_virtual_encoder(self, frame, command, now):
        dt = max(0.0, now - self._last_cycle_at) if self._last_cycle_at is not None else 0.0
        delta_cm = frame.distance_delta_cm
        if delta_cm is None or not math.isfinite(float(delta_cm)):
            delta_cm = max(0.0, float(frame.speed_kmh)) * 100000.0 / 3600.0 * dt
        delta_cm = max(0.0, float(delta_cm))
        self._distance_accumulator_cm += delta_cm
        pulse_distance = max(0.001, float(getattr(self.config, "ENCODER_PULSE_DISTANCE_CM", 0.5)))
        new_count = int(self._distance_accumulator_cm / pulse_distance)
        self._encoder_delta = new_count - self._encoder_pulses
        self._encoder_pulses = new_count
        self._last_distance_cm += delta_cm
        if self.odometry is not None:
            self.odometry.ingest({
                "extended": True, "epoch": "simulated-1",
                "signed_pulses": self._encoder_pulses,
                "servo": int(round(command.servo_angle)), "valid": True,
            }, received_at=now)

    def _record_command_if_changed(self, perception, command):
        # Steering changes almost every frame. They belong in the live state
        # panel, not in the terminal: emitting an INFO line per frame adds
        # avoidable console I/O and can materially reduce processing FPS.
        key = (
            str(perception.get("lane_type", "none")),
            bool(perception.get("perception_valid", False)),
            bool(command.throttle > 0.001),
            bool(command.brake >= 0.5),
            str(command.reason),
        )
        if key != self._last_event_key:
            self._last_event_key = key
            level = "info" if perception.get("perception_valid") else "warning"
            message = "virtual actuator state changed: throttle={:.2f}, brake={:.2f}; {}".format(
                command.throttle, command.brake, command.reason
            )
            self._record_event(level, message, log=False)

    def set_run_enabled(self, enabled):
        """Arm/disarm CARLA autonomous motion; disarming applies the brake immediately."""
        if self.backend != "carla":
            raise RuntimeError("Explicit run mode is currently available only for CARLA.")
        enabled = bool(enabled)
        if enabled == self._run_enabled:
            return self._run_enabled
        if enabled:
            if self._camera_editor_active or self._scene_edit_active:
                raise RuntimeError("Close the CARLA camera/scene editor before starting autonomous run.")
            if not self.adapter.connected or not self._carla_vehicle_ready():
                raise RuntimeError("CARLA vehicle is not ready; autonomous run cannot be started.")
            self._run_enabled = True
            self._last_error = None
            self._stop_event_active = False
            self._record_event("info", "CARLA autonomous run enabled by an explicit Stream command.")
        else:
            self._run_enabled = False
            self._safe_stop("CARLA run mode stopped; waiting for an explicit Start Run command.")
            self._last_error = None
            self._record_event("warning", "CARLA autonomous run disabled; vehicle is held by the brake.")
        return self._run_enabled

    def set_camera_editor_active(self, active):
        """Hold the CARLA vehicle while the user is positioning the camera."""
        active = bool(active)
        if active == self._camera_editor_active:
            return
        self._camera_editor_active = active
        if active:
            self.set_run_enabled(False)
            self._safe_stop("CARLA camera editor is open; holding vehicle stationary.")
            self._record_event("warning", "Camera placement studio active; CARLA run is disarmed.")
        else:
            self._record_event("info", "Camera placement studio closed; CARLA remains STOPPED until Start Run is pressed.")

    def set_scene_edit_active(self, active):
        """Temporarily hold autonomous control while the CARLA scene is reconfigured."""
        active = bool(active)
        if active == self._scene_edit_active:
            return
        self._scene_edit_active = active
        if active:
            if self.backend == "carla":
                self.set_run_enabled(False)
            self._safe_stop("CARLA scene editor is changing the world, vehicle, or spawn point.")
            self._record_event("warning", "CARLA scene change started; autonomous throttle is suspended.")
        else:
            self._record_event("info", "CARLA scene change finished; CARLA remains STOPPED until Start Run is pressed.")

    def _carla_vehicle_ready(self):
        if self.backend != "carla":
            return True
        readiness = getattr(self.adapter, "control_ready", None)
        return bool(readiness()) if callable(readiness) else True

    def _safe_stop(self, reason):
        self._last_error = str(reason)
        if not self._stop_event_active:
            self._record_event("warning", reason)
        self._stop_event_active = True
        safe = VehicleCommand(
            steering=self._last_command.steering if self._last_command else 0.0,
            throttle=0.0, brake=1.0,
            servo_angle=self.controller.last_servo, target_speed=0.0, reason=reason,
        )
        try:
            self.adapter.apply_control(safe)
        except Exception:
            logger.debug("Virtual safe-stop command failed", exc_info=True)
        self._last_command = safe

    def snapshot(self):
        now = time.monotonic()
        with self._state_lock:
            result = dict(self._last_result)
            frame = self._last_sensor_frame
            points = getattr(frame, "lidar_points", None) if frame is not None else None
            lidar_xy, nearest_m = [], None
            if points is not None and len(points):
                try:
                    finite = np.isfinite(points[:, :2]).all(axis=1)
                    selected = points[finite]
                    if len(selected):
                        stride = max(1, int(math.ceil(len(selected) / 500.0)))
                        lidar_xy = [[float(p[0]), float(p[1])] for p in selected[::stride][:500]]
                        nearest_m = float(np.linalg.norm(selected[:, :2], axis=1).min())
                except Exception:
                    logger.debug("Could not make LiDAR preview snapshot", exc_info=True)
            ranges = dict(getattr(frame, "ranges_cm", {}) or {}) if frame is not None else {}
            age_ms = None if self._last_frame_at is None else max(0.0, (now - self._last_frame_at) * 1000.0)
            speed = float(getattr(frame, "speed_kmh", 0.0) or 0.0) if frame is not None else 0.0
            encoder = {"available": True, "pulses": int(self._encoder_pulses),
                       "delta": int(self._encoder_delta), "distance_cm": round(self._last_distance_cm, 2),
                       "source": "simulated travel estimate; not hardware ground truth"}
            sensor_data = {
                "speed_kmh": speed, "ranges_cm": ranges,
                "lidar_available": bool(self.backend == "carla" and
                                        getattr(self.config, "SIMULATOR_LIDAR_ENABLED", False) and points is not None),
                "lidar_point_count": int(len(points)) if points is not None else 0,
                "lidar_points_xy": lidar_xy, "lidar_nearest_m": nearest_m,
                "virtual_encoder": encoder,
                "range_min_cm": min((v for v in ranges.values() if isinstance(v, (int, float)) and math.isfinite(float(v))), default=None),
            }
            return {
                "mode": self.mode, "backend": self.backend, "vision_profile": self.vision_profile,
                "editor_profile": "simulator", "connected": bool(self.adapter.connected),
                "camera_editor_active": bool(self._camera_editor_active),
                "run_enabled": bool(self._run_enabled),
                "run_mode": "running" if self._run_enabled else "stopped",
                "image": dict(self._last_image_diagnostics),
                "running": self._started_at is not None and not self.shutdown_event.is_set(),
                "frame_sequence": int(getattr(frame, "sequence", 0)) if frame is not None else 0,
                "frame_age_ms": round(age_ms, 1) if age_ms is not None else None,
                "lane_type": str(result.get("lane_type", "none")),
                "perception_valid": bool(result.get("perception_valid", False)),
                "steering_angle": round(float(self.controller.last_servo), 2),
                "steering_normalized": round(float(self._last_command.steering), 3),
                "crosswalk": bool(result.get("crosswalk", False)), "speed_kmh": round(speed, 2),
                "command": {"steering": round(float(self._last_command.steering), 3),
                            "throttle": round(float(self._last_command.throttle), 3),
                            "brake": round(float(self._last_command.brake), 3),
                            "servo_angle": round(float(self._last_command.servo_angle), 2),
                            "target_speed": float(self._last_command.target_speed),
                            "reason": self._last_command.reason},
                "sensors": sensor_data, "virtual_io": encoder,
                "events": list(self._events)[-60:], "error": self._last_error,
            }

    def run(self):
        try:
            self.adapter.connect()
            self._started_at = time.monotonic()
            self._stop_event_active = False
            self._record_event("info", f"Connected {self.backend}; {self.vision_profile} vision processor loaded.")
            if self.backend == "carla":
                # Apply a physical CARLA brake before the first sensor/control cycle.
                self._safe_stop("CARLA connected in STOPPED mode; press Start Run to enable autonomy.")
            while not self.shutdown_event.is_set():
                frame = self.adapter.read(timeout=0.25)
                now = time.monotonic()
                if frame is None:
                    self._safe_stop("No fresh simulator camera frame; braking until frames resume.")
                    self.shutdown_event.wait(0.05)
                    continue
                if frame.sequence and frame.sequence == self._last_sequence:
                    continue
                self._last_sequence = frame.sequence
                self._last_frame_at = frame.captured_at
                self._last_sensor_frame = frame
                sensor_status = dict(getattr(frame, "sensor_status", {}) or {})
                if (
                    self.backend == "carla"
                    and bool(getattr(self.config, "SIMULATOR_LIDAR_ENABLED", False))
                    and sensor_status.get("lidar_fresh") is not True
                ):
                    age = sensor_status.get("lidar_age_s")
                    age_text = str(sensor_status.get("lidar_reason") or "sensor not fresh")
                    if age is not None:
                        age_text += f", last packet {float(age):.2f}s ago"
                    self._safe_stop(
                        "CARLA LiDAR is missing or stale (" + age_text + "); braking until fresh sensor data returns."
                    )
                    # LiDAR health must stop motion, not blank the camera dashboard.
                    # Keep publishing the fresh RGB frame while waiting for LiDAR.
                    self._last_result = {
                        "lane_type": "not evaluated",
                        "perception_valid": False,
                        "crosswalk": False,
                    }
                    self._publish_frame(frame, self._last_result, self._last_command)
                    self.shutdown_event.wait(0.05)
                    continue
                result = self.vision.detect(frame.image)
                if not isinstance(result, dict):
                    result = {}
                command = self.controller.command_for(result, frame.speed_kmh)
                obstacle_limit = float(getattr(self.config, "SIMULATOR_OBSTACLE_STOP_DISTANCE_CM", 35.0))
                ranges = dict(getattr(frame, "ranges_cm", {}) or {})
                front_range = ranges.get("front")
                if front_range is not None and obstacle_limit > 0:
                    try:
                        front_range = float(front_range)
                    except (TypeError, ValueError, OverflowError):
                        front_range = None
                    if front_range is not None and math.isfinite(front_range) and 0 <= front_range <= obstacle_limit:
                        command = VehicleCommand(
                            steering=command.steering, throttle=0.0, brake=1.0,
                            servo_angle=command.servo_angle, target_speed=0.0,
                            reason=f"forward range {front_range:.1f} cm at/below {obstacle_limit:.1f} cm; simulator braking",
                        )
                if (self.vision_profile == "city" and bool(result.get("crosswalk", False))
                        and bool(getattr(self.config, "SIMULATOR_STOP_ON_CROSSWALK", True))):
                    command = VehicleCommand(
                        steering=command.steering, throttle=0.0, brake=1.0,
                        servo_angle=command.servo_angle, target_speed=0.0,
                        reason="crosswalk detected; simulator braking",
                    )
                if self.backend == "carla" and not self._run_enabled:
                    command = VehicleCommand(
                        steering=command.steering, throttle=0.0, brake=1.0,
                        servo_angle=command.servo_angle, target_speed=0.0,
                        reason="run mode stopped; waiting for explicit Start Run command",
                    )
                if self.backend == "carla" and (self._camera_editor_active or self._scene_edit_active):
                    hold_reason = ("CARLA scene is being reconfigured; vehicle held stationary"
                                   if self._scene_edit_active else
                                   "CARLA camera placement studio active; vehicle held stationary")
                    command = VehicleCommand(
                        steering=command.steering, throttle=0.0, brake=1.0,
                        servo_angle=command.servo_angle, target_speed=0.0,
                        reason=hold_reason,
                    )
                if self.backend == "carla" and not self._carla_vehicle_ready():
                    hold_reason = "CARLA vehicle actor is temporarily unavailable; waiting for the scene to become ready."
                    self._last_command = VehicleCommand(
                        steering=command.steering, throttle=0.0, brake=1.0,
                        servo_angle=command.servo_angle, target_speed=0.0, reason=hold_reason,
                    )
                    if not self._stop_event_active:
                        self._record_event("warning", hold_reason)
                    self._stop_event_active = True
                    self.shutdown_event.wait(0.05)
                    continue
                if not self.adapter.apply_control(command):
                    # A stale camera frame can be processed just as CARLA destroys the old actor.
                    if self.backend == "carla" and not self._carla_vehicle_ready():
                        self._last_command = VehicleCommand(
                            steering=command.steering, throttle=0.0, brake=1.0,
                            servo_angle=command.servo_angle, target_speed=0.0,
                            reason="CARLA vehicle actor is temporarily unavailable; waiting for scene recovery.",
                        )
                        self.shutdown_event.wait(0.05)
                        continue
                    raise RuntimeError("simulator adapter did not accept the virtual actuator command")
                self._last_command = command
                self._last_result = result
                self._last_error = None
                self._stop_event_active = False
                self._update_virtual_encoder(frame, command, now)
                self._record_command_if_changed(result, command)
                self._publish_frame(frame, result, command)
                self._last_cycle_at = now
                self._next_cycle_at = max(self._next_cycle_at + self._frame_period, now)
                self.shutdown_event.wait(max(0.0, self._next_cycle_at - time.monotonic()))
        except KeyboardInterrupt:
            logger.info("Simulation interrupted; stopping vehicle")
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            self._record_event("error", self._last_error)
            logger.exception("Simulation runtime failed")
            raise
        finally:
            self._started_at = None
            self._safe_stop("Simulation runtime stopped; virtual vehicle commanded to brake.")
            try:
                self.adapter.close()
            finally:
                if getattr(self.config, "simulation_runtime", None) is self:
                    self.config.simulation_runtime = None

    def start(self):
        stream_thread = None
        if bool(getattr(self.config, "STREAM", False)):
            stream_thread = threading.Thread(target=start_stream, args=(self.config,),
                                             daemon=True, name="simulator-stream")
            stream_thread.start()
        try:
            self.run()
        finally:
            if stream_thread is not None and stream_thread.is_alive():
                try:
                    stop_stream(self.config)
                except Exception:
                    logger.debug("Could not stop simulator dashboard", exc_info=True)
                stream_thread.join(timeout=1.0)
