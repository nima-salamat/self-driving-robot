"""Temporal line association using bipartite maximum matching.

Line tracks and current-frame detections form a bipartite graph. Geometry-based
edges prevent implausible associations, and augmenting paths find a maximum
cardinality matching. Hall's condition describes when every previous track
can be assigned a unique current detection.
"""
from __future__ import annotations

import math

import numpy as np


class HallLineTracker:
    """Keep line identities stable across camera frames."""

    def __init__(self, max_missed_frames: int = 4, max_candidates: int = 128):
        self.max_missed_frames = max(1, int(max_missed_frames))
        self.max_candidates = max(8, int(max_candidates))
        self._tracks = {}
        self._next_track_id = 1
        self._selected_track_id = None
        self._ever_selected = False

    def reset(self):
        self._tracks.clear()
        self._next_track_id = 1
        self._selected_track_id = None
        self._ever_selected = False

    @staticmethod
    def _feature(line, width, height):
        try:
            xy = np.asarray(line, dtype=np.float64).reshape(-1)
            if xy.size < 4 or not np.isfinite(xy[:4]).all():
                return None
            x1, y1, x2, y2 = map(float, xy[:4])
        except (TypeError, ValueError, OverflowError):
            return None
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length < 1.0:
            return None
        angle = math.degrees(math.atan2(dy, dx)) % 180.0
        diagonal = max(1.0, math.hypot(float(width), float(height)))
        return (
            ((x1 + x2) * 0.5) / max(1.0, float(width)),
            ((y1 + y2) * 0.5) / max(1.0, float(height)),
            length / diagonal,
            angle,
        )

    @staticmethod
    def _angle_distance(a, b):
        delta = abs(float(a) - float(b)) % 180.0
        return min(delta, 180.0 - delta)

    @staticmethod
    def _maximum_matching(adjacency):
        """Return track-index -> detection-index maximum-cardinality matching."""
        detection_to_track = {}

        def augment(track_index, visited):
            for detection_index, _cost in adjacency[track_index]:
                if detection_index in visited:
                    continue
                visited.add(detection_index)
                previous = detection_to_track.get(detection_index)
                if previous is None or augment(previous, visited):
                    detection_to_track[detection_index] = track_index
                    return True
            return False

        for track_index in range(len(adjacency)):
            augment(track_index, set())

        return {
            track_index: detection_index
            for detection_index, track_index in detection_to_track.items()
        }

    def _cost(self, track, feature):
        steps = int(track["missed"]) + 1
        previous = track["feature"]
        predicted_x = previous[0] + track["vx"] * steps
        predicted_y = previous[1] + track["vy"] * steps
        dx = (feature[0] - predicted_x) / 0.14
        dy = (feature[1] - predicted_y) / 0.22
        position = math.hypot(dx, dy)
        angle = self._angle_distance(feature[3], previous[3])
        length = abs(math.log((feature[2] + 0.02) / (previous[2] + 0.02)))
        if position > 4.5 or angle > 55.0 or length > 2.3:
            return None
        cost = 0.62 * position + 0.23 * (angle / 45.0) + 0.15 * min(length, 2.0)
        return cost if cost <= 4.0 else None

    def update(self, lines, frame_width, frame_height, preferred_index=None):
        """Associate detections and preserve the selected line through occlusion.

        preferred_index is the current detector's geometric choice. It is used
        on initial acquisition or after the prior identity expires, not to
        replace a still-visible selected track.
        """
        width = max(1, int(frame_width))
        height = max(1, int(frame_height))
        source = [] if lines is None else list(lines)
        detections = []
        for original_index, line in enumerate(source):
            feature = self._feature(line, width, height)
            if feature is not None:
                detections.append({
                    "original_index": original_index,
                    "line": line,
                    "feature": feature,
                })

        if len(detections) > self.max_candidates:
            ranked = sorted(detections, key=lambda item: item["feature"][2], reverse=True)[:self.max_candidates]
            preferred = next((item for item in detections if item["original_index"] == preferred_index), None)
            if preferred is not None and all(item["original_index"] != preferred_index for item in ranked):
                ranked[-1] = preferred
            detections = sorted(ranked, key=lambda item: item["original_index"])

        previous = sorted(self._tracks.items())
        adjacency = []
        for _track_id, track in previous:
            edges = []
            for detection_index, detection in enumerate(detections):
                cost = self._cost(track, detection["feature"])
                if cost is not None:
                    edges.append((detection_index, cost))
            edges.sort(key=lambda item: item[1])
            adjacency.append(edges)

        matching = self._maximum_matching(adjacency)
        detection_to_track = {}
        matched_track_ids = set()
        stable_lines = []

        for track_index, detection_index in matching.items():
            track_id, track = previous[track_index]
            detection = detections[detection_index]
            feature = detection["feature"]
            elapsed = int(track["missed"]) + 1
            delta_x = (feature[0] - track["feature"][0]) / elapsed
            delta_y = (feature[1] - track["feature"][1]) / elapsed
            track["vx"] = 0.55 * track["vx"] + 0.45 * delta_x
            track["vy"] = 0.55 * track["vy"] + 0.45 * delta_y
            track["feature"] = feature
            track["line"] = detection["line"]
            track["missed"] = 0
            track["hits"] += 1
            track["age"] += 1
            detection_to_track[detection_index] = track_id
            matched_track_ids.add(track_id)
            stable_lines.append(detection["line"])

        for track_index, (track_id, track) in enumerate(previous):
            if track_index not in matching:
                track["missed"] += 1
                track["age"] += 1
                if track["missed"] > self.max_missed_frames:
                    self._tracks.pop(track_id, None)

        for detection_index, detection in enumerate(detections):
            if detection_index in detection_to_track:
                continue
            track_id = self._next_track_id
            self._next_track_id += 1
            self._tracks[track_id] = {
                "feature": detection["feature"], "line": detection["line"],
                "vx": 0.0, "vy": 0.0, "hits": 1, "age": 1, "missed": 0,
            }
            detection_to_track[detection_index] = track_id

        selected_track = self._tracks.get(self._selected_track_id)
        state, selected_line, selected_midpoint = "LOST", None, None
        if selected_track is not None and self._selected_track_id in matched_track_ids:
            state = "TRACKING"
            selected_line = selected_track["line"]
            selected_midpoint = float(selected_track["feature"][0] * width)
        elif selected_track is not None:
            state = "COASTING"
            selected_midpoint = float(
                (selected_track["feature"][0] + selected_track["vx"] * selected_track["missed"]) * width
            )
        else:
            self._selected_track_id = None
            candidate_index = next(
                (i for i, item in enumerate(detections)
                 if item["original_index"] == preferred_index and i in detection_to_track),
                None,
            )
            if candidate_index is None and detections:
                candidate_index = max(range(len(detections)), key=lambda i: detections[i]["feature"][2])
            if candidate_index is not None:
                self._selected_track_id = detection_to_track[candidate_index]
                selected_track = self._tracks[self._selected_track_id]
                selected_line = selected_track["line"]
                selected_midpoint = float(selected_track["feature"][0] * width)
                state = "REACQUIRING" if self._ever_selected else "TRACKING"
                self._ever_selected = True

        selected_track = self._tracks.get(self._selected_track_id)
        missed = int(selected_track["missed"]) if selected_track else 0
        hall_satisfied = len(matching) == len(previous)
        candidate_tracks = [
            {
                "candidate_index": int(item["original_index"]),
                "track_id": int(detection_to_track[index]),
                "matched": index in matching.values(),
                "hits": int(self._tracks[detection_to_track[index]]["hits"]),
            }
            for index, item in enumerate(detections)
        ]
        return {
            "state": state,
            "selected_track_id": self._selected_track_id,
            "selected_line": selected_line,
            "selected_midpoint": selected_midpoint,
            "active_tracks": len(self._tracks),
            "matched_tracks": len(matching),
            "hall_satisfied": bool(hall_satisfied),
            "hall_deficiency": max(0, len(previous) - len(matching)),
            "missed_frames": missed,
            "candidate_tracks": candidate_tracks,
            "stable_lines": stable_lines,
        }
