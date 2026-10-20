import logging
import time
from pathlib import Path

import cv2
import numpy as np

from .bundled import ensure_model_materialized
from .registry import get_model_spec


logger = logging.getLogger(__name__)


class MLLaneDetector:
    def __init__(self, model_name, model_root=None, cpu_threads=4, servo_center=95, servo_min=55, servo_max=125):
        self.spec = get_model_spec(model_name)
        self.model_name = model_name
        self.servo_center = float(servo_center)
        self.servo_min = float(servo_min)
        self.servo_max = float(servo_max)
        self.last_steering = self.servo_center
        self.model_root = Path(model_root) if model_root else Path(__file__).resolve().parents[2] / "models" / "lane"
        try:
            import ncnn
        except ImportError as exc:
            raise RuntimeError(
                "NCNN Python runtime is required for ML lane detection. "
                "Install the project dependencies in this environment with: "
                "python3 -m pip install -r requirements.txt"
            ) from exc

        self.ncnn = ncnn
        # Check the runtime dependency before downloading model files. On
        # systems without NCNN, fail quickly and leave the model directory
        # untouched.
        self.param_path, self.bin_path = ensure_model_materialized(model_name)
        self.net = ncnn.Net()
        self.net.opt.use_vulkan_compute = False
        self.net.opt.num_threads = max(1, int(cpu_threads))

        ret = self.net.load_param(str(self.param_path))
        if ret != 0:
            raise RuntimeError(f"Failed to load NCNN param: {self.param_path} (code {ret})")
        ret = self.net.load_model(str(self.bin_path))
        if ret != 0:
            raise RuntimeError(f"Failed to load NCNN weights: {self.bin_path} (code {ret})")

        self.input_blob = "in0"
        self.output_blob = "out0"

    def info(self):
        return {
            "name": self.spec.name,
            "title": self.spec.title,
            "runtime": "ncnn",
            "input": [self.spec.input_height, self.spec.input_width],
            "dataset": self.spec.dataset,
            "license": self.spec.license,
            "params": self.spec.params,
            "param_path": str(self.param_path),
            "bin_path": str(self.bin_path),
        }

    @staticmethod
    def _lane_center_from_mask(mask):
        binary = mask > 0.45
        h, w = binary.shape
        band = binary[int(h * 0.55):]

        if not np.any(band):
            return None, "none"

        histogram = band.sum(axis=0).astype(np.float32)
        threshold = max(1.0, histogram.max() * 0.20)
        active = np.flatnonzero(histogram >= threshold)
        if active.size == 0:
            return None, "none"

        groups = []
        start = previous = int(active[0])
        for value in active[1:]:
            value = int(value)
            if value > previous + 6:
                groups.append((start, previous))
                start = value
            previous = value
        groups.append((start, previous))

        centers = [
            (left + right) / 2.0
            for left, right in groups
            if right - left + 1 >= 2
        ]

        if len(centers) >= 2:
            left, right = centers[0], centers[-1]
            return (left + right) / 2.0, "both"

        center = centers[0]
        return center, "only_left" if center < w / 2 else "only_right"

    def _predict_unet(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(
            rgb,
            (self.spec.input_width, self.spec.input_height),
            interpolation=cv2.INTER_AREA,
        )
        chw = np.transpose(resized.astype(np.float32) / 255.0, (2, 0, 1))

        mat = self.ncnn.Mat(chw)
        extractor = self.net.create_extractor()

        inference_started = time.monotonic()
        ret = extractor.input(self.input_blob, mat)
        if ret != 0:
            raise RuntimeError(f"NCNN input failed with code {ret}")

        ret, output = extractor.extract(self.output_blob)
        if ret != 0:
            raise RuntimeError(f"NCNN extraction failed with code {ret}")
        inference_ms = (time.monotonic() - inference_started) * 1000.0

        result = np.array(output, copy=True).astype(np.float32)
        result = np.squeeze(result)
        if result.ndim != 2:
            raise RuntimeError(f"Unexpected NCNN output shape: {result.shape}")

        if result.size == 0:
            return (
                np.zeros((frame.shape[0], frame.shape[1]), dtype=np.float32),
                None,
                "none",
                {},
                inference_ms,
            )

        if float(result.min()) < 0.0 or float(result.max()) > 1.0:
            result = 1.0 / (1.0 + np.exp(-np.clip(result, -30.0, 30.0)))

        lane_mask = 1.0 - result

        lane_mask = cv2.resize(
            lane_mask,
            (frame.shape[1], frame.shape[0]),
            interpolation=cv2.INTER_LINEAR,
        )
        center_x, lane_type = self._lane_center_from_mask(lane_mask)
        return lane_mask, center_x, lane_type, {"lanes": []}, inference_ms

    def detect(self, frame, debug_frame=None):
        started = time.monotonic()

        if frame is None or frame.size == 0:
            return {
                "steering_angle": int(self.last_steering),
                "error": 0,
                "lane_type": "none",
                "perception_valid": False,
                "debug": None,
                "kp": 0,
            }

        mask, center_x, lane_type, meta, inference_ms = self._predict_unet(frame)

        width = frame.shape[1]
        frame_center = width / 2.0

        if center_x is None:
            error = 0.0
            lane_type = "none"
            steering_angle = int(self.last_steering)
        else:
            error = frame_center - center_x
            steering_angle = int(np.clip(self.servo_center - 0.45 * error, self.servo_min, self.servo_max))
            self.last_steering = float(steering_angle)

        debug = None
        if debug_frame is not None:
            debug = {
                "combined": debug_frame.copy(),
                "draw_data": {
                    "kind": "ml",
                    "frame_width": int(width),
                    "frame_height": int(frame.shape[0]),
                    "mask": mask,
                    "center_x": center_x,
                },
            }

        elapsed_ms = (time.monotonic() - started) * 1000.0
        return {
            "steering_angle": steering_angle,
            "error": error,
            "lane_type": lane_type,
            "perception_valid": center_x is not None,
            "debug": debug,
            "kp": 0.45,
            "ml_model": self.model_name,
            "ml_latency_ms": elapsed_ms,
            "ml_inference_ms": inference_ms,
            # Output is a thresholded lane mask; this occupancy measure is
            # detector evidence, not a calibrated probability.
            "perception_quality": float(np.clip(np.count_nonzero(mask > 0.45) / max(1, mask.size), 0.0, 1.0)) if mask is not None else 0.0,
            "observed_lane_boundaries": 2 if lane_type == "both" else 1 if lane_type in ("only_left", "only_right") else 0,
        }


def create_ml_lane_detector(config):
    enabled = bool(getattr(config, "USE_ML_LANE_DETECTOR", False))
    if not enabled:
        return None

    model_name = getattr(config, "ML_LANE_MODEL", "unet_depthwise_nano")
    threads = int(getattr(config, "ML_LANE_CPU_THREADS", 4))
    return MLLaneDetector(
        model_name,
        cpu_threads=threads,
        servo_center=float(getattr(config, "SERVO_CENTER", 95)),
        servo_min=float(getattr(config, "MIN_SERVO_ANGLE", 55)),
        servo_max=float(getattr(config, "MAX_SERVO_ANGLE", 125)),
    )
