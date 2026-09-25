from time import sleep
import time
import cv2
import logging
from collections import deque
from calibration.calibrator import CameraCalibration

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
        self.requested_frame_rate = None
        self.measured_frame_rate = None
        self._capture_timestamps = deque(maxlen=120)
        self.camera_calibration = CameraCalibration(
            enabled=bool(getattr(self.config, "APPLY_CAMERA_CALIBRATION", True))
        )

        if self.mode == "picam" and Picamera2 is not None:
            try:
                self.pi_mode = True
                self.picam = Picamera2()
                self.setup_camera()
                logger.info("Using Picamera2")
            except Exception:
                logger.exception("Failed to initialize Picamera2")
                self._cleanup_failed_initialization()
                if not self.allow_picam_fallback:
                    raise
                logger.warning("Falling back to OpenCV camera by explicit configuration")
                self.pi_mode = False
                self.cap = cv2.VideoCapture(self.usbcam_addr)
                try:
                    self.setup_camera()
                except Exception:
                    self._cleanup_failed_initialization()
                    raise
        else:
            self.pi_mode = False
            self.cap = cv2.VideoCapture(self.usbcam_addr)
            try:
                self.setup_camera()
            except Exception:
                self._cleanup_failed_initialization()
                raise
            logger.info("Using OpenCV VideoCapture")

    def _cleanup_failed_initialization(self):
        self.camera_initialized = False
        try:
            if self.pi_mode and getattr(self, "picam", None) is not None:
                self.picam.stop()
                self.picam.close()
        except Exception:
            logger.exception("Failed to clean up Picamera2 after initialization failure")
        try:
            cap = getattr(self, "cap", None)
            if cap is not None:
                cap.release()
        except Exception:
            logger.exception("Failed to clean up OpenCV camera after initialization failure")
        self.picam = None
        self.cap = None

    def setup_camera(self):
        if self.pi_mode:
            try:
                config_pi = self.picam.create_preview_configuration(
                    main={"size": (self.width, self.height), "format": "RGB888"},
                    queue=False,
                )
                self.picam.configure(config_pi)
                
                self.picam.set_controls({
                    "AeEnable": False,
                    "AwbEnable": False,
                    "ExposureTime": 16600,
                    "AnalogueGain": 6.0,
                })
                
                self.picam.start()
                sleep(2)
                self.camera_initialized = True
                target_fps = getattr(
                    self.config,
                    "CAMERA_FPS",
                    60.0,
                )
                self.set_frame_rate(target_fps)
                
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
            self.cap.set(
                cv2.CAP_PROP_FPS,
                float(getattr(self.config, "CAMERA_FPS", 30.0)),
            )
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
    
    def get_frame_rate_limits(self):
        if not self.pi_mode:
            return None
        controls = getattr(self.picam, "camera_controls", {})
        limits = controls.get("FrameDurationLimits")
        if limits is None or len(limits) < 2:
            return None
        min_duration = float(limits[0])
        max_duration = float(limits[1])
        if min_duration <= 0 or max_duration <= 0:
            return None
        return (
            1_000_000.0 / max_duration,
            1_000_000.0 / min_duration,
        )

    def set_frame_rate(self, fps):
        """Request a target camera capture rate in frames per second."""
        fps = float(fps)
        if fps <= 0:
            raise ValueError("fps must be greater than zero")

        if self.pi_mode:
            frame_duration_us = int(round(1_000_000.0 / fps))
            limits = self.get_frame_rate_limits()
            if limits is not None and not limits[0] <= fps <= limits[1]:
                raise ValueError(
                    f"requested Picamera2 FPS {fps:.2f} is outside the "
                    f"configured camera-mode range "
                    f"{limits[0]:.2f}-{limits[1]:.2f} FPS"
                )
            try:
                self.picam.set_controls({
                    "FrameDurationLimits": (
                        frame_duration_us,
                        frame_duration_us,
                    )
                })
            except Exception:
                logger.exception(
                    "Failed to set Picamera2 FrameDurationLimits to %.2f FPS",
                    fps,
                )
                raise
            self.requested_frame_rate = fps
            self._capture_timestamps.clear()
            self.measured_frame_rate = None
            return

        if not self.cap.isOpened():
            raise RuntimeError("OpenCV camera is not open")

        requested = self.cap.set(
            cv2.CAP_PROP_FPS,
            fps,
        )
        if not requested:
            logger.warning(
                "OpenCV backend did not accept requested camera FPS %.2f",
                fps,
            )
        self.requested_frame_rate = fps
        self._capture_timestamps.clear()
        self.measured_frame_rate = None

    def get_frame_rate(self):
        if self.measured_frame_rate is not None:
            return self.measured_frame_rate
        if self.pi_mode:
            return None
        try:
            value = float(
                self.cap.get(cv2.CAP_PROP_FPS)
            )
            return value if value > 0 else None
        except Exception:
            return None

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
            now = time.monotonic()
            self._capture_timestamps.append(now)
            if len(self._capture_timestamps) >= 2:
                span = now - self._capture_timestamps[0]
                if span > 0:
                    self.measured_frame_rate = (
                        (len(self._capture_timestamps) - 1) / span
                    )
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