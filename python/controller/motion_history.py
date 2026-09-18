import re
import threading
import time
from collections import deque


_PULSE_GROUP_RE = re.compile(r"^([fbFB])\s+(\d+)\s+(\d+)\s+(\d+)$")


class MotionHistory:
    """
    Bounded in-memory motion trace for future closed-loop recovery.

    The pulse deque stores the most recent individual pulse units commanded by
    Python. It intentionally does not claim that every command was physically
    completed by the Arduino.

    Events are kept separately so a long pulse sequence cannot erase important
    semantic boundaries such as hardcoded maneuvers, stops, and crosswalk waits.

    FUTURE RECOVERY HOOK:
    Implement the recovery coordinator in controller/motion_recovery.py.
    MotionHistory should remain a passive recorder. Recovery should:
      1. detect route deviation from perception/odometry,
      2. select a previously verified safe event/pulse boundary,
      3. replay only a bounded prefix up to that safe point,
      4. never blindly replay the entire 200-pulse window.

    FUTURE HARDWARE ACCURACY:
    The current history records Python-issued pulse commands. Arduino-generated
    autonomous pulse motion is not yet represented as physical execution data.
    A later protocol revision can attach pulse lifecycle telemetry (start,
    progress, completion, abort) and upgrade records from commanded -> executed.
    """

    def __init__(self, max_pulses=200, max_events=128):
        self.max_pulses = max(1, int(max_pulses))
        self.max_events = max(1, int(max_events))
        self._lock = threading.RLock()
        self._pulses = deque(maxlen=self.max_pulses)
        self._events = deque(maxlen=self.max_events)
        self._sequence = 0

    @staticmethod
    def _parse_pulse_groups(command):
        tokens = str(command).strip().split()
        if not tokens or len(tokens) % 4:
            return []

        groups = []
        for index in range(0, len(tokens), 4):
            match = _PULSE_GROUP_RE.match(" ".join(tokens[index:index + 4]))
            if match is None:
                return []
            direction, speed, pulses, angle = match.groups()
            groups.append(
                {
                    "direction": "forward" if direction.lower() == "f" else "backward",
                    "speed": int(speed),
                    "pulses": int(pulses),
                    "angle": int(angle),
                }
            )
        return groups

    def _next_sequence(self):
        self._sequence += 1
        return self._sequence

    def record_pulse_command(self, command, event="pulse_command", source="python", metadata=None):
        groups = self._parse_pulse_groups(command)
        if not groups:
            return 0

        metadata = dict(metadata or {})
        total_pulses = sum(group["pulses"] for group in groups)

        # Keep only the tail that can fit in the bounded pulse history. This
        # avoids expanding a very large command into thousands of discarded
        # Python objects.
        skip = max(0, total_pulses - self.max_pulses)
        recorded = 0
        global_offset = 0

        with self._lock:
            operation_id = self._next_sequence()
            for group_index, group in enumerate(groups):
                for pulse_number in range(1, group["pulses"] + 1):
                    absolute_number = global_offset + pulse_number
                    if absolute_number <= skip:
                        continue

                    self._pulses.append(
                        {
                            "sequence": self._next_sequence(),
                            "operation_id": operation_id,
                            "type": "pulse",
                            "direction": group["direction"],
                            "speed": group["speed"],
                            "angle": group["angle"],
                            "pulse_index": pulse_number,
                            "pulse_count": group["pulses"],
                            "group_index": group_index,
                            "event": event,
                            "source": source,
                            "status": "commanded",
                            "timestamp": time.time(),
                            "metadata": dict(metadata),
                        }
                    )
                    recorded += 1
                global_offset += group["pulses"]

        return recorded

    def record_event(self, event, source="python", metadata=None):
        metadata = dict(metadata or {})
        with self._lock:
            self._events.append(
                {
                    "sequence": self._next_sequence(),
                    "type": "event",
                    "event": str(event),
                    "source": source,
                    "timestamp": time.time(),
                    "metadata": metadata,
                }
            )

    def recent_pulses(self):
        with self._lock:
            return [dict(item) for item in self._pulses]

    def recent_events(self):
        with self._lock:
            return [dict(item) for item in self._events]

    def timeline(self):
        with self._lock:
            items = [dict(item) for item in self._pulses]
            items.extend(dict(item) for item in self._events)
        items.sort(key=lambda item: item["sequence"])
        return items

    def snapshot(self):
        return {
            "max_pulses": self.max_pulses,
            "max_events": self.max_events,
            "pulse_count": len(self.recent_pulses()),
            "event_count": len(self.recent_events()),
            "pulses": self.recent_pulses(),
            "events": self.recent_events(),
        }
