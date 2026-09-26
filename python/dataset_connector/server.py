from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from tempfile import SpooledTemporaryFile

import cv2
from flask import Flask, Response, jsonify, render_template_string, request, send_file
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename

from calibration.calibrator import CameraCalibration
from calibration.config import create_camera_config
from vision.camera import Camera

from .storage import DatasetImageStore
from .template import DATASET_CONNECTOR_HTML

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATASET_DIR = BASE_DIR / "assets" / "dataset_connector"
DEFAULT_CALIBRATION_FILE = DEFAULT_DATASET_DIR / ".active_camera_calibration.npz"


class DatasetConnectorServer:
    """Web dataset capture workspace backed by the project's Camera abstraction."""

    def __init__(
        self,
        camera_config,
        dataset_dir=DEFAULT_DATASET_DIR,
        calibration_file=DEFAULT_CALIBRATION_FILE,
        host="127.0.0.1",
        port=5051,
        target_fps=30.0,
        max_upload_bytes=16 * 1024 * 1024,
    ):
        self.config = camera_config
        setattr(self.config, "APPLY_CAMERA_CALIBRATION", False)

        self.dataset_dir = Path(dataset_dir)
        self.image_store = DatasetImageStore(self.dataset_dir)
        self.calibration_file = Path(calibration_file)
        self.calibration_file.parent.mkdir(parents=True, exist_ok=True)

        self.host = str(host)
        self.port = int(port)
        self.requested_fps = float(target_fps)
        self.max_upload_bytes = int(max_upload_bytes)

        self._frame_condition = threading.Condition()
        self._raw_frame = None
        self._display_frame = None
        self._frame_seq = 0
        self._stop_event = threading.Event()
        self._camera_thread = None
        self._camera_lock = threading.Lock()
        self._operation_lock = threading.RLock()
        self._calibration_lock = threading.RLock()

        self.preview_mode = "raw"
        self._calibration = None
        self._calibration_error = None
        self._last_camera_error = None

        self._load_existing_calibration()

        self.camera = Camera(config=self.config)
        self.camera.set_frame_rate(self.requested_fps)

    @classmethod
    def from_options(
        cls,
        camera_mode=None,
        camera_index=None,
        width=None,
        height=None,
        fps=30.0,
        **kwargs,
    ):
        config = create_camera_config(
            camera_mode=camera_mode,
            camera_index=camera_index,
            width=width,
            height=height,
            target_fps=fps,
        )
        config.APPLY_CAMERA_CALIBRATION = False
        return cls(config, target_fps=fps, **kwargs)

    def _load_existing_calibration(self):
        if not self.calibration_file.exists():
            return

        calibration = CameraCalibration(self.calibration_file, enabled=True)
        if calibration.enabled:
            with self._calibration_lock:
                self._calibration = calibration
                self._calibration_error = None
        else:
            self._calibration_error = (
                calibration.last_error or "Calibration file is not usable."
            )
            logger.warning(
                "Ignoring invalid persisted dataset calibration: %s",
                self._calibration_error,
            )

    def _calibration_status(self):
        with self._calibration_lock:
            calibration = self._calibration
            error = self._calibration_error

        if calibration is None:
            return {
                "available": False,
                "active": False,
                "filename": None,
                "image_size": None,
                "calibration_model": None,
                "quality_status": None,
                "error": error,
            }

        available = bool(calibration.enabled)
        return {
            "available": available,
            "active": available and self.preview_mode == "calibrated",
            "filename": "camera_calibration.npz" if available else None,
            "image_size": (
                list(calibration.image_size)
                if calibration.image_size
                else None
            ) if available else None,
            "calibration_model": calibration.calibration_model if available else None,
            "quality_status": calibration.quality_status if available else None,
            "error": calibration.last_error or error,
        }

    def _apply_preview(self, frame):
        if self.preview_mode != "calibrated":
            return frame

        with self._calibration_lock:
            calibration = self._calibration

        if calibration is None or not calibration.enabled:
            return frame

        try:
            return calibration.undistort(frame)
        except Exception as exc:
            with self._calibration_lock:
                self._calibration_error = str(exc)
            logger.exception("Dataset calibrated preview failed")
            return frame

    def _publish(self, raw_frame):
        display = self._apply_preview(raw_frame)
        with self._frame_condition:
            self._raw_frame = raw_frame.copy()
            self._display_frame = display.copy()
            self._frame_seq += 1
            self._frame_condition.notify_all()

    def current_raw_frame(self):
        with self._frame_condition:
            return None if self._raw_frame is None else self._raw_frame.copy()

    def _camera_loop(self):
        next_tick = time.monotonic()

        while not self._stop_event.is_set():
            try:
                with self._camera_lock:
                    frame, _ = self.camera.capture_frame(with_resize=False)

                if (
                    frame is None
                    or not self.camera.last_capture_valid
                    or getattr(frame, "size", 0) == 0
                ):
                    self._last_camera_error = "Camera capture failed."
                else:
                    self._last_camera_error = None
                    self._publish(frame)
            except Exception as exc:
                self._last_camera_error = str(exc)
                logger.exception("Dataset camera loop failed")

            period = 1.0 / max(1.0, self.requested_fps)
            next_tick += period
            sleep_for = next_tick - time.monotonic()

            if sleep_for > 0:
                self._stop_event.wait(sleep_for)
            else:
                next_tick = time.monotonic()

        with self._camera_lock:
            self.camera.release()

    def start(self):
        self._stop_event.clear()
        if self._camera_thread is None or not self._camera_thread.is_alive():
            self._camera_thread = threading.Thread(
                target=self._camera_loop,
                daemon=True,
                name="dataset-camera",
            )
            self._camera_thread.start()

    def stop(self):
        self._stop_event.set()
        with self._frame_condition:
            self._frame_condition.notify_all()

        thread = self._camera_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)

        if (
            thread is self._camera_thread
            and thread is not None
            and not thread.is_alive()
        ):
            self._camera_thread = None

    def _mjpeg(self):
        last_seq = None

        while not self._stop_event.is_set():
            with self._frame_condition:
                self._frame_condition.wait_for(
                    lambda: (
                        self._stop_event.is_set()
                        or (
                            self._display_frame is not None
                            and self._frame_seq != last_seq
                        )
                    ),
                    timeout=1.0,
                )
                if self._stop_event.is_set():
                    return

                frame = (
                    None
                    if self._display_frame is None
                    else self._display_frame.copy()
                )
                seq = self._frame_seq

            if frame is None:
                continue

            try:
                ok, buffer = cv2.imencode(
                    ".jpg",
                    frame,
                    [cv2.IMWRITE_JPEG_QUALITY, 85],
                )
            except Exception:
                logger.exception("Failed to encode dataset stream frame")
                continue

            if not ok:
                continue

            last_seq = seq
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Cache-Control: no-store\r\n\r\n"
                + buffer.tobytes()
                + b"\r\n"
            )

    def capture(self):
        with self._operation_lock:
            raw = self.current_raw_frame()
            if raw is None:
                return False, "No camera frame is available yet.", None

            try:
                path = self.image_store.save(raw)
            except (OSError, ValueError) as exc:
                logger.exception("Dataset capture failed")
                return False, f"Failed to save image: {exc}", None

            return True, f"Captured {path.name}.", path.name

    def set_preview_mode(self, mode):
        mode = str(mode or "").strip().lower()
        if mode not in {"raw", "calibrated"}:
            raise ValueError("preview mode must be raw or calibrated")

        if mode == "calibrated":
            with self._calibration_lock:
                calibration = self._calibration
            if calibration is None or not calibration.enabled:
                raise ValueError(
                    self._calibration_error
                    or "No valid calibration file is available."
                )

        with self._frame_condition:
            self.preview_mode = mode
            raw = (
                None
                if self._raw_frame is None
                else self._raw_frame.copy()
            )

        if raw is not None:
            display = self._apply_preview(raw)
            with self._frame_condition:
                self._display_frame = display.copy()
                self._frame_seq += 1
                self._frame_condition.notify_all()

    def delete_capture(self, filename):
        with self._operation_lock:
            try:
                deleted = self.image_store.delete(filename)
            except ValueError as exc:
                return False, str(exc)
            if not deleted:
                return False, "Image not found."
            return True, f"Deleted {Path(filename).name}."

    def clear_dataset(self):
        with self._operation_lock:
            return self.image_store.clear()

    def build_zip(self):
        with self._operation_lock:
            paths = self.image_store.paths()
            if not paths:
                raise ValueError("The dataset is empty.")

            archive = SpooledTemporaryFile(
                max_size=8 * 1024 * 1024,
                mode="w+b",
                prefix="dataset-",
                suffix=".zip",
            )
            try:
                with zipfile.ZipFile(
                    archive,
                    "w",
                    compression=zipfile.ZIP_DEFLATED,
                    compresslevel=6,
                ) as zf:
                    for path in paths:
                        if path.is_file():
                            zf.write(path, arcname=path.name)
                archive.seek(0)
                return archive
            except Exception:
                archive.close()
                raise

    def upload_calibration(self, uploaded_file):
        if uploaded_file is None:
            raise ValueError("Choose a calibration .npz file first.")

        filename = secure_filename(uploaded_file.filename or "")
        if not filename:
            raise ValueError("The uploaded calibration file has no filename.")
        if Path(filename).suffix.lower() != ".npz":
            raise ValueError("Calibration file must use the .npz format.")

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                suffix=".npz",
                prefix=".upload-",
                dir=self.dataset_dir,
                delete=False,
            ) as handle:
                tmp_path = Path(handle.name)
                total = 0
                while True:
                    chunk = uploaded_file.stream.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > self.max_upload_bytes:
                        raise ValueError(
                            "Calibration file is larger than the 16 MiB upload limit."
                        )
                    handle.write(chunk)

            calibration = CameraCalibration(tmp_path, enabled=True)
            if not calibration.enabled:
                raise ValueError(
                    calibration.last_error
                    or "Calibration file failed validation."
                )

            with self._operation_lock, self._calibration_lock:
                os.replace(tmp_path, self.calibration_file)
                tmp_path = None
                self._calibration = CameraCalibration(
                    self.calibration_file,
                    enabled=True,
                )
                if self._calibration is None or not self._calibration.enabled:
                    raise ValueError(
                        "Calibration file could not be activated after validation."
                    )
                self._calibration_error = None

            return self._calibration_status()
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink()
                except OSError:
                    pass

    def calibration_download_path(self):
        with self._calibration_lock:
            calibration = self._calibration
        if calibration is None or not calibration.enabled:
            return None
        return self.calibration_file if self.calibration_file.exists() else None

    def status(self):
        return {
            "preview_mode": self.preview_mode,
            "captured_images": self.image_store.count(),
            "dataset": {"directory": "dataset_connector"},
            "camera": {
                "initialized": bool(
                    getattr(self.camera, "camera_initialized", False)
                ),
                "requested_fps": self.requested_fps,
                "measured_fps": getattr(
                    self.camera,
                    "measured_frame_rate",
                    None,
                ),
                "resolution": [
                    int(getattr(self.camera, "width", 0)),
                    int(getattr(self.camera, "height", 0)),
                ],
                "last_error": self._last_camera_error,
            },
            "calibration": self._calibration_status(),
        }

    def create_app(self):
        app = Flask(__name__)
        app.config["MAX_CONTENT_LENGTH"] = self.max_upload_bytes

        @app.errorhandler(RequestEntityTooLarge)
        def too_large(_error):
            return jsonify(
                success=False,
                message="Uploaded file exceeds the 16 MiB limit.",
            ), 413

        @app.get("/")
        def index():
            return render_template_string(DATASET_CONNECTOR_HTML)

        @app.get("/video_feed")
        def video_feed():
            return Response(
                self._mjpeg(),
                mimetype="multipart/x-mixed-replace; boundary=frame",
                headers={
                    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                    "Pragma": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )

        @app.get("/api/status")
        def api_status():
            return jsonify(self.status())

        @app.get("/api/captures")
        def api_captures():
            return jsonify(
                captures=[
                    {
                        "filename": path.name,
                        "url": f"/api/captures/{path.name}",
                    }
                    for path in reversed(self.image_store.paths())
                ],
            )

        @app.get("/api/captures/<path:filename>")
        def get_capture(filename):
            try:
                path = self.image_store.resolve(filename)
            except ValueError as exc:
                return jsonify(success=False, message=str(exc)), 400
            if not path.exists():
                return jsonify(success=False, message="Image not found."), 404

            view = request.args.get("view", "raw").strip().lower()
            if view not in {"raw", "calibrated"}:
                return jsonify(
                    success=False,
                    message="view must be raw or calibrated",
                ), 400

            if view == "raw":
                return send_file(path, mimetype="image/jpeg", max_age=0)

            with self._calibration_lock:
                calibration = self._calibration
            if calibration is None or not calibration.enabled:
                return jsonify(
                    success=False,
                    message=(
                        self._calibration_error
                        or "No valid calibration file is available."
                    ),
                ), 409

            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if image is None:
                return jsonify(
                    success=False,
                    message="Failed to read captured image.",
                ), 500

            try:
                calibrated = calibration.undistort(image)
                ok, buffer = cv2.imencode(
                    ".jpg",
                    calibrated,
                    [cv2.IMWRITE_JPEG_QUALITY, 90],
                )
            except Exception:
                logger.exception("Failed to generate calibrated image preview")
                return jsonify(
                    success=False,
                    message="Failed to generate calibrated preview.",
                ), 500

            if not ok:
                return jsonify(
                    success=False,
                    message="Failed to encode calibrated preview.",
                ), 500

            return Response(
                buffer.tobytes(),
                mimetype="image/jpeg",
                headers={"Cache-Control": "no-store"},
            )

        @app.post("/api/capture")
        def api_capture():
            saved, message, filename = self.capture()
            return jsonify(
                success=saved,
                message=message,
                filename=filename,
                captured_images=self.image_store.count(),
            ), (201 if saved else 409)

        @app.delete("/api/captures/<path:filename>")
        def api_delete_capture(filename):
            deleted, message = self.delete_capture(filename)
            return jsonify(
                success=deleted,
                message=message,
                captured_images=self.image_store.count(),
            ), (200 if deleted else 404)

        @app.post("/api/clear")
        def api_clear():
            removed = self.clear_dataset()
            return jsonify(
                success=True,
                removed=removed,
                captured_images=self.image_store.count(),
                message=f"Removed {removed} images.",
            )

        @app.post("/api/preview")
        def api_preview():
            data = request.get_json(silent=True) or {}
            try:
                self.set_preview_mode(data.get("mode"))
            except ValueError as exc:
                return jsonify(success=False, message=str(exc)), 409
            return jsonify(
                success=True,
                preview_mode=self.preview_mode,
            )

        @app.post("/api/calibration/upload")
        def api_calibration_upload():
            try:
                result = self.upload_calibration(request.files.get("file"))
            except ValueError as exc:
                return jsonify(success=False, message=str(exc)), 422
            except Exception:
                logger.exception("Calibration upload failed")
                return jsonify(
                    success=False,
                    message="Calibration upload failed.",
                ), 500

            return jsonify(
                success=True,
                message="Calibration file validated and activated.",
                calibration=result,
            )

        @app.get("/api/calibration/download")
        def api_calibration_download():
            path = self.calibration_download_path()
            if path is None:
                return jsonify(
                    success=False,
                    message="No valid calibration file is available.",
                ), 404
            return send_file(
                path,
                as_attachment=True,
                download_name="camera_calibration.npz",
                mimetype="application/octet-stream",
                max_age=0,
            )

        @app.get("/api/dataset/download")
        def api_dataset_download():
            try:
                archive = self.build_zip()
            except ValueError as exc:
                return jsonify(success=False, message=str(exc)), 409
            except Exception:
                logger.exception("Dataset ZIP generation failed")
                return jsonify(
                    success=False,
                    message="Failed to create dataset ZIP.",
                ), 500

            response = send_file(
                archive,
                as_attachment=True,
                download_name="dataset.zip",
                mimetype="application/zip",
                max_age=0,
            )
            response.call_on_close(archive.close)
            return response

        return app

    def serve_forever(self):
        from werkzeug.serving import make_server
        app = self.create_app()
        server = make_server(self.host, self.port, app, threaded=True)
        self.start()
        try:
            server.serve_forever()
        finally:
            server.server_close()
            self.stop()


def build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        description="Web camera dataset capture and calibration workspace.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5051)
    parser.add_argument(
        "--camera-mode",
        choices=["picam", "webcam", "opencv"],
        default=None,
    )
    parser.add_argument("--camera-index", type=int, default=None)
    parser.add_argument("--width", type=int, default=None)
    parser.add_argument("--height", type=int, default=None)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        default=DEFAULT_DATASET_DIR,
    )
    parser.add_argument(
        "--calibration-file",
        type=Path,
        default=DEFAULT_CALIBRATION_FILE,
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.camera_index is not None and args.camera_index < 0:
        raise SystemExit("--camera-index must be non-negative")
    if args.fps <= 0:
        raise SystemExit("--fps must be greater than zero")

    server = DatasetConnectorServer.from_options(
        camera_mode=args.camera_mode,
        camera_index=args.camera_index,
        width=args.width,
        height=args.height,
        fps=args.fps,
        dataset_dir=args.dataset_dir,
        calibration_file=args.calibration_file,
        host=args.host,
        port=args.port,
    )
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
