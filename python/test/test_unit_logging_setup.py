import io
import logging
from pathlib import Path
import sys
import tempfile
import unittest

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from utils import logging_setup


_MISSING = object()


class LoggingSetupTests(unittest.TestCase):
    def setUp(self):
        self.root = logging.getLogger()
        self.original_handlers = list(self.root.handlers)
        self.original_level = self.root.level
        self.original_disable = logging.root.manager.disable
        self.original_marker = getattr(
            self.root, logging_setup._LOGGER_CONFIGURED, _MISSING
        )
        self.original_dependency_levels = {
            name: logging.getLogger(name).level
            for name in ("picamera2", "picamera2.picamera2")
        }
        for handler in list(self.root.handlers):
            self.root.removeHandler(handler)
        if hasattr(self.root, logging_setup._LOGGER_CONFIGURED):
            delattr(self.root, logging_setup._LOGGER_CONFIGURED)

    def tearDown(self):
        for handler in list(self.root.handlers):
            self.root.removeHandler(handler)
            if handler not in self.original_handlers:
                handler.close()
        for handler in self.original_handlers:
            if handler not in self.root.handlers:
                self.root.addHandler(handler)
        self.root.setLevel(self.original_level)
        if self.original_marker is _MISSING:
            if hasattr(self.root, logging_setup._LOGGER_CONFIGURED):
                delattr(self.root, logging_setup._LOGGER_CONFIGURED)
        else:
            setattr(
                self.root,
                logging_setup._LOGGER_CONFIGURED,
                self.original_marker,
            )
        logging.disable(self.original_disable)
        for name, level in self.original_dependency_levels.items():
            logging.getLogger(name).setLevel(level)

    def test_debug_records_are_filtered_in_city_and_race_and_from_file(self):
        with tempfile.TemporaryDirectory() as log_dir:
            # Mode DEBUG is commonly enabled for visualization, but must not
            # cause DEBUG-level log records to appear in any output destination.
            logging_setup.configure_logging(debug=True, log_dir=log_dir)
            self.assertEqual(self.root.level, logging.INFO)

            console = next(
                handler
                for handler in self.root.handlers
                if isinstance(handler, logging.StreamHandler)
                and not isinstance(handler, logging.FileHandler)
            )
            console_output = io.StringIO()
            console.setStream(console_output)

            for mode_logger in ("modes.city.city", "modes.race.race"):
                with self.subTest(mode=mode_logger):
                    logger = logging.getLogger(mode_logger)
                    logger.debug("DEBUG-MUST-NOT-APPEAR-%s", mode_logger)
                    logger.info("INFO-MUST-APPEAR-%s", mode_logger)
                    logger.warning("WARNING-MUST-APPEAR-%s", mode_logger)
                    logger.error("ERROR-MUST-APPEAR-%s", mode_logger)
                    logger.critical("CRITICAL-MUST-APPEAR-%s", mode_logger)

            for handler in self.root.handlers:
                handler.flush()

            console_text = console_output.getvalue()
            log_text = (Path(log_dir) / "robot.log").read_text(encoding="utf-8")
            self.assertNotIn("DEBUG-MUST-NOT-APPEAR", console_text)
            self.assertNotIn("DEBUG-MUST-NOT-APPEAR", log_text)
            for level in ("INFO", "WARNING", "ERROR", "CRITICAL"):
                self.assertIn(f"{level}-MUST-APPEAR", console_text)
                self.assertIn(f"{level}-MUST-APPEAR", log_text)

    def test_reconfiguration_cannot_restore_debug_logging(self):
        with tempfile.TemporaryDirectory() as log_dir:
            logging_setup.configure_logging(debug=True, log_dir=log_dir)

            # Simulate permissive logger/handler levels left by other setup code.
            self.root.setLevel(logging.DEBUG)
            for handler in self.root.handlers:
                handler.setLevel(logging.DEBUG)

            logging_setup.configure_logging(debug=True, log_dir=log_dir)

            self.assertEqual(self.root.level, logging.INFO)
            self.assertTrue(
                all(handler.level == logging.INFO for handler in self.root.handlers)
            )


if __name__ == "__main__":
    unittest.main()
