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
from controller import RobotController
from modes.race.config_race import (
    SPEED, HARDCODE_SPEED, SERVO_CENTER,
    TURN_LEFT, TURN_RIGHT, STRAIGHT, STOP, USE_SIGN)
from stream import start_stream
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

        # Send commands to Arduino only when hardware control is enabled.
        if not getattr(config_race, "WITHOUT_ARDUINO", False):
            self.control._send_command(cmd_avoid_left)
            time.sleep(0.4)
            self.control._send_command("save left")
            time.sleep(0.4)
            self.control._send_command(cmd_return_right)
            time.sleep(0.4)
            self.control._send_command("save right")
            time.sleep(0.4)


        self.vision = VisionProcessor()
        self.apriltag_detector = ApriltagDetector(config=config_race)
        self.last_tag = None
        self.stop_last_seen = None
        self.read_sign_counter = 0
        self.last_sign_result_id = 0
        
        # Initialize sign detector strictly based on USE_SIGN variable
        if USE_SIGN:
            detector = SVMTrafficSignDetector() if config_race.SIGN_DETECTOR_METHOD == "svm" else YOLOTrafficSignDetector()
            self.sign_detector = AsyncSignDetector(detector)
        else:
            self.sign_detector = None
        setattr(config_race, "sign_detector", self.sign_detector)
            
        # OutputManager instance 
        self.output = OutputManager(config_module=config_race, output_dir=OUTPUT_DIR)
        self.fps = FPS(config=config_race)
        self.object_detector = ObjectDetector()

        if self.health is not None:
            from utils.health import HealthState
            self.health.set_lifecycle(HealthState.READY)

    def _pace_control_loop(self):
        period = max(0.001, float(getattr(config_race, "CONTROL_PERIOD", 0.01)))
        self._next_control_time += period
        delay = self._next_control_time - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        else:
            self._next_control_time = time.monotonic()

    def update_debug_frames(self, frame):
        config_race.debug_frames_list.append(frame)
        config_race.stream_frame_seq = getattr(config_race, "stream_frame_seq", 0) + 1

   
    def _shutdown_requested(self):
        event = getattr(config_race, "SHUTDOWN_EVENT", None)
        return bool(event is not None and event.is_set())

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
                if not result.get("perception_valid", False):
                    self.control.stop()
                    self._pace_control_loop()
                    continue

                angle = result.get("steering_angle")
                
                # Defaults fallback when USE_SIGN is False to prevent breaking the loop
                status = "running"
                sign_text = "None"
                
                if USE_SIGN:
                    sign_text, stop_seen, debug_frame, coordinate = self.handle_read_sign_or_tag(frame, debug_frame)

                    status = "stopped" if stop_seen or (self.stop_last_seen is not None and time.time() - self.stop_last_seen <= 2) else "running"
                 
                    if config_race.DETECT_OBJECT:
                        self.handle_detect_object(frame)
                    
                    if coordinate is not None:
                        (x1, y1), (x2, y2) = coordinate
                        width = x2 - x1
                        height = y2 - y1
                        area = width * height
                        if area < 5000:
                            status = "running"
                            self.stop_last_seen = None
                            
                    if status == "stopped":
                        self.handle_debug_stream(result, frame, angle, status, sign_text)
                        self.control.stop()
                        time.sleep(config_race.DELAY)
                        self._pace_control_loop()
                        continue
                    
                # Unconditionally process debug stream outside USE_SIGN to maintain camera feed
                self.handle_debug_stream(result, frame, angle, status, sign_text)
                    
                if config_race.AUTO_UPDATE_KP:
                    self.control.update_kp(result["kp"])
                
                control_started = time.monotonic()
                if config_race.USE_PID:
                    self.control.set_angle_by_error(result["error"], result["lane_type"])
                else:
                    self.control.set_angle(result["steering_angle"])

                self.control.set_speed(SPEED)
                if self.metrics is not None:
                    self.metrics.record_control(
                        (time.monotonic() - control_started) * 1000.0
                    )
                self._pace_control_loop()

        except KeyboardInterrupt:
            logger.error("error KeyboardInterrupt")
            
        except Exception as e:
            logger.exception("Unhandled robot loop exception")
        finally:
            self.close()
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

    def handle_read_sign_or_tag(self, frame, debug_frame):
        # Strict fallback: Skip all processing if USE_SIGN is disabled
        if not USE_SIGN:
            return None, False, debug_frame, None
            
        sign_tag_frame = crop_image(frame, 
                                    config_race.ST_TOP_ROI, 
                                    config_race.ST_BOTTOM_ROI, 
                                    config_race.ST_LEFT_ROI, 
                                    config_race.ST_RIGHT_ROI
        )
        
        stop_seen = False
        coordinate = None
        if config_race.WITH_APRILTAG:
            tags, debug_frame, largest_tag, coordinate = self.apriltag_detector.detect(sign_tag_frame, debug_frame)
            if largest_tag is not None:
                tag_id = largest_tag["id"]
                if largest_tag["corners"][1][1] > 180:
                    if tag_id == STOP:
                        stop_seen = True
                        self.stop_last_seen = time.time()
                    self.last_tag = tag_id
        elif config_race.WITH_SIGN:
            self.read_sign_counter += 1
            tag_id = None
            if self.read_sign_counter >= config_race.READ_SIGN_THRESHOLD:
                self.read_sign_counter = 0
                self.sign_detector.submit(sign_tag_frame.copy(), debug_frame.copy() if debug_frame is not None else None)
                latest_sign = self.sign_detector.latest()
                if latest_sign is None or latest_sign[0] <= self.last_sign_result_id:
                    return None, False, debug_frame, None
                self.last_sign_result_id = latest_sign[0]
                sign_result = latest_sign[1]
                coordinate = sign_result["coordinate"]
                debug_frame = sign_result["debug_frame"]
                if sign_result['text'] == "TURN LEFT":
                    tag_id = TURN_LEFT
                elif sign_result['text'] == "TURN RIGHT":
                    tag_id = TURN_RIGHT
                elif sign_result['text'] == "STRAIGHT":
                    tag_id = STRAIGHT
                elif sign_result['text'] == "STOP":
                    tag_id = STOP
                    stop_seen = True
                    self.stop_last_seen = time.time()
            if tag_id is not None:
                self.last_tag = tag_id
            
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
            display_frame = debug["combined"].copy()
            texts = [
                f"FPS: {self.fps.instant_fps:.1f}, RealFPS: {self.fps.second_fps:.1f}, {status}",
                f"Angle:{angle:.1f}, RealAngle:{self.control.last_angle:.1f}, Sign:{sign_text}, LastTag:{self.last_tag}",
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

            config_race.debug_frames_list = []
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

    def close(self):
        if self.health is not None:
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

        if self.flask_thread and self.flask_thread.is_alive():
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
