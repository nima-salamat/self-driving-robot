"""Fail-safe, observation-driven start gate used only by Race mode."""

import math


class RaceStartGate:
    def __init__(self, absence_seconds=1.0, max_observation_age_s=0.75):
        absence_seconds = float(absence_seconds)
        max_age = float(max_observation_age_s)
        if not math.isfinite(absence_seconds) or absence_seconds < 0:
            raise ValueError("absence_seconds must be finite and non-negative")
        if not math.isfinite(max_age) or max_age <= 0:
            raise ValueError("max_observation_age_s must be positive and finite")
        self.absence_seconds = absence_seconds
        self.max_observation_age_s = max_age
        self.saw_stop = False
        self.absent_since = None
        self.last_observation_id = None
        self.last_observation_at = None
        self.released = False

    def observe(self, *, result_id, stop_present, observation_at, now, valid=True):
        """Accept a new valid result; missing/duplicate/stale results fail closed."""
        if self.released:
            return True
        if not valid or result_id is None or observation_at is None:
            self._expire(now)
            return False
        try:
            observation_at = float(observation_at)
            now = float(now)
        except (TypeError, ValueError):
            self._expire(now)
            return False
        if (not math.isfinite(observation_at) or not math.isfinite(now) or
                observation_at > now or now - observation_at > self.max_observation_age_s):
            self._expire(now)
            return False
        if (self.last_observation_at is not None and
                now - self.last_observation_at > self.max_observation_age_s):
            self.absent_since = None
        if self.last_observation_id is not None and result_id <= self.last_observation_id:
            self._expire(now)
            return False
        self.last_observation_id = result_id
        self.last_observation_at = now
        if stop_present:
            self.saw_stop = True
            self.absent_since = None
            return False
        if not self.saw_stop:
            return False
        if self.absent_since is None:
            self.absent_since = now
            self.released = self.absence_seconds == 0
            return self.released
        self.released = now - self.absent_since >= self.absence_seconds
        return self.released

    def _expire(self, now):
        if self.last_observation_at is None:
            return
        try:
            age = float(now) - self.last_observation_at
        except (TypeError, ValueError):
            age = float("inf")
        if not math.isfinite(age) or age > self.max_observation_age_s:
            self.absent_since = None


class RaceFinishState:
    """One-way timer-to-finishing-to-terminal-stop state for Race."""

    def __init__(self, finish_after_seconds, finish_speed):
        self.finish_after_seconds = float(finish_after_seconds)
        self.finish_speed = int(finish_speed)
        if not math.isfinite(self.finish_after_seconds) or self.finish_after_seconds < 0:
            raise ValueError("finish_after_seconds must be finite and non-negative")
        self.started_at = None
        self.finishing = False
        self.finishing_started_at = None
        self.finished = False

    def start(self, now):
        if self.started_at is None:
            self.started_at = float(now)

    def update(self, now):
        if (not self.finished and self.started_at is not None and
                float(now) - self.started_at >= self.finish_after_seconds):
            if not self.finishing:
                self.finishing = True
                self.finishing_started_at = (
                    self.started_at + self.finish_after_seconds
                )
        return self.finishing

    def finish(self):
        if self.finishing and not self.finished:
            self.finished = True
            return True
        return False
