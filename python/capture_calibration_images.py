"""
Backward-compatible wrapper for the web-based calibration interface.

The old local OpenCV window has been replaced by the Flask calibration stream.
Use:
    python -m calibration.stream
"""

from calibration.stream import main


if __name__ == "__main__":
    raise SystemExit(main())
