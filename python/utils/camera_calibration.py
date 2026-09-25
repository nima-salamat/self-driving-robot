"""
Compatibility import for older callers.

CameraCalibration now lives in the dedicated calibration package.
"""

from calibration.calibrator import CameraCalibration

__all__ = ["CameraCalibration"]
