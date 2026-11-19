"""Joint temporal tracking of the left and right lane boundaries.

The per-ROI Hall matcher maintains segment identities. This module adds a
shared lane-width model, temporal prediction, side-aware geometric gates, and
confirmed reacquisition. A fragment cannot replace a missing boundary merely
because it is the best Hough line in that ROI.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

from vision.hall_line_tracking import HallLineTracker


@dataclass
class _BoundaryState:
    track_id: int | None = None
    x_px: float | None = None
    velocity_px: float = 0.0
    angle_deg: float = 0.0
    line_global: tuple[float, float, float, float] | None = None
    missed_frames: int = 0
    age: int = 0
    pending: dict | None = None
    observed: bool = False


class LaneBoundaryTracker:
    """Track a lane as a pair of boundaries rather than unrelated line picks.

    Coordinates are measured in the full camera frame at a common look-ahead
    row. The learned boundary separation is retained while either side is
    occluded. A returning boundary must satisfy the lane-width gate and remain
    consistent for several consecutive frames before it replaces an inferred
    boundary.
    """

    def __init__(self, max_missed_frames=4, reacquire_frames=3, max_candidates=128):
        self.max_missed_frames = max(1, int(max_missed_frames))
        self.reacquire_frames = max(2, int(reacquire_frames))
        self.max_candidates = max(8, int(max_candidates))
        self._sides = {"left": _BoundaryState(), "right": _BoundaryState()}
        self._hall = {
            side: HallLineTracker(
                max_missed_frames=self.max_missed_frames,
                max_candidates=self.max_candidates,
            )
            for side in ("left", "right")
        }
        self._next_track_id = 1
        self._lane_width_px = None
        self._last_lane_center_px = None
        self._last_lane_center_velocity_px = 0.0
        self._frame_index = 0

    def reset(self):
        """Forget lane geometry and all temporal identities."""
        for state in self._sides.values():
            state.track_id = None
            state.x_px = None
            state.velocity_px = 0.0
            state.angle_deg = 0.0
            state.line_global = None
            state.missed_frames = 0
            state.age = 0
            state.pending = None
            state.observed = False
        for tracker in self._hall.values():
            tracker.reset()
        self._next_track_id = 1
        self._lane_width_px = None
        self._last_lane_center_px = None
        self._last_lane_center_velocity_px = 0.0
        self._frame_index = 0

    @staticmethod
    def _angle_delta(a, b):
        return abs(float(a) - float(b))

    @staticmethod
    def _roi_tuple(roi):
        values = tuple(int(round(float(value))) for value in roi)
        if len(values) != 4:
            raise ValueError("ROI must be (left, top, right, bottom)")
        left, top, right, bottom = values
        if right <= left or bottom <= top:
            raise ValueError("ROI must have positive width and height")
        return left, top, right, bottom

    def _candidates(self, lines, roi, frame_width, y_ref, preferred_index=None):
        left, top, right, bottom = roi
        roi_height = max(1.0, float(bottom - top))
        raw_source = [] if lines is None else list(lines)
        if len(raw_source) > self.max_candidates:
            selected = set(range(self.max_candidates))
            if preferred_index is not None and 0 <= int(preferred_index) < len(raw_source):
                preferred = int(preferred_index)
                if preferred not in selected:
                    selected.add(preferred)
                    selected.discard(self.max_candidates - 1)
            source = [(index, raw_source[index]) for index in sorted(selected)]
        else:
            source = list(enumerate(raw_source))
        candidates = []
        for index, line in source:
            try:
                values = np.asarray(line, dtype=np.float64).reshape(-1)
                if values.size < 4 or not np.isfinite(values[:4]).all():
                    continue
                x1, y1, x2, y2 = map(float, values[:4])
            except (TypeError, ValueError, OverflowError):
                continue

            dx, dy = x2 - x1, y2 - y1
            if abs(dy) < 2.0:
                continue
            length = math.hypot(dx, dy)
            if length < max(5.0, roi_height * 0.035):
                continue

            gx1, gx2 = x1 + left, x2 + left
            gy1, gy2 = y1 + top, y2 + top
            slope = dx / dy
            segment_min_y = min(gy1, gy2)
            segment_max_y = max(gy1, gy2)
            y_gap = max(0.0, segment_min_y - y_ref, y_ref - segment_max_y)
            if y_gap > roi_height * 0.35:
                continue
            x_ref = gx1 + slope * (y_ref - gy1)
            horizontal_margin = max(4.0, (right - left) * 0.15)
            if (
                not math.isfinite(x_ref)
                or not 0 <= x_ref < frame_width
                or x_ref < left - horizontal_margin
                or x_ref > right + horizontal_margin
            ):
                continue

            y_span = min(1.0, abs(dy) / roi_height)
            length_quality = min(1.0, length / max(1.0, roi_height * 0.60))
            angle = math.degrees(math.atan(slope))
            angle_quality = max(0.0, 1.0 - abs(angle) / 75.0)
            quality = (
                0.45 * length_quality
                + 0.35 * y_span
                + 0.20 * angle_quality
            )
            candidates.append({
                "index": int(index),
                "x_px": float(x_ref),
                "slope": float(slope),
                "angle_deg": float(angle),
                "quality": float(max(0.0, min(1.0, quality))),
                "line_global": (
                    float(gx1), float(gy1), float(gx2), float(gy2),
                ),
            })
        return candidates

    def _hall_update(self, side, lines, roi, preferred_index):
        left, top, right, bottom = roi
        hall = self._hall[side]
        hall.max_missed_frames = self.max_missed_frames
        result = hall.update(
            lines,
            max(1, right - left),
            max(1, bottom - top),
            preferred_index=preferred_index,
        )
        selected_index = None
        selected_id = result.get("selected_track_id")
        if selected_id is not None:
            for item in result.get("candidate_tracks", ()):
                if item.get("track_id") == selected_id and item.get("matched"):
                    selected_index = int(item["candidate_index"])
                    break
        return result, selected_index

    def _candidate_cost(self, state, candidate, preferred_index,
                        hall_selected_index, frame_width):
        dx = 0.0
        angle_delta = 0.0
        if state.x_px is not None:
            predicted_x = state.x_px + state.velocity_px
            dx = abs(candidate["x_px"] - predicted_x)
            angle_delta = self._angle_delta(candidate["angle_deg"], state.angle_deg)
            if state.missed_frames == 0:
                gate = max(
                    frame_width * 0.045,
                    min(frame_width * 0.15,
                        frame_width * 0.045 + abs(state.velocity_px) * 0.65),
                )
                if dx > gate or angle_delta > 34.0:
                    return None
            elif angle_delta > 50.0:
                # When a side is occluded, the joint lane-width model is a
                # better position gate than its stale single-side prediction.
                return None
        position_scale = max(frame_width * 0.06, 1.0)
        position_cost = min(1.5, dx / position_scale)
        angle_cost = min(1.5, angle_delta / 40.0)
        cost = (
            0.52 * position_cost
            + 0.23 * angle_cost
            + 0.25 * (1.0 - candidate["quality"])
        )
        if preferred_index is not None and candidate["index"] == preferred_index:
            cost -= 0.10
        if hall_selected_index is not None and candidate["index"] == hall_selected_index:
            cost -= 0.18
        return float(cost)

    def _ranked(self, side, candidates, preferred_index,
                hall_selected_index, frame_width):
        state = self._sides[side]
        ranked = []
        for candidate in candidates:
            cost = self._candidate_cost(
                state, candidate, preferred_index,
                hall_selected_index, frame_width,
            )
            if cost is not None:
                ranked.append((cost, candidate))
        ranked.sort(key=lambda item: (item[0], -item[1]["quality"], item[1]["index"]))
        return ranked

    @staticmethod
    def _pair_is_plausible(left, right, frame_width, prior_width=None,
                           reference_center_x=None):
        width = right["x_px"] - left["x_px"]
        center = (right["x_px"] + left["x_px"]) * 0.5
        if width < frame_width * 0.12 or width > frame_width * 0.72:
            return False, width
        if not frame_width * 0.15 <= center <= frame_width * 0.85:
            return False, width
        if reference_center_x is not None:
            # The lane should ordinarily straddle the camera's expected lane
            # reference. Allow a generous margin for camera offset and curves,
            # but reject a pair that is wholly remote on one side of the image.
            margin = frame_width * 0.10
            if left["x_px"] > reference_center_x + margin:
                return False, width
            if right["x_px"] < reference_center_x - margin:
                return False, width
        if prior_width is not None:
            tolerance = max(
                frame_width * 0.045,
                min(frame_width * 0.12, prior_width * 0.18),
            )
            if abs(width - prior_width) > tolerance:
                return False, width
        return True, width

    def _initial_pair(self, left_ranked, right_ranked, frame_width, reference_center_x):
        best = None
        for left_cost, left in left_ranked[:32]:
            for right_cost, right in right_ranked[:32]:
                valid, width = self._pair_is_plausible(
                    left, right, frame_width, prior_width=None,
                    reference_center_x=reference_center_x,
                )
                if not valid:
                    continue
                angle_penalty = min(
                    1.0,
                    self._angle_delta(left["angle_deg"], right["angle_deg"]) / 80.0,
                )
                center_penalty = abs(
                    0.5 * (left["x_px"] + right["x_px"]) - reference_center_x
                ) / max(1.0, frame_width)
                score = left_cost + right_cost + 0.08 * angle_penalty + 0.20 * center_penalty
                if best is None or score < best[0]:
                    best = (score, left, right, width)
        return best

    def _best_pair(self, left_ranked, right_ranked, frame_width, reference_center_x):
        best = None
        prior = self._lane_width_px
        for left_cost, left in left_ranked[:32]:
            for right_cost, right in right_ranked[:32]:
                valid, width = self._pair_is_plausible(
                    left, right, frame_width, prior_width=prior,
                    reference_center_x=reference_center_x,
                )
                if not valid:
                    continue
                tolerance = max(
                    frame_width * 0.045,
                    min(frame_width * 0.12, prior * 0.18),
                )
                width_cost = abs(width - prior) / max(1.0, tolerance)
                center_penalty = abs(
                    0.5 * (left["x_px"] + right["x_px"]) - reference_center_x
                ) / max(1.0, frame_width)
                score = left_cost + right_cost + 0.28 * width_cost + 0.20 * center_penalty
                if best is None or score < best[0]:
                    best = (score, left, right, width)
        return best

    def _apply(self, side, candidate):
        state = self._sides[side]
        if state.x_px is None:
            state.track_id = self._next_track_id
            self._next_track_id += 1
            state.x_px = candidate["x_px"]
            state.velocity_px = 0.0
            state.angle_deg = candidate["angle_deg"]
            state.line_global = candidate["line_global"]
            state.age = 1
            state.missed_frames = 0
            state.pending = None
            state.observed = True
            return "ACQUIRED"

        if state.missed_frames > 0:
            return "PENDING"

        predicted = state.x_px + state.velocity_px
        innovation = candidate["x_px"] - predicted
        state.x_px = predicted + 0.68 * innovation
        state.velocity_px = 0.62 * state.velocity_px + 0.38 * innovation
        state.angle_deg = 0.68 * state.angle_deg + 0.32 * candidate["angle_deg"]
        state.line_global = candidate["line_global"]
        state.age += 1
        state.missed_frames = 0
        state.pending = None
        state.observed = True
        return "TRACKING"

    def _confirm_reacquisition(self, side, candidate, expected_x, pair_tolerance):
        state = self._sides[side]
        pending = state.pending
        consistency_tolerance = max(pair_tolerance * 0.55, 2.0)
        if pending is None:
            state.pending = {
                "x_px": candidate["x_px"],
                "angle_deg": candidate["angle_deg"],
                "expected_x": expected_x,
                "hits": 1,
            }
            return False

        expected_shift = expected_x - pending["expected_x"]
        predicted_pending_x = pending["x_px"] + expected_shift
        position_ok = abs(candidate["x_px"] - predicted_pending_x) <= consistency_tolerance
        angle_ok = self._angle_delta(candidate["angle_deg"], pending["angle_deg"]) <= 18.0
        if position_ok and angle_ok:
            pending["hits"] += 1
            pending["x_px"] = candidate["x_px"]
            pending["angle_deg"] = candidate["angle_deg"]
            pending["expected_x"] = expected_x
        else:
            state.pending = {
                "x_px": candidate["x_px"],
                "angle_deg": candidate["angle_deg"],
                "expected_x": expected_x,
                "hits": 1,
            }
            pending = state.pending

        if pending["hits"] < self.reacquire_frames:
            return False

        # Reacquired sides get a new identity; stale coordinates are not blended.
        state.track_id = self._next_track_id
        self._next_track_id += 1
        state.x_px = candidate["x_px"]
        state.velocity_px = 0.0
        state.angle_deg = candidate["angle_deg"]
        state.line_global = candidate["line_global"]
        state.age = 1
        state.missed_frames = 0
        state.pending = None
        state.observed = True
        return True

    def _miss(self, side):
        state = self._sides[side]
        state.observed = False
        state.missed_frames += 1
        state.age += 1
        state.velocity_px *= 0.86

    def _mark_observed(self, side, candidate):
        status = self._apply(side, candidate)
        return status != "PENDING"

    def _accept_pair(self, left, right, frame_width):
        left_state = self._sides["left"]
        right_state = self._sides["right"]
        prior = self._lane_width_px
        tolerance = max(
            frame_width * 0.045,
            min(frame_width * 0.12, (prior or (right["x_px"] - left["x_px"])) * 0.18),
        )
        left_ok = self._mark_observed("left", left)
        right_ok = self._mark_observed("right", right)
        expected_left = right["x_px"] - (prior or (right["x_px"] - left["x_px"]))
        expected_right = left["x_px"] + (prior or (right["x_px"] - left["x_px"]))
        if not left_ok:
            self._confirm_reacquisition("left", left, expected_left, tolerance)
        if not right_ok:
            self._confirm_reacquisition("right", right, expected_right, tolerance)
        left_visible = left_state.observed
        right_visible = right_state.observed
        return left_visible, right_visible

    def _attempt_missing_side(self, side, candidates, expected_x,
                              frame_width, preferred_index, hall_selected_index):
        state = self._sides[side]
        if self._lane_width_px is None:
            return False
        tolerance = max(
            frame_width * 0.045,
            min(frame_width * 0.12, self._lane_width_px * 0.18),
        )
        options = []
        for candidate in candidates:
            dx = abs(candidate["x_px"] - expected_x)
            if dx > tolerance:
                continue
            if state.x_px is not None:
                angle_delta = self._angle_delta(candidate["angle_deg"], state.angle_deg)
                if angle_delta > 42.0:
                    continue
            else:
                angle_delta = 0.0
            score = dx / max(1.0, tolerance) + angle_delta / 90.0
            score += (1.0 - candidate["quality"]) * 0.35
            if preferred_index is not None and candidate["index"] == preferred_index:
                score -= 0.08
            if hall_selected_index is not None and candidate["index"] == hall_selected_index:
                score -= 0.12
            options.append((score, candidate))
        if not options:
            state.pending = None
            return False
        options.sort(key=lambda item: item[0])
        candidate = options[0][1]
        return self._confirm_reacquisition(
            side, candidate, expected_x, tolerance
        )

    @staticmethod
    def _predicted_line(state, x_ref, y_ref, roi, fallback_angle=0.0):
        left, top, right, bottom = roi
        angle = state.angle_deg if state.x_px is not None else fallback_angle
        slope = math.tan(math.radians(float(angle)))
        return [
            float(x_ref + slope * (top - y_ref)), float(top),
            float(x_ref + slope * (bottom - y_ref)), float(bottom),
        ]

    def _side_payload(self, side, roi, y_ref, observed, inferred_x,
                      fallback_angle=0.0, hall_result=None):
        state = self._sides[side]
        line = state.line_global if observed else None
        x_px = state.x_px if observed else inferred_x
        if x_px is None:
            x_px = state.x_px
        inferred = bool(not observed and inferred_x is not None)
        if observed:
            status = "TRACKING"
        elif state.pending is not None:
            status = "REACQUIRING"
        elif inferred:
            status = "LOST · INFERRED"
        elif state.x_px is not None and state.missed_frames <= self.max_missed_frames:
            status = "COASTING"
        elif state.x_px is not None:
            status = "LOST"
        else:
            status = "UNINITIALIZED"
        predicted_line = None
        if x_px is not None:
            predicted_line = self._predicted_line(
                state, x_px, y_ref, roi, fallback_angle
            )
        hall_result = hall_result or {}
        return {
            "side": side,
            "status": status,
            "observed": bool(observed),
            "inferred": inferred,
            "track_id": int(state.track_id) if state.track_id is not None else None,
            "x_px": float(x_px) if x_px is not None else None,
            "line": [float(value) for value in line] if line else None,
            "predicted_line": predicted_line,
            "missed_frames": int(state.missed_frames),
            "pending_hits": int(state.pending["hits"]) if state.pending else 0,
            "pending_required": int(self.reacquire_frames),
            "candidate_count": int(hall_result.get("candidate_count", 0)),
            "matched_tracks": int(hall_result.get("matched_tracks", 0)),
            "hall_satisfied": bool(hall_result.get("hall_satisfied", True)),
            "hall_deficiency": int(hall_result.get("hall_deficiency", 0)),
        }

    def update(
        self,
        left_lines,
        right_lines,
        frame_shape,
        left_roi,
        right_roi,
        reference_center_x=None,
        left_preferred_index=None,
        right_preferred_index=None,
    ):
        """Update the joint lane model using two full-frame ROI definitions."""
        frame_height, frame_width = map(int, frame_shape[:2])
        frame_width = max(1, frame_width)
        frame_height = max(1, frame_height)
        left_box = self._roi_tuple(left_roi)
        right_box = self._roi_tuple(right_roi)
        overlap_top = max(left_box[1], right_box[1])
        overlap_bottom = min(left_box[3], right_box[3])
        if overlap_bottom > overlap_top:
            y_ref = 0.5 * (overlap_top + overlap_bottom)
        else:
            y_ref = 0.25 * (
                left_box[1] + left_box[3] + right_box[1] + right_box[3]
            )
        reference_x = (
            float(reference_center_x)
            if reference_center_x is not None
            else frame_width * 0.5
        )

        self._frame_index += 1
        left_hall, left_hall_selected = self._hall_update(
            "left", left_lines, left_box, left_preferred_index
        )
        right_hall, right_hall_selected = self._hall_update(
            "right", right_lines, right_box, right_preferred_index
        )
        left_candidates = self._candidates(
            left_lines, left_box, frame_width, y_ref, left_preferred_index
        )
        right_candidates = self._candidates(
            right_lines, right_box, frame_width, y_ref, right_preferred_index
        )
        left_hall["candidate_count"] = len(left_candidates)
        right_hall["candidate_count"] = len(right_candidates)
        left_ranked = self._ranked(
            "left", left_candidates, left_preferred_index,
            left_hall_selected, frame_width,
        )
        right_ranked = self._ranked(
            "right", right_candidates, right_preferred_index,
            right_hall_selected, frame_width,
        )

        left_observed = False
        right_observed = False
        inferred_side = None
        reacquired = False
        rejected_left = len(left_candidates)
        rejected_right = len(right_candidates)

        if self._lane_width_px is None:
            pair = self._initial_pair(
                left_ranked, right_ranked, frame_width, reference_x
            )
            if pair is not None:
                _score, left, right, _width = pair
                left_observed, right_observed = self._accept_pair(
                    left, right, frame_width
                )
                rejected_left = max(0, len(left_candidates) - 1)
                rejected_right = max(0, len(right_candidates) - 1)
            else:
                # One boundary alone cannot establish lane width safely.
                if left_ranked and self._sides["left"].x_px is None:
                    left_observed = self._mark_observed("left", left_ranked[0][1])
                if right_ranked and self._sides["right"].x_px is None:
                    right_observed = self._mark_observed("right", right_ranked[0][1])
        else:
            pair = self._best_pair(
                left_ranked, right_ranked, frame_width, reference_x
            )
            if pair is not None:
                _score, left, right, _width = pair
                before_left_missed = self._sides["left"].missed_frames
                before_right_missed = self._sides["right"].missed_frames
                left_observed, right_observed = self._accept_pair(
                    left, right, frame_width
                )
                reacquired = (
                    (before_left_missed > 0 and left_observed)
                    or (before_right_missed > 0 and right_observed)
                )
                rejected_left = max(0, len(left_candidates) - 1)
                rejected_right = max(0, len(right_candidates) - 1)
            else:
                # Keep the side with the stronger current identity. The
                # opposite side is inferred until a width-compatible candidate
                # passes consecutive-frame confirmation.
                active = []
                if left_ranked and self._sides["left"].x_px is not None:
                    if self._sides["left"].missed_frames == 0:
                        active.append(("left", left_ranked[0]))
                if right_ranked and self._sides["right"].x_px is not None:
                    if self._sides["right"].missed_frames == 0:
                        active.append(("right", right_ranked[0]))

                anchor_side = None
                anchor_candidate = None
                if active:
                    active.sort(key=lambda item: item[1][0])
                    anchor_side, (_cost, anchor_candidate) = active[0]

                if anchor_side == "left":
                    left_observed = self._mark_observed("left", anchor_candidate)
                    anchor_x = self._sides["left"].x_px
                    expected_right = anchor_x + self._lane_width_px
                    confirmed = self._attempt_missing_side(
                        "right", right_candidates, expected_right,
                        frame_width, right_preferred_index, right_hall_selected,
                    )
                    right_observed = bool(confirmed)
                    reacquired = right_observed
                    inferred_side = None if right_observed else "right"
                elif anchor_side == "right":
                    right_observed = self._mark_observed("right", anchor_candidate)
                    anchor_x = self._sides["right"].x_px
                    expected_left = anchor_x - self._lane_width_px
                    confirmed = self._attempt_missing_side(
                        "left", left_candidates, expected_left,
                        frame_width, left_preferred_index, left_hall_selected,
                    )
                    left_observed = bool(confirmed)
                    reacquired = left_observed
                    inferred_side = None if left_observed else "left"

        for side, observed in (("left", left_observed), ("right", right_observed)):
            if not observed:
                self._miss(side)
        if left_observed:
            self._sides["left"].observed = True
        if right_observed:
            self._sides["right"].observed = True

        if left_observed and right_observed:
            left_x = self._sides["left"].x_px
            right_x = self._sides["right"].x_px
            measured_width = right_x - left_x
            if measured_width > frame_width * 0.12:
                if self._lane_width_px is None:
                    self._lane_width_px = measured_width
                else:
                    self._lane_width_px = 0.88 * self._lane_width_px + 0.12 * measured_width
            lane_center_x = (left_x + right_x) * 0.5
            lane_type = "both"
            state_name = "REACQUIRING" if reacquired else "TRACKING"
            perception_valid = True
            quality = 0.88
            speed_factor = 1.0
            inferred_side = None
            previous_center = self._last_lane_center_px
            if previous_center is not None:
                self._last_lane_center_velocity_px = (
                    0.70 * self._last_lane_center_velocity_px
                    + 0.30 * (lane_center_x - previous_center)
                )
            self._last_lane_center_px = lane_center_x
        elif self._lane_width_px is not None and (left_observed or right_observed):
            if left_observed:
                visible_x = self._sides["left"].x_px
                inferred_right_x = visible_x + self._lane_width_px
                lane_center_x = 0.5 * (visible_x + inferred_right_x)
                lane_type = "only_left"
                inferred_side = "right"
                state_name = (
                    "REACQUIRING_RIGHT"
                    if self._sides["right"].pending else "SINGLE_SIDE_LEFT"
                )
            else:
                visible_x = self._sides["right"].x_px
                inferred_left_x = visible_x - self._lane_width_px
                lane_center_x = 0.5 * (inferred_left_x + visible_x)
                lane_type = "only_right"
                inferred_side = "left"
                state_name = (
                    "REACQUIRING_LEFT"
                    if self._sides["left"].pending else "SINGLE_SIDE_RIGHT"
                )
            perception_valid = True
            quality = 0.58
            speed_factor = 0.55
            if self._last_lane_center_px is not None:
                self._last_lane_center_velocity_px = (
                    0.75 * self._last_lane_center_velocity_px
                    + 0.25 * (lane_center_x - self._last_lane_center_px)
                )
            self._last_lane_center_px = lane_center_x
        else:
            max_missed = max(
                self._sides["left"].missed_frames,
                self._sides["right"].missed_frames,
            )
            if (
                self._last_lane_center_px is not None
                and max_missed <= self.max_missed_frames
            ):
                lane_center_x = (
                    self._last_lane_center_px + self._last_lane_center_velocity_px
                )
                self._last_lane_center_px = lane_center_x
                self._last_lane_center_velocity_px *= 0.65
                state_name = "COASTING"
                lane_type = "none"
                perception_valid = True
                quality = max(
                    0.10,
                    0.35 * (1.0 - max_missed / (self.max_missed_frames + 1)),
                )
                speed_factor = 0.25
            else:
                lane_center_x = None
                state_name = "LOST" if self._lane_width_px is not None else "ACQUIRING_PAIR"
                lane_type = "none"
                perception_valid = False
                quality = 0.0
                speed_factor = 0.0

        reference_x = (
            float(reference_center_x)
            if reference_center_x is not None
            else frame_width * 0.5
        )
        lane_error_px = (
            float(lane_center_x - reference_x)
            if lane_center_x is not None else None
        )
        fallback_angle = (
            self._sides["right"].angle_deg
            if self._sides["right"].x_px is not None
            else self._sides["left"].angle_deg
        )
        left_inferred_x = None
        right_inferred_x = None
        if inferred_side == "left" and right_observed and self._lane_width_px is not None:
            left_inferred_x = self._sides["right"].x_px - self._lane_width_px
        elif inferred_side == "right" and left_observed and self._lane_width_px is not None:
            right_inferred_x = self._sides["left"].x_px + self._lane_width_px
        elif state_name == "COASTING" and lane_center_x is not None and self._lane_width_px is not None:
            left_inferred_x = lane_center_x - self._lane_width_px * 0.5
            right_inferred_x = lane_center_x + self._lane_width_px * 0.5

        left_payload = self._side_payload(
            "left", left_box, y_ref, left_observed,
            left_inferred_x, fallback_angle, left_hall,
        )
        right_payload = self._side_payload(
            "right", right_box, y_ref, right_observed,
            right_inferred_x, fallback_angle, right_hall,
        )
        hall_satisfied = bool(
            left_hall.get("hall_satisfied", True)
            and right_hall.get("hall_satisfied", True)
        )
        hall_deficiency = (
            int(left_hall.get("hall_deficiency", 0))
            + int(right_hall.get("hall_deficiency", 0))
        )
        return {
            "enabled": True,
            "state": state_name,
            "lane_type": lane_type,
            "perception_valid": bool(perception_valid),
            "perception_quality": float(quality),
            "speed_factor": float(speed_factor),
            "lane_center_px": float(lane_center_x) if lane_center_x is not None else None,
            "lane_error_px": lane_error_px,
            "reference_center_x": float(reference_x),
            "y_ref_px": float(y_ref),
            "lane_width_px": float(self._lane_width_px) if self._lane_width_px is not None else None,
            "inferred_side": inferred_side,
            "reacquire_frames": int(self.reacquire_frames),
            "hall_satisfied": hall_satisfied,
            "hall_applicable": bool(
                left_hall.get("hall_applicable", False)
                or right_hall.get("hall_applicable", False)
            ),
            "hall_deficiency": int(hall_deficiency),
            "left": left_payload,
            "right": right_payload,
            "candidate_count": {
                "left": len(left_candidates),
                "right": len(right_candidates),
            },
            "rejected_count": {
                "left": int(rejected_left),
                "right": int(rejected_right),
            },
            "matched_tracks": {
                "left": int(left_hall.get("matched_tracks", 0)),
                "right": int(right_hall.get("matched_tracks", 0)),
            },
        }
