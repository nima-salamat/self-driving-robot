# from vision.camera import Camera
# from vision.vision_processing import VisionProcessor
# from vision.apriltag import ApriltagDetector
# from controller import RobotController
# from base_config import SPEED, CROSSWALK_SLEEP, CROSSWALK_THRESH_SPEND
# import base_config
# import logging
# import cv2
# import time
# logging.disable(logging.DEBUG)
# logger = logging.getLogger(__name__)

# base_config.DEBUG = False

# class Robot:
#     def __init__(self):
#         self.camera = Camera()
#         self.control = RobotController()

#         self.vision = VisionProcessor()
#         self.apriltag_detector = ApriltagDetector()
#         self.crosswalk_time_start = 0
#         self.crosswalk_last_seen = 0
#         self.last_tag = None
        
#     def check_crosswalk(self, frame):
#         now = time.time()
#         if now - self.crosswalk_last_seen>= CROSSWALK_THRESH_SPEND:
#             # Only reset the crosswalk timer if it's not already running
#             self.crosswalk_time_start = now
#             self.crosswalk_last_seen = now
#             return True

#         # If crosswalk timer is running, check for elapsed time
#         if self.crosswalk_time_start != 0:
#             elapsed = now - self.crosswalk_time_start
#             if elapsed >= CROSSWALK_SLEEP:
#                 self.crosswalk_time_start = 0
           
#                 # Navigate based on last tag detected
#                 if self.last_tag == 12:
#                      time.sleep(0.1)
#                      self.control.forward_pulse(f"f {SPEED} 5 90 f {SPEED} 5 140")
#                      time.sleep(0.1)
#                 elif self.last_tag == 11:
#                     time.sleep(0.1)
#                     self.control.forward_pulse(f"f {SPEED} 7 90 f {SPEED} 5 40")
#                     time.sleep(0.1)
#                 elif self.last_tag == 6:
#                     pass
#                 elif self.last_tag == 119:
#                     time.sleep(0.1)
#                     self.control.forward_pulse(f"f {SPEED} 10 90")
#                     time.sleep(0.1)
#                 else:
#                     time.sleep(0.1)
#                     self.control.forward_pulse(f"f {SPEED} 10 90")
#                     time.sleep(0.1)


#             else:
#                 # Attempt to read AprilTag while the timer is running
#                 tags = self.apriltag_detector.detect(frame)
#                 if tags:
#                     first_tag = tags[0]
#                     tag_id = first_tag["id"]
#                     self.last_tag = tag_id
#                 return True

#         return False

                    
#     def run(self):
#         logger.info("starting")
#         try:
#             while True:
#                 if config_race.DEBUG:
#                     cv2.waitKey(1)
#                 angle=90
#                 crosswalk = False
#                 if self.crosswalk_time_start == 0: # 3 sec
#                     frame = self.camera.capture_frame()
                    
#                     result = self.vision.detect(frame)
        
#                     angle = result.get("steering_angle")
            
#                     crosswalk = result.get("crosswalk", False)
#                     if config_race.DEBUG:
#                         debug = result.get("debug") or {}
#                         if debug.get("combined") is not None:
#                             cv2.imshow("combined", debug.get("combined"))
#                         if frame is not None:
#                             cv2.imshow("frame", frame)

#                 else: # not 3 sec
#                     frame = self.camera.capture_frame(resize=False)
#                     self.control.stop()
#                     self.check_crosswalk(frame)
#                     continue
                
#                 if crosswalk and time.time() - self.crosswalk_last_seen >= CROSSWALK_THRESH_SPEND:
#                     self.check_crosswalk(frame)
#                     self.control.stop()
#                     continue
                
#                 self.control.set_angle(angle)
#                 time.sleep(0.01)
#                 self.control.set_speed(SPEED)  
#                 time.sleep(0.01)

#         except KeyboardInterrupt:
#             logger.error("error KeyboardInterrupt")
#         except Exception as e:
#             logger.error(f"error {e}")
#             print(e)
#         finally:
            
#             self.close()
#             logger.info("exited")
            
    
#     def close(self):
#         self.camera.release()
#         cv2.destroyAllWindows()
        

# if __name__ == '__main__':
#     robot = Robot()
#     robot.run()

from modes.city import city

city.start()