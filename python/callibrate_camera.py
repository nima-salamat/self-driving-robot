"""
Backward-compatible wrapper.

Use:
    python -m calibration.calibrate
"""

from calibration.calibrate import main


if __name__ == "__main__":
    raise SystemExit(main())
