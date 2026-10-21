"""Safe paths and validation for camera intrinsic calibration assets."""
import re
import zipfile
from pathlib import Path

import numpy as np

PYTHON_ROOT = Path(__file__).resolve().parents[1]
CALIBRATION_ASSET_RELATIVE_DIR = "assets/camera_calibrations"
CALIBRATION_ASSET_DIR = PYTHON_ROOT / "assets" / "camera_calibrations"
DEFAULT_CALIBRATION_REFERENCE = CALIBRATION_ASSET_RELATIVE_DIR + "/camera_calibration.npz"
MAX_UPLOAD_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}\.npz\Z", re.IGNORECASE)


def calibration_path_from_reference(reference, require_exists=True):
    """Resolve a mode-JSON reference without permitting traversal or arbitrary paths."""
    if not isinstance(reference, str):
        raise ValueError("CAMERA_CALIBRATION_FILE must be a relative calibration asset path")
    normalized = reference.strip()
    prefix = CALIBRATION_ASSET_RELATIVE_DIR + "/"
    if not normalized.startswith(prefix):
        raise ValueError("camera calibration must be stored under " + CALIBRATION_ASSET_RELATIVE_DIR)
    name = normalized[len(prefix):]
    if "/" in name or "\\" in name or not _SAFE_NAME.fullmatch(name):
        raise ValueError("camera calibration must name one .npz file inside " + CALIBRATION_ASSET_RELATIVE_DIR)
    directory = CALIBRATION_ASSET_DIR.resolve()
    path = (directory / name).resolve()
    if path.parent != directory:
        raise ValueError("camera calibration path escapes the calibration assets directory")
    if require_exists and not path.is_file():
        raise ValueError("camera calibration file does not exist: " + name)
    return path


def calibration_reference_for_path(path):
    """Convert an existing calibration file path back to its canonical JSON reference."""
    candidate = Path(path).resolve()
    directory = CALIBRATION_ASSET_DIR.resolve()
    if candidate.parent != directory or not candidate.is_file() or candidate.suffix.lower() != ".npz":
        raise ValueError("calibration file must be an .npz directly inside " + str(directory))
    if not _SAFE_NAME.fullmatch(candidate.name):
        raise ValueError("calibration file name contains unsupported characters")
    return CALIBRATION_ASSET_RELATIVE_DIR + "/" + candidate.name


def validate_calibration_file(path):
    """Validate archive structure, numeric intrinsics, and runtime quality before use."""
    path = Path(path)
    if not path.is_file() or path.suffix.lower() != ".npz":
        raise ValueError("camera calibration must be an existing .npz file")
    size_bytes = path.stat().st_size
    if size_bytes <= 0 or size_bytes > MAX_UPLOAD_BYTES:
        raise ValueError("calibration file must be between 1 byte and 16 MiB")
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            names = {member.filename for member in members}
            if len(members) > 16 or not {"cameraMatrix.npy", "distCoeffs.npy"}.issubset(names):
                raise ValueError("NPZ must contain cameraMatrix.npy and distCoeffs.npy")
            uncompressed = sum(member.file_size for member in members)
            if uncompressed > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                raise ValueError("calibration archive expands beyond the 64 MiB safety limit")
            if any(member.file_size > MAX_ARCHIVE_UNCOMPRESSED_BYTES for member in members):
                raise ValueError("calibration archive contains an oversized member")
            if any(member.filename.startswith("/") or ".." in Path(member.filename).parts for member in members):
                raise ValueError("calibration archive contains an unsafe member path")
    except zipfile.BadZipFile as exc:
        raise ValueError("file is not a valid NumPy .npz archive") from exc

    from .calibrator import CameraCalibration
    calibration = CameraCalibration(calibration_file=path, enabled=True)
    if not calibration.enabled or calibration.camera_matrix is None or calibration.dist_coeffs is None:
        raise ValueError(calibration.last_error or "calibration could not be loaded for runtime use")
    matrix = np.asarray(calibration.camera_matrix, dtype=np.float64)
    distortion = np.asarray(calibration.dist_coeffs, dtype=np.float64)
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
        raise ValueError("cameraMatrix must be a finite 3x3 matrix")
    if matrix[0, 0] <= 0 or matrix[1, 1] <= 0:
        raise ValueError("cameraMatrix focal lengths must be positive")
    if distortion.size not in {4, 5, 8, 12, 14} or not np.isfinite(distortion).all():
        raise ValueError("distCoeffs must contain 4, 5, 8, 12, or 14 finite coefficients")
    width, height = calibration.image_size or (640, 480)
    probe = np.zeros((int(height), int(width), 3), dtype=np.uint8)
    output = calibration.undistort(probe)
    if output is None or output.shape != probe.shape or not calibration.enabled:
        raise ValueError(calibration.last_error or "OpenCV could not apply this calibration")
    return {
        "valid": True,
        "filename": path.name,
        "size_bytes": size_bytes,
        "quality_status": calibration.quality_status,
        "image_size": list(calibration.image_size) if calibration.image_size else None,
        "calibration_model": calibration.calibration_model,
        "last_error": None,
    }


def safe_upload_name(filename):
    """Normalize a browser filename to a safe flat .npz basename."""
    raw = str(filename or "").replace("\\", "/").split("/")[-1]
    if not raw.lower().endswith(".npz"):
        raise ValueError("only .npz camera calibration files are supported")
    stem = raw[:-4]
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
    if not stem:
        stem = "camera_calibration"
    stem = stem[:80].rstrip("._-") or "camera_calibration"
    return stem + ".npz"
