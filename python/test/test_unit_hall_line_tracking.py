import sys
import unittest
from pathlib import Path

import numpy as np

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from vision.hall_line_tracking import HallLineTracker


class HallLineMatchingTests(unittest.TestCase):
    def test_maximum_cardinality_precedes_local_greedy_cost(self):
        adjacency = [
            [(0, 0.10), (1, 0.20)],
            [(0, 0.15), (1, 0.90)],
        ]
        matching = HallLineTracker._maximum_matching(adjacency, 2)
        self.assertEqual(len(matching), 2)
        self.assertEqual(matching, {0: 1, 1: 0})
        self.assertAlmostEqual(
            sum(dict(adjacency[row])[column] for row, column in matching.items()),
            0.35,
        )

    def test_matching_prefers_cardinality_over_a_cheaper_partial_match(self):
        adjacency = [
            [(0, 0.01)],
            [(0, 0.02), (1, 3.50)],
            [(1, 3.75)],
        ]
        matching = HallLineTracker._maximum_matching(adjacency, 2)
        self.assertEqual(len(matching), 2)
        self.assertEqual(set(matching.values()), {0, 1})

    def test_hall_witness_exposes_deficient_track_subset(self):
        adjacency = [[(0, 0.10)], [(0, 0.20)]]
        matching = HallLineTracker._maximum_matching(adjacency, 1)
        tracks, neighborhood = HallLineTracker._hall_witness(adjacency, matching)
        self.assertEqual(len(matching), 1)
        self.assertEqual(tracks, [0, 1])
        self.assertEqual(neighborhood, [0])
        self.assertEqual(len(tracks) - len(neighborhood), 1)

    def test_empty_history_is_vacuously_hall_satisfied_but_not_applicable(self):
        result = HallLineTracker().update(None, 640, 480)
        self.assertTrue(result["hall_satisfied"])
        self.assertFalse(result["hall_applicable"])
        self.assertEqual(result["hall_deficiency"], 0)
        self.assertIsNone(result["association_ratio"])

    def test_selected_identity_is_not_stolen_by_new_preferred_index(self):
        tracker = HallLineTracker()
        first = np.array(
            [[[100, 10, 110, 90]], [[300, 10, 310, 90]]], dtype=np.int32
        )
        initial = tracker.update(first, 400, 100, preferred_index=0)
        selected_id = initial["selected_track_id"]
        second = np.array(
            [[[302, 10, 312, 90]], [[102, 10, 112, 90]]], dtype=np.int32
        )
        updated = tracker.update(second, 400, 100, preferred_index=0)
        self.assertEqual(updated["state"], "TRACKING")
        self.assertEqual(updated["selected_track_id"], selected_id)

    def test_selected_track_coasts_then_expires_and_reacquires(self):
        tracker = HallLineTracker(max_missed_frames=1)
        line = np.array([[[100, 10, 110, 90]]], dtype=np.int32)
        first = tracker.update(line, 400, 100, preferred_index=0)
        selected_id = first["selected_track_id"]
        coast = tracker.update(None, 400, 100)
        self.assertEqual(coast["state"], "COASTING")
        self.assertEqual(coast["selected_track_id"], selected_id)
        self.assertIsNotNone(coast["selected_midpoint"])
        self.assertEqual(coast["missed_frames"], 1)
        expired = tracker.update(None, 400, 100)
        self.assertEqual(expired["state"], "LOST")
        self.assertIn(selected_id, expired["expired_track_ids"])
        reacquired = tracker.update(line, 400, 100, preferred_index=0)
        self.assertEqual(reacquired["state"], "REACQUIRING")
        self.assertNotEqual(reacquired["selected_track_id"], selected_id)

    def test_bad_segments_are_ignored_and_original_indices_are_preserved(self):
        tracker = HallLineTracker()
        lines = [
            np.array([1, 2, 1]),
            np.array([10, 10, 10, 10]),
            np.array([20, 10, 30, 90]),
        ]
        result = tracker.update(lines, 100, 100, preferred_index=2)
        self.assertEqual(len(result["candidate_tracks"]), 1)
        self.assertEqual(result["candidate_tracks"][0]["candidate_index"], 2)
        self.assertEqual(result["state"], "TRACKING")

    def test_preferred_candidate_survives_candidate_cap(self):
        tracker = HallLineTracker(max_candidates=8)
        lines = [[x, 10, x + 5, 90] for x in range(10, 190, 20)]
        result = tracker.update(lines, 240, 100, preferred_index=8)
        selected = next(
            item for item in result["candidate_tracks"]
            if item["track_id"] == result["selected_track_id"]
        )
        self.assertEqual(selected["candidate_index"], 8)

    def test_hall_witness_deficiency_matches_matching_deficiency(self):
        adjacency = [[(0, 0.1)], [(0, 0.2)], [(1, 0.1)]]
        matching = HallLineTracker._maximum_matching(adjacency, 2)
        tracks, neighborhood = HallLineTracker._hall_witness(adjacency, matching)
        self.assertEqual(len(tracks) - len(neighborhood), 1)
        self.assertEqual(len(adjacency) - len(matching), 1)


if __name__ == "__main__":
    unittest.main()
