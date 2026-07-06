"""
Robust Lane Detection Pipeline
================================

Redesigned `VisionProcessor` for the city-driving mode. Keeps the original
public interface -- `detect(frame, debug_frame) -> dict` with the same core
keys (`steering_angle`, `error`, `lane_type`, `crosswalk`, `debug`, `kp`) plus
a new `confidence` key -- but replaces the Canny+Hough-only pipeline with a
more robust stack, organized to match the 7 improvement areas requested:

  1. Preprocessing   - CLAHE, Scharr gradient, adaptive threshold, morphology
  2. BEV             - homography-based bird's-eye remap; geometry done in BEV space
  3. Feature extraction - Hough segments -> orientation filter -> RANSAC polyfit (curves)
  4. Tracking        - Kalman filter on lane-center error + per-frame confidence
  5. Fallback logic  - probabilistic confidence instead of binary seen/not-seen,
                       Kalman *prediction* instead of a hard reset when lost
  6. Crosswalk       - independent pipeline, orientation-histogram gated
  7. Control         - PID (P+I+D) + rate limiter, replacing the old ad-hoc
                       dynamically-rescaled proportional gain

--------------------------------------------------------------------------
NEW CONFIG VALUES (add to config_city.py -- all are optional, sane defaults
are used through `_cfg()` if you don't add them yet, so this file is a
drop-in replacement even before you tune anything):

    BEV_SRC_POINTS         4 (x_ratio, y_ratio) points in the ORIGINAL frame,
                           in [top_left, top_right, bottom_right, bottom_left]
                           order, describing a trapezoid painted on a known
                           FLAT, STRAIGHT stretch of road directly ahead.
                           This is the one value that most affects geometric
                           accuracy -- see "Calibrating BEV" below.
    BEV_OUT_SIZE           (w, h) pixel size of the BEV canvas. Default (400, 600).
    LANE_WIDTH_BEV_PX      Expected pixel distance between the two lane lines
                           in the BEV canvas (measure it once on a calibration
                           frame). Used to extrapolate a missing lane from the
                           visible one. Default: 0.6 * BEV width.
    RANSAC_ITERATIONS      Default 40.
    RANSAC_THRESH_PX       Inlier distance threshold, BEV pixels. Default 6.0.
    MIN_LANE_POINTS        Minimum candidate points to attempt a fit. Default 8.
    KALMAN_PROCESS_VAR     Default 1e-2.
    KALMAN_MEASUREMENT_VAR Default 25.0.
    PID_KP, PID_KI, PID_KD Default 0.6, 0.02, 0.15. Tuned so a full-lane-width
                           BEV-pixel offset drives close to full steering
                           deflection -- retune for your servo/steering geometry.
    PID_INTEGRAL_LIMIT     Anti-windup clamp on the I term. Default 50.0.
    STEERING_MAX_RATE      Max change in steering angle (servo-degrees) allowed
                           per frame. Default 6.0.
    MAX_LANE_LOST_FRAMES   Frames to keep predicting before a lane side is
                           considered fully lost (search window stops growing
                           further). Default 15.

Calibrating BEV_SRC_POINTS: place the car on a straight, flat road with the
lane markings visible, grab one frame, and pick four points that form a
trapezoid over a straight section of the two lane lines (top edge further
away, bottom edge close to the car). Until you do this, a fallback trapezoid
is built from your existing RL_*/LL_* ROI ratios -- it will work, but the BEV
geometry (and therefore curvature estimates) will only be approximate.
--------------------------------------------------------------------------
"""
import warnings
warnings.filterwarnings('ignore', message='Polyfit may be poorly conditioned')

import math
import cv2
import numpy as np

from modes.city.config_city import (
    MAX_SERVO_ANGLE, MIN_SERVO_ANGLE, SERVO_CENTER, SERVO_DIRECTION,
    CAMERA_HEIGHT, CAMERA_PITCH_DEG, LANE_WIDTH
)
import modes.city.config_city as conf


def _cfg(name, default):
    """Fetch an optional config value, falling back to a sane default so this
    module works before config_city.py is updated."""
    return getattr(conf, name, default)


# ============================================================
# 1. PREPROCESSING -- CLAHE, Scharr gradient, adaptive threshold, morphology
# ============================================================

_CLAHE = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))


def enhance_contrast(gray):
    """CLAHE local-contrast enhancement -> robust to global lighting changes
    and to one part of the frame being in shadow while another is bright."""
    return _CLAHE.apply(gray)


def scharr_x_magnitude(gray):
    """Scharr gradient in x. Lane lines are close to vertical in the camera
    view, so a strong x-gradient response is a good, more stable-than-Sobel
    signal for them at small kernel sizes."""
    gx = cv2.Scharr(gray, cv2.CV_32F, 1, 0)
    gx = np.absolute(gx)
    peak = gx.max()
    if peak < 1e-6:
        return np.zeros_like(gray)
    return np.uint8(255 * gx / peak)


def adaptive_binary(gray, block_size=25, c=-8):
    """Adaptive (local) threshold instead of one fixed global threshold ->
    survives shadows and uneven illumination across the ROI."""
    block_size = block_size if block_size % 2 == 1 else block_size + 1
    return cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block_size, c
    )


def morphological_clean(binary, ksize=(5, 5)):
    """Close small gaps (dashed lane markings) then open (remove speckle
    noise) so we get a few stable blobs instead of dozens of fragmented Hough
    segments."""
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, ksize)
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    opened = cv2.morphologyEx(closed, cv2.MORPH_OPEN, kernel, iterations=1)
    return opened


def lane_feature_mask(roi_bgr):
    """Full preprocessing chain for one lane-search region. Returns a clean
    single-channel binary mask, or None if the ROI is empty."""
    if roi_bgr is None or roi_bgr.size == 0:
        return None
    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    gray = enhance_contrast(gray)

    grad = scharr_x_magnitude(gray)
    _, grad_bin = cv2.threshold(grad, 40, 255, cv2.THRESH_BINARY)

    adapt = adaptive_binary(gray)

    combined = cv2.bitwise_or(grad_bin, adapt)
    combined = morphological_clean(combined)
    return combined


# ============================================================
# 2. BIRD'S EYE VIEW (Inverse Perspective Mapping / Homography)
# ============================================================

class BEVTransformer:
    """Homography-based bird's-eye remap. Parallel-lane geometry and
    curvature are far easier (and cheaper) to reason about in BEV space than
    in raw perspective."""

    def __init__(self, width, height):
        self.src_w, self.src_h = width, height
        self.out_w, self.out_h = _cfg("BEV_OUT_SIZE", (400, 600))

        src_ratio = _cfg("BEV_SRC_POINTS", None)
        if src_ratio is None:
            # Fallback trapezoid built from the existing lane-ROI extremes.
            # Works out of the box, but calibrate BEV_SRC_POINTS for accurate
            # real-world geometry (see module docstring).
            top = min(conf.RL_TOP_ROI, conf.LL_TOP_ROI)
            bottom = max(conf.RL_BOTTOM_ROI, conf.LL_BOTTOM_ROI)
            src_ratio = [
                (conf.LL_RIGHT_ROI, top),      # top-left
                (conf.RL_LEFT_ROI, top),       # top-right
                (conf.RL_RIGHT_ROI, bottom),   # bottom-right
                (conf.LL_LEFT_ROI, bottom),    # bottom-left
            ]

        self.src_points = np.float32([[rx * width, ry * height] for rx, ry in src_ratio])
        self.dst_points = np.float32([
            [0, 0],
            [self.out_w, 0],
            [self.out_w, self.out_h],
            [0, self.out_h],
        ])

        self.M = cv2.getPerspectiveTransform(self.src_points, self.dst_points)
        self.Minv = cv2.getPerspectiveTransform(self.dst_points, self.src_points)

    def warp(self, img):
        return cv2.warpPerspective(img, self.M, (self.out_w, self.out_h), flags=cv2.INTER_LINEAR)

    def unwarp(self, img):
        return cv2.warpPerspective(img, self.Minv, (self.src_w, self.src_h), flags=cv2.INTER_LINEAR)

    def unwarp_points(self, pts):
        """pts: iterable of (x, y) in BEV space -> back to original image space."""
        pts = np.array(pts, dtype=np.float32).reshape(-1, 1, 2)
        if len(pts) == 0:
            return np.empty((0, 2))
        out = cv2.perspectiveTransform(pts, self.Minv)
        return out.reshape(-1, 2)


# ============================================================
# 3. FEATURE EXTRACTION -- Hough segments -> orientation filter -> RANSAC polyfit
# ============================================================

def extract_segments(mask, min_len=8, max_gap=8):
    edges = cv2.Canny(mask, 60, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=18,
                             minLineLength=min_len, maxLineGap=max_gap)
    return lines


def filter_by_orientation(lines, min_angle_from_horizontal=25.0):
    """Drop near-horizontal segments -- crosswalk stripes, tar seams, shadow
    edges from overpasses/trees -- so only lane-like near-vertical segments
    survive into the fit. This is what keeps crosswalk/noise features from
    dragging the lane fit around (see section 6 for the crosswalk side of
    this same separation)."""
    if lines is None:
        return np.empty((0, 4), dtype=np.float32)
    kept = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        angle = math.degrees(math.atan2(abs(y2 - y1), abs(x2 - x1) + 1e-9))
        if angle >= min_angle_from_horizontal:
            kept.append((x1, y1, x2, y2))
    return np.array(kept, dtype=np.float32)


def segment_points(segments):
    """Flatten Nx4 segment endpoints into candidate (x, y) point arrays."""
    if segments is None or len(segments) == 0:
        return np.empty((0,)), np.empty((0,))
    xs = np.concatenate([segments[:, 0], segments[:, 2]])
    ys = np.concatenate([segments[:, 1], segments[:, 3]])
    return xs, ys


def ransac_polyfit(xs, ys, order=2, iterations=40, thresh=6.0,
                    min_samples=None, min_inlier_ratio=0.35, rng=None):
    """RANSAC-robust polynomial fit of x = f(y) (y as the independent
    variable, standard for near-vertical lane lines). Robust against stray
    Hough segments from noise/shadows that a plain np.polyfit would be
    thrown off by. Returns (coeffs, confidence); coeffs is None on failure.
    confidence is the inlier ratio, used directly as the per-lane
    confidence score for the fallback logic in section 4/5."""
    n = len(ys)
    min_samples = min_samples or (order + 1)
    if n < max(min_samples, 4):
        return None, 0.0

    rng = rng or np.random.default_rng()
    best_coeffs, best_inliers, best_count = None, None, -1

    for _ in range(iterations):
        idx = rng.choice(n, size=min_samples, replace=False)
        try:
            coeffs = np.polyfit(ys[idx], xs[idx], order)
        except (np.linalg.LinAlgError, ValueError):
            continue
        pred = np.polyval(coeffs, ys)
        inliers = np.abs(pred - xs) < thresh
        count = int(np.sum(inliers))
        if count > best_count:
            best_coeffs, best_inliers, best_count = coeffs, inliers, count

    if best_coeffs is None or (best_count / n) < min_inlier_ratio:
        return None, 0.0

    # Refine using all inliers -> smoother, less noisy final curve.
    refined = np.polyfit(ys[best_inliers], xs[best_inliers], order)
    return refined, float(best_count / n)


# ============================================================
# 4. TRACKING -- Kalman filter for the lane-center error + confidence
# ============================================================

class KalmanTracker1D:
    """Constant-velocity Kalman filter for a single scalar (here: lane-center
    offset in BEV pixels). Lets the pipeline *predict* through short dropouts
    instead of snapping to a default/reset value (section 5)."""

    def __init__(self, process_var=1e-2, measurement_var=25.0):
        self.x = np.zeros(2)            # [position, velocity]
        self.P = np.eye(2) * 500.0
        self.F = np.array([[1.0, 1.0], [0.0, 1.0]])
        self.H = np.array([[1.0, 0.0]])
        self.Q = np.eye(2) * process_var
        self.R = np.array([[measurement_var]])
        self.initialized = False

    def predict(self):
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q
        return float(self.x[0])

    def update(self, measurement):
        if not self.initialized:
            self.x[0], self.x[1] = measurement, 0.0
            self.initialized = True
        z = np.array([measurement])
        y = z - self.H @ self.x
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.x = self.x + (K.flatten() * y)
        self.P = (np.eye(2) - np.outer(K, self.H)) @ self.P
        return float(self.x[0])

    @property
    def position(self):
        return float(self.x[0])


# ============================================================
# 6. CROSSWALK DETECTION -- independent pipeline, orientation-gated
# ============================================================

def detect_crosswalk(cw_bgr, cw_top, cw_bottom):
    """LSD-based detection gated by an orientation histogram: a real
    crosswalk needs *both* a horizontal-dominant cluster (the stripes) AND
    enough vertical structure (stripe edges) spread across the ROI. A single
    noisy line, or lane markings that leak into the ROI, can't satisfy both
    conditions at once -- this is what keeps crosswalk detection from
    tripping on shadows or on the lane lines themselves."""
    result = {"crosswalk": False, "lines": [], "confidence": 0.0}
    if cw_bgr is None or cw_bgr.size == 0:
        return result

    gray = cv2.cvtColor(cw_bgr, cv2.COLOR_BGR2GRAY)
    gray = enhance_contrast(gray)
    _, binary = cv2.threshold(gray, _cfg("CROSSWALK_THRESHOLD", 170), 255, cv2.THRESH_BINARY)
    edges = cv2.Canny(binary, 60, 150)

    lsd = cv2.createLineSegmentDetector(0)
    detected = lsd.detect(edges)
    lines = detected[0]

    h, w = cw_bgr.shape[:2]
    diag = math.hypot(w, h)
    min_len = max(diag / 20.0, 10.0)

    horizontal_y, vertical_count, kept_lines = [], 0, []

    if lines is not None:
        for line in lines:
            x0, y0, x1, y1 = line[0]
            length = math.hypot(x1 - x0, y1 - y0)
            if length < min_len:
                continue
            angle = abs(math.degrees(math.atan2(y1 - y0, x1 - x0 + 1e-6)))
            angle = min(angle, 180 - angle)
            if angle <= 25:
                horizontal_y.append(max(y0, y1))
                kept_lines.append(line)
            elif angle >= 65:
                vertical_count += 1
                kept_lines.append(line)

    crosswalk_pixel_dist = (3.5 / 5.0) * (cw_bottom - cw_top)
    crosswalk, confidence = False, 0.0
    if len(horizontal_y) >= 2 and vertical_count >= 3:
        if max(horizontal_y) > crosswalk_pixel_dist:
            crosswalk = True
            confidence = min(1.0, (len(horizontal_y) + vertical_count) / 10.0)

    result.update({"crosswalk": crosswalk, "lines": kept_lines, "confidence": confidence})
    return result


# ============================================================
# 7. CONTROL -- PID + smoothing + rate limiter
# ============================================================

class PIDController:
    """Standard P+I+D with anti-windup clamping on the integral term,
    replacing the old scheme where the proportional gain itself was
    recomputed every frame from the current min/max error bounds (which made
    the effective gain -- and therefore stability -- change frame to frame)."""

    def __init__(self, kp, ki, kd, out_min, out_max, integral_limit=None):
        self.kp, self.ki, self.kd = kp, ki, kd
        self.out_min, self.out_max = out_min, out_max
        self.integral_limit = integral_limit
        self.integral = 0.0
        self.prev_error = None

    def reset(self):
        self.integral = 0.0
        self.prev_error = None

    def update(self, error, dt=1.0):
        self.integral += error * dt
        if self.integral_limit is not None:
            self.integral = max(-self.integral_limit, min(self.integral_limit, self.integral))
        derivative = 0.0 if self.prev_error is None else (error - self.prev_error) / dt
        self.prev_error = error
        out = self.kp * error + self.ki * self.integral + self.kd * derivative
        return max(self.out_min, min(self.out_max, out))


class RateLimiter:
    """Clamp how fast the output is allowed to change per call -> removes
    abrupt steering jumps even when the PID output itself jumps (e.g. right
    after a lane reappears)."""

    def __init__(self, max_delta):
        self.max_delta = max_delta
        self.value = None

    def apply(self, target):
        if self.value is None:
            self.value = target
            return self.value
        delta = max(-self.max_delta, min(self.max_delta, target - self.value))
        self.value += delta
        return self.value


# ============================================================
# MAIN PIPELINE
# ============================================================

def _expand_bound(base_bound, extreme_bound, unseen_counter, max_unseen):
    """Grow a search-window bound toward `extreme_bound` as a lane side has
    gone unseen for longer -- same "search wider before giving up" behavior
    as the original growing-ROI logic, generalized into one helper."""
    if max_unseen <= 0:
        return base_bound
    frac = min(1.0, unseen_counter / max_unseen)
    return base_bound + (extreme_bound - base_bound) * frac


class VisionProcessor:
    def __init__(self):
        self.last_steering = float(SERVO_CENTER)

        self.max_unseen_counter = _cfg("MAX_LANE_LOST_FRAMES", 15)
        self.rroi_unseen_counter = 0
        self.lroi_unseen_counter = 0

        self.bev = None  # built lazily once we know the frame size

        self.ransac_iterations = _cfg("RANSAC_ITERATIONS", 40)
        self.ransac_thresh = _cfg("RANSAC_THRESH_PX", 6.0)
        self.min_lane_points = _cfg("MIN_LANE_POINTS", 8)
        self.bev_ref_y_ratio = _cfg("BEV_REFERENCE_Y_RATIO", 0.9)  # evaluate fits near the car

        self.error_tracker = KalmanTracker1D(
            process_var=_cfg("KALMAN_PROCESS_VAR", 1e-2),
            measurement_var=_cfg("KALMAN_MEASUREMENT_VAR", 25.0),
        )

        self.pid = PIDController(
            kp=_cfg("PID_KP", 0.6),
            ki=_cfg("PID_KI", 0.02),
            kd=_cfg("PID_KD", 0.15),
            out_min=MIN_SERVO_ANGLE - SERVO_CENTER,
            out_max=MAX_SERVO_ANGLE - SERVO_CENTER,
            integral_limit=_cfg("PID_INTEGRAL_LIMIT", 50.0),
        )
        self.rate_limiter = RateLimiter(_cfg("STEERING_MAX_RATE", 6.0))

        self._rng = np.random.default_rng()

    # ---------- per-side lane fit in BEV space ----------

    def _fit_side(self, bev_mask, x0, x1, y0, y1, side):
        """Extract features inside a BEV sub-window and RANSAC-fit x = f(y)
        in *full BEV image* coordinates. Returns (coeffs_or_None, confidence)."""
        region = bev_mask[y0:y1, x0:x1]
        if region is None or region.size == 0:
            return None, 0.0

        segments = extract_segments(region)
        segments = filter_by_orientation(segments)
        if len(segments) == 0:
            return None, 0.0

        # shift local segment coords into full-BEV coords before fitting
        segments = segments.copy()
        segments[:, [0, 2]] += x0
        segments[:, [1, 3]] += y0

        xs, ys = segment_points(segments)
        if len(xs) < self.min_lane_points:
            return None, 0.0

        coeffs, confidence = ransac_polyfit(
            xs, ys, order=2,
            iterations=self.ransac_iterations,
            thresh=self.ransac_thresh,
            min_inlier_ratio=0.35,
            rng=self._rng,
        )
        return coeffs, confidence

    def detect(self, frame, debug_frame):
        height, width = frame.shape[:2]

        if self.bev is None:
            self.bev = BEVTransformer(width, height)
        bev = self.bev

        # ---------------------------------------------------
        # 2. Warp to bird's-eye view, then run feature extraction there
        # ---------------------------------------------------
        bev_frame = bev.warp(frame)
        bev_mask = lane_feature_mask(bev_frame)
        bev_h, bev_w = bev_mask.shape[:2]

        mid_x = bev_w / 2.0
        margin = bev_w * 0.15

        # Search windows grow toward the frame edge the longer that side has
        # gone unseen (same intent as the original growing-ROI logic).
        left_x0 = 0
        left_x1 = int(_expand_bound(mid_x + margin, bev_w, self.lroi_unseen_counter, self.max_unseen_counter))
        right_x0 = int(_expand_bound(mid_x - margin, 0, self.rroi_unseen_counter, self.max_unseen_counter))
        right_x1 = bev_w

        left_fit, left_conf = self._fit_side(bev_mask, left_x0, left_x1, 0, bev_h, "left")
        right_fit, right_conf = self._fit_side(bev_mask, right_x0, right_x1, 0, bev_h, "right")

        # ---------------------------------------------------
        # 5. Probabilistic fallback logic
        # ---------------------------------------------------
        CONF_THRESH = 0.35
        left_ok = left_fit is not None and left_conf >= CONF_THRESH
        right_ok = right_fit is not None and right_conf >= CONF_THRESH

        if left_ok:
            self.lroi_unseen_counter = max(0, self.lroi_unseen_counter - 1)
        else:
            self.lroi_unseen_counter = min(self.max_unseen_counter, self.lroi_unseen_counter + 2)

        if right_ok:
            self.rroi_unseen_counter = max(0, self.rroi_unseen_counter - 1)
        else:
            self.rroi_unseen_counter = min(self.max_unseen_counter, self.rroi_unseen_counter + 2)

        if left_ok and right_ok:
            lane_type = "both"
        elif left_ok and not right_ok:
            lane_type = "only_left"
        elif right_ok and not left_ok:
            lane_type = "only_right"
        else:
            lane_type = "none"

        confidence = {
            "both": (left_conf + right_conf) / 2.0,
            "only_left": left_conf * 0.6,   # single lane -> capped confidence
            "only_right": right_conf * 0.6,
            "none": 0.0,
        }[lane_type]

        # ---------------------------------------------------
        # Lane-center error in BEV pixel space, evaluated near the car
        # ---------------------------------------------------
        ref_y = bev_h * self.bev_ref_y_ratio
        lane_width_px = _cfg("LANE_WIDTH_BEV_PX", bev_w * 0.6)
        vehicle_center_x = bev_w / 2.0

        left_x = np.polyval(left_fit, ref_y) if left_ok else None
        right_x = np.polyval(right_fit, ref_y) if right_ok else None

        if lane_type == "both":
            lane_center_x = (left_x + right_x) / 2.0
        elif lane_type == "only_left":
            lane_center_x = left_x + lane_width_px / 2.0
        elif lane_type == "only_right":
            lane_center_x = right_x - lane_width_px / 2.0
        else:
            lane_center_x = None

        # ---------------------------------------------------
        # 4. Kalman tracking: update on a real measurement, otherwise predict
        #    through the dropout instead of resetting.
        # ---------------------------------------------------
        if lane_center_x is not None:
            measurement = vehicle_center_x - lane_center_x
            smoothed_error = self.error_tracker.update(measurement)
        else:
            smoothed_error = self.error_tracker.predict()

        # ---------------------------------------------------
        # 7. PID + rate limiter -> final steering angle
        # ---------------------------------------------------
        pid_out = self.pid.update(smoothed_error)
        if SERVO_DIRECTION == "rtl":
            pid_out = -pid_out
        raw_steering = SERVO_CENTER + pid_out
        raw_steering = max(MIN_SERVO_ANGLE, min(MAX_SERVO_ANGLE, raw_steering))

        # If we've been fully lost for a while, ease back toward center
        # instead of trusting a stale prediction indefinitely.
        fully_lost = (self.lroi_unseen_counter >= self.max_unseen_counter and
                      self.rroi_unseen_counter >= self.max_unseen_counter)
        if fully_lost:
            raw_steering = 0.5 * raw_steering + 0.5 * SERVO_CENTER

        steering_angle = self.rate_limiter.apply(raw_steering)
        steering_angle = int(round(steering_angle))
        self.last_steering = steering_angle

        # ---------------------------------------------------
        # 6. Crosswalk detection (kept in original perspective space --
        #    the flat-road assumption already holds near the vehicle, so
        #    this avoids needing a second BEV calibration for the CW ROI)
        # ---------------------------------------------------
        cw_top, cw_bottom = int(conf.CW_TOP_ROI * height), int(conf.CW_BOTTOM_ROI * height)
        cw_left, cw_right = int(conf.CW_LEFT_ROI * width), int(conf.CW_RIGHT_ROI * width)
        cw_frame = frame[cw_top:cw_bottom, cw_left:cw_right]
        cw_result = detect_crosswalk(cw_frame, cw_top, cw_bottom)

        # ---------------------------------------------------
        # DEBUG DRAWING
        # ---------------------------------------------------
        debug = {"rl_draw": None, "ll_draw": None, "combined": None, "crosswalk_draw": None, "bev": None}
        if conf.DEBUG or conf.STREAM:
            debug = self._draw_debug(
                frame, debug_frame, bev, bev_mask, bev_h, bev_w,
                left_fit, right_fit, left_ok, right_ok,
                lane_center_x, vehicle_center_x, ref_y,
                cw_result, cw_top, cw_bottom, cw_left, cw_right,
            )

        return {
            "steering_angle": steering_angle,
            "error": smoothed_error,
            "lane_type": lane_type,
            "crosswalk": cw_result["crosswalk"],
            "confidence": confidence,
            "debug": debug,
            "kp": self.pid.kp,
        }

    # ---------- debug visualization ----------

    def _draw_debug(self, frame, debug_frame, bev, bev_mask, bev_h, bev_w,
                     left_fit, right_fit, left_ok, right_ok,
                     lane_center_x, vehicle_center_x, ref_y,
                     cw_result, cw_top, cw_bottom, cw_left, cw_right):
        vis = debug_frame.copy()
        bev_vis = cv2.cvtColor(bev_mask, cv2.COLOR_GRAY2BGR)

        ys = np.linspace(0, bev_h - 1, 30)

        def draw_fit(coeffs, color):
            xs = np.polyval(coeffs, ys)
            pts_bev = np.stack([xs, ys], axis=1)
            for x, y in pts_bev:
                if 0 <= x < bev_w:
                    cv2.circle(bev_vis, (int(x), int(y)), 2, color, -1)
            pts_img = bev.unwarp_points(pts_bev)
            for x, y in pts_img:
                if 0 <= x < vis.shape[1] and 0 <= y < vis.shape[0]:
                    cv2.circle(vis, (int(x), int(y)), 2, color, -1)

        if left_ok:
            draw_fit(left_fit, (0, 255, 0))
        if right_ok:
            draw_fit(right_fit, (255, 0, 0))

        if lane_center_x is not None:
            cv2.line(bev_vis, (int(lane_center_x), 0), (int(lane_center_x), bev_h), (255, 0, 255), 1)
        cv2.line(bev_vis, (int(vehicle_center_x), 0), (int(vehicle_center_x), bev_h), (0, 0, 255), 1)

        cv2.rectangle(vis, (cw_left, cw_top), (cw_right, cw_bottom), (0, 255, 255), 1)
        cw_draw = frame[cw_top:cw_bottom, cw_left:cw_right].copy()
        for line in cw_result["lines"]:
            x0, y0, x1, y1 = line[0]
            cv2.line(cw_draw, (int(x0), int(y0)), (int(x1), int(y1)), (0, 255, 255), 1)
            cv2.line(vis, (cw_left + int(x0), cw_top + int(y0)),
                     (cw_left + int(x1), cw_top + int(y1)), (0, 255, 255), 2)

        return {
            "rl_draw": None,
            "ll_draw": None,
            "bev": bev_vis,
            "combined": vis,
            "crosswalk_draw": cw_draw,
        }