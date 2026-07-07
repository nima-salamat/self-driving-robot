# --- Camera Defaults ---
CAM_WIDTH = 640
CAM_HEIGHT = 480

resize_width = 380
resize_height = 230
CAMERA_PITCH_DEG = -40 # camera angle in real world
CAMERA_HEIGHT = 27 # height of camera in real world
USBCAM_ADDR = 0

# Mode options: "picam" for Raspberry Pi Camera, "webcam" for USB camera
CAMERA_MODE = "picam"


# --- Lane Detection Regions of Interest (ROIs) ---
# Values are normalized (0.0 – 1.0), multiplied by frame width/height
# Tune these for your camera placement

# Right lane ROI (fraction of frame)
RL_TOP_ROI = 0.8   # start 80% down from top
RL_BOTTOM_ROI = 1  # stop at 100% of frame height
RL_LEFT_ROI = 0.6   # left boundary (60% of width)
RL_RIGHT_ROI = 0.9 # right boundary (90% of width)

# Left lane ROI
LL_TOP_ROI = 0.8
LL_BOTTOM_ROI = 1
LL_LEFT_ROI = 0.2
LL_RIGHT_ROI = 0.5

# Crosswalk ROI (if you later want stop line detection)
CW_TOP_ROI = 0.8
CW_BOTTOM_ROI = 1.0
CW_LEFT_ROI = 0.3
CW_RIGHT_ROI = 0.9

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
SERVO_CENTER = 90
SERVO_DIRECTION = "ltr" # left = 0 and right = 180

# --- Speed Config ---
SPEED = 255

# --- Crosswalk Setting ---
CROSSWALK_SLEEP = 3 # sec  - after seeing crosswalk
CROSSWALK_THRESH_SPEND = 8 # sec  - dont care if crosswalk seen before threshold time


# Stream (enable/disable) 
STREAM = True
debug_frames_list = [] # global stream frame variable

# tack snapshot and video of camera
TAKE_PICTURE = False
RECORD_VIDEO = False

# Lane Width (distance between two lane in the track)
LANE_WIDTH = 30 # cm

# Static Threshold
LANE_THRESHOLD = 180 # lane vision processing threshold
CROSSWALK_THRESHOLD = 180 

# Run Level 
RUN_LVL = "MOVE" # it can be MOVE or STOP


# Change Configs based on json file
CHANGE_WITH_JSON = True

# Set use sign or apriltag detector
WITH_SIGN = True
WITH_APRILTAG = not WITH_SIGN

READ_SIGN_THRESHOLD = 5

# Sign or Tag id
TURN_RIGHT = 2
TURN_LEFT = 3
STRAIGHT = 4
STOP = 5

# without arduino
WITHOUT_ARDUINO = False

# sleep delay time
DELAY = 0.005

# show fps
SHOW_FPS = False

# PID parameters
USE_PID = True
KP = 1
KI = 0
KD = 0
KT = 0
OUTPUT_LIMITS = (-80, 80)
AUTO_UPDATE_KP = False

# lane detection method
OLD_METHOD = True
