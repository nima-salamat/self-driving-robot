import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch
from pathlib import Path

import cv2
import numpy as np

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from calibration.calibrator import CameraCalibrator, CameraCalibration
from calibration.stream import CalibrationStreamServer
from stream import WebStreamer, publish_debug_frame
from stream.capabilities import mode_capabilities
from train_sign_detector import classification
from train_sign_detector.dataset_collector import save_sample
from train_sign_detector.labels import SIGN_LABELS


class SecondPassStreamTests(unittest.TestCase):
    def config(self, mode="race", ml=True):
        return types.SimpleNamespace(
            MODE=mode,
            STREAM=True,
            STREAM_ALLOW_CONTROL=True,
            RECORD_VIDEO=False,
            WITH_SIGN=True,
            WITH_APRILTAG=False,
            USE_SIGN=(mode == "race"),
            USE_ML_LANE_DETECTOR=(mode == "race" and ml),
            CITY_LANE_DETECTOR="blsf-beta" if mode == "city" else "default",
            USE_BEV=True,
            DETECT_OBJECT=False,
            debug_frames_list=[],
            stream_frame_seq=0,
            OUTPUT_DIR="output",
            RL_TOP_ROI=0.2, RL_BOTTOM_ROI=0.8,
            RL_LEFT_ROI=0.1, RL_RIGHT_ROI=0.9,
            LL_TOP_ROI=0.2, LL_BOTTOM_ROI=0.8,
            LL_LEFT_ROI=0.1, LL_RIGHT_ROI=0.9,
            CW_TOP_ROI=0.2, CW_BOTTOM_ROI=0.8,
            CW_LEFT_ROI=0.1, CW_RIGHT_ROI=0.9,
            ST_TOP_ROI=0.2, ST_BOTTOM_ROI=0.8,
            ST_LEFT_ROI=0.1, ST_RIGHT_ROI=0.9,
            OBJ_TOP_ROI=0.2, OBJ_BOTTOM_ROI=0.8,
            OBJ_LEFT_ROI=0.1, OBJ_RIGHT_ROI=0.9,
            TAKE_PICTURE=False,
        )

    def test_capabilities_differ_by_mode(self):
        city = self.config("city", ml=False)
        race_ml = self.config("race", ml=True)
        race_classical = self.config("race", ml=False)
        self.assertTrue(mode_capabilities(city)["supports_crosswalk"])
        self.assertFalse(mode_capabilities(race_ml)["supports_crosswalk"])
        self.assertTrue(mode_capabilities(race_classical)["supports_bev"])
        self.assertFalse(mode_capabilities(race_ml)["supports_bev"])
        self.assertFalse(mode_capabilities(race_ml)["supports_lane_roi"])
        self.assertTrue(mode_capabilities(city)["supports_lane_roi"])

    def test_stream_buffer_is_bounded_and_sequenced(self):
        config = self.config()
        for i in range(100):
            publish_debug_frame(
                config,
                np.full((8, 8, 3), i, dtype=np.uint8),
            )
        self.assertEqual(len(config.debug_frames_list), 1)
        self.assertEqual(config.stream_frame_seq, 100)

    def test_race_rejects_unsupported_crosswalk_control(self):
        config = self.config("race", ml=False)
        response = WebStreamer(config).app.test_client().post(
            "/set_advanced",
            json={"CW_TRAPEZOID_MODE": True},
        )
        self.assertEqual(response.status_code, 409)

    def test_race_ml_rejects_bev_and_lane_roi_controls(self):
        config = self.config("race", ml=True)
        client = WebStreamer(config).app.test_client()
        self.assertEqual(
            client.post("/set_advanced", json={"USE_BEV": False}).status_code,
            409,
        )
        self.assertEqual(
            client.post(
                "/set_advanced",
                json={"LANE_ROI_MODE": "rectangle"},
            ).status_code,
            409,
        )

    def test_boolean_payload_is_strict(self):
        config = self.config()
        response = WebStreamer(config).app.test_client().post(
            "/set_advanced",
            json={"WITH_SIGN": "false"},
        )
        self.assertEqual(response.status_code, 400)

    def test_invalid_base_roi_payload_is_rejected(self):
        config = self.config()
        response = WebStreamer(config).app.test_client().post(
            "/update_conf",
            json={"RL_TOP_ROI": "not-a-number"},
        )
        self.assertEqual(response.status_code, 400)

    def test_marker_control_updates_legacy_alias(self):
        config = self.config()
        config.apply_marker_mode = lambda mode: (
            setattr(config, "WITH_SIGN", mode == "sign"),
            setattr(config, "WITH_APRILTAG", mode == "apriltag"),
            setattr(config, "USE_SIGN", mode == "sign"),
        )
        response = WebStreamer(config).app.test_client().post(
            "/set_advanced",
            json={"WITH_SIGN": False, "WITH_APRILTAG": True},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(config.WITH_SIGN)
        self.assertTrue(config.WITH_APRILTAG)
        self.assertFalse(config.USE_SIGN)


class CalibrationStreamBoardSettingsTests(unittest.TestCase):
    def test_status_stays_responsive_during_detector_work(self):
        import threading

        with tempfile.TemporaryDirectory() as tmp:
            config = types.SimpleNamespace(
                CAMERA_MODE="opencv",
                USBCAM_ADDR=0,
                CAM_WIDTH=160,
                CAM_HEIGHT=120,
                CAMERA_FALLBACK_TO_OPENCV=True,
            )
            with patch("calibration.stream.Camera"):
                server = CalibrationStreamServer(
                    camera_config=config,
                    image_dir=Path(tmp) / "images",
                    output_file=Path(tmp) / "calibration.npz",
                )
                started = threading.Event()
                release = threading.Event()

                def slow_evaluate(*_args, **_kwargs):
                    started.set()
                    release.wait(timeout=1.0)
                    return {
                        "valid": False,
                        "detected": False,
                        "quality_valid": False,
                        "corners": None,
                        "coverage": 0.0,
                        "center": None,
                        "sharpness": 0.0,
                        "edge_margin": 0.0,
                        "feature": None,
                        "detector": "test",
                        "detection_view": "none",
                        "detection_scale": 1.0,
                        "quality_reason": "board not detected",
                    }

                server.calibrator.evaluate_frame = slow_evaluate
                frame = np.zeros((120, 160, 3), dtype=np.uint8)
                server._publish(frame, frame)

                worker = threading.Thread(
                    target=server._detection_loop,
                    daemon=True,
                )
                worker.start()

                self.assertTrue(started.wait(timeout=1.0))
                begin = time.monotonic()
                server.status()
                elapsed = time.monotonic() - begin

                release.set()
                server._stop_event.set()
                server._detection_wakeup.set()
                worker.join(timeout=1.0)

                self.assertLess(
                    elapsed,
                    0.25,
                    f"status blocked behind detector for {elapsed:.3f}s",
                )

    def test_web_board_configuration_uses_square_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = types.SimpleNamespace(
                CAMERA_MODE="opencv",
                USBCAM_ADDR=0,
                CAM_WIDTH=640,
                CAM_HEIGHT=480,
                CAMERA_FALLBACK_TO_OPENCV=True,
            )
            with patch("calibration.stream.Camera"):
                server = CalibrationStreamServer(
                    camera_config=config,
                    image_dir=Path(tmp) / "images",
                    output_file=Path(tmp) / "calibration.npz",
                )
                response = server.create_app().test_client().post(
                    "/api/settings",
                    json={
                        "board_cols": 7,
                        "board_rows": 9,
                        "square_size": 20,
                        "min_valid_images": 12,
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(server.board_squares, (7, 9))
                self.assertEqual(server.calibrator.checkerboard, (6, 8))
                self.assertEqual(server.calibrator.square_size, 20.0)
                self.assertEqual(server.min_valid_images, 12)
                self.assertEqual(
                    response.get_json()["checkerboard_inner_corners"],
                    [6, 8],
                )


    def test_web_settings_response_preserves_board_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = types.SimpleNamespace(
                CAMERA_MODE="opencv",
                USBCAM_ADDR=0,
                CAM_WIDTH=640,
                CAM_HEIGHT=480,
                CAMERA_FALLBACK_TO_OPENCV=True,
            )
            with patch("calibration.stream.Camera"):
                server = CalibrationStreamServer(
                    camera_config=config,
                    image_dir=Path(tmp) / "images",
                    output_file=Path(tmp) / "calibration.npz",
                )
                client = server.create_app().test_client()
                response = client.post(
                    "/api/settings",
                    json={
                        "board_cols": 7,
                        "board_rows": 9,
                        "square_size": 20,
                        "min_valid_images": 12,
                    },
                )
                payload = response.get_json()
                self.assertTrue(payload["success"])
                self.assertEqual(payload["board_squares"], [7, 9])
                self.assertEqual(payload["checkerboard_inner_corners"], [6, 8])
                self.assertEqual(payload["square_size"], 20.0)
                self.assertEqual(payload["min_valid_images"], 12)

    def test_web_detection_and_auto_capture_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = types.SimpleNamespace(
                CAMERA_MODE="opencv",
                USBCAM_ADDR=0,
                CAM_WIDTH=640,
                CAM_HEIGHT=480,
                CAMERA_FALLBACK_TO_OPENCV=True,
            )
            with patch("calibration.stream.Camera"):
                server = CalibrationStreamServer(
                    camera_config=config,
                    image_dir=Path(tmp) / "images",
                    output_file=Path(tmp) / "calibration.npz",
                )
                response = server.create_app().test_client().post(
                    "/api/settings",
                    json={
                        "detector_mode": "sb",
                        "auto_capture_enabled": True,
                        "auto_capture_interval": 2,
                        "min_coverage": 0.01,
                        "min_sharpness": 10,
                        "min_edge_margin": 0.02,
                        "duplicate_distance": 0.1,
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(server.calibrator.detector_mode, "sb")
                self.assertTrue(server.auto_capture_enabled)
                self.assertEqual(server.auto_capture_interval, 2.0)
                self.assertEqual(server.calibrator.min_sharpness, 10.0)

    def test_auto_capture_saves_accepted_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = types.SimpleNamespace(
                CAMERA_MODE="opencv",
                USBCAM_ADDR=0,
                CAM_WIDTH=640,
                CAM_HEIGHT=480,
                CAMERA_FALLBACK_TO_OPENCV=True,
            )
            with patch("calibration.stream.Camera"):
                server = CalibrationStreamServer(
                    camera_config=config,
                    image_dir=Path(tmp) / "images",
                    output_file=Path(tmp) / "calibration.npz",
                )
                server.auto_capture_enabled = True
                evaluation = {
                    "quality_valid": True,
                    "quality_reason": None,
                    "feature": np.zeros(7, dtype=np.float32),
                    "corners": np.zeros((77, 1, 2), dtype=np.float32),
                    "coverage": 0.1,
                    "center": [0.5, 0.5],
                    "sharpness": 100.0,
                    "edge_margin": 0.1,
                    "detector": "test",
                    "detection_view": "detector",
                    "detection_scale": 1.0,
                }
                server._maybe_auto_capture(
                    np.zeros((24, 32, 3), dtype=np.uint8),
                    evaluation,
                )
                self.assertEqual(server.image_store.count(), 1)
                self.assertEqual(server.auto_captured_images, 1)

    def test_captures_api_lists_saved_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = types.SimpleNamespace(
                CAMERA_MODE="opencv",
                USBCAM_ADDR=0,
                CAM_WIDTH=640,
                CAM_HEIGHT=480,
                CAMERA_FALLBACK_TO_OPENCV=True,
            )
            with patch("calibration.stream.Camera"):
                server = CalibrationStreamServer(
                    camera_config=config,
                    image_dir=Path(tmp) / "images",
                    output_file=Path(tmp) / "calibration.npz",
                )
                path = server.image_store.next_path()
                cv2.imwrite(str(path), np.zeros((10, 10, 3), dtype=np.uint8))
                payload = server.create_app().test_client().get(
                    "/api/captures"
                ).get_json()
                self.assertEqual(len(payload["captures"]), 1)
                self.assertEqual(
                    payload["captures"][0]["filename"],
                    path.name,
                )

    def test_calibration_preview_accepts_valid_saved_model(self):
        config = types.SimpleNamespace(
            CAMERA_MODE="webcam",
            CAM_WIDTH=160,
            CAM_HEIGHT=120,
            CAMERA_FALLBACK_TO_OPENCV=False,
            APPLY_CAMERA_CALIBRATION=False,
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "calibration.npz"
            CameraCalibrator.save(
                {
                    "image_size": (160, 120),
                    "checkerboard": (7, 9),
                    "square_size": 20.0,
                    "rms": 0.2,
                    "mean_reprojection_error": 0.2,
                    "max_reprojection_error": 0.3,
                    "valid_images": 10,
                    "valid_paths": [],
                    "rejected_paths": [],
                    "quality_status": "pass",
                    "acceptable_for_runtime": True,
                    "camera_matrix": np.array(
                        [[100.0, 0.0, 80.0],
                         [0.0, 100.0, 60.0],
                         [0.0, 0.0, 1.0]],
                        dtype=np.float64,
                    ),
                    "dist_coeffs": np.zeros((5, 1), dtype=np.float64),
                },
                output,
            )

            with patch("calibration.stream.Camera"):
                server = CalibrationStreamServer(
                    camera_config=config,
                    image_dir=Path(tmp) / "images",
                    output_file=output,
                )
                self.assertEqual(
                    server._calibration_state,
                    "not calibrated",
                )
                server.set_calibration_preview(True)
                self.assertTrue(
                    server.calibration_preview_enabled,
                )
                self.assertIsNotNone(server._calibration_preview)

                server.set_calibration_preview(False)
                self.assertFalse(
                    server.calibration_preview_enabled,
                )
                self.assertIsNone(server._calibration_preview)

    def test_calibration_preview_toggle_applies_to_live_frame_only(self):
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

                raw = np.zeros((120, 160, 3), dtype=np.uint8)
                calibrated = np.full(
                    (120, 160, 3),
                    77,
                    dtype=np.uint8,
                )
                preview = types.SimpleNamespace(
                    enabled=True,
                    undistort=lambda frame: calibrated,
                    undistort_points=lambda points, image_size: points,
                )
                server._calibration_preview = preview

                server.calibration_preview_enabled = False
                np.testing.assert_array_equal(
                    server._display_frame(raw),
                    raw,
                )

                server.calibration_preview_enabled = True
                np.testing.assert_array_equal(
                    server._display_frame(raw),
                    calibrated,
                )

                server.calibration_preview_enabled = False
                np.testing.assert_array_equal(
                    server._display_frame(raw),
                    raw,
                )

                server.stop()

    def test_calibration_preview_requires_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = types.SimpleNamespace(
                CAMERA_MODE="opencv",
                USBCAM_ADDR=0,
                CAM_WIDTH=640,
                CAM_HEIGHT=480,
                CAMERA_FALLBACK_TO_OPENCV=True,
            )
            with patch("calibration.stream.Camera"):
                server = CalibrationStreamServer(
                    camera_config=config,
                    image_dir=Path(tmp) / "images",
                    output_file=Path(tmp) / "calibration.npz",
                )
                response = server.create_app().test_client().post(
                    "/api/preview",
                    json={"enabled": True},
                )
                self.assertEqual(response.status_code, 409)
                self.assertFalse(server.calibration_preview_enabled)

    def test_web_rejects_board_changes_when_captures_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = types.SimpleNamespace(
                CAMERA_MODE="opencv",
                USBCAM_ADDR=0,
                CAM_WIDTH=640,
                CAM_HEIGHT=480,
                CAMERA_FALLBACK_TO_OPENCV=True,
            )
            with patch("calibration.stream.Camera"):
                server = CalibrationStreamServer(
                    camera_config=config,
                    image_dir=Path(tmp) / "images",
                    output_file=Path(tmp) / "calibration.npz",
                )
                server.image_store.next_path().write_bytes(b"placeholder")
                response = server.create_app().test_client().post(
                    "/api/settings",
                    json={
                        "board_cols": 7,
                        "board_rows": 9,
                        "square_size": 20,
                    },
                )
                self.assertEqual(response.status_code, 409)
                payload = response.get_json()
                self.assertEqual(payload["code"], "CAPTURES_EXIST")
                self.assertIn(
                    "Clear captured calibration images",
                    payload["message"],
                )


class CalibrationDetectionTests(unittest.TestCase):
    def test_detector_falls_back_to_sb_when_classic_fails(self):
        calibrator = CameraCalibrator(checkerboard=(6, 8))
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

        with patch("calibration.calibrator.cv2.findChessboardCorners") as classic:
            classic.return_value = (False, None)
            found, corners, gray, detector = calibrator.detect_corners_detailed(frame)

        self.assertFalse(found)
        self.assertIsNone(corners)
        self.assertEqual(gray.ndim, 2)
        self.assertEqual(detector, "none")

    def test_detection_canonicalizes_transposed_pattern(self):
        calibrator = CameraCalibrator(checkerboard=(6, 8))
        detected = np.arange(
            48 * 2,
            dtype=np.float32,
        ).reshape(48, 1, 2)

        canonical = calibrator._canonicalize_corners(
            detected,
            (8, 6),
            (0, 0),
        )

        expected = (
            detected
            .reshape(6, 8, 2)
            .transpose(1, 0, 2)
            .reshape(48, 1, 2)
        )
        np.testing.assert_array_equal(canonical, expected)

    def test_detection_removes_padding_offset(self):
        calibrator = CameraCalibrator(checkerboard=(6, 8))
        corners = np.zeros(
            (48, 1, 2),
            dtype=np.float32,
        )
        corners[:, 0, 0] = np.arange(48, dtype=np.float32) + 24
        corners[:, 0, 1] = np.arange(48, dtype=np.float32) + 24

        canonical = calibrator._canonicalize_corners(
            corners,
            (6, 8),
            (24, 24),
        )

        np.testing.assert_array_equal(
            canonical,
            corners - np.array(
                [[[24.0, 24.0]]],
                dtype=np.float32,
            ),
        )

    def test_synthetic_board_is_detectable(self):
        calibrator = CameraCalibrator(checkerboard=(6, 8))
        square = 40
        margin = square
        image = np.full(
            (9 * square + 2 * margin, 7 * square + 2 * margin),
            255,
            dtype=np.uint8,
        )
        for row in range(9):
            for col in range(7):
                if (row + col) % 2 == 0:
                    image[
                        margin + row * square:margin + (row + 1) * square,
                        margin + col * square:margin + (col + 1) * square,
                    ] = 0
        frame = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)

        found, corners, _, detector = calibrator.detect_corners_detailed(frame)
        self.assertTrue(found)
        self.assertEqual(corners.shape[0], 48)
        self.assertIn(detector, {"classic", "sb"})


class CalibrationQualityTests(unittest.TestCase):
    def test_blank_frame_is_rejected_with_reason(self):
        calibrator = CameraCalibrator()
        result = calibrator.evaluate_frame(
            np.zeros((480, 640, 3), dtype=np.uint8)
        )
        self.assertFalse(result["quality_valid"])
        self.assertEqual(result["quality_reason"], "board not detected")

    def test_camera_calibration_rejects_aspect_ratio_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "calibration.npz"
            CameraCalibrator.save(
                {
                    "image_size": (640, 480),
                    "checkerboard": (11, 7),
                    "square_size": 1.0,
                    "rms": 0.2,
                    "mean_reprojection_error": 0.2,
                    "valid_images": 10,
                    "valid_paths": [],
                    "rejected_paths": [],
                    "quality_status": "pass",
                    "acceptable_for_runtime": True,
                    "camera_matrix": np.array(
                        [[500.0, 0, 320], [0, 500.0, 240], [0, 0, 1]]
                    ),
                    "dist_coeffs": np.zeros((5, 1)),
                },
                path,
            )
            loader = CameraCalibration(path, enabled=True)
            with self.assertRaises(ValueError):
                loader._scaled_camera_matrix(800, 480)

    def test_save_and_load_preserves_quality_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "calibration.npz"
            result = {
                "image_size": (640, 480),
                "checkerboard": (11, 7),
                "square_size": 1.0,
                "rms": 0.2,
                "mean_reprojection_error": 0.2,
                "median_reprojection_error": 0.15,
                "max_reprojection_error": 0.4,
                "per_view_errors": [0.1, 0.2, 0.4],
                "valid_images": 10,
                "valid_paths": [],
                "rejected_paths": [],
                "quality_status": "pass",
                "acceptable_for_runtime": True,
                "camera_matrix": np.array(
                    [[500.0, 0, 320], [0, 500.0, 240], [0, 0, 1]]
                ),
                "dist_coeffs": np.zeros((5, 1)),
            }
            CameraCalibrator.save(result, path)
            loader = CameraCalibration(path, enabled=True)
            self.assertTrue(loader.enabled)
            self.assertEqual(loader.quality_status, "pass")
            self.assertEqual(loader.calibration_model, "pinhole")

    def test_runtime_disables_quality_failed_calibration(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "calibration.npz"
            result = {
                "image_size": (640, 480),
                "checkerboard": (11, 7),
                "square_size": 1.0,
                "rms": 4.0,
                "mean_reprojection_error": 4.0,
                "valid_images": 10,
                "valid_paths": [],
                "rejected_paths": [],
                "quality_status": "fail",
                "acceptable_for_runtime": False,
                "camera_matrix": np.array(
                    [[500.0, 0, 320], [0, 500.0, 240], [0, 0, 1]]
                ),
                "dist_coeffs": np.zeros((5, 1)),
            }
            CameraCalibrator.save(result, path)
            loader = CameraCalibration(path, enabled=True)
            self.assertFalse(loader.enabled)
            self.assertIn("quality gate", loader.last_error)


class DatasetContractTests(unittest.TestCase):
    def test_all_classes_have_one_authoritative_name(self):
        self.assertEqual(set(SIGN_LABELS), set(range(6)))
        self.assertEqual(classification.SIGN_LABELS, SIGN_LABELS)
        self.assertEqual(
            list(SIGN_LABELS.values()),
            [
                "ERROR",
                "STOP",
                "TURN RIGHT",
                "TURN LEFT",
                "STRAIGHT",
                "PARK",
            ],
        )

    def test_collected_dataset_is_distinct_and_module_relative(self):
        from train_sign_detector import dataset_collector
        self.assertTrue(
            str(dataset_collector.dataset_path()).endswith(
                "train_sign_detector/collected_dataset"
            )
        )

    def test_collected_sample_is_consumable_by_loader(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            frame = np.full((48, 64, 3), 127, dtype=np.uint8)
            path = save_sample(frame, 2, base)
            features, labels = classification.load_dataset(base)
            self.assertEqual(path.parent.name, "2")
            self.assertEqual(labels.tolist(), [2])
            self.assertEqual(features.shape[0], 1)

    def test_save_sample_rejects_invalid_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                save_sample(None, 2, Path(tmp))


if __name__ == "__main__":
    unittest.main()
