import json
import logging
import math
import time
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
    ):
        self.checkerboard = (
            int(checkerboard[0]),
            int(checkerboard[1]),
        )
        if len(checkerboard) == 2
        else (11, 7)

        self.square_size = float(square_size)
        if self.square_size <= 0:
            raise ValueError("square_size must be greater than zero")

        self.min_valid_images = max(
            3,
            int(min_valid_images),
        )

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

    def detect_corners(self, image):
        if image is None or image.size == 0:
            return False, None, None

        gray = cv2.cvtColor(
            image,
            cv2.COLOR_BGR2GRAY,
        )

        flags = (
            cv2.CALIB_CB_ADAPTIVE_THRESH
            | cv2.CALIB_CB_NORMALIZE_IMAGE
        )

        found, corners = cv2.findChessboardCorners(
            gray,
            self.checkerboard,
            flags,
        )

        if not found:
            return False, None, gray

        refined = cv2.cornerSubPix(
            gray,
            corners,
            (11, 11),
            (-1, -1),
            self.criteria,
        )

        return True, refined, gray

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
        found, corners, gray = self.detect_corners(image)
        if not found:
            return {
                "valid": False,
                "corners": None,
                "coverage": 0.0,
                "center": None,
                "gray": gray,
            }

        coverage, center = self._coverage(
            corners,
            image.shape,
        )

        preview = image.copy()
        cv2.drawChessboardCorners(
            preview,
            self.checkerboard,
            corners,
            True,
        )

        return {
            "valid": True,
            "corners": corners,
            "coverage": coverage,
            "center": center,
            "gray": gray,
            "preview": preview,
        }

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

            error = cv2.norm(
                image_point,
                projected,
                cv2.NORM_L2,
            ) / max(
                1,
                len(projected),
            )

            per_view_error.append(float(error))
            total_error += float(error) ** 2 * len(projected)
            total_points += len(projected)

        mean_reprojection_error = math.sqrt(
            total_error / max(1, total_points)
        )

        return {
            "rms": float(rms),
            "mean_reprojection_error": float(
                mean_reprojection_error
            ),
            "per_view_error": per_view_error,
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
            if not result["valid"]:
                rejected_paths.append(
                    {
                        "path": str(path),
                        "reason": "chessboard_not_found",
                    }
                )
                continue

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
            "format_version": 2,
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
            imageSize=np.asarray(
                result["image_size"],
                dtype=np.int32,
            ),
            checkerboard=np.asarray(
                result["checkerboard"],
                dtype=np.int32,
            ),
            squareSize=np.asarray(
                result["square_size"],
                dtype=np.float64,
            ),
            rms=np.asarray(
                result["rms"],
                dtype=np.float64,
            ),
            meanReprojectionError=np.asarray(
                result["mean_reprojection_error"],
                dtype=np.float64,
            ),
            metadata=np.asarray(
                json.dumps(
                    metadata,
                    ensure_ascii=False,
                )
            ),
        )

        logger.info(
            "Saved camera calibration: %s",
            output_path,
        )

    def calibrate_from_directory(
        self,
        image_dir,
        output_path,
    ):
        image_dir = Path(image_dir)
        paths = sorted(
            image_dir.glob("*.jpg")
        )
        paths += sorted(
            image_dir.glob("*.jpeg")
        )
        paths += sorted(
            image_dir.glob("*.png")
        )

        result = self.calibrate_directory(paths)
        self.save(
            result,
            output_path,
        )
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
                    if len(size) == 2:
                        self.image_size = (
                            int(size[0]),
                            int(size[1]),
                        )

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

        except Exception:
            logger.exception(
                "Failed to load calibration file: %s",
                self.calibration_file,
            )
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

        cached = self._new_camera_matrix_cache.get(key)
        if cached is None:
            matrix = self._scaled_camera_matrix(
                width,
                height,
            )

            new_matrix, _ = cv2.getOptimalNewCameraMatrix(
                matrix,
                self.dist_coeffs,
                (width, height),
                1,
                (width, height),
            )

            cached = (
                matrix,
                new_matrix,
            )
            self._new_camera_matrix_cache[key] = cached

        matrix, new_matrix = cached

        return cv2.undistort(
            frame,
            matrix,
            self.dist_coeffs,
            None,
            new_matrix,
        )
