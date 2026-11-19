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

    def test_recovery_search_expands_and_follows_a_shifted_boundary_outside_base_roi(self):
        self.update(left_x=220.0, right_x=420.0)
        self.update(left_x=None, right_x=430.0)
        self.update(left_x=None, right_x=460.0)

        search = self.tracker.recovery_rois(
            self.LEFT_ROI, self.RIGHT_ROI, self.FRAME_SHAPE,
            max_expansion_fraction=0.28,
        )
        self.assertTrue(search["left"]["expanded"])
        self.assertGreater(search["left"]["roi"][2], self.LEFT_ROI[2])
        self.assertAlmostEqual(search["left"]["expected_x"], 260.0, delta=15.0)

        for index in range(3):
            left_search_roi = search["left"]["roi"]
            left_lines = self.line_for_global_x(left_search_roi, 280.0, dx=-8.0)
            right_lines = self.line_for_global_x(self.RIGHT_ROI, 480.0, dx=8.0)
            result = self.tracker.update(
                left_lines=left_lines,
                right_lines=right_lines,
                frame_shape=self.FRAME_SHAPE,
                left_roi=left_search_roi,
                right_roi=self.RIGHT_ROI,
                reference_center_x=320.0,
                left_recovery=True,
            )
            if index < 2:
                self.assertFalse(result["left"]["observed"])
                self.assertEqual(result["left"]["pending_hits"], index + 1)

        self.assertTrue(result["left"]["observed"])
        self.assertEqual(result["lane_type"], "both")
        sticky = self.tracker.recovery_rois(
            self.LEFT_ROI, self.RIGHT_ROI, self.FRAME_SHAPE,
            max_expansion_fraction=0.28,
        )
        self.assertTrue(sticky["left"]["expanded"])
        self.assertGreater(sticky["left"]["roi"][2], self.LEFT_ROI[2])

    def test_single_side_can_reacquire_after_both_boundaries_were_lost(self):
        self.update(left_x=220.0, right_x=420.0)
        for _ in range(6):
            result = self.update(left_x=None, right_x=None)
        self.assertEqual(result["state"], "LOST")
        self.assertFalse(result["perception_valid"])

        for index in range(3):
            search = self.tracker.recovery_rois(
                self.LEFT_ROI, self.RIGHT_ROI, self.FRAME_SHAPE,
                max_expansion_fraction=0.28,
            )
            self.assertTrue(search["left"]["expanded"])
            self.assertTrue(search["right"]["expanded"])
            left_lines = self.line_for_global_x(search["left"]["roi"], 220.0, dx=-8.0)
            result = self.tracker.update(
                left_lines=left_lines,
                right_lines=None,
                frame_shape=self.FRAME_SHAPE,
                left_roi=search["left"]["roi"],
                right_roi=search["right"]["roi"],
                reference_center_x=320.0,
                left_recovery=True,
                right_recovery=True,
            )
            if index < 2:
                self.assertFalse(result["perception_valid"])

        self.assertTrue(result["perception_valid"])
        self.assertEqual(result["lane_type"], "only_left")
        self.assertEqual(result["inferred_side"], "right")
        self.assertTrue(result["left"]["observed"])
        self.assertFalse(result["right"]["observed"])
        self.assertAlmostEqual(result["speed_factor"], 0.55)

    def test_single_boundary_without_a_learned_lane_width_is_not_trusted(self):
        result = self.update(left_x=220.0, right_x=None)

        self.assertFalse(result["perception_valid"])
        self.assertEqual(result["state"], "ACQUIRING_PAIR")
        self.assertEqual(result["lane_type"], "none")


if __name__ == "__main__":
    unittest.main()
