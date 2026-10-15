import modes.city.config_city as config_city 

from utils.config_mode import set_city_mode
# set_city_mode()
from manager.output_manager import OutputManager
from vision.camera import Camera
from vision.city_vision_processing import VisionProcessor
from vision.blsf_lane import create_blsf_lane_detector
from vision.apriltag import ApriltagDetector
from vision.object_detector import ObjectDetector
from vision.traffic_light import TrafficLightDetector, GreenConfirmationWindow
from traffic_sign_detector.svm_detector import TrafficSignDetector as SVMTrafficSignDetector
from traffic_sign_detector.yolo_detector import TrafficSignDetector as YOLOTrafficSignDetector
from traffic_sign_detector.async_detector import AsyncSignDetector
from traffic_sign_detector.stop_hold import StopSignHold
from controller import RobotController
from controller.perception_confidence import PerceptionConfidenceEstimator, ConfidenceSpeedLimiter
from modes.city.config_city import (
    SPEED, HARDCODE_SPEED, SERVO_CENTER,
    TURN_LEFT, TURN_RIGHT, STRAIGHT, STOP)
from stream import publish_debug_frame, start_stream, stop_stream
import logging
import cv2
import numpy as np
import time
import threading
from utils.fps import FPS
from utils.roi_manager import crop_image


logger = logging.getLogger(__name__)

# keep defaults (config_city can override)
OUTPUT_DIR = getattr(config_city, "OUTPUT_DIR", "output")
VIDEO_FPS = getattr(config_city, "VIDEO_FPS", 20)
VIDEO_CODEC = getattr(config_city, "VIDEO_CODEC", "mp4v")

if not hasattr(config_city, "debug_frames_list") or not isinstance(config_city.debug_frames_list, list):
    config_city.debug_frames_list = [None, None]

config_city.DEBUG = False


class Robot:
    def __init__(self):
        self.metrics = getattr(config_city, "runtime_metrics", None)
        self.health = getattr(config_city, "health_monitor", None)
        self.camera = Camera(config=config_city)
        self.control = RobotController(config=config_city)
        config_city.arduino_connection = self.control.connection
        config_city.robot_controller = self.control
        if getattr(config_city, "ENCODER_MAP_ENABLED", False):
            from controller.odometry import EncoderOdometry
            self.odometry = EncoderOdometry(
                config_city.ENCODER_PULSE_DISTANCE_CM,
                wheelbase_cm=config_city.ENCODER_WHEELBASE_CM,
                servo_center=self.control.servo_center,
                servo_min=self.control.min_servo_angle,
                servo_max=self.control.max_servo_angle,
                road_angle_min_deg=config_city.ENCODER_ROAD_ANGLE_MIN_DEG,
                road_angle_max_deg=config_city.ENCODER_ROAD_ANGLE_MAX_DEG,
            )
            if not self.control.request_encoder_telemetry():
                raise RuntimeError("Selected firmware did not acknowledge encoder telemetry ODOM1")
            self.control._encoder_telemetry_ready = True
            config_city.encoder_odometry = self.odometry
        else:
            self.odometry = None
        self.flask_thread = None
        self.runtime_exception = None
        self._next_control_time = time.monotonic()
        if getattr(config_city, "CONFIDENCE_AWARE_ENABLED", False):
            self.confidence_estimator = PerceptionConfidenceEstimator()
            self.confidence_limiter = ConfidenceSpeedLimiter(
                config_city.CONFIDENCE_SLOW_THRESHOLD,
                config_city.CONFIDENCE_STOP_THRESHOLD,
            )
        else:
            self.confidence_estimator = self.confidence_limiter = None

        # SET-based lane configuration is independent of the optional handshake.
        if not getattr(config_city, "WITHOUT_ARDUINO", False):
            self.control.configure_lane_sequences(
                "b 170 110 70 b 170 80 125",
                "f 170 70 125 f 170 70 70",
                persist=False,
                command_delay_s=0.4,
            )

        lane_detector = getattr(config_city, "CITY_LANE_DETECTOR", "default")

        if lane_detector == "blsf-beta":
            # BETA: experimental classical BLSF lane detector.
            # Existing City lane detection remains the default.
            self.vision = create_blsf_lane_detector(config_city)
        elif lane_detector == "default":
            self.vision = VisionProcessor()
        else:
            raise ValueError(
                "Unsupported CITY_LANE_DETECTOR: "
                f"{lane_detector!r}. Expected 'default' or 'blsf-beta'."
            )

        logger.info("City lane detector selected: %s", lane_detector)
        self.apriltag_detector = ApriltagDetector(config=config_city)
        self.crosswalk_time_start = 0
        self.crosswalk_last_seen = 0
        self.traffic_light_detector = None
        self.traffic_light_window = None
        self._traffic_light_status = ""
        self._traffic_light_last_state = None
        if getattr(config_city, "TRAFFIC_LIGHTS_ENABLED", False):
            self.traffic_light_detector = TrafficLightDetector(config_city)
            self.traffic_light_window = GreenConfirmationWindow(getattr(config_city,"TL_CONFIRMATION_WINDOW",10),getattr(config_city,"TL_CONFIRMATION_GREEN_REQUIRED",8))
        self.last_tag = None
        self.stop_last_seen = None
        self.read_sign_counter = 0
        self.last_sign_result_id = 0
        self.stop_hold = StopSignHold(
            clear_confirmations=3,
            minimum_duration_s=getattr(config_city, "STOP_MIN_HOLD_SECONDS", 3.0),
        )
        self.stop_hold_detector_kind = None
        self.last_sign_observation_fresh = False
        self.last_sign_observation_at = None
        self._last_stop_command_at = None
        self._last_stop_release_attempt_at = None
        # This records Python's controller gate, not a confirmed MCU latch.
        self._mcu_stop_latched = False
        self._stop_connection_state = None
        self._marker_lock = threading.RLock()
        self.sign_detector = None
        if config_city.WITH_SIGN:
            self._ensure_sign_detector()
        setattr(config_city, "sign_detector", self.sign_detector)
        config_city.apply_marker_mode = self.apply_marker_mode
        # OutputManager instance 
        self.output = OutputManager(config_module=config_city, output_dir=OUTPUT_DIR)
        self.fps = FPS(config=config_city)
        self.object_detector = ObjectDetector()

        if self.health is not None:
            from utils.health import HealthState
            self.health.set_lifecycle(HealthState.READY)


    def _ensure_sign_detector(self):
        if self.sign_detector is not None:
            return
        detector = (
            SVMTrafficSignDetector()
            if config_city.SIGN_DETECTOR_METHOD == "svm"
            else YOLOTrafficSignDetector()
        )
        self.sign_detector = AsyncSignDetector(detector)
        setattr(config_city, "sign_detector", self.sign_detector)

    def apply_marker_mode(self, mode):
        mode = str(mode).lower()
        with self._marker_lock:
            if mode == "sign":
                self._ensure_sign_detector()
            elif mode not in {"apriltag", "none"}:
                raise ValueError(f"unsupported marker mode: {mode}")
            config_city.WITH_SIGN = mode == "sign"
            config_city.WITH_APRILTAG = mode == "apriltag"
            if hasattr(config_city, "USE_SIGN"):
                config_city.USE_SIGN = config_city.WITH_SIGN

    def _sleep_interruptible(self, seconds):
        event = getattr(config_city, "SHUTDOWN_EVENT", None)
        seconds = max(0.0, float(seconds))
        if event is None:
            time.sleep(seconds)
            return False
        return bool(event.wait(seconds))

    def _pace_control_loop(self):
        period = max(0.001, float(getattr(config_city, "CONTROL_PERIOD", 0.01)))
        self._next_control_time += period
        delay = self._next_control_time - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        else:
            self._next_control_time = time.monotonic()

    def update_debug_frames(self, frame):
        publish_debug_frame(config_city, frame)

    def _observe_stop_result(self, stop_seen, detector_kind=None):
        """Update the mode-owned STOP state from a fresh detector observation."""
        if not hasattr(self, "stop_hold"):
            self.stop_hold = StopSignHold(
                clear_confirmations=3,
                minimum_duration_s=getattr(
                    config_city, "STOP_MIN_HOLD_SECONDS", 3.0
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
                getattr(config_city, "STOP_COMMAND_REFRESH_INTERVAL", 0.25)
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
                config_city, "SEND_TRAFFIC_STOP_COMMAND", False
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

        debug_frame = frame.copy() if (config_city.STREAM or config_city.DEBUG) else None
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

        if config_city.STREAM or config_city.DEBUG:
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
                False,
                status,
                "STOP" if still_holding else "STOP CLEARED",
            )

        self._pace_control_loop()


    def check_crosswalk(self, frame=None):
        now = time.time()
        if self.crosswalk_time_start == 0 and now - self.crosswalk_last_seen >= config_city.CROSSWALK_THRESH_SPEND:
            self.crosswalk_time_start = now
            self.crosswalk_last_seen = now
            self.control.record_event(
                "crosswalk_stop_started",
                {
                    "planned_duration_s": config_city.CROSSWALK_SLEEP,
                    "last_tag": self.last_tag,
                },
            )

        if self.crosswalk_time_start != 0:
            elapsed = now - self.crosswalk_time_start
            enabled = bool(getattr(config_city,"TRAFFIC_LIGHTS_ENABLED",False))
            permitted = False
            if enabled:
                wait = bool(getattr(config_city,"TRAFFIC_LIGHT_WAIT_BEFORE_CHECK",False))
                if wait and elapsed < float(config_city.CROSSWALK_SLEEP): self._traffic_light_status=f"Waiting before check ({elapsed:.1f}/{config_city.CROSSWALK_SLEEP:.1f}s)"
                elif frame is None or not getattr(self.camera,"last_capture_valid",False): self._traffic_light_status="UNKNOWN camera frame; holding"
                else:
                    try: color,_=self.traffic_light_detector.detect(frame)
                    except Exception:
                        logger.exception("Traffic-light detector failed; holding");color=None
                    token=getattr(self.camera,"last_capture_at",None)
                    if token is None:token=id(frame)
                    permitted=self.traffic_light_window.observe(color,token)
                    if color=="RED":self._traffic_light_status="RED detected; holding"
                    elif color!="GREEN":self._traffic_light_status="UNKNOWN/ambiguous; holding"
                    elif permitted:self._traffic_light_status="GREEN confirmed; crossing permitted"
                    else:self._traffic_light_status=f"GREEN confirmation: {self.traffic_light_window.green_count}/{self.traffic_light_window.window_size}"
                if self._traffic_light_status!=self._traffic_light_last_state:
                    logger.info("City traffic-light gate: %s",self._traffic_light_status);self._traffic_light_last_state=self._traffic_light_status
                if permitted and self._traffic_light_status=="GREEN confirmed; crossing permitted":self.control.record_event("traffic_light_green_confirmed",{"green_count":self.traffic_light_window.green_count,"window_size":self.traffic_light_window.window_size})
            can_cross=permitted if enabled else elapsed>=config_city.CROSSWALK_SLEEP
            if can_cross:
                self.crosswalk_time_start = 0
                if enabled and self.traffic_light_window is not None:
                    self.control.record_event("traffic_light_crossing_released",{"tag":self.last_tag})
                    self.traffic_light_window.reset()
                logger.debug(f"navigate with tag: {self.last_tag}")
                if self._shutdown_requested():
                    return
                self.control.record_event(
                    "crosswalk_maneuver_started",
                    {"tag": self.last_tag},
                )
                self.control.set_angle(self.control.servo_center)
                if self._sleep_interruptible(0.3):
                    return

                if self.last_tag == TURN_RIGHT:
                    if self._shutdown_requested():
                        return
                    self.control.signal_right()
                    if self._sleep_interruptible(0.1):
                        return
                    if self._shutdown_requested():
                        return
                    self.control.forward_pulse(
                        f"f {HARDCODE_SPEED} 80 95  f {HARDCODE_SPEED} 80 120 b {HARDCODE_SPEED} 80 70 f {HARDCODE_SPEED} 80 110",
                        event="crosswalk_turn_right",
                        metadata={"tag": self.last_tag},
                    )
                    if self._sleep_interruptible(0.1):
                        return
                elif self.last_tag == TURN_LEFT:
                    if self._shutdown_requested():
                        return
                    self.control.signal_left()
                    if self._sleep_interruptible(0.1):
                        return
                    if self._shutdown_requested():
                        return
                    self.control.forward_pulse(
                        f"f {HARDCODE_SPEED} 120 95 f {HARDCODE_SPEED} 120 60",
                        event="crosswalk_turn_left",
                        metadata={"tag": self.last_tag},
                    )
                    if self._sleep_interruptible(0.1):
                        return
                elif self.last_tag == STRAIGHT:
                    if self._sleep_interruptible(0.1):
                        return
                    if self._shutdown_requested():
                        return
                    self.control.forward_pulse(
                        f"f {HARDCODE_SPEED} 220 95",
                        event="crosswalk_straight",
                        metadata={"tag": self.last_tag},
                    )
                    if self._sleep_interruptible(0.1):
                        return
                else:
                    if self._sleep_interruptible(0.1):
                        return
                    if self._shutdown_requested():
                        return
                    self.control.forward_pulse(f"f {HARDCODE_SPEED}  220 95")
                    if self._sleep_interruptible(0.1):
                        return

    def _shutdown_requested(self):
        event = getattr(config_city, "SHUTDOWN_EVENT", None)
        return bool(event is not None and event.is_set())

    def _log_lane_detection_state(self, lane_missing, held_angle=None):
        """Log lane loss/recovery without writing a message for every camera frame."""
        lane_missing = bool(lane_missing)
        now = time.monotonic()
        previous = getattr(self, "_lane_missing_state", None)
        last_log_at = getattr(self, "_last_lane_state_log_at", None)
        elapsed = (
            float("inf")
            if last_log_at is None
            else max(0.0, now - last_log_at)
        )

        # Report the first loss immediately, then rate-limit state changes and
        # emit a low-frequency reminder only while lane detection stays lost.
        if lane_missing:
            should_log = (
                last_log_at is None
                or (previous is not True and elapsed >= 1.0)
                or (previous is True and elapsed >= 5.0)
            )
            if should_log:
                logger.debug(
                    "City lane markings not detected; holding steering angle %s",
                    held_angle,
                )
        else:
            should_log = previous is True and elapsed >= 1.0
            if should_log:
                logger.debug("City lane markings detected again")

        if should_log:
            self._last_lane_state_log_at = now
        self._lane_missing_state = lane_missing

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
                    # STOP-sign holds supersede traffic-light permission; discard
                    # any prior green history so it cannot release this crossing.
                    if self.traffic_light_window is not None:
                        self.traffic_light_window.reset()
                    self._run_stop_hold_cycle()
                    continue

                if config_city.RUN_LVL == "STOP":
                    # Operator-selected STOP uses the same mode-owned MCU latch.
                    self._set_mcu_stop_latched(True)

                    if config_city.STREAM or config_city.DEBUG:
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
                                result, frame, SERVO_CENTER, False, "stopped"
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

                if config_city.SHOW_FPS:
                    self.fps.print_every_second(
                        self.fps.instant_fps,
                        "|",
                        self.fps.second_fps,
                        "|",
                        self.fps.avg_fps,
                    )

                if config_city.DEBUG:
                    cv2.waitKey(1)
                angle=SERVO_CENTER
                crosswalk = False
                confidence = None
                
                if self.crosswalk_time_start == 0:
                    frame, frame_resized = self.camera.capture_frame(with_resize=True)
                    self.camera.last_frame = frame
                    if not self.camera.last_capture_valid or frame_resized is None:
                        self.control.stop()
                        self._pace_control_loop()
                        continue
                    if config_city.STREAM or config_city.DEBUG:
                        debug_frame = frame.copy()
                    else:
                        debug_frame = None
                    
                    perception_started = time.monotonic()
                    result = self.vision.detect(frame_resized, debug_frame)
                    if getattr(self, "odometry", None) is not None:
                        # The telemetry API returns a rolling tail, so loops overlap.
                        # Only feed ODOM1 records; EncoderOdometry also rejects replayed
                        # and out-of-order receive timestamps.
                        for sample in self.control.encoder_telemetry(limit=8):
                            if sample.get("extended"):
                                self.odometry.ingest(
                                    sample, received_at=sample["received_at"]
                                )
                    confidence = None
                    if getattr(self, "confidence_estimator", None) is not None:
                        confidence = self.confidence_estimator.evaluate(
                            result,
                            frame_valid=self.camera.last_capture_valid,
                            frame_at=self.camera.last_capture_at,
                            observation_token=self.camera.last_capture_at,
                        )
                        config_city.perception_confidence = confidence
                    if self.metrics is not None:
                        self.metrics.record_perception(
                            (time.monotonic() - perception_started) * 1000.0,
                            bool(result.get("perception_valid", False)),
                        )

                    sign_text = ""
                    if config_city.WITH_SIGN or config_city.WITH_APRILTAG:
                        sign_text, _, debug_frame, _ = self.handle_read_sign_or_tag(
                            frame,
                            debug_frame,
                        )
                    if self.stop_hold.active:
                        self.handle_debug_stream(
                            result,
                            frame,
                            result.get("steering_angle", SERVO_CENTER),
                            result.get("crosswalk", False),
                            "STOP HOLD",
                            sign_text,
                        )
                        self._keep_stop_hold()
                        self._pace_control_loop()
                        continue

                    # Missing lane markings in a valid camera frame are common
                    # through bends. Hold the last actuator angle and continue
                    # at cruising speed instead of treating lane_type="none" as
                    # a camera/perception-system failure.
                    lane_missing = result.get("lane_type") == "none"
                    if not result.get("perception_valid", False) and not lane_missing:
                        self.control.stop()
                        if config_city.STREAM or config_city.DEBUG:
                            self.handle_debug_stream(
                                result,
                                frame,
                                result.get("steering_angle", SERVO_CENTER),
                                result.get("crosswalk", False),
                                "perception unavailable",
                                "",
                            )
                        self._pace_control_loop()
                        continue

                    if lane_missing:
                        held_angle = self.control.last_angle
                        if held_angle is None:
                            held_angle = self.control.current_angle
                        if held_angle is None:
                            held_angle = SERVO_CENTER
                        result["steering_angle"] = int(held_angle)
                        self._log_lane_detection_state(True, held_angle)
                    else:
                        self._log_lane_detection_state(False)

                    angle = result.get("steering_angle")
                    crosswalk = result.get("crosswalk", False)

                    status = "STOP HOLD" if self.stop_hold.active else "running"
                    self.handle_debug_stream(
                        result,
                        frame,
                        angle,
                        crosswalk,
                        status,
                        sign_text,
                    )
                    if self.stop_hold.active:
                        self._keep_stop_hold()
                        self._pace_control_loop()
                        continue

                    if config_city.DETECT_OBJECT:
                        self.handle_detect_object(frame)
                    
                else:
                    if not self.control.stop():
                        self._pace_control_loop()
                        continue
                    time.sleep(2*config_city.DELAY)
                    frame, frame_resized = self.camera.capture_frame(with_resize=True)
                    if not self.camera.last_capture_valid or frame_resized is None:
                        self.control.stop()
                        self._pace_control_loop()
                        continue
                    result = {
                        "steering_angle": SERVO_CENTER,
                        "error": 0,
                        "lane_type": "crosswalk",
                        "perception_valid": True,
                        "crosswalk": True,
                        "debug": {"combined": frame},
                    }
                    sign_text = ""
                    debug_frame = frame.copy() if (config_city.DEBUG or config_city.STREAM) else None

                    if config_city.DEBUG or config_city.STREAM:
                        perception_started = time.monotonic()
                        result = self.vision.detect(frame_resized, debug_frame)
                        if getattr(self, "confidence_estimator", None) is not None:
                            confidence = self.confidence_estimator.evaluate(
                                result,
                                frame_valid=self.camera.last_capture_valid,
                                frame_at=self.camera.last_capture_at,
                                observation_token=self.camera.last_capture_at,
                            )
                            config_city.perception_confidence = confidence
                        if self.metrics is not None:
                            self.metrics.record_perception(
                                (time.monotonic() - perception_started) * 1000.0,
                                bool(result.get("perception_valid", False)),
                            )
                        angle = result.get("steering_angle")
                        crosswalk = result.get("crosswalk", False)

                    # Marker checks must run even when Debug and Stream are off;
                    # otherwise STOP could be missed during the crosswalk path.
                    sign_text, debug_frame = self._process_crosswalk_marker(
                        frame,
                        debug_frame,
                    )
                    if self.stop_hold.active:
                        self._keep_stop_hold()
                        if config_city.DEBUG or config_city.STREAM:
                            self.handle_debug_stream(
                                result,
                                frame,
                                SERVO_CENTER,
                                False,
                                "STOP HOLD",
                                "STOP",
                            )
                        self._pace_control_loop()
                        continue

                    self.check_crosswalk(frame)
                    if config_city.DEBUG or config_city.STREAM:
                        self.handle_debug_stream(
                            result,
                            frame,
                            angle,
                            crosswalk,
                            "crosswalk",
                            self._format_crosswalk_status_text(
                                sign_text,
                                getattr(self, "_traffic_light_status", ""),
                            ),
                        )
                    self._pace_control_loop()
                    continue
                
                if crosswalk and time.time() - self.crosswalk_last_seen >= config_city.CROSSWALK_THRESH_SPEND:
                    self.control.stop()
                    time.sleep(2*config_city.DELAY)
                    self.check_crosswalk()
                    self._pace_control_loop()
                    continue
                
                if config_city.AUTO_UPDATE_KP:
                    self.control.update_kp(result["kp"])
                
                control_started = time.monotonic()
                if config_city.USE_PID:
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
                    config_city.speed_decision = {"target": target_speed, "reason": reason}
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
                                    config_city.OBJ_TOP_ROI, 
                                    config_city.OBJ_BOTTOM_ROI, 
                                    config_city.OBJ_LEFT_ROI, 
                                    config_city.OBJ_RIGHT_ROI
        )
        detected = self.object_detector.detect(object_frame)[1]
        logger.debug("Object detector result: %s", detected)

    @staticmethod
    def _format_crosswalk_status_text(sign_text, traffic_light_status):
        """Format optional marker/light status values without assuming strings."""
        parts = []
        for value in (sign_text, traffic_light_status):
            if value is None:
                continue
            value_text = str(value).strip()
            if value_text:
                parts.append(value_text)
        return " | ".join(parts)

    def _process_crosswalk_marker(self, frame, debug_frame):
        """Use the normal marker pipeline while the robot is in crosswalk mode."""
        if config_city.WITH_APRILTAG or config_city.WITH_SIGN:
            # Keep ROI handling, async sign inference, and the detector's
            # four-item AprilTag result contract in one shared code path.
            sign_text, _, debug_frame, _ = self.handle_read_sign_or_tag(
                frame,
                debug_frame,
            )
            return sign_text, debug_frame

        return "", debug_frame

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
            use_apriltag = bool(config_city.WITH_APRILTAG)
            use_sign = bool(config_city.WITH_SIGN)

        if not (use_sign or use_apriltag):
            return None, False, debug_frame, None

        sign_tag_frame = crop_image(
            frame,
            config_city.ST_TOP_ROI,
            config_city.ST_BOTTOM_ROI,
            config_city.ST_LEFT_ROI,
            config_city.ST_RIGHT_ROI,
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
                    self.read_sign_counter >= config_city.READ_SIGN_THRESHOLD
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
                max_age_s=getattr(config_city, "SIGN_RESULT_MAX_AGE", 0.75)
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


    def handle_debug_stream(self, result, frame, angle, crosswalk, status, sign_text):
        if config_city.DEBUG:
            debug = result.get("debug") or {}
            if debug.get("combined") is not None:
                cv2.imshow("combined", debug["combined"])
            if frame is not None:
                cv2.imshow("frame", frame)
            
        if config_city.STREAM:
            
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
                f"FPS: {self.fps.instant_fps:.1f}, RealFPS: {self.fps.second_fps:.1f}, Crosswalk:{crosswalk}, {status}",
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

            if getattr(config_city, "TAKE_PICTURE", False):
                try:
                    self.output.save_image(display_frame)
                except Exception as e:
                    logger.error(f"save_image failed: {e}")
                config_city.TAKE_PICTURE = False

            if getattr(config_city, "RECORD_VIDEO", False):
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

        if config_city.DEBUG:
            try:
                cv2.destroyAllWindows()
            except Exception:
                logger.exception("Cleanup failed: OpenCV windows")

        if not keep_dashboard and self.flask_thread and self.flask_thread.is_alive():
            try:
                stop_stream(config_city)
            except Exception:
                logger.exception("Failed to stop Flask stream")
            self.flask_thread.join(timeout=1.0)

        try:
            if getattr(config_city, 'arduino_connection', None) is self.control.connection:
                delattr(config_city, "arduino_connection")
        except Exception:
            logger.exception("Cleanup failed: serial state detach")


def start():
    robot = Robot()
    robot.flask_thread = None

    if config_city.STREAM:
        robot.flask_thread = threading.Thread(
            target=start_stream,
            args=(config_city,),
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
        shutdown_event = getattr(config_city, "SHUTDOWN_EVENT", None)
        try:
            while robot.flask_thread.is_alive():
                if shutdown_event is not None and shutdown_event.wait(0.5):
                    break
                if shutdown_event is None:
                    time.sleep(0.5)
        finally:
            if robot.flask_thread.is_alive():
                try:
                    stop_stream(config_city)
                except Exception:
                    logger.exception("Failed to stop diagnostic dashboard")
                robot.flask_thread.join(timeout=1.0)
