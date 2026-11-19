import sys
import unittest
from pathlib import Path

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from modes.simulation.settings import _defaults, _validate_settings


class LaneRecoverySettingsTests(unittest.TestCase):
    def test_recovery_expansion_has_a_bounded_default_for_both_backends(self):
        for backend in ("carla", "avis"):
            with self.subTest(backend=backend):
                settings = _defaults("city", backend)
                self.assertEqual(settings["HALL_LINE_TRACKING_REACQUIRE_MARGIN"], 0.28)

    def test_recovery_expansion_accepts_documented_bounds(self):
        for value in (0.05, 0.28, 0.45):
            with self.subTest(value=value):
                clean = _validate_settings(
                    {"HALL_LINE_TRACKING_REACQUIRE_MARGIN": value},
                    backend="carla",
                )
                self.assertEqual(clean["HALL_LINE_TRACKING_REACQUIRE_MARGIN"], value)

    def test_recovery_expansion_rejects_unbounded_or_non_finite_values(self):
        for value in (0.0, 0.049, 0.451, 1.0, float("nan"), float("inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    _validate_settings(
                        {"HALL_LINE_TRACKING_REACQUIRE_MARGIN": value},
                        backend="carla",
                    )


if __name__ == "__main__":
    unittest.main()
