import config_city 

from utils.config_mode import set_city_mode
set_city_mode()

from utils import json_config
json_config.load()

from manager.output_manager import OutputManager
from vision.camera import Camera
from vision.city_vision_processing import VisionProcessor
from vision.apriltag import ApriltagDetector
from traffic_sign_detector.detector import localization as sign_detector
from traffic_sign_detector.detector import get_model
from controller import controller
from config_city import (
    SPEED, SERVO_CENTER,
    TURN_LEFT, TURN_RIGHT, STRAIGHT, STOP)
from stream import start_stream
import logging
import cv2
import numpy as np
import time
import threading
import sys
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
        self.camera = Camera()
        self.control = controller
        self.vision = VisionProcessor()
        self.apriltag_detector = ApriltagDetector()
        self.crosswalk_time_start = 0
        self.crosswalk_last_seen = 0
        self.last_tag = None
        self.stop_last_seen = None
        self.model = get_model() if config_city.WITH_SIGN else None

        # OutputManager instance 
        self.output = OutputManager(config_module=config_city, output_dir=OUTPUT_DIR)

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
                if self.last_tag == TURN_RIGHT:
                     time.sleep(0.1)
                     self.control.forward_pulse(f"f {SPEED} 5 90 f {SPEED} 4 140")
                     time.sleep(0.1)
                elif self.last_tag == TURN_LEFT:
                    time.sleep(0.1)
                    self.control.forward_pulse(f"f {SPEED} 6 90 f {SPEED} 4 60")
                    time.sleep(0.1)
                elif self.last_tag == STRAIGHT:
                    time.sleep(0.1)
                    self.control.forward_pulse(f"f {SPEED} 9 95")
                    time.sleep(0.1)
                else:
                    time.sleep(0.1)
                    self.control.forward_pulse(f"f {SPEED}  10 95")
                    time.sleep(0.1)

    def run(self):
        logger.info("starting")
        prev_time = time.time()
        read_sign_counter = 0
        try:
            while True:
                if config_city.RUN_LVL == "STOP":
                    time.sleep(0.01)
                    self.control.stop()
                    time.sleep(0.01)
                    self.control.set_angle(SERVO_CENTER)
                    time.sleep(0.01)
                    
                    frame, frame_resized = self.camera.capture_frame(with_resize=True)
                    result = self.vision.detect(frame_resized, debug_frame)
                    
                    if config_city.STREAM:
                        curr_time = time.time()
                        fps = 1.0 / (curr_time - prev_time)
                        prev_time = curr_time
                        debug = result.get("debug") or {}
                        display_frame = debug["combined"].copy()
                        cv2.putText(display_frame, f"FPS: {fps:.1f}", (10, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                        
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

                    continue
                
                stop_seen = False
                if config_city.DEBUG:
                    cv2.waitKey(1)
                angle=SERVO_CENTER
                crosswalk = False
                
                if self.crosswalk_time_start == 0:
                    frame, frame_resized = self.camera.capture_frame(with_resize=True)
                    if config_city.STREAM or config_city.DEBUG:
                        debug_frame = frame.copy()
                    else:
                        debug_frame = None
                    
                    result = self.vision.detect(frame_resized, debug_frame)
        
                    angle = result.get("steering_angle")
                    crosswalk = result.get("crosswalk", False)
                    
                    if config_city.WITH_APRILTAG:
                        tags, debug_frame, largest_tag = self.apriltag_detector.detect(frame, debug_frame)
                        if largest_tag is not None:
                            tag_id = largest_tag["id"]
                            if largest_tag["corners"][1][1] > 180:
                                if tag_id == STOP:
                                    stop_seen = True
                                    self.stop_last_seen = time.time()
                                self.last_tag = tag_id
                    elif config_city.WITH_SIGN:
                        read_sign_counter += 1
                        tag_id = None
                        if read_sign_counter >= config_city.READ_SIGN_THRESHOLD:
                            read_sign_counter = 0
                            coordinate, debug_frame, sign_type, text = sign_detector(frame, debug_frame=debug_frame, model=self.model)
                            if text == "TURN LEFT":
                                tag_id = TURN_LEFT
                            elif text == "TURN RIGHT":
                                tag_id = TURN_RIGHT
                            elif text == "STRAIGHT":
                                tag_id = STRAIGHT
                            elif text == "STOP":
                                tag_id = STOP
                                stop_seen = True
                                self.stop_last_seen = time.time()
                        if tag_id is not None:
                            self.last_tag = tag_id

                    status = "stopped" if stop_seen or (self.stop_last_seen is not None and time.time() - self.stop_last_seen <= 1) else "running"
                
                    if config_city.DEBUG:
                        debug = result.get("debug") or {}
                        if debug.get("combined") is not None:
                            cv2.imshow("combined", debug["combined"])
                        if frame is not None:
                            cv2.imshow("frame", frame)
                        
                    if config_city.STREAM:
                        curr_time = time.time()
                        fps = 1.0 / (curr_time - prev_time)
                        prev_time = curr_time
                        debug = result.get("debug") or {}
                        display_frame = debug["combined"].copy()

                        text = f"FPS: {fps:.1f}, Crosswalk:{crosswalk}, {status}, angle:{angle:.1f}"
                        org = (10, 30)
                        font = cv2.FONT_HERSHEY_SIMPLEX
                        scale = 0.6
                        thickness = 2
                        
                        (text_width, text_height), baseline = cv2.getTextSize(text, font, scale, thickness)
                        pad = 4
                        x1, y1 = org[0]-pad, org[1]-text_height-pad
                        x2, y2 = org[0]+text_width+pad, org[1]+baseline+pad
                        roi = display_frame[max(0,y1):y2, max(0,x1):x2]

                        if roi.size > 0:
                            roi_blur = cv2.GaussianBlur(roi, (15,15), 0)
                            roi_white = cv2.addWeighted(roi_blur, 0.3, 255*np.ones_like(roi_blur, dtype=np.uint8), 0.7, 0)
                            display_frame[max(0,y1):y2, max(0,x1):x2] = roi_white

                        cv2.putText(display_frame, text, (org[0], org[1]), font, scale, (0,0,0), thickness)

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

                    if status == "stopped":
                        self.control.stop()
                        time.sleep(0.01)
                        continue
                    
                else:
                    self.control.stop()
                    time.sleep(0.1)
                    frame, frame_resized = self.camera.capture_frame(with_resize=True)
                    self.check_crosswalk()
                    
                    if config_city.DEBUG or config_city.STREAM:
                        debug_frame = frame.copy()
                        result = self.vision.detect(frame_resized, debug_frame)
                        angle = result.get("steering_angle")
                        crosswalk = result.get("crosswalk", False)

                        if config_city.WITH_APRILTAG:
                            tags, debug_frame, largest_tag = self.apriltag_detector.detect(frame, debug_frame)
                        elif config_city.WITH_SIGN:
                            coordinate, debug_frame, sign_type, text = sign_detector(frame, debug_frame=debug_frame, model=self.model)

                        if config_city.DEBUG:
                            debug = result.get("debug") or {}
                            if debug.get("combined") is not None:
                                cv2.imshow("combined", debug["combined"])
                            if frame is not None:
                                cv2.imshow("frame", frame)

                        if config_city.STREAM:
                            curr_time = time.time()
                            fps = 1.0 / (curr_time - prev_time)
                            prev_time = curr_time
                            debug = result.get("debug") or {}
                            display_frame = debug["combined"].copy()

                            text = f"FPS: {fps:.1f}, Crosswalk:{crosswalk}, stopped, time elapsed:{time.time() - self.crosswalk_last_seen:.1f}"
                            org = (10, 30)
                            font = cv2.FONT_HERSHEY_SIMPLEX
                            scale = 0.6
                            thickness = 2
                            
                            (text_width, text_height), baseline = cv2.getTextSize(text, font, scale, thickness)
                            pad = 4
                            x1, y1 = org[0]-pad, org[1]-text_height-pad
                            x2, y2 = org[0]+text_width+pad, org[1]+baseline+pad
                            roi = display_frame[max(0,y1):y2, max(0,x1):x2]

                            if roi.size > 0:
                                roi_blur = cv2.GaussianBlur(roi, (15,15), 0)
                                roi_white = cv2.addWeighted(roi_blur, 0.3, 255*np.ones_like(roi_blur, dtype=np.uint8), 0.7, 0)
                                display_frame[max(0,y1):y2, max(0,x1):x2] = roi_white

                            cv2.putText(display_frame, text, (org[0], org[1]), font, scale, (0,0,0), thickness)

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
                    
                    continue
                
                if crosswalk and time.time() - self.crosswalk_last_seen >= config_city.CROSSWALK_THRESH_SPEND:
                    self.control.stop()
                    time.sleep(0.1)
                    self.check_crosswalk()
                    continue
                
                self.control.set_angle(angle)
                time.sleep(0.01)
                self.control.set_speed(SPEED)  
                time.sleep(0.01)

        except KeyboardInterrupt:
            logger.error("error KeyboardInterrupt")
            
        except Exception as e:
            logger.error(f"error {e}")
        finally:
            self.close()
            logger.info("exited")
            
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
        
        if config_city.DEBUG:
            _(cv2.destroyAllWindows)()
            
        if config_city.STREAM:
            try:
                import requests
                requests.post("http://127.0.0.1:5000/shutdown")
            except Exception:
                pass

            if flask_thread.is_alive():
                flask_thread.join()
        sys.exit(0)

if __name__ == '__main__':
    if config_city.STREAM:
        flask_thread = threading.Thread(target=start_stream, daemon=False)
        flask_thread.start()
    robot = Robot()
    robot.run()
