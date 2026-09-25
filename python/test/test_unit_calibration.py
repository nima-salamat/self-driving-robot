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
from vision.camera import Camera


class CalibrationCoreTests(unittest.TestCase):
    def test_blank_frame_does_not_detect_board(self):
        calibrator = CameraCalibrator()
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        result = calibrator.evaluate_frame(frame)

        self.assertFalse(result["valid"])
        self.assertIsNone(result["corners"])

    def test_physical_7x9_board_maps_to_6x8_inner_corners(self):
        calibrator = CameraCalibrator(
            checkerboard=(6, 8),
            square_size=20.0,
        )

        square = 40
        board_cols = 7
        board_rows = 9
        board = np.zeros(
            (
                board_rows * square,
                board_cols * square,
            ),
            dtype=np.uint8,
        )
        for row in range(board_rows):
            for col in range(board_cols):
                if (row + col) % 2 == 0:
                    board[
                        row * square:(row + 1) * square,
                        col * square:(col + 1) * square,
                    ] = 255

        frame = cv2.copyMakeBorder(
            board,
            40,
            40,
            40,
            40,
            cv2.BORDER_CONSTANT,
            value=255,
        )
        frame = cv2.cvtColor(
            frame,
            cv2.COLOR_GRAY2BGR,
        )

        found, corners, _gray, detector = (
            calibrator.detect_corners_detailed(frame)
        )

        self.assertTrue(found)
        self.assertEqual(corners.shape, (48, 1, 2))
        self.assertIn(detector, {"classic", "sb"})

        evaluation = calibrator.evaluate_frame(frame)
        self.assertTrue(evaluation["valid"])
        self.assertEqual(
            evaluation["corners"].shape,
            (48, 1, 2),
        )

    def test_detector_mode_is_respected(self):
        frame = np.zeros((120, 160, 3), dtype=np.uint8)

        with patch(
            "calibration.calibrator.cv2.findChessboardCorners",
            return_value=(False, None),
        ) as classic:
            with patch(
                "calibration.calibrator.cv2.findChessboardCornersSB",
                side_effect=AssertionError("SB should not run in classic mode"),
            ):
                result = CameraCalibrator(
                    detector_mode="classic"
                ).detect_corners_detailed(frame)
                self.assertFalse(result[0])
                self.assertGreaterEqual(classic.call_count, 1)

        sb = getattr(cv2, "findChessboardCornersSB", None)
        if sb is not None:
            with patch(
                "calibration.calibrator.cv2.findChessboardCornersSB",
                return_value=(False, None),
            ) as sb_detector:
                with patch(
                    "calibration.calibrator.cv2.findChessboardCorners",
                    side_effect=AssertionError("classic should not run in SB mode"),
                ):
                    result = CameraCalibrator(
                        detector_mode="sb"
                    ).detect_corners_detailed(frame)
                    self.assertFalse(result[0])
                    self.assertGreaterEqual(
                        sb_detector.call_count,
                        1,
                    )

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

    def test_synthetic_calibration_runs_and_reports_low_error(self):
        calibrator = CameraCalibrator(
            checkerboard=(11, 7),
            square_size=25.0,
            min_valid_images=10,
        )

        camera_matrix = np.array(
            [
                [520.0, 0.0, 320.0],
                [0.0, 515.0, 240.0],
                [0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )
        dist_coeffs = np.array(
            [0.01, -0.005, 0.0005, -0.0002, 0.001],
            dtype=np.float64,
        )

        object_points = []
        image_points = []

        for index in range(12):
            angle_x = np.deg2rad(-12.0 + index * 2.0)
            angle_y = np.deg2rad(-8.0 + (index % 4) * 5.0)
            angle_z = np.deg2rad(-4.0 + (index % 3) * 4.0)

            rotation, _ = cv2.Rodrigues(
                np.array([angle_x, angle_y, angle_z], dtype=np.float64)
            )

            rvec, _ = cv2.Rodrigues(rotation)
            tvec = np.array(
                [
                    [(-30.0 + index * 5.0)],
                    [(index % 3 - 1) * 20.0],
                    [750.0 + (index % 4) * 35.0],
                ],
                dtype=np.float64,
            )

            projected, _ = cv2.projectPoints(
                calibrator.object_template,
                rvec,
                tvec,
                camera_matrix,
                dist_coeffs,
            )

            object_points.append(calibrator.object_template.copy())
            image_points.append(projected.astype(np.float32))

        result = calibrator.calibrate(
            object_points,
            image_points,
            (640, 480),
        )

        self.assertEqual(result["valid_images"], 12)
        self.assertEqual(result["image_size"], (640, 480))
        self.assertLess(result["rms"], 0.05)
        self.assertLess(
            result["mean_reprojection_error"],
            0.05,
        )

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


    def test_detector_mode_fast_path_uses_bounded_calls(self):
        frame = np.zeros(
            (480, 640, 3),
            dtype=np.uint8,
        )
        with patch(
            "calibration.calibrator.cv2.findChessboardCorners",
            return_value=(False, None),
        ) as classic:
            with patch(
                "calibration.calibrator.cv2.findChessboardCornersSB",
                return_value=(False, None),
            ) as sb:
                CameraCalibrator(
                    detector_mode="auto"
                ).detect_corners_detailed(frame)

        # Two orientations in fast mode, with no per-frame 4-flag cascade.
        self.assertLessEqual(classic.call_count, 2)
        self.assertLessEqual(sb.call_count, 2)

    def test_non_finite_quality_setting_is_rejected(self):
        with self.assertRaises(ValueError):
            CameraCalibrator(
                min_sharpness=float("nan")
            )



class CameraChannelOrderTests(unittest.TestCase):
    def test_picamera_rgb888_capture_is_not_channel_swapped(self):
        class FakePicam:
            def capture_array(self):
                return np.array(
                    [[[10, 20, 30]]],
                    dtype=np.uint8,
                )

        camera = Camera.__new__(Camera)
        camera.pi_mode = True
        camera.camera_initialized = True
        camera.picam = FakePicam()
        camera.camera_calibration = types.SimpleNamespace(
            undistort=lambda frame: frame
        )
        camera.config = types.SimpleNamespace(
            runtime_metrics=None,
        )
        camera.consecutive_failures = 0
        camera.last_capture_valid = False
        camera.last_capture_at = None
        camera.requested_frame_rate = None
        camera.measured_frame_rate = None
        camera._capture_timestamps = __import__(
            "collections"
        ).deque(maxlen=120)

        frame, _ = camera.capture_frame(
            with_resize=False
        )

        self.assertTrue(
            np.array_equal(
                frame,
                np.array(
                    [[[10, 20, 30]]],
                    dtype=np.uint8,
                ),
            )
        )



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

    def test_debug_frame_endpoint_returns_image(self):
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
                server._raw_frame = server.camera.frame.copy()
                client = server.create_app().test_client()

                response = client.get(
                    "/api/debug_frame?view=fixed&threshold=180"
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, "image/jpeg")
                self.assertGreater(len(response.data), 100)

                response = client.get(
                    "/api/debug_frame?view=unknown"
                )
                self.assertEqual(response.status_code, 400)

                server.stop()


    def test_board_configuration_preserves_detector_and_quality_settings(self):
        config = types.SimpleNamespace(
            CAMERA_MODE="opencv",
            USBCAM_ADDR=0,
            CAM_WIDTH=640,
            CAM_HEIGHT=480,
            CAMERA_FALLBACK_TO_OPENCV=True,
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch("calibration.stream.Camera"):
                server = CalibrationStreamServer(
                    config,
                    image_dir=Path(tmp) / "images",
                    output_file=Path(tmp) / "calibration.npz",
                )
                server.set_detector_mode("sb")
                server.set_quality_settings(
                    min_coverage=0.12,
                    min_sharpness=33,
                    min_edge_margin=0.04,
                    duplicate_distance=0.11,
                )
                server.set_board_configuration(
                    board_cols=8,
                    board_rows=10,
                    square_size=25,
                )
                self.assertEqual(
                    server.calibrator.detector_mode,
                    "sb",
                )
                self.assertEqual(
                    server.calibrator.min_coverage,
                    0.12,
                )
                self.assertEqual(
                    server.calibrator.min_sharpness,
                    33.0,
                )
                self.assertEqual(
                    server.calibrator.min_edge_margin,
                    0.04,
                )
                self.assertEqual(
                    server.calibrator.duplicate_distance,
                    0.11,
                )
                server.stop()

    def test_persisted_capture_features_are_restored(self):
        config = types.SimpleNamespace(
            CAMERA_MODE="opencv",
            USBCAM_ADDR=0,
            CAM_WIDTH=640,
            CAM_HEIGHT=480,
            CAMERA_FALLBACK_TO_OPENCV=True,
        )
        with tempfile.TemporaryDirectory() as tmp:
            image_dir = Path(tmp) / "images"
            store_module = __import__(
                "calibration.capture",
                fromlist=["CalibrationImageStore"],
            )
            store = store_module.CalibrationImageStore(
                image_dir
            )
            image = np.zeros(
                (48, 64, 3),
                dtype=np.uint8,
            )
            feature = np.asarray(
                [0.2, 0.7, 0.4, 0.5, 0.2, 0.1, -0.1],
                dtype=np.float32,
            )
            path = store.save(
                image,
                {
                    "format_version": 1,
                    "image_size": [64, 48],
                    "checkerboard": [11, 7],
                    "feature": feature.tolist(),
                    "corners": np.zeros(
                        (77, 2),
                        dtype=float,
                    ).tolist(),
                    "sharpness": 100.0,
                    "detector": "classic",
                },
            )
            self.assertTrue(store.metadata_path(path).exists())

            with patch("calibration.stream.Camera"):
                server = CalibrationStreamServer(
                    config,
                    image_dir=image_dir,
                    output_file=Path(tmp) / "calibration.npz",
                )
                self.assertEqual(
                    len(server._accepted_features),
                    1,
                )
                self.assertTrue(
                    np.allclose(
                        server._accepted_features[0],
                        feature,
                    )
                )
                server.stop()



if __name__ == "__main__":
    unittest.main()
