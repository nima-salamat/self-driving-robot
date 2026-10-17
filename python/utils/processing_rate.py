"""Monotonic, non-catching-up admission control for vision cycles."""

import math
import time
from collections import deque


DEFAULT_TARGET_FPS = 30.0


class ProcessingRateController:
    """Limit vision-cycle start rate without accumulating scheduling debt.

    Call ``wait_for_slot`` immediately before acquiring the frame for a vision
    cycle. Slow cycles never trigger catch-up work; the next start is measured
    from the actual previous start. ``event.wait`` keeps shutdown responsive.
    """

    def __init__(
        self, target_fps=DEFAULT_TARGET_FPS, clock=time.monotonic, sleeper=time.sleep
    ):
        target_fps = float(target_fps)
        if not math.isfinite(target_fps) or target_fps <= 0:
            raise ValueError("target_fps must be a positive finite number")
        self.target_fps = target_fps
        self.interval = 1.0 / target_fps
        self._clock = clock
        self._sleeper = sleeper
        self._next_start = None
        self.last_wait_seconds = 0.0
        self.last_start = None
        self.cycle_starts = 0
        self._starts = deque(maxlen=120)

    def set_target_fps(self, target_fps):
        """Change the runtime admission rate without scheduling catch-up cycles."""
        value = float(target_fps)
        if not math.isfinite(value) or not 1.0 <= value <= 60.0:
            raise ValueError("target_fps must be between 1 and 60")
        self.target_fps = value
        self.interval = 1.0 / value
        # Reset the deadline to avoid carrying stale scheduling debt across a
        # deliberate operator rate change.
        self._next_start = None
        self.last_wait_seconds = 0.0
        return self.snapshot()

    def wait_for_slot(self, shutdown_event=None):
        """Wait for the next permitted cycle; return False if shutting down."""
        now = self._clock()
        deadline = self._next_start
        delay = max(0.0, deadline - now) if deadline is not None else 0.0
        self.last_wait_seconds = delay
        if delay:
            if shutdown_event is not None:
                if shutdown_event.wait(delay):
                    return False
            else:
                self._sleeper(delay)
        elif shutdown_event is not None and shutdown_event.is_set():
            return False

        started = self._clock()
        self.last_start = started
        self._next_start = started + self.interval
        self.cycle_starts += 1
        self._starts.append(started)
        return True

    def snapshot(self):
        """Return compact rate and wait diagnostics for periodic logging."""
        starts = list(self._starts)
        elapsed = starts[-1] - starts[0] if len(starts) > 1 else 0.0
        return {
            "target_fps": self.target_fps,
            "achieved_fps": (len(starts) - 1) / elapsed if elapsed > 0 else 0.0,
            "last_wait_ms": self.last_wait_seconds * 1000.0,
            "cycles": self.cycle_starts,
        }
