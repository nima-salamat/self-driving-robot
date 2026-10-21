import sys
import unittest
from pathlib import Path

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from controller.manual_encoder_map import ManualEncoderMap


class FakeConnection:
    def __init__(self, connected=True):
        self.connected = connected
        self.state = "CONNECTED" if connected else "DISCONNECTED"


class FakeController:
    without_arduino = False

    def __init__(self):
        self.connection = FakeConnection()
        self.records = []
        self.enable_calls = 0

    def encoder_telemetry(self, limit=100):
        return list(self.records[-limit:])

    def request_encoder_telemetry(self, timeout=0.5):
        self.enable_calls += 1
        return True


def sample(at, pulses, *, epoch=1, servo=95, extended=True):
    return {
        "received_at": at,
        "extended": extended,
        "valid": True,
        "epoch": epoch,
        "signed_pulses": pulses,
        "raw_count": abs(pulses),
        "servo": servo,
    }


class ManualEncoderMapTests(unittest.TestCase):
    def setUp(self):
        self.now = [10.0]
        self.controller = FakeController()
        self.calibration = {
            "pulse_distance_cm": 0.5,
            "wheelbase_cm": 20.0,
            "road_angle_min_deg": -20.0,
            "road_angle_max_deg": 15.0,
        }
        self.tracker = ManualEncoderMap(
            self.controller,
            servo_center=95,
            servo_min=55,
            servo_max=125,
            calibration=self.calibration,
            clock=lambda: self.now[0],
        )

    def test_calibrated_samples_draw_estimated_path_and_distance(self):
        self.tracker.poll_once(now=10.0)  # Establish the serial connection boundary.
        self.controller.records = [sample(10.01, 0), sample(10.10, 4)]
        self.now[0] = 10.10
        self.tracker.poll_once()
        state = self.tracker.snapshot()
        self.assertTrue(state["telemetry_available"])
        self.assertTrue(state["trajectory_available"])
        self.assertEqual(state["signed_pulses"], 4)
        self.assertAlmostEqual(state["travel_cm"], 2.0)
        self.assertAlmostEqual(state["x_cm"], 2.0, places=4)
        self.assertAlmostEqual(state["y_cm"], 0.0, places=4)

    def test_pulse_distance_without_steering_calibration_never_fabricates_xy(self):
        self.tracker.set_calibration({"pulse_distance_cm": 0.25})
        self.tracker.poll_once(now=10.0)
        self.controller.records = [sample(10.01, 0), sample(10.10, 8)]
        self.now[0] = 10.10
        self.tracker.poll_once()
        state = self.tracker.snapshot()
        self.assertTrue(state["distance_calibrated"])
        self.assertFalse(state["trajectory_available"])
        self.assertAlmostEqual(state["travel_cm"], 2.0)
        self.assertIsNone(state["x_cm"])
        self.assertIsNone(state["y_cm"])

    def test_duplicate_and_old_records_are_not_integrated_twice(self):
        self.tracker.poll_once(now=10.0)
        self.controller.records = [sample(10.01, 0), sample(10.10, 4)]
        self.now[0] = 10.10
        self.tracker.poll_once()
        expected = self.tracker.snapshot()["travel_cm"]
        self.tracker.poll_once()
        self.assertEqual(self.tracker.snapshot()["travel_cm"], expected)

    def test_reconnect_creates_a_gap_and_reanchors_instead_of_integrating_unknown_motion(self):
        self.tracker.poll_once(now=10.0)
        self.controller.records = [sample(10.01, 0), sample(10.10, 4)]
        self.now[0] = 10.10
        self.tracker.poll_once()

        self.controller.connection.connected = False
        self.controller.connection.state = "DISCONNECTED"
        self.now[0] = 10.2
        self.tracker.poll_once()

        self.controller.connection.connected = True
        self.controller.connection.state = "CONNECTED"
        self.now[0] = 20.0
        self.tracker.poll_once()
        self.controller.records = [sample(10.01, 0), sample(10.10, 4), sample(20.01, 1000)]
        self.now[0] = 20.01
        self.tracker.poll_once()
        self.assertTrue(self.tracker.snapshot()["history"][-1]["gap"])

        self.controller.records.append(sample(20.10, 1002))
        self.now[0] = 20.10
        self.tracker.poll_once()
        self.assertAlmostEqual(self.tracker.snapshot()["travel_cm"], 3.0)

    def test_invalid_calibration_is_rejected(self):
        for values in (
            {"pulse_distance_cm": 0},
            {"pulse_distance_cm": 0.5, "wheelbase_cm": -1},
            {"pulse_distance_cm": 0.5, "road_angle_min_deg": -10},
            {"pulse_distance_cm": 0.5, "road_angle_min_deg": 10, "road_angle_max_deg": 20},
        ):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    self.tracker.set_calibration(values)

    def test_reset_origin_changes_only_the_displayed_pose(self):
        self.tracker.poll_once(now=10.0)
        self.controller.records = [sample(10.01, 0), sample(10.10, 4)]
        self.now[0] = 10.10
        self.tracker.poll_once()
        self.tracker.reset_origin()
        state = self.tracker.snapshot()
        self.assertAlmostEqual(state["x_cm"], 0.0)
        self.assertAlmostEqual(state["y_cm"], 0.0)
        self.assertAlmostEqual(state["travel_cm"], 2.0)
        self.assertEqual(self.controller.enable_calls, 0)


if __name__ == "__main__":
    unittest.main()
