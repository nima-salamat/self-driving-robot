import sys
import unittest
from pathlib import Path

import numpy as np

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from vision.frame_health import is_camera_frame_obscured


class CameraFrameHealthTests(unittest.TestCase):
    def test_fully_black_frame_is_treated_as_occluded(self):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        self.assertTrue(is_camera_frame_obscured(frame))

    def test_sensor_noise_on_a_covered_lens_is_still_occluded(self):
        rng = np.random.default_rng(17)
        frame = rng.integers(0, 7, size=(240, 320, 3), dtype=np.uint8)
        self.assertTrue(is_camera_frame_obscured(frame))

    def test_visible_image_is_not_treated_as_occluded(self):
        frame = np.full((240, 320, 3), 32, dtype=np.uint8)
        self.assertFalse(is_camera_frame_obscured(frame))

    def test_dark_scene_with_bright_structure_is_not_treated_as_occluded(self):
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        frame[70:170, 100:220] = 80
        self.assertFalse(is_camera_frame_obscured(frame))

    def test_missing_or_invalid_frames_are_left_to_camera_validity_checks(self):
        self.assertFalse(is_camera_frame_obscured(None))
        self.assertFalse(is_camera_frame_obscured(np.empty((0, 0, 3), dtype=np.uint8)))
        self.assertFalse(is_camera_frame_obscured(np.zeros((8,), dtype=np.uint8)))


if __name__ == "__main__":
    unittest.main()
