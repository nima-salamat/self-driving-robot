import modes.race.config_race as config_race 

from utils.config_mode import set_race_mode
# set_race_mode()

from manager.output_manager import OutputManager
from vision.camera import Camera
from vision.race_vision_processing import VisionProcessor
from vision.apriltag import ApriltagDetector
from vision.object_detector import ObjectDetector
from traffic_sign_detector.svm_detector import TrafficSignDetector as SVMTrafficSignDetector
from traffic_sign_detector.yolo_detector import TrafficSignDetector as YOLOTrafficSignDetector
from traffic_sign_detector.async_detector import AsyncSignDetector
from traffic_sign_detector.stop_hold import StopSignHold
from controller import RobotController
from controller.odometry import EncoderOdometry
from controller.perception_confidence import PerceptionConfidenceEstimator, ConfidenceSpeedLimiter
from controller.adaptive_obstacle import AdaptiveObstaclePlanner
from modes.race.config_race import (
    SPEED, HARDCODE_SPEED, SERVO_CENTER,
    TURN_LEFT, TURN_RIGHT, STRAIGHT, STOP)
from stream import publish_debug_frame, start_stream, stop_stream
import logging
import cv2
import math
import numpy as np
import time
import threading
from utils.fps import FPS
from utils.roi_manager import crop_image

# Set to False to completely bypass sign and tag processing

logger = logging.getLogger(__name__)

# keep defaults (config_race can override)
OUTPUT_DIR = getattr(config_race, "OUTPUT_DIR", "output")
VIDEO_FPS = getattr(config_race, "VIDEO_FPS", 20)
VIDEO_CODEC = getattr(config_race, "VIDEO_CODEC", "mp4v")

if not hasattr(config_race, "debug_frames_list") or not isinstance(config_race.debug_frames_list, list):
    config_race.debug_frames_list = [None, None]

config_race.DEBUG = False


class Robot:
    def __init__(self):
        self.metrics = getattr(config_race, "runtime_metrics", None)
        self.health = getattr(config_race, "health_monitor", None)
        self.camera = Camera(config=config_race)
        self.control = RobotController(config=config_race)
        config_race.arduino_connection = self.control.connection
        config_race.robot_controller = self.control
        self.flask_thread = None
        self.runtime_exception = None
        self._next_control_time = time.monotonic()
        
        if getattr(config_race, "ENCODER_MAP_ENABLED", False) or getattr(config_race, "ADAPTIVE_OBSTACLE_AVOIDANCE_ENABLED", False):
            self.odometry = EncoderOdometry(
                config_race.ENCODER_PULSE_DISTANCE_CM,
                wheelbase_cm=config_race.ENCODER_WHEELBASE_CM,
                servo_center=self.control.servo_center,
                servo_min=self.control.min_servo_angle,
                servo_max=self.control.max_servo_angle,
                road_angle_min_deg=config_race.ENCODER_ROAD_ANGLE_MIN_DEG,
                road_angle_max_deg=config_race.ENCODER_ROAD_ANGLE_MAX_DEG,
            )
            if not self.control.request_encoder_telemetry():
                raise RuntimeError("Selected firmware did not acknowledge encoder telemetry ODOM1")
            self.control._encoder_telemetry_ready = True
            config_race.encoder_odometry = self.odometry
        else:
            self.odometry = None

        if getattr(config_race, "CONFIDENCE_AWARE_ENABLED", False):
            self.confidence_estimator = PerceptionConfidenceEstimator()
            self.confidence_limiter = ConfidenceSpeedLimiter(
                config_race.CONFIDENCE_SLOW_THRESHOLD,
                config_race.CONFIDENCE_STOP_THRESHOLD,
            )
            config_race.perception_confidence = None
        else:
            self.confidence_estimator = self.confidence_limiter = None

        if getattr(config_race, "ADAPTIVE_OBSTACLE_AVOIDANCE_ENABLED", False):
            if not self.control.request_adaptive_lane_mode(config_race.OBSTACLE_STOP_DISTANCE_CM):
                raise RuntimeError("Firmware did not acknowledge host-adaptive lane ownership")
            self.control._adaptive_mode_ready = True
            self.obstacle_planner = AdaptiveObstaclePlanner(
                config_race.OBSTACLE_TRIGGER_DISTANCE_CM,
                config_race.OBSTACLE_STOP_DISTANCE_CM,
                config_race.OBSTACLE_LANE_WIDTH_CM,
                config_race.OBSTACLE_ROBOT_WIDTH_CM,
                config_race.OBSTACLE_CLEARANCE_CM,
                servo_center=self.control.servo_center,
                servo_min=self.control.min_servo_angle,
                servo_max=self.control.max_servo_angle,
            )
            config_race.adaptive_reconnected = False
        else:
            self.obstacle_planner = None
            # Preserve legacy sequence configuration and EEPROM persistence.
            lane_width, robot_width, safe_margin, pulse_cm = 30, 12, 3, 0.5
            lateral_shift_cm = (lane_width / 2) - (robot_width / 2) + safe_margin
            theta_radians = math.radians(30)
            travel_pulse = int((lateral_shift_cm / math.sin(theta_radians)) / pulse_cm)
            # Preserve the checked-in legacy EEPROM sequence angles exactly.
            left_angle, right_angle = 60, 120
            cmd_avoid_left = f"f 230 {travel_pulse} {left_angle} f 230 {travel_pulse} {right_angle}"
            cmd_return_right = f"f 230 {travel_pulse} {right_angle} f 230 {travel_pulse} {left_angle}"
            if not getattr(config_race, "WITHOUT_ARDUINO", False) and not self._shutdown_requested():
                self.control.configure_lane_sequences(cmd_avoid_left, cmd_return_right,
                                                      persist=True, command_delay_s=0.4)


        self.vision = VisionProcessor()
        self.apriltag_detector = ApriltagDetector(config=config_race)
        self.last_tag = None
        self.stop_last_seen = None
        self.read_sign_counter = 0
        self.last_sign_result_id = 0
        self.stop_hold = StopSignHold(
            clear_confirmations=3,
            minimum_duration_s=getattr(config_race, "STOP_MIN_HOLD_SECONDS", 3.0),
        )
        self.stop_hold_detector_kind = None
        self.last_sign_observation_fresh = False
        self.last_sign_observation_at = None
        self._last_stop_command_at = None
        self._last_stop_release_attempt_at = None
        # This records Python's controller gate, not a confirmed MCU latch.
        self._mcu_stop_latched = False
        self._stop_connection_state = None
        
        # Initialize sign detector strictly based on USE_SIGN variable
        self._marker_lock = threading.RLock()
        self.sign_detector = None
        if config_race.WITH_SIGN:
            self._ensure_sign_detector()
        setattr(config_race, "sign_detector", self.sign_detector)
        config_race.apply_marker_mode = self.apply_marker_mode
            
        # OutputManager instance 
        self.output = OutputManager(config_module=config_race, output_dir=OUTPUT_DIR)
        self.fps = FPS(config=config_race)
        self.object_detector = ObjectDetector()

        if self.health is not None:
            from utils.health import HealthState
            self.health.set_lifecycle(HealthState.READY)


    def _ensure_sign_detector(self):
        if self.sign_detector is not None:
            return
        detector = (
            SVMTrafficSignDetector()
            if config_race.SIGN_DETECTOR_METHOD == "svm"
            else YOLOTrafficSignDetector()
        )
        self.sign_detector = AsyncSignDetector(detector)
        setattr(config_race, "sign_detector", self.sign_detector)

    def apply_marker_mode(self, mode):
        mode = str(mode).lower()
        with self._marker_lock:
            if mode == "sign":
                self._ensure_sign_detector()
            elif mode not in {"apriltag", "none"}:
                raise ValueError(f"unsupported marker mode: {mode}")
            config_race.WITH_SIGN = mode == "sign"
            config_race.WITH_APRILTAG = mode == "apriltag"
            if hasattr(config_race, "USE_SIGN"):
                config_race.USE_SIGN = config_race.WITH_SIGN

    def _sleep_interruptible(self, seconds):
        event = getattr(config_race, "SHUTDOWN_EVENT", None)
        seconds = max(0.0, float(seconds))
        if event is None:
            time.sleep(seconds)
            return False
        return bool(event.wait(seconds))

    def _pace_control_loop(self):
        period = max(0.001, float(getattr(config_race, "CONTROL_PERIOD", 0.01)))
        self._next_control_time += period
        delay = self._next_control_time - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        else:
            self._next_control_time = time.monotonic()

    def update_debug_frames(self, frame):
        publish_debug_frame(config_race, frame)

    def _observe_stop_result(self, stop_seen, detector_kind=None):
        """Update the mode-owned STOP state from a fresh detector observation."""
        if not hasattr(self, "stop_hold"):
            self.stop_hold = StopSignHold(
                clear_confirmations=3,
                minimum_duration_s=getattr(
                    config_race, "STOP_MIN_HOLD_SECONDS", 3.0
                ),
            )

        if stop_seen:
            self.stop_last_seen = time.time()
            if detector_kind is not None:
                self.stop_hold_detector_kind = detector_kind

        was_active = self.stop_hold.active
        self.stop_hold.observe(
            stop_present=bool(stop_seen),
            fresh=bool(getattr(self, "last_sign_observation_fresh", False)),
            observation_time=getattr(self, "last_sign_observation_at", None),
            now=time.monotonic(),
        )

        if self.stop_hold.active and not was_active:
            self._last_stop_command_at = None
            self._last_stop_release_attempt_at = None
            self._set_mcu_stop_latched(
                True,
                force=True,
                send_command=True,
            )
        return self.stop_hold.active

    def _set_mcu_stop_latched(self, latched, force=False, send_command=True):
        """Gate Python motion and periodically transmit the ordinary STOP command."""
        latched = bool(latched)
        control = getattr(self, "control", None)
        if control is None:
            self._mcu_stop_latched = latched
            return True

        without_arduino = getattr(control, "without_arduino", False) is True
        connection = getattr(control, "connection", None)
        connected = without_arduino or bool(
            getattr(connection, "connected", False)
        )
        previous_connected = getattr(self, "_stop_connection_state", None)
        self._stop_connection_state = connected
        reconnected = connected and previous_connected is False
        now = time.monotonic()
        refresh_interval = max(
            0.05,
            float(
                getattr(
                    config_race, "STOP_COMMAND_REFRESH_INTERVAL", 0.25
                )
            ),
        )

        inhibit = getattr(control, "set_motion_inhibited", None)
        if latched:
            if callable(inhibit):
                try:
                    if not inhibit(True, reason="traffic_stop"):
                        return False
                except Exception:
                    logger.exception("Failed to enable the Python traffic STOP gate")
                    return False
            elif not without_arduino:
                logger.error("Controller does not support motion inhibition")
                return False

            was_latched = bool(getattr(self, "_mcu_stop_latched", False))
            self._mcu_stop_latched = True
            if without_arduino:
                return True
            if not send_command:
                return True

            due = (
                force
                or not was_latched
                or reconnected
                or self._last_stop_command_at is None
                or now - self._last_stop_command_at >= refresh_interval
            )
            if not due:
                return True

            # Throttle retries while disconnected, then force an immediate stop
            # after the connection returns.
            self._last_stop_command_at = now
            if not connected or not callable(getattr(control, "stop", None)):
                return False
            try:
                return bool(control.stop(reason="traffic_stop"))
            except Exception:
                logger.exception("Failed to transmit traffic STOP")
                return False

        if not getattr(self, "_mcu_stop_latched", False):
            return True
        if not without_arduino:
            if not connected:
                return False
            last_attempt = getattr(self, "_last_stop_release_attempt_at", None)
            if (
                not reconnected
                and last_attempt is not None
                and now - last_attempt < refresh_interval
            ):
                return False
            self._last_stop_release_attempt_at = now

        if callable(inhibit):
            try:
                success = bool(
                    inhibit(False, reason="traffic_sign_cleared")
                )
            except Exception:
                logger.exception("Failed to release the Python traffic STOP gate")
                success = False
        else:
            success = bool(without_arduino)

        if success:
            self._mcu_stop_latched = False
            self._last_stop_command_at = None
            self._last_stop_release_attempt_at = None
        return success

    def _keep_stop_hold(self):
        """Keep Python motion inhibited and refresh the ordinary MCU stop."""
        success = self._set_mcu_stop_latched(
            True,
            send_command=getattr(
                config_race, "SEND_TRAFFIC_STOP_COMMAND", False
            ),
        )
        return bool(success)

    def _release_stop_hold_if_ready(self):
        """Release only after clearance/time pass and the controller unlock succeeds."""
        if not self.stop_hold.can_release(time.monotonic()):
            return False
        if not self._set_mcu_stop_latched(False):
            return False
        if not self.stop_hold.release(time.monotonic()):
            return False
        self.stop_hold_detector_kind = None
        return True

    def _run_stop_hold_cycle(self):
        """Check STOP on every camera frame while keeping Debug/Stream alive."""
        frame, frame_resized = self.camera.capture_frame(with_resize=True)
        if not self.camera.last_capture_valid or frame_resized is None:
            self._keep_stop_hold()
            self._pace_control_loop()
            return

        debug_frame = frame.copy() if (config_race.STREAM or config_race.DEBUG) else None
        sign_text, _, _, _ = self.handle_read_sign_or_tag(
            frame,
            debug_frame,
            force_check=True,
        )
        if self.stop_hold.active:
            self._release_stop_hold_if_ready()
        still_holding = self.stop_hold.active
        if still_holding:
            self._keep_stop_hold()

        if config_race.STREAM or config_race.DEBUG:
            status = "STOP HOLD" if still_holding else "STOP CLEARED - resuming next frame"
            result = {
                "steering_angle": SERVO_CENTER,
                "error": 0,
                "lane_type": "stop_hold" if still_holding else "stop_cleared",
                "perception_valid": True,
                "crosswalk": False,
                "debug": {"combined": frame},
            }
            self.handle_debug_stream(
                result,
                frame,
                SERVO_CENTER,
                status,
                "STOP" if still_holding else "STOP CLEARED",
            )

        self._pace_control_loop()


   
    def _shutdown_requested(self):
        event = getattr(config_race, "SHUTDOWN_EVENT", None)
        return bool(event is not None and event.is_set())

    def _hold_last_steering_if_lane_missing(self, result):
        """Apply the race policy for a temporarily missing lane estimate."""
        if result.get("lane_type") != "none":
            return False

        held_angle = self.control.last_angle
        if held_angle is None:
            held_angle = getattr(self.control, "current_angle", None)
        if held_angle is None:
            held_angle = SERVO_CENTER

        result["steering_angle"] = int(held_angle)
        logger.debug(
            "Race lane markings not detected; holding steering angle %s",
            held_angle,
        )
        return True

    def run(self):
        logger.info("starting")
        self.fps.start()
        try:
            if self.health is not None:
                from utils.health import HealthState
                self.health.set_lifecycle(HealthState.RUNNING)

            while not self._shutdown_requested():
                self.fps.update()
                self.fps.maybe_log_performance()
                if self.stop_hold.active:
                    self._run_stop_hold_cycle()
                    continue

                if config_race.RUN_LVL == "STOP":
                    # Operator-selected STOP uses the same mode-owned MCU latch.
                    self._set_mcu_stop_latched(True)

                    if config_race.STREAM or config_race.DEBUG:
                        frame, _ = self.camera.capture_frame(with_resize=False)
                        if self.camera.last_capture_valid:
                            result = {
                                "steering_angle": SERVO_CENTER,
                                "error": 0,
                                "lane_type": "stopped",
                                "perception_valid": True,
                                "debug": {"combined": frame},
                            }
                            self.handle_debug_stream(
                                result, frame, SERVO_CENTER,
                                False, "stopped"
                            )
                    self._pace_control_loop()
                    continue

                # Do not enter normal steering/speed branches until the Python
                # controller gate has released successfully.
                latch_state = getattr(self, "_mcu_stop_latched", False)
                if latch_state is True or latch_state is None:
                    if not self._set_mcu_stop_latched(False):
                        self._pace_control_loop()
                        continue

                if config_race.SHOW_FPS:
                    self.fps.print_every_second(
                        self.fps.instant_fps,
                        "|",
                        self.fps.second_fps,
                        "|",
                        self.fps.avg_fps,
                    )

                if config_race.DEBUG:
                    cv2.waitKey(1)
                
                angle = SERVO_CENTER
            
                frame, frame_resized = self.camera.capture_frame(with_resize=True)
                self.camera.last_frame = frame
                if not self.camera.last_capture_valid or frame_resized is None:
                    self.control.stop()
                    self._pace_control_loop()
                    continue
                if config_race.STREAM or config_race.DEBUG:
                    debug_frame = frame.copy()
                else:
                    debug_frame = None
                
                perception_started = time.monotonic()
                result = self.vision.detect(frame_resized, debug_frame)
                observation_at = getattr(self.camera, "last_capture_at", None)
                confidence = None
                if getattr(self, "confidence_estimator", None) is not None:
                    confidence = self.confidence_estimator.evaluate(
                        result, frame_valid=self.camera.last_capture_valid,
                        frame_at=observation_at,
                        observation_token=getattr(self.camera, "frame_sequence", observation_at),
                    )
                    config_race.perception_confidence = confidence
                if self.metrics is not None:
                    self.metrics.record_perception(
                        (time.monotonic() - perception_started) * 1000.0,
                        bool(result.get("perception_valid", False)),
                    )

                sign_text = "None"
                if config_race.WITH_SIGN or config_race.WITH_APRILTAG:
                    sign_text, _, debug_frame, _ = self.handle_read_sign_or_tag(
                        frame,
                        debug_frame,
                    )
                if self.stop_hold.active:
                    self.handle_debug_stream(
                        result,
                        frame,
                        result.get("steering_angle", SERVO_CENTER),
                        "STOP HOLD",
                        "STOP",
                    )
                    self._keep_stop_hold()
                    self._pace_control_loop()
                    continue

                if self.odometry is not None:
                    # Encoder mapping is independent of adaptive obstacle mode.
                    # Consume extended records from the overlapping telemetry tail;
                    # EncoderOdometry deduplicates by monotonic receive timestamp.
                    for sample in self.control.encoder_telemetry(limit=8):
                        if sample.get("extended"):
                            self.odometry.ingest(
                                sample, received_at=sample["received_at"]
                            )

                # On a valid camera frame, temporarily missing lane markings
                # must not stop Race mode. Keep the last applied steering angle
                # and continue at race speed, just as City mode does.
                lane_missing = self._hold_last_steering_if_lane_missing(result)
                if not result.get("perception_valid", False) and not lane_missing:
                    self.control.stop()
                    if config_race.STREAM or config_race.DEBUG:
                        self.handle_debug_stream(
                            result,
                            frame,
                            result.get("steering_angle", SERVO_CENTER),
                            "perception unavailable",
                            "",
                        )
                    self._pace_control_loop()
                    continue

                angle = result.get("steering_angle")
                
                status = "running"

                if config_race.DETECT_OBJECT:
                    self.handle_detect_object(frame)

                # Publish the current debug frame regardless of marker configuration.
                self.handle_debug_stream(result, frame, angle, status, sign_text)
                    
                if config_race.AUTO_UPDATE_KP:
                    self.control.update_kp(result["kp"])
                
                control_started = time.monotonic()
                if getattr(self, "obstacle_planner", None) is not None:
                    # Adaptive planner supplies the sole actuator target.
                    pass
                elif config_race.USE_PID:
                    control_ok = self.control.set_angle_by_error(
                        result["error"],
                        result["lane_type"],
                    )
                    if not control_ok:
                        self._pace_control_loop()
                        continue
                else:
                    control_ok = self.control.set_angle(result["steering_angle"])
                    if not control_ok:
                        self._pace_control_loop()
                        continue

                target_speed = SPEED
                if getattr(self, "confidence_limiter", None) is not None:
                    target_speed, reason = self.confidence_limiter.limit(target_speed, confidence)
                    config_race.speed_decision = {"target": target_speed, "reason": reason}
                if getattr(self, "obstacle_planner", None) is not None:
                    if (not self.control.connection.connected or
                            not getattr(self.control, "_adaptive_mode_ready", False) or
                            getattr(self.control, "_connection_reestablished", False)):
                        self.odometry.mark_discontinuity("serial disconnect/reboot during active planner")
                        decision = self.obstacle_planner._safe("serial reconnect requires fresh initialization and new route decision")
                        self.control.stop(reason=decision["reason"])
                        config_race.obstacle_diagnostics = {"state": decision["state"], "reason": decision["reason"]}
                        self.control._connection_reestablished = False
                        self._pace_control_loop()
                        continue
                    self._run_adaptive_obstacle_cycle(result, target_speed, confidence)
                    if self.metrics is not None:
                        self.metrics.record_control((time.monotonic() - control_started) * 1000.0)
                    self._pace_control_loop()
                    continue
                self.control.set_speed(target_speed)
                if self.metrics is not None:
                    self.metrics.record_control(
                        (time.monotonic() - control_started) * 1000.0
                    )
                self._pace_control_loop()

        except KeyboardInterrupt:
            logger.error("error KeyboardInterrupt")
            
        except Exception as e:
            self.runtime_exception = e
            if self.health is not None:
                from utils.health import FaultSeverity
                self.health.set_fault(
                    "robot_loop",
                    True,
                    severity=FaultSeverity.CRITICAL,
                    message=f"{type(e).__name__}: {e}",
                )
            logger.exception("Unhandled robot loop exception")
        finally:
            # A fatal loop error must stop hardware control but keep the
            # dashboard alive so the health endpoint can report the fault.
            self.close(keep_dashboard=self.runtime_exception is not None)
            logger.info("exited")

    def handle_detect_object(self, frame):
        object_frame = crop_image(frame, 
                                    config_race.OBJ_TOP_ROI, 
                                    config_race.OBJ_BOTTOM_ROI, 
                                    config_race.OBJ_LEFT_ROI, 
                                    config_race.OBJ_RIGHT_ROI
        )
        detected = self.object_detector.detect(object_frame)[1]
        logger.debug("Object detector result: %s", detected)

    def _lane_fraction_under_camera(self, lane_segments_px, frame_shape):
        """Estimate where the camera/vehicle center lies inside visible lane pixels."""
        if frame_shape is None:
            return None
        height, width = frame_shape[:2]
        # Race Hough segments are extracted inside the bottom 20% ROI.
        lookahead_y = min(height - 1, max(1, int(height * 0.90)))
        bounds = self.object_detector.lane_bounds_at_y(
            lane_segments_px, frame_shape, lookahead_y
        )
        if bounds is None:
            return None
        left_bound, right_bound = bounds
        span = right_bound - left_bound
        if span <= 1:
            return None
        fraction = ((width / 2.0) - left_bound) / span
        return fraction if math.isfinite(fraction) else None

    def _path_servo_for_fraction(
        self, lane_segments_px, frame_shape, target_fraction, lookahead_cm
    ):
        """Use calibrated bicycle geometry to steer toward a lane-relative target."""
        if self.odometry is None or not self.odometry.calibrated or frame_shape is None:
            return None
        current_fraction = self._lane_fraction_under_camera(lane_segments_px, frame_shape)
        if current_fraction is None or not 0.0 < float(target_fraction) < 1.0:
            return None
        wheelbase = self.odometry.wheelbase_cm
        road_min = self.odometry.road_angle_min_deg
        road_max = self.odometry.road_angle_max_deg
        if (
            wheelbase is None or wheelbase <= 0
            or road_min is None or road_max is None
            or not float(road_min) < 0 < float(road_max)
        ):
            return None
        lane_width_cm = float(config_race.OBSTACLE_LANE_WIDTH_CM)
        lateral_cm = (float(target_fraction) - current_fraction) * lane_width_cm
        lookahead = max(
            float(config_race.OBSTACLE_STOP_DISTANCE_CM) + self.obstacle_planner.clearance_cm,
            float(lookahead_cm),
            float(wheelbase) * 2.0,
        )
        wheel_angle_deg = math.degrees(math.atan2(
            2.0 * float(wheelbase) * lateral_cm,
            lookahead * lookahead + lateral_cm * lateral_cm,
        ))
        wheel_angle_deg = max(float(road_min), min(float(road_max), wheel_angle_deg))
        ratio = (wheel_angle_deg - float(road_min)) / (float(road_max) - float(road_min))
        servo = self.control.min_servo_angle + ratio * (
            self.control.max_servo_angle - self.control.min_servo_angle
        )
        return int(round(max(
            self.control.min_servo_angle,
            min(self.control.max_servo_angle, servo),
        )))

    def _run_adaptive_obstacle_cycle(self, result, configured_speed, confidence):
        """Collect distinct camera/sensor evidence and apply one planner-owned target."""
        # ACK/status lines can interleave with ODOM1; select the newest parsed
        # extended record rather than treating a non-status line as bad sonar data.
        records = [
            sample for sample in self.control.encoder_telemetry(limit=20)
            if sample.get("extended")
        ]
        record = records[-1] if records else {}
        connection = self.control.connection
        front = record.get("right_ultrasonic_dist") if record.get("front_valid") else None
        front_age = record.get("front_age_ms", 1_000_000) / 1000.0
        if record.get("received_at") is not None:
            front_age += max(0.0, time.monotonic() - record["received_at"])

        frame = getattr(self.camera, "last_frame", None)
        now = time.monotonic()
        camera_fresh = bool(
            self.camera.last_capture_valid
            and self.camera.last_capture_at is not None
            and now - self.camera.last_capture_at <= 0.25
        )
        lane_segments = list(result.get("lane_segments_px") or [])
        if frame is None:
            source_width = source_height = 1.0
        else:
            source_width = float(result.get("frame_width_px") or frame.shape[1])
            source_height = float(result.get("frame_height_px") or frame.shape[0])
            scale_x = frame.shape[1] / max(1.0, source_width)
            scale_y = frame.shape[0] / max(1.0, source_height)
            lane_segments = [
                [float(x1) * scale_x, float(y1) * scale_y,
                 float(x2) * scale_x, float(y2) * scale_y]
                for x1, y1, x2, y2 in lane_segments
            ]

        lane_bounds_ok = bool(
            frame is not None and result.get("lane_type") == "both"
            and result.get("perception_valid")
            and self.object_detector.lane_bounds_at_y(
                lane_segments, frame.shape,
                max(1, int(frame.shape[0] * 0.90)),
            ) is not None
        )
        current_fraction = (
            self._lane_fraction_under_camera(lane_segments, frame.shape)
            if frame is not None and lane_bounds_ok else None
        )
        obstacle = None
        lane_relation = None
        relation = None
        passage_options = {}

        if frame is not None and camera_fresh:
            cropped = crop_image(
                frame, config_race.OBJ_TOP_ROI, config_race.OBJ_BOTTOM_ROI,
                config_race.OBJ_LEFT_ROI, config_race.OBJ_RIGHT_ROI,
            )
            _detected_by_global_area, _percent, mask = self.object_detector.detect(cropped)
            obstacle = self.object_detector.localize(cropped, mask)
            if obstacle is not None:
                # localize() returns ROI-local pixels. Translate to raw-frame pixels.
                obstacle["bbox_px"][0] += int(config_race.OBJ_LEFT_ROI * frame.shape[1])
                obstacle["bbox_px"][1] += int(config_race.OBJ_TOP_ROI * frame.shape[0])
                obstacle["centroid_px"][0] += int(config_race.OBJ_LEFT_ROI * frame.shape[1])
                obstacle["centroid_px"][1] += int(config_race.OBJ_TOP_ROI * frame.shape[0])
                lane_relation = self.object_detector.relates_to_lane(
                    obstacle, lane_segments, frame.shape
                )
                component_ratio = float(obstacle.get("area_px", 0.0)) / max(
                    1.0, float(frame.shape[0] * frame.shape[1])
                )
                object_confirmable = bool(
                    obstacle.get("valid") and component_ratio >= 0.002
                    and float(obstacle.get("quality", 0.0)) >= 0.10
                )
                if (
                    object_confirmable and lane_relation.get("valid")
                    and lane_relation.get("relation") == "inside_lane"
                ):
                    fraction = float(lane_relation["image_fraction_across_lane"])
                    relation = "left" if fraction < 0.40 else (
                        "right" if fraction > 0.60 else "center"
                    )
                    passage_options = self.object_detector.passage_options(
                        obstacle, lane_segments, frame.shape,
                        config_race.OBSTACLE_LANE_WIDTH_CM,
                        config_race.OBSTACLE_ROBOT_WIDTH_CM,
                        config_race.OBSTACLE_CLEARANCE_CM,
                    )
                elif lane_relation.get("valid") and lane_relation.get("relation") == "outside_lane":
                    relation = "outside_path"

        lane_servo = result.get("steering_angle", self.control.servo_center)
        snapshot = self.odometry.snapshot() if self.odometry is not None else {"valid": False}
        path_servo = {}
        lookahead_cm = (
            float(front) if isinstance(front, (int, float)) and front > 0
            else float(config_race.OBSTACLE_TRIGGER_DISTANCE_CM)
        )
        for side, option in passage_options.items():
            angle = self._path_servo_for_fraction(
                lane_segments, frame.shape, float(option["target_fraction"]), lookahead_cm
            ) if frame is not None else None
            if angle is not None:
                path_servo[side] = angle

        target_fraction = self.obstacle_planner.target_fraction
        selected_side = self.obstacle_planner.selected_side
        if target_fraction is not None and lane_bounds_ok and frame is not None:
            angle = self._path_servo_for_fraction(
                lane_segments, frame.shape, target_fraction, lookahead_cm
            )
            if selected_side and angle is not None:
                path_servo[selected_side] = angle
        if lane_bounds_ok and frame is not None:
            return_angle = self._path_servo_for_fraction(
                lane_segments, frame.shape, 0.5, lookahead_cm
            )
            if return_angle is not None:
                path_servo["return"] = return_angle

        pass_path_acquired = bool(
            current_fraction is not None and target_fraction is not None
            and abs(current_fraction - target_fraction) <= 0.10
        )
        original_lane_reacquired = bool(
            current_fraction is not None and abs(current_fraction - 0.5) <= 0.10
        )
        obstacle_detected_in_lane = bool(
            obstacle and obstacle.get("valid") and frame is not None
            and float(obstacle.get("area_px", 0.0)) / max(
                1.0, float(frame.shape[0] * frame.shape[1])
            ) >= 0.002
            and lane_relation and lane_relation.get("valid")
            and lane_relation.get("relation") == "inside_lane"
        )
        observation = {
            "front_right_cm": front,
            "front_age_s": front_age,
            "front_sample_sequence": record.get("front_sequence"),
            "orange_obstacle_detected": obstacle_detected_in_lane,
            "obstacle_lane_relation": relation,
            "camera_fresh": camera_fresh,
            "camera_geometry_valid": lane_bounds_ok,
            "frame_token": self.camera.last_capture_at if camera_fresh else None,
            "passage_options": passage_options,
            "path_servo": path_servo,
            "steering_calibrated": bool(self.odometry is not None and self.odometry.calibrated),
            "odometry_valid": bool(snapshot.get("valid")),
            "odometry_discontinuity": not bool(snapshot.get("valid")),
            "travel_cm": snapshot.get("travel_cm"),
            "pass_path_acquired": pass_path_acquired,
            "original_lane_reacquired": original_lane_reacquired,
            "lane_servo": lane_servo,
            "servo_center": self.control.servo_center,
            "configured_speed": configured_speed,
            "slow_speed": min(abs(configured_speed), 70),
            "connection_lost": not connection.connected,
        }
        decision = self.obstacle_planner.update(observation)
        config_race.obstacle_diagnostics = {
            "state": decision["state"],
            "reason": decision["reason"],
            "selected_side": decision.get("selected_side"),
            "target_fraction": decision.get("target_fraction"),
            "orange_component": obstacle,
            "front_sensor_cm": front,
            "front_sample_age_s": front_age,
            "camera_lane_relation": lane_relation,
            "passage_options": passage_options,
            "current_lane_fraction": current_fraction,
            "rear_left_sensor_used_for_forward_clearance": False,
            "odometry": snapshot,
            "confidence": confidence,
        }

        if decision["state"] == "SAFE_STOP":
            self.control.stop(reason=decision["reason"])
            return
        steering = max(
            self.control.min_servo_angle,
            min(self.control.max_servo_angle, decision["steering"]),
        )
        if not self.control.set_angle(steering):
            decision = self.obstacle_planner._safe("steering target was not acknowledged")
            self.control.stop(reason=decision["reason"])
            config_race.obstacle_diagnostics.update(
                {"state": decision["state"], "reason": decision["reason"]}
            )
            return
        self.control.set_speed(decision["speed"])

    def handle_read_sign_or_tag(self, frame, debug_frame, force_check=False):
        # A latched STOP keeps using the detector that originally found it,
        # even if the dashboard's marker-mode toggle changes during the hold.
        self.last_sign_observation_fresh = False
        self.last_sign_observation_at = None

        hold_active = getattr(getattr(self, "stop_hold", None), "active", False)
        hold_detector = getattr(self, "stop_hold_detector_kind", None)
        if force_check and hold_active:
            use_apriltag = hold_detector == "apriltag"
            use_sign = hold_detector == "sign"
        else:
            use_apriltag = bool(config_race.WITH_APRILTAG)
            use_sign = bool(config_race.WITH_SIGN)

        if not (use_sign or use_apriltag):
            return None, False, debug_frame, None

        sign_tag_frame = crop_image(
            frame,
            config_race.ST_TOP_ROI,
            config_race.ST_BOTTOM_ROI,
            config_race.ST_LEFT_ROI,
            config_race.ST_RIGHT_ROI,
        )

        stop_seen = False
        coordinate = None
        tag_id = None
        detector_kind = None

        if use_apriltag:
            _, debug_frame, largest_tag, coordinate = self.apriltag_detector.detect(
                sign_tag_frame,
                debug_frame,
            )
            # AprilTag detection is synchronous, so every captured frame is a
            # fresh presence/absence observation while STOP hold is active.
            self.last_sign_observation_fresh = True
            self.last_sign_observation_at = time.monotonic()

            if largest_tag is not None:
                tag_id = largest_tag["id"]
                if tag_id == STOP:
                    # STOP must not be hidden by the old y-coordinate gate.
                    stop_seen = True
                    detector_kind = "apriltag"
                    self.last_tag = tag_id
                elif largest_tag["corners"][1][1] > 180:
                    self.last_tag = tag_id

        elif use_sign:
            if self.sign_detector is None:
                self._ensure_sign_detector()

            should_submit = bool(force_check)
            if force_check:
                # No READ_SIGN_THRESHOLD gate in the latched STOP state.
                self.read_sign_counter = 0
            else:
                self.read_sign_counter += 1
                should_submit = (
                    self.read_sign_counter >= config_race.READ_SIGN_THRESHOLD
                )

            if should_submit:
                self.read_sign_counter = 0
                self.sign_detector.submit(
                    sign_tag_frame.copy(),
                    debug_frame.copy() if debug_frame is not None else None,
                )

            # Submission is throttled, but a completed result is consumed on
            # every loop iteration so READ_SIGN_THRESHOLD cannot delay STOP.
            latest_sign = self.sign_detector.latest(
                max_age_s=getattr(config_race, "SIGN_RESULT_MAX_AGE", 0.75)
            )
            if (
                latest_sign is not None
                and latest_sign[0] > self.last_sign_result_id
            ):
                self.last_sign_result_id = latest_sign[0]
                sign_result = latest_sign[1]
                coordinate = sign_result.get("coordinate")
                debug_frame = sign_result.get("debug_frame", debug_frame)
                self.last_sign_observation_fresh = True
                self.last_sign_observation_at = latest_sign[2]

                sign_label = sign_result.get("text", "")
                if sign_label == "TURN LEFT":
                    tag_id = TURN_LEFT
                elif sign_label == "TURN RIGHT":
                    tag_id = TURN_RIGHT
                elif sign_label == "STRAIGHT":
                    tag_id = STRAIGHT
                elif sign_label == "STOP":
                    tag_id = STOP
                    stop_seen = True
                    detector_kind = "sign"

                if tag_id is not None:
                    self.last_tag = tag_id

        self._observe_stop_result(stop_seen, detector_kind=detector_kind)
        return tag_id, stop_seen, debug_frame, coordinate


    def handle_debug_stream(self, result, frame, angle, status, sign_text):
        if getattr(config_race, "STREAM", False):
            diagnostics = []
            confidence = getattr(config_race, "perception_confidence", None)
            if confidence:
                diagnostics.append(f"Confidence:{confidence['score']:.2f} {confidence['name']}")
            obstacle = getattr(config_race, "obstacle_diagnostics", None)
            if obstacle:
                diagnostics.append(f"Obstacle:{obstacle['state']} {obstacle['reason']}")
            result.setdefault("debug", {})["runtime_diagnostics"] = diagnostics
        if config_race.DEBUG:
            debug = result.get("debug") or {}
            if debug.get("combined") is not None:
                cv2.imshow("combined", debug["combined"])
            if frame is not None:
                cv2.imshow("frame", frame)
            
        if config_race.STREAM:
            
            debug = result.get("debug") or {}
            source_frame = debug.get("combined")
            if source_frame is None:
                source_frame = frame
            if source_frame is None:
                return
            display_frame = source_frame.copy()
            angle_text = (
                f"{angle:.1f}"
                if isinstance(angle, (int, float, np.number))
                else "N/A"
            )
            real_angle = self.control.last_angle
            real_angle_text = (
                f"{real_angle:.1f}"
                if isinstance(real_angle, (int, float, np.number))
                else "N/A"
            )
            texts = [
                f"FPS: {self.fps.instant_fps:.1f}, RealFPS: {self.fps.second_fps:.1f}, {status}",
                f"Angle:{angle_text}, RealAngle:{real_angle_text}, Sign:{sign_text}, LastTag:{self.last_tag}",
            ]

            font = cv2.FONT_HERSHEY_SIMPLEX
            scale = 0.3
            thickness = 1
            line_height = 15 
            org_x = 10
            org_y_start = 20 

            for i, text in enumerate(texts):
                y_pos = org_y_start + (i * line_height)
                
                (text_width, text_height), baseline = cv2.getTextSize(text, font, scale, thickness)
                pad = 4
                x1, y1 = org_x - pad, y_pos - text_height - pad
                x2, y2 = org_x + text_width + pad, y_pos + baseline + pad
                
                roi = display_frame[max(0, y1):y2, max(0, x1):x2]
                if roi.size > 0:
                    roi_blur = cv2.GaussianBlur(roi, (15, 15), 0)
                    roi_white = cv2.addWeighted(roi_blur, 0.3, 255*np.ones_like(roi_blur, dtype=np.uint8), 0.7, 0)
                    display_frame[max(0, y1):y2, max(0, x1):x2] = roi_white

                cv2.putText(display_frame, text, (org_x, y_pos), font, scale, (0, 0, 0), thickness)

            self.update_debug_frames(display_frame)

            if getattr(config_race, "TAKE_PICTURE", False):
                try:
                    self.output.save_image(display_frame)
                except Exception as e:
                    logger.error(f"save_image failed: {e}")
                config_race.TAKE_PICTURE = False

            if getattr(config_race, "RECORD_VIDEO", False):
                if not self.output.is_recording():
                    try:
                        self.output.start_recording(display_frame.shape, fps=VIDEO_FPS, codec=VIDEO_CODEC)
                    except Exception as e:
                        logger.error(f"start_recording failed: {e}")
                self.output.write_frame(display_frame)
            else:
                if self.output.is_recording():
                    try:
                        self.output.stop_recording()
                    except Exception as e:
                        logger.error(f"stop_recording failed: {e}")

    def close(self, keep_dashboard=False):
        if self.health is not None and not keep_dashboard:
            from utils.health import HealthState
            self.health.set_lifecycle(HealthState.SHUTTING_DOWN)

        cleanup = [
            ("stop", self.control.stop),
            ("center servo", lambda: self.control.set_angle(self.control.servo_center)),
            ("camera release", self.camera.release),
            ("serial close", self.control.connection.close),
        ]
        for name, action in cleanup:
            try:
                action()
            except Exception:
                logger.exception("Cleanup failed: %s", name)

        if self.sign_detector is not None:
            try:
                self.sign_detector.close()
            except Exception:
                logger.exception("Cleanup failed: sign detector")

        try:
            self.output.close()
        except Exception:
            logger.exception("Cleanup failed: output manager")

        if config_race.DEBUG:
            try:
                cv2.destroyAllWindows()
            except Exception:
                logger.exception("Cleanup failed: OpenCV windows")

        if not keep_dashboard and self.flask_thread and self.flask_thread.is_alive():
            try:
                stop_stream(config_race)
            except Exception:
                logger.exception("Failed to stop Flask stream")
            self.flask_thread.join(timeout=1.0)

        try:
            if getattr(config_race, 'arduino_connection', None) is self.control.connection:
                delattr(config_race, "arduino_connection")
        except Exception:
            logger.exception("Cleanup failed: serial state detach")


def start():
    robot = Robot()
    robot.flask_thread = None

    if config_race.STREAM:
        robot.flask_thread = threading.Thread(
            target=start_stream,
            args=(config_race,),
            daemon=True,
            name="flask-stream",
        )
        robot.flask_thread.start()

    robot.run()

    # Fatal runtime exceptions stop the actuators and release camera/serial
    # resources, but keep the HTTP dashboard available for diagnosis. Do not
    # restart the motion loop automatically; the operator must review the fault.
    if (
        robot.runtime_exception is not None
        and robot.flask_thread is not None
        and robot.flask_thread.is_alive()
    ):
        logger.error(
            "Robot loop failed; actuators are stopped. Dashboard remains available "
            "for diagnosis. Press Ctrl+C to exit."
        )
        shutdown_event = getattr(config_race, "SHUTDOWN_EVENT", None)
        try:
            while robot.flask_thread.is_alive():
                if shutdown_event is not None and shutdown_event.wait(0.5):
                    break
                if shutdown_event is None:
                    time.sleep(0.5)
        finally:
            if robot.flask_thread.is_alive():
                try:
                    stop_stream(config_race)
                except Exception:
                    logger.exception("Failed to stop diagnostic dashboard")
                robot.flask_thread.join(timeout=1.0)
