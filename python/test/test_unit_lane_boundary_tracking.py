import sys
import unittest
from pathlib import Path

import numpy as np

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from vision.lane_boundary_tracking import LaneBoundaryTracker


class LaneBoundaryTrackingTests(unittest.TestCase):
    FRAME_SHAPE = (480, 640, 3)
    LEFT_ROI = (80, 300, 260, 440)
    RIGHT_ROI = (380, 300, 560, 440)

    @staticmethod
    def line_for_global_x(roi, global_x, dx=0.0):
        left, top, _right, bottom = roi
        height = bottom - top
        local_x = float(global_x - left)
        return np.asarray(
            [[[local_x - dx * 0.5, 0.0, local_x + dx * 0.5, float(height)]]],
            dtype=np.float32,
        )

    def setUp(self):
        self.tracker = LaneBoundaryTracker(max_missed_frames=4, reacquire_frames=3)

    def update(
        self,
        left_x=None,
        right_x=None,
        *,
        max_inferred_frames=None,
        enable_full_pair_reacquisition=False,
        coast_frames=0,
    ):
        left_lines = (
            self.line_for_global_x(self.LEFT_ROI, left_x, dx=-8.0)
            if left_x is not None else None
        )
        right_lines = (
            self.line_for_global_x(self.RIGHT_ROI, right_x, dx=8.0)
            if right_x is not None else None
        )
        return self.tracker.update(
            left_lines=left_lines,
            right_lines=right_lines,
            frame_shape=self.FRAME_SHAPE,
            left_roi=self.LEFT_ROI,
            right_roi=self.RIGHT_ROI,
            reference_center_x=320.0,
            left_preferred_index=0 if left_lines is not None else None,
            right_preferred_index=0 if right_lines is not None else None,
            max_inferred_frames=max_inferred_frames,
            enable_full_pair_reacquisition=enable_full_pair_reacquisition,
            coast_frames=coast_frames,
        )

    def test_candidate_limit_preserves_preferred_index_and_original_hough_index(self):
        tracker = LaneBoundaryTracker(max_candidates=8)
        lines = [
            np.asarray([index * 10.0, 0.0, index * 10.0 + 5.0, 140.0])
            for index in range(10)
        ]

        candidates = tracker._candidates(
            lines,
            self.LEFT_ROI,
            frame_width=640,
            y_ref=370.0,
            preferred_index=9,
        )

        candidate_indices = {item["index"] for item in candidates}
        self.assertIn(9, candidate_indices)
        self.assertNotIn(8, candidate_indices)

    def test_initial_pair_establishes_lane_width_and_center(self):
        result = self.update(left_x=220.0, right_x=420.0)

        self.assertTrue(result["perception_valid"])
        self.assertEqual(result["lane_type"], "both")
        self.assertEqual(result["state"], "TRACKING")
        self.assertAlmostEqual(result["speed_factor"], 1.0)
        self.assertAlmostEqual(result["lane_width_px"], 200.0, delta=2.0)
        self.assertAlmostEqual(result["lane_center_px"], 320.0, delta=2.0)
        self.assertTrue(result["hall_satisfied"])
        self.assertTrue(result["left"]["observed"])
        self.assertTrue(result["right"]["observed"])

    def test_one_missing_boundary_keeps_driving_from_the_visible_boundary(self):
        self.update(left_x=220.0, right_x=420.0)
        result = self.update(left_x=None, right_x=430.0)

        self.assertTrue(result["perception_valid"])
        self.assertEqual(result["lane_type"], "only_right")
        self.assertEqual(result["state"], "SINGLE_SIDE_RIGHT")
        self.assertEqual(result["inferred_side"], "left")
        self.assertAlmostEqual(result["speed_factor"], 0.55)
        self.assertTrue(result["right"]["observed"])
        self.assertFalse(result["left"]["observed"])
        self.assertIn("INFERRED", result["left"]["status"])
        self.assertAlmostEqual(result["lane_center_px"], 330.0, delta=7.0)
        self.assertTrue(result["left"]["inference_valid"])
        self.assertTrue(result["left"]["inside_search_roi"])
        self.assertGreaterEqual(result["left"]["roi_edge_distances_px"]["left_px"], 0)
        self.assertGreaterEqual(result["left"]["roi_edge_distances_px"]["right_px"], 0)

    def test_single_side_inference_expires_after_a_bounded_number_of_frames(self):
        self.update(left_x=220.0, right_x=420.0)
        inference_limit = max(
            self.tracker.reacquire_frames * 2,
            self.tracker.max_missed_frames * 3,
        )
        for index in range(inference_limit):
            result = self.update(
                left_x=None,
                right_x=430.0 + index * 0.25,
                max_inferred_frames=inference_limit,
            )
            self.assertTrue(result["perception_valid"])
            self.assertEqual(result["lane_type"], "only_right")
            self.assertEqual(result["inferred_side"], "left")
            self.assertAlmostEqual(result["speed_factor"], 0.55)

        expired = self.update(
            left_x=None, right_x=433.5,
            max_inferred_frames=inference_limit,
        )
        self.assertFalse(expired["perception_valid"])
        self.assertEqual(expired["lane_type"], "none")
        self.assertEqual(expired["state"], "LOST")
        self.assertIsNone(expired["inferred_side"])
        self.assertFalse(expired["left"]["inferred"])

    def test_one_geometrically_valid_returning_line_is_accepted_immediately(self):
        self.update(left_x=220.0, right_x=420.0)
        self.update(left_x=None, right_x=430.0)
        self.tracker.reacquire_frames = 1

        # Exactly one Hough segment per ROI on this frame. With the explicit
        # one-frame setting, a geometrically valid segment is accepted
        # immediately; simulator processors use two-frame temporal stability.
        result = self.update(left_x=230.0, right_x=430.0)

        self.assertTrue(result["perception_valid"])
        self.assertEqual(result["lane_type"], "both")
        self.assertTrue(result["left"]["observed"])
        self.assertTrue(result["right"]["observed"])
        self.assertEqual(result["left"]["pending_hits"], 0)
        self.assertEqual(result["reacquire_frames"], 1)

    def test_simulator_single_segment_reacquisition_requires_two_consistent_frames(self):
        # One Hough segment per ROI per frame is sufficient. The same geometry
        # must persist for two frames so a one-frame shadow/texture edge does
        # not flip the side back to DETECTED.
        self.tracker.reacquire_frames = 2
        self.update(left_x=220.0, right_x=420.0)
        self.update(left_x=None, right_x=420.0)

        first = self.update(left_x=220.0, right_x=420.0)
        self.assertEqual(first["lane_type"], "only_right")
        self.assertFalse(first["left"]["observed"])
        self.assertEqual(first["left"]["pending_hits"], 1)

        second = self.update(left_x=220.0, right_x=420.0)
        self.assertEqual(second["lane_type"], "both")
        self.assertTrue(second["left"]["observed"])
        self.assertEqual(second["left"]["pending_hits"], 0)

    def test_smoothed_boundary_geometry_does_not_follow_raw_hough_jitter(self):
        self.update(left_x=220.0, right_x=420.0)
        before = self.tracker._sides["left"].x_px
        changed = self.update(left_x=232.0, right_x=420.0)
        after = self.tracker._sides["left"].x_px

        self.assertTrue(changed["left"]["observed"])
        self.assertGreater(after, before)
        self.assertLess(after, 232.0)
        y_ref = changed["y_ref_px"]
        self.assertAlmostEqual(
            self.tracker._line_x_at(
                self.tracker._sides["left"].line_global, y_ref
            ),
            after,
            delta=0.1,
        )

    def test_hough_fragment_near_lookahead_row_is_not_discarded(self):
        # Dashed/partially occluded lane paint often produces a segment which
        # ends a little before the reference row. Its projected x is still
        # inside the configured ROI and should be considered as one candidate.
        fragment = np.asarray([[[120.0, 0.0, 130.0, 40.0]]], dtype=np.float32)
        candidates = self.tracker._candidates(
            fragment, self.LEFT_ROI, frame_width=640, y_ref=370.0
        )
        self.assertEqual(len(candidates), 1)
        self.assertAlmostEqual(candidates[0]["x_px"], 217.5, delta=0.5)
        self.assertGreater(candidates[0]["quality"], 0.0)

    def test_simulator_keeps_last_boundary_solid_during_short_hough_dropout(self):
        self.update(left_x=220.0, right_x=420.0)
        previous_line = list(self.tracker._sides["left"].line_global)

        held = self.update(
            left_x=None, right_x=420.0, coast_frames=2
        )
        self.assertTrue(held["perception_valid"])
        self.assertEqual(held["lane_type"], "only_right")
        self.assertEqual(held["left"]["status"], "COASTING")
        self.assertTrue(held["left"]["coasting"])
        self.assertFalse(held["left"]["inferred"])
        self.assertIsNotNone(held["left"]["predicted_line"])
        self.assertEqual(
            tuple(previous_line), self.tracker._sides["left"].line_global
        )

        returned = self.update(left_x=220.0, right_x=420.0, coast_frames=2)
        self.assertEqual(returned["left"]["status"], "DETECTED")
        self.assertTrue(returned["left"]["observed"])

    def test_short_hough_fragment_is_not_a_lane_boundary_candidate(self):
        # Tiny fragments from shadows and road texture must not be extrapolated
        # to the shared look-ahead row and promoted into a lane track.
        fragment = np.asarray([[[30.0, 58.0, 34.0, 65.0]]], dtype=np.float32)
        candidates = self.tracker._candidates(
            fragment, self.LEFT_ROI, frame_width=640, y_ref=370.0
        )
        self.assertEqual(candidates, [])

    def test_recent_missing_track_uses_own_geometry_and_requests_recheck(self):
        left_roi = (80, 300, 260, 440)
        right_roi = (380, 300, 560, 440)
        left_state = self.tracker._sides["left"]
        left_state.track_id = 1
        left_state.x_px = 270.0
        left_state.missed_frames = 1
        left_state.observed = False
        left_state.line_global = (270.0, 300.0, 270.0, 440.0)

        right_state = self.tracker._sides["right"]
        right_state.track_id = 2
        right_state.x_px = 500.0
        right_state.observed = True
        right_state.line_global = (500.0, 300.0, 500.0, 440.0)

        self.tracker._lane_width_px = 200.0
        self.tracker.set_geometry_mode("bev")
        recovery = self.tracker.recovery_rois(
            left_roi, right_roi, self.FRAME_SHAPE, geometry_mode="bev"
        )["left"]

        self.assertTrue(recovery["recheck"])
        self.assertEqual(recovery["reason"], "recent_track_grace")
        self.assertTrue(recovery["prediction_valid"])
        self.assertTrue(recovery["expanded"])
        self.assertAlmostEqual(recovery["expected_x"], 270.0, delta=2.0)
        self.assertGreater(recovery["roi"][2], left_roi[2])

    def test_simulator_startup_ignores_a_single_frame_false_pair(self):
        self.tracker.reacquire_frames = 2
        left = self.line_for_global_x(self.LEFT_ROI, 220.0, dx=-8.0)
        right = self.line_for_global_x(self.RIGHT_ROI, 420.0, dx=8.0)

        ghost = self.tracker.update(
            left, right, self.FRAME_SHAPE,
            self.LEFT_ROI, self.RIGHT_ROI,
            reference_center_x=320.0, geometry_mode="bev",
            enable_full_pair_reacquisition=True,
        )
        self.assertFalse(ghost["perception_valid"])
        self.assertEqual(ghost["state"], "ACQUIRING_PAIR")
        self.assertEqual(ghost["pair_pending_hits"], 1)
        self.assertIsNone(self.tracker._sides["left"].track_id)
        self.assertIsNone(self.tracker._sides["right"].track_id)

        # The candidate disappears on the next frame: discard that hypothesis.
        blank = self.tracker.update(
            None, None, self.FRAME_SHAPE,
            self.LEFT_ROI, self.RIGHT_ROI,
            reference_center_x=320.0, geometry_mode="bev",
            enable_full_pair_reacquisition=True,
        )
        self.assertFalse(blank["perception_valid"])
        self.assertEqual(blank["pair_pending_hits"], 0)
        self.assertIsNone(self.tracker._sides["left"].track_id)

        # A real pair with the same geometry on two consecutive frames is
        # accepted, using one Hough segment in each ROI per frame.
        first = self.tracker.update(
            left, right, self.FRAME_SHAPE,
            self.LEFT_ROI, self.RIGHT_ROI,
            reference_center_x=320.0, geometry_mode="bev",
            enable_full_pair_reacquisition=True,
        )
        self.assertFalse(first["perception_valid"])
        self.assertEqual(first["pair_pending_hits"], 1)

        second = self.tracker.update(
            left, right, self.FRAME_SHAPE,
            self.LEFT_ROI, self.RIGHT_ROI,
            reference_center_x=320.0, geometry_mode="bev",
            enable_full_pair_reacquisition=True,
        )
        self.assertTrue(second["perception_valid"])
        self.assertEqual(second["lane_type"], "both")
        self.assertEqual(second["candidate_count"], {"left": 1, "right": 1})

    def test_simulator_startup_single_boundary_is_pending_not_detected(self):
        self.tracker.reacquire_frames = 2
        left = self.line_for_global_x(self.LEFT_ROI, 220.0, dx=-8.0)
        first = self.tracker.update(
            left, None, self.FRAME_SHAPE,
            self.LEFT_ROI, self.RIGHT_ROI,
            reference_center_x=320.0, geometry_mode="bev",
            enable_full_pair_reacquisition=True,
        )
        self.assertFalse(first["left"]["observed"])
        self.assertEqual(first["left"]["status"], "REACQUIRING")
        self.assertEqual(first["left"]["pending_hits"], 1)

        second = self.tracker.update(
            left, None, self.FRAME_SHAPE,
            self.LEFT_ROI, self.RIGHT_ROI,
            reference_center_x=320.0, geometry_mode="bev",
            enable_full_pair_reacquisition=True,
        )
        self.assertTrue(second["left"]["observed"])
        self.assertEqual(second["left"]["status"], "DETECTED")
        self.assertIsNone(second["lane_width_px"])

    def test_generic_tracker_keeps_three_frame_confirmation_by_default(self):
        tracker = LaneBoundaryTracker()
        self.assertEqual(tracker.reacquire_frames, 3)

    def test_single_pair_reacquisition_accepts_one_candidate_per_side(self):
        self.tracker.reacquire_frames = 1
        self.tracker.recovery_rois(
            self.LEFT_ROI, self.RIGHT_ROI, self.FRAME_SHAPE,
            geometry_mode="bev",
        )
        self.update(left_x=220.0, right_x=420.0)

        for _ in range(self.tracker.max_missed_frames + 1):
            self.tracker.recovery_rois(
                self.LEFT_ROI, self.RIGHT_ROI, self.FRAME_SHAPE,
                geometry_mode="bev",
            )
            self.tracker.update(
                None, None, self.FRAME_SHAPE,
                self.LEFT_ROI, self.RIGHT_ROI,
                reference_center_x=320.0, geometry_mode="bev",
                enable_full_pair_reacquisition=True,
            )

        recovery = self.tracker.recovery_rois(
            self.LEFT_ROI, self.RIGHT_ROI, self.FRAME_SHAPE,
            geometry_mode="bev",
        )
        pair_roi = recovery["left"]["roi"]
        one_left_line = self.line_for_global_x(pair_roi, 270.0, dx=-8.0)
        one_right_line = self.line_for_global_x(pair_roi, 470.0, dx=8.0)
        result = self.tracker.update(
            one_left_line, one_right_line, self.FRAME_SHAPE,
            pair_roi, pair_roi, reference_center_x=370.0,
            geometry_mode="bev", enable_full_pair_reacquisition=True,
        )

        self.assertTrue(result["perception_valid"])
        self.assertEqual(result["lane_type"], "both")
        self.assertEqual(result["candidate_count"], {"left": 1, "right": 1})
        self.assertEqual(result["state"], "REACQUIRING")
        self.assertFalse(result["pair_reacquire_required"])

    def test_wrong_opposite_line_is_rejected_instead_of_stealing_the_track(self):
        self.update(left_x=220.0, right_x=420.0)
        result = self.update(left_x=180.0, right_x=430.0)

        self.assertTrue(result["perception_valid"])
        self.assertEqual(result["lane_type"], "only_right")
        self.assertEqual(result["inferred_side"], "left")
        self.assertFalse(result["left"]["observed"])
        self.assertEqual(result["left"]["pending_hits"], 0)
        self.assertAlmostEqual(result["lane_width_px"], 200.0, delta=3.0)

    def test_reacquisition_requires_three_geometrically_consistent_frames(self):
        # Multi-frame confirmation remains available when explicitly requested;
        # it is no longer the simulator default.
        self.tracker.reacquire_frames = 3
        self.update(left_x=220.0, right_x=420.0)
        self.update(left_x=None, right_x=430.0)

        first = self.update(left_x=230.0, right_x=430.0)
        self.assertEqual(first["lane_type"], "only_right")
        self.assertEqual(first["state"], "REACQUIRING_LEFT")
        self.assertEqual(first["left"]["pending_hits"], 1)
        self.assertFalse(first["left"]["observed"])

        second = self.update(left_x=230.0, right_x=430.0)
        self.assertEqual(second["lane_type"], "only_right")
        self.assertEqual(second["left"]["pending_hits"], 2)
        self.assertFalse(second["left"]["observed"])

        third = self.update(left_x=230.0, right_x=430.0)
        self.assertEqual(third["lane_type"], "both")
        self.assertTrue(third["left"]["observed"])
        self.assertTrue(third["right"]["observed"])
        self.assertEqual(third["state"], "REACQUIRING")

    def test_wrong_candidate_does_not_start_reacquisition(self):
        self.update(left_x=220.0, right_x=420.0)
        self.update(left_x=None, right_x=430.0)

        for _ in range(5):
            result = self.update(left_x=180.0, right_x=430.0)
            self.assertEqual(result["lane_type"], "only_right")
            self.assertFalse(result["left"]["observed"])
            self.assertEqual(result["left"]["pending_hits"], 0)

    def test_nearby_candidate_with_incompatible_tangent_is_rejected(self):
        self.update(left_x=220.0, right_x=420.0)
        self.update(left_x=None, right_x=420.0)
        misleading = self.line_for_global_x(self.LEFT_ROI, 220.0, dx=180.0)
        result = self.tracker.update(
            misleading,
            self.line_for_global_x(self.RIGHT_ROI, 420.0, dx=0.0),
            self.FRAME_SHAPE, self.LEFT_ROI, self.RIGHT_ROI,
            reference_center_x=320.0,
        )

        self.assertFalse(result["left"]["observed"])
        self.assertEqual(result["left"]["pending_hits"], 0)
        self.assertEqual(result["inferred_side"], "left")

    def test_left_boundary_can_be_the_single_reliable_anchor(self):
        self.update(left_x=220.0, right_x=420.0)
        result = self.update(left_x=230.0, right_x=None)

        self.assertTrue(result["perception_valid"])
        self.assertEqual(result["lane_type"], "only_left")
        self.assertEqual(result["inferred_side"], "right")
        self.assertTrue(result["left"]["observed"])
        self.assertFalse(result["right"]["observed"])
        self.assertAlmostEqual(result["lane_center_px"], 330.0, delta=7.0)

    def test_both_boundaries_lost_eventually_invalidates_perception(self):
        self.update(left_x=220.0, right_x=420.0)
        for _ in range(4):
            result = self.update(left_x=None, right_x=None)
            self.assertTrue(result["perception_valid"])
            self.assertEqual(result["state"], "COASTING")
            self.assertEqual(result["speed_factor"], 0.25)

        lost = self.update(left_x=None, right_x=None)
        self.assertFalse(lost["perception_valid"])
        self.assertEqual(lost["state"], "LOST")
        self.assertIsNone(lost["lane_center_px"])

    def test_single_boundary_without_a_learned_lane_width_is_not_trusted(self):
        result = self.update(left_x=220.0, right_x=None)

        self.assertFalse(result["perception_valid"])
        self.assertEqual(result["state"], "ACQUIRING_PAIR")
        self.assertEqual(result["lane_type"], "none")

    def test_returning_anchor_reacquires_after_both_sides_miss_without_losing_identity(self):
        self.update(left_x=220.0, right_x=420.0)
        original_id = self.tracker._sides["left"].track_id
        self.update()
        self.update()

        for hit in range(3):
            result = self.update(left_x=221.0, right_x=None)
            if hit < 2:
                self.assertFalse(result["left"]["observed"])
                self.assertEqual(result["left"]["status"], "REACQUIRING")

        self.assertTrue(result["left"]["observed"])
        self.assertEqual(result["left"]["track_id"], original_id)
        self.assertTrue(result["perception_valid"])
        self.assertEqual(result["inferred_side"], "right")

    def test_recovery_roi_expands_inward_around_predicted_boundary(self):
        left_roi = (90, 300, 228, 440)
        right_roi = (432, 300, 570, 440)
        # Acquire both boundaries within the configured crops, then let the
        # visible right boundary move so the inferred left boundary lands just
        # outside the left ROI and requires a bounded inward search expansion.
        left_lines = self.line_for_global_x(left_roi, 220.0, dx=-12.0)
        initial_right_lines = self.line_for_global_x(right_roi, 480.0, dx=12.0)
        shifted_right_lines = self.line_for_global_x(right_roi, 500.0, dx=12.0)
        self.tracker.update(
            left_lines, initial_right_lines, self.FRAME_SHAPE,
            left_roi, right_roi, reference_center_x=320.0,
        )
        self.tracker.update(None, shifted_right_lines, self.FRAME_SHAPE,
                            left_roi, right_roi, reference_center_x=320.0)

        search = self.tracker.recovery_rois(left_roi, right_roi, self.FRAME_SHAPE)
        self.assertTrue(search["left"]["expanded"])
        self.assertGreater(search["left"]["roi"][2], left_roi[2])
        search_left, _top, search_right, _bottom = search["left"]["roi"]
        self.assertTrue(search["left"]["expected_points"])
        for expected_x, _expected_y in search["left"]["expected_points"]:
            self.assertGreaterEqual(expected_x, search_left)
            self.assertLessEqual(expected_x, search_right)

    def test_bev_inferred_boundary_uses_constant_offset_in_rectified_coordinates(self):
        left = self.line_for_global_x(self.LEFT_ROI, 220.0, dx=-28.0)
        right = self.line_for_global_x(self.RIGHT_ROI, 420.0, dx=-28.0)
        self.tracker.update(
            left, right, self.FRAME_SHAPE, self.LEFT_ROI, self.RIGHT_ROI,
            reference_center_x=320.0, geometry_mode="bev",
        )
        result = self.tracker.update(
            left, None, self.FRAME_SHAPE, self.LEFT_ROI, self.RIGHT_ROI,
            reference_center_x=320.0, geometry_mode="bev",
        )

        self.assertEqual(result["geometry_mode"], "bev")
        self.assertEqual(result["lane_width_model"], "constant_bev")
        points = result["right"]["predicted_points"]
        self.assertGreaterEqual(len(points), 2)

        left_state = self.tracker._sides["left"]
        y_ref = result["y_ref_px"]
        x_deltas = []
        slope = -28.0 / (self.LEFT_ROI[3] - self.LEFT_ROI[1])
        for x, y in points:
            anchor_x = left_state.x_px + slope * (y - y_ref)
            x_deltas.append(x - anchor_x)
        self.assertAlmostEqual(max(x_deltas), min(x_deltas), delta=0.1)
        self.assertGreaterEqual(len(result["center_points"]), 2)
        self.assertAlmostEqual(
            result["steering_center_px"],
            0.2 * result["center_points"][0][0]
            + 0.5 * result["center_points"][1][0]
            + 0.3 * result["center_points"][-1][0],
            delta=0.1,
        )

    def test_perspective_inference_follows_row_dependent_width_not_parallel_shift(self):
        left = self.line_for_global_x(self.LEFT_ROI, 220.0, dx=-14.0)
        right = self.line_for_global_x(self.RIGHT_ROI, 420.0, dx=21.0)
        learned = self.tracker.update(
            left, right, self.FRAME_SHAPE, self.LEFT_ROI, self.RIGHT_ROI,
            reference_center_x=320.0, geometry_mode="perspective",
        )
        self.assertEqual(learned["geometry_mode"], "perspective")
        self.assertEqual(learned["lane_width_model"], "perspective_profile")
        self.assertGreaterEqual(len(learned["lane_width_profile"]), 2)

        result = self.tracker.update(
            left, None, self.FRAME_SHAPE, self.LEFT_ROI, self.RIGHT_ROI,
            reference_center_x=320.0, geometry_mode="perspective",
        )
        self.assertEqual(result["inferred_side"], "right")
        points = result["right"]["predicted_points"]
        self.assertGreaterEqual(len(points), 5)

        left_state = self.tracker._sides["left"]
        y_ref = result["y_ref_px"]
        slope = -14.0 / (self.LEFT_ROI[3] - self.LEFT_ROI[1])
        offsets = []
        for x, y in points:
            anchor_x = left_state.x_px + slope * (y - y_ref)
            offsets.append(x - anchor_x)

        # The lane opens with image-row depth in this synthetic perspective
        # geometry, so a constant parallel offset would be demonstrably wrong.
        self.assertGreater(max(offsets) - min(offsets), 10.0)
        self.assertAlmostEqual(
            offsets[len(offsets) // 2],
            self.tracker._width_at(y_ref, self.FRAME_SHAPE[0]),
            delta=2.0,
        )

    def test_changing_configured_roi_resets_old_lane_geometry(self):
        # Production calls this with persisted ROIs before every recovery pass.
        self.tracker.set_roi_configuration(
            self.LEFT_ROI, self.RIGHT_ROI, self.FRAME_SHAPE
        )
        self.update(left_x=220.0, right_x=420.0)
        self.assertIsNotNone(self.tracker._lane_width_px)
        shifted_left_roi = (90, 300, 270, 440)
        self.tracker.set_roi_configuration(
            shifted_left_roi, self.RIGHT_ROI, self.FRAME_SHAPE
        )

        self.assertIsNone(self.tracker._lane_width_px)
        self.assertIsNone(self.tracker._lane_width_profile)
        self.assertIsNone(self.tracker._sides["left"].track_id)
        self.assertIsNone(self.tracker._sides["right"].track_id)

    def test_switching_bev_mode_discards_perspective_width_profile(self):
        self.update(left_x=220.0, right_x=420.0)
        self.assertIsNotNone(self.tracker._lane_width_px)
        self.tracker.set_geometry_mode("bev")

        self.assertIsNone(self.tracker._lane_width_px)
        self.assertIsNone(self.tracker._lane_width_profile)
        self.assertIsNone(self.tracker._sides["left"].track_id)
        self.assertEqual(self.tracker._geometry_mode, "bev")

    def test_perspective_width_profile_is_learned_from_two_real_boundaries(self):
        left = self.line_for_global_x(self.LEFT_ROI, 220.0, dx=-14.0)
        right = self.line_for_global_x(self.RIGHT_ROI, 420.0, dx=21.0)
        learned = self.tracker.update(
            left, right, self.FRAME_SHAPE, self.LEFT_ROI, self.RIGHT_ROI,
            reference_center_x=320.0,
        )
        profile = learned["lane_width_profile"]
        self.assertEqual(len(profile), 3)
        self.assertGreater(max(width for _row, width in profile)
                           - min(width for _row, width in profile), 5.0)

        inferred = self.tracker.update(
            self.line_for_global_x(self.LEFT_ROI, 225.0, dx=-18.0), None,
            self.FRAME_SHAPE, self.LEFT_ROI, self.RIGHT_ROI,
            reference_center_x=320.0,
        )
        self.assertEqual(inferred["inferred_side"], "right")
        self.assertNotEqual(inferred["center_points"][0][0],
                            inferred["center_points"][-1][0])

    def test_perspective_recovery_roi_contains_the_inferred_curve_at_every_sample(self):
        left_roi = (80, 300, 260, 440)
        right_roi = (380, 300, 560, 440)
        left = self.line_for_global_x(left_roi, 220.0, dx=-18.0)
        right = self.line_for_global_x(right_roi, 420.0, dx=20.0)
        self.tracker.update(
            left, right, self.FRAME_SHAPE, left_roi, right_roi,
            reference_center_x=320.0, geometry_mode="perspective",
        )
        self.tracker.update(
            None, right, self.FRAME_SHAPE, left_roi, right_roi,
            reference_center_x=320.0, geometry_mode="perspective",
        )

        recovery = self.tracker.recovery_rois(
            left_roi, right_roi, self.FRAME_SHAPE,
            geometry_mode="perspective",
        )["left"]
        search_left, search_top, search_right, search_bottom = recovery["roi"]

        self.assertEqual(recovery["geometry_mode"], "perspective")
        self.assertGreaterEqual(len(recovery["expected_points"]), 5)
        for x, y in recovery["expected_points"]:
            self.assertGreaterEqual(x, search_left)
            self.assertLessEqual(x, search_right)
            self.assertGreaterEqual(y, search_top)
            self.assertLessEqual(y, search_bottom)

    def test_uninitialized_tracker_never_expands_roi_from_its_midpoint(self):
        self.tracker.update(
            None, None, self.FRAME_SHAPE,
            self.LEFT_ROI, self.RIGHT_ROI,
            reference_center_x=320.0,
        )

        recovery = self.tracker.recovery_rois(
            self.LEFT_ROI, self.RIGHT_ROI, self.FRAME_SHAPE
        )

        self.assertFalse(recovery["left"]["expanded"])
        self.assertFalse(recovery["right"]["expanded"])
        self.assertEqual(recovery["left"]["roi"], self.LEFT_ROI)
        self.assertEqual(recovery["right"]["roi"], self.RIGHT_ROI)
        self.assertEqual(
            recovery["left"]["reason"],
            "no_confirmed_geometric_prediction",
        )

    def test_recovery_window_never_shrinks_a_wide_configured_roi(self):
        left_roi = (20, 300, 260, 440)
        right_roi = (380, 300, 620, 440)
        self.tracker.update(
            self.line_for_global_x(left_roi, 140.0, dx=-8.0),
            self.line_for_global_x(right_roi, 500.0, dx=8.0),
            self.FRAME_SHAPE, left_roi, right_roi,
            reference_center_x=320.0,
        )
        self.tracker.update(
            None,
            self.line_for_global_x(right_roi, 500.0, dx=8.0),
            self.FRAME_SHAPE, left_roi, right_roi,
            reference_center_x=320.0,
        )

        search = self.tracker.recovery_rois(
            left_roi, right_roi, self.FRAME_SHAPE
        )["left"]["roi"]

        self.assertLessEqual(search[0], left_roi[0])
        self.assertGreaterEqual(search[2], left_roi[2])
        self.assertGreaterEqual(search[2] - search[0], left_roi[2] - left_roi[0])


    def test_recovered_boundary_keeps_expanded_search_window_until_back_inside_roi(self):
        left_roi = (90, 300, 228, 440)
        right_roi = (432, 300, 570, 440)
        state = self.tracker._sides["left"]
        state.track_id = 1
        state.x_px = 235.0
        state.line_global = (235.0, 300.0, 235.0, 440.0)
        state.observed = True
        state.missed_frames = 0

        first = self.tracker.recovery_rois(
            left_roi, right_roi, self.FRAME_SHAPE
        )["left"]
        self.assertTrue(first["expanded"])
        self.assertEqual(first["reason"], "observed_track_hysteresis")
        self.assertGreater(first["roi"][2], left_roi[2])

        # Recompute on the next frame before processing the next image: the
        # ROI must remain expanded, otherwise the recovered line disappears
        # from the detector crop and toggles back to LOST.
        second = self.tracker.recovery_rois(
            left_roi, right_roi, self.FRAME_SHAPE
        )["left"]
        self.assertTrue(second["expanded"])
        self.assertGreater(second["roi"][2], left_roi[2])
        self.assertTrue(all(
            second["roi"][0] <= x < second["roi"][2]
            for x, _y in second["expected_points"]
        ))

        # Once the tracked line has genuinely returned well inside the user's
        # configured ROI, the search corridor contracts back to that exact ROI.
        state.x_px = 190.0
        state.line_global = (190.0, 300.0, 190.0, 440.0)
        contracted = self.tracker.recovery_rois(
            left_roi, right_roi, self.FRAME_SHAPE
        )["left"]
        self.assertFalse(contracted["expanded"])
        self.assertEqual(contracted["roi"], left_roi)
        self.assertEqual(contracted["reason"], "tracking")

    def test_candidate_projection_must_stay_inside_the_actual_search_roi(self):
        # The segment itself is inside the crop, but extrapolating it to y_ref
        # puts its lane point 6 px beyond the right edge. The old 15%-of-ROI
        # horizontal margin incorrectly accepted this candidate.
        fragment = np.asarray([[[0.0, 0.0, 80.0, 30.0]]], dtype=np.float32)
        candidates = self.tracker._candidates(
            fragment, self.LEFT_ROI, frame_width=640, y_ref=370.0
        )
        self.assertEqual(candidates, [])

    def test_hall_association_uses_full_frame_coordinates_when_crop_changes(self):
        first_roi = (80, 300, 260, 440)
        second_roi = (60, 300, 300, 440)
        first = self.line_for_global_x(first_roi, 220.0, dx=-8.0)
        second = self.line_for_global_x(second_roi, 220.0, dx=-8.0)

        self.tracker._hall_update("left", first, first_roi, 0, self.FRAME_SHAPE)
        tracks = self.tracker._hall["left"]._tracks
        self.assertEqual(len(tracks), 1)
        original_id = next(iter(tracks))
        original_feature = tuple(tracks[original_id]["feature"])

        self.tracker._hall_update("left", second, second_roi, 0, self.FRAME_SHAPE)
        tracks = self.tracker._hall["left"]._tracks
        self.assertEqual(len(tracks), 1)
        self.assertIn(original_id, tracks)
        np.testing.assert_allclose(
            tracks[original_id]["feature"], original_feature, atol=1e-6
        )
        self.assertEqual(tracks[original_id]["missed"], 0)

    def test_recovery_rejects_a_prediction_beyond_the_configured_expansion_limit(self):
        left_roi = (80, 300, 260, 440)
        right_roi = (400, 300, 580, 440)
        left_state = self.tracker._sides["left"]
        left_state.track_id = 1
        left_state.missed_frames = 2
        right_state = self.tracker._sides["right"]
        right_state.track_id = 2
        right_state.x_px = 630.0
        right_state.line_global = (630.0, 300.0, 630.0, 440.0)
        right_state.observed = True
        self.tracker._lane_width_px = 200.0
        self.tracker._geometry_mode = "bev"

        recovery = self.tracker.recovery_rois(
            left_roi, right_roi, self.FRAME_SHAPE, geometry_mode="bev"
        )["left"]

        self.assertFalse(recovery["prediction_valid"])
        self.assertFalse(recovery["expanded"])
        self.assertEqual(recovery["roi"], left_roi)
        self.assertEqual(
            recovery["reason"], "predicted_boundary_outside_recovery_limit"
        )
        self.assertAlmostEqual(
            recovery["edge_distances_px"]["outside_right_px"], 171.0, delta=1.0
        )
        self.assertLess(
            recovery["edge_distances_px"]["to_inner_edge_px"], 0.0
        )

    def test_valid_recovery_roi_contains_the_whole_predicted_corridor(self):
        left_roi = (80, 300, 260, 440)
        right_roi = (380, 300, 560, 440)
        self.tracker.set_geometry_mode("bev")
        left_state = self.tracker._sides["left"]
        left_state.track_id = 1
        left_state.x_px = 270.0
        left_state.missed_frames = 2
        left_state.line_global = (270.0, 300.0, 270.0, 440.0)
        right_state = self.tracker._sides["right"]
        right_state.track_id = 2
        right_state.x_px = 450.0
        right_state.observed = True
        right_state.line_global = (450.0, 300.0, 450.0, 440.0)
        self.tracker._lane_width_px = 200.0
        recovery = self.tracker.recovery_rois(
            left_roi, right_roi, self.FRAME_SHAPE, geometry_mode="bev"
        )["left"]
        self.assertTrue(recovery["prediction_valid"])
        self.assertTrue(recovery["expanded"])
        left_edge, top, right_edge, bottom = recovery["roi"]
        for x, y in recovery["expected_points"]:
            self.assertGreaterEqual(x, left_edge)
            self.assertLess(x, right_edge)
            self.assertGreaterEqual(y, top)
            self.assertLess(y, bottom)
        distances = recovery["edge_distances_px"]
        self.assertIn("to_outer_edge_px", distances)
        self.assertIn("to_inner_edge_px", distances)

    def test_full_pair_loss_enters_wide_reacquisition_and_confirms_new_pair(self):
        # Initialise the configured ROI signature as production does.
        self.tracker.recovery_rois(
            self.LEFT_ROI, self.RIGHT_ROI, self.FRAME_SHAPE,
            geometry_mode="bev",
        )
        self.update(left_x=220.0, right_x=420.0)

        for _ in range(self.tracker.max_missed_frames + 1):
            self.tracker.recovery_rois(
                self.LEFT_ROI, self.RIGHT_ROI, self.FRAME_SHAPE,
                geometry_mode="bev",
            )
            lost = self.tracker.update(
                None, None, self.FRAME_SHAPE,
                self.LEFT_ROI, self.RIGHT_ROI,
                reference_center_x=320.0, geometry_mode="bev",
                enable_full_pair_reacquisition=True,
            )
        self.assertFalse(lost["perception_valid"])
        self.assertEqual(lost["state"], "LOST")

        recovery = self.tracker.recovery_rois(
            self.LEFT_ROI, self.RIGHT_ROI, self.FRAME_SHAPE,
            geometry_mode="bev",
        )
        self.assertTrue(recovery["left"]["pair_reacquire"])
        self.assertEqual(recovery["left"]["roi"], (0, 300, 640, 440))
        self.assertEqual(recovery["right"]["roi"], (0, 300, 640, 440))

        pair_roi = recovery["left"]["roi"]
        left_new = self.line_for_global_x(pair_roi, 270.0, dx=-8.0)
        right_new = self.line_for_global_x(pair_roi, 470.0, dx=8.0)
        pair_lines = np.concatenate((left_new, right_new), axis=0)

        for hit in range(self.tracker.reacquire_frames):
            recovery = self.tracker.recovery_rois(
                self.LEFT_ROI, self.RIGHT_ROI, self.FRAME_SHAPE,
                geometry_mode="bev",
            )
            pair_roi = recovery["left"]["roi"]
            result = self.tracker.update(
                pair_lines, pair_lines, self.FRAME_SHAPE,
                pair_roi, pair_roi,
                reference_center_x=320.0, geometry_mode="bev",
                left_prediction_valid=False, right_prediction_valid=False,
            )
            if hit < self.tracker.reacquire_frames - 1:
                self.assertFalse(result["perception_valid"])
                self.assertEqual(result["state"], "REACQUIRING_PAIR")
                self.assertEqual(result["pair_pending_hits"], hit + 1)

        self.assertTrue(result["perception_valid"])
        self.assertEqual(result["lane_type"], "both")
        self.assertEqual(result["state"], "REACQUIRING")
        self.assertAlmostEqual(result["lane_center_px"], 370.0, delta=3.0)
        self.assertAlmostEqual(result["lane_width_px"], 200.0, delta=3.0)
        self.assertFalse(result["pair_reacquire_required"])


if __name__ == "__main__":
    unittest.main()
