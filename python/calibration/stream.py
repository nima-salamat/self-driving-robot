import argparse
import logging
import socket
import struct
import threading
import time
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Linux exposes fcntl.
    fcntl = None

import cv2
from flask import Flask, Response, jsonify, render_template_string, request
from werkzeug.serving import make_server

from .calibrator import CameraCalibrator
from .capture import CalibrationImageStore
from .config import create_camera_config
from .template import CALIBRATION_HTML
from vision.camera import Camera


logger = logging.getLogger(__name__)


def _default_route_interfaces():
    """Return Linux interfaces carrying a default IPv4 route."""
    route_file = Path("/proc/net/route")
    if not route_file.exists():
        return []

    routes = []
    try:
        for line in route_file.read_text().splitlines()[1:]:
            fields = line.split()
            if len(fields) < 11 or fields[1] != "00000000":
                continue
            try:
                metric = int(fields[6])
            except ValueError:
                metric = 0
            routes.append((metric, fields[0]))
    except OSError:
        return []

    return [name for _, name in sorted(routes)]


def _interface_ipv4(interface):
    """Resolve the first IPv4 address assigned to a Linux interface."""
    if fcntl is None:
        return None

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            request = struct.pack("256s", interface.encode("utf-8")[:15])
            packed = fcntl.ioctl(sock.fileno(), 0x8915, request)
            return socket.inet_ntoa(packed[20:24])
        finally:
            sock.close()
    except (OSError, struct.error):
        return None


def discover_network_addresses():
    """
    Discover usable local IPv4 addresses without making network requests.

    The default-route interface is preferred, followed by other interfaces
    visible under /sys/class/net.
    """
    interfaces = []
    for interface in _default_route_interfaces():
        if interface not in interfaces:
            interfaces.append(interface)

    net_dir = Path("/sys/class/net")
    if net_dir.exists():
        try:
            for entry in sorted(net_dir.iterdir()):
                if entry.name not in interfaces:
                    interfaces.append(entry.name)
        except OSError:
            pass

    addresses = []
    for interface in interfaces:
        address = _interface_ipv4(interface)
        if not address or address.startswith("127.") or address.startswith("169.254."):
            continue
        addresses.append({"interface": interface, "ip": address})

    if addresses:
        return addresses

    try:
        hostname = socket.gethostname()
        resolved = {
            info[4][0]
            for info in socket.getaddrinfo(
                hostname,
                None,
                socket.AF_INET,
                socket.SOCK_STREAM,
            )
        }
        return [
            {"interface": "host", "ip": ip}
            for ip in sorted(resolved)
            if not ip.startswith("127.") and ip != "0.0.0.0"
        ]
    except OSError:
        return []


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
        self.board_squares = (
            self.calibrator.checkerboard[0] + 1,
            self.calibrator.checkerboard[1] + 1,
        )
        self.min_valid_images = int(min_valid_images)

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
        self._operation_lock = threading.Lock()
        self._accepted_features = []
        self.last_rejection_reason = None

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
                    quality_reason = self.calibrator.quality_reason(evaluated)
                    evaluated["quality_valid"] = quality_reason is None
                    evaluated["quality_reason"] = quality_reason

                    self.chessboard_detected = bool(
                        evaluated["valid"]
                    )
                    self.last_rejection_reason = quality_reason
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
                                "READY"
                                if evaluated.get("quality_valid")
                                else (
                                    "DETECTED / REJECTED"
                                    if evaluated.get("valid")
                                    else "NOT DETECTED"
                                )
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

    def set_board_configuration(
        self,
        board_cols,
        board_rows,
        square_size,
        min_valid_images=None,
    ):
        board_cols = int(board_cols)
        board_rows = int(board_rows)
        square_size = float(square_size)
        min_valid_images = (
            self.min_valid_images
            if min_valid_images is None
            else int(min_valid_images)
        )

        if board_cols < 2 or board_rows < 2:
            raise ValueError("board dimensions must be at least 2 x 2 squares")
        if board_cols > 100 or board_rows > 100:
            raise ValueError("board dimensions must not exceed 100 x 100 squares")
        if square_size <= 0:
            raise ValueError("square_size must be greater than zero")
        if min_valid_images < 3 or min_valid_images > 500:
            raise ValueError("min_valid_images must be between 3 and 500")

        new_board_squares = (board_cols, board_rows)
        new_inner_corners = (board_cols - 1, board_rows - 1)

        if (
            new_board_squares == self.board_squares
            and abs(self.calibrator.square_size - square_size) < 1e-12
            and min_valid_images == self.min_valid_images
        ):
            return

        if (
            self._calibration_thread is not None
            and self._calibration_thread.is_alive()
        ):
            raise ValueError(
                "Calibration is running; board configuration cannot be changed."
            )

        if self.image_store.count() > 0:
            raise ValueError(
                "Clear captured calibration images before changing the board configuration."
            )

        self.calibrator = CameraCalibrator(
            checkerboard=new_inner_corners,
            square_size=square_size,
            min_valid_images=min_valid_images,
        )
        self.board_squares = new_board_squares
        self.min_valid_images = min_valid_images
        self._accepted_features.clear()
        self._last_detection = None
        self.last_rejection_reason = None
        self.chessboard_detected = False
        self._last_calibration = None
        self._calibration_state = "not calibrated"

    def _validate_fps(self, fps):
        fps = float(fps)
        if not 1.0 <= fps <= 120.0:
            raise ValueError("fps must be between 1 and 120")
        return fps

    def set_fps(self, fps):
        fps = self._validate_fps(fps)

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
        if (
            self._calibration_thread is not None
            and self._calibration_thread.is_alive()
        ):
            return (
                False,
                "Calibration is running; capture is temporarily disabled.",
            )
        with self._operation_lock:
            raw = self.current_raw_frame()
            if raw is None:
                return False, "No raw camera frame is available."
            fresh = self.calibrator.evaluate_frame(raw)
            reason = self.calibrator.quality_reason(fresh)
            if reason is not None:
                self.last_rejection_reason = reason
                return False, reason
            if self.calibrator.is_duplicate(
                fresh,
                self._accepted_features,
            ):
                self.last_rejection_reason = "too similar to another accepted view"
                return False, self.last_rejection_reason
            path = self.image_store.next_path()
            if not cv2.imwrite(str(path), raw):
                return False, "Failed to save calibration image."
            self._accepted_features.append(fresh["feature"])
            self.last_rejection_reason = None
            return True, f"Saved {path.name}"

    def _run_calibration(self):
        with self._operation_lock:
            self._calibration_state = "calibrating"
            try:
                result = self.calibrator.calibrate_from_directory(
                    self.image_dir,
                    self.output_file,
                )
                self._last_calibration = result
                self._calibration_state = (
                    "calibrated"
                    if result.get("acceptable_for_runtime", True)
                    else "quality_failed"
                )
                logger.info(
                    "Calibration complete: valid=%d rms=%.6f "
                    "reprojection=%.6f quality=%s",
                    result["valid_images"],
                    result["rms"],
                    result["mean_reprojection_error"],
                    result.get("quality_status", "unknown"),
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
            "capture_eligible": bool(
                self._last_detection
                and self._last_detection.get("quality_valid")
            ),
            "last_rejection_reason": self.last_rejection_reason,
            "camera_fps_limits": (
                self.camera.get_frame_rate_limits()
                if hasattr(self.camera, "get_frame_rate_limits")
                else None
            ),
            "image_size": [
                int(getattr(self.config, "CAM_WIDTH", 0)),
                int(getattr(self.config, "CAM_HEIGHT", 0)),
            ],
            "checkerboard": list(self.calibrator.checkerboard),
            "checkerboard_inner_corners": list(self.calibrator.checkerboard),
            "board_squares": list(self.board_squares),
            "square_size": self.calibrator.square_size,
            "min_valid_images": self.min_valid_images,
            "captured_images": self.image_store.count(),
            "network_addresses": discover_network_addresses(),
            "calibration_state": self._calibration_state,
            "last_calibration_error": result.get("rms"),
            "mean_reprojection_error": result.get(
                "mean_reprojection_error"
            ),
            "median_reprojection_error": result.get(
                "median_reprojection_error"
            ),
            "max_reprojection_error": result.get(
                "max_reprojection_error"
            ),
            "per_view_reprojection_error": result.get(
                "per_view_errors",
                result.get("per_view_error"),
            ),
            "quality_status": result.get(
                "quality_status",
                "not evaluated",
            ),
            "acceptable_for_runtime": result.get(
                "acceptable_for_runtime"
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
                supported = {
                    "fps",
                    "board_cols",
                    "board_rows",
                    "square_size",
                    "min_valid_images",
                }
                unknown = sorted(set(data) - supported)
                if unknown:
                    return jsonify(
                        success=False,
                        message=f"Unsupported settings: {', '.join(unknown)}",
                    ), 400

                if not data:
                    return jsonify(
                        success=False,
                        message="At least one setting is required",
                    ), 400

                if "fps" in data:
                    self._validate_fps(data["fps"])

                board_keys = {
                    "board_cols",
                    "board_rows",
                    "square_size",
                    "min_valid_images",
                }
                if board_keys.intersection(data):
                    self.set_board_configuration(
                        board_cols=data.get("board_cols", self.board_squares[0]),
                        board_rows=data.get("board_rows", self.board_squares[1]),
                        square_size=data.get(
                            "square_size",
                            self.calibrator.square_size,
                        ),
                        min_valid_images=data.get(
                            "min_valid_images",
                            self.min_valid_images,
                        ),
                    )

                if "fps" in data:
                    self.set_fps(float(data["fps"]))

                return jsonify(
                    success=True,
                    requested_fps=self.requested_fps,
                    board_squares=list(self.board_squares),
                    checkerboard_inner_corners=list(self.calibrator.checkerboard),
                    square_size=self.calibrator.square_size,
                    min_valid_images=self.min_valid_images,
                )
            except (TypeError, ValueError) as exc:
                status = (
                    409
                    if (
                        "Clear captured calibration images" in str(exc)
                        or "Calibration is running" in str(exc)
                    )
                    else 400
                )
                return jsonify(
                    success=False,
                    message=str(exc),
                ), status
            except Exception:
                logger.exception(
                    "Failed to update calibration stream settings"
                )
                return jsonify(
                    success=False,
                    message="Failed to update calibration stream settings",
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
            if (
                self._calibration_thread is not None
                and self._calibration_thread.is_alive()
            ):
                return jsonify(
                    success=False,
                    message=(
                        "Calibration is running; clear is temporarily "
                        "disabled."
                    ),
                ), 409
            with self._operation_lock:
                removed = self.image_store.clear()
                self._accepted_features.clear()
                self.last_rejection_reason = None

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
        if self.host in {"0.0.0.0", "::"}:
            logger.warning(
                "Calibration stream is bound to %s; /api/capture, "
                "/api/clear, /api/settings, and /api/calibrate are "
                "unauthenticated network controls.",
                self.host,
            )
        app = self.create_app()
        server = make_server(
            self.host,
            self.port,
            app,
            threaded=True,
        )
        self.start()

        try:
            if self.host in {"0.0.0.0", "::"}:
                logger.info(
                    "Calibration stream bound to %s:%d (all network interfaces)",
                    self.host,
                    self.port,
                )
                addresses = discover_network_addresses()
                if addresses:
                    logger.info("Open the calibration UI from another device:")
                    for address in addresses:
                        logger.info(
                            "  %s -> http://%s:%d",
                            address["interface"],
                            address["ip"],
                            self.port,
                        )
                else:
                    logger.warning(
                        "No non-loopback IPv4 address was detected; "
                        "use 'ip addr' to find the robot's LAN address."
                    )
            elif self.host in {"127.0.0.1", "localhost"}:
                logger.info(
                    "Calibration stream listening on http://127.0.0.1:%d (local machine only)",
                    self.port,
                )
                logger.info(
                    "For access from a phone/PC on the same LAN, restart with "
                    "--host 0.0.0.0"
                )
            else:
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
