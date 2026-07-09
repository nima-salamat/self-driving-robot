import time


class FPS:
    def __init__(self):
        self._start_time = None
        self._num_frames = 0

        self.avg_fps = 0
        self.instant_fps = 0
        self.second_fps = 0

        self._last_frame_time = None
        self._sec_start = None
        self._sec_frames = 0

    def start(self):
        now = time.time()

        self._start_time = now
        self._last_frame_time = now
        self._sec_start = now

        return self

    def update(self):
        now = time.time()

        # ----------------------------
        # Instant FPS
        # ----------------------------
        dt = now - self._last_frame_time
        if dt > 0:
            self.instant_fps = 1.0 / dt

        self._last_frame_time = now

        # ----------------------------
        # Average FPS
        # ----------------------------
        self._num_frames += 1
        elapsed = now - self._start_time
        if elapsed > 0:
            self.avg_fps = self._num_frames / elapsed

        # ----------------------------
        # FPS Every Second
        # ----------------------------
        self._sec_frames += 1

        sec_elapsed = now - self._sec_start
        if sec_elapsed >= 1.0:
            self.second_fps = self._sec_frames / sec_elapsed
            self._sec_frames = 0
            self._sec_start = now

    def stop(self):
        return self.avg_fps

    def __call__(self):
        return self.avg_fps
    
    def print_every_second(self, *values):
        now = time.time()

        if not hasattr(self, "_last_print"):
            self._last_print = now

        if now - self._last_print >= 1.0:
            print(*values)
            self._last_print = now