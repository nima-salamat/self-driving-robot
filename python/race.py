import config_race

from utils.config_mode import set_city_mode
set_city_mode()

from vision.camera import Camera
from vision.race_vision_processing import VisionProcessor
from vision.apriltag import ApriltagDetector
from controller import controller
from config_race import SPEED, default_height, default_width
import logging
import cv2
import time
logging.disable(logging.DEBUG)
logger = logging.getLogger(__name__)

config_race.DEBUG = True

class Robot:
    def __init__(self):
        self.camera = Camera()
        self.control = controller
        self.vision = VisionProcessor()
        self.apriltag_detector = ApriltagDetector()
        self.stop_last_seen = None

    def run(self):
        logger.info("starting")
        try:
            
            while True:
                tag = False
                if config_race.DEBUG:
                    cv2.waitKey(1)
                frame_at = self.camera.capture_frame(resize=False)
            
                frame = cv2.resize(frame_at, (default_width, default_height), interpolation=cv2.INTER_AREA)
                
                result = self.vision.detect(frame)                
                
                angle = result.get("steering_angle")
                tags, frame_at, _ = self.apriltag_detector.detect(frame_at)

                if isinstance(tags, list) and len(tags) > 0:
                        tag = tags[0]
                        if isinstance(tag, dict):
                            if "id" in tag:
                                tag_id = tag["id"]
                                if isinstance(tag_id, int):
                                    
                                    if tag_id == 5:
                                      
                                      if tags[0]["corners"][1][1] > 180:
                                      
                                        tag = True
                                        self.stop_last_seen = time.time()
                                        self.last_tag = tag_id
                                        
                                    else:
                                    
                                        pass                         
                                    
                if config_race.DEBUG:
                    debug = result.get("debug") or {}
                    if debug.get("combined") is not None:
                        cv2.imshow("combined", debug.get("combined"))
                    if frame is not None:
                            cv2.imshow("frame", frame)
                
                if tag or (self.stop_last_seen is not None and time.time() - self.stop_last_seen <= 1):
                    self.control.stop()
                    time.sleep(0.01)
                    
                    continue
                else:
                    
                    self.stop_last_seen = None
                
                self.control.set_angle(angle)
                time.sleep(0.01)
                self.control.set_speed(SPEED)  
                time.sleep(0.01)

        except KeyboardInterrupt:
            logger.error("error KeyboardInterrupt")
        except Exception as e:
            logger.error(f"error {e}")
            print(e)
        finally:
            
            self.close()
            logger.info("exited")
    
    def close(self):
        time.sleep(0.01)
        self.control.stop()
        time.sleep(0.01)
        self.control.set_angle(90)
        time.sleep(0.01)
        self.camera.release()
        cv2.destroyAllWindows()

if __name__ == '__main__':
    robot = Robot()
    robot.run()