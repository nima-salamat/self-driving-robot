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
from .avis_behaviors import AVISBehaviorCoordinator
from visualization.lane_debug_overlay import render_lane_debug_overlay

logger = logging.getLogger(__name__)


def _draw_simulation_debug_panel(image, title, rows):
    """Render diagnostics in one aligned panel with consistent typography."""
    if not isinstance(image, np.ndarray) or image.size == 0:
        return image
    height, width = image.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = max(0.32, min(0.50, height / 1600.0))
    thickness = max(1, int(round(height / 850.0)))
    title_height = max(24, int(round(height * 0.038)))
    row_height = max(20, int(round(height * 0.032)))
    panel_width = min(width - 16, max(220, int(round(width * 0.40))))
    panel_height = min(height - 16, title_height + row_height * len(rows) + 12)
    if panel_width < 90 or panel_height < title_height:
        return image

    x0, y0 = 8, 8
    x1, y1 = x0 + panel_width, y0 + panel_height
    overlay = image.copy()
    cv2.rectangle(overlay, (x0, y0), (x1, y1), (14, 20, 29), -1)
    cv2.addWeighted(overlay, 0.84, image, 0.16, 0.0, image)
    cv2.rectangle(image, (x0, y0), (x1, y1), (86, 101, 119), 1, cv2.LINE_AA)
    cv2.putText(
        image, str(title).upper(), (x0 + 10, y0 + max(17, title_height - 7)),
        font, font_scale, (235, 241, 248), thickness + 1, cv2.LINE_AA,
    )
    cv2.line(
        image, (x0 + 8, y0 + title_height),
        (x1 - 8, y0 + title_height), (70, 83, 99), 1, cv2.LINE_AA,
    )

    text_width = max(24, panel_width - 42)
    for index, (label, value, indicator) in enumerate(rows):
        baseline = y0 + title_height + (index + 1) * row_height - 4
        if baseline > y1 - 3:
            break
        dot_x, dot_y = x0 + 14, baseline - max(5, row_height // 3)
        cv2.circle(image, (dot_x, dot_y), max(3, thickness + 1), indicator, -1, cv2.LINE_AA)
        text = "{}  {}".format(str(label).upper(), str(value))
        while text and cv2.getTextSize(text, font, font_scale, thickness)[0][0] > text_width:
            text = text[:-2] + "…"
        cv2.putText(
            image, text, (x0 + 26, baseline),
            font, font_scale, (225, 232, 240), thickness, cv2.LINE_AA,
        )
    return image


def _draw_avis_road_rule_debug(
    image, perception, *, frame_source="camera", command=None, sensor_frame=None,
    mode="avis", vision_profile="city",
):
    """Draw bounded road-rule geometry and a single structured AVIS HUD."""
    if not isinstance(image, np.ndarray) or image.size == 0:
        return image
    perception = perception if isinstance(perception, dict) else {}
    behavior = perception.get("simulation_behavior")
    behavior = behavior if isinstance(behavior, dict) else {}

    if frame_source == "camera":
        for detection in behavior.get("traffic_light_detections", []):
            if not isinstance(detection, dict):
                continue
            center = detection.get("center")
            try:
                x = int(round(float(center[0])))
                y = int(round(float(center[1])))
                radius = max(5, int(round(float(detection.get("radius", 6.0)))))
                if not (0 <= x < image.shape[1] and 0 <= y < image.shape[0]):
                    continue
            except (TypeError, ValueError, IndexError, OverflowError):
                continue
            color_name = str(detection.get("color", "UNKNOWN")).upper()
            color = (
                (0, 0, 220) if color_name == "RED"
                else (40, 190, 80) if color_name == "GREEN"
                else (0, 175, 220)
            )
            cv2.rectangle(
                image, (max(0, x - radius), max(0, y - radius)),
                (min(image.shape[1] - 1, x + radius), min(image.shape[0] - 1, y + radius)),
                color, 2, cv2.LINE_AA,
            )

        stop_line = behavior.get("stop_line_detection")
        if isinstance(stop_line, dict) and stop_line.get("detected"):
            bbox = stop_line.get("bbox")
            try:
                x, y, box_width, box_height = [
                    int(round(float(value))) for value in bbox
                ]
                if box_width > 0 and box_height > 0:
                    cv2.rectangle(
                        image, (max(0, x), max(0, y)),
                        (min(image.shape[1] - 1, x + box_width),
                         min(image.shape[0] - 1, y + box_height)),
                        (0, 165, 255), 2, cv2.LINE_AA,
                    )
            except (TypeError, ValueError, IndexError, OverflowError):
                pass

    lane_type = str(perception.get("lane_type", "none")).upper()
    lane_valid = bool(perception.get("perception_valid", False))
    speed = getattr(sensor_frame, "speed_kmh", None) if sensor_frame is not None else None
    try:
        speed_text = "{:.1f} km/h".format(float(speed))
    except (TypeError, ValueError, OverflowError):
        speed_text = "unavailable"
    if command is not None:
        steering_text = "{:+.0f}%".format(float(command.steering) * 100.0)
        control_state = (
            "STOP" if float(command.brake) >= 0.5
            else "REVERSE" if float(command.throttle) < 0
            else "DRIVE"
        )
        control_reason = str(getattr(command, "reason", "") or "no command")
    else:
        steering_text, control_state, control_reason = "unavailable", "UNKNOWN", "no actuator command"

    crosswalk_detected = bool(perception.get("crosswalk"))
    route_state = str(behavior.get("crosswalk_state") or "idle").upper()
    route_name = str(behavior.get("crosswalk_route") or "—").upper()
    route_sign = str(behavior.get("crosswalk_sign") or "NO SIGN").upper()
    route_step = int(behavior.get("crosswalk_step", 0) or 0)
    route_total = int(behavior.get("crosswalk_steps", 0) or 0)
    route_text = "{} ← {} · {} {}/{}".format(route_name, route_sign, route_state, route_step, route_total)
    if route_state == "BRAKING":
        detected = int(behavior.get("crosswalk_detection_frames", 0) or 0)
        required = int(behavior.get("crosswalk_detection_required", 3) or 3)
        route_text += " · confirming {}/{}".format(detected, required)
    elif route_state in {"STOPPING", "HOLDING"}:
        measured_speed = behavior.get("crosswalk_measured_speed_kmh")
        speed_text = (
            "{:.1f} km/h".format(float(measured_speed))
            if measured_speed is not None else "speed unavailable"
        )
        stop_count = int(behavior.get("crosswalk_stop_confirm_count", 0) or 0)
        stop_required = int(behavior.get("crosswalk_stop_confirm_required", 3) or 3)
        route_text += " · {} · stopped {}/{}".format(
            speed_text, stop_count, stop_required
        )
    elif route_state == "WAITING_FOR_GREEN":
        if not behavior.get("traffic_light_enabled"):
            route_text += " · traffic-light detector DISABLED"
        else:
            green_count = int(behavior.get("crosswalk_green_count", 0) or 0)
            green_required = int(behavior.get("crosswalk_green_required", 0) or 0)
            observations = int(behavior.get("crosswalk_green_observations", 0) or 0)
            window = int(behavior.get("crosswalk_green_window", 0) or 0)
            route_text += " · green {}/{} ({}/{})".format(
                green_count, green_required, observations, window
            )
    if route_state == "BLOCKED":
        route_text = "BLOCKED · " + str(behavior.get("crosswalk_reason") or "route unavailable")

    light_enabled = bool(behavior.get("traffic_light_enabled", False))
    light_color = str(behavior.get("traffic_light") or "UNKNOWN").upper()
    light_text = (
        light_color + (" · HOLD" if behavior.get("traffic_light_hold") else "")
        + (
            " · CROSSWALK GATE {}/{}".format(
                int(behavior.get("crosswalk_green_count", 0) or 0),
                int(behavior.get("crosswalk_green_required", 0) or 0),
            )
            if behavior.get("crosswalk_waiting_for_green") else ""
        )
        if light_enabled else "DISABLED"
    )
    stop_enabled = bool(behavior.get("stop_line_enabled", False))
    stop_detection = behavior.get("stop_line_detection")
    stop_detected = bool(isinstance(stop_detection, dict) and stop_detection.get("detected"))
    stop_text = (
        "WAITING" if behavior.get("stop_line_waiting")
        else "DETECTED" if stop_detected else "CLEAR"
    ) if stop_enabled else "DISABLED"

    deadlock_enabled = bool(behavior.get("deadlock_enabled", False))
    deadlock_state = str(behavior.get("deadlock_state") or "idle").upper()
    deadlock_candidate = str(behavior.get("deadlock_candidate") or "—").upper()
    deadlock_frames = int(behavior.get("deadlock_confirmation_frames", 0) or 0)
    deadlock_required = int(behavior.get("deadlock_confirmation_required", 4) or 4)
    deadlock_diag = behavior.get("deadlock_diagnostics")
    deadlock_diag = deadlock_diag if isinstance(deadlock_diag, dict) else {}
    deadlock_cw = int(deadlock_diag.get("crosswalk_horizontal_lines", 0) or 0)
    deadlock_cw_required = int(deadlock_diag.get("required_horizontal_lines", 1) or 1)
    deadlock_ml = int(deadlock_diag.get("left_lane_lines", 0) or 0)
    deadlock_mr = int(deadlock_diag.get("right_lane_lines", 0) or 0)
    deadlock_text = (
        "{} · {} {}/{} · CW H {}/{} · ML {} / MR {}".format(
            deadlock_state, deadlock_candidate, deadlock_frames, deadlock_required,
            deadlock_cw, deadlock_cw_required, deadlock_ml, deadlock_mr,
        )
        if deadlock_enabled else "DISABLED"
    )
    deadlock_color = (
        (0, 205, 240) if deadlock_state in {"RUNNING", "BLOCKED"} or deadlock_frames else
        (40, 190, 80) if deadlock_enabled else (105, 120, 138)
    )

    rows = [
        ("MODE", str(mode).upper() + " / " + str(vision_profile).upper(), (0, 175, 220)),
        ("LANE", lane_type + (" · VALID" if lane_valid else " · INVALID"),
         (40, 190, 80) if lane_valid else (0, 165, 255)),
        ("STEER / SPEED", steering_text + " · " + speed_text, (190, 205, 220)),
        ("CROSSWALK", "DETECTED" if crosswalk_detected else "CLEAR",
         (0, 205, 240) if crosswalk_detected else (105, 120, 138)),
        ("ROUTE", route_text,
         (0, 205, 240) if route_state in {"BRAKING", "STOPPING", "HOLDING", "WAITING_FOR_GREEN", "RUNNING"} else
         (0, 165, 255) if route_state == "BLOCKED" else (105, 120, 138)),
        ("TRAFFIC LIGHT", light_text,
         (0, 0, 220) if light_color == "RED" else
         (40, 190, 80) if light_color == "GREEN" else (105, 120, 138)),
        ("STOP LINE", stop_text,
         (0, 165, 255) if stop_text in {"WAITING", "DETECTED"} else (105, 120, 138)),
        ("DEADLOCK", deadlock_text, deadlock_color),
        ("CONTROL", control_state + " · " + control_reason,
         (0, 165, 255) if control_state == "STOP" else (40, 190, 80)),
    ]
    return _draw_simulation_debug_panel(image, "AVIS CITY · DIAGNOSTICS", rows)


def _draw_generic_simulation_debug(image, perception, command, sensor_frame, mode, vision_profile):
    """Use the same typography and placement for CARLA and other simulator modes."""
    lane_type = str(perception.get("lane_type", "none")).upper()
    lane_valid = bool(perception.get("perception_valid", False))
    speed = getattr(sensor_frame, "speed_kmh", 0.0)
    try:
        speed_text = "{:.1f} km/h".format(float(speed))
    except (TypeError, ValueError, OverflowError):
        speed_text = "unavailable"
    control_state = (
        "STOP" if float(command.brake) >= 0.5
        else "REVERSE" if float(command.throttle) < 0
        else "DRIVE"
    )
    rows = [
        ("MODE", str(mode).upper() + " / " + str(vision_profile).upper(), (0, 175, 220)),
        ("LANE", lane_type + (" · VALID" if lane_valid else " · INVALID"),
         (40, 190, 80) if lane_valid else (0, 165, 255)),
        ("STEER / SPEED", "{:+.0f}% · {}".format(float(command.steering) * 100.0, speed_text),
         (190, 205, 220)),
        ("CROSSWALK", "DETECTED" if perception.get("crosswalk") else "CLEAR",
         (0, 205, 240) if perception.get("crosswalk") else (105, 120, 138)),
        ("CONTROL", control_state + " · " + str(getattr(command, "reason", "") or "no command"),
         (0, 165, 255) if control_state == "STOP" else (40, 190, 80)),
    ]
    return _draw_simulation_debug_panel(image, "SIMULATOR · DIAGNOSTICS", rows)
def _apply_forward_range_guard(command, ranges, *, backend, stop_distance_cm):
    """Apply the independent forward-range safety guard.

    AVIS has no verified separate brake channel: a stop is represented by a
    zero-speed command. Missing/invalid AVIS front telemetry therefore fails
    closed instead of allowing lane-following throttle to continue.
    """
    backend = str(backend or "").lower()
    ranges = ranges if isinstance(ranges, dict) else {}
    raw_front = ranges.get("front")
    try:
        front = float(raw_front)
        if isinstance(raw_front, bool) or not math.isfinite(front) or front < 0:
            front = None
    except (TypeError, ValueError, OverflowError):
        front = None

    try:
        configured_threshold = float(stop_distance_cm)
        if not math.isfinite(configured_threshold):
            raise ValueError("non-finite stop threshold")
    except (TypeError, ValueError, OverflowError):
        configured_threshold = 60.0 if backend == "avis" else 35.0

    if backend == "avis":
        threshold = max(20.0, configured_threshold)
        if front is None:
            reason = "AVIS front range sensor missing/invalid; temporary safety brake"
            status = "sensor_unavailable"
        elif front <= threshold:
            reason = f"forward range {front:.1f} cm at/below {threshold:.1f} cm; AVIS safety stop"
            status = "obstacle_detected"
        else:
            return command, {
                "status": "clear", "front_range_cm": front,
                "threshold_cm": threshold, "reason": "front range above emergency-stop threshold",
            }
        safe = VehicleCommand(
            steering=command.steering, throttle=0.0, brake=1.0,
            servo_angle=command.servo_angle, target_speed=0.0, reason=reason,
        )
        return safe, {
            "status": status, "front_range_cm": front,
            "threshold_cm": threshold, "reason": reason,
        }

    threshold = configured_threshold
    if threshold <= 0 or front is None:
        return command, {
            "status": "disabled" if threshold <= 0 else "unavailable",
            "front_range_cm": front, "threshold_cm": threshold,
            "reason": "forward range guard is disabled or no front range is supplied",
        }
    if front <= threshold:
        reason = f"forward range {front:.1f} cm at/below {threshold:.1f} cm; simulator braking"
        safe = VehicleCommand(
            steering=command.steering, throttle=0.0, brake=1.0,
            servo_angle=command.servo_angle, target_speed=0.0, reason=reason,
        )
        return safe, {
            "status": "obstacle_detected", "front_range_cm": front,
            "threshold_cm": threshold, "reason": reason,
        }
    return command, {
        "status": "clear", "front_range_cm": front,
        "threshold_cm": threshold, "reason": "front range above stop threshold",
    }


class SimulationRuntime:
    @staticmethod
    def _should_auto_start_without_stream(config, backend):
        """AVIS has no Start button without Stream, so arm it on process launch."""
        return (
            str(backend or "").strip().lower() == "avis"
            and not bool(getattr(config, "STREAM", False))
        )

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
        self.avis_behaviors = (
            AVISBehaviorCoordinator(config, self.vision_profile)
            if self.backend == "avis" else None
        )
        self.shutdown_event = getattr(config, "SHUTDOWN_EVENT", None)
        if self.shutdown_event is None:
            self.shutdown_event = threading.Event()
        self.target_fps = float(getattr(config, "TARGET_PROCESSING_FPS", DEFAULT_TARGET_FPS))
        self._frame_period = 1.0 / max(1.0, self.target_fps)
        # Stream is a diagnostics preview, not part of the vehicle control loop.
        try:
            stream_render_fps = float(getattr(config, "STREAM_RENDER_FPS", 8.3))
        except (TypeError, ValueError, OverflowError):
            stream_render_fps = 8.3
        if not math.isfinite(stream_render_fps):
            stream_render_fps = 8.3
        self._stream_frame_period = 1.0 / max(1.0, min(8.3, stream_render_fps))
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
        self._last_range_safety = {"status": "waiting", "reason": "waiting for the first front-range sample"}
        self._front_range_unavailable_since = None
        self._front_range_grace_notified = False
        self._last_command = self.controller.last_command
        self._last_error = None
        self._fatal_runtime_error = None
        self._last_event_key = None
        self._last_cycle_at = None
        self._stop_event_active = False
        self._last_safe_stop_command_at = 0.0
        self._last_safe_stop_log_at = 0.0
        self._last_safe_stop_reason = None
        self._camera_editor_active = False
        self._scene_edit_active = False
        # AVIS has no Start/Stop controls when Stream is disabled. In that
        # headless mode, arm the initial run automatically; Stream-enabled AVIS
        # and CARLA retain the explicit Start Run interlock.
        self._run_enabled = self._should_auto_start_without_stream(
            config, self.backend
        )
        if self._run_enabled:
            self._record_event(
                "info",
                "AVIS autonomous run auto-armed because Stream is disabled; "
                "sensor, perception and range safety stops remain active.",
            )
        self._last_image_diagnostics = {}
        self._cycle_times = deque(maxlen=120)
        self._detection_times_ms = deque(maxlen=120)
        self._debug_render_times_ms = deque(maxlen=120)
        self._last_detection_ms = 0.0
        self._last_control_ms = 0.0
        self._last_debug_render_ms = 0.0
        self._camera_frames_skipped = 0
        # Debug rendering has its own latest-frame worker. It must never hold
        # the camera -> detection -> control loop hostage.
        self._visual_condition = threading.Condition()
        self._visual_pending = None
        self._visual_stopping = False
        self._visual_thread = None
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
                servo_min=getattr(config, "MIN_SERVO_ANGLE", 55),
                servo_max=getattr(config, "MAX_SERVO_ANGLE", 125),
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
        render_started = time.perf_counter()
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
        image_diagnostics = {
            "width": int(display.shape[1]),
            "height": int(display.shape[0]),
            "mean_intensity": round(float(np.mean(sample)), 2) if sample.size else 0.0,
            "max_intensity": int(np.max(sample)) if sample.size else 0,
            "source": frame_source,
            "looks_black": bool(not sample.size or float(np.mean(sample)) < 1.0 or int(np.max(sample)) < 4),
        }
        with self._state_lock:
            self._last_image_diagnostics = image_diagnostics
        draw_data = debug.get("draw_data") if isinstance(debug, dict) else None
        if isinstance(draw_data, dict):
            draw_data = dict(draw_data)
            draw_data["suppress_labels"] = True
            lane_tracking = draw_data.get("lane_tracking")
            if isinstance(lane_tracking, dict):
                draw_data["lane_tracking"] = dict(lane_tracking)
                draw_data["lane_tracking"]["suppress_labels"] = True
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
        if self.backend == "avis":
            display = _draw_avis_road_rule_debug(
                display, perception, frame_source=frame_source, command=command,
                sensor_frame=sensor_frame, mode=self.mode, vision_profile=self.vision_profile,
            )
        else:
            display = _draw_generic_simulation_debug(
                display, perception, command, sensor_frame, self.mode, self.vision_profile
            )
        with self.frame_lock:
            self.config.debug_frames_list = [None, display]
            self.config.stream_frame_seq = int(getattr(self.config, "stream_frame_seq", 0)) + 1
        elapsed_ms = (time.perf_counter() - render_started) * 1000.0
        with self._state_lock:
            self._last_debug_render_ms = elapsed_ms
            self._debug_render_times_ms.append(elapsed_ms)

    def _queue_frame_for_stream(self, sensor_frame, perception, command):
        """Queue the newest annotated frame without blocking vehicle control."""
        with self._visual_condition:
            # Keep the newest frame while the renderer is busy or rate-limited.
            was_empty = self._visual_pending is None
            self._visual_pending = (sensor_frame, perception, command)
            if was_empty:
                self._visual_condition.notify()

    def _visualization_loop(self):
        next_render_at = 0.0
        while True:
            with self._visual_condition:
                while self._visual_pending is None and not self._visual_stopping:
                    self._visual_condition.wait()
                if self._visual_pending is None and self._visual_stopping:
                    return
                while self._visual_pending is not None and not self._visual_stopping:
                    remaining = next_render_at - time.monotonic()
                    if remaining <= 0.0:
                        break
                    self._visual_condition.wait(timeout=remaining)
                if self._visual_pending is None and self._visual_stopping:
                    return
                item = self._visual_pending
                self._visual_pending = None
            render_started = time.monotonic()
            try:
                self._publish_frame(*item)
            except Exception:
                logger.exception("Could not render/publish simulator lane-debug frame")
            finally:
                next_render_at = render_started + self._stream_frame_period

    def _start_visualization_worker(self):
        with self._visual_condition:
            if self._visual_thread is not None and self._visual_thread.is_alive():
                return
            self._visual_stopping = False
            self._visual_thread = threading.Thread(
                target=self._visualization_loop,
                name="simulator-debug-render",
                daemon=True,
            )
            self._visual_thread.start()

    def _stop_visualization_worker(self):
        with self._visual_condition:
            self._visual_stopping = True
            self._visual_condition.notify_all()
            thread = self._visual_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        with self._visual_condition:
            self._visual_thread = None
            self._visual_pending = None

    @staticmethod
    def _recent_rate(samples, now, window_seconds=2.0):
        recent = [value for value in samples if now - value <= window_seconds]
        if len(recent) < 2:
            return 0.0
        elapsed = recent[-1] - recent[0]
        return (len(recent) - 1) / elapsed if elapsed > 0 else 0.0

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

    def _adapter_control_ready(self):
        if not bool(getattr(self.adapter, "connected", False)):
            return False
        readiness = getattr(self.adapter, "control_ready", None)
        return bool(readiness()) if callable(readiness) else True

    def set_run_enabled(self, enabled):
        """Arm/disarm autonomous motion on CARLA or AVIS.

        Reconnection is independent of run arming: the operator must press Start
        again after any AVIS link loss or simulator reset.
        """
        if self._fatal_runtime_error is not None:
            raise RuntimeError(
                "Simulation runtime has stopped after an internal error; restart the "
                "simulation process before enabling motion."
            )
        enabled = bool(enabled)
        if enabled == self._run_enabled:
            return self._run_enabled
        if enabled:
            if self.backend == "carla" and (self._camera_editor_active or self._scene_edit_active):
                raise RuntimeError("Close the CARLA camera/scene editor before starting autonomous run.")
            if not self._adapter_control_ready():
                label = "CARLA vehicle" if self.backend == "carla" else "AVIS connection"
                raise RuntimeError(label + " is not ready; wait for reconnection before starting.")
            self._run_enabled = True
            self._front_range_unavailable_since = None
            self._front_range_grace_notified = False
            self._last_error = None
            self._stop_event_active = False
            self._record_event("info", self.backend.upper() + " autonomous run enabled by an explicit Stream Start command.")
        else:
            self._run_enabled = False
            stop_vehicle = getattr(self.adapter, "stop_vehicle", None) if self.backend == "avis" else None
            stopped = False
            if callable(stop_vehicle):
                try:
                    stopped = bool(stop_vehicle())
                except Exception:
                    logger.error("Explicit AVIS stop command failed; falling back to zero-throttle safety control", exc_info=True)
            if stopped:
                self._last_command = VehicleCommand(
                    steering=0.0, throttle=0.0, brake=1.0,
                    servo_angle=self.controller.last_servo, target_speed=0.0,
                    reason="AVIS Engine explicit stop command sent.",
                )
                self._stop_event_active = True
                self._last_safe_stop_command_at = time.monotonic()
            else:
                self._safe_stop(self.backend.upper() + " run stopped; waiting for an explicit Start Run command.")
            self._last_error = None
            self._record_event("info", self.backend.upper() + " autonomous run disabled; explicit stop requested.")
        return self._run_enabled

    def _latch_avis_range_stop(self, now=None):
        """Disarm for a confirmed obstacle or a sustained front-sensor outage.

        A missing sample still produces an immediate brake in
        _apply_forward_range_guard. Brief telemetry gaps keep the Engine
        session armed so a valid next sample can safely resume control.
        """
        if self.backend != "avis":
            return False
        status = str(self._last_range_safety.get("status", ""))
        if status == "clear":
            self._front_range_unavailable_since = None
            self._front_range_grace_notified = False
            self._last_range_safety.pop("unavailable_for_seconds", None)
            self._last_range_safety.pop("invalid_grace_seconds", None)
            return False
        if status not in {"sensor_unavailable", "obstacle_detected"} or not self._run_enabled:
            return False

        now = time.monotonic() if now is None else float(now)
        reason = str(self._last_range_safety.get("reason", "AVIS forward range safety fault"))
        if status == "sensor_unavailable":
            if self._front_range_unavailable_since is None:
                self._front_range_unavailable_since = now
                self._front_range_grace_notified = False
            unavailable_for = max(0.0, now - self._front_range_unavailable_since)
            try:
                grace = float(getattr(
                    self.config, "SIMULATOR_AVIS_FRONT_RANGE_INVALID_GRACE_SECONDS", 1.5
                ))
            except (TypeError, ValueError, OverflowError):
                grace = 1.5
            if not math.isfinite(grace):
                grace = 1.5
            grace = max(0.0, min(10.0, grace))
            self._last_range_safety["unavailable_for_seconds"] = unavailable_for
            self._last_range_safety["invalid_grace_seconds"] = grace
            if unavailable_for < grace:
                if not self._front_range_grace_notified:
                    tag_state = (
                        "present" if self._last_range_safety.get("sensor_tag_present")
                        else "absent/unknown"
                    )
                    count = self._last_range_safety.get("range_sensor_count", "unknown")
                    self._record_event(
                        "warning",
                        f"AVIS front range telemetry is unavailable (sensor tag {tag_state}, "
                        f"{count} readings); braking this frame and waiting up to "
                        f"{grace:.1f}s for valid range data before disarming the run.",
                    )
                    self._front_range_grace_notified = True
                return False
            reason += (
                f"; front-range telemetry stayed unavailable for {unavailable_for:.1f}s "
                f"(configured grace {grace:.1f}s elapsed)"
            )
        else:
            # A positive near-range reading is a confirmed forward hazard;
            # never apply the telemetry grace period to a real obstacle.
            self._front_range_unavailable_since = None
            self._front_range_grace_notified = False

        self._record_event(
            "warning",
            reason + "; issuing AVIS Engine stop and disarming autonomous run.",
        )
        self.set_run_enabled(False)
        self._last_range_safety["stop_latched"] = True
        return True

    def request_reconnect(self):
        """Force an AVIS socket reconnect while keeping the vehicle disarmed."""
        if self.backend != "avis":
            raise RuntimeError("Manual reconnect is available only for AVIS Engine modes.")
        self.set_run_enabled(False)
        callback = getattr(self.adapter, "request_reconnect", None)
        if not callable(callback):
            raise RuntimeError("The active AVIS adapter does not support reconnect requests.")
        result = callback()
        self._record_event("info", "AVIS reconnect requested; autonomous run remains STOPPED.")
        return result

    def set_camera_editor_active(self, active):
        """Hold the CARLA vehicle while the user is positioning the camera."""
        active = bool(active)
        if active == self._camera_editor_active:
            return
        self._camera_editor_active = active
        if active:
            self.set_run_enabled(False)
            self._safe_stop("CARLA camera editor is open; holding vehicle stationary.")
            self._last_error = None
            self._record_event("info", "Camera placement studio active; CARLA run is disarmed.")
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
            self._last_error = None
            self._record_event("info", "CARLA scene change started; autonomous throttle is suspended.")
        else:
            self._record_event("info", "CARLA scene change finished; CARLA remains STOPPED until Start Run is pressed.")

    def _carla_vehicle_ready(self):
        if self.backend != "carla":
            return True
        readiness = getattr(self.adapter, "control_ready", None)
        return bool(readiness()) if callable(readiness) else True

    def _safe_stop(self, reason, *, level="warning", set_error=True):
        if set_error:
            self._last_error = str(reason)
        now = time.monotonic()
        # Expected startup/waiting/STOPPED states remain visible without being
        # mislabeled as warnings or ordinary runtime errors.
        reason_changed = reason != self._last_safe_stop_reason
        if reason_changed or now - self._last_safe_stop_log_at >= 30.0:
            self._record_event(level, reason)
            self._last_safe_stop_reason = reason
            self._last_safe_stop_log_at = now
        # Repeated stops are rate-limited, but a new safety reason must issue
        # an immediate brake command instead of being hidden by the prior one.
        if not reason_changed and now - self._last_safe_stop_command_at < 0.5:
            return
        self._last_safe_stop_command_at = now
        safe = VehicleCommand(
            steering=self._last_command.steering if self._last_command else 0.0,
            throttle=0.0, brake=1.0,
            servo_angle=self.controller.last_servo, target_speed=0.0, reason=reason,
        )
        try:
            self.adapter.apply_control(safe)
        except Exception as exc:
            self._last_error = "Virtual safe-stop command failed: " + str(exc)
            self._record_event("error", self._last_error)
            logger.error("Virtual safe-stop command failed", exc_info=True)
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
            camera_sensor = {}
            camera_diag = getattr(self.adapter, "camera_diagnostics", None)
            if callable(camera_diag):
                try:
                    camera_sensor = camera_diag() or {}
                except Exception:
                    logger.debug("Could not read simulator camera diagnostics", exc_info=True)
            image_diagnostics = dict(self._last_image_diagnostics)
            cycle_times = list(self._cycle_times)
            detection_times = list(self._detection_times_ms)
            debug_render_times = list(self._debug_render_times_ms)
            processing_data = {
                "target_fps": float(self.target_fps),
                "lane_fps": round(self._recent_rate(cycle_times, now), 1),
                "detection_ms": round(float(self._last_detection_ms), 1),
                "detection_ms_avg": round(sum(detection_times) / len(detection_times), 1) if detection_times else 0.0,
                "control_ms": round(float(self._last_control_ms), 1),
                "debug_render_ms": round(float(self._last_debug_render_ms), 1),
                "debug_render_ms_avg": round(sum(debug_render_times) / len(debug_render_times), 1) if debug_render_times else 0.0,
                "camera_frames_skipped": int(self._camera_frames_skipped),
            }
            if not image_diagnostics and camera_sensor.get("width"):
                image_diagnostics = {
                    "width": camera_sensor.get("width"),
                    "height": camera_sensor.get("height"),
                    "mean_intensity": camera_sensor.get("mean_intensity"),
                    "max_intensity": camera_sensor.get("max_intensity"),
                    "source": "camera callback",
                    "looks_black": bool(camera_sensor.get("looks_black", False)),
                }
            encoder = {"available": True, "pulses": int(self._encoder_pulses),
                       "delta": int(self._encoder_delta), "distance_cm": round(self._last_distance_cm, 2),
                       "source": "simulated travel estimate; not hardware ground truth"}
            range_sensor_status = (
                dict(getattr(frame, "sensor_status", {}) or {}) if frame is not None else {}
            )
            sensor_data = {
                "speed_kmh": speed, "ranges_cm": ranges,
                "range_sensor_status": range_sensor_status,
                "range_safety": dict(self._last_range_safety),
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
                "image": image_diagnostics,
                "camera_sensor": camera_sensor,
                "processing": processing_data,
                "running": self._started_at is not None and not self.shutdown_event.is_set(),
                "frame_sequence": int(getattr(frame, "sequence", 0)) if frame is not None else 0,
                "frame_age_ms": round(age_ms, 1) if age_ms is not None else None,
                "lane_type": str(result.get("lane_type", "none")),
                "perception_valid": bool(result.get("perception_valid", False)),
                "line_tracking": result.get("line_tracking", {"enabled": False, "state": "DISABLED"}),
                "simulation_behavior": (
                    self.avis_behaviors.snapshot() if self.avis_behaviors is not None else {}
                ),
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
                "runtime_faulted": self._fatal_runtime_error is not None,
            }

    def run(self):
        try:
            connection_retries = 0
            retry_delay_s = 0.5
            last_retry_log_at = None
            while not self.shutdown_event.is_set():
                try:
                    connected = self.adapter.connect()
                    if self.backend == "avis" and connected is False:
                        detail = getattr(self.adapter, "_last_error", None) or "connection refused"
                        raise ConnectionError(str(detail))
                    break
                except Exception as exc:
                    if self.backend != "avis":
                        raise
                    self._last_error = f"{type(exc).__name__}: {exc}"
                    message = "AVIS Engine is not available yet; retrying with backoff: " + str(exc)
                    self._record_event("info", message, log=False)
                    now = time.monotonic()
                    # A simulator that is still starting is a normal transient
                    # condition. Keep one concise status line, never a traceback
                    # for each retry; the Stream retains the latest detail.
                    if last_retry_log_at is None or now - last_retry_log_at >= 30.0:
                        logger.info("%s", message)
                        last_retry_log_at = now
                    connection_retries += 1
                    if self.shutdown_event.wait(retry_delay_s):
                        return
                    retry_delay_s = min(5.0, retry_delay_s * 2.0)
            if self.shutdown_event.is_set():
                return
            self._last_error = None
            self._start_visualization_worker()
            self._started_at = time.monotonic()
            self._stop_event_active = False
            connected_message = f"Connected {self.backend}; {self.vision_profile} vision processor loaded."
            if connection_retries:
                connected_message += f" (after {connection_retries} connection retries)"
            self._record_event("info", connected_message)
            self._safe_stop(
                self.backend.upper() + " connected in STOPPED mode; press Start Run to enable autonomy.",
                level="info", set_error=False,
            )
            while not self.shutdown_event.is_set():
                frame = self.adapter.read(timeout=0.25)
                now = time.monotonic()
                if frame is None:
                    if self.backend == "avis":
                        camera_diag = {}
                        camera_diag_fn = getattr(self.adapter, "camera_diagnostics", None)
                        if callable(camera_diag_fn):
                            try:
                                camera_diag = camera_diag_fn() or {}
                            except Exception:
                                logger.debug("Could not read AVIS camera diagnostics", exc_info=True)
                        adapter_error = camera_diag.get("last_error")
                        if adapter_error:
                            self._last_error = str(adapter_error)
                        elif bool(getattr(self.adapter, "connected", False)):
                            self._last_error = None

                        if not bool(getattr(self.adapter, "connected", False)):
                            if self._run_enabled:
                                self._run_enabled = False
                                recovery_action = (
                                    "restart the AVIS process after camera frames return; "
                                    "this run has no Stream controls."
                                    if not bool(getattr(self.config, "STREAM", False))
                                    else "press Start after camera frames return."
                                )
                                self._record_event(
                                    "info",
                                    "AVIS link lost; autonomy disarmed. " + recovery_action,
                                )
                            stop_reason = "AVIS camera link is reconnecting; vehicle braked and run disarmed."
                        else:
                            stop_reason = (
                                "AVIS TCP is connected but no decodable camera frame is available; "
                                "holding the vehicle stopped while waiting for a valid frame."
                            )
                            missing_count = int(camera_diag.get("missing_images", 0) or 0)
                            missing_age = float(camera_diag.get("missing_image_duration_s") or 0.0)
                            if self._run_enabled and missing_count >= 30 and missing_age >= 5.0:
                                self._run_enabled = False
                                recovery_action = (
                                    "restart the AVIS process after the camera stream is healthy; "
                                    "this run has no Stream controls."
                                    if not bool(getattr(self.config, "STREAM", False))
                                    else "an explicit Start Run command is required."
                                )
                                self._record_event(
                                    "error",
                                    "AVIS camera stream stayed unavailable for at least 5 seconds; "
                                    "autonomy was disarmed and " + recovery_action,
                                    log=False,
                                )
                        self._safe_stop(stop_reason, level="info", set_error=False)
                    else:
                        self._safe_stop("No fresh simulator camera frame; braking until frames resume.")
                    self.shutdown_event.wait(0.05)
                    continue
                if frame.sequence and frame.sequence == self._last_sequence:
                    continue
                if frame.sequence and self._last_sequence and frame.sequence > self._last_sequence + 1:
                    with self._state_lock:
                        self._camera_frames_skipped += frame.sequence - self._last_sequence - 1
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
                    self._queue_frame_for_stream(frame, self._last_result, self._last_command)
                    self.shutdown_event.wait(0.05)
                    continue
                if self.avis_behaviors is not None:
                    # Prepare the requested temporary lane ROI before processing this frame.
                    self.avis_behaviors.prepare_vision(now=now)
                detection_started = time.perf_counter()
                result = self.vision.detect(frame.image)
                detection_ms = (time.perf_counter() - detection_started) * 1000.0
                if not isinstance(result, dict):
                    result = {}
                command = self.controller.command_for(result, frame.speed_kmh)
                if self.avis_behaviors is not None:
                    self.avis_behaviors.submit_sign_frame(frame)
                    command = self.avis_behaviors.apply(
                        frame, result, command,
                        distance_delta_cm=getattr(frame, "distance_delta_cm", 0.0),
                        now=now,
                    )
                    command = self.avis_behaviors.approach_speed.apply(
                        frame, command, now=now
                    )
                    result["simulation_behavior"] = self.avis_behaviors.snapshot()
                obstacle_limit = getattr(
                    self.config, "SIMULATOR_OBSTACLE_STOP_DISTANCE_CM",
                    60.0 if self.backend == "avis" else 35.0,
                )
                ranges = dict(getattr(frame, "ranges_cm", {}) or {})
                command, self._last_range_safety = _apply_forward_range_guard(
                    command, ranges, backend=self.backend,
                    stop_distance_cm=obstacle_limit,
                )
                if self.backend == "avis":
                    sensor_status = dict(getattr(frame, "sensor_status", {}) or {})
                    self._last_range_safety.update({
                        "sensor_tag_present": sensor_status.get("sensor_tag_present"),
                        "range_sensor_count": sensor_status.get("range_sensor_count"),
                        "front_range_available": sensor_status.get(
                            "front_range_available", ranges.get("front") is not None
                        ),
                    })
                if self._latch_avis_range_stop():
                    # The Engine stop token closes the active control session.
                    # Motion requires a fresh Start click after reconnect.
                    self.shutdown_event.wait(0.05)
                    continue
                if (self.backend != "avis" and self.vision_profile == "city" and bool(result.get("crosswalk", False))
                        and bool(getattr(self.config, "SIMULATOR_STOP_ON_CROSSWALK", True))):
                    command = VehicleCommand(
                        steering=command.steering, throttle=0.0, brake=1.0,
                        servo_angle=command.servo_angle, target_speed=0.0,
                        reason="crosswalk detected; simulator braking",
                    )
                if not self._run_enabled:
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
                control_started = time.perf_counter()
                control_accepted = self.adapter.apply_control(command)
                control_ms = (time.perf_counter() - control_started) * 1000.0
                if not control_accepted:
                    # CARLA actors can disappear during world changes.
                    if self.backend == "carla" and not self._carla_vehicle_ready():
                        self._last_command = VehicleCommand(
                            steering=command.steering, throttle=0.0, brake=1.0,
                            servo_angle=command.servo_angle, target_speed=0.0,
                            reason="CARLA vehicle actor is temporarily unavailable; waiting for scene recovery.",
                        )
                        self.shutdown_event.wait(0.05)
                        continue
                    if self.backend == "avis":
                        self._run_enabled = False
                        self._safe_stop("AVIS actuator link failed; reconnecting while remaining STOPPED.")
                        self.shutdown_event.wait(0.1)
                        continue
                    raise RuntimeError("simulator adapter did not accept the virtual actuator command")
                self._last_command = command
                self._last_result = result
                self._last_error = None
                self._stop_event_active = False
                self._update_virtual_encoder(frame, command, now)
                self._record_command_if_changed(result, command)
                with self._state_lock:
                    self._last_detection_ms = detection_ms
                    self._last_control_ms = control_ms
                    self._detection_times_ms.append(detection_ms)
                    self._cycle_times.append(time.monotonic())
                self._queue_frame_for_stream(frame, result, command)
                self._last_cycle_at = now
                self._next_cycle_at = max(self._next_cycle_at + self._frame_period, now)
                self.shutdown_event.wait(max(0.0, self._next_cycle_at - time.monotonic()))
        except KeyboardInterrupt:
            logger.info("Simulation interrupted; stopping vehicle")
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            self._fatal_runtime_error = self._last_error
            self._record_event("error", self._last_error)
            logger.exception("Simulation runtime failed")
            raise
        finally:
            self._started_at = None
            self._stop_visualization_worker()
            self._safe_stop(
                "Simulation runtime stopped; virtual vehicle commanded to brake.",
                level="info", set_error=False,
            )
            if self.avis_behaviors is not None:
                self.avis_behaviors.close()
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
        except Exception:
            if stream_thread is None or not stream_thread.is_alive():
                raise

            # Keep the diagnostics/control web server alive after a worker crash.
            # The runtime remains attached for read-only snapshots, while
            # set_run_enabled() rejects all motion commands in this faulted state.
            self._run_enabled = False
            self.config.simulation_runtime = self
            self.config.simulation_runtime_error = self._fatal_runtime_error or self._last_error
            logger.error(
                "Simulation worker stopped unexpectedly; Stream dashboard remains "
                "available for diagnostics. Restart the process before resuming motion."
            )
            try:
                while stream_thread.is_alive():
                    stream_thread.join(timeout=0.5)
            except KeyboardInterrupt:
                logger.info("Stream dashboard interrupted by operator")
        finally:
            if stream_thread is not None and stream_thread.is_alive():
                try:
                    stop_stream(self.config)
                except Exception:
                    logger.debug("Could not stop simulator dashboard", exc_info=True)
                stream_thread.join(timeout=1.0)
