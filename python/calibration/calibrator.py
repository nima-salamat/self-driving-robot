import json
import logging
import math
import time
import threading
from pathlib import Path

import cv2
import numpy as np


logger = logging.getLogger(__name__)


class CameraCalibrator:
    """
    Camera intrinsic/distortion calibration from chessboard images.

    CHECKERBOARD is expressed as the number of INNER corners, as required by
    OpenCV's findChessboardCorners/calibrateCamera APIs.
    """

    def __init__(
        self,
        checkerboard=(11, 7),
        square_size=1.0,
        min_valid_images=10,
        min_coverage=0.03,
        min_sharpness=20.0,
        min_edge_margin=0.01,
        duplicate_distance=0.05,
        max_mean_reprojection_error=1.0,
        max_view_reprojection_error=2.5,
        detector_mode="auto",
    ):
        if len(checkerboard) == 2:
            self.checkerboard = (
                int(checkerboard[0]),
                int(checkerboard[1]),
            )
        else:
            self.checkerboard = (11, 7)

        self.square_size = float(square_size)
        if self.square_size <= 0:
            raise ValueError("square_size must be greater than zero")

        self.min_valid_images = max(3, int(min_valid_images))
        self.min_coverage = float(min_coverage)
        self.min_sharpness = float(min_sharpness)
        self.min_edge_margin = float(min_edge_margin)
        self.duplicate_distance = float(duplicate_distance)
        self.max_mean_reprojection_error = float(max_mean_reprojection_error)
        self.max_view_reprojection_error = float(max_view_reprojection_error)

        detector_mode = str(detector_mode).lower().strip()
        if detector_mode not in {"auto", "classic", "sb"}:
            raise ValueError(
                "detector_mode must be one of: auto, classic, sb"
            )
        self.detector_mode = detector_mode

        self.criteria = (
            cv2.TERM_CRITERIA_EPS
            + cv2.TERM_CRITERIA_MAX_ITER,
            30,
            0.0001,
        )

        self.object_template = np.zeros(
            (
                self.checkerboard[0]
                * self.checkerboard[1],
                3,
            ),
            np.float32,
        )

        self.object_template[:, :2] = (
            np.mgrid[
                0:self.checkerboard[0],
                0:self.checkerboard[1],
            ]
            .T
            .reshape(-1, 2)
        )

        self.object_template *= self.square_size

    def set_detector_mode(self, mode):
        mode = str(mode).lower().strip()
        if mode not in {"auto", "classic", "sb"}:
            raise ValueError(
                "detector_mode must be one of: auto, classic, sb"
            )
        self.detector_mode = mode

    def detect_corners(self, image):
        found, corners, gray, _ = self.detect_corners_detailed(image)
        return found, corners, gray

    def _detection_patterns(self):
        patterns = [self.checkerboard]
        cols, rows = self.checkerboard
        if cols != rows:
            patterns.append((rows, cols))
        return patterns

    def _detection_views(self, gray):
        """
        Yield candidate grayscale views for chessboard detection.

        - direct: original grayscale
        - clahe: contrast-enhanced (helps uneven lighting on physical boards)
        - padded: white border (helps when board touches frame edge)

        Coordinates from padded views are offset so callers stay in original
        image space. CLAHE uses offset (0, 0).
        """
        yield gray, (0, 0), "direct"

        try:
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)
            yield enhanced, (0, 0), "clahe"
        except cv2.error:
            pass

        padding = max(
            16,
            int(round(min(gray.shape[:2]) * 0.05)),
        )
        padded = cv2.copyMakeBorder(
            gray,
            padding,
            padding,
            padding,
            padding,
            cv2.BORDER_CONSTANT,
            value=255,
        )
        yield padded, (padding, padding), "padded"

        try:
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            padded_clahe = clahe.apply(padded)
            yield padded_clahe, (padding, padding), "padded_clahe"
        except cv2.error:
            pass

    def _canonicalize_corners(self, corners, detected_pattern, offset):
        points = np.asarray(corners, dtype=np.float32).reshape(-1, 1, 2)

        if tuple(detected_pattern) != tuple(self.checkerboard):
            detected_cols, detected_rows = detected_pattern
            expected_count = self.checkerboard[0] * self.checkerboard[1]
            if points.shape[0] != expected_count:
                return None

            grid = points.reshape(
                detected_rows,
                detected_cols,
                2,
            )
            points = (
                grid.transpose(1, 0, 2)
                .reshape(-1, 1, 2)
            )

        if offset != (0, 0):
            points = points - np.asarray(
                offset,
                dtype=np.float32,
            ).reshape(1, 1, 2)

        return points

    def _try_classic_detector(self, gray, pattern):
        flag_sets = [
            (
                cv2.CALIB_CB_ADAPTIVE_THRESH
                | cv2.CALIB_CB_NORMALIZE_IMAGE
            ),
            (
                cv2.CALIB_CB_ADAPTIVE_THRESH
                | cv2.CALIB_CB_NORMALIZE_IMAGE
                | cv2.CALIB_CB_FILTER_QUADS
            ),
            cv2.CALIB_CB_ADAPTIVE_THRESH,
            0,
        ]
        for flags in flag_sets:
            try:
                found, corners = cv2.findChessboardCorners(
                    gray,
                    pattern,
                    flags,
                )
                if found and corners is not None:
                    return True, corners
            except cv2.error:
                continue
        return False, None

    def _try_sb_detector(self, gray, pattern):
        detector = getattr(cv2, "findChessboardCornersSB", None)
        if detector is None:
            return False, None

        flag_sets = [
            (
                cv2.CALIB_CB_NORMALIZE_IMAGE
                | cv2.CALIB_CB_EXHAUSTIVE
                | cv2.CALIB_CB_ACCURACY
            ),
            (
                cv2.CALIB_CB_NORMALIZE_IMAGE
                | cv2.CALIB_CB_EXHAUSTIVE
            ),
            cv2.CALIB_CB_NORMALIZE_IMAGE,
            0,
        ]
        for flags in flag_sets:
            try:
                found, corners = detector(gray, pattern, flags)
                if found and corners is not None:
                    return True, corners
            except (cv2.error, TypeError):
                try:
                    found, corners = detector(gray, pattern)
                    if found and corners is not None:
                        return True, corners
                except (cv2.error, TypeError):
                    continue
        return False, None

    def detect_corners_detailed(self, image):
        if image is None or image.size == 0:
            return False, None, None, "none"

        gray = cv2.cvtColor(
            image,
            cv2.COLOR_BGR2GRAY,
        )

        detectors = []
        if self.detector_mode in {"auto", "classic"}:
            detectors.append(("classic", self._try_classic_detector))
        if self.detector_mode in {"auto", "sb"}:
            detectors.append(("sb", self._try_sb_detector))

        if not detectors:
            return False, None, gray, "none"

        patterns = self._detection_patterns()
        views = list(self._detection_views(gray))

        for view, offset, _view_name in views:
            for detector_name, detector in detectors:
                for pattern in patterns:
                    found, corners = detector(view, pattern)
                    if not found or corners is None:
                        continue

                    canonical = self._canonicalize_corners(
                        corners,
                        pattern,
                        offset,
                    )
                    if canonical is None:
                        continue

                    refined = cv2.cornerSubPix(
                        gray,
                        canonical,
                        (11, 11),
                        (-1, -1),
                        self.criteria,
                    )
                    return True, refined, gray, detector_name

        return False, None, gray, "none"

    @staticmethod
    def _coverage(corners, image_shape):
        if corners is None:
            return 0.0, None

        height, width = image_shape[:2]
        points = corners.reshape(-1, 2)

        min_xy = points.min(axis=0)
        max_xy = points.max(axis=0)

        span_x = max(0.0, float(max_xy[0] - min_xy[0]))
        span_y = max(0.0, float(max_xy[1] - min_xy[1]))

        area_ratio = (
            (span_x * span_y)
            / max(1.0, float(width * height))
        )

        center = (
            float(points[:, 0].mean() / max(1, width)),
            float(points[:, 1].mean() / max(1, height)),
        )

        return float(area_ratio), center

    def evaluate_frame(self, image):
        found, corners, gray, detector = self.detect_corners_detailed(image)
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var()) if gray is not None else 0.0
        if not found:
            return {
                "valid": False,
                "detected": False,
                "quality_valid": False,
                "corners": None,
                "coverage": 0.0,
                "center": None,
                "sharpness": sharpness,
                "edge_margin": 0.0,
                "feature": None,
                "detector": detector,
                "quality_reason": "board not detected",
                "gray": gray,
                "preview": image.copy(),
            }

        coverage, center = self._coverage(corners, image.shape)
        points = corners.reshape(-1, 2)
        height, width = image.shape[:2]
        min_xy = points.min(axis=0)
        max_xy = points.max(axis=0)
        edge_margin = min(
            float(min_xy[0]), float(min_xy[1]),
            float(width - max_xy[0]), float(height - max_xy[1]),
        ) / max(1.0, float(min(width, height)))
        span_x = max(0.0, float(max_xy[0] - min_xy[0])) / max(1.0, width)
        span_y = max(0.0, float(max_xy[1] - min_xy[1])) / max(1.0, height)
        cols, rows = self.checkerboard
        horizontal = points[cols - 1] - points[0]
        vertical = points[(rows - 1) * cols] - points[0]
        feature = np.asarray(
            [
                center[0], center[1], span_x, span_y, coverage,
                math.degrees(math.atan2(float(horizontal[1]), float(horizontal[0]))) / 180.0,
                math.degrees(math.atan2(float(vertical[1]), float(vertical[0]))) / 180.0,
            ],
            dtype=np.float32,
        )
        preview = image.copy()
        cv2.drawChessboardCorners(preview, self.checkerboard, corners, True)
        result = {
            "valid": True,
            "detected": True,
            "corners": corners,
            "coverage": coverage,
            "center": center,
            "sharpness": sharpness,
            "edge_margin": edge_margin,
            "detector": detector,
            "feature": feature,
            "gray": gray,
            "preview": preview,
        }
        result["quality_reason"] = self.quality_reason(result)
        result["quality_valid"] = result["quality_reason"] is None
        return result

    def quality_reason(self, evaluation):
        if not evaluation.get("valid"):
            return "board not detected"
        if float(evaluation.get("coverage", 0.0)) < self.min_coverage:
            return f"board too small (coverage={evaluation['coverage']:.4f})"
        if float(evaluation.get("edge_margin", 0.0)) < self.min_edge_margin:
            return "board too close to image edge"
        if float(evaluation.get("sharpness", 0.0)) < self.min_sharpness:
            return f"frame too blurry (sharpness={evaluation['sharpness']:.1f})"
        return None

    def is_duplicate(self, evaluation, accepted_features):
        feature = evaluation.get("feature")
        if feature is None:
            return False
        return any(
            float(np.linalg.norm(feature - other)) < self.duplicate_distance
            for other in accepted_features
        )

    def calibrate(self, object_points, image_points, image_size):
        if len(object_points) < self.min_valid_images:
            raise ValueError(
                f"At least {self.min_valid_images} valid calibration "
                f"images are required; got {len(object_points)}"
            )

        if image_size is None:
            raise ValueError("image_size is required")

        if len(image_points) != len(object_points):
            raise ValueError(
                "object_points and image_points must have the same length"
            )

        rms, camera_matrix, dist_coeffs, rvecs, tvecs = (
            cv2.calibrateCamera(
                object_points,
                image_points,
                tuple(map(int, image_size)),
                None,
                None,
            )
        )

        per_view_error = []
        total_error = 0.0
        total_points = 0

        for index, (
            object_point,
            image_point,
            rvec,
            tvec,
        ) in enumerate(
            zip(
                object_points,
                image_points,
                rvecs,
                tvecs,
            )
        ):
            projected, _ = cv2.projectPoints(
                object_point,
                rvec,
                tvec,
                camera_matrix,
                dist_coeffs,
            )

            point_count = max(1, len(projected))
            squared_error = float(
                cv2.norm(
                    image_point,
                    projected,
                    cv2.NORM_L2,
                )
            ) ** 2
            rms_error = math.sqrt(
                squared_error / point_count
            )

            per_view_error.append(float(rms_error))
            total_error += squared_error
            total_points += point_count

        mean_reprojection_error = math.sqrt(
            total_error / max(1, total_points)
        )

        return {
            "rms": float(rms),
            "mean_reprojection_error": float(
                mean_reprojection_error
            ),
            "per_view_error": per_view_error,
            "per_view_errors": list(per_view_error),
            "median_reprojection_error": (
                float(np.median(per_view_error)) if per_view_error else None
            ),
            "max_reprojection_error": (
                float(max(per_view_error)) if per_view_error else None
            ),
            "camera_matrix": camera_matrix,
            "dist_coeffs": dist_coeffs,
            "rvecs": rvecs,
            "tvecs": tvecs,
            "image_size": (
                int(image_size[0]),
                int(image_size[1]),
            ),
            "checkerboard": self.checkerboard,
            "square_size": self.square_size,
            "valid_images": len(object_points),
        }

    def calibrate_directory(self, image_paths):
        paths = [
            Path(path)
            for path in image_paths
        ]

        if not paths:
            raise ValueError("No calibration images found")

        object_points = []
        image_points = []
        image_size = None
        valid_paths = []
        rejected_paths = []
        accepted_features = []

        for path in sorted(paths):
            image = cv2.imread(
                str(path),
                cv2.IMREAD_COLOR,
            )

            if image is None:
                rejected_paths.append(
                    {
                        "path": str(path),
                        "reason": "image_read_failed",
                    }
                )
                continue

            current_size = (
                image.shape[1],
                image.shape[0],
            )

            if image_size is None:
                image_size = current_size
            elif current_size != image_size:
                rejected_paths.append(
                    {
                        "path": str(path),
                        "reason": (
                            "image_size_mismatch:"
                            f"{current_size}!={image_size}"
                        ),
                    }
                )
                continue

            result = self.evaluate_frame(image)
            reason = self.quality_reason(result)
            if reason is not None:
                rejected_paths.append({"path": str(path), "reason": reason})
                continue
            if self.is_duplicate(result, accepted_features):
                rejected_paths.append({
                    "path": str(path),
                    "reason": "too similar to another accepted view",
                })
                continue
            accepted_features.append(result["feature"])

            object_points.append(
                self.object_template.copy()
            )
            image_points.append(
                result["corners"]
            )
            valid_paths.append(str(path))

        calibration = self.calibrate(object_points, image_points, image_size)
        errors = list(calibration.get("per_view_errors", calibration.get("per_view_error", [])))
        if (
            errors
            and len(valid_paths) > self.min_valid_images
            and max(errors) > self.max_view_reprojection_error
        ):
            worst = int(np.argmax(errors))
            rejected_paths.append({
                "path": valid_paths.pop(worst),
                "reason": f"reprojection outlier ({errors[worst]:.3f}px)",
            })
            object_points.pop(worst)
            image_points.pop(worst)
            calibration = self.calibrate(object_points, image_points, image_size)

        reasons = []
        mean_error = float(calibration["mean_reprojection_error"])
        max_error = calibration.get("max_reprojection_error")
        if mean_error > self.max_mean_reprojection_error:
            reasons.append(
                f"mean reprojection error {mean_error:.3f}px exceeds "
                f"configured {self.max_mean_reprojection_error:.3f}px threshold"
            )
        if max_error is not None and float(max_error) > self.max_view_reprojection_error:
            reasons.append(
                f"max per-view reprojection error {float(max_error):.3f}px exceeds "
                f"configured {self.max_view_reprojection_error:.3f}px threshold"
            )
        calibration["quality_status"] = "pass" if not reasons else "fail"
        calibration["acceptable_for_runtime"] = not reasons
        calibration["quality_reasons"] = reasons
        calibration["valid_paths"] = valid_paths
        calibration["rejected_paths"] = rejected_paths
        return calibration

    @staticmethod
    def save(result, output_path):
        output_path = Path(output_path)
        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        metadata = {
            "format_version": 3,
            "calibration_model": "pinhole",
            "created_at": time.time(),
            "image_width": result["image_size"][0],
            "image_height": result["image_size"][1],
            "checkerboard_cols": result["checkerboard"][0],
            "checkerboard_rows": result["checkerboard"][1],
            "square_size": result["square_size"],
            "rms": result["rms"],
            "mean_reprojection_error": result[
                "mean_reprojection_error"
            ],
            "valid_images": result["valid_images"],
            "quality_status": result.get("quality_status", "legacy-unverified"),
            "acceptable_for_runtime": bool(result.get("acceptable_for_runtime", True)),
            "median_reprojection_error": result.get("median_reprojection_error"),
            "max_reprojection_error": result.get("max_reprojection_error"),
            "per_view_reprojection_error": result.get(
                "per_view_errors", result.get("per_view_error", [])
            ),
            "valid_paths": result.get(
                "valid_paths",
                [],
            ),
            "rejected_images": result.get(
                "rejected_paths",
                [],
            ),
        }

        np.savez(
            output_path,
            cameraMatrix=result["camera_matrix"],
            distCoeffs=result["dist_coeffs"],
            imageSize=np.array(result["image_size"], dtype=np.int32),
            metadata=json.dumps(metadata),
        )

        return output_path

    def calibrate_from_directory(self, image_dir, output_path):
        image_dir = Path(image_dir)
        if not image_dir.is_dir():
            raise ValueError(f"Not a directory: {image_dir}")

        extensions = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
        image_paths = sorted(
            p for p in image_dir.iterdir()
            if p.suffix.lower() in extensions and p.is_file()
        )
        if not image_paths:
            raise ValueError(f"No images found in {image_dir}")

        result = self.calibrate_directory(image_paths)
        self.save(result, output_path)
        return result


class CameraCalibration:
    """
    Runtime calibration loader/undistorter.

    Calibration is keyed by source resolution. When runtime resolution differs,
    the intrinsic matrix is scaled to the new resolution before undistortion.
    """

    def __init__(self, calibration_file=None, enabled=True):
        self.enabled = bool(enabled)
        self.camera_matrix = None
        self.dist_coeffs = None
        self.image_size = None

        self._new_camera_matrix_cache = {}
        self._cache_lock = threading.RLock()
        self.last_error = None
        self.quality_status = "legacy-unverified"
        self.calibration_model = "pinhole"

        if not self.enabled:
            return

        if calibration_file is None:
            calibration_file = (
                Path(__file__).resolve().parents[1]
                / "assets"
                / "camera_calibration.npz"
            )

        self.calibration_file = Path(
            calibration_file
        )

        if not self.calibration_file.exists():
            logger.warning(
                "Calibration file not found: %s. "
                "Using raw camera frames.",
                self.calibration_file,
            )
            self.enabled = False
            return

        try:
            with np.load(
                self.calibration_file,
                allow_pickle=False,
            ) as data:
                self.camera_matrix = data["cameraMatrix"]
                self.dist_coeffs = data["distCoeffs"]

                if "imageSize" in data:
                    size = data["imageSize"].astype(int).tolist()
                    if len(size) == 2 and all(int(value) > 0 for value in size):
                        self.image_size = (int(size[0]), int(size[1]))

                metadata = data["metadata"] if "metadata" in data else None
                if metadata is not None:
                    parsed = json.loads(
                        metadata.item() if hasattr(metadata, "item") else str(metadata)
                    )
                    self.quality_status = str(
                        parsed.get("quality_status", "legacy-unverified")
                    )
                    self.calibration_model = str(
                        parsed.get("calibration_model", "pinhole")
                    )
                    if parsed.get("acceptable_for_runtime") is False:
                        self.last_error = "calibration failed its runtime quality gate"
                        self.enabled = False
                        return
                    if self.calibration_model != "pinhole":
                        self.last_error = (
                            "unsupported calibration model: "
                            f"{self.calibration_model}"
                        )
                        self.enabled = False
                        return

            if self.camera_matrix.shape != (3, 3):
                raise ValueError(
                    "cameraMatrix must have shape (3, 3)"
                )

            if self.image_size is None:
                logger.warning(
                    "Calibration file has no imageSize metadata; "
                    "runtime resolution matching is not verifiable."
                )

            logger.info(
                "Camera calibration loaded successfully from %s",
                self.calibration_file,
            )

        except Exception as exc:
            logger.exception(
                "Failed to load calibration file: %s",
                self.calibration_file,
            )
            self.last_error = str(exc)
            self.enabled = False

    def _scaled_camera_matrix(self, width, height):
        if self.image_size is None:
            return self.camera_matrix

        source_width, source_height = self.image_size
        if (
            source_width <= 0
            or source_height <= 0
        ):
            return self.camera_matrix

        source_ratio = source_width / float(source_height)
        runtime_ratio = width / float(height)
        if abs(source_ratio - runtime_ratio) / source_ratio > 0.01:
            raise ValueError(
                "runtime resolution changes aspect ratio; calibration "
                "intrinsics cannot be scaled safely across a possible "
                "crop/binning/FOV change"
            )

        scale_x = width / source_width
        scale_y = height / source_height

        matrix = self.camera_matrix.astype(
            np.float64,
            copy=True,
        )

        matrix[0, 0] *= scale_x
        matrix[0, 2] *= scale_x
        matrix[1, 1] *= scale_y
        matrix[1, 2] *= scale_y

        return matrix

    def undistort(self, frame):
        if (
            not self.enabled
            or frame is None
            or frame.size == 0
        ):
            return frame

        height, width = frame.shape[:2]
        key = (
            int(width),
            int(height),
        )

        try:
            with self._cache_lock:
                cached = self._new_camera_matrix_cache.get(key)
                if cached is None:
                    matrix = self._scaled_camera_matrix(width, height)
                    new_matrix, _ = cv2.getOptimalNewCameraMatrix(
                        matrix,
                        self.dist_coeffs,
                        (width, height),
                        1,
                        (width, height),
                    )
                    cached = (matrix, new_matrix)
                    self._new_camera_matrix_cache[key] = cached
                matrix, new_matrix = cached
            return cv2.undistort(
                frame,
                matrix,
                self.dist_coeffs,
                None,
                new_matrix,
            )
        except Exception as exc:
            self.last_error = str(exc)
            self.enabled = False
            logger.error(
                "Disabling camera calibration after runtime validation failure: %s",
                exc,
            )
            return frame
