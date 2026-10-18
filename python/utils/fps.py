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
        snapshot = self.metrics.snapshot()
        timing = snapshot["timing"]
        rate_controller = getattr(self.config, "processing_rate_controller", None)
        rate = rate_controller.snapshot() if rate_controller is not None else None
        vision_rate = (
            " target_fps=%.1f vision_fps=%.1f vision_wait_ms=%.2f"
            % (rate["target_fps"], rate["achieved_fps"], rate["last_wait_ms"])
            if rate is not None
            else ""
        )
        logger.info(
            "performance: fps=%.1f loop_mean=%.2fms loop_p95=%.2fms "
            "loop_max=%.2fms camera_p95=%.2fms perception_p95=%.2fms "
            "control_p95=%.2fms serial_p95=%.2fms%s",
            self.second_fps,
            timing["loop"]["mean_ms"],
            timing["loop"]["p95_ms"],
            timing["loop"]["max_ms"],
            timing["camera"]["p95_ms"],
            timing["perception"]["p95_ms"],
            timing["control"]["p95_ms"],
            timing["serial"]["p95_ms"],
            vision_rate,
        )

        # Stage timers show where wall time is actually spent. Keep this
        # separate from the headline line so it remains readable on the Pi.
        stage_names = (
            "lane", "confidence", "sign_submit", "sign_consume",
            "sign_latency", "sign_input_age", "object", "traffic_light", "debug_stream",
            "camera_wait", "frame_age", "rate_wait",
        )
        stage_items = [
            f"{name}_p95_ms={timing[name]['p95_ms']:.2f}"
            for name in stage_names
            if name in timing and timing[name]["count"] > 0
        ]
        if stage_items:
            logger.info("performance stages: %s", " ".join(stage_items))

        robot = getattr(self.config, "runtime_robot", None)
        camera = getattr(robot, "camera", None)
        camera_fps = getattr(camera, "measured_frame_rate", None)
        capture_at = getattr(camera, "last_capture_at", None)
        frame_age_ms = (
            max(0.0, (time.monotonic() - capture_at) * 1000.0)
            if capture_at is not None
            else None
        )
        camera_skipped = getattr(camera, "dropped_camera_frames", 0)
        source_items = []
        if camera_fps is not None:
            source_items.append(f"camera_fps={float(camera_fps):.1f}")
        if frame_age_ms is not None:
            source_items.append(f"camera_frame_age_ms={frame_age_ms:.1f}")
        if camera is not None:
            source_items.append(f"camera_skipped_frames={int(camera_skipped or 0)}")

        sign_worker = getattr(self.config, "sign_detector", None)
        if sign_worker is not None and callable(getattr(sign_worker, "status", None)):
            try:
                sign = sign_worker.status()
                kind = "process" if getattr(sign_worker, "multiprocess", False) else "thread"
                source_items.extend((
                    f"sign_worker={kind}",
                    f"sign_alive={bool(sign.get('worker_alive', False))}",
                    f"sign_queue={int(sign.get('queue_depth', 0) or 0)}",
                    f"sign_submitted={int(sign.get('submitted', 0) or 0)}",
                    f"sign_completed={int(sign.get('completed', 0) or 0)}",
                    f"sign_replaced={int(sign.get('replaced', 0) or 0)}",
                    f"sign_dropped={int(sign.get('dropped', 0) or 0)}",
                    f"sign_failures={int(sign.get('failures', 0) or 0)}",
                ))
                latency = sign.get("last_latency_ms")
                input_age = sign.get("last_result_input_age_s")
                if latency is not None:
                    source_items.append(f"sign_inference_ms={float(latency):.1f}")
                if input_age is not None:
                    source_items.append(f"sign_result_input_age_ms={float(input_age) * 1000.0:.1f}")
            except Exception:
                logger.debug("Could not collect sign-worker performance status", exc_info=True)
        if source_items:
            logger.info("performance sources: %s", " ".join(source_items))

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
