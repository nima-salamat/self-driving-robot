import os
import subprocess
import sys
import unittest
from pathlib import Path


PYTHON_ROOT = Path(__file__).resolve().parents[1]


class ImportContractTests(unittest.TestCase):
    def test_importing_camera_does_not_import_city_runtime(self):
        # Use a fresh interpreter so prior imports in the unit-test process
        # cannot mask a circular import during camera/calibration startup.
        code = (
            "import sys; "
            "import vision.camera; "
            "assert 'modes.city.city' not in sys.modules, "
            "'camera import unexpectedly loaded the City runtime'"
        )
        env = os.environ.copy()
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (
            str(PYTHON_ROOT)
            if not existing_pythonpath
            else str(PYTHON_ROOT) + os.pathsep + existing_pythonpath
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=PYTHON_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=(result.stdout + result.stderr),
        )


if __name__ == "__main__":
    unittest.main()
