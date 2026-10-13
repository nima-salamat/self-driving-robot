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
        
        # Calculate dynamic obstacle avoidance parameters
        lane_width = 30      # cm
        robot_width = 12     # cm (Approximate robot width)
        safe_margin = 3      # cm (Safety gap from the obstacle)
        pulse_cm = 0.5

        # Calculate required lateral shift to avoid center obstacle
        lateral_shift_cm = (lane_width / 2) - (robot_width / 2) + safe_margin

        center_angle = 90
        turn_angle_offset = 30  # 30 degrees deviation

        left_angle = center_angle - turn_angle_offset   # 60
        right_angle = center_angle + turn_angle_offset  # 120

        # Calculate hypotenuse distance needed for the lateral shift
        theta_radians = math.radians(turn_angle_offset)
        travel_distance_cm = lateral_shift_cm / math.sin(theta_radians)

        # Convert distances to pulses
        travel_pulse = int(travel_distance_cm / pulse_cm)

        # Command to shift LEFT (Avoid obstacle)
        # 1. Steer left (60) to move out
        # 2. Steer right (120) to straighten out in the new lane
        cmd_avoid_left = (
            f"set left "
            f"f 230 {travel_pulse} {left_angle} "
            f"f 230 {travel_pulse} {right_angle}"
        )

        # Command to shift RIGHT (Return to original lane after passing the object)
        # 1. Steer right (120) to move back in
        # 2. Steer left (60) to straighten out
        cmd_return_right = (
            f"set right "
            f"f 230 {travel_pulse} {right_angle} "
            f"f 230 {travel_pulse} {left_angle}"
        )

        # Send the hardcoded sequences with SET commands, without hello/cfg.
        # This firmware accepts one "save" command for both EEPROM sequences.
        if not getattr(config_race, "WITHOUT_ARDUINO", False):
            if not self._shutdown_requested():
                self.control.configure_lane_sequences(
                    cmd_avoid_left[len("set left "):],
                    cmd_return_right[len("set right "):],
                    persist=True,
                    command_delay_s=0.4,
                )


        self.vision = VisionProcessor()
        self.apriltag_detector = ApriltagDetector(config=config_race)
        self.last_tag = None
        self.stop_last_seen = None
        self.read_sign_counter = 0
        self.last_sign_result_id = 0
        self.stop_hold = StopSignHold(clear_confirmations=3)
        self.stop_hold_detector_kind = None
        self.last_sign_observation_fresh = False
        self.last_sign_observation_at = None
        self._last_stop_command_at = None
        
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
        """Update STOP latch state; non-fresh results cannot release it."""
        if not hasattr(self, "stop_hold"):
            self.stop_hold = StopSignHold(clear_confirmations=3)

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
        elif was_active and not self.stop_hold.active:
            self.stop_hold_detector_kind = None
        return self.stop_hold.active

    def _keep_stop_hold(self):
        """Send a STOP command on every control-loop cycle while STOP is latched."""
        first_command = getattr(self, "_last_stop_command_at", None) is None
        success = self.control.stop(
            reason="traffic_sign_stop_hold" if first_command else None
        )
        # If serial transmission failed, retry on the very next loop iteration.
        self._last_stop_command_at = time.monotonic() if success else None
        return bool(success)

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
        still_holding = self.stop_hold.active
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
                    self.control.stop()
                    self.control.set_angle(SERVO_CENTER)

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
                if self.metrics is not None:
                    self.metrics.record_perception(
                        (time.monotonic() - perception_started) * 1000.0,
                        bool(result.get("perception_valid", False)),
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
                        angle,
                        "STOP HOLD",
                        "STOP",
                    )
                    self._keep_stop_hold()
                    self._pace_control_loop()
                    continue

                if config_race.DETECT_OBJECT:
                    self.handle_detect_object(frame)

                # Publish the current debug frame regardless of marker configuration.
                self.handle_debug_stream(result, frame, angle, status, sign_text)
                    
                if config_race.AUTO_UPDATE_KP:
                    self.control.update_kp(result["kp"])
                
                control_started = time.monotonic()
                if config_race.USE_PID:
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

                self.control.set_speed(SPEED)
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

            should_check = bool(force_check)
            if force_check:
                # No READ_SIGN_THRESHOLD gate in the latched STOP state.
                self.read_sign_counter = 0
            else:
                self.read_sign_counter += 1
                should_check = (
                    self.read_sign_counter >= config_race.READ_SIGN_THRESHOLD
                )

            if should_check:
                self.read_sign_counter = 0
                submitted_at = time.monotonic()
                self.sign_detector.submit(
                    sign_tag_frame.copy(),
                    debug_frame.copy() if debug_frame is not None else None,
                )
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
                    self.last_sign_observation_at = latest_sign[2] or submitted_at

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
            ("center servo", lambda: self.control.set_angle(90)),
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
