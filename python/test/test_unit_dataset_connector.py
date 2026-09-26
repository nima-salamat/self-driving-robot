import io
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import numpy as np

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from dataset_connector.server import DatasetConnectorServer


class FakeCamera:
    def __init__(self, config):
        self.camera_initialized = True
        self.measured_frame_rate = 30.0
        self.width = getattr(config, "CAM_WIDTH", 64)
        self.height = getattr(config, "CAM_HEIGHT", 48)
        self.last_capture_valid = True
        self.frame = np.full(
            (self.height, self.width, 3),
            120,
            dtype=np.uint8,
        )

    def set_frame_rate(self, fps):
        self.measured_frame_rate = float(fps)

    def capture_frame(self, with_resize=False):
        return self.frame.copy(), None

    def release(self):
        self.camera_initialized = False


class FakeCalibration:
    def __init__(self, path, enabled=True):
        path = Path(path)
        self.enabled = (
            enabled
            and path.exists()
            and path.stat().st_size > 0
        )
        self.last_error = None if self.enabled else "invalid calibration"
        self.image_size = (64, 48)
        self.calibration_model = "pinhole"
        self.quality_status = "pass"

    def undistort(self, frame):
        return np.clip(
            frame.astype(np.int16) + 10,
            0,
            255,
        ).astype(np.uint8)


class DatasetConnectorTests(unittest.TestCase):
    def make_server(self, tmp):
        config = types.SimpleNamespace(
            CAMERA_MODE="webcam",
            USBCAM_ADDR=0,
            CAM_WIDTH=64,
            CAM_HEIGHT=48,
            CAMERA_FALLBACK_TO_OPENCV=True,
            APPLY_CAMERA_CALIBRATION=False,
        )
        return DatasetConnectorServer(
            config,
            dataset_dir=Path(tmp) / "dataset",
            calibration_file=(
                Path(tmp)
                / "dataset"
                / ".active_camera_calibration.npz"
            ),
            port=5051,
            target_fps=30,
        )

    def test_capture_gallery_delete_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("dataset_connector.server.Camera", FakeCamera):
                server = self.make_server(tmp)
                server.start()
                try:
                    client = server.create_app().test_client()

                    response = client.post("/api/capture")
                    self.assertEqual(response.status_code, 201)
                    self.assertEqual(
                        response.get_json()["filename"],
                        "frame_000001.jpg",
                    )

                    listed = client.get("/api/captures")
                    self.assertEqual(listed.status_code, 200)
                    self.assertEqual(
                        listed.get_json()["captures"][0]["filename"],
                        "frame_000001.jpg",
                    )

                    deleted = client.delete(
                        "/api/captures/frame_000001.jpg"
                    )
                    self.assertEqual(deleted.status_code, 200)

                    client.post("/api/capture")
                    cleared = client.post("/api/clear")
                    self.assertEqual(cleared.status_code, 200)
                    self.assertEqual(cleared.get_json()["removed"], 1)
                    self.assertEqual(server.image_store.count(), 0)
                finally:
                    server.stop()

    def test_empty_dataset_download_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("dataset_connector.server.Camera", FakeCamera):
                server = self.make_server(tmp)
                response = server.create_app().test_client().get(
                    "/api/dataset/download"
                )
                self.assertEqual(response.status_code, 409)

    def test_zip_contains_only_captured_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("dataset_connector.server.Camera", FakeCamera):
                server = self.make_server(tmp)
                server.capture()
                server.capture()
                archive = server.build_zip()
                try:
                    with zipfile.ZipFile(archive) as zf:
                        self.assertEqual(
                            zf.namelist(),
                            [
                                "frame_000001.jpg",
                                "frame_000002.jpg",
                            ],
                        )
                finally:
                    archive.close()

    def test_calibrated_preview_requires_calibration(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("dataset_connector.server.Camera", FakeCamera):
                server = self.make_server(tmp)
                response = server.create_app().test_client().post(
                    "/api/preview",
                    json={"mode": "calibrated"},
                )
                self.assertEqual(response.status_code, 409)

    def test_valid_calibration_can_activate_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("dataset_connector.server.Camera", FakeCamera):
                with patch(
                    "dataset_connector.server.CameraCalibration",
                    FakeCalibration,
                ):
                    server = self.make_server(tmp)
                    server.calibration_file.write_bytes(b"valid")
                    client = server.create_app().test_client()
                    status = client.get("/api/status").get_json()
                    self.assertTrue(
                        status["calibration"]["available"]
                    )

                    response = client.post(
                        "/api/preview",
                        json={"mode": "calibrated"},
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(
                        response.get_json()["preview_mode"],
                        "calibrated",
                    )

    def test_upload_rejects_non_npz(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("dataset_connector.server.Camera", FakeCamera):
                server = self.make_server(tmp)
                response = server.create_app().test_client().post(
                    "/api/calibration/upload",
                    data={
                        "file": (
                            io.BytesIO(b"invalid"),
                            "calibration.txt",
                        )
                    },
                    content_type="multipart/form-data",
                )
                self.assertEqual(response.status_code, 422)

    def test_raw_capture_preview_works_without_calibration(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("dataset_connector.server.Camera", FakeCamera):
                server = self.make_server(tmp)
                server.start()
                try:
                    server.capture()
                    response = server.create_app().test_client().get(
                        "/api/captures/frame_000001.jpg?view=raw"
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(
                        response.mimetype,
                        "image/jpeg",
                    )
                finally:
                    server.stop()


if __name__ == "__main__":
    unittest.main()
