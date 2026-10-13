import sys
import unittest
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from vision.camera import Camera


class PicameraFrameRateTests(unittest.TestCase):
    def make_camera(self):
        camera = Camera.__new__(Camera)
        camera.pi_mode = True
        camera.config = SimpleNamespace(CAMERA_FPS=60.0)
        camera.picam = Mock()
        # Picamera2 expresses FrameDurationLimits in microseconds:
        # 16972 us -> about 58.92 FPS maximum; 5000000 us -> 0.20 FPS minimum.
        camera.picam.camera_controls = {
            "FrameDurationLimits": (16972, 5000000),
        }
        camera.requested_frame_rate = None
        camera.measured_frame_rate = 12.0
        camera._capture_timestamps = deque([1.0, 1.1], maxlen=120)
        return camera

    def test_request_above_camera_mode_max_is_clamped_and_logged(self):
        camera = self.make_camera()
        max_fps = 1_000_000.0 / 16972

        with patch("vision.camera.logger.warning") as warning:
            camera.set_frame_rate(60.0)

        warning.assert_called_once_with(
            "Requested Picamera2 FPS %.2f exceeds the configured "
            "camera-mode maximum of %.2f FPS; clamping to %.2f FPS.",
            60.0,
            max_fps,
            max_fps,
        )
        camera.picam.set_controls.assert_called_once_with({
            "FrameDurationLimits": (16972, 16972),
        })
        self.assertAlmostEqual(camera.requested_frame_rate, max_fps)
        self.assertAlmostEqual(camera.config.CAMERA_FPS, max_fps)
        self.assertIsNone(camera.measured_frame_rate)
        self.assertEqual(list(camera._capture_timestamps), [])

    def test_supported_fps_is_applied_without_clamping_warning(self):
        camera = self.make_camera()

        with patch("vision.camera.logger.warning") as warning:
            camera.set_frame_rate(30.0)

        warning.assert_not_called()
        camera.picam.set_controls.assert_called_once_with({
            "FrameDurationLimits": (33333, 33333),
        })
        self.assertEqual(camera.requested_frame_rate, 30.0)

    def test_request_below_camera_mode_min_still_raises_clear_error(self):
        camera = self.make_camera()

        with self.assertRaisesRegex(ValueError, "below the configured camera-mode minimum"):
            camera.set_frame_rate(0.1)

        camera.picam.set_controls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
