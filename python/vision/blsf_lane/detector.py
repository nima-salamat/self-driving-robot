import math
import time

import cv2
import numpy as np


class BLSFLaneDetector:
    """
    Beta classical lane detector based on a BEV + line-segment pipeline.

    Pipeline:
        BEV -> weighted grayscale -> median local threshold
        -> LSD -> Binary Line Segment Filter -> column projection
        -> sliding windows -> quadratic RANSAC fit

    This detector is City-mode only and is intentionally opt-in.
    """

    def __init__(self, config):
        self.config = config
        self.last_steering = float(getattr(config, "SERVO_CENTER", 90))
        self.last_error = 0.0

        self._bev_key = None
        self._bev_matrix = None
        self._lsd = cv2.createLineSegmentDetector(0)
        self._rng = np.random.default_rng(
            int(getattr(config, "BLSF_RANDOM_SEED", 42))
        )

        self.min_segment_length = float(
            getattr(config, "BLSF_MIN_SEGMENT_LENGTH", 17)
        )
        self.angle_limit = float(
            getattr(config, "BLSF_ANGLE_LIMIT_DEG", 35)
        )
        self.straight_band = float(
            getattr(config, "BLSF_STRAIGHT_BAND_DEG", 5)
        )
        self.min_angle_vote = float(
            getattr(config, "BLSF_MIN_ANGLE_VOTE", 20)
        )

        kernel = int(getattr(config, "BLSF_MEDIAN_KERNEL", 9))
        kernel = max(3, kernel)
        self.median_kernel = kernel + 1 if kernel % 2 == 0 else kernel

        self.local_threshold = int(
            getattr(config, "BLSF_LOCAL_THRESHOLD", 15)
        )
        self.num_windows = max(
            3, int(getattr(config, "BLSF_NUM_WINDOWS", 9))
        )
        self.window_width_factor = float(
            getattr(config, "BLSF_WINDOW_WIDTH_FACTOR", 0.40)
        )

        self.ransac_iterations = max(
            1, int(getattr(config, "BLSF_RANSAC_ITERATIONS", 80))
        )
        self.ransac_threshold = float(
            getattr(config, "BLSF_RANSAC_INLIER_THRESHOLD", 6.0)
        )
        self.min_fit_points = max(
            3, int(getattr(config, "BLSF_MIN_FIT_POINTS", 12))
        )

    def _cfg(self, name, default):
        return getattr(self.config, name, default)

    def _bev(self, frame):
        # BLSF beta intentionally reuses the existing City BEV configuration.
        if not self._cfg("USE_BEV", False):
            return frame

        height, width = frame.shape[:2]
        key = (
            width,
            height,
            self._cfg("BEV_SRC_TL_X", 0.35),
            self._cfg("BEV_SRC_TL_Y", 0.60),
            self._cfg("BEV_SRC_TR_X", 0.65),
            self._cfg("BEV_SRC_TR_Y", 0.60),
            self._cfg("BEV_SRC_BR_X", 1.00),
            self._cfg("BEV_SRC_BR_Y", 1.00),
            self._cfg("BEV_SRC_BL_X", 0.00),
            self._cfg("BEV_SRC_BL_Y", 1.00),
        )

        if key != self._bev_key:
            src = np.float32(
                [
                    [width * key[2], height * key[3]],
                    [width * key[4], height * key[5]],
                    [width * key[6], height * key[7]],
                    [width * key[8], height * key[9]],
                ]
            )
            dst = np.float32(
                [
                    [0, 0],
                    [width, 0],
                    [width, height],
                    [0, height],
                ]
            )
            self._bev_matrix = cv2.getPerspectiveTransform(src, dst)
            self._bev_key = key

        return cv2.warpPerspective(
            frame,
            self._bev_matrix,
            (width, height),
            flags=cv2.INTER_LINEAR,
        )

    @staticmethod
    def _weighted_gray(frame):
        b, g, r = cv2.split(frame.astype(np.float32))
        gray = 0.1 * b + 0.4 * g + 0.5 * r
        return np.clip(gray, 0, 255).astype(np.uint8)

    def _median_local_threshold(self, gray):
        local_median = cv2.medianBlur(
            gray,
            self.median_kernel,
        )
        bright = (
            gray.astype(np.int16)
            > local_median.astype(np.int16) + self.local_threshold
        )
        return np.where(bright, gray, 0).astype(np.uint8)

    @staticmethod
    def _vertical_angle(x1, y1, x2, y2):
        dx = float(x2 - x1)
        dy = float(y2 - y1)

        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            return 0.0

        angle = math.degrees(math.atan2(dx, -dy))
        while angle > 90:
            angle -= 180
        while angle < -90:
            angle += 180
        return angle

    def _segments(self, binary):
        lines = self._lsd.detect(binary)[0]
        if lines is None:
            return []

        segments = []
        for line in lines[:, 0]:
            x1, y1, x2, y2 = map(float, line)
            length = math.hypot(x2 - x1, y2 - y1)
            if length < self.min_segment_length:
                continue

            angle = self._vertical_angle(x1, y1, x2, y2)
            if abs(angle) > self.angle_limit:
                continue

            segments.append(
                (x1, y1, x2, y2, length, angle)
            )

        return segments

    def _blsf_band(self, segments):
        if not segments:
            return None, (0.0, 0.0, 0.0)

        bands = (
            (-self.angle_limit, -self.straight_band),
            (-self.straight_band, self.straight_band),
            (self.straight_band, self.angle_limit),
        )

        votes = np.zeros(3, dtype=np.float64)

        for segment in segments:
            length = segment[4]
            angle = segment[5]
            for index, (low, high) in enumerate(bands):
                if low <= angle <= high:
                    votes[index] += length

        best = int(np.argmax(votes))
        if votes[best] < self.min_angle_vote:
            return None, tuple(votes.tolist())

        return bands[best], tuple(votes.tolist())

    def _blsf_binary(self, thresholded, segments, band):
        if band is None:
            return np.zeros_like(thresholded)

        low, high = band
        filtered = np.zeros_like(thresholded)

        for x1, y1, x2, y2, _, angle in segments:
            if not low <= angle <= high:
                continue

            cv2.line(
                filtered,
                (int(round(x1)), int(round(y1))),
                (int(round(x2)), int(round(y2))),
                255,
                1,
                cv2.LINE_AA,
            )

        return cv2.bitwise_and(filtered, thresholded)

    @staticmethod
    def _smooth_hist(hist, size=9):
        size = max(3, int(size))
        if size % 2 == 0:
            size += 1
        kernel = np.ones(size, dtype=np.float32) / size
        return np.convolve(hist.astype(np.float32), kernel, mode="same")

    def _seeds(self, binary):
        height, width = binary.shape
        near = binary[int(height * 0.55):]
        histogram = self._smooth_hist(
            (near > 0).sum(axis=0)
        )

        if histogram.max() <= 0:
            return None, None, histogram

        minimum_vote = max(2.0, float(histogram.max()) * 0.15)
        center = width / 2.0

        left = np.flatnonzero(
            histogram[:int(center)] >= minimum_vote
        )
        right = np.flatnonzero(
            histogram[int(center):] >= minimum_vote
        )

        left_seed = (
            int(left[np.argmax(histogram[left])])
            if left.size
            else None
        )
        right_seed = (
            int(center) + int(
                right[np.argmax(
                    histogram[int(center) + right]
                )]
            )
            if right.size
            else None
        )

        return left_seed, right_seed, histogram

    def _track(self, binary, seed, window_width):
        if seed is None:
            return None

        height, _ = binary.shape
        window_height = max(1, height // self.num_windows)
        window_width = max(8.0, float(window_width))

        ys, xs = np.nonzero(binary > 0)
        current_x = float(seed)
        points = []

        for index in range(self.num_windows):
            y_low = max(
                0, height - (index + 1) * window_height
            )
            y_high = min(
                height, height - index * window_height
            )

            x_low = max(
                0, int(current_x - window_width / 2)
            )
            x_high = min(
                binary.shape[1],
                int(current_x + window_width / 2)
            )

            selected = (
                (ys >= y_low)
                & (ys < y_high)
                & (xs >= x_low)
                & (xs < x_high)
            )

            local_x = xs[selected]
            local_y = ys[selected]

            if local_x.size == 0:
                continue

            points.extend(
                zip(
                    local_x.astype(float),
                    local_y.astype(float),
                )
            )
            current_x = float(local_x.mean())

        if len(points) < self.min_fit_points:
            return None

        return np.asarray(points, dtype=np.float64)

    def _ransac_parabola(self, points):
        if points is None or len(points) < 3:
            return None

        x = points[:, 0]
        y = points[:, 1]

        if np.ptp(y) < 5:
            return None

        best_coeff = None
        best_inliers = -1
        best_mse = float("inf")

        for _ in range(self.ransac_iterations):
            indices = self._rng.choice(
                len(points),
                size=3,
                replace=False,
            )
            sample_y = y[indices]
            sample_x = x[indices]

            try:
                coeff = np.polyfit(
                    sample_y,
                    sample_x,
                    2,
                )
            except (np.linalg.LinAlgError, ValueError):
                continue

            residual = np.abs(
                x - np.polyval(coeff, y)
            )
            inlier_mask = residual <= self.ransac_threshold
            inlier_count = int(np.count_nonzero(inlier_mask))

            if inlier_count < self.min_fit_points:
                continue

            mse = float(
                np.mean(residual[inlier_mask] ** 2)
            )

            if (
                inlier_count > best_inliers
                or (
                    inlier_count == best_inliers
                    and mse < best_mse
                )
            ):
                best_coeff = coeff
                best_inliers = inlier_count
                best_mse = mse

        if best_coeff is None:
            return None

        inliers = (
            np.abs(
                x - np.polyval(best_coeff, y)
            )
            <= self.ransac_threshold
        )

        if np.count_nonzero(inliers) >= 3:
            try:
                best_coeff = np.polyfit(
                    y[inliers],
                    x[inliers],
                    2,
                )
            except (np.linalg.LinAlgError, ValueError):
                pass

        return best_coeff

    def _lane_state(self, left, right, width, height):
        y = height * 0.90

        left_x = (
            float(np.polyval(left, y))
            if left is not None
            else None
        )
        right_x = (
            float(np.polyval(right, y))
            if right is not None
            else None
        )

        if left_x is not None and right_x is not None:
            return (
                (left_x + right_x) / 2.0,
                "both",
                left_x,
                right_x,
            )

        half_width = width * float(
            self._cfg(
                "BLSF_FALLBACK_HALF_LANE_WIDTH",
                0.20,
            )
        )

        if left_x is not None:
            return (
                left_x + half_width,
                "only_left",
                left_x,
                None,
            )

        if right_x is not None:
            return (
                right_x - half_width,
                "only_right",
                None,
                right_x,
            )

        return (
            width / 2.0,
            "none",
            None,
            None,
        )

    def _detect_crosswalk(self, frame):
        crosswalk = False
        lines_for_debug = []

        height, width = frame.shape[:2]
        top = int(self._cfg("CW_TOP_ROI", 0.8) * height)
        bottom = int(self._cfg("CW_BOTTOM_ROI", 1.0) * height)
        left = int(self._cfg("CW_LEFT_ROI", 0.3) * width)
        right = int(self._cfg("CW_RIGHT_ROI", 0.9) * width)

        roi = frame[top:bottom, left:right].copy()
        if roi.size == 0:
            return crosswalk, lines_for_debug, (top, bottom, left, right)

        if self._cfg("CW_TRAPEZOID_MODE", False):
            roi_height, roi_width = roi.shape[:2]
            factor = float(
                self._cfg("CW_TOP_WIDTH_FACTOR", 0.90)
            )
            polygon = np.array(
                [
                    [
                        int(
                            roi_width
                            * (1 - factor)
                            / 2
                        ),
                        0,
                    ],
                    [
                        int(
                            roi_width
                            * (1 + factor)
                            / 2
                        ),
                        0,
                    ],
                    [roi_width, roi_height],
                    [0, roi_height],
                ],
                dtype=np.int32,
            )
            mask = np.zeros(
                (roi_height, roi_width),
                dtype=np.uint8,
            )
            cv2.fillPoly(mask, [polygon], 255)
            roi = cv2.bitwise_and(roi, roi, mask=mask)

        gray = cv2.cvtColor(
            roi,
            cv2.COLOR_BGR2GRAY,
        )
        _, gray = cv2.threshold(
            gray,
            int(self._cfg("CROSSWALK_THRESHOLD", 180)),
            255,
            cv2.THRESH_BINARY,
        )
        edges = cv2.Canny(gray, 100, 150)

        if self._cfg("CW_OLD_METHOD", True):
            lines = self._lsd.detect(edges)[0]
        else:
            lines = cv2.HoughLinesP(
                edges,
                1,
                np.pi / 180,
                threshold=20,
                minLineLength=5,
                maxLineGap=5,
            )

        diagonal = math.hypot(
            right - left,
            bottom - top,
        )
        minimum_length = max(
            diagonal / 10,
            10,
        )
        pixel_distance = 0.7 * (bottom - top)

        vertical = 0
        horizontal = 0
        lowest_horizontal = None

        if lines is not None:
            for line in lines:
                x0, y0, x1, y1 = line[0]
                length = math.hypot(
                    x1 - x0,
                    y1 - y0,
                )
                if length < minimum_length:
                    continue

                slope = (
                    (y1 - y0)
                    / (x1 - x0 + 1e-6)
                )
                angle = abs(
                    math.degrees(
                        math.atan(slope)
                    )
                )

                if angle <= 30:
                    horizontal += 1
                    lines_for_debug.append(line)
                    if (
                        lowest_horizontal is None
                        or max(y0, y1)
                        > max(
                            lowest_horizontal[0][0][1],
                            lowest_horizontal[0][0][3],
                        )
                    ):
                        lowest_horizontal = line
                elif angle >= 60:
                    vertical += 1
                    lines_for_debug.append(line)

        if (
            vertical >= 4
            and horizontal >= 3
            and lowest_horizontal is not None
        ):
            _, y0, _, y1 = lowest_horizontal[0]
            if max(y0, y1) > pixel_distance:
                crosswalk = True

        return (
            crosswalk,
            lines_for_debug,
            (top, bottom, left, right),
        )

    def _steering(self, lane_center, lane_type, width):
        center = float(
            self._cfg("SERVO_CENTER", 90)
        )
        minimum = float(
            self._cfg("MIN_SERVO_ANGLE", 55)
        )
        maximum = float(
            self._cfg("MAX_SERVO_ANGLE", 125)
        )

        if lane_type == "none":
            return (
                int(
                    np.clip(
                        self._cfg(
                            "BLSF_NO_LANE_STEERING",
                            150,
                        ),
                        minimum,
                        maximum,
                    )
                ),
                0.0,
            )

        error = width / 2.0 - lane_center
        kp = float(
            self._cfg("BLSF_STEERING_KP", 0.45)
        )

        target = float(
            np.clip(
                center - kp * error,
                minimum,
                maximum,
            )
        )

        smoothing = float(
            self._cfg(
                "BLSF_STEERING_SMOOTHING",
                0.70,
            )
        )
        target = (
            smoothing * target
            + (1.0 - smoothing) * self.last_steering
        )

        self.last_steering = target
        self.last_error = error
        return int(round(target)), float(error)

    def _debug_frame(
        self,
        frame,
        left_model,
        right_model,
        lane_center,
        lane_type,
        crosswalk,
        crosswalk_lines,
        crosswalk_roi,
    ):
        vis = frame.copy()
        height, width = vis.shape[:2]
        y_values = np.arange(
            height,
            dtype=np.float32,
        )

        for model in (left_model, right_model):
            if model is None:
                continue

            x_values = np.polyval(
                model,
                y_values,
            )
            points = np.column_stack(
                (x_values, y_values)
            ).astype(np.int32)

            valid = (
                (points[:, 0] >= 0)
                & (points[:, 0] < width)
                & (points[:, 1] >= 0)
                & (points[:, 1] < height)
            )
            points = points[valid]

            if len(points) > 1:
                cv2.polylines(
                    vis,
                    [points],
                    False,
                    (0, 255, 0),
                    2,
                )

        center_x = int(width / 2)
        cv2.line(
            vis,
            (center_x, 0),
            (center_x, height),
            (0, 0, 255),
            1,
        )
        cv2.line(
            vis,
            (int(lane_center), 0),
            (int(lane_center), height),
            (255, 0, 255),
            1,
        )

        top, bottom, left, right = crosswalk_roi
        cv2.rectangle(
            vis,
            (left, top),
            (right, bottom),
            (0, 255, 255),
            1,
        )

        for line in crosswalk_lines:
            x0, y0, x1, y1 = line[0]
            cv2.line(
                vis,
                (left + int(x0), top + int(y0)),
                (left + int(x1), top + int(y1)),
                (0, 255, 255),
                2,
            )

        cv2.putText(
            vis,
            (
                f"BLSF-BETA lane={lane_type} "
                f"error={self.last_error:.1f} "
                f"crosswalk={crosswalk}"
            ),
            (10, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )

        return vis

    def detect(self, frame, debug_frame=None):
        started = time.monotonic()

        if frame is None or frame.size == 0:
            return {
                "steering_angle": int(self.last_steering),
                "error": self.last_error,
                "lane_type": "none",
                "perception_valid": False,
                "crosswalk": False,
                "debug": {"combined": None, "cw_draw": None},
                "kp": 0,
                "lane_detector": "blsf-beta",
                "lane_latency_ms": 0.0,
            }

        bev = self._bev(frame)
        gray = self._weighted_gray(bev)
        thresholded = self._median_local_threshold(gray)

        segments = self._segments(thresholded)
        band, votes = self._blsf_band(segments)
        binary = self._blsf_binary(
            thresholded,
            segments,
            band,
        )

        left_seed, right_seed, histogram = self._seeds(binary)

        if left_seed is not None and right_seed is not None:
            lane_width = max(
                1.0,
                float(right_seed - left_seed),
            )
        else:
            lane_width = frame.shape[1] * float(
                self._cfg(
                    "BLSF_DEFAULT_LANE_WIDTH",
                    0.40,
                )
            )

        window_width = (
            self.window_width_factor
            * lane_width
        )

        left_points = self._track(
            binary,
            left_seed,
            window_width,
        )
        right_points = self._track(
            binary,
            right_seed,
            window_width,
        )

        left_model = self._ransac_parabola(
            left_points
        )
        right_model = self._ransac_parabola(
            right_points
        )

        lane_center, lane_type, left_x, right_x = (
            self._lane_state(
                left_model,
                right_model,
                frame.shape[1],
                frame.shape[0],
            )
        )

        steering_angle, error = self._steering(
            lane_center,
            lane_type,
            frame.shape[1],
        )

        crosswalk, crosswalk_lines, crosswalk_roi = (
            self._detect_crosswalk(bev)
        )

        debug = {
            "combined": None,
            "cw_draw": None,
            "binary": binary,
            "histogram": histogram,
            "segments": segments,
            "selected_angle_band": band,
            "angle_votes": votes,
            "left_model": left_model,
            "right_model": right_model,
        }

        if (
            self._cfg("DEBUG", False)
            or self._cfg("STREAM", False)
        ):
            debug["combined"] = self._debug_frame(
                bev,
                left_model,
                right_model,
                lane_center,
                lane_type,
                crosswalk,
                crosswalk_lines,
                crosswalk_roi,
            )

        return {
            "steering_angle": steering_angle,
            "error": error,
            "lane_type": lane_type,
            "perception_valid": lane_type != "none",
            "crosswalk": crosswalk,
            "debug": debug,
            "kp": float(
                self._cfg(
                    "BLSF_STEERING_KP",
                    0.45,
                )
            ),
            "lane_detector": "blsf-beta",
            "lane_latency_ms": (
                time.monotonic() - started
            ) * 1000.0,
            "lane_segment_count": len(segments),
            "lane_left_x": left_x,
            "lane_right_x": right_x,
            "lane_angle_band": band,
            "lane_angle_votes": votes,
        }


def create_blsf_lane_detector(config):
    return BLSFLaneDetector(config)
