import logging
import time
from pathlib import Path

import cv2
import numpy as np

from .bundled import ensure_model_materialized
from .registry import get_model_spec


logger = logging.getLogger(__name__)


class MLLaneDetector:
    def __init__(self, model_name, model_root=None, cpu_threads=4):
        self.spec = get_model_spec(model_name)
        self.model_name = model_name
        self.model_root = Path(model_root) if model_root else Path(__file__).resolve().parents[2] / "models" / "lane"
        self.param_path, self.bin_path = ensure_model_materialized(model_name)

        try:
            import ncnn
        except ImportError as exc:
            raise RuntimeError(
                "NCNN Python runtime is required for ML lane detection. "
                "Install it with: pip install ncnn"
            ) from exc

        self.ncnn = ncnn
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
                "steering_angle": 90,
                "error": 0,
                "lane_type": "none",
                "perception_valid": False,
                "debug": {"combined": None},
                "kp": 0,
            }

        mask, center_x, lane_type, meta, inference_ms = self._predict_unet(frame)

        width = frame.shape[1]
        frame_center = width / 2.0

        if center_x is None:
            error = 0.0
            lane_type = "none"
        else:
            error = frame_center - center_x

        steering_angle = int(np.clip(90.0 - 0.45 * error, 30.0, 150.0))

        vis = frame.copy()
        if mask is not None:
            mask_u8 = np.uint8(np.clip(mask, 0.0, 1.0) * 255.0)
            _, mask_bin = cv2.threshold(mask_u8, 100, 255, cv2.THRESH_BINARY)
            contours, _ = cv2.findContours(
                mask_bin,
                cv2.RETR_EXTERNAL,
                cv2.CHAIN_APPROX_SIMPLE,
            )
            cv2.drawContours(vis, contours, -1, (0, 255, 0), 2)

        cv2.line(
            vis,
            (int(frame_center), 0),
            (int(frame_center), vis.shape[0]),
            (0, 0, 255),
            1,
        )

        if center_x is not None:
            cv2.line(
                vis,
                (int(center_x), 0),
                (int(center_x), vis.shape[0]),
                (255, 0, 255),
                1,
            )

        if debug_frame is not None and debug_frame.shape[:2] != vis.shape[:2]:
            vis = cv2.resize(
                vis,
                (debug_frame.shape[1], debug_frame.shape[0]),
                interpolation=cv2.INTER_LINEAR,
            )

        elapsed_ms = (time.monotonic() - started) * 1000.0
        return {
            "steering_angle": steering_angle,
            "error": error,
            "lane_type": lane_type,
            "perception_valid": center_x is not None,
            "debug": {"combined": vis},
            "kp": 0.45,
            "ml_model": self.model_name,
            "ml_latency_ms": elapsed_ms,
            "ml_inference_ms": inference_ms,
        }


def create_ml_lane_detector(config):
    enabled = bool(getattr(config, "USE_ML_LANE_DETECTOR", False))
    if not enabled:
        return None

    model_name = getattr(config, "ML_LANE_MODEL", "unet_depthwise_nano")
    threads = int(getattr(config, "ML_LANE_CPU_THREADS", 4))
    return MLLaneDetector(model_name, cpu_threads=threads)
