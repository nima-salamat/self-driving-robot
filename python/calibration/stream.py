import argparse
import copy
import logging
import math
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
import numpy as np
from flask import (
    Flask,
    Response,
    jsonify,
    render_template_string,
    request,
    send_file,
    send_from_directory,
)
from werkzeug.serving import make_server

from .calibrator import CameraCalibration, CameraCalibrator
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
        checkerboard=(7, 9),
        square_size=20.0,
        min_valid_images=10,
        host="127.0.0.1",
        port=5050,
        target_fps=30.0,
    ):
        self.config = camera_config
        setattr(self.config, "APPLY_CAMERA_CALIBRATION", False)
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
        self._detection_thread = None
        self._detection_wakeup = threading.Event()
        self._calibration_thread = None
        self._operation_lock = threading.Lock()
        self._calibrator_lock = threading.RLock()
        self._detection_state_lock = threading.Lock()
        self._accepted_features = []
        self.last_rejection_reason = None

        self.auto_capture_enabled = True
        self.auto_capture_interval = 1.0
        self.last_auto_capture_at = 0.0
        self.auto_captured_images = 0
        self.calibration_preview_enabled = False
        self._calibration_preview = None
        self.workspace_mode = "calibration"
        self._auto_capture_before_calibrated = True
        self._calibration_cancel = threading.Event()

        self.requested_fps = float(target_fps)
        self.actual_fps = None
        self.chessboard_detected = False
        self._last_detection = None
        self._last_calibration = None
        self._calibration_state = "not calibrated"
        self._last_calibration_message = None
        self._last_camera_error = None
        self._last_detection_at = 0.0
        self._detection_count = 0
        self._last_detection_duration_ms = None
        self.detection_interval = self._validate_detection_interval(
            getattr(
                self.config,
                "CALIBRATION_DETECTION_INTERVAL",
                0.20,
            )
        )
        # Recovery preprocessing is intentionally slower than the direct
        # detector. Keep it out of the normal live-frame cadence.
        self.detection_recovery_interval = max(
            2.0,
            self.detection_interval * 8.0,
        )
        self._last_detection_recovery_at = 0.0

        self._restore_persisted_capture_state()

        self.camera = Camera(config=self.config)
        self.camera.set_frame_rate(self.requested_fps)

    def _publish(self, raw_frame, display_frame):
        with self._lock:
            self._raw_frame = raw_frame.copy()
            self._frame = display_frame.copy()
            self._frame_seq += 1
            self._lock.notify_all()

    def _display_frame(self, frame):
        if self.workspace_mode != "calibrated":
            return frame
        if not self.calibration_preview_enabled:
            return frame

        preview = self._calibration_preview
        if preview is None or not preview.enabled:
            return frame

        try:
            return preview.undistort(frame)
        except Exception as exc:
            logger.exception("Calibration preview failed")
            self._last_camera_error = (
                f"Calibration preview failed: {exc}"
            )
            return frame

    def _decorate_live_frame(self, frame):
        display = frame.copy()

        with self._calibrator_lock:
            checkerboard = tuple(self.calibrator.checkerboard)

        with self._detection_state_lock:
            evaluation = self._last_detection
            detected_at = self._last_detection_at

        now = time.monotonic()
        detection_freshness = max(
            0.5,
            self.detection_interval * 2.5,
        )

        if (
            self.workspace_mode == "calibration"
            and evaluation
            and evaluation.get("corners") is not None
            and detected_at
            and now - detected_at <= detection_freshness
        ):
            corners = evaluation["corners"]
            if self.calibration_preview_enabled:
                preview = self._calibration_preview
                if preview is not None and preview.enabled:
                    corners = preview.undistort_points(
                        corners,
                        (
                            int(display.shape[1]),
                            int(display.shape[0]),
                        ),
                    )
            cv2.drawChessboardCorners(
                display,
                checkerboard,
                corners,
                True,
            )

        state = (
            self._detection_state(evaluation)
            if self.workspace_mode == "calibration"
            else "DETECTOR_DISABLED"
        )
        cv2.putText(
            display,
            f"CHESSBOARD: {state.replace('_', ' ')}",
            (10, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.60,
            (
                (0, 255, 0)
                if state == "READY_FOR_CAPTURE"
                else (0, 220, 255)
                if state == "DETECTED_BUT_REJECTED"
                else (0, 160, 255)
            ),
            2,
            cv2.LINE_AA,
        )
        return display

    def _camera_loop(self):
        timestamps = []
        next_tick = time.monotonic()

        while not self._stop_event.is_set():
            try:
                with self._camera_lock:
                    frame, _ = self.camera.capture_frame(
                        with_resize=False
                    )

                if frame is None or not self.camera.last_capture_valid:
                    self._last_camera_error = "Camera capture failed."
                    self.chessboard_detected = False
                else:
                    now = time.monotonic()
                    self._last_camera_error = None

                    # The camera producer never waits for chessboard detection.
                    # Wake the detector, but always publish this newest frame
                    # immediately so the HTTP stream cannot build a stale queue.
                    if self.workspace_mode == "calibration":
                        self._detection_wakeup.set()
                    display_source = self._display_frame(frame)
                    display = self._decorate_live_frame(
                        display_source
                    )
                    self._publish(frame, display)

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
                                timestamps[-1] - timestamps[0],
                            )
                        )

            except Exception as exc:
                self._last_camera_error = str(exc)
                logger.exception(
                    "Calibration camera loop failed"
                )

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

    def _detection_loop(self):
        next_detection = time.monotonic()

        while not self._stop_event.is_set():
            now = time.monotonic()
            wait_for = max(
                0.0,
                next_detection - now,
            )

            # Detection is intentionally timer-driven. The camera publishes
            # frames continuously, so waking this worker for every camera
            # frame can keep a slow detector in a tight catch-up loop.
            if self._stop_event.wait(wait_for):
                return

            now = time.monotonic()
            if self.workspace_mode != "calibration":
                self._clear_detection_state()
                if self._stop_event.wait(0.25):
                    return
                next_detection = time.monotonic()
                continue

            raw = self.current_raw_frame()
            if raw is None:
                next_detection = now + self.detection_interval
                continue

            started = time.monotonic()
            try:
                # Snapshot the calibrator object while holding the lock, then
                # release it before running OpenCV. Board/detection/quality
                # settings replace the calibrator atomically, so the expensive
                # detector never blocks /api/status or the live camera thread.
                with self._calibrator_lock:
                    calibrator = self.calibrator

                allow_recovery = (
                    now - self._last_detection_recovery_at
                    >= self.detection_recovery_interval
                )
                if allow_recovery:
                    self._last_detection_recovery_at = now

                worker_calibrator = copy.copy(calibrator)
                evaluated = worker_calibrator.evaluate_frame(
                    raw,
                    allow_recovery=allow_recovery,
                )
                quality_reason = worker_calibrator.quality_reason(
                    evaluated
                )
                evaluated["quality_valid"] = (
                    quality_reason is None
                )
                evaluated["quality_reason"] = quality_reason

                # A settings update may have replaced the calibrator while
                # OpenCV was working. Do not publish or auto-capture a result
                # computed with obsolete board/quality settings.
                with self._calibrator_lock:
                    current_calibrator = self.calibrator

                if current_calibrator is not calibrator:
                    next_detection = time.monotonic() + self.detection_interval
                    continue

                finished = time.monotonic()
                with self._detection_state_lock:
                    self._last_detection = evaluated
                    self._last_detection_at = finished
                    self._detection_count += 1
                    self._last_detection_duration_ms = round(
                        (finished - started) * 1000.0,
                        1,
                    )
                    self.chessboard_detected = bool(
                        evaluated.get("valid")
                    )
                    self.last_rejection_reason = quality_reason

                self._maybe_auto_capture(
                    raw,
                    evaluated,
                    calibrator=calibrator,
                )
            except Exception as exc:
                finished = time.monotonic()
                message = f"Detector error: {exc}"
                logger.exception(
                    "Calibration detection loop failed"
                )
                with self._detection_state_lock:
                    self._last_detection = {
                        "valid": False,
                        "detected": False,
                        "quality_valid": False,
                        "corners": None,
                        "coverage": 0.0,
                        "center": None,
                        "sharpness": 0.0,
                        "edge_margin": 0.0,
                        "feature": None,
                        "detector": "error",
                        "detection_view": "error",
                        "detection_scale": 1.0,
                        "quality_reason": message,
                        "gray": None,
                        "preview": None,
                    }
                    self._last_detection_at = finished
                    self._detection_count += 1
                    self._last_detection_duration_ms = round(
                        (finished - started) * 1000.0,
                        1,
                    )
                    self.chessboard_detected = False
                    self.last_rejection_reason = message
            finally:
                # Start the next cadence from completion, not from the
                # previous scheduled deadline. A slow OpenCV pass therefore
                # cannot cause immediate back-to-back detections.
                next_detection = time.monotonic() + self.detection_interval

    def start(self):
        if (
            self._detection_thread is None
            or not self._detection_thread.is_alive()
        ):
            self._stop_event.clear()
            self._detection_thread = threading.Thread(
                target=self._detection_loop,
                daemon=True,
                name="calibration-detection",
            )
            self._detection_thread.start()

        if (
            self._camera_thread is None
            or not self._camera_thread.is_alive()
        ):
            self._camera_thread = threading.Thread(
                target=self._camera_loop,
                daemon=True,
                name="calibration-camera",
            )
            self._camera_thread.start()

    def stop(self):
        self._stop_event.set()
        self._detection_wakeup.set()

        with self._lock:
            self._lock.notify_all()

        if (
            self._detection_thread is not None
            and self._detection_thread.is_alive()
        ):
            self._detection_thread.join(timeout=2.0)

        if (
            self._camera_thread is not None
            and self._camera_thread.is_alive()
        ):
            self._camera_thread.join(timeout=2.0)

    def _validate_detection_interval(self, value):
        try:
            interval = float(value)
        except (TypeError, ValueError):
            raise ValueError(
                "detection_interval must be a number"
            )
        if not math.isfinite(interval):
            raise ValueError(
                "detection_interval must be finite"
            )
        if not 0.05 <= interval <= 2.0:
            raise ValueError(
                "detection_interval must be between 0.05 and 2 seconds"
            )
        return interval

    @staticmethod
    def _detection_state(evaluation):
        if not evaluation or not evaluation.get("valid"):
            return "NOT_DETECTED"
        if evaluation.get("quality_valid"):
            return "READY_FOR_CAPTURE"
        return "DETECTED_BUT_REJECTED"

    @staticmethod
    def _feature_cell(feature):
        if feature is None or len(feature) < 2:
            return None
        x = min(
            2,
            max(
                0,
                int(float(feature[0]) * 3.0),
            ),
        )
        y = min(
            2,
            max(
                0,
                int(float(feature[1]) * 3.0),
            ),
        )
        return y * 3 + x

    def _diversity_summary(self):
        cells = [0] * 9
        for feature in self._accepted_features:
            cell = self._feature_cell(feature)
            if cell is not None:
                cells[cell] += 1
        return {
            "grid": cells,
            "occupied_cells": sum(
                1 for value in cells if value
            ),
            "total_cells": 9,
        }

    def _restore_persisted_capture_state(self):
        restored = []
        for path in self.image_store.paths():
            metadata = self.image_store.load_metadata(path)
            if not metadata:
                continue
            try:
                feature = np.asarray(
                    metadata.get("feature"),
                    dtype=np.float32,
                ).reshape(-1)
            except (TypeError, ValueError):
                continue
            if (
                feature.shape != (7,)
                or not np.isfinite(feature).all()
            ):
                continue
            restored.append(feature)
        self._accepted_features = restored

    def _auto_capture_is_diverse(self, evaluation):
        feature = evaluation.get("feature")
        if feature is None:
            return False

        if not self._accepted_features:
            return True

        cell = self._feature_cell(feature)
        occupied = {
            self._feature_cell(existing)
            for existing in self._accepted_features
        }
        if cell is not None and cell not in occupied:
            return True

        distances = [
            float(
                np.linalg.norm(
                    feature - existing
                )
            )
            for existing in self._accepted_features
        ]
        nearest = min(
            distances,
            default=float("inf"),
        )
        return nearest >= max(
            self.calibrator.duplicate_distance * 1.5,
            0.08,
        )

    def set_board_configuration(
        self,
        board_cols,
        board_rows,
        square_size,
        min_valid_images=None,
        replace_captures=False,
    ):
        try:
            board_cols = int(board_cols)
            board_rows = int(board_rows)
        except (TypeError, ValueError):
            raise ValueError(
                "board dimensions must be integers"
            )

        try:
            square_size = float(square_size)
        except (TypeError, ValueError):
            raise ValueError(
                "square_size must be a number"
            )

        min_valid_images = (
            self.min_valid_images
            if min_valid_images is None
            else int(min_valid_images)
        )

        if board_cols < 2 or board_rows < 2:
            raise ValueError(
                "board dimensions must be at least 2 x 2 squares"
            )
        if board_cols > 100 or board_rows > 100:
            raise ValueError(
                "board dimensions must not exceed 100 x 100 squares"
            )
        if (
            not math.isfinite(square_size)
            or square_size <= 0
        ):
            raise ValueError(
                "square_size must be finite and greater than zero"
            )
        if min_valid_images < 3 or min_valid_images > 500:
            raise ValueError(
                "min_valid_images must be between 3 and 500"
            )

        new_board_squares = (
            board_cols,
            board_rows,
        )
        new_inner_corners = (
            board_cols - 1,
            board_rows - 1,
        )

        with self._operation_lock:
            with self._calibrator_lock:
                current = self.calibrator
                if (
                    new_board_squares == self.board_squares
                    and abs(
                        current.square_size - square_size
                    ) < 1e-12
                    and min_valid_images == self.min_valid_images
                ):
                    return

                if (
                    self._calibration_thread is not None
                    and self._calibration_thread.is_alive()
                ):
                    raise ValueError(
                        "Calibration is running; board configuration "
                        "cannot be changed."
                    )

                if self.workspace_mode != "calibration":
                    raise ValueError(
                        "Switch to calibration mode before changing "
                        "the board configuration."
                    )

                if self.image_store.count() > 0:
                    if not replace_captures:
                        raise ValueError(
                            "Captured calibration images exist; confirm "
                            "replacement to clear them before changing "
                            "the board configuration."
                        )
                    self.image_store.clear()

                self.calibrator = CameraCalibrator(
                    checkerboard=new_inner_corners,
                    square_size=square_size,
                    min_valid_images=min_valid_images,
                    min_coverage=current.min_coverage,
                    min_sharpness=current.min_sharpness,
                    min_edge_margin=current.min_edge_margin,
                    duplicate_distance=current.duplicate_distance,
                    max_mean_reprojection_error=(
                        current.max_mean_reprojection_error
                    ),
                    max_view_reprojection_error=(
                        current.max_view_reprojection_error
                    ),
                    detector_mode=current.detector_mode,
                )

                self.board_squares = new_board_squares
                self.min_valid_images = min_valid_images
                self._accepted_features.clear()
                self._last_detection = None
                self._last_detection_at = 0.0
                self.last_rejection_reason = None
                self.chessboard_detected = False
                self._last_calibration = None
                self._last_calibration_message = None
                self._calibration_state = "not calibrated"
                self._calibration_preview = None
                self.calibration_preview_enabled = False
                if self.output_file.exists():
                    try:
                        self.output_file.unlink()
                    except OSError as exc:
                        logger.warning(
                            "Failed to remove stale calibration model: %s",
                            exc,
                        )

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

    def debug_frame(
        self,
        view="detector",
        threshold=128,
        adaptive_block=21,
        adaptive_c=5,
    ):
        raw = self.current_raw_frame()
        if raw is None:
            return None

        view = str(
            view or "detector"
        ).strip().lower()

        try:
            threshold = int(threshold)
        except (TypeError, ValueError):
            threshold = 128
        threshold = max(
            0,
            min(255, threshold),
        )

        try:
            adaptive_block = int(adaptive_block)
        except (TypeError, ValueError):
            adaptive_block = 21
        adaptive_block = max(
            3,
            adaptive_block,
        )
        if adaptive_block % 2 == 0:
            adaptive_block += 1

        try:
            adaptive_c = int(adaptive_c)
        except (TypeError, ValueError):
            adaptive_c = 5

        if view in {
            "detector",
            "clahe",
            "invert",
        }:
            with self._calibrator_lock:
                display = self.calibrator.debug_preprocessed(
                    raw,
                    view=view,
                )
        else:
            gray = cv2.cvtColor(
                raw,
                cv2.COLOR_BGR2GRAY,
            )
            if view == "gray":
                debug = gray
            elif view == "fixed":
                _, debug = cv2.threshold(
                    gray,
                    threshold,
                    255,
                    cv2.THRESH_BINARY,
                )
            elif view == "otsu":
                _, debug = cv2.threshold(
                    gray,
                    0,
                    255,
                    cv2.THRESH_BINARY + cv2.THRESH_OTSU,
                )
            elif view == "adaptive":
                debug = cv2.adaptiveThreshold(
                    gray,
                    255,
                    cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                    cv2.THRESH_BINARY,
                    adaptive_block,
                    adaptive_c,
                )
            elif view == "normalized":
                debug = cv2.normalize(
                    gray,
                    None,
                    0,
                    255,
                    cv2.NORM_MINMAX,
                )
            else:
                raise ValueError(
                    "view must be one of: detector, clahe, invert, "
                    "gray, normalized, fixed, otsu, adaptive"
                )
            display = cv2.cvtColor(
                debug,
                cv2.COLOR_GRAY2BGR,
            )

        return display

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

            payload = encoded.tobytes()
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                + f"Content-Length: {len(payload)}\r\n".encode("ascii")
                + b"Cache-Control: no-store, no-cache, must-revalidate\r\n"
                + b"Pragma: no-cache\r\n\r\n"
                + payload
                + b"\r\n"
            )

    def _save_evaluated_frame(
        self,
        raw_frame,
        evaluation,
        auto=False,
    ):
        if not evaluation.get("quality_valid"):
            return (
                False,
                evaluation.get(
                    "quality_reason",
                    "frame rejected",
                ),
            )

        with self._calibrator_lock:
            if self.calibrator.is_duplicate(
                evaluation,
                self._accepted_features,
            ):
                reason = (
                    "This view is too similar to an accepted capture."
                )
                if not auto:
                    self.last_rejection_reason = reason
                return False, reason

            if (
                auto
                and not self._auto_capture_is_diverse(
                    evaluation
                )
            ):
                return (
                    False,
                    "Auto-capture skipped: move or tilt the board "
                    "to create a more diverse view.",
                )

            try:
                path = self.image_store.save(
                    raw_frame,
                    {
                        "format_version": 1,
                        "captured_at": time.time(),
                        "image_size": [
                            int(raw_frame.shape[1]),
                            int(raw_frame.shape[0]),
                        ],
                        "checkerboard": list(
                            self.calibrator.checkerboard
                        ),
                        "square_size": float(
                            self.calibrator.square_size
                        ),
                        "corners": (
                            evaluation["corners"]
                            .reshape(-1, 2)
                            .tolist()
                        ),
                        "coverage": float(
                            evaluation.get("coverage", 0.0)
                        ),
                        "center": list(
                            evaluation.get(
                                "center",
                                (0.0, 0.0),
                            )
                        ),
                        "sharpness": float(
                            evaluation.get("sharpness", 0.0)
                        ),
                        "edge_margin": float(
                            evaluation.get("edge_margin", 0.0)
                        ),
                        "feature": evaluation[
                            "feature"
                        ].tolist(),
                        "detector": str(
                            evaluation.get(
                                "detector",
                                "unknown",
                            )
                        ),
                        "detection_view": str(
                            evaluation.get(
                                "detection_view",
                                "detector",
                            )
                        ),
                        "detection_scale": float(
                            evaluation.get(
                                "detection_scale",
                                1.0,
                            )
                        ),
                    },
                )
            except (
                OSError,
                IOError,
                ValueError,
                TypeError,
            ) as exc:
                logger.exception(
                    "Failed to save calibration capture"
                )
                self.last_rejection_reason = str(exc)
                return (
                    False,
                    f"Failed to save calibration capture: {exc}",
                )

            self._accepted_features.append(
                np.asarray(
                    evaluation["feature"],
                    dtype=np.float32,
                )
            )

        self.last_rejection_reason = None
        if auto:
            self.last_auto_capture_at = time.monotonic()
            self.auto_captured_images += 1
        self._last_calibration_message = None
        return True, f"Saved {path.name}"

    def _maybe_auto_capture(
        self,
        raw_frame,
        evaluation,
        calibrator=None,
    ):
        if self.workspace_mode != "calibration":
            return
        if not self.auto_capture_enabled:
            return
        if (
            self._calibration_thread is not None
            and self._calibration_thread.is_alive()
        ):
            return
        if not evaluation.get("quality_valid"):
            return

        if calibrator is not None:
            with self._calibrator_lock:
                if self.calibrator is not calibrator:
                    return

        now = time.monotonic()
        if (
            now - self.last_auto_capture_at
            < self.auto_capture_interval
        ):
            return

        with self._operation_lock:
            saved, reason = self._save_evaluated_frame(
                raw_frame,
                evaluation,
                auto=True,
            )
        if saved:
            logger.info(
                "Auto-captured calibration image #%d",
                self.image_store.count(),
            )
        elif reason:
            logger.debug(reason)

    def set_auto_capture(
        self,
        enabled,
        interval=None,
    ):
        if not isinstance(enabled, bool):
            raise ValueError(
                "auto_capture_enabled must be boolean"
            )
        self.auto_capture_enabled = enabled

        if interval is not None:
            try:
                interval = float(interval)
            except (TypeError, ValueError):
                raise ValueError(
                    "auto_capture_interval must be a number"
                )
            if not math.isfinite(interval):
                raise ValueError(
                    "auto_capture_interval must be finite"
                )
            if not 0.2 <= interval <= 30.0:
                raise ValueError(
                    "auto_capture_interval must be between "
                    "0.2 and 30 seconds"
                )
            self.auto_capture_interval = interval

        if not self.auto_capture_enabled:
            self.last_auto_capture_at = 0.0

    def set_detector_mode(self, mode):
        with self._calibrator_lock:
            updated = copy.copy(self.calibrator)
            updated.set_detector_mode(mode)
            self.calibrator = updated

    def set_quality_settings(
        self,
        min_coverage=None,
        min_sharpness=None,
        min_edge_margin=None,
        duplicate_distance=None,
        max_mean_reprojection_error=None,
        max_view_reprojection_error=None,
    ):
        values = {
            "min_coverage": min_coverage,
            "min_sharpness": min_sharpness,
            "min_edge_margin": min_edge_margin,
            "duplicate_distance": duplicate_distance,
            "max_mean_reprojection_error": max_mean_reprojection_error,
            "max_view_reprojection_error": max_view_reprojection_error,
        }
        with self._calibrator_lock:
            updated = copy.copy(self.calibrator)
            for name, value in values.items():
                if value is None:
                    continue
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    raise ValueError(
                        f"{name} must be a number"
                    )
                if not math.isfinite(value):
                    raise ValueError(
                        f"{name} must be finite"
                    )
                if value <= 0:
                    raise ValueError(
                        f"{name} must be greater than zero"
                    )
                if (
                    name == "min_coverage"
                    and value > 1
                ):
                    raise ValueError(
                        "min_coverage must be at most 1"
                    )
                if (
                    name == "min_edge_margin"
                    and value > 0.5
                ):
                    raise ValueError(
                        "min_edge_margin must be at most 0.5"
                    )
                if (
                    name == "duplicate_distance"
                    and value > 5
                ):
                    raise ValueError(
                        "duplicate_distance must be at most 5"
                    )
                setattr(
                    updated,
                    name,
                    value,
                )
            self.calibrator = updated

    def _clear_detection_state(self):
        with self._detection_state_lock:
            self._last_detection = None
            self._last_detection_at = 0.0
            self.chessboard_detected = False
            self.last_rejection_reason = None

    def _enter_calibrated_mode(self, preview):
        self._auto_capture_before_calibrated = self.auto_capture_enabled
        self.auto_capture_enabled = False
        self.last_auto_capture_at = 0.0
        self._calibration_preview = preview
        self.calibration_preview_enabled = True
        self.workspace_mode = "calibrated"
        self._clear_detection_state()

    def _enter_calibration_mode(self):
        self.workspace_mode = "calibration"
        self.calibration_preview_enabled = False
        self._calibration_preview = None
        self.auto_capture_enabled = self._auto_capture_before_calibrated
        self._clear_detection_state()

    def set_workspace_mode(self, mode):
        mode = str(mode or "").strip().lower()
        if mode not in {"calibration", "calibrated"}:
            raise ValueError("mode must be calibration or calibrated")
        if (
            self._calibration_thread is not None
            and self._calibration_thread.is_alive()
        ):
            raise ValueError(
                "Calibration is running; stop calibration before changing mode."
            )
        if mode == self.workspace_mode:
            return
        if mode == "calibrated":
            if not self.output_file.exists():
                raise ValueError("No calibration model exists yet.")
            preview = CameraCalibration(
                self.output_file,
                enabled=True,
            )
            if not preview.enabled:
                raise ValueError(
                    preview.last_error
                    or "Calibration model is not usable."
                )
            self._enter_calibrated_mode(preview)
        else:
            self._enter_calibration_mode()

    def set_calibration_preview(self, enabled):
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be boolean")
        self.set_workspace_mode(
            "calibrated" if enabled else "calibration"
        )

    def capture(self):
        if self.workspace_mode != "calibration":
            return (
                False,
                "Switch to calibration mode before capturing views.",
            )
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
                return (
                    False,
                    "No raw camera frame is available.",
                )

            with self._calibrator_lock:
                fresh = self.calibrator.evaluate_frame(
                    raw
                )
                reason = self.calibrator.quality_reason(
                    fresh
                )
                fresh["quality_valid"] = reason is None
                fresh["quality_reason"] = reason
                return self._save_evaluated_frame(
                    raw,
                    fresh,
                )

    def _run_calibration(self):
        with self._operation_lock:
            self._calibration_cancel.clear()
            self._enter_calibration_mode()
            self._calibration_state = "calibrating"
            self._last_calibration_message = (
                "Calibration is running against the accepted captures."
            )
            try:
                with self._calibrator_lock:
                    result = self.calibrator.calibrate_from_directory(
                        self.image_dir,
                        self.output_file,
                        metadata_loader=(
                            self.image_store.load_metadata
                        ),
                        cancel_event=self._calibration_cancel,
                    )

                self._last_calibration = result

                if result.get(
                    "acceptable_for_runtime",
                    True,
                ):
                    self._calibration_state = "calibrated"
                    self._last_calibration_message = (
                        f"Calibration completed with "
                        f"{result['valid_images']} accepted views. "
                        f"RMS {result['rms']:.4f}px; mean "
                        f"reprojection "
                        f"{result['mean_reprojection_error']:.4f}px."
                    )
                else:
                    self._calibration_state = "quality_failed"
                    reasons = result.get(
                        "quality_reasons"
                    ) or [
                        "Calibration failed its quality gate."
                    ]
                    self._last_calibration_message = " ".join(
                        reasons
                    )

                self._enter_calibrated_mode(
                    CameraCalibration(self.output_file, enabled=True)
                )
                logger.info(
                    "Calibration complete: valid=%d rms=%.6f "
                    "reprojection=%.6f quality=%s",
                    result["valid_images"],
                    result["rms"],
                    result["mean_reprojection_error"],
                    result.get(
                        "quality_status",
                        "unknown",
                    ),
                )
            except Exception as exc:
                logger.exception(
                    "Camera calibration failed"
                )
                self._calibration_state = "failed"
                self._last_calibration_message = str(exc)

    def start_calibration(self):
        with self._operation_lock:
            if self.workspace_mode != "calibration":
                return (
                    False,
                    "Switch to calibration mode before running calibration.",
                )
            if (
                self._calibration_thread is not None
                and self._calibration_thread.is_alive()
            ):
                return (
                    False,
                    "Calibration is already running.",
                )

            self._calibration_cancel.clear()
            self._calibration_thread = threading.Thread(
                target=self._run_calibration,
                daemon=True,
                name="camera-calibration",
            )
            self._calibration_thread.start()
            return True, "Calibration started."

    def cancel_calibration(self):
        thread = self._calibration_thread
        if thread is None or not thread.is_alive():
            return False, "Calibration is not running."
        self._calibration_cancel.set()
        self._last_calibration_message = "Calibration cancellation requested."
        return True, "Calibration cancellation requested."

    def status(self):
        result = self._last_calibration or {}

        with self._calibrator_lock:
            calibrator = self.calibrator
            checkerboard = list(
                calibrator.checkerboard
            )
            square_size = calibrator.square_size
            detector_mode = calibrator.detector_mode
            min_coverage = calibrator.min_coverage
            min_sharpness = calibrator.min_sharpness
            min_edge_margin = calibrator.min_edge_margin
            duplicate_distance = (
                calibrator.duplicate_distance
            )
            max_mean_reprojection_error = (
                calibrator.max_mean_reprojection_error
            )
            max_view_reprojection_error = (
                calibrator.max_view_reprojection_error
            )

        with self._detection_state_lock:
            evaluation = self._last_detection
            detection_count = self._detection_count
            last_detection_at = self._last_detection_at
            detection_duration_ms = self._last_detection_duration_ms
            chessboard_detected = self.chessboard_detected
            last_rejection_reason = self.last_rejection_reason

        detection_state = (
            self._detection_state(evaluation)
            if self.workspace_mode == "calibration"
            else "DETECTOR_DISABLED"
        )

        if self.workspace_mode != "calibration":
            detection_message = (
                "Detector and auto-capture are disabled in calibrated mode."
            )
        elif evaluation:
            if detection_state == "READY_FOR_CAPTURE":
                detection_message = (
                    "Board detected and quality checks passed."
                )
            elif detection_state == "DETECTED_BUT_REJECTED":
                detection_message = (
                    evaluation.get("quality_reason")
                    or "Detected, but quality checks rejected this frame."
                )
            else:
                detection_message = (
                    evaluation.get("quality_reason")
                    or "Chessboard was not detected."
                )
        elif self._last_camera_error:
            detection_message = self._last_camera_error
        else:
            detection_message = (
                "Waiting for the first camera frame."
            )

        return {
            "workspace_mode": self.workspace_mode,
            "detector_enabled": self.workspace_mode == "calibration",
            "calibration_model_available": self.output_file.exists(),
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
            "detection_fps": (
                1.0 / self.detection_interval
                if self.detection_interval > 0
                else None
            ),
            "detection_interval": self.detection_interval,
            "detection_count": detection_count,
            "detection_duration_ms": detection_duration_ms,
            "detection_age_ms": (
                round(
                    max(
                        0.0,
                        time.monotonic()
                        - last_detection_at,
                    )
                    * 1000.0,
                    1,
                )
                if last_detection_at
                else None
            ),
            "detection_state": detection_state,
            "detection_message": detection_message,
            "chessboard_detected": chessboard_detected,
            "capture_eligible": (
                detection_state
                == "READY_FOR_CAPTURE"
            ),
            "last_rejection_reason": last_rejection_reason,
            "last_camera_error": self._last_camera_error,
            "camera_fps_limits": (
                self.camera.get_frame_rate_limits()
                if hasattr(
                    self.camera,
                    "get_frame_rate_limits",
                )
                else None
            ),
            "image_size": [
                int(
                    getattr(
                        self.config,
                        "CAM_WIDTH",
                        0,
                    )
                ),
                int(
                    getattr(
                        self.config,
                        "CAM_HEIGHT",
                        0,
                    )
                ),
            ],
            "checkerboard": checkerboard,
            "checkerboard_inner_corners": checkerboard,
            "board_squares": list(
                self.board_squares
            ),
            "square_size": square_size,
            "min_valid_images": self.min_valid_images,
            "detector_mode": detector_mode,
            "detector": (
                evaluation.get("detector")
                if evaluation
                else None
            ),
            "detection_view": (
                evaluation.get("detection_view")
                if evaluation
                else None
            ),
            "min_coverage": min_coverage,
            "min_sharpness": min_sharpness,
            "min_edge_margin": min_edge_margin,
            "duplicate_distance": duplicate_distance,
            "max_mean_reprojection_error": (
                self.calibrator.max_mean_reprojection_error
            ),
            "max_view_reprojection_error": (
                self.calibrator.max_view_reprojection_error
            ),
            "auto_capture_enabled": (
                self.auto_capture_enabled
            ),
            "auto_capture_interval": (
                self.auto_capture_interval
            ),
            "auto_captured_images": (
                self.auto_captured_images
            ),
            "calibration_preview_enabled": (
                self.calibration_preview_enabled
            ),
            "captured_images": self.image_store.count(),
            "diversity": self._diversity_summary(),
            "network_addresses": discover_network_addresses(),
            "calibration_state": self._calibration_state,
            "last_calibration_message": (
                self._last_calibration_message
            ),
            "last_calibration_error": result.get("rms"),
            "rms": result.get("rms"),
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
            "quality_reasons": result.get(
                "quality_reasons",
                [],
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
                headers={
                    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                    "Pragma": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )

        @app.get("/api/debug_frame")
        def api_debug_frame():
            view = request.args.get(
                "view",
                "detector",
            )
            threshold = request.args.get("threshold", "128")
            adaptive_block = request.args.get("adaptive_block", "21")
            adaptive_c = request.args.get("adaptive_c", "5")

            try:
                frame = self.debug_frame(
                    view=view,
                    threshold=threshold,
                    adaptive_block=adaptive_block,
                    adaptive_c=adaptive_c,
                )
            except ValueError as exc:
                return jsonify(
                    success=False,
                    message=str(exc),
                ), 400

            if frame is None:
                return Response(status=204)

            ok, encoded = cv2.imencode(
                ".jpg",
                frame,
                [
                    cv2.IMWRITE_JPEG_QUALITY,
                    90,
                ],
            )
            if not ok:
                return Response(status=204)

            return Response(
                encoded.tobytes(),
                mimetype="image/jpeg",
                headers={"Cache-Control": "no-store"},
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
                    "detector_mode",
                    "min_coverage",
                    "min_sharpness",
                    "min_edge_margin",
                    "duplicate_distance",
                    "max_mean_reprojection_error",
                    "max_view_reprojection_error",
                    "auto_capture_enabled",
                    "auto_capture_interval",
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

                if "detector_mode" in data:
                    self.set_detector_mode(data["detector_mode"])

                quality_keys = {
                    "min_coverage",
                    "min_sharpness",
                    "min_edge_margin",
                    "duplicate_distance",
                    "max_mean_reprojection_error",
                    "max_view_reprojection_error",
                }
                if quality_keys.intersection(data):
                    self.set_quality_settings(
                        min_coverage=data.get("min_coverage"),
                        min_sharpness=data.get("min_sharpness"),
                        min_edge_margin=data.get("min_edge_margin"),
                        duplicate_distance=data.get("duplicate_distance"),
                        max_mean_reprojection_error=data.get(
                            "max_mean_reprojection_error"
                        ),
                        max_view_reprojection_error=data.get(
                            "max_view_reprojection_error"
                        ),
                    )

                if (
                    "auto_capture_enabled" in data
                    or "auto_capture_interval" in data
                ):
                    self.set_auto_capture(
                        data.get(
                            "auto_capture_enabled",
                            self.auto_capture_enabled,
                        ),
                        data.get(
                            "auto_capture_interval",
                            self.auto_capture_interval,
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
                    detector_mode=self.calibrator.detector_mode,
                    min_coverage=self.calibrator.min_coverage,
                    min_sharpness=self.calibrator.min_sharpness,
                    min_edge_margin=self.calibrator.min_edge_margin,
                    duplicate_distance=self.calibrator.duplicate_distance,
                    max_mean_reprojection_error=(
                        self.calibrator.max_mean_reprojection_error
                    ),
                    max_view_reprojection_error=(
                        self.calibrator.max_view_reprojection_error
                    ),
                    auto_capture_enabled=self.auto_capture_enabled,
                    auto_capture_interval=self.auto_capture_interval,
                    diversity=self._diversity_summary(),
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
                    code=(
                        "CALIBRATION_RUNNING"
                        if "Calibration is running" in str(exc)
                        else "CAPTURES_EXIST"
                        if "Clear captured calibration images" in str(exc)
                        else "INVALID_SETTINGS"
                    ),
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

        @app.get("/api/captures")
        def api_captures():
            files = self.image_store.paths()
            return jsonify(
                captures=[
                    {
                        "filename": path.name,
                        "url": f"/api/captures/{path.name}",
                    }
                    for path in reversed(files)
                ]
            )

        @app.get("/api/captures/<path:filename>")
        def capture_file(filename):
            return send_from_directory(
                self.image_dir,
                filename,
            )

        @app.post("/api/preview")
        def api_preview():
            try:
                data = request.get_json(silent=True) or {}
                value = data.get("enabled", False)
                if not isinstance(value, bool):
                    return jsonify(
                        success=False,
                        message="enabled must be boolean",
                    ), 400
                self.set_calibration_preview(value)
                return jsonify(
                    success=True,
                    enabled=self.calibration_preview_enabled,
                )
            except (TypeError, ValueError) as exc:
                return jsonify(
                    success=False,
                    message=str(exc),
                ), 409
            except Exception:
                logger.exception("Failed to toggle calibration preview")
                return jsonify(
                    success=False,
                    message="Failed to toggle calibration preview",
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
                self.last_auto_capture_at = 0.0
                self.auto_captured_images = 0
                self._last_calibration = None
                self._last_calibration_message = None
                self._calibration_state = "not calibrated"

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
        default=20.0,
        help="Physical chessboard square size.",
    )
    parser.add_argument(
        "--checkerboard-cols",
        type=int,
        default=7,
    )
    parser.add_argument(
        "--checkerboard-rows",
        type=int,
        default=9,
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
