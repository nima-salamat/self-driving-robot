"""Temporal association of Hough segments using Hall-aware matching.

Each lane ROI supplies image-space Hough segments. Geometry gates create a
bipartite graph between previous segment tracks and current detections. A
minimum-cost maximum-cardinality matcher preserves identities; Hall deficiency
and an alternating-path witness report which previous tracks cannot all be
assigned uniquely.

This is a segment-association component for the existing City/Race vision
pipeline. It is not, by itself, a metric lane model or a lane-departure detector.
"""
from __future__ import annotations

from collections import deque
import heapq
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
    def _maximum_matching(adjacency, detection_count=None):
        """Return a minimum-cost maximum-cardinality bipartite matching.

        Successive shortest augmenting paths maximize the number of matched
        tracks. Reduced-cost potentials let Dijkstra handle residual reverse
        edges, while minimizing total geometric association cost for each
        achieved cardinality. The graph is sparse and has no SciPy dependency.
        """
        track_count = len(adjacency)
        if track_count == 0:
            return {}

        if detection_count is None:
            edge_indices = [
                int(detection_index)
                for edges in adjacency
                for detection_index, _cost in edges
            ]
            detection_count = max(edge_indices, default=-1) + 1

        detection_count = max(0, int(detection_count))
        if detection_count == 0:
            return {}

        source = 0
        track_start = 1
        detection_start = track_start + track_count
        sink = detection_start + detection_count
        graph = [[] for _ in range(sink + 1)]

        def add_edge(start, end, capacity, cost):
            forward = [end, len(graph[end]), capacity, float(cost)]
            reverse = [start, len(graph[start]), 0, -float(cost)]
            graph[start].append(forward)
            graph[end].append(reverse)
            return forward

        for track_index in range(track_count):
            add_edge(source, track_start + track_index, 1, 0.0)

        for detection_index in range(detection_count):
            add_edge(detection_start + detection_index, sink, 1, 0.0)

        edge_references = []
        for track_index, edges in enumerate(adjacency):
            for detection_index, cost in edges:
                try:
                    detection_index = int(detection_index)
                    cost = float(cost)
                except (TypeError, ValueError, OverflowError):
                    continue

                if (
                    0 <= detection_index < detection_count
                    and math.isfinite(cost)
                    and cost >= 0.0
                ):
                    edge = add_edge(
                        track_start + track_index,
                        detection_start + detection_index,
                        1,
                        cost,
                    )
                    edge_references.append(
                        (track_index, detection_index, edge)
                    )

        node_count = len(graph)
        potential = [0.0] * node_count
        epsilon = 1e-12

        while True:
            distance = [float("inf")] * node_count
            previous_node = [-1] * node_count
            previous_edge = [-1] * node_count
            distance[source] = 0.0
            queue = [(0.0, source)]

            while queue:
                current_distance, node = heapq.heappop(queue)
                if current_distance > distance[node] + epsilon:
                    continue

                for edge_index, edge in enumerate(graph[node]):
                    target, _reverse_index, capacity, edge_cost = edge
                    if capacity <= 0:
                        continue

                    reduced_cost = (
                        edge_cost + potential[node] - potential[target]
                    )
                    if reduced_cost < 0.0 and reduced_cost > -1e-9:
                        reduced_cost = 0.0

                    candidate_distance = current_distance + reduced_cost
                    if candidate_distance + epsilon < distance[target]:
                        distance[target] = candidate_distance
                        previous_node[target] = node
                        previous_edge[target] = edge_index
                        heapq.heappush(
                            queue, (candidate_distance, target)
                        )

            if previous_node[sink] < 0:
                break

            for node, value in enumerate(distance):
                if math.isfinite(value):
                    potential[node] += value

            node = sink
            while node != source:
                parent = previous_node[node]
                edge = graph[parent][previous_edge[node]]
                reverse_index = edge[1]
                edge[2] -= 1
                graph[node][reverse_index][2] += 1
                node = parent

        matching = {}
        for track_index, detection_index, edge in edge_references:
            if edge[2] == 0:
                matching[track_index] = detection_index

        return matching

    @staticmethod
    def _hall_witness(adjacency, matching):
        """Return a deficient Hall subset and its neighborhood.

        Starting from unmatched track vertices, traverse unmatched edges from
        tracks to detections and matched edges in reverse. For a maximum
        matching, the reached set S has |S| - |N(S)| equal to the matching
        deficiency. Returned indices refer to adjacency rows and detections.
        """
        detection_to_track = {
            detection_index: track_index
            for track_index, detection_index in matching.items()
        }
        reachable_tracks = {
            track_index
            for track_index in range(len(adjacency))
            if track_index not in matching
        }
        reachable_detections = set()
        queue = deque(sorted(reachable_tracks))

        while queue:
            track_index = queue.popleft()
            matched_detection = matching.get(track_index)

            for detection_index, _cost in adjacency[track_index]:
                detection_index = int(detection_index)
                if detection_index == matched_detection:
                    continue
                if detection_index in reachable_detections:
                    continue

                reachable_detections.add(detection_index)
                matched_track = detection_to_track.get(detection_index)
                if (
                    matched_track is not None
                    and matched_track not in reachable_tracks
                ):
                    reachable_tracks.add(matched_track)
                    queue.append(matched_track)

        neighborhood = {
            int(detection_index)
            for track_index in reachable_tracks
            for detection_index, _cost in adjacency[track_index]
        }
        return sorted(reachable_tracks), sorted(neighborhood)

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

        matching = self._maximum_matching(adjacency, len(detections))
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

        expired_track_ids = []
        for track_index, (track_id, track) in enumerate(previous):
            if track_index not in matching:
                track["missed"] += 1
                track["age"] += 1
                if track["missed"] > self.max_missed_frames:
                    self._tracks.pop(track_id, None)
                    expired_track_ids.append(int(track_id))

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
            predicted_x = (
                selected_track["feature"][0]
                + selected_track["vx"] * selected_track["missed"]
            )
            # Never feed an extrapolated point outside this ROI into steering.
            if math.isfinite(predicted_x) and 0.0 <= predicted_x <= 1.0:
                selected_midpoint = float(predicted_x * width)
            else:
                state = "LOST"
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

        hall_witness_rows, hall_witness_detections = self._hall_witness(
            adjacency, matching
        )
        hall_deficiency = max(0, len(previous) - len(matching))
        hall_satisfied = len(matching) == len(previous)
        edge_costs = {
            (track_index, detection_index): float(cost)
            for track_index, edges in enumerate(adjacency)
            for detection_index, cost in edges
        }
        matching_cost = sum(
            edge_costs[(track_index, detection_index)]
            for track_index, detection_index in matching.items()
        )
        unmatched_track_ids = [
            int(track_id)
            for index, (track_id, _track) in enumerate(previous)
            if index not in matching
        ]
        matched_detection_indices = set(matching.values())
        unmatched_candidate_indices = [
            int(item["original_index"])
            for index, item in enumerate(detections)
            if index not in matched_detection_indices
        ]
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
            "hall_applicable": bool(previous),
            "hall_deficiency": int(hall_deficiency),
            "hall_witness_track_ids": [
                int(previous[index][0]) for index in hall_witness_rows
            ],
            "hall_witness_candidate_indices": [
                int(detections[index]["original_index"])
                for index in hall_witness_detections
            ],
            "hall_witness_deficiency": int(
                len(hall_witness_rows) - len(hall_witness_detections)
            ),
            "association_ratio": (
                float(len(matching) / len(previous)) if previous else None
            ),
            "matching_cost": float(matching_cost),
            "unmatched_track_ids": unmatched_track_ids,
            "unmatched_candidate_indices": unmatched_candidate_indices,
            "matched_track_ids": sorted(int(track_id) for track_id in matched_track_ids),
            "expired_track_ids": sorted(set(expired_track_ids)),
            "missed_frames": missed,
            "candidate_tracks": candidate_tracks,
            "stable_lines": stable_lines,
        }
