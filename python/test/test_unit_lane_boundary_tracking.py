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
        left_lines = self.line_for_global_x(left_roi, 190.0, dx=-12.0)
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
        self.assertLessEqual(search["left"]["roi"][2] - search["left"]["roi"][0],
                             int(self.FRAME_SHAPE[1] * 0.30) + 2)

    def test_inferred_geometry_uses_visible_boundary_tangent_and_lookahead(self):
        self.update(left_x=220.0, right_x=420.0)
        left = self.line_for_global_x(self.LEFT_ROI, 230.0, dx=-28.0)
        result = self.tracker.update(
            left, None, self.FRAME_SHAPE, self.LEFT_ROI, self.RIGHT_ROI,
            reference_center_x=320.0,
        )
        inferred = result["right"]["predicted_line"]
        observed = result["left"]["line"]
        self.assertAlmostEqual(
            (inferred[2] - inferred[0]) / (inferred[3] - inferred[1]),
            (observed[2] - observed[0]) / (observed[3] - observed[1]),
            delta=0.03,
        )
        self.assertGreaterEqual(len(result["center_points"]), 2)
        self.assertAlmostEqual(
            result["steering_center_px"],
            0.2 * result["center_points"][0][0]
            + 0.5 * result["center_points"][1][0]
            + 0.3 * result["center_points"][-1][0],
            delta=0.1,
        )

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


if __name__ == "__main__":
    unittest.main()
