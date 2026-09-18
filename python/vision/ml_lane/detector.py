import logging
import math
import time
from pathlib import Path

import cv2
import numpy as np

from .registry import get_model_spec, resolve_model_path


logger = logging.getLogger(__name__)


class MLLaneDetector:
    def __init__(self, model_name, model_root=None, cpu_threads=4):
        self.spec = get_model_spec(model_name)
        self.model_name = model_name
        self.model_root = Path(model_root) if model_root else Path(__file__).resolve().parents[2] / "models" / "lane"
        self.model_path = self._resolve_path()
        if not self.model_path.exists():
            raise FileNotFoundError(
                f"Lane model '{model_name}' is not installed: {self.model_path}. "
                f"Run: python python/tools/download_lane_models.py --model {model_name}"
            )

        self.net = cv2.dnn.readNetFromONNX(str(self.model_path))
        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        self.cpu_threads = max(1, int(cpu_threads))
        try:
            cv2.setNumThreads(self.cpu_threads)
        except Exception:
            logger.debug("OpenCV thread count could not be configured", exc_info=True)

        self.input_name = None
        self.output_names = self.net.getUnconnectedOutLayersNames()

    def _resolve_path(self):
        if self.spec.model_path is not None:
            return self.model_root / self.spec.model_path
        return resolve_model_path(self.model_name)

    def info(self):
        return {
            "name": self.spec.name,
            "title": self.spec.title,
            "format": self.spec.format,
            "input": [self.spec.input_height, self.spec.input_width],
            "dataset": self.spec.dataset,
            "license": self.spec.license,
            "params": self.spec.params,
            "model_path": str(self.model_path),
        }

    @staticmethod
    def _softmax(x, axis=0):
        x = x - np.max(x, axis=axis, keepdims=True)
        exp_x = np.exp(x)
        return exp_x / np.sum(exp_x, axis=axis, keepdims=True)

    @staticmethod
    def _lane_center_from_mask(mask):
        binary = mask > 0.45
        h, w = binary.shape
        y0 = int(h * 0.55)
        band = binary[y0:]
        if not np.any(band):
            return None, "none"

        histogram = band.sum(axis=0).astype(np.float32)
        threshold = max(1.0, histogram.max() * 0.20)
        active = np.flatnonzero(histogram >= threshold)
        if active.size == 0:
            return None, "none"

        groups = []
        start = prev = int(active[0])
        for value in active[1:]:
            value = int(value)
            if value > prev + 6:
                groups.append((start, prev))
                start = value
            prev = value
        groups.append((start, prev))

        centers = [(a + b) / 2.0 for a, b in groups if b - a + 1 >= 2]
        if len(centers) >= 2:
            left, right = centers[0], centers[-1]
            return (left + right) / 2.0, "both"

        return centers[0], "only_left" if centers[0] < w / 2 else "only_right"

    def _predict_unet(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(
            rgb,
            (self.spec.input_width, self.spec.input_height),
            interpolation=cv2.INTER_AREA,
        )
        blob = resized.astype(np.float32) / 255.0
        blob = np.transpose(blob, (2, 0, 1))[None, ...]
        self.net.setInput(blob)
        raw = self.net.forward()
        output = np.squeeze(raw).astype(np.float32)

        if output.ndim == 3:
            output = output[0]
        if output.ndim != 2:
            raise RuntimeError(f"Unexpected UNet output shape: {raw.shape}")

        if float(output.max()) > 1.0 or float(output.min()) < 0.0:
            output = 1.0 / (1.0 + np.exp(-np.clip(output, -30.0, 30.0)))

        mask = cv2.resize(
            output,
            (frame.shape[1], frame.shape[0]),
            interpolation=cv2.INTER_LINEAR,
        )
        center_x, lane_type = self._lane_center_from_mask(mask)
        return mask, center_x, lane_type, {"lanes": []}

    def _decode_ufld(self, raw, frame):
        output = np.squeeze(raw).astype(np.float32)
        if output.ndim != 3 or output.shape[2] != 4:
            raise RuntimeError(f"Unexpected UFLD output shape: {raw.shape}")

        output = output[:, ::-1, :]
        griding_num = output.shape[0]
        rows = output.shape[1]
        lanes = output.shape[2]

        prob = self._softmax(output[:-1], axis=0)
        idx = np.arange(griding_num, dtype=np.float32) + 1.0
        loc = np.sum(prob * idx[:, None, None], axis=0)
        hard = np.argmax(output, axis=0)
        loc[hard == griding_num] = 0

        row_anchor = [
            121, 131, 141, 150, 160, 170, 180, 189, 199,
            209, 219, 228, 238, 248, 258, 267, 277, 287
        ]

        lane_points = []
        detected = []
        col_sample_w = (800.0 - 1.0) / (griding_num - 1)

        for lane_idx in range(lanes):
            points = []
            if np.sum(loc[:, lane_idx] != 0) > 2:
                detected.append(True)
                for point_idx in range(rows):
                    value = loc[point_idx, lane_idx]
                    if value > 0:
                        x = int(value * col_sample_w * 1640.0 / 800.0) - 1
                        y = int(590.0 * row_anchor[rows - 1 - point_idx] / 288.0) - 1
                        points.append((x, y))
            else:
                detected.append(False)
            lane_points.append(points)

        sx = frame.shape[1] / 1640.0
        sy = frame.shape[0] / 590.0
        scaled = [
            [(int(x * sx), int(y * sy)) for x, y in points]
            for points in lane_points
        ]

        candidates = []
        for idx in (1, 2):
            if detected[idx] and scaled[idx]:
                points = scaled[idx]
                near_bottom = max(points, key=lambda p: p[1])
                candidates.append(near_bottom[0])

        if len(candidates) >= 2:
            center_x = sum(candidates[:2]) / 2.0
            lane_type = "both"
        elif len(candidates) == 1:
            center_x = candidates[0]
            lane_type = "only_left" if candidates[0] < frame.shape[1] / 2 else "only_right"
        else:
            center_x = None
            lane_type = "none"

        return None, center_x, lane_type, {"lanes": scaled}

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

        if self.model_name.startswith("unet_depthwise_"):
            mask, center_x, lane_type, meta = self._predict_unet(frame)
        elif self.model_name == "ufld_culane_resnet18":
            self.net.setInput(
                self._prepare_ufld(frame)
            )
            raw = self.net.forward()
            mask, center_x, lane_type, meta = self._decode_ufld(raw, frame)
        else:
            raise ValueError(f"No detector implementation for {self.model_name}")

        width = frame.shape[1]
        frame_center = width / 2.0
        if center_x is None:
            error = 0.0
            lane_type = "none"
        else:
            error = frame_center - center_x

        steering_angle = int(np.clip(90.0 - 0.45 * error, 30.0, 150.0))

        vis = (debug_frame.copy() if debug_frame is not None else frame.copy())
        if mask is not None:
            mask_u8 = np.uint8(np.clip(mask, 0.0, 1.0) * 255.0)
            _, mask_bin = cv2.threshold(mask_u8, 100, 255, cv2.THRESH_BINARY)
            contours, _ = cv2.findContours(mask_bin, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(vis, contours, -1, (0, 255, 0), 2)
        for lane in meta.get("lanes", []):
            for x, y in lane:
                cv2.circle(vis, (x, y), 2, (0, 255, 255), -1)

        cv2.line(vis, (int(frame_center), 0), (int(frame_center), vis.shape[0]), (0, 0, 255), 1)
        if center_x is not None:
            cv2.line(vis, (int(center_x), 0), (int(center_x), vis.shape[0]), (255, 0, 255), 1)

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
        }

    def _prepare_ufld(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(
            rgb,
            (self.spec.input_width, self.spec.input_height),
            interpolation=cv2.INTER_LINEAR,
        ).astype(np.float32)
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        normalized = (resized / 255.0 - mean) / std
        return np.transpose(normalized, (2, 0, 1))[None, ...]

def create_ml_lane_detector(config):
    enabled = bool(getattr(config, "USE_ML_LANE_DETECTOR", False))
    if not enabled:
        return None
    model_name = getattr(config, "ML_LANE_MODEL", "unet_depthwise_nano")
    threads = int(getattr(config, "ML_LANE_CPU_THREADS", 4))
    return MLLaneDetector(model_name, cpu_threads=threads)
