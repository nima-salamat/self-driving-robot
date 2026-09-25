import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from calibration.calibrator import CameraCalibration, CameraCalibrator
from calibration.config import create_camera_config
from calibration.stream import CalibrationStreamServer


class CalibrationCoreTests(unittest.TestCase):
    def test_blank_frame_does_not_detect_board(self):
        calibrator = CameraCalibrator()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        result = calibrator.evaluate_frame(frame)

        self.assertFalse(result["valid"])
        self.assertIsNone(result["corners"])

    def test_create_camera_config_disables_existing_calibration(self):
        config = create_camera_config(
            camera_mode="webcam",
            camera_index=2,
            width=800,
            height=600,
            target_fps=24,
        )

        self.assertEqual(config.CAMERA_MODE, "webcam")
        self.assertEqual(config.USBCAM_ADDR, 2)
        self.assertEqual(config.CAM_WIDTH, 800)
        self.assertEqual(config.CAM_HEIGHT, 600)
        self.assertEqual(config.CALIBRATION_TARGET_FPS, 24)
        self.assertFalse(config.APPLY_CAMERA_CALIBRATION)

    def test_calibration_save_and_resolution_aware_load(self):
        calibrator = CameraCalibrator()
        result = {
            "image_size": (640, 480),
            "checkerboard": (11, 7),
            "square_size": 1.0,
            "rms": 0.2,
            "mean_reprojection_error": 0.18,
            "valid_images": 10,
            "valid_paths": [],
            "rejected_paths": [],
            "camera_matrix": np.array(
                [
                    [500.0, 0.0, 320.0],
                    [0.0, 500.0, 240.0],
                    [0.0, 0.0, 1.0],
                ],
                dtype=np.float64,
            ),
            "dist_coeffs": np.zeros((5, 1), dtype=np.float64),
        }

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "calibration.npz"
            calibrator.save(result, path)

            loaded = CameraCalibration(path)
            self.assertTrue(loaded.enabled)

            matrix = loaded._scaled_camera_matrix(1280, 960)
            self.assertAlmostEqual(matrix[0, 0], 1000.0)
            self.assertAlmostEqual(matrix[1, 1], 1000.0)
            self.assertAlmostEqual(matrix[0, 2], 640.0)
            self.assertAlmostEqual(matrix[1, 2], 480.0)


class FakeCamera:
    def __init__(self, config):
        self.config = config
        self.last_capture_valid = True
        self.frame = np.zeros((120, 160, 3), dtype=np.uint8)
        self.frame[70:110, 50:110] = 255
        self.rate = 30.0
        self.released = False

    def set_frame_rate(self, fps):
        self.rate = float(fps)

    def capture_frame(self, with_resize=False):
        return self.frame.copy(), self.frame.copy()

    def release(self):
        self.released = True


class CalibrationStreamTests(unittest.TestCase):
    def test_status_and_fps_setting_api(self):
        config = types.SimpleNamespace(
            CAMERA_MODE="webcam",
            CAM_WIDTH=160,
            CAM_HEIGHT=120,
            resize_width=160,
            resize_height=120,
            CAMERA_FALLBACK_TO_OPENCV=False,
            APPLY_CAMERA_CALIBRATION=False,
            CALIBRATION_TARGET_FPS=30.0,
        )

        with tempfile.TemporaryDirectory() as tmp:
            with patch("calibration.stream.Camera", FakeCamera):
                server = CalibrationStreamServer(
                    config,
                    image_dir=Path(tmp) / "images",
                    output_file=Path(tmp) / "calibration.npz",
                    host="127.0.0.1",
                    port=0,
                    target_fps=30,
                )

                client = server.create_app().test_client()

                response = client.get("/api/status")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()["requested_fps"], 30.0)

                response = client.post(
                    "/api/settings",
                    json={"fps": 24},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.get_json()["requested_fps"],
                    24.0,
                )
                self.assertEqual(server.camera.rate, 24.0)

                server.stop()


if __name__ == "__main__":
    unittest.main()
