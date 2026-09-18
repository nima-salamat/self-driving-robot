import modes.city.config_city as config_city 

from utils.config_mode import set_city_mode
# set_city_mode()
from utils import json_config

from manager.output_manager import OutputManager
from vision.camera import Camera
from vision.city_vision_processing import VisionProcessor
from vision.apriltag import ApriltagDetector
from vision.object_detector import ObjectDetector
from traffic_sign_detector.svm_detector import TrafficSignDetector as SVMTrafficSignDetector
from traffic_sign_detector.yolo_detector import TrafficSignDetector as YOLOTrafficSignDetector
from traffic_sign_detector.async_detector import AsyncSignDetector
from controller import RobotController
from modes.city.config_city import (
    SPEED, HARDCODE_SPEED, SERVO_CENTER,
    TURN_LEFT, TURN_RIGHT, STRAIGHT, STOP)
from stream import start_stream
import logging
import cv2
import numpy as np
import time
import threading
import sys
from utils.fps import FPS
from utils.roi_manager import crop_image


logging.disable(logging.DEBUG)
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
        self.camera = Camera(config=config_city)
        self.control = RobotController(config=config_city)
        config_city.arduino_connection = self.control.connection
        self.flask_thread = None
        self._next_control_time = time.monotonic()

        # hardcode the left and right lane change
        if not getattr(config_city, "WITHOUT_ARDUINO", False):
            self.control._send_command("set left b 170 110 70 b 170 80 125")
            time.sleep(0.4)
            self.control._send_command("set right f 170 70 125 f 170 70 70")
            time.sleep(0.4)

        self.vision = VisionProcessor()
        self.apriltag_detector = ApriltagDetector(config=config_city)
        self.crosswalk_time_start = 0
        self.crosswalk_last_seen = 0
        self.last_tag = None
        self.stop_last_seen = None
        self.read_sign_counter = 0
        self.last_sign_result_id = 0
        detector = SVMTrafficSignDetector() if config_city.SIGN_DETECTOR_METHOD == "svm" else YOLOTrafficSignDetector()
        self.sign_detector = AsyncSignDetector(detector)
        # OutputManager instance 
        self.output = OutputManager(config_module=config_city, output_dir=OUTPUT_DIR)
        self.fps = FPS()
        self.object_detector = ObjectDetector()

    def _pace_control_loop(self):
        period = max(0.001, float(getattr(config_city, "CONTROL_PERIOD", 0.01)))
        self._next_control_time += period
        delay = self._next_control_time - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        else:
            self._next_control_time = time.monotonic()

    def update_debug_frames(self, frame):
        config_city.debug_frames_list.append(frame)

    def check_crosswalk(self):
        now = time.time()
        if now - self.crosswalk_last_seen>= config_city.CROSSWALK_THRESH_SPEND:
            self.crosswalk_time_start = now
            self.crosswalk_last_seen = now

        if self.crosswalk_time_start != 0:
            elapsed = now - self.crosswalk_time_start
            if elapsed >= config_city.CROSSWALK_SLEEP:
                self.crosswalk_time_start = 0
                logger.debug(f"navigate with tag: {self.last_tag}")
                self.control.set_angle(90)
                time.sleep(0.3)
                
                if self.last_tag == TURN_RIGHT:
                    self.control.signal_right()
                    time.sleep(0.1)
                    self.control.forward_pulse(f"f {HARDCODE_SPEED} 50 70 f {HARDCODE_SPEED} 170 120")
                    time.sleep(0.1)
                elif self.last_tag == TURN_LEFT:
                    self.control.signal_left()
                    time.sleep(0.1)
                    self.control.forward_pulse(f"f {HARDCODE_SPEED} 120 90 f {HARDCODE_SPEED} 120 60")
                    time.sleep(0.1)
                elif self.last_tag == STRAIGHT:
                    time.sleep(0.1)
                    self.control.forward_pulse(f"f {HARDCODE_SPEED} 220 90")
                    time.sleep(0.1)
                else:
                    time.sleep(0.1)
                    self.control.forward_pulse(f"f {HARDCODE_SPEED}  220 90")
                    time.sleep(0.1)

    def run(self):
        logger.info("starting")
        self.fps.start()
        try:
            while True:
                self.fps.update()
                if config_city.RUN_LVL == "STOP":
                    self.control.stop()
                    self.control.set_angle(SERVO_CENTER)

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
                
                if self.crosswalk_time_start == 0:
                    frame, frame_resized = self.camera.capture_frame(with_resize=True)
                    if not self.camera.last_capture_valid or frame_resized is None:
                        self.control.stop()
                        continue
                    if config_city.STREAM or config_city.DEBUG:
                        debug_frame = frame.copy()
                    else:
                        debug_frame = None
                    
                    result = self.vision.detect(frame_resized, debug_frame)
                    if not result.get("perception_valid", True):
                        self.control.stop()
                        continue

                    angle = result.get("steering_angle")
                    crosswalk = result.get("crosswalk", False)
                    
                    sign_text, stop_seen, debug_frame, coordinate = self.handle_read_sign_or_tag(frame, debug_frame)

                    status = "stopped" if stop_seen or (self.stop_last_seen is not None and time.time() - self.stop_last_seen <= 2) else "running"

                    self.handle_debug_stream(result, frame, angle, crosswalk, status, sign_text)                    
                    if config_city.DETECT_OBJECT:
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
                        self.control.stop()
                        time.sleep(config_city.DELAY)
                        continue
                    
                else:
                    self.control.stop()
                    time.sleep(2*config_city.DELAY)
                    frame, frame_resized = self.camera.capture_frame(with_resize=True)
                    if not self.camera.last_capture_valid or frame_resized is None:
                        self.control.stop()
                        continue
                    self.check_crosswalk()
                    result = {
                        "steering_angle": SERVO_CENTER,
                        "error": 0,
                        "lane_type": "crosswalk",
                        "perception_valid": True,
                        "crosswalk": True,
                        "debug": {"combined": frame},
                    }

                    if config_city.DEBUG or config_city.STREAM:
                        debug_frame = frame.copy()
                        result = self.vision.detect(frame_resized, debug_frame)
                        angle = result.get("steering_angle")
                        crosswalk = result.get("crosswalk", False)

                        if config_city.WITH_APRILTAG:
                            tags, debug_frame, largest_tag = self.apriltag_detector.detect(frame, debug_frame)
                        elif config_city.WITH_SIGN:
                            self.sign_detector.process_frame(frame, debug_frame=debug_frame)

                    self.handle_debug_stream(result, frame, angle, crosswalk, "crosswalk", "")
                    
                    continue
                
                if crosswalk and time.time() - self.crosswalk_last_seen >= config_city.CROSSWALK_THRESH_SPEND:
                    self.control.stop()
                    time.sleep(2*config_city.DELAY)
                    self.check_crosswalk()
                    continue
                
                if config_city.AUTO_UPDATE_KP:
                    self.control.update_kp(result["kp"])
                
                if config_city.USE_PID:
                    self.control.set_angle_by_error(result["error"], result["lane_type"])
                else:
                    self.control.set_angle(result["steering_angle"])
                    
                self.control.set_speed(SPEED)
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
                                    config_city.OBJ_TOP_ROI, 
                                    config_city.OBJ_BOTTOM_ROI, 
                                    config_city.OBJ_LEFT_ROI, 
                                    config_city.OBJ_RIGHT_ROI
        )
        detected = self.object_detector.detect(object_frame)[1]
        logger.debug("Object detector result: %s", detected)

    def handle_read_sign_or_tag(self, frame, debug_frame):
        
        sign_tag_frame = crop_image(frame, 
                                    config_city.ST_TOP_ROI, 
                                    config_city.ST_BOTTOM_ROI, 
                                    config_city.ST_LEFT_ROI, 
                                    config_city.ST_RIGHT_ROI
        )
        
        stop_seen = False
        coordinate = None
        if config_city.WITH_APRILTAG:
            tags, debug_frame, largest_tag, coordinate = self.apriltag_detector.detect(sign_tag_frame, debug_frame)
            if largest_tag is not None:
                tag_id = largest_tag["id"]
                if largest_tag["corners"][1][1] > 180:
                    if tag_id == STOP:
                        stop_seen = True
                        self.stop_last_seen = time.time()
                    self.last_tag = tag_id
        elif config_city.WITH_SIGN:
            self.read_sign_counter += 1
            tag_id = None
            if self.read_sign_counter >= config_city.READ_SIGN_THRESHOLD:
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


    def handle_debug_stream(self, result, frame, angle, crosswalk, status, sign_text):
        if config_city.DEBUG:
            debug = result.get("debug") or {}
            if debug.get("combined") is not None:
                cv2.imshow("combined", debug["combined"])
            if frame is not None:
                cv2.imshow("frame", frame)
            
        if config_city.STREAM:
            
            debug = result.get("debug") or {}
            display_frame = debug["combined"].copy()
            texts = [
                f"FPS: {self.fps.instant_fps:.1f}, RealFPS: {self.fps.second_fps:.1f}, Crosswalk:{crosswalk}, {status}",
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

            config_city.debug_frames_list = []
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

    def close(self):
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

        if config_city.DEBUG:
            try:
                cv2.destroyAllWindows()
            except Exception:
                logger.exception("Cleanup failed: OpenCV windows")

        if self.flask_thread and self.flask_thread.is_alive():
            self.flask_thread.join(timeout=1.0)

        try:
            if getattr(config_city, 'arduino_connection', None) is self.control.connection:
                delattr(config_city, "arduino_connection")
        except Exception:
            logger.exception("Cleanup failed: serial state detach")

        sys.exit(0)

def start():
    json_config.load()

    if config_city.STREAM:
        flask_thread = threading.Thread(
            target=start_stream,
            args=(config_city,),
            daemon=True,
            name="flask-stream",
        )
        flask_thread.start()
    robot = Robot()
    robot.flask_thread = flask_thread if config_city.STREAM else None
    robot.run()
