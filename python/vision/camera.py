import base_config as temp_conf
from utils.camera_calibration import CameraCalibration

if temp_conf.CONFIG_MODULE is not None:
    conf = temp_conf.CONFIG_MODULE
else:
    conf = temp_conf

try:
    from picamera2 import Picamera2
except ImportError:
    Picamera2 = None

from time import sleep
import cv2
import logging

logger = logging.getLogger(__name__)

class Camera:
    def __init__(self, width=conf.CAM_WIDTH, height=conf.CAM_HEIGHT,resize_width=conf.resize_width, resize_height=conf.resize_height, mode=conf.CAMERA_MODE):
        self.width = width
        self.height = height
        self.resize_width = resize_width
        self.resize_height = resize_height
        
        self.mode = mode
        self.pi_mode = False
        self.camera_initialized = False
        self.camera_calibration = CameraCalibration()


        # Initialize camera based on mode
        if mode == "picam" and Picamera2 is not None:
            try:
                self.pi_mode = True
                self.picam = Picamera2()
                self.setup_camera()
                logger.info("Using Picamera2")
            except Exception as e:
                logger.error(f"Failed to initialize Picamera2: {e}")
                logger.info("Falling back to OpenCV")
                self.pi_mode = False
                self.cap = cv2.VideoCapture(conf.USBCAM_ADDR)
                self.setup_camera()
        else:
            self.pi_mode = False
            self.cap = cv2.VideoCapture(conf.USBCAM_ADDR)
            self.setup_camera()
            logger.info("Using OpenCV VideoCapture")

    def setup_camera(self):
        if self.pi_mode:
            try:
                config = self.picam.create_preview_configuration(
                    main={"size": (self.width, self.height), "format": "RGB888"}
                )
                self.picam.configure(config)
                
                self.picam.set_controls({
                    "FrameRate": 60.0,
                    "AeEnable": False,
                    "AwbEnable": False,
                    "ExposureTime": 16600, 
                    "AnalogueGain": 6.0, 
                })

                # Try to set controls, but continue if it fails
                try:
                    #                     self.picam.set_controls({
                    #        "AeEnable": True,
                    #     "AwbEnable": True,
                    #     "AnalogueGain": 3.0, 
                    #     "ExposureTime": 50000,  
                    
                    # })                
                    pass


                except Exception as e:
                    logger.debug(f"Could not set manual camera controls: {e}")
                
                self.picam.start()
                sleep(2)  # Give camera more time to initialize
                self.camera_initialized = True
                
            except Exception as e:
                logger.error(f"Picamera2 setup failed: {e}")
                self.camera_initialized = False
                raise

        else:
            # OpenCV camera setup
            if not self.cap.isOpened():
                # Try to reopen
                self.cap = cv2.VideoCapture(conf.USBCAM_ADDR)
                
            if not self.cap.isOpened():
                logger.error("Failed to open webcam (index 0)")
                raise RuntimeError("No webcam detected.")
                
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self.cap.set(cv2.CAP_PROP_FPS, 30)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            # Test capture
            for _ in range(5):  # Try a few times
                ret, frame = self.cap.read()
                if ret and frame is not None:
                    self.camera_initialized = True
                    break
                sleep(0.1)
            
            if not self.camera_initialized:
                logger.error("Webcam test capture failed")
                raise RuntimeError("Webcam not functioning properly")
    
    def capture_frame(self, with_resize=True):

        frame = None
        frame_resized = None

        if not self.camera_initialized:
            logger.error("Camera not initialized")
            return frame, frame_resized

        try:

            if self.pi_mode:

                frame = self.picam.capture_array()

                if frame is None or frame.size == 0:
                    logger.warning("Picamera2 returned empty frame")
                    return frame, frame_resized

            else:

                ret, frame = self.cap.read()

                if not ret or frame is None:
                    logger.warning("OpenCV camera returned no frame")
                    return frame, frame_resized


            # Apply lens distortion correction
            frame = self.camera_calibration.undistort(frame)


            if with_resize:

                if frame.shape[:2] != (
                    self.resize_height,
                    self.resize_width
                ):

                    frame_resized = cv2.resize(
                        frame,
                        (self.resize_width, self.resize_height),
                        interpolation=cv2.INTER_AREA
                    )


            return frame, frame_resized


        except Exception as e:

            logger.error(
                f"Error capturing frame: {e}"
            )

            return frame, frame_resized

    def release(self):
        self.camera_initialized = False
        if self.pi_mode:
            try:
                self.picam.stop()
                self.picam.close()
            except Exception as e:
                logger.error(f"Error releasing Picamera2: {e}")
        else:
            try:
                self.cap.release()
            except Exception as e:
                logger.error(f"Error releasing OpenCV camera: {e}")
