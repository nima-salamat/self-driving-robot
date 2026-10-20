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

MODE = "race"
# Settings marked [JSON] below are overridden by race.json at startup when CHANGE_WITH_JSON=True.
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
ST_TRAPEZOID_MODE = False  # [JSON] sign/AprilTag ROI shape: trapezoid or rectangle
OBJ_TRAPEZOID_MODE = False  # [JSON] object ROI shape: trapezoid or rectangle

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
LOW_KP = 0.3 # smaller correction when error is small
HIGH_KP = 0.6 # stronger correction when error is large
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
SPEED = 255
HARDCODE_SPEED = 220
# Arduino lane-change sequences sent during startup; format: f|b PWM PULSES SERVO.
OBSTACLE_LANE_LEFT_SEQUENCE = "f 230 48 60 f 230 48 120"  # [JSON] left/pass sequence; preserves the previous 48-pulse default
OBSTACLE_LANE_RIGHT_SEQUENCE = "f 230 48 120 f 230 48 60"  # [JSON] right/return sequence; preserves the previous 48-pulse default
SEND_AUTOMATIC_ARDUINO_COMMANDS = True  # [JSON] allow automatic Python control/config commands; manual Stream commands bypass this gate

# --- Crosswalk Setting ---
CROSSWALK_SLEEP = 3  # [JSON] delay after handling a crosswalk, in seconds
CROSSWALK_THRESH_SPEND = 8  # [JSON] crosswalk re-detection cooldown window, in seconds


# Stream (enable/disable) 
STREAM = False
ENCODER_MAP_ENABLED = False
# Optional hardware calibration for --encoder-map / host-adaptive features.
# Fill these with measurements for this specific mode/robot. CLI values override them.
ENCODER_PULSE_DISTANCE_CM = None
ENCODER_WHEELBASE_CM = None
ENCODER_ROAD_ANGLE_MIN_DEG = None
ENCODER_ROAD_ANGLE_MAX_DEG = None

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
STOP_COMMAND_REFRESH_INTERVAL = 0.25
SEND_TRAFFIC_STOP_COMMAND = False


# Change Configs based on json file
CHANGE_WITH_JSON = True

# Set use sign or apriltag detector
WITH_SIGN = True  # [JSON] enable traffic-sign detection; false disables this marker detector
WITH_APRILTAG = not WITH_SIGN  # [JSON] enable AprilTag detection; do not enable with WITH_SIGN

READ_SIGN_THRESHOLD = 18  # [JSON] loop iterations between sign-inference submissions; higher reduces inference frequency
RACE_START_ON_STOP_SIGN = False
RACE_STOP_ABSENCE_SECONDS = 1.0
RACE_STOP_CONFIDENCE_THRESHOLD = 0.2
RACE_FINISH_AFTER_SECONDS = None
RACE_FINISH_SPEED = None

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
PID_MIN_DT = 0.001  # [JSON] minimum accepted PID sample interval in seconds
PID_MAX_DT = 0.2  # [JSON] maximum accepted PID sample interval in seconds
PID_DERIVATIVE_FILTER = 0.25  # [JSON] derivative smoothing factor, from 0 to 1


# Control-loop target period (seconds)
CONTROL_PERIOD = 0.01
# Legacy delay retained for maneuver timing
DELAY = 0.005

# show fps
SHOW_FPS = False

# PID parameters — editable in Stream and persisted in the mode JSON.
USE_PID = True  # [JSON] enable or bypass PID steering correction
KP = 0.35  # [JSON] proportional gain
KI = 0.0  # [JSON] integral gain
KD = 0.01  # [JSON] derivative gain
KT = 0.01  # [JSON] nominal PID sample period in seconds
OUTPUT_LIMITS = (-80, 80)  # [JSON] lower and upper steering-correction limits
AUTO_UPDATE_KP = False  # [JSON] legacy option; not consumed by the current PID controller

# lane detection method
OLD_METHOD = False

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
USE_SIGN = False
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

# City-only lane detector note: BLSF beta is intentionally not available in Race mode.
# Optional ML lane detector; disabled by default.
USE_ML_LANE_DETECTOR = False
ML_LANE_MODEL = "unet_depthwise_nano"
ML_LANE_CPU_THREADS = 4
