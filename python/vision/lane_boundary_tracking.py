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
        self.reacquire_frames = max(1, int(reacquire_frames))
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
        self._lane_width_profile = None
        self._geometry_mode = None
        self._roi_signature = None
        self._last_lane_center_px = None
        self._last_lane_center_velocity_px = 0.0
        self._frame_index = 0
        self._reacquiring_pair = False
        self._pair_pending = None

    def _clear_lane_model(self):
        """Clear stale geometry while preserving the active ROI and transform mode."""
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
        self._lane_width_profile = None
        self._last_lane_center_px = None
        self._last_lane_center_velocity_px = 0.0

    def reset(self):
        """Forget lane geometry, ROI identity, and all temporal associations."""
        self._clear_lane_model()
        self._roi_signature = None
        self._frame_index = 0
        self._reacquiring_pair = False
        self._pair_pending = None

    def set_geometry_mode(self, mode):
        """Reset stale lane state when switching between BEV and perspective."""
        value = str(mode or "perspective").strip().lower()
        normalized = "bev" if value in {
            "bev", "birdseye", "bird's-eye", "birdseyeview"
        } else "perspective"
        if self._geometry_mode is not None and self._geometry_mode != normalized:
            self.reset()
        self._geometry_mode = normalized
        return normalized

    def set_roi_configuration(self, left_roi, right_roi, frame_shape):
        """Invalidate old tracks if the user's ROI geometry or frame size changes."""
        height, width = map(int, frame_shape[:2])
        signature = (
            self._roi_tuple(left_roi),
            self._roi_tuple(right_roi),
            width,
            height,
        )
        if self._roi_signature is not None and signature != self._roi_signature:
            geometry_mode = self._geometry_mode
            self.reset()
            self._geometry_mode = geometry_mode
        self._roi_signature = signature
        return signature

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
            # Hough endpoints are local to the crop, but extrapolating a short
            # segment to y_ref can place its lane point outside that crop.
            # Such a line must not be treated as a detection for this ROI.
            if (
                not math.isfinite(x_ref)
                or not 0 <= x_ref < frame_width
                or x_ref < left
                or x_ref >= right
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

    def _hall_update(self, side, lines, roi, preferred_index, frame_shape):
        """Associate Hall segments in stable full-frame coordinates.

        Recovery crops change size and origin as the search expands. Passing
        crop-local coordinates to HallLineTracker would make a stationary line
        appear to move when the crop changes. Translate every segment first.
        """
        left, top, _right, _bottom = roi
        frame_height, frame_width = map(int, frame_shape[:2])
        source = [] if lines is None else list(lines)
        global_lines = []
        for line in source:
            try:
                values = np.asarray(line, dtype=np.float64).reshape(-1)
                if values.size < 4 or not np.isfinite(values[:4]).all():
                    global_lines.append(line)
                    continue
                x1, y1, x2, y2 = map(float, values[:4])
                global_lines.append((
                    x1 + left, y1 + top, x2 + left, y2 + top,
                ))
            except (TypeError, ValueError, OverflowError):
                # Preserve the original index; HallLineTracker rejects malformed
                # segments itself, and candidate indices must remain aligned.
                global_lines.append(line)
        hall = self._hall[side]
        hall.max_missed_frames = self.max_missed_frames
        result = hall.update(
            global_lines,
            max(1, frame_width),
            max(1, frame_height),
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
            angle_reference = state.angle_deg
            opposite = self._sides["right" if state is self._sides["left"] else "left"]
            if opposite.observed and opposite.line_global is not None:
                ox1, oy1, ox2, oy2 = opposite.line_global
                angle_reference = math.degrees(math.atan2(ox2 - ox1, oy2 - oy1))
            angle_delta = self._angle_delta(candidate["angle_deg"], angle_reference)
            missed_growth = min(frame_width * 0.12,
                                frame_width * 0.018 * state.missed_frames)
            gate = max(
                frame_width * 0.045,
                min(frame_width * 0.15,
                    frame_width * 0.045 + abs(state.velocity_px) * 0.65),
            ) + missed_growth
            if dx > gate or angle_delta > (34.0 if state.missed_frames == 0 else 42.0):
                # A returning track may move farther while occluded, but the
                # gate remains bounded and its angle must still be plausible.
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

    @staticmethod
    def _line_x_at(line, y):
        if not line:
            return None
        x1, y1, x2, y2 = map(float, line)
        if abs(y2 - y1) < 1e-6:
            return (x1 + x2) * 0.5
        return x1 + (y - y1) * (x2 - x1) / (y2 - y1)

    @staticmethod
    def _reference_row(left_box, right_box):
        """Return the common look-ahead row used by both lane boundaries."""
        overlap_top = max(left_box[1], right_box[1])
        overlap_bottom = min(left_box[3], right_box[3])
        if overlap_bottom > overlap_top:
            return 0.5 * (overlap_top + overlap_bottom)
        return 0.25 * (
            left_box[1] + left_box[3] + right_box[1] + right_box[3]
        )

    def _width_at(self, y, frame_height):
        if self._lane_width_px is None:
            return None
        if self._geometry_mode == "bev":
            return self._lane_width_px
        profile = self._lane_width_profile
        if not profile:
            return None
        ratio = float(y) / max(1.0, float(frame_height))
        keys = sorted(profile)
        if ratio <= keys[0]:
            return profile[keys[0]]
        if ratio >= keys[-1]:
            return profile[keys[-1]]
        for low, high in zip(keys, keys[1:]):
            if low <= ratio <= high:
                amount = (ratio - low) / (high - low)
                return profile[low] * (1.0 - amount) + profile[high] * amount
        return self._lane_width_px

    def _learn_width_profile(self, frame_height, y_ref):
        left = self._sides["left"].line_global
        right = self._sides["right"].line_global
        if not left or not right:
            return
        if self._geometry_mode == "bev":
            # The road plane is rectified: lane separation is one BEV-space
            # distance, not a perspective-dependent function of image row.
            self._lane_width_profile = None
            return

        profile = dict(self._lane_width_profile or {})
        common_top = max(min(left[1], left[3]), min(right[1], right[3]))
        common_bottom = min(max(left[1], left[3]), max(right[1], right[3]))
        if common_bottom <= common_top:
            return
        for offset in (-0.12, 0.0, 0.12):
            y = min(common_bottom, max(common_top, y_ref + offset * frame_height))
            lx, rx = self._line_x_at(left, y), self._line_x_at(right, y)
            if lx is None or rx is None:
                continue
            width = rx - lx
            if width <= 0:
                continue
            key = y / max(1.0, float(frame_height))
            profile[key] = (
                width if key not in profile
                else 0.85 * profile[key] + 0.15 * width
            )
        if len(profile) >= 2:
            self._lane_width_profile = profile

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

    def _confirm_pair_reacquisition(self, pair, frame_width):
        """Require a stable lane pair before replacing a completely lost model."""
        _score, left, right, width = pair
        current = {
            "left_x": float(left["x_px"]),
            "right_x": float(right["x_px"]),
            "width": float(width),
            "left_angle": float(left["angle_deg"]),
            "right_angle": float(right["angle_deg"]),
            "hits": 1,
        }
        previous = self._pair_pending
        if previous is not None:
            position_tolerance = max(frame_width * 0.035, previous["width"] * 0.10)
            width_tolerance = max(frame_width * 0.025, previous["width"] * 0.08)
            consistent = (
                abs(current["left_x"] - previous["left_x"]) <= position_tolerance
                and abs(current["right_x"] - previous["right_x"]) <= position_tolerance
                and abs(current["width"] - previous["width"]) <= width_tolerance
                and self._angle_delta(current["left_angle"], previous["left_angle"]) <= 18.0
                and self._angle_delta(current["right_angle"], previous["right_angle"]) <= 18.0
            )
            if consistent:
                current["hits"] = previous["hits"] + 1

        self._pair_pending = current
        return current["hits"] >= self.reacquire_frames

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

        # Keep the identity while a known side is coasting. Allocate a new ID
        # only when this side has never had a confirmed track.
        if state.track_id is None:
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
                              frame_width, preferred_index, hall_selected_index,
                              frame_height):
        state = self._sides[side]
        if self._lane_width_px is None or expected_x is None:
            return False
        if not math.isfinite(float(expected_x)):
            return False
        anchor = self._sides["right" if side == "left" else "left"]
        tolerance = max(
            frame_width * 0.045,
            min(frame_width * 0.12, self._lane_width_px * 0.18),
        )
        options = []
        for candidate in candidates:
            dx = abs(candidate["x_px"] - expected_x)
            if dx > tolerance:
                continue
            if anchor.x_px is not None:
                # The visible side's current tangent is a better geometric
                # reference than the missing side's stale angle.
                anchor_angle = anchor.angle_deg
                if anchor.line_global is not None:
                    ax1, ay1, ax2, ay2 = anchor.line_global
                    anchor_angle = math.degrees(math.atan2(ax2 - ax1, ay2 - ay1))
                angle_delta = self._angle_delta(candidate["angle_deg"], anchor_angle)
                if angle_delta > 42.0:
                    continue
            else:
                angle_delta = 0.0
            profile_residual = 0.0
            if anchor.line_global is not None:
                x1, y1, x2, y2 = candidate["line_global"]
                sample_rows = [y1 + (y2 - y1) * fraction for fraction in (0.2, 0.5, 0.8)]
                residuals = []
                for row in sample_rows:
                    anchor_x = self._line_x_at(anchor.line_global, row)
                    candidate_x = self._line_x_at(candidate["line_global"], row)
                    width_here = self._width_at(row, frame_height) or self._lane_width_px
                    expected_here = anchor_x + (width_here if side == "right" else -width_here)
                    residuals.append(abs(candidate_x - expected_here))
                profile_residual = sum(residuals) / max(1, len(residuals))
                if profile_residual > max(tolerance * 1.6, frame_width * 0.08):
                    continue
            score = (
                0.42 * dx / max(1.0, tolerance)
                + 0.20 * min(1.5, angle_delta / 35.0)
                + 0.22 * min(1.5, profile_residual / max(1.0, tolerance))
                + 0.16 * (1.0 - candidate["quality"])
            )
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

    def _boundary_x_from_anchor(self, anchor_side, target_side, y, y_ref,
                                frame_height, predict_next_frame=False):
        """Predict the other boundary in the active BEV/perspective geometry."""
        anchor = self._sides[anchor_side]
        if anchor.x_px is None:
            return None
        width = self._width_at(y, frame_height)
        if width is None:
            return None
        slope = 0.0
        if anchor.line_global is not None:
            x1, y1, x2, y2 = anchor.line_global
            if abs(y2 - y1) > 1e-6:
                slope = (x2 - x1) / (y2 - y1)
        anchor_x = anchor.x_px + slope * (float(y) - float(y_ref))
        if predict_next_frame:
            anchor_x += anchor.velocity_px
        direction = 1.0 if target_side == "right" else -1.0
        return float(anchor_x + direction * width)

    def _inferred_boundary_points(self, side, anchor_side, roi, y_ref,
                                  frame_height, samples=7):
        """Sample inferred boundary points from the learned geometry model."""
        _left, top, _right, bottom = roi
        # ROI bottom is exclusive (NumPy slice semantics); keep samples on
        # the final valid image row rather than one pixel outside the crop.
        rows = np.linspace(float(top), float(max(top, bottom - 1)), max(2, int(samples)))
        points = []
        for y in rows:
            x = self._boundary_x_from_anchor(
                anchor_side, side, float(y), y_ref, frame_height
            )
            if x is None or not math.isfinite(x):
                return []
            points.append([float(x), float(y)])
        return points

    @staticmethod
    def _points_to_line(points):
        if len(points) < 2:
            return None
        return [
            float(points[0][0]), float(points[0][1]),
            float(points[-1][0]), float(points[-1][1]),
        ]

    @staticmethod
    def _predicted_line(state, x_ref, y_ref, roi, fallback_angle=0.0):
        left, top, right, bottom = roi
        angle = fallback_angle if fallback_angle is not None else state.angle_deg
        slope = math.tan(math.radians(float(angle)))
        return [
            float(x_ref + slope * (top - y_ref)), float(top),
            float(x_ref + slope * (bottom - y_ref)), float(bottom),
        ]

    def _side_payload(self, side, roi, y_ref, observed, inferred_x,
                      fallback_angle=0.0, hall_result=None, anchor_side=None,
                      frame_height=None):
        state = self._sides[side]
        line = state.line_global if observed else None
        x_px = state.x_px if observed else inferred_x
        if x_px is None:
            x_px = state.x_px
        inferred = bool(not observed and inferred_x is not None)
        if observed:
            status = "DETECTED"
        elif state.pending is not None:
            status = "REACQUIRING"
        elif inferred:
            status = "INFERRED"
        elif state.x_px is not None and state.missed_frames <= self.max_missed_frames:
            status = "PREDICTED"
        elif state.x_px is not None:
            status = "LOST"
        else:
            status = "UNINITIALIZED"

        predicted_points = []
        if inferred and anchor_side is not None and frame_height is not None:
            predicted_points = self._inferred_boundary_points(
                side, anchor_side, roi, y_ref, frame_height
            )
            roi_left, roi_top, roi_right, roi_bottom = roi
            points_inside = (
                len(predicted_points) >= 2
                and all(
                    roi_left <= point[0] < roi_right
                    and roi_top <= point[1] < roi_bottom
                    for point in predicted_points
                )
            )
            # Never emit an INFERRED boundary whose displayed/search geometry is
            # outside the actual detector crop. Fall back to the ordinary
            # missing/predicted state and let the caller coast or stop safely.
            if not points_inside:
                inferred = False
                inferred_x = None
                x_px = state.x_px
                status = (
                    "PREDICTED"
                    if state.x_px is not None
                    and state.missed_frames <= self.max_missed_frames
                    else "LOST" if state.x_px is not None else "UNINITIALIZED"
                )
                predicted_points = []
        predicted_line = self._points_to_line(predicted_points)
        if predicted_line is None and x_px is not None and (
            not inferred and state.missed_frames <= self.max_missed_frames
        ):
            predicted_line = self._predicted_line(
                state, x_px, y_ref, roi, state.angle_deg
            )
        roi_left, roi_top, roi_right, roi_bottom = roi
        inside_search_roi = bool(
            x_px is not None
            and roi_left <= x_px < roi_right
            and roi_top <= y_ref < roi_bottom
        )
        roi_edge_distances = (
            {
                "left_px": float(x_px - roi_left),
                "right_px": float((roi_right - 1) - x_px),
            }
            if x_px is not None else None
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
            "predicted_points": predicted_points,
            "search_roi": [int(value) for value in roi],
            "inside_search_roi": inside_search_roi,
            "roi_edge_distances_px": roi_edge_distances,
            "inference_valid": bool(inferred),
            "expected_x": float(inferred_x) if inferred_x is not None else None,
            "reacquiring_line": (
                self._predicted_line(state, state.pending["x_px"], y_ref, roi,
                                     state.pending["angle_deg"])
                if state.pending is not None else None
            ),
            "missed_frames": int(state.missed_frames),
            "pending_hits": int(state.pending["hits"]) if state.pending else 0,
            "pending_required": int(self.reacquire_frames),
            "candidate_count": int(hall_result.get("candidate_count", 0)),
            "matched_tracks": int(hall_result.get("matched_tracks", 0)),
            "hall_satisfied": bool(hall_result.get("hall_satisfied", True)),
            "hall_deficiency": int(hall_result.get("hall_deficiency", 0)),
        }

    def recovery_rois(self, left_roi, right_roi, frame_shape,
                     max_expansion_fraction=0.18, geometry_mode=None):
        """Return bounded recovery crops justified by the current lane geometry.

        The user's configured ROI is never modified. While one boundary is
        visible, its tangent and the active BEV/perspective width model predict
        the missing boundary. The search crop may expand only by a bounded
        amount and only when every predicted sample remains inside it.

        After both previously tracked boundaries have exceeded the coast window,
        stale geometry is retired and both ROIs become a temporary full-width
        pair reacquisition band. A new pair is then confirmed over consecutive
        frames by update().
        """
        if geometry_mode is not None:
            self.set_geometry_mode(geometry_mode)
        elif self._geometry_mode is None:
            self.set_geometry_mode("perspective")

        frame_height, frame_width = map(int, frame_shape[:2])
        frame_height = max(1, frame_height)
        frame_width = max(1, frame_width)
        self.set_roi_configuration(left_roi, right_roi, frame_shape)
        boxes = {
            "left": self._roi_tuple(left_roi),
            "right": self._roi_tuple(right_roi),
        }

        previously_learned = (
            self._lane_width_px is not None
            and self._last_lane_center_px is not None
            and all(
                state.track_id is not None
                and state.missed_frames > self.max_missed_frames
                for state in self._sides.values()
            )
        )
        if previously_learned and not self._reacquiring_pair:
            self._reacquiring_pair = True
            self._pair_pending = None

        if self._reacquiring_pair:
            left_box, right_box = boxes["left"], boxes["right"]
            overlap_top = max(left_box[1], right_box[1])
            overlap_bottom = min(left_box[3], right_box[3])
            if overlap_bottom <= overlap_top:
                overlap_top = min(left_box[1], right_box[1])
                overlap_bottom = max(left_box[3], right_box[3])
            pair_roi = (0, overlap_top, frame_width, overlap_bottom)
            return {
                side: {
                    "roi": pair_roi,
                    "configured_roi": boxes[side],
                    "expanded": pair_roi != boxes[side],
                    "expected_x": None,
                    "expected_points": [],
                    "prediction_valid": False,
                    "pair_reacquire": True,
                    "missed_frames": int(self._sides[side].missed_frames),
                    "max_expansion_px": 0,
                    "edge_distances_px": None,
                    "reason": "full_frame_pair_reacquisition",
                    "geometry_mode": self._geometry_mode,
                }
                for side in ("left", "right")
            }

        try:
            expansion_fraction = float(max_expansion_fraction)
        except (TypeError, ValueError, OverflowError):
            expansion_fraction = 0.18
        if not math.isfinite(expansion_fraction):
            expansion_fraction = 0.18
        expansion_fraction = max(0.02, min(0.35, expansion_fraction))

        y_ref = self._reference_row(boxes["left"], boxes["right"])
        results = {}

        for side in ("left", "right"):
            box = boxes[side]
            state = self._sides[side]
            anchor_side = "right" if side == "left" else "left"
            anchor = self._sides[anchor_side]
            base_width = max(1, box[2] - box[0])
            max_extra = min(
                frame_width * expansion_fraction,
                max(base_width * 0.75, frame_width * 0.05),
            )

            sample_y = np.linspace(
                float(box[1]), float(max(box[1], box[3] - 1)), 7
            )

            # Hysteresis: when a line was recovered outside (or very near the
            # edge of) the configured ROI, keep detecting it in a bounded
            # corridor on following frames. Shrinking to the user's base crop
            # immediately after one successful frame creates a deterministic
            # one-frame TRACKING / next-frame LOST oscillation.
            if (
                state.observed
                and state.track_id is not None
                and state.line_global is not None
                and state.pending is None
            ):
                track_x = []
                for y in sample_y:
                    value = self._line_x_at(state.line_global, float(y))
                    if value is not None and math.isfinite(value):
                        track_x.append(
                            float(value + state.velocity_px)
                        )
                if len(track_x) == len(sample_y):
                    hold_margin = max(3.0, base_width * 0.08)
                    desired_left = min(float(box[0]), min(track_x) - hold_margin)
                    desired_right = max(float(box[2]), max(track_x) + hold_margin)
                    search_left = max(
                        0,
                        int(math.floor(max(float(box[0]) - max_extra, desired_left))),
                    )
                    search_right = min(
                        frame_width,
                        int(math.ceil(min(float(box[2]) + max_extra, desired_right))),
                    )
                    search_roi = (
                        search_left, int(box[1]),
                        max(search_left + 1, search_right), int(box[3]),
                    )
                    corridor_inside = (
                        all(0.0 <= x < float(frame_width) for x in track_x)
                        and all(
                            search_roi[0] <= x < search_roi[2]
                            and search_roi[1] <= y < search_roi[3]
                            for x, y in zip(track_x, sample_y)
                        )
                    )
                    if corridor_inside:
                        expanded = search_roi != box
                        results[side] = {
                            "roi": search_roi,
                            "configured_roi": box,
                            "expanded": expanded,
                            "expected_x": float(state.x_px + state.velocity_px),
                            "expected_points": [
                                [float(x), float(y)]
                                for x, y in zip(track_x, sample_y)
                            ],
                            "prediction_valid": True,
                            "pair_reacquire": False,
                            "missed_frames": 0,
                            "max_expansion_px": float(max_extra),
                            "edge_distances_px": {
                                "to_outer_edge_px": (
                                    float(state.x_px - box[0])
                                    if side == "left"
                                    else float((box[2] - 1) - state.x_px)
                                ),
                                "to_inner_edge_px": (
                                    float((box[2] - 1) - state.x_px)
                                    if side == "left"
                                    else float(state.x_px - box[0])
                                ),
                                "outside_left_px": max(
                                    0.0, float(box[0]) - min(track_x)
                                ),
                                "outside_right_px": max(
                                    0.0, max(track_x) - float(box[2] - 1)
                                ),
                            },
                            "reason": (
                                "observed_track_hysteresis"
                                if expanded else "tracking"
                            ),
                            "geometry_mode": self._geometry_mode,
                        }
                        continue

            if state.missed_frames == 0 and state.pending is None:
                results[side] = {
                    "roi": box,
                    "configured_roi": box,
                    "expanded": False,
                    "expected_x": state.x_px,
                    "expected_points": [],
                    "prediction_valid": True,
                    "pair_reacquire": False,
                    "missed_frames": 0,
                    "max_expansion_px": float(max_extra),
                    "edge_distances_px": None,
                    "reason": "tracking",
                    "geometry_mode": self._geometry_mode,
                }
                continue

            sample_x = []
            expected = None
            has_anchor_prediction = (
                self._lane_width_px is not None
                and anchor.observed
                and anchor.x_px is not None
            )

            if has_anchor_prediction:
                for y in sample_y:
                    value = self._boundary_x_from_anchor(
                        anchor_side, side, float(y), y_ref, frame_height,
                        predict_next_frame=True,
                    )
                    if value is not None and math.isfinite(value):
                        sample_x.append(float(value))
                expected = self._boundary_x_from_anchor(
                    anchor_side, side, y_ref, y_ref, frame_height,
                    predict_next_frame=True,
                )
            elif state.track_id is not None and state.x_px is not None:
                slope = 0.0
                if state.line_global is not None:
                    x1, y1, x2, y2 = state.line_global
                    if abs(y2 - y1) > 1e-6:
                        slope = (x2 - x1) / (y2 - y1)
                expected = float(state.x_px + state.velocity_px)
                sample_x = [
                    expected + slope * (float(y) - y_ref)
                    for y in sample_y
                ]

            if (
                expected is None
                or not math.isfinite(float(expected))
                or len(sample_x) != len(sample_y)
            ):
                results[side] = {
                    "roi": box,
                    "configured_roi": box,
                    "expanded": False,
                    "expected_x": None,
                    "expected_points": [],
                    "prediction_valid": False,
                    "pair_reacquire": False,
                    "missed_frames": int(state.missed_frames),
                    "max_expansion_px": float(max_extra),
                    "edge_distances_px": None,
                    "reason": "no_confirmed_geometric_prediction",
                    "geometry_mode": self._geometry_mode,
                }
                continue

            inside_frame = all(
                0.0 <= x < float(frame_width) for x in sample_x
            )
            # Signed distances from the predicted reference point to the
            # configured ROI's outer and inner vertical edges.
            if side == "left":
                outer_distance = float(expected - box[0])
                inner_distance = float((box[2] - 1) - expected)
            else:
                inner_distance = float(expected - box[0])
                outer_distance = float((box[2] - 1) - expected)
            outside_left = max(0.0, float(box[0]) - min(sample_x))
            outside_right = max(0.0, max(sample_x) - float(box[2] - 1))
            edge_distances = {
                "to_outer_edge_px": outer_distance,
                "to_inner_edge_px": inner_distance,
                "outside_left_px": outside_left,
                "outside_right_px": outside_right,
            }

            prediction_valid = (
                inside_frame
                and outside_left <= max_extra
                and outside_right <= max_extra
            )
            if not prediction_valid:
                results[side] = {
                    "roi": box,
                    "configured_roi": box,
                    "expanded": False,
                    "expected_x": float(expected),
                    "expected_points": [
                        [float(x), float(y)]
                        for x, y in zip(sample_x, sample_y)
                    ],
                    "prediction_valid": False,
                    "pair_reacquire": False,
                    "missed_frames": int(state.missed_frames),
                    "max_expansion_px": float(max_extra),
                    "edge_distances_px": edge_distances,
                    "reason": "predicted_boundary_outside_recovery_limit",
                    "geometry_mode": self._geometry_mode,
                }
                continue

            miss_count = max(1, int(state.missed_frames))
            miss_growth = min(0.12, 0.025 * max(0, miss_count - 1))
            margin = max(
                3.0,
                base_width * (0.08 + miss_growth)
                + min(base_width * 0.20, abs(state.velocity_px) * 0.60),
            )
            desired_left = min(float(box[0]), min(sample_x) - margin)
            desired_right = max(float(box[2]), max(sample_x) + margin)
            search_left = max(
                0,
                int(math.floor(max(float(box[0]) - max_extra, desired_left))),
            )
            search_right = min(
                frame_width,
                int(math.ceil(min(float(box[2]) + max_extra, desired_right))),
            )
            search_roi = (
                search_left, int(box[1]),
                max(search_left + 1, search_right), int(box[3]),
            )
            samples_contained = all(
                search_roi[0] <= x < search_roi[2]
                and search_roi[1] <= y < search_roi[3]
                for x, y in zip(sample_x, sample_y)
            )
            if not samples_contained:
                search_roi = box
                prediction_valid = False
                reason = "predicted_boundary_not_contained"
            else:
                reason = (
                    "predicted_track_recovery"
                    if search_roi != box else "prediction_inside_configured_roi"
                )

            results[side] = {
                "roi": search_roi,
                "configured_roi": box,
                "expanded": search_roi != box,
                "expected_x": float(expected),
                "expected_points": [
                    [float(x), float(y)]
                    for x, y in zip(sample_x, sample_y)
                ],
                "prediction_valid": bool(prediction_valid),
                "pair_reacquire": False,
                "missed_frames": int(state.missed_frames),
                "max_expansion_px": float(max_extra),
                "edge_distances_px": edge_distances,
                "reason": reason,
                "geometry_mode": self._geometry_mode,
            }
        return results

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
        geometry_mode=None,
        left_prediction_valid=True,
        right_prediction_valid=True,
        enable_full_pair_reacquisition=False,
        max_inferred_frames=None,
    ):
        """Update the joint lane model using two full-frame ROI definitions."""
        if geometry_mode is not None:
            self.set_geometry_mode(geometry_mode)
        elif self._geometry_mode is None:
            self.set_geometry_mode("perspective")
        frame_height, frame_width = map(int, frame_shape[:2])
        frame_width = max(1, frame_width)
        frame_height = max(1, frame_height)
        left_box = self._roi_tuple(left_roi)
        right_box = self._roi_tuple(right_roi)
        y_ref = self._reference_row(left_box, right_box)
        if (
            enable_full_pair_reacquisition
            and self._lane_width_px is not None
            and all(
                state.track_id is not None
                and state.missed_frames > self.max_missed_frames
                for state in self._sides.values()
            )
            and not self._reacquiring_pair
        ):
            self._reacquiring_pair = True
            self._pair_pending = None
        if self._reacquiring_pair and self._lane_width_px is not None:
            # Both old boundaries have expired. Do not keep gating new lines
            # against their stale IDs, width, tangent, or lane-centre velocity.
            self._clear_lane_model()

        reference_x = (
            float(reference_center_x)
            if reference_center_x is not None
            else frame_width * 0.5
        )

        self._frame_index += 1
        left_hall, left_hall_selected = self._hall_update(
            "left", left_lines, left_box, left_preferred_index, frame_shape
        )
        right_hall, right_hall_selected = self._hall_update(
            "right", right_lines, right_box, right_preferred_index, frame_shape
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
            if self._reacquiring_pair:
                if pair is not None and self._confirm_pair_reacquisition(
                    pair, frame_width
                ):
                    _score, left, right, _width = pair
                    left_observed, right_observed = self._accept_pair(
                        left, right, frame_width
                    )
                    self._reacquiring_pair = False
                    self._pair_pending = None
                    reacquired = True
                    rejected_left = max(0, len(left_candidates) - 1)
                    rejected_right = max(0, len(right_candidates) - 1)
                elif pair is None:
                    self._pair_pending = None
            elif pair is not None:
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
                    active.append(("left", left_ranked[0]))
                if right_ranked and self._sides["right"].x_px is not None:
                    active.append(("right", right_ranked[0]))

                anchor_side = None
                anchor_candidate = None
                if active:
                    active.sort(key=lambda item: item[1][0])
                    anchor_side, (_cost, anchor_candidate) = active[0]

                if anchor_side == "left":
                    left_state = self._sides["left"]
                    if left_state.missed_frames:
                        tolerance = max(frame_width * 0.045, self._lane_width_px * 0.18)
                        left_observed = self._confirm_reacquisition(
                            "left", anchor_candidate,
                            left_state.x_px + left_state.velocity_px,
                            tolerance,
                        )
                        reacquired = left_observed
                    else:
                        left_observed = self._mark_observed("left", anchor_candidate)
                    anchor_x = self._sides["left"].x_px
                    width_at_reference = self._width_at(y_ref, frame_height)
                    expected_right = (
                        anchor_x + width_at_reference
                        if width_at_reference is not None else None
                    )
                    confirmed = (
                        self._attempt_missing_side(
                            "right", right_candidates, expected_right,
                            frame_width, right_preferred_index, right_hall_selected,
                            frame_height,
                        )
                        if expected_right is not None and right_prediction_valid else False
                    )
                    right_observed = bool(confirmed)
                    reacquired = right_observed
                    inferred_side = None if right_observed else "right"
                elif anchor_side == "right":
                    right_state = self._sides["right"]
                    if right_state.missed_frames:
                        tolerance = max(frame_width * 0.045, self._lane_width_px * 0.18)
                        right_observed = self._confirm_reacquisition(
                            "right", anchor_candidate,
                            right_state.x_px + right_state.velocity_px,
                            tolerance,
                        )
                        reacquired = right_observed
                    else:
                        right_observed = self._mark_observed("right", anchor_candidate)
                    anchor_x = self._sides["right"].x_px
                    width_at_reference = self._width_at(y_ref, frame_height)
                    expected_left = (
                        anchor_x - width_at_reference
                        if width_at_reference is not None else None
                    )
                    confirmed = (
                        self._attempt_missing_side(
                            "left", left_candidates, expected_left,
                            frame_width, left_preferred_index, left_hall_selected,
                            frame_height,
                        )
                        if expected_left is not None and left_prediction_valid else False
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
            self._learn_width_profile(frame_height, y_ref)
        elif (
            self._lane_width_px is not None
            and self._width_at(y_ref, frame_height) is not None
            and (left_observed or right_observed)
            and (
                (left_observed
                 and right_prediction_valid
                 and (
                     max_inferred_frames is None
                     or self._sides["right"].missed_frames
                        <= max(1, int(max_inferred_frames))
                 ))
                or
                (right_observed
                 and left_prediction_valid
                 and (
                     max_inferred_frames is None
                     or self._sides["left"].missed_frames
                        <= max(1, int(max_inferred_frames))
                 ))
            )
        ):
            if left_observed:
                visible_x = self._sides["left"].x_px
                inferred_right_x = visible_x + self._width_at(y_ref, frame_height)
                lane_center_x = 0.5 * (visible_x + inferred_right_x)
                lane_type = "only_left"
                inferred_side = "right"
                state_name = (
                    "REACQUIRING_RIGHT"
                    if self._sides["right"].pending else "SINGLE_SIDE_LEFT"
                )
            else:
                visible_x = self._sides["right"].x_px
                inferred_left_x = visible_x - self._width_at(y_ref, frame_height)
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
                state_name = (
                    "REACQUIRING_PAIR" if self._reacquiring_pair
                    else "LOST" if self._lane_width_px is not None
                    else "ACQUIRING_PAIR"
                )
                lane_type = "none"
                perception_valid = False
                quality = 0.0
                speed_factor = 0.0

        # An anchor can remain observable after its opposite-side inference has
        # expired. Do not keep publishing the stale inferred coordinate as if
        # it were still a valid boundary.
        if lane_type not in ("only_left", "only_right"):
            inferred_side = None

        reference_x = (
            float(reference_center_x)
            if reference_center_x is not None
            else frame_width * 0.5
        )
        lane_error_px = (
            float(lane_center_x - reference_x)
            if lane_center_x is not None else None
        )
        visible_state = (
            self._sides["left"] if left_observed
            else self._sides["right"] if right_observed
            else None
        )
        if visible_state is not None and visible_state.line_global is not None:
            x1, y1, x2, y2 = visible_state.line_global
            fallback_angle = math.degrees(math.atan2(x2 - x1, y2 - y1))
        else:
            fallback_angle = 0.0
        left_inferred_x = None
        right_inferred_x = None
        width_at_reference = self._width_at(y_ref, frame_height)
        if inferred_side == "left" and right_observed and width_at_reference is not None:
            left_inferred_x = self._sides["right"].x_px - width_at_reference
        elif inferred_side == "right" and left_observed and width_at_reference is not None:
            right_inferred_x = self._sides["left"].x_px + width_at_reference
        elif state_name == "COASTING" and lane_center_x is not None and self._lane_width_px is not None:
            left_inferred_x = lane_center_x - self._lane_width_px * 0.5
            right_inferred_x = lane_center_x + self._lane_width_px * 0.5

        center_points = []
        steering_center_x = lane_center_x
        if lane_center_x is not None:
            for y in (y_ref - 0.10 * frame_height, y_ref, y_ref + 0.10 * frame_height):
                y = min(frame_height - 1.0, max(0.0, y))
                lx = self._line_x_at(self._sides["left"].line_global, y) if left_observed else None
                rx = self._line_x_at(self._sides["right"].line_global, y) if right_observed else None
                width_here = self._width_at(y, frame_height)
                if lx is not None and rx is not None:
                    center_x = (lx + rx) * 0.5
                elif width_here is not None and lx is not None:
                    center_x = lx + width_here * 0.5
                elif width_here is not None and rx is not None:
                    center_x = rx - width_here * 0.5
                else:
                    continue
                center_points.append([float(center_x), float(y)])
            if len(center_points) >= 3:
                # Weight the nearest look-ahead most heavily, while retaining
                # curvature information from the farther samples.
                steering_center_x = (0.2 * center_points[0][0]
                                      + 0.5 * center_points[1][0]
                                      + 0.3 * center_points[-1][0])
            elif center_points:
                steering_center_x = sum(point[0] for point in center_points) / len(center_points)

        left_payload = self._side_payload(
            "left", left_box, y_ref, left_observed,
            left_inferred_x, fallback_angle, left_hall,
            anchor_side="right" if inferred_side == "left" and right_observed else None,
            frame_height=frame_height,
        )
        right_payload = self._side_payload(
            "right", right_box, y_ref, right_observed,
            right_inferred_x, fallback_angle, right_hall,
            anchor_side="left" if inferred_side == "right" and left_observed else None,
            frame_height=frame_height,
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
            "steering_center_px": float(steering_center_x) if steering_center_x is not None else None,
            "center_points": center_points,
            "lane_error_px": lane_error_px,
            "reference_center_x": float(reference_x),
            "y_ref_px": float(y_ref),
            "lane_width_px": float(self._lane_width_px) if self._lane_width_px is not None else None,
            "geometry_mode": self._geometry_mode,
            "lane_width_model": (
                "constant_bev" if self._geometry_mode == "bev"
                else "perspective_profile"
            ),
            "lane_width_profile": [
                [float(y), float(width)]
                for y, width in sorted((self._lane_width_profile or {}).items())
            ],
            "inferred_side": inferred_side,
            "reacquire_frames": int(self.reacquire_frames),
            "pair_reacquire_required": bool(self._reacquiring_pair),
            "pair_pending_hits": (
                int(self._pair_pending["hits"]) if self._pair_pending else 0
            ),
            "pair_pending_required": int(self.reacquire_frames),
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
