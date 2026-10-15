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
from utils.parser import parse_args


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

    def _capture_log_output(self, level):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        logging_setup.configure_logging(level=level, log_dir=temp_dir.name)
        console = next(
            handler
            for handler in self.root.handlers
            if isinstance(handler, logging.StreamHandler)
            and not isinstance(handler, logging.FileHandler)
        )
        console_output = io.StringIO()
        console.setStream(console_output)
        return temp_dir.name, console_output

    def test_default_log_level_is_info(self):
        args = parse_args([])
        self.assertEqual(args.log_level, "INFO")

    def test_cli_log_level_is_case_insensitive(self):
        args = parse_args(["--log-level", "debug"])
        self.assertEqual(args.log_level, "DEBUG")

    def test_info_level_filters_debug_but_keeps_info_and_above_in_both_outputs(self):
        log_dir, console_output = self._capture_log_output("INFO")
        logger = logging.getLogger("modes.race.race")
        original_logger_level = logger.level
        logger.setLevel(logging.NOTSET)
        try:
            logger.debug("DEBUG-MUST-NOT-APPEAR")
            logger.info("INFO-MUST-APPEAR")
            logger.warning("WARNING-MUST-APPEAR")
            logger.error("ERROR-MUST-APPEAR")
            logger.critical("CRITICAL-MUST-APPEAR")
        finally:
            logger.setLevel(original_logger_level)

        for handler in self.root.handlers:
            handler.flush()

        console_text = console_output.getvalue()
        file_text = (Path(log_dir) / "robot.log").read_text(encoding="utf-8")
        for output in (console_text, file_text):
            self.assertNotIn("DEBUG-MUST-NOT-APPEAR", output)
            for marker in ("INFO-MUST-APPEAR", "WARNING-MUST-APPEAR",
                           "ERROR-MUST-APPEAR", "CRITICAL-MUST-APPEAR"):
                self.assertIn(marker, output)

    def test_explicit_debug_level_emits_debug_records_to_both_outputs(self):
        log_dir, console_output = self._capture_log_output("DEBUG")
        logger = logging.getLogger("modes.race.race")
        original_logger_level = logger.level
        logger.setLevel(logging.NOTSET)
        try:
            logger.debug("RACE-DEBUG-VISIBLE")
        finally:
            logger.setLevel(original_logger_level)
        for handler in self.root.handlers:
            handler.flush()

        self.assertIn("RACE-DEBUG-VISIBLE", console_output.getvalue())
        file_text = (Path(log_dir) / "robot.log").read_text(encoding="utf-8")
        self.assertIn("RACE-DEBUG-VISIBLE", file_text)
        self.assertEqual(self.root.level, logging.DEBUG)
        self.assertTrue(
            all(handler.level == logging.DEBUG for handler in self.root.handlers)
        )

    def test_reconfiguration_changes_all_handler_levels(self):
        with tempfile.TemporaryDirectory() as log_dir:
            logging_setup.configure_logging(level="DEBUG", log_dir=log_dir)
            logging_setup.configure_logging(level="WARNING", log_dir=log_dir)
            self.assertEqual(self.root.level, logging.WARNING)
            self.assertTrue(
                all(handler.level == logging.WARNING for handler in self.root.handlers)
            )

    def test_invalid_level_is_rejected(self):
        with tempfile.TemporaryDirectory() as log_dir:
            with self.assertRaises(ValueError):
                logging_setup.configure_logging(level="VERBOSE", log_dir=log_dir)


if __name__ == "__main__":
    unittest.main()
