import os
import subprocess
import sys
import unittest
from pathlib import Path


PYTHON_ROOT = Path(__file__).resolve().parents[1]


class ImportContractTests(unittest.TestCase):
    def run_fresh_interpreter(self, code):
        # Use a fresh interpreter so previous imports in the unit-test process
        # cannot mask a circular import during startup.
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
        self.assertEqual(result.returncode, 0, msg=(result.stdout + result.stderr))

    def test_importing_camera_does_not_import_city_runtime(self):
        self.run_fresh_interpreter(
            "import sys; "
            "import vision.camera; "
            "assert 'modes.city.city' not in sys.modules, "
            "'camera import unexpectedly loaded the City runtime'"
        )

    def test_importing_city_vision_does_not_eagerly_import_city_runtime(self):
        self.run_fresh_interpreter(
            "import sys; "
            "from vision.city_vision_processing import VisionProcessor; "
            "assert callable(VisionProcessor); "
            "assert 'modes.city.city' not in sys.modules, "
            "'City configuration import unexpectedly loaded the City runtime'; "
            "from modes.city import start; "
            "assert callable(start); "
            "assert 'modes.city.city' not in sys.modules, "
            "'Importing the lazy start entrypoint loaded the City runtime'"
        )

    def test_importing_race_config_does_not_eagerly_import_race_runtime(self):
        self.run_fresh_interpreter(
            "import sys; "
            "from modes.race import config_race, start; "
            "assert config_race.MODE == 'race'; "
            "assert callable(start); "
            "assert 'modes.race.race' not in sys.modules, "
            "'Importing Race configuration loaded the Race runtime'"
        )


if __name__ == "__main__":
    unittest.main()
