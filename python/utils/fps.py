import logging
import time


logger = logging.getLogger(__name__)


class FPS:
    def __init__(self, config=None):
        self.config = config
        self.metrics = getattr(config, "runtime_metrics", None) if config is not None else None
        self._start_time = None
        self._num_frames = 0
        self.avg_fps = 0
        self.instant_fps = 0
        self.second_fps = 0
        self._last_frame_time = None
        self._last_period_time = None
        self._sec_start = None
        self._sec_frames = 0
        self._last_performance_log = None

    def start(self):
        now = time.monotonic()
        self._start_time = now
        self._last_frame_time = now
        self._last_period_time = None
        self._sec_start = now
        return self

    def update(self):
        now = time.monotonic()

        if self._last_period_time is not None and self.metrics is not None:
            self.metrics.record_loop((now - self._last_period_time) * 1000.0)
        self._last_period_time = now

        dt = now - self._last_frame_time
        if dt > 0:
            self.instant_fps = 1.0 / dt
        self._last_frame_time = now

        self._num_frames += 1
        elapsed = now - self._start_time
        if elapsed > 0:
            self.avg_fps = self._num_frames / elapsed

        self._sec_frames += 1
        sec_elapsed = now - self._sec_start
        if sec_elapsed >= 1.0:
            self.second_fps = self._sec_frames / sec_elapsed
            self._sec_frames = 0
            self._sec_start = now

    def maybe_log_performance(self):
        if self.metrics is None or not getattr(self.config, "PERFORMANCE", False):
            return

        now = time.monotonic()
        if (
            self._last_performance_log is not None
            and now - self._last_performance_log < 1.0
        ):
            return

        self._last_performance_log = now
        timing = self.metrics.snapshot()["timing"]
        logger.info(
            "performance: fps=%.1f loop_mean=%.2fms loop_p95=%.2fms "
            "loop_max=%.2fms camera_p95=%.2fms perception_p95=%.2fms "
            "serial_p95=%.2fms",
            self.second_fps,
            timing["loop"]["mean_ms"],
            timing["loop"]["p95_ms"],
            timing["loop"]["max_ms"],
            timing["camera"]["p95_ms"],
            timing["perception"]["p95_ms"],
            timing["serial"]["p95_ms"],
        )

    def stop(self):
        return self.avg_fps

    def __call__(self):
        return self.avg_fps

    def print_every_second(self, *values):
        now = time.monotonic()
        if not hasattr(self, "_last_print"):
            self._last_print = now
        if now - self._last_print >= 1.0:
            print(*values)
            self._last_print = now
