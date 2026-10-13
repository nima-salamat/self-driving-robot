import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from main import _validate_ml_lane_runtime
from utils.preflight import run_preflight


class MLLaneRuntimeDependencyTests(unittest.TestCase):
    def test_runtime_validation_is_skipped_when_ml_is_disabled(self):
        config = SimpleNamespace(USE_ML_LANE_DETECTOR=False)
        with patch("main.importlib.import_module") as import_module:
            _validate_ml_lane_runtime(config)
        import_module.assert_not_called()

    def test_missing_ncnn_fails_before_mode_start_with_install_instructions(self):
        config = SimpleNamespace(USE_ML_LANE_DETECTOR=True)
        with patch(
            "main.importlib.import_module",
            side_effect=ModuleNotFoundError("No module named 'ncnn'"),
        ):
            with self.assertRaises(SystemExit) as caught:
                _validate_ml_lane_runtime(config)

        message = str(caught.exception)
        self.assertIn("NCNN Python runtime", message)
        self.assertIn("python3 -m pip install -r requirements.txt", message)

    def test_preflight_checks_ncnn_when_ml_lane_detection_is_enabled(self):
        config = SimpleNamespace(
            USE_ML_LANE_DETECTOR=True,
            USE_SIGN=False,
            WITH_SIGN=False,
            OUTPUT_DIR="output",
            STREAM=False,
            WITHOUT_ARDUINO=True,
        )

        def import_module(name):
            if name == "ncnn":
                raise ModuleNotFoundError("No module named 'ncnn'")
            return object()

        with (
            patch("utils.preflight.importlib.import_module", side_effect=import_module),
            patch("utils.preflight._check_output_storage"),
            patch("utils.preflight._check_models"),
            patch("utils.preflight._check_camera"),
            patch("utils.preflight._check_arduino"),
            patch("utils.preflight._check_stream_port"),
        ):
            report = run_preflight(config)

        ncnn_check = next(
            check for check in report.checks
            if check.name == "NCNN ML lane runtime"
        )
        self.assertFalse(ncnn_check.ok)
        self.assertIn("No module named 'ncnn'", ncnn_check.detail)
        self.assertFalse(report.ok)


if __name__ == "__main__":
    unittest.main()
