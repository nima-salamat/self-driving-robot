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
        min_sharpness=10.0,
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

        self.square_size = self._finite_float(
            "square_size",
            square_size,
            minimum=0.0,
        )
        self.min_valid_images = max(3, int(min_valid_images))
        self.min_coverage = self._finite_float(
            "min_coverage",
            min_coverage,
            minimum=0.0,
        )
        self.min_sharpness = self._finite_float(
            "min_sharpness",
            min_sharpness,
            minimum=0.0,
        )
        self.min_edge_margin = self._finite_float(
            "min_edge_margin",
            min_edge_margin,
            minimum=0.0,
        )
        self.duplicate_distance = self._finite_float(
            "duplicate_distance",
            duplicate_distance,
            minimum=0.0,
        )
        self.max_mean_reprojection_error = self._finite_float(
            "max_mean_reprojection_error",
            max_mean_reprojection_error,
            minimum=0.0,
        )
        self.max_view_reprojection_error = self._finite_float(
            "max_view_reprojection_error",
            max_view_reprojection_error,
            minimum=0.0,
        )

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
        self.last_detection_info = {
            "detector": "none",
            "view": "none",
            "scale": 1.0,
        }

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

    @staticmethod
    def _finite_float(name, value, minimum=None):
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be a number")
        if not math.isfinite(number):
            raise ValueError(f"{name} must be finite")
        if minimum is not None and number <= minimum:
            raise ValueError(f"{name} must be greater than {minimum}")
        return number

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
        Yield full-resolution recovery views for physical chessboard frames.

        Detection runs in its own worker, so robustness is preferred here over
        doing a cheap detector pass inside the live camera producer.
        """
        # Keep the cascade deliberately short.  A failed chessboard search is
        # expensive, but the threshold recovery views must be real detector
        # inputs rather than diagnostics only: a well-separated Otsu board is
        # often the only usable image under uneven camera exposure.
        yield gray, (0, 0), "direct"

        try:
            _, otsu = cv2.threshold(
                gray,
                0,
                255,
                cv2.THRESH_BINARY + cv2.THRESH_OTSU,
            )
            yield otsu, (0, 0), "otsu"
        except cv2.error:
            pass

        try:
            adaptive = cv2.adaptiveThreshold(
                gray,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                21,
                5,
            )
            yield adaptive, (0, 0), "adaptive"
        except cv2.error:
            pass

        try:
            clahe = cv2.createCLAHE(
                clipLimit=2.0,
                tileGridSize=(8, 8),
            ).apply(gray)
            yield clahe, (0, 0), "clahe"
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
        try:
            padded_clahe = cv2.createCLAHE(
                clipLimit=2.0,
                tileGridSize=(8, 8),
            ).apply(padded)
            yield padded_clahe, (padding, padding), "padded_clahe"
        except cv2.error:
            pass

    def _canonicalize_corners(self, corners, detected_pattern, offset):
        """
        Normalize detector output to the configured inner-corner ordering.

        OpenCV accepts a transposed pattern when width/height are swapped, but
        calibration object points always use self.checkerboard ordering. Padded
        detector views also operate in a translated coordinate system, so their
        offset must be removed before the corners are returned.
        """
        points = np.asarray(
            corners,
            dtype=np.float32,
        ).reshape(-1, 1, 2)

        expected_count = (
            self.checkerboard[0]
            * self.checkerboard[1]
        )
        if points.shape[0] != expected_count:
            return None

        if tuple(detected_pattern) != tuple(self.checkerboard):
            detected_cols, detected_rows = (
                int(detected_pattern[0]),
                int(detected_pattern[1]),
            )
            if (
                detected_cols * detected_rows
                != expected_count
            ):
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

    def _detection_debug_views(self, gray):
        yield "detector", gray
        try:
            yield "clahe", cv2.createCLAHE(
                clipLimit=2.0,
                tileGridSize=(8, 8),
            ).apply(gray)
        except cv2.error:
            pass
        yield "invert", cv2.bitwise_not(gray)

    def debug_preprocessed(self, image, view="detector"):
        if image is None or image.size == 0:
            return None

        gray = cv2.cvtColor(
            image,
            cv2.COLOR_BGR2GRAY,
        )
        requested = str(view or "detector").strip().lower()

        for name, prepared in self._detection_debug_views(gray):
            if name == requested:
                return cv2.cvtColor(
                    prepared,
                    cv2.COLOR_GRAY2BGR,
                )

        raise ValueError(
            "view must be one of: detector, clahe, invert"
        )

    def _try_classic_detector(self, gray, pattern, robust=False):
        # This is OpenCV's conventional, broadly compatible fallback.  Do not
        # try progressively weaker flags: each failed invocation performs a
        # complete search and can make the live UI fall badly behind.
        flags = (
            cv2.CALIB_CB_ADAPTIVE_THRESH
            | cv2.CALIB_CB_NORMALIZE_IMAGE
        )
        try:
            found, corners = cv2.findChessboardCorners(
                gray,
                pattern,
                flags,
            )
            if found and corners is not None:
                return True, corners
        except cv2.error:
            pass
        return False, None

    def _try_sb_detector(self, gray, pattern, robust=False):
        detector = getattr(
            cv2,
            "findChessboardCornersSB",
            None,
        )
        if detector is None:
            return False, None

        # The sector-based detector is substantially more robust under lens
        # distortion and perspective.  Use its high-quality single pass first
        # rather than repeatedly running it with weaker flag sets.
        flags = (
            cv2.CALIB_CB_NORMALIZE_IMAGE
            | cv2.CALIB_CB_EXHAUSTIVE
            | cv2.CALIB_CB_ACCURACY
        )
        try:
            found, corners = detector(
                gray,
                pattern,
                flags,
            )
            if found and corners is not None:
                return True, corners
        except (cv2.error, TypeError):
            try:
                found, corners = detector(gray, pattern)
                if found and corners is not None:
                    return True, corners
            except (cv2.error, TypeError):
                pass
        return False, None

    def _detect_on_view(
        self,
        gray,
        offset=(0, 0),
        robust=False,
        view_name="direct",
        binary_recovery=False,
    ):
        if self.detector_mode == "classic":
            detectors = [
                ("classic", self._try_classic_detector),
            ]
        elif self.detector_mode == "sb":
            detectors = [
                ("sb", self._try_sb_detector),
            ]
        else:
            detectors = [
                ("sb", self._try_sb_detector),
                ("classic", self._try_classic_detector),
            ]
            # The classic detector is especially reliable on the explicit
            # black/white recovery views, and avoiding an unnecessary SB
            # exhaustive search keeps these fallback passes bounded.
            if binary_recovery:
                detectors.reverse()

        for detector_name, detector in detectors:
            for pattern in self._detection_patterns():
                found, corners = detector(
                    gray,
                    pattern,
                    robust=robust,
                )
                if not found or corners is None:
                    continue

                canonical = self._canonicalize_corners(
                    corners,
                    pattern,
                    offset,
                )
                if canonical is None:
                    continue

                return {
                    "corners": canonical.astype(np.float32),
                    "detector": detector_name,
                    "view": view_name,
                    "scale": 1.0,
                }

        return None

    def detect_corners_detailed(self, image):
        if image is None or image.size == 0:
            return False, None, None, "none"

        gray = cv2.cvtColor(
            image,
            cv2.COLOR_BGR2GRAY,
        )

        detection = None
        for view, offset, view_name in self._detection_views(gray):
            detection = self._detect_on_view(
                view,
                offset=offset,
                robust=view_name != "direct",
                view_name=view_name,
                binary_recovery=view_name in {"otsu", "adaptive"},
            )
            if detection is not None:
                break

        if detection is None:
            return False, None, gray, "none"

        canonical = detection["corners"]
        try:
            refined = cv2.cornerSubPix(
                gray,
                canonical,
                (11, 11),
                (-1, -1),
                self.criteria,
            )
        except cv2.error:
            refined = canonical

        self.last_detection_info = {
            "detector": detection["detector"],
            "view": detection["view"],
            "scale": detection["scale"],
        }

        return (
            True,
            refined.astype(np.float32),
            gray,
            detection["detector"],
        )

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

    @staticmethod
    def _feature_from_corners(corners, image_shape, checkerboard):
        coverage, center = CameraCalibrator._coverage(
            corners,
            image_shape,
        )
        points = corners.reshape(-1, 2)
        height, width = image_shape[:2]
        min_xy = points.min(axis=0)
        max_xy = points.max(axis=0)

        edge_margin = min(
            float(min_xy[0]),
            float(min_xy[1]),
            float(width - max_xy[0]),
            float(height - max_xy[1]),
        ) / max(1.0, float(min(width, height)))

        span_x = max(
            0.0,
            float(max_xy[0] - min_xy[0]),
        ) / max(1.0, width)
        span_y = max(
            0.0,
            float(max_xy[1] - min_xy[1]),
        ) / max(1.0, height)

        cols, rows = checkerboard
        horizontal = points[cols - 1] - points[0]
        vertical = points[(rows - 1) * cols] - points[0]

        feature = np.asarray(
            [
                center[0],
                center[1],
                span_x,
                span_y,
                coverage,
                math.degrees(
                    math.atan2(
                        float(horizontal[1]),
                        float(horizontal[0]),
                    )
                ) / 180.0,
                math.degrees(
                    math.atan2(
                        float(vertical[1]),
                        float(vertical[0]),
                    )
                ) / 180.0,
            ],
            dtype=np.float32,
        )
        return coverage, center, edge_margin, feature

    def evaluate_frame(self, image):
        found, corners, gray, detector = self.detect_corners_detailed(image)
        sharpness = (
            float(
                cv2.Laplacian(
                    gray,
                    cv2.CV_64F,
                ).var()
            )
            if gray is not None
            else 0.0
        )

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
                "detection_view": "none",
                "detection_scale": 1.0,
                "quality_reason": "board not detected",
                "gray": gray,
                "preview": image.copy(),
            }

        coverage, center, edge_margin, feature = (
            self._feature_from_corners(
                corners,
                image.shape,
                self.checkerboard,
            )
        )
        info = dict(self.last_detection_info)

        preview = image.copy()
        cv2.drawChessboardCorners(
            preview,
            self.checkerboard,
            corners,
            True,
        )
        result = {
            "valid": True,
            "detected": True,
            "corners": corners,
            "coverage": coverage,
            "center": center,
            "sharpness": sharpness,
            "edge_margin": edge_margin,
            "detector": detector,
            "detection_view": info.get("view", "detector"),
            "detection_scale": float(info.get("scale", 1.0)),
            "feature": feature,
            "gray": gray,
            "preview": preview,
        }
        result["quality_reason"] = self.quality_reason(result)
        result["quality_valid"] = result["quality_reason"] is None
        return result

    def evaluation_from_metadata(self, metadata, image_shape):
        if not isinstance(metadata, dict):
            return None
        try:
            if int(metadata.get("format_version", 0)) < 1:
                return None
            checkerboard = tuple(
                int(value)
                for value in metadata.get("checkerboard", ())
            )
        except (TypeError, ValueError):
            return None

        if checkerboard != self.checkerboard:
            return None

        image_size = metadata.get("image_size")
        if (
            not isinstance(image_size, (list, tuple))
            or len(image_size) != 2
        ):
            return None
        try:
            expected_size = tuple(map(int, image_size))
        except (TypeError, ValueError):
            return None

        if expected_size != (
            int(image_shape[1]),
            int(image_shape[0]),
        ):
            return None

        try:
            corners = np.asarray(
                metadata["corners"],
                dtype=np.float32,
            ).reshape(-1, 1, 2)
        except (KeyError, TypeError, ValueError):
            return None

        expected_count = (
            self.checkerboard[0] * self.checkerboard[1]
        )
        if corners.shape[0] != expected_count:
            return None
        if not np.isfinite(corners).all():
            return None

        coverage, center, edge_margin, feature = (
            self._feature_from_corners(
                corners,
                image_shape,
                self.checkerboard,
            )
        )
        try:
            sharpness = float(
                metadata.get("sharpness", 0.0)
            )
            detection_scale = float(
                metadata.get("detection_scale", 1.0)
            )
        except (TypeError, ValueError):
            return None
        if not math.isfinite(sharpness):
            return None
        if not math.isfinite(detection_scale) or detection_scale <= 0:
            return None

        return {
            "valid": True,
            "detected": True,
            "quality_valid": True,
            "corners": corners,
            "coverage": coverage,
            "center": center,
            "sharpness": sharpness,
            "edge_margin": edge_margin,
            "feature": feature,
            "detector": str(
                metadata.get("detector", "stored")
            ),
            "detection_view": str(
                metadata.get("detection_view", "stored")
            ),
            "detection_scale": detection_scale,
            "quality_reason": None,
            "gray": None,
            "preview": None,
            "metadata_source": "capture",
        }

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

    def calibrate_directory(self, image_paths, metadata_loader=None):
        paths = [Path(path) for path in image_paths]
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
                rejected_paths.append({
                    "path": str(path),
                    "reason": "image_read_failed",
                })
                continue

            current_size = (
                image.shape[1],
                image.shape[0],
            )
            if image_size is None:
                image_size = current_size
            elif current_size != image_size:
                rejected_paths.append({
                    "path": str(path),
                    "reason": (
                        "image_size_mismatch:"
                        f"{current_size}!={image_size}"
                    ),
                })
                continue

            result = None
            if callable(metadata_loader):
                try:
                    metadata = metadata_loader(path)
                except Exception:
                    metadata = None
                    logger.exception(
                        "Failed to load calibration metadata: %s",
                        path,
                    )
                if metadata is not None:
                    result = self.evaluation_from_metadata(
                        metadata,
                        image.shape,
                    )
                    if result is None:
                        rejected_paths.append({
                            "path": str(path),
                            "reason": "capture_metadata_incompatible",
                        })
                        continue

            if result is None:
                result = self.evaluate_frame(image)
                reason = self.quality_reason(result)
                if reason is not None:
                    rejected_paths.append({
                        "path": str(path),
                        "reason": reason,
                    })
                    continue

            if self.is_duplicate(
                result,
                accepted_features,
            ):
                rejected_paths.append({
                    "path": str(path),
                    "reason": (
                        "too similar to another accepted view"
                    ),
                })
                continue

            accepted_features.append(
                np.asarray(
                    result["feature"],
                    dtype=np.float32,
                )
            )
            object_points.append(
                self.object_template.copy()
            )
            image_points.append(
                result["corners"]
            )
            valid_paths.append(str(path))

        calibration = self.calibrate(
            object_points,
            image_points,
            image_size,
        )
        errors = list(
            calibration.get(
                "per_view_errors",
                calibration.get("per_view_error", []),
            )
        )

        if (
            errors
            and len(valid_paths) > self.min_valid_images
            and max(errors) > self.max_view_reprojection_error
        ):
            worst = int(np.argmax(errors))
            rejected_paths.append({
                "path": valid_paths.pop(worst),
                "reason": (
                    f"reprojection outlier "
                    f"({errors[worst]:.3f}px)"
                ),
            })
            object_points.pop(worst)
            image_points.pop(worst)
            calibration = self.calibrate(
                object_points,
                image_points,
                image_size,
            )

        reasons = []
        mean_error = float(
            calibration["mean_reprojection_error"]
        )
        max_error = calibration.get(
            "max_reprojection_error"
        )
        if mean_error > self.max_mean_reprojection_error:
            reasons.append(
                f"mean reprojection error "
                f"{mean_error:.3f}px exceeds configured "
                f"{self.max_mean_reprojection_error:.3f}px threshold"
            )
        if (
            max_error is not None
            and float(max_error) > self.max_view_reprojection_error
        ):
            reasons.append(
                f"max per-view reprojection error "
                f"{float(max_error):.3f}px exceeds configured "
                f"{self.max_view_reprojection_error:.3f}px threshold"
            )

        calibration["quality_status"] = (
            "pass" if not reasons else "fail"
        )
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

    def calibrate_from_directory(
        self,
        image_dir,
        output_path,
        metadata_loader=None,
    ):
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

        result = self.calibrate_directory(
            image_paths,
            metadata_loader=metadata_loader,
        )
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
            if not np.isfinite(self.camera_matrix).all():
                raise ValueError(
                    "cameraMatrix contains non-finite values"
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
