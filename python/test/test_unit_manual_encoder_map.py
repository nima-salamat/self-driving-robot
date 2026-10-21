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

    def test_calibration_form_uses_one_effective_wheel_angle_setting(self):
        html = (PYTHON_ROOT / "test" / "manual_encoder_map.html").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'id="maxWheelAngle" name="max_wheel_angle_deg" type="number" min="0.1" max="45"',
            html,
        )
        self.assertNotIn("road_angle_min_deg", html)
        self.assertNotIn("road_angle_max_deg", html)

    def test_servo_command_and_pulse_delta_are_recorded_for_each_sample(self):
        self.tracker.set_calibration({
            "pulse_distance_cm": 0.4,
            "wheelbase_cm": 25.0,
            "max_wheel_angle_deg": 25.0,
        })
        self.tracker.poll_once(now=10.0)
        self.controller.records = [sample(10.01, 0, servo=95), sample(10.10, 4, servo=115)]
        self.now[0] = 10.10
        self.tracker.poll_once()
        history = self.tracker.snapshot()["history"]
        last = history[-1]
        self.assertEqual(last["signed_pulses"], 4)
        self.assertEqual(last["pulse_delta"], 4)
        self.assertEqual(last["servo_command"], 115)
        self.assertAlmostEqual(self.tracker.snapshot()["road_wheel_angle_deg"], 12.5)

    def test_effective_wheel_angle_is_derived_from_servo_command_and_editable_limit(self):
        self.tracker.set_calibration({
            "pulse_distance_cm": 0.4,
            "wheelbase_cm": 25.0,
            "max_wheel_angle_deg": 30.0,
        })
        odometry = self.tracker._odometry
        self.assertAlmostEqual(odometry._road_wheel_angle(55), -30.0)
        self.assertAlmostEqual(odometry._road_wheel_angle(95), 0.0)
        self.assertAlmostEqual(odometry._road_wheel_angle(130), 30.0)

    def test_max_wheel_angle_must_be_positive_and_at_most_45_degrees(self):
        for angle in (0, -1, 45.1, float("inf")):
            with self.subTest(angle=angle):
                with self.assertRaises(ValueError):
                    self.tracker.set_calibration({
                        "pulse_distance_cm": 0.4,
                        "wheelbase_cm": 25.0,
                        "max_wheel_angle_deg": angle,
                    })

    def test_invalid_calibration_is_rejected(self):
        for values in (
            {"pulse_distance_cm": 0},
            {"pulse_distance_cm": 0.5, "wheelbase_cm": -1},
            {"pulse_distance_cm": 0.5, "max_wheel_angle_deg": 0},
            {"pulse_distance_cm": 0.5, "max_wheel_angle_deg": 50},
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
