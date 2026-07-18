import modes.race.config_race as config_race 

from utils.config_mode import set_race_mode
# set_race_mode()

from utils import json_config

from manager.output_manager import OutputManager
from vision.camera import Camera
from vision.race_vision_processing import VisionProcessor
from vision.apriltag import ApriltagDetector
from vision.object_detector import ObjectDetector
from traffic_sign_detector.svm_detector import TrafficSignDetector as SVMTrafficSignDetector
from traffic_sign_detector.yolo_detector import TrafficSignDetector as YOLOTrafficSignDetector
from controller import RobotController
from modes.race.config_race import (
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

# keep defaults (config_race can override)
OUTPUT_DIR = getattr(config_race, "OUTPUT_DIR", "output")
VIDEO_FPS = getattr(config_race, "VIDEO_FPS", 20)
VIDEO_CODEC = getattr(config_race, "VIDEO_CODEC", "mp4v")

if not hasattr(config_race, "debug_frames_list") or not isinstance(config_race.debug_frames_list, list):
    config_race.debug_frames_list = [None, None]

config_race.DEBUG = False


class Robot:
    def __init__(self):
        self.camera = Camera(config=config_race)
        self.control = RobotController(config=config_race)

        self.vision = VisionProcessor()
        self.apriltag_detector = ApriltagDetector(config=config_race)
        self.last_tag = None
        self.stop_last_seen = None
        self.read_sign_counter = 0
        self.sign_detector = SVMTrafficSignDetector() if config_race.SIGN_DETECTOR_METHOD == "svm" else YOLOTrafficSignDetector()
        # OutputManager instance 
        self.output = OutputManager(config_module=config_race, output_dir=OUTPUT_DIR)
        self.fps = FPS()
        self.object_detector = ObjectDetector()

    def update_debug_frames(self, frame):
        config_race.debug_frames_list.append(frame)

   
    def run(self):
        logger.info("starting")
        self.fps.start()
        try:
            while True:
                self.fps.update()
                if config_race.RUN_LVL == "STOP":
                    time.sleep(config_race.DELAY)
                    self.control.stop()
                    time.sleep(config_race.DELAY)
                    self.control.set_angle(SERVO_CENTER)
                    time.sleep(config_race.DELAY)
                    
                    frame, frame_resized = self.camera.capture_frame(with_resize=True)
                    debug_frame=None
                    result = self.vision.detect(frame_resized, debug_frame=None)
                    self.handle_debug_stream(result, frame, SERVO_CENTER, False, "stopped")
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
                angle=SERVO_CENTER
            
            
                frame, frame_resized = self.camera.capture_frame(with_resize=True)
                if config_race.STREAM or config_race.DEBUG:
                    debug_frame = frame.copy()
                else:
                    debug_frame = None
                
                result = self.vision.detect(frame_resized, debug_frame)

                angle = result.get("steering_angle")
                
                sign_text, stop_seen, debug_frame, coordinate = self.handle_read_sign_or_tag(frame, debug_frame)

                status = "stopped" if stop_seen or (self.stop_last_seen is not None and time.time() - self.stop_last_seen <= 2) else "running"

                self.handle_debug_stream(result, frame, angle, status, sign_text)                    
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
                    self.control.stop()
                    time.sleep(config_race.DELAY)
                    continue
                
                
                if config_race.AUTO_UPDATE_KP:
                    self.control.update_kp(result["kp"])
                
                if config_race.USE_PID:
                    self.control.set_angle_by_error(result["error"], result["lane_type"])
                else:
                    self.control.set_angle(result["steering_angle"])
                    
                time.sleep(config_race.DELAY)
                self.control.set_speed(SPEED)  
                time.sleep(config_race.DELAY)

        except KeyboardInterrupt:
            logger.error("error KeyboardInterrupt")
            
        except Exception as e:
            logger.error(f"error {e}")
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
        print(self.object_detector.detect(object_frame)[1])

    def handle_read_sign_or_tag(self, frame, debug_frame):
        
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
                sign_result = self.sign_detector.process_frame(sign_tag_frame, debug_frame=debug_frame)
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

    def safe(self, func):
        def wrapper(*args, **kwargs):
            val =  None
            try:
                val = func(*args, **kwargs)
            except Exception:
                pass

            return val
        return wrapper
        
    def close(self):
        _ = self.safe
        _(self.control.stop)()
        _(self.control.set_angle)(90)
        _(self.camera.release)()
        _(self.control.connection.close)() # close serial connection

        # release output manager resources
        try:
            self.output.close()
        except Exception:
            pass
        
        if config_race.DEBUG:
            _(cv2.destroyAllWindows)()
            
        if config_race.STREAM:
            try:
                import requests
                requests.post("http://127.0.0.1:5000/shutdown")
            except Exception:
                pass

            if flask_thread.is_alive():
                flask_thread.join()
        sys.exit(0)

def start():
    json_config.load()

    if config_race.STREAM:
        flask_thread = threading.Thread(
            target=start_stream, 
            args=(config_race,), 
            daemon=False
        )
        flask_thread.start()
    robot = Robot()
    robot.run()
