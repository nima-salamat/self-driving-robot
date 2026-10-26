import importlib
import os
import shutil
import socket
import tempfile
import time
from dataclasses import dataclass


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    critical: bool = True


class PreflightReport:
    def __init__(self):
        self.checks = []

    @property
    def ok(self):
        return all(check.ok for check in self.checks if check.critical)

    def add(self, name, ok, detail, critical=True):
        self.checks.append(CheckResult(name, bool(ok), str(detail), critical))

    def format(self):
        lines = ["PRE-FLIGHT DIAGNOSTICS", "=" * 24]
        for check in self.checks:
            status = "PASS" if check.ok else "FAIL"
            severity = "" if check.critical else " (warning)"
            lines.append(f"[{status}] {check.name}{severity}: {check.detail}")
        lines.append("=" * 24)
        lines.append("RESULT: " + ("READY" if self.ok else "NOT READY"))
        return "\n".join(lines)


def _check_import(report, module_name, label=None):
    try:
        importlib.import_module(module_name)
    except Exception as exc:
        report.add(label or module_name, False, f"{type(exc).__name__}: {exc}")
    else:
        report.add(label or module_name, True, "available")


def _check_output_storage(report, config):
    output_dir = os.path.abspath(getattr(config, "OUTPUT_DIR", "output"))
    try:
        os.makedirs(output_dir, exist_ok=True)
        usage = shutil.disk_usage(output_dir)
        minimum_mb = max(0.0, float(getattr(config, "MIN_FREE_DISK_MB", 256)))
        free_mb = usage.free / (1024 * 1024)
        if free_mb < minimum_mb:
            report.add(
                "storage",
                False,
                f"{free_mb:.1f} MiB free; minimum is {minimum_mb:.1f} MiB",
            )
            return
        with tempfile.NamedTemporaryFile(prefix=".preflight-", dir=output_dir, delete=True):
            pass
        report.add(
            "storage",
            True,
            f"{free_mb:.1f} MiB free; output directory writable",
        )
    except Exception as exc:
        report.add("storage", False, f"{type(exc).__name__}: {exc}")


def _check_models(report, config):
    use_sign = bool(
        getattr(config, "USE_SIGN", False)
        or getattr(config, "WITH_SIGN", False)
    )
    if not use_sign:
        report.add(
            "sign model",
            True,
            "not required by current runtime configuration",
            critical=False,
        )
        return

    from base_config import BASE_DIR

    method = str(getattr(config, "SIGN_DETECTOR_METHOD", "yolo")).lower()
    if method == "yolo":
        candidates = [os.path.join(BASE_DIR, "assets", "best416.onnx")]
        label = "YOLO sign model"
    elif method == "svm":
        candidates = [
            os.path.join(BASE_DIR, "assets", "svm_model.xml"),
            os.path.join(BASE_DIR, "rf_model.xml"),
        ]
        label = "SVM sign model"
    else:
        report.add(
            "sign detector configuration",
            False,
            f"unsupported method: {method}",
        )
        return

    existing = next((path for path in candidates if os.path.isfile(path)), None)
    report.add(
        label,
        existing is not None,
        existing if existing is not None else "required model file not found",
    )


def _check_stream_port(report, config):
    if not bool(getattr(config, "STREAM", False)):
        report.add("stream port", True, "stream disabled", critical=False)
        return

    host = str(getattr(config, "STREAM_HOST", "0.0.0.0"))
    port = int(getattr(config, "STREAM_PORT", 5000))
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        report.add("stream port", True, f"{host}:{port} available")
    except OSError as exc:
        report.add("stream port", False, f"{host}:{port} unavailable: {exc}")
    finally:
        sock.close()


def _check_camera(report, config):
    try:
        from vision.camera import Camera

        camera = Camera(config=config)
        try:
            frame, _ = camera.capture_frame(with_resize=False)
            if not camera.last_capture_valid or frame is None:
                report.add(
                    "camera",
                    False,
                    "camera initialized but did not produce a valid frame",
                )
                return

            expected = (
                int(getattr(config, "CAM_HEIGHT", frame.shape[0])),
                int(getattr(config, "CAM_WIDTH", frame.shape[1])),
            )
            actual = tuple(frame.shape[:2])
            if actual != expected:
                report.add(
                    "camera",
                    False,
                    f"frame shape {actual}, expected {expected}",
                )
            else:
                report.add(
                    "camera",
                    True,
                    f"frame {actual[1]}x{actual[0]} received",
                )
        finally:
            camera.release()
    except Exception as exc:
        report.add("camera", False, f"{type(exc).__name__}: {exc}")


def _check_arduino(report, config):
    if bool(getattr(config, "WITHOUT_ARDUINO", False)):
        report.add(
            "Arduino",
            True,
            "disabled by --without-arduino",
            critical=False,
        )
        return

    port = str(getattr(config, "SERIAL_PORT", "/dev/ttyUSB0"))
    try:
        import serial

        connection = serial.Serial(
            port,
            int(getattr(config, "BAUD_RATE", 115200)),
            timeout=min(float(getattr(config, "SERIAL_TIMEOUT", 0.1)), 0.5),
        )
        connection.close()
        report.add("Arduino", True, f"serial port {port} opened successfully")
    except Exception as exc:
        report.add("Arduino", False, f"{type(exc).__name__}: {exc}")


def _check_simulator_endpoint(report, config):
    backend = str(getattr(config, "SIMULATOR_BACKEND", "")).lower()
    module_name = "carla" if backend == "carla" else "avisengine"
    _check_import(report, module_name, label=backend.upper() + " Python API")
    host = str(getattr(config, "SIMULATOR_HOST", "127.0.0.1"))
    port = int(getattr(config, "SIMULATOR_PORT", 2000 if backend == "carla" else 25001))
    timeout = min(2.0, max(0.1, float(getattr(config, "SIMULATOR_TIMEOUT_S", 5.0))))
    try:
        with socket.create_connection((host, port), timeout=timeout):
            report.add(backend.upper() + " server", True, f"{host}:{port} accepts TCP connections")
    except OSError as exc:
        report.add(backend.upper() + " server", False, f"{host}:{port} not reachable: {exc}")


def run_preflight(config):
    report = PreflightReport()
    monotonic_before, wall_before = time.monotonic(), time.time()
    monotonic_after, wall_after = time.monotonic(), time.time()
    report.add(
        "system clock",
        monotonic_after > monotonic_before and wall_after >= wall_before,
        "wall clock and monotonic clock are advancing",
    )

    mode = str(getattr(config, "MODE", "city")).lower()
    try:
        from modes.registry import SIMULATOR_MODES
    except Exception:
        SIMULATOR_MODES = frozenset()
    simulation = mode in SIMULATOR_MODES
    dependencies = ["numpy", "cv2", "flask"]
    if not simulation:
        dependencies.append("serial")
        if (bool(getattr(config, "USE_SIGN", False)) and
                str(getattr(config, "SIGN_DETECTOR_METHOD", "yolo")).lower() == "yolo"):
            dependencies.append("onnxruntime")
    if bool(getattr(config, "USE_ML_LANE_DETECTOR", False)):
        dependencies.append("ncnn")
    for module_name in dependencies:
        _check_import(report, module_name,
                      label="NCNN ML lane runtime" if module_name == "ncnn" else module_name)

    _check_output_storage(report, config)
    if simulation:
        _check_simulator_endpoint(report, config)
        report.add("camera source", True, "frames are provided by the selected simulator adapter")
        report.add("Arduino / motor / encoder", True,
                   "physical hardware not required; virtual actuator and motion-derived encoder are used",
                   critical=False)
    else:
        _check_models(report, config)
        _check_camera(report, config)
        _check_arduino(report, config)
    _check_stream_port(report, config)
    return report
