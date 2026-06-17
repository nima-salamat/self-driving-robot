# =========================
# config.py
# =========================

# --- Camera Defaults ---
default_width = 380
default_height = 230

# Mode options: "picam" for Raspberry Pi Camera, "webcam" for USB camera
CAMERA_MODE = "picam"

# --- Lane Detection Regions of Interest (ROIs) ---
# Values are normalized (0.0 – 1.0), multiplied by frame width/height
# Tune these for your camera placement

# Right lane ROI (fraction of frame)
RL_TOP_ROI = 0.8   # start 40% down from top
RL_BOTTOM_ROI = 1  # stop at 90% of frame height
RL_LEFT_ROI = 0.7   # left boundary (55% of width)
RL_RIGHT_ROI = 1 # right boundary (95% of width)

# Left lane ROI
LL_TOP_ROI = 0.8
LL_BOTTOM_ROI = 1
LL_LEFT_ROI = 0.2
LL_RIGHT_ROI = 0.5

# Crosswalk ROI (if you later want stop line detection)
CW_TOP_ROI = 0.8
CW_BOTTOM_ROI = 1.0
CW_LEFT_ROI = 0.1
CW_RIGHT_ROI = 0.4

# Apriltag ROI
AT_TOP_ROI = 0.1
AT_BOTTOM_ROI = 1
AT_LEFT_ROI = 0.0
AT_RIGHT_ROI = 1.0

# --- Control Gains ---
# These are proportional gains for steering correction
LOW_KP = 0.5 # smaller correction when error is small
HIGH_KP = 0.7 # stronger correction when error is large

# --- Debugging ---
# If True, will draw ROIs, lane midpoints, error, etc.
DEBUG = True

# --- Arduino Serial Settings ---
SERIAL_PORT = "/dev/ttyUSB0"   # adjust if different
BAUD_RATE = 115200
SERIAL_TIMEOUT = 0.1

# --- Servo Angle Limits ---
MIN_SERVO_ANGLE = 55.0
MAX_SERVO_ANGLE = 125.0

# --- Speed Config ---
SPEED = 255

# --- Crosswalk Setting ---
CROSSWALK_SLEEP = 3
CROSSWALK_THRESH_SPEND = 10

# Stream (enable/disable) 
STREAM = True
debug_frame_buffer = None # global stream frame variable

# Static Threshold
LANE_THRESHOLD = 180 # lane vision processing threshold
CROSSWALK_THRESHOLD = 180 

# Run Level
RUN_LVL = "MOVE" # it can be MOVE or STOP