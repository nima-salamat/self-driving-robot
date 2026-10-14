"""Heuristic, detector-agnostic confidence estimate from existing frame output."""

import math
import time
from collections import deque


class PerceptionConfidenceEstimator:
    def __init__(self, history_size=8, max_frame_age_s=0.25):
        self._history = deque(maxlen=max(2, int(history_size)))
        self.max_frame_age_s = float(max_frame_age_s)
        self._last_token = None
        self._last_time = None

    def evaluate(self, result, *, frame_valid=True, frame_at=None, now=None,
                 observation_token=None):
        now = time.monotonic() if now is None else float(now)
        frame_at = now if frame_at is None else float(frame_at)
        age = max(0.0, now - frame_at)
        lane_type = result.get("lane_type")
        reasons, unavailable, factors = [], [], {}
        fresh = age <= self.max_frame_age_s
        if not frame_valid:
            reasons.append("camera capture invalid")
        if not fresh:
            reasons.append("camera frame stale")
        if lane_type not in {"both", "only_left", "only_right"}:
            reasons.append("lane geometry unavailable")
            unavailable.append("lane boundary geometry")
        score = 1.0
        score *= 1.0 if frame_valid else 0.0
        score *= max(0.0, 1.0 - max(0.0, age - self.max_frame_age_s) / max(self.max_frame_age_s, 1e-6))
        if lane_type == "both":
            factors["observed_boundaries"] = "both"
        elif lane_type in {"only_left", "only_right"}:
            score *= 0.68
            factors["observed_boundaries"] = "one"
            reasons.append("only one lane boundary observed")
        else:
            score = 0.0
        if not bool(result.get("perception_valid", False)):
            score = 0.0
            reasons.append("detector marks perception invalid")
        # Detector-specific measurable evidence is consumed only when supplied.
        quality = result.get("perception_quality")
        if isinstance(quality, (float, int)) and math.isfinite(float(quality)):
            quality = max(0.0, min(1.0, float(quality)))
            factors["detector_quality"] = quality
            score *= 0.5 + 0.5 * quality
        else:
            unavailable.append("detector quality (not exposed by selected detector)")
        token = observation_token if observation_token is not None else frame_at
        distinct = token != self._last_token
        error = result.get("error")
        if distinct and bool(frame_valid) and fresh and bool(result.get("perception_valid", False)):
            if isinstance(error, (float, int)) and math.isfinite(float(error)):
                if self._history:
                    jump = abs(float(error) - self._history[-1][1])
                    factors["lane_error_jump"] = jump
                    if jump > 75.0:
                        score *= 0.45
                        reasons.append("large lane-error change between fresh frames")
                    elif jump > 35.0:
                        score *= 0.75
                        reasons.append("lane-error change between fresh frames")
                self._history.append((token, float(error)))
            self._last_token, self._last_time = token, now
        else:
            unavailable.append("temporal consistency (no distinct fresh observation)")
        score = max(0.0, min(1.0, score))
        valid = bool(frame_valid and fresh and result.get("perception_valid", False))
        return {"score": score, "valid": valid, "fresh": fresh,
                "frame_age_s": age, "lane_type": lane_type,
                "factors": factors, "reasons": reasons,
                "unavailable": unavailable,
                "name": "heuristic confidence estimate"}


class ConfidenceSpeedLimiter:
    """Hysteretic confidence-only speed bound; obstacle/curve limits stay separate."""
    def __init__(self, slow_threshold=0.65, stop_threshold=0.30, recovery_step=10):
        if not 0 <= stop_threshold < slow_threshold <= 1:
            raise ValueError("thresholds must satisfy 0 <= stop < slow <= 1")
        self.slow_threshold = float(slow_threshold)
        self.stop_threshold = float(stop_threshold)
        self.recovery_step = max(1, int(recovery_step))
        self._last_speed = 0
        self._low_confirmations = 0

    def limit(self, configured_speed, estimate):
        configured_speed = int(configured_speed)
        score = float(estimate.get("score", 0.0))
        if not estimate.get("valid"):
            desired, reason = 0, "invalid or stale perception; stop"
            self._low_confirmations += 1
        elif score <= self.stop_threshold:
            self._low_confirmations += 1
            desired, reason = 0, "confidence at/below stop threshold"
        elif score < self.slow_threshold:
            self._low_confirmations += 1
            fraction = (score - self.stop_threshold) / (self.slow_threshold - self.stop_threshold)
            desired = int(abs(configured_speed) * max(0.15, min(0.6, fraction * 0.6)))
            reason = "confidence below slow threshold"
        else:
            self._low_confirmations = 0
            desired, reason = abs(configured_speed), "confidence permits configured mode speed"
        if not hasattr(self, "_initialized"):
            self._initialized = True
        elif desired > self._last_speed and self._last_speed >= 0:
            desired = min(desired, self._last_speed + self.recovery_step)
            if desired < abs(configured_speed):
                reason += "; gradual recovery"
        self._last_speed = desired
        return (desired if configured_speed >= 0 else -desired), reason
