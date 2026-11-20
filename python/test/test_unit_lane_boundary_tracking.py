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

    def update(self, left_x=None, right_x=None):
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

    def test_missing_side_can_remain_inferred_beyond_short_hall_coast_window(self):
        self.update(left_x=220.0, right_x=420.0)
        last_center = None
        for index in range(20):
            result = self.update(left_x=None, right_x=430.0 + index * 0.5)
            self.assertTrue(result["perception_valid"])
            self.assertEqual(result["lane_type"], "only_right")
            self.assertEqual(result["inferred_side"], "left")
            self.assertAlmostEqual(result["speed_factor"], 0.55)
            last_center = result["lane_center_px"]
        self.assertIsNotNone(last_center)

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
        # Put the left boundary just inside the inter-ROI gap so its
        # predicted recovery corridor must extend inward from the configured box.
        left_lines = self.line_for_global_x(left_roi, 235.0, dx=-12.0)
        right_lines = self.line_for_global_x(right_roi, 500.0, dx=12.0)
        self.tracker.update(
            left_lines, right_lines, self.FRAME_SHAPE,
            left_roi, right_roi, reference_center_x=320.0,
        )
        self.tracker.update(None, right_lines, self.FRAME_SHAPE,
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


if __name__ == "__main__":
    unittest.main()
