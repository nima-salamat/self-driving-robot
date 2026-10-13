"""Fail-safe state for a traffic STOP sign.

Inference is polled continuously while this state is active. Missing, stale, or
failed inference results never clear the stop state. Releasing motion requires
several distinct, fresh observations that do not contain STOP.
"""


class StopSignHold:
    """Latch STOP until fresh observations consistently show it is absent."""

    def __init__(self, clear_confirmations=3):
        confirmations = int(clear_confirmations)
        if confirmations < 1:
            raise ValueError("clear_confirmations must be at least 1")
        self.clear_confirmations = confirmations
        self.active = False
        self.started_at = None
        self.clear_observations = 0

    def observe(
        self,
        *,
        stop_present,
        fresh,
        observation_time=None,
        now=None,
    ):
        """Update the latch from one detector observation.

        observation_time is the monotonic time at which the input frame was
        submitted to inference. An old result from before STOP was latched must
        not count as evidence that the sign has disappeared.
        """
        if stop_present:
            if not self.active:
                self.active = True
                self.started_at = (
                    observation_time if observation_time is not None else now
                )
            self.clear_observations = 0
            return True

        if not self.active:
            return False

        if not fresh or observation_time is None:
            return True

        if self.started_at is not None and observation_time < self.started_at:
            return True

        self.clear_observations += 1
        if self.clear_observations >= self.clear_confirmations:
            self.active = False
            self.started_at = None
            self.clear_observations = 0

        return self.active
