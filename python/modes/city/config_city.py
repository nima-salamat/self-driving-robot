import os

from utils.camera_defaults import (
    CAM_HEIGHT,
    CAM_WIDTH,
    CAMERA_FALLBACK_TO_OPENCV,
    CAMERA_MODE,
    USBCAM_ADDR,
    resize_height,
    resize_width,
)

MODE = "city"
# Settings marked [JSON] below are overridden by city.json at startup when CHANGE_WITH_JSON=True.

# --- Camera Defaults ---
CAMERA_PITCH_DEG = -40 # camera angle in real world
CAMERA_HEIGHT = 27 # height of camera in real world
# Camera backend defaults are shared with calibration.
CAMERA_FPS = 60.0
# Apply saved intrinsic/distortion calibration to runtime camera frames.
APPLY_CAMERA_CALIBRATION = True


# --- ROI Shape Features ---
# Values are normalized (0.0 – 1.0), multiplied by frame width/height

# Options: "rectangle" or "trapezoid"
LANE_ROI_MODE = "rectangle"  # [JSON] lane-region geometry mode: rectangle or trapezoid

# Toggle for Crosswalk Trapezoid (True = Isosceles Trapezoid, False = Rectangle)
CW_TRAPEZOID_MODE = False  # [JSON] crosswalk ROI shape: true=trapezoid, false=rectangle
ST_TRAPEZOID_MODE = True  # [JSON] sign/AprilTag ROI shape: trapezoid or rectangle
OBJ_TRAPEZOID_MODE = True  # [JSON] object ROI shape: trapezoid or rectangle

# Top width factor for trapezoids (0.0 to 1.0)
# 0.5 means the top edge will be 50% of the base width
RL_TOP_WIDTH_FACTOR = 0.85  # [JSON] top width of the right-lane trapezoid as a fraction of its base
LL_TOP_WIDTH_FACTOR = 0.85  # [JSON] top width of the left-lane trapezoid as a fraction of its base
CW_TOP_WIDTH_FACTOR = 0.90  # [JSON] top width of the crosswalk trapezoid as a fraction of its base
ST_TOP_WIDTH_FACTOR = 0.8  # [JSON] top width of the sign/AprilTag trapezoid as a fraction of its base
OBJ_TOP_WIDTH_FACTOR = 0.8  # [JSON] top width of the object ROI trapezoid as a fraction of its base

# Right lane ROI (fraction of frame)
RL_TOP_ROI = 0.8  # [JSON] right-lane ROI top edge; Y normalized by frame height
RL_BOTTOM_ROI = 1  # [JSON] right-lane ROI bottom edge; Y normalized by frame height
RL_LEFT_ROI = 0.6  # [JSON] right-lane ROI left edge; X normalized by frame width
RL_RIGHT_ROI = 0.9  # [JSON] right-lane ROI right edge; X normalized by frame width

# Left lane ROI
LL_TOP_ROI = 0.8  # [JSON] left-lane ROI top edge; Y normalized by frame height
LL_BOTTOM_ROI = 1  # [JSON] left-lane ROI bottom edge; Y normalized by frame height
LL_LEFT_ROI = 0.2  # [JSON] left-lane ROI left edge; X normalized by frame width
LL_RIGHT_ROI = 0.5  # [JSON] left-lane ROI right edge; X normalized by frame width

# Crosswalk ROI (if you later want stop line detection)
CW_TOP_ROI = 0.8  # [JSON] crosswalk ROI top edge; normalized frame coordinates
CW_BOTTOM_ROI = 1.0  # [JSON] crosswalk ROI bottom edge; normalized frame coordinates
CW_LEFT_ROI = 0.3  # [JSON] crosswalk ROI left edge; normalized frame coordinates
CW_RIGHT_ROI = 0.9  # [JSON] crosswalk ROI right edge; normalized frame coordinates

# Apriltag ROI
AT_TOP_ROI = 0.0
AT_BOTTOM_ROI = 1
AT_LEFT_ROI = 0.0
AT_RIGHT_ROI = 1.0

# Traffic Light ROI
TL_TOP_ROI = 0.0
TL_BOTTOM_ROI = 1
TL_LEFT_ROI = 0.0
TL_RIGHT_ROI = 1.0

# Sign or Tag ROI
ST_TOP_ROI = 0.0  # [JSON] sign/AprilTag processing crop top edge
ST_BOTTOM_ROI = 1  # [JSON] sign/AprilTag processing crop bottom edge
ST_LEFT_ROI = 0.0  # [JSON] sign/AprilTag processing crop left edge
ST_RIGHT_ROI = 1.0  # [JSON] sign/AprilTag processing crop right edge

# Object ROI
OBJ_TOP_ROI = 0.0  # [JSON] object-detection ROI top edge
OBJ_BOTTOM_ROI = 1  # [JSON] object-detection ROI bottom edge
OBJ_LEFT_ROI = 0.0  # [JSON] object-detection ROI left edge
OBJ_RIGHT_ROI = 1.0  # [JSON] object-detection ROI right edge

# --- Control Gains ---
# These are proportional gains for steering correction
LOW_KP = 0.5 # smaller correction when error is small
HIGH_KP = 0.7 # stronger correction when error is large
# now high and low kp dont use in city vision  

# --- Debugging ---
# If True, will draw ROIs, lane midpoints, error, etc.
DEBUG = True

# --- Arduino Serial Settings ---
SERIAL_PORT = "/dev/ttyUSB0"   # adjust if different
BAUD_RATE = 115200             # same as in your arduino etc 
SERIAL_TIMEOUT = 0.1

# --- Servo Angle Limits ---
MIN_SERVO_ANGLE = 55.0
MAX_SERVO_ANGLE = 125.0
# --- Servo Default Config ---
SERVO_CENTER = 95
SERVO_DIRECTION = "ltr" # left = 0 and right = 180

# --- Speed Config ---
SPEED = 175  # Normal City cruising PWM command (0-255)
HARDCODE_SPEED = 220  # Crosswalk maneuver PWM command
MOTOR_COMMAND_REFRESH_INTERVAL = 0.1  # Retry steady motor setpoints every 100 ms

# --- Crosswalk Setting ---
CROSSWALK_SLEEP = 3  # [JSON] delay after handling a crosswalk, in seconds
CROSSWALK_THRESH_SPEND = 8  # [JSON] crosswalk re-detection cooldown window, in seconds


# Stream (enable/disable) 
STREAM = False
ENCODER_MAP_ENABLED = False
CONFIDENCE_AWARE_ENABLED = False
ADAPTIVE_OBSTACLE_AVOIDANCE_ENABLED = False
debug_frames_list = [] # global stream frame variable

# tack snapshot and video of camera
TAKE_PICTURE = False
RECORD_VIDEO = False  # [JSON] enable or disable runtime video recording

# Lane Width (distance between two lane in the track)
LANE_WIDTH = 30 # cm

# Static Threshold
LANE_THRESHOLD = 180  # [JSON] pixel-intensity threshold used by classical lane detection
CROSSWALK_THRESHOLD = 180  # [JSON] pixel threshold used by crosswalk detection

# Run Level 
RUN_LVL = "MOVE"  # [JSON] runtime level selected by legacy/dashboard controls: MOVE or STOP
STOP_MIN_HOLD_SECONDS = 3.0
STOP_COMMAND_REFRESH_INTERVAL = 0.25
SEND_TRAFFIC_STOP_COMMAND = False


# Change Configs based on json file
CHANGE_WITH_JSON = True

# Set use sign or apriltag detector
WITH_SIGN = True  # [JSON] enable traffic-sign detection; false disables this marker detector
WITH_APRILTAG = not WITH_SIGN  # [JSON] enable AprilTag detection; do not enable with WITH_SIGN

READ_SIGN_THRESHOLD = 40  # [JSON] loop iterations between sign-inference submissions; higher reduces inference frequency

# Targeted detector-box filter. Area uses detector pixel coordinates (px²);
# 900 px² is a tunable 30×30 px starting point, not an empirical calibration.
SIGN_AREA_FILTER_ENABLED = True  # [JSON] enable minimum bounding-box-area filtering for selected signs
SIGN_AREA_FILTER_TARGETS = ["STOP"]  # [JSON] sign labels affected by the area filter (for example STOP)
SIGN_AREA_MIN_PX2 = 900  # [JSON] minimum accepted detector-box area in square pixels

# Sign or Tag id
TURN_RIGHT = 2  # [JSON] numeric AprilTag ID interpreted as TURN RIGHT
TURN_LEFT = 3  # [JSON] numeric AprilTag ID interpreted as TURN LEFT
STRAIGHT = 4  # [JSON] numeric AprilTag ID interpreted as STRAIGHT
STOP = 5  # [JSON] numeric AprilTag ID interpreted as STOP

# without arduino
# Strict hello/cfg hardware handshake is opt-in via --arduino-config PATH.
ARDUINO_CONFIG = None
ARDUINO_CONTRACT_TIMEOUT = 3.0
WITHOUT_ARDUINO = os.name == "nt"

# Serial recovery / telemetry
SERIAL_MAX_RETRIES = 3
SERIAL_STARTUP_WAIT = 3.0
SERIAL_REBOOT_WAIT = 2.0
SERIAL_RECONNECT_INTERVAL = 0.5
SERIAL_RECONNECT_TIMEOUT = 0.5
SERIAL_TELEMETRY_BUFFER_SIZE = 100
READ_ARDUINO_OUTPUT = False

# Raspberry Pi -> Arduino liveness protection.
HOST_HEARTBEAT_INTERVAL = 0.1

# In-memory command trace used by the future route-recovery coordinator.
MOTION_HISTORY_MAX_PULSES = 200
MOTION_HISTORY_MAX_EVENTS = 128

# PID timing protection
PID_MIN_DT = 0.001
PID_MAX_DT = 0.2
PID_DERIVATIVE_FILTER = 0.25


# Control-loop target period (seconds)
CONTROL_PERIOD = 0.01
# Legacy delay retained for maneuver timing
DELAY = 0.005

# show fps
SHOW_FPS = False

# PID parameters
USE_PID = True
KP = 0.38
KI = 0
KD = 0.01
KT = 0.01
OUTPUT_LIMITS = (-80, 80)
AUTO_UPDATE_KP = False

# lane detection method
OLD_METHOD = False

# ---------------------------------------------------------------------------
# BLSF beta lane detector (City mode only)
# The normal City detector remains the default. Enable with:
#   python main.py --mode city --city-lane-detector blsf-beta
# This experimental detector reuses the BEV_* settings above.
CITY_LANE_DETECTOR = "default"  # "default" or "blsf-beta"
BLSF_RANDOM_SEED = 42
BLSF_MIN_SEGMENT_LENGTH = 17
BLSF_ANGLE_LIMIT_DEG = 35
BLSF_STRAIGHT_BAND_DEG = 5
BLSF_MIN_ANGLE_VOTE = 20
BLSF_MEDIAN_KERNEL = 9
BLSF_LOCAL_THRESHOLD = 15
BLSF_NUM_WINDOWS = 9
BLSF_WINDOW_WIDTH_FACTOR = 0.40
BLSF_RANSAC_ITERATIONS = 80
BLSF_RANSAC_INLIER_THRESHOLD = 6.0
BLSF_MIN_FIT_POINTS = 12
BLSF_DEFAULT_LANE_WIDTH = 0.40
BLSF_FALLBACK_HALF_LANE_WIDTH = 0.20
BLSF_STEERING_KP = 0.45
BLSF_STEERING_SMOOTHING = 0.70
BLSF_NO_LANE_STEERING = 150

# crosswalk detection method
CW_OLD_METHOD = True

# Roi Resizable
ROI_RESIZABLE = False

# --- BEV (Bird's Eye View) Config ---
USE_BEV = True  # [JSON] enable the bird's-eye-view perspective transform

BEV_SRC_TL_X = 0.35  # [JSON] source top-left BEV corner X; normalized by frame width
BEV_SRC_TL_Y = 0.60  # [JSON] source top-left BEV corner Y; normalized by frame height
BEV_SRC_TR_X = 0.65  # [JSON] source top-right BEV corner X; normalized by frame width
BEV_SRC_TR_Y = 0.60  # [JSON] source top-right BEV corner Y; normalized by frame height
BEV_SRC_BR_X = 1.00  # [JSON] source bottom-right BEV corner X; normalized by frame width
BEV_SRC_BR_Y = 1.00  # [JSON] source bottom-right BEV corner Y; normalized by frame height
BEV_SRC_BL_X = 0.00  # [JSON] source bottom-left BEV corner X; normalized by frame width
BEV_SRC_BL_Y = 1.00  # [JSON] source bottom-left BEV corner Y; normalized by frame height

# Detect Object
DETECT_OBJECT = False

# Traffic sign detector method
SIGN_DETECTOR_METHOD = "yolo"  # "yolo" or "svm"

OUTPUT_DIR = "output"
MIN_FREE_DISK_MB = 256
# Bind to all interfaces so trusted devices on the LAN can open the dashboard.
# Use --stream-host 127.0.0.1 for loopback-only access.
STREAM_HOST = "0.0.0.0"
STREAM_PORT = 5000
# Controls are enabled for the interactive dashboard; use --stream-read-only
# on networks where other devices must not change runtime settings.
STREAM_ALLOW_CONTROL = True
SHUTDOWN_EVENT = None
PERFORMANCE = False

SIGN_RESULT_MAX_AGE = 0.75


# Optional City-only traffic-light gate; activation is explicit CLI opt-in.
TRAFFIC_LIGHTS_ENABLED = False
TRAFFIC_LIGHT_WAIT_BEFORE_CHECK = False
TL_RED_HSV_RANGES = (((0,100,100),(10,255,255)), ((170,100,100),(180,255,255)))
TL_GREEN_HSV_RANGES = (((40,50,50),(90,255,255)),)
TL_MIN_SATURATION = 50
TL_MIN_VALUE = 50
TL_MIN_CONTOUR_AREA = 5.0
TL_MIN_ACTIVE_BRIGHTNESS = 180
TL_CONFIRMATION_WINDOW = 10
TL_CONFIRMATION_GREEN_REQUIRED = 8
