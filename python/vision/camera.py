from time import sleep
import time
import cv2
import logging
from utils.camera_calibration import CameraCalibration

try:
    from picamera2 import Picamera2
except ImportError:
    Picamera2 = None

logger = logging.getLogger(__name__)

class Camera:

    def __init__(self, config, width=None, height=None,
                 resize_width=None, resize_height=None,
                 mode=None):

        self.config = config
        setattr(self.config, "camera", self)
        
        self.width = width or getattr(self.config, 'CAM_WIDTH', 640)
        self.height = height or getattr(self.config, 'CAM_HEIGHT', 480)
        self.resize_width = resize_width or getattr(self.config, 'resize_width', 640)
        self.resize_height = resize_height or getattr(self.config, 'resize_height', 480)
        self.mode = mode or getattr(self.config, 'CAMERA_MODE', 'opencv')
        self.usbcam_addr = getattr(self.config, 'USBCAM_ADDR', 0)
        self.allow_picam_fallback = bool(
            getattr(self.config, 'CAMERA_FALLBACK_TO_OPENCV', False)
        )

        self.pi_mode = False
        self.camera_initialized = False
        self.last_capture_valid = False
        self.last_capture_at = None
        self.consecutive_failures = 0
        self.camera_calibration = CameraCalibration()

        if self.mode == "picam" and Picamera2 is not None:
            try:
                self.pi_mode = True
                self.picam = Picamera2()
                self.setup_camera()
                logger.info("Using Picamera2")
            except Exception:
                logger.exception("Failed to initialize Picamera2")
                self.pi_mode = False
                if not self.allow_picam_fallback:
                    raise
                logger.warning("Falling back to OpenCV camera by explicit configuration")
                self.cap = cv2.VideoCapture(self.usbcam_addr)
                self.setup_camera()
        else:
            self.pi_mode = False
            self.cap = cv2.VideoCapture(self.usbcam_addr)
            self.setup_camera()
            logger.info("Using OpenCV VideoCapture")

    def setup_camera(self):
        if self.pi_mode:
            try:
                config_pi = self.picam.create_preview_configuration(
                    main={"size": (self.width, self.height), "format": "RGB888"},
                    queue=False,
                )
                self.picam.configure(config_pi)
                
                self.picam.set_controls({
                    "FrameRate": 60.0,
                    "AeEnable": False,
                    "AwbEnable": False,
                    "ExposureTime": 16600, 
                    "AnalogueGain": 6.0, 
                })

                try:
                    pass
                except Exception as e:
                    logger.debug(f"Could not set manual camera controls: {e}")
                
                self.picam.start()
                sleep(2)
                self.camera_initialized = True
                
            except Exception as e:
                logger.error(f"Picamera2 setup failed: {e}")
                self.camera_initialized = False
                raise

        else:
            if self.mode == "picam" and Picamera2 is None and not self.allow_picam_fallback:
                raise RuntimeError(
                    "Picamera2 is unavailable for CAMERA_MODE='picam'; "
                    "enable CAMERA_FALLBACK_TO_OPENCV to allow webcam fallback"
                )

            # OpenCV camera setup
            if getattr(self, 'cap', None) is None or not self.cap.isOpened():
                self.cap = cv2.VideoCapture(self.usbcam_addr)
                
            if not self.cap.isOpened():
                logger.error("Failed to open webcam (index 0)")
                raise RuntimeError("No webcam detected.")
                
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            self.cap.set(cv2.CAP_PROP_FPS, 30)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            
            for _ in range(5): 
                ret, frame = self.cap.read()
                if ret and frame is not None:
                    self.camera_initialized = True
                    break
                sleep(0.1)
            
            if not self.camera_initialized:
                logger.error("Webcam test capture failed")
                raise RuntimeError("Webcam not functioning properly")
    
    def capture_frame(self, with_resize=True):

        started = time.monotonic()
        frame = None
        frame_resized = None
        self.last_capture_valid = False

        def finish(result_frame, result_resized, valid):
            self.last_capture_at = time.monotonic()
            metrics = getattr(self.config, "runtime_metrics", None)
            if metrics is not None:
                metrics.record_camera(
                    (time.monotonic() - started) * 1000.0,
                    valid,
                )
            return result_frame, result_resized

        if not self.camera_initialized:
            logger.error("Camera not initialized")
            return finish(frame, frame_resized, False)

        try:
            if self.pi_mode:
                frame = self.picam.capture_array()

                if frame is None or frame.size == 0:
                    logger.warning("Picamera2 returned empty frame")
                    self.consecutive_failures += 1
                    return finish(frame, frame_resized, False)

            else:
                ret, frame = self.cap.read()

                if not ret or frame is None:
                    logger.warning("OpenCV camera returned no frame")
                    self.consecutive_failures += 1
                    return finish(frame, frame_resized, False)

            frame = self.camera_calibration.undistort(frame)

            if with_resize:
                if frame.shape[:2] != (self.resize_height, self.resize_width):
                    frame_resized = cv2.resize(
                        frame,
                        (self.resize_width, self.resize_height),
                        interpolation=cv2.INTER_AREA
                    )
                else:
                    frame_resized = frame

            self.last_capture_valid = True
            self.consecutive_failures = 0
            return finish(frame, frame_resized, True)

        except Exception:
            self.consecutive_failures += 1
            logger.exception("Error capturing frame")
            return finish(frame, frame_resized, False)

    def release(self):
        self.camera_initialized = False
        self.last_capture_valid = False
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