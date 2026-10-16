"""State for stopping while a fresh traffic-sign observation contains STOP."""

import math
import time


class StopSignHold:
    """Latch STOP until it has been absent for the configured clear interval."""

    def __init__(self, clear_confirmations=1, minimum_duration_s=3.0):
        confirmations = int(clear_confirmations)
        if confirmations < 1:
            raise ValueError("clear_confirmations must be at least 1")

        duration = float(minimum_duration_s)
        if not math.isfinite(duration) or duration < 0.0:
            raise ValueError("minimum_duration_s must be finite and non-negative")

        self.clear_confirmations = confirmations
        self.minimum_duration_s = duration
        self.active = False
        self.started_at = None
        self.clear_started_at = None
        self.clear_observations = 0
        self._last_observation_time = None

    def observe(
        self,
        *,
        stop_present,
        fresh,
        observation_time=None,
        now=None,
    ):
        """Record a new detector observation without releasing the hold.

        ``observation_time`` is the monotonic time at which the frame was
        submitted to inference. ``started_at`` is set to ``now`` when Python
        accepts the STOP result. The clear interval starts when Python accepts
        the first fresh result without STOP; a new STOP result resets it.
        """
        if now is None:
            now = time.monotonic()
        now = float(now)

        if not fresh or observation_time is None:
            return self.active

        observation_time = float(observation_time)
        if not math.isfinite(observation_time):
            return self.active

        if not self.active:
            if not stop_present:
                return False
            self.active = True
            self.started_at = now
            self.clear_started_at = None
            self.clear_observations = 0
            self._last_observation_time = observation_time
            return True

        # A frame captured before the hold began, an out-of-order result, or a
        # duplicate timestamp cannot change the active safety state.
        if (
            self.started_at is None
            or observation_time <= self.started_at
            or (
                self._last_observation_time is not None
                and observation_time <= self._last_observation_time
            )
        ):
            return True

        self._last_observation_time = observation_time
        if stop_present:
            self.clear_started_at = None
            self.clear_observations = 0
            return True

        if self.clear_started_at is None:
            self.clear_started_at = now
        self.clear_observations += 1
        return True

    def can_release(self, now=None):
        """Return whether STOP has remained absent for the clear interval."""
        if not self.active or self.clear_started_at is None:
            return False
        if now is None:
            now = time.monotonic()
        elapsed = float(now) - self.clear_started_at
        return (
            elapsed >= self.minimum_duration_s
            and self.clear_observations >= self.clear_confirmations
        )

    def release(self, now=None):
        """Clear the state only after the caller has safely released control."""
        if not self.can_release(now):
            return False
        self.active = False
        self.started_at = None
        self.clear_started_at = None
        self.clear_observations = 0
        self._last_observation_time = None
        return True
