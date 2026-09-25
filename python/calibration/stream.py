import argparse
import logging
import threading
import time
from pathlib import Path

import cv2
from flask import Flask, Response, jsonify, render_template_string, request
from werkzeug.serving import make_server

from .calibrator import CameraCalibrator
from .capture import CalibrationImageStore
from .config import create_camera_config
from .template import CALIBRATION_HTML
from vision.camera import Camera


logger = logging.getLogger(__name__)


DEFAULT_IMAGE_DIR = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "images"
)
DEFAULT_OUTPUT_FILE = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "camera_calibration.npz"
)


class CalibrationStreamServer:
    """
    Flask calibration UI + background camera producer.

    The camera loop controls the requested camera FPS and separately reports
    measured FPS. On Raspberry Pi/Picamera2 the requested FPS is sent to
    libcamera via Camera.set_frame_rate().
    """

    def __init__(
        self,
        camera_config,
        image_dir=DEFAULT_IMAGE_DIR,
        output_file=DEFAULT_OUTPUT_FILE,
        checkerboard=(11, 7),
        square_size=1.0,
        min_valid_images=10,
        host="127.0.0.1",
        port=5050,
        target_fps=30.0,
    ):
        self.config = camera_config
        self.image_dir = Path(image_dir)
        self.output_file = Path(output_file)
        self.image_store = CalibrationImageStore(self.image_dir)

        self.calibrator = CameraCalibrator(
            checkerboard=checkerboard,
            square_size=square_size,
            min_valid_images=min_valid_images,
        )

        self.host = host
        self.port = int(port)

        self._lock = threading.Condition()
        self._camera_lock = threading.Lock()
        self._frame = None
        self._raw_frame = None
        self._frame_seq = 0
        self._stop_event = threading.Event()
        self._camera_thread = None
        self._calibration_thread = None

        self.requested_fps = float(target_fps)
        self.actual_fps = None
        self.chessboard_detected = False
        self._last_detection = None
        self._last_calibration = None
        self._calibration_state = "not calibrated"

        self.camera = Camera(config=self.config)
        self.camera.set_frame_rate(self.requested_fps)

    def _publish(self, raw_frame, display_frame):
        with self._lock:
            self._raw_frame = raw_frame.copy()
            self._frame = display_frame.copy()
            self._frame_seq += 1
            self._lock.notify_all()

    def _camera_loop(self):
        timestamps = []
        next_tick = time.monotonic()

        while not self._stop_event.is_set():
            started = time.monotonic()

            try:
                with self._camera_lock:
                    frame, _ = self.camera.capture_frame(
                        with_resize=False
                    )

                if frame is not None and self.camera.last_capture_valid:
                    evaluated = self.calibrator.evaluate_frame(frame)

                    self.chessboard_detected = bool(
                        evaluated["valid"]
                    )
                    self._last_detection = evaluated

                    display = evaluated.get(
                        "preview",
                        frame,
                    )
                    cv2.putText(
                        display,
                        (
                            "CHESSBOARD: "
                            + (
                                "DETECTED"
                                if evaluated["valid"]
                                else "NOT DETECTED"
                            )
                        ),
                        (10, 24),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.65,
                        (
                            (0, 255, 0)
                            if evaluated["valid"]
                            else (0, 255, 255)
                        ),
                        2,
                        cv2.LINE_AA,
                    )

                    self._publish(frame, display)

                    now = time.monotonic()
                    timestamps.append(now)
                    cutoff = now - 2.0
                    timestamps = [
                        t for t in timestamps
                        if t >= cutoff
                    ]

                    if len(timestamps) >= 2:
                        self.actual_fps = (
                            (len(timestamps) - 1)
                            / max(
                                1e-6,
                                timestamps[-1]
                                - timestamps[0],
                            )
                        )
                else:
                    self.chessboard_detected = False

            except Exception:
                logger.exception("Calibration camera loop failed")

            period = 1.0 / max(
                1.0,
                self.requested_fps,
            )
            next_tick += period
            sleep_for = next_tick - time.monotonic()

            if sleep_for > 0:
                self._stop_event.wait(sleep_for)
            else:
                next_tick = time.monotonic()

        with self._camera_lock:
            self.camera.release()

    def start(self):
        if (
            self._camera_thread is None
            or not self._camera_thread.is_alive()
        ):
            self._stop_event.clear()
            self._camera_thread = threading.Thread(
                target=self._camera_loop,
                daemon=True,
                name="calibration-camera",
            )
            self._camera_thread.start()

    def stop(self):
        self._stop_event.set()

        with self._lock:
            self._lock.notify_all()

        if (
            self._camera_thread is not None
            and self._camera_thread.is_alive()
        ):
            self._camera_thread.join(timeout=2.0)

    def set_fps(self, fps):
        fps = float(fps)
        if not 1.0 <= fps <= 120.0:
            raise ValueError(
                "fps must be between 1 and 120"
            )

        with self._camera_lock:
            self.camera.set_frame_rate(fps)
        self.requested_fps = fps

    def current_frame(self):
        with self._lock:
            if self._frame is None:
                return None
            return self._frame.copy()

    def current_raw_frame(self):
        with self._lock:
            if self._raw_frame is None:
                return None
            return self._raw_frame.copy()

    def mjpeg(self):
        last_seq = -1

        while not self._stop_event.is_set():
            with self._lock:
                self._lock.wait_for(
                    lambda: (
                        self._frame_seq != last_seq
                        or self._stop_event.is_set()
                    ),
                    timeout=1.0,
                )

                if self._stop_event.is_set():
                    return

                if self._frame is None:
                    continue

                frame = self._frame.copy()
                last_seq = self._frame_seq

            ok, encoded = cv2.imencode(
                ".jpg",
                frame,
                [
                    cv2.IMWRITE_JPEG_QUALITY,
                    85,
                ],
            )

            if not ok:
                continue

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n"
                + encoded.tobytes()
                + b"\r\n"
            )

    def capture(self):
        detection = self._last_detection
        frame = self.current_frame()

        if frame is None or detection is None:
            return False, "No camera frame is available."

        if not detection.get("valid"):
            return (
                False,
                "Chessboard was not detected. "
                "Move the board and try again.",
            )

        # Detection preview contains drawn corners, so save the raw frame
        # obtained from the camera instead of the display frame.
        # Use the raw frame already produced by the camera thread.
        # This avoids concurrent access to Picamera2/OpenCV capture from the
        # Flask request thread.
        raw = self.current_raw_frame()

        if raw is None:
            return False, "No raw camera frame is available."

        fresh = self.calibrator.evaluate_frame(raw)
        if not fresh["valid"]:
            return False, "Chessboard disappeared before capture."

        path = self.image_store.next_path()
        if not cv2.imwrite(str(path), raw):
            return False, "Failed to save calibration image."

        return True, f"Saved {path.name}"

    def _run_calibration(self):
        self._calibration_state = "calibrating"

        try:
            result = self.calibrator.calibrate_from_directory(
                self.image_dir,
                self.output_file,
            )
            self._last_calibration = result
            self._calibration_state = "calibrated"
            logger.info(
                "Calibration complete: valid=%d rms=%.6f reprojection=%.6f",
                result["valid_images"],
                result["rms"],
                result["mean_reprojection_error"],
            )
        except Exception:
            logger.exception("Camera calibration failed")
            self._calibration_state = "failed"

    def start_calibration(self):
        if (
            self._calibration_thread is not None
            and self._calibration_thread.is_alive()
        ):
            return False, "Calibration is already running."

        self._calibration_thread = threading.Thread(
            target=self._run_calibration,
            daemon=True,
            name="camera-calibration",
        )
        self._calibration_thread.start()
        return True, "Calibration started."

    def status(self):
        result = self._last_calibration or {}

        return {
            "camera_mode": getattr(
                self.config,
                "CAMERA_MODE",
                "unknown",
            ),
            "width": int(
                getattr(
                    self.config,
                    "CAM_WIDTH",
                    0,
                )
            ),
            "height": int(
                getattr(
                    self.config,
                    "CAM_HEIGHT",
                    0,
                )
            ),
            "requested_fps": self.requested_fps,
            "actual_fps": self.actual_fps,
            "chessboard_detected": self.chessboard_detected,
            "captured_images": self.image_store.count(),
            "calibration_state": self._calibration_state,
            "last_calibration_error": result.get("rms"),
            "mean_reprojection_error": result.get(
                "mean_reprojection_error"
            ),
        }

    def create_app(self):
        app = Flask(__name__)

        @app.get("/")
        def index():
            return render_template_string(CALIBRATION_HTML)

        @app.get("/video_feed")
        def video_feed():
            return Response(
                self.mjpeg(),
                mimetype=(
                    "multipart/x-mixed-replace; "
                    "boundary=frame"
                ),
            )

        @app.get("/api/status")
        def api_status():
            return jsonify(self.status())

        @app.post("/api/settings")
        def api_settings():
            try:
                data = request.get_json(silent=True) or {}
                if "fps" not in data:
                    return jsonify(
                        success=False,
                        message="fps is required",
                    ), 400

                self.set_fps(float(data["fps"]))
                return jsonify(
                    success=True,
                    requested_fps=self.requested_fps,
                )
            except (TypeError, ValueError) as exc:
                return jsonify(
                    success=False,
                    message=str(exc),
                ), 400
            except Exception:
                logger.exception(
                    "Failed to update calibration stream settings"
                )
                return jsonify(
                    success=False,
                    message="Failed to update camera FPS",
                ), 500

        @app.post("/api/capture")
        def api_capture():
            saved, message = self.capture()
            return jsonify(
                success=saved,
                saved=saved,
                message=message,
            ), (200 if saved else 409)

        @app.post("/api/clear")
        def api_clear():
            removed = self.image_store.clear()

            return jsonify(
                success=True,
                removed=removed,
                message=f"Removed {removed} calibration images.",
            )

        @app.post("/api/calibrate")
        def api_calibrate():
            started, message = self.start_calibration()
            return jsonify(
                success=started,
                message=message,
            ), (202 if started else 409)

        return app

    def serve_forever(self):
        app = self.create_app()
        server = make_server(
            self.host,
            self.port,
            app,
            threaded=True,
        )
        self.start()

        try:
            logger.info(
                "Calibration stream listening on http://%s:%d",
                self.host,
                self.port,
            )
            server.serve_forever()
        finally:
            server.server_close()
            self.stop()


def build_parser():
    parser = argparse.ArgumentParser(
        description="Live Flask camera calibration stream.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address. Use 0.0.0.0 for LAN access.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5050,
        help="Flask port.",
    )
    parser.add_argument(
        "--camera-mode",
        choices=["picam", "webcam", "opencv"],
        default=None,
    )
    parser.add_argument(
        "--camera-index",
        type=int,
        default=None,
    )
    parser.add_argument(
        "--width",
        type=int,
        default=None,
    )
    parser.add_argument(
        "--height",
        type=int,
        default=None,
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=30.0,
        help="Initial requested camera FPS.",
    )
    parser.add_argument(
        "--square-size",
        type=float,
        default=1.0,
        help="Physical chessboard square size.",
    )
    parser.add_argument(
        "--checkerboard-cols",
        type=int,
        default=11,
    )
    parser.add_argument(
        "--checkerboard-rows",
        type=int,
        default=7,
    )
    parser.add_argument(
        "--min-valid-images",
        type=int,
        default=10,
    )
    parser.add_argument(
        "--image-dir",
        type=Path,
        default=DEFAULT_IMAGE_DIR,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_FILE,
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(message)s",
    )

    if args.camera_index is not None and args.camera_index < 0:
        raise SystemExit(
            "--camera-index must be non-negative"
        )

    config = create_camera_config(
        camera_mode=args.camera_mode,
        camera_index=args.camera_index,
        width=args.width,
        height=args.height,
        target_fps=args.fps,
    )

    server = CalibrationStreamServer(
        camera_config=config,
        image_dir=args.image_dir,
        output_file=args.output,
        checkerboard=(
            args.checkerboard_cols,
            args.checkerboard_rows,
        ),
        square_size=args.square_size,
        min_valid_images=args.min_valid_images,
        host=args.host,
        port=args.port,
        target_fps=args.fps,
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()
