import base_config
import config_city 
base_config.MODE="city"
base_config.CONFIG_MODULE = config_city
import os
import json
try:
    if config_city.CHANGE_WITH_JSON:
        if os.path.exists("city.json"):
            with open("city.json", "r") as f:
                configs = json.loads(f.read())
                for conf_name, value in configs.items():
                    setattr(config_city, conf_name, value)
except json.JSONDecodeError:
    pass
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
import time
import threading
import sys
logging.disable(logging.DEBUG)
logger = logging.getLogger(__name__)

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
        
    def check_crosswalk(self):
        now = time.time()
        if now - self.crosswalk_last_seen>= config_city.CROSSWALK_THRESH_SPEND:
            # Only reset the crosswalk timer if it's not already running
            self.crosswalk_time_start = now
            self.crosswalk_last_seen = now

        # If crosswalk timer is running, check for elapsed time
        if self.crosswalk_time_start != 0:
            elapsed = now - self.crosswalk_time_start
            if elapsed >= config_city.CROSSWALK_SLEEP:
                self.crosswalk_time_start = 0
                logger.debug(f"navigate with tag: {self.last_tag}")
                # Navigate based on last tag detected
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


                    result = self.vision.detect(frame_resized)
                    
                    if config_city.STREAM:
                        curr_time = time.time()
                        fps = 1.0 / (curr_time - prev_time)
                        prev_time = curr_time
                        debug = result.get("debug") or {}
                        display_frame = debug.get("combined").copy()
                        cv2.putText(display_frame, f"FPS: {fps:.1f}", (10, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                        config_city.debug_frame_buffer = display_frame
                    continue
                
                stop_seen = False
                if config_city.DEBUG:
                    cv2.waitKey(1)
                angle=SERVO_CENTER
                crosswalk = False
                
                if self.crosswalk_time_start == 0: # 3 sec
                    frame, frame_resized = self.camera.capture_frame(with_resize=True)
                    if config_city.STREAM or config_city.DEBUG:
                        debug_frame = frame.copy()
                    else:
                        debug_frame = None
                    
                    result = self.vision.detect(frame_resized, debug_frame)
        
                    angle = result.get("steering_angle")
            
                    crosswalk = result.get("crosswalk", False)
                    
                    if config_city.WITH_APRILTAG:
                        
                        tags, frame_at, largest_tag = self.apriltag_detector.detect(frame, debug_frame)
                        
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
                                               
                                     
                    if stop_seen or (self.stop_last_seen is not None and time.time() - self.stop_last_seen <= 1):
                        self.control.stop()
                        time.sleep(0.01)
                        continue
                
                    if config_city.DEBUG: 
                        debug = result.get("debug") or {}
                        if debug.get("combined") is not None:
                            cv2.imshow("combined", debug.get("combined"))
                        if frame is not None:
                            cv2.imshow("frame", frame)
                        if frame_at is not None:
                            cv2.imshow("at", frame_at)
             
                    if config_city.STREAM:
                        curr_time = time.time()
                        fps = 1.0 / (curr_time - prev_time)
                        prev_time = curr_time
                        debug = result.get("debug") or {}
                        display_frame = debug.get("combined").copy()
                        cv2.putText(display_frame, f"FPS: {fps:.1f}", (10, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                        config_city.debug_frame_buffer = display_frame
                    
                else: # not 3 sec
                    self.control.stop()
                    time.sleep(0.1)
                    frame, _ = self.camera.capture_frame(with_resize=False)
                    self.check_crosswalk()
                    if config_city.STREAM:
                        config_city.debug_frame_buffer = frame
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
            finally:
                return val
        return wrapper
        
    def close(self):
        _ = self.safe
        _(self.control.stop)()
        _(self.control.set_angle)(90)
        _(self.camera.release)()
        _(self.control.connection.close)() # close serial connection
        
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