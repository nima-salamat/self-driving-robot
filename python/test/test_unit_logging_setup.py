import io
import logging
import multiprocessing as mp
from pathlib import Path
import sys
import tempfile
import time
import unittest

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from utils import logging_setup
from utils.parser import parse_args


def _emit_central_worker_record(log_queue, level, message):
    from utils.logging_setup import configure_worker_logging
    configure_worker_logging(log_queue, level=level)
    logging.getLogger("traffic_sign_detector.worker_test").warning(message)


class LoggingSetupTests(unittest.TestCase):
    def setUp(self):
        self.root = logging.getLogger()
        logging_setup.shutdown_logging()
        self.original_handlers = list(self.root.handlers)
        self.original_level = self.root.level
        self.original_disable = logging.root.manager.disable
        self.original_dependency_levels = {
            name: logging.getLogger(name).level
            for name in ("picamera2", "picamera2.picamera2")
        }
        for handler in list(self.root.handlers):
            self.root.removeHandler(handler)

    def tearDown(self):
        logging_setup.shutdown_logging()
        for handler in list(self.root.handlers):
            self.root.removeHandler(handler)
            if handler not in self.original_handlers:
                handler.close()
        for handler in self.original_handlers:
            if handler not in self.root.handlers:
                self.root.addHandler(handler)
        self.root.setLevel(self.original_level)
        logging.disable(self.original_disable)
        for name, level in self.original_dependency_levels.items():
            logging.getLogger(name).setLevel(level)

    def _capture_log_output(self, level):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        logging_setup.configure_logging(level=level, log_dir=temp_dir.name)
        console = next(
            handler for handler in self.root.handlers
            if isinstance(handler, logging.StreamHandler)
            and not isinstance(handler, logging.FileHandler)
        )
        console_output = io.StringIO()
        console.setStream(console_output)
        return temp_dir.name, console_output

    def test_default_log_level_is_info(self):
        self.assertEqual(parse_args([]).log_level, "INFO")

    def test_cli_log_level_is_case_insensitive(self):
        self.assertEqual(parse_args(["--log-level", "debug"]).log_level, "DEBUG")

    def test_info_level_filters_debug_but_keeps_info_and_above_in_both_outputs(self):
        log_dir, console_output = self._capture_log_output("INFO")
        logger = logging.getLogger("modes.race.race")
        original_level = logger.level
        logger.setLevel(logging.NOTSET)
        try:
            logger.debug("DEBUG-MUST-NOT-APPEAR")
            logger.info("INFO-MUST-APPEAR")
            logger.warning("WARNING-MUST-APPEAR")
            logger.error("ERROR-MUST-APPEAR")
            logger.critical("CRITICAL-MUST-APPEAR")
        finally:
            logger.setLevel(original_level)
        self.assertTrue(logging_setup.flush_logging())
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
        original_level = logger.level
        logger.setLevel(logging.NOTSET)
        try:
            logger.debug("RACE-DEBUG-VISIBLE")
        finally:
            logger.setLevel(original_level)
        self.assertTrue(logging_setup.flush_logging())
        self.assertIn("RACE-DEBUG-VISIBLE", console_output.getvalue())
        file_text = (Path(log_dir) / "robot.log").read_text(encoding="utf-8")
        self.assertIn("RACE-DEBUG-VISIBLE", file_text)
        self.assertEqual(self.root.level, logging.DEBUG)
        self.assertTrue(all(
            handler.level == logging.DEBUG
            for handler in logging_setup.get_managed_handlers()
        ))

    def test_reconfiguration_is_idempotent_and_updates_only_managed_sinks(self):
        with tempfile.TemporaryDirectory() as log_dir:
            logging_setup.configure_logging(level="DEBUG", log_dir=log_dir)
            first_queue, _ = logging_setup.get_logging_context()
            first_handlers = logging_setup.get_managed_handlers()
            logging_setup.configure_logging(level="WARNING", log_dir=log_dir)
            second_queue, _ = logging_setup.get_logging_context()
            self.assertIs(first_queue, second_queue)
            self.assertEqual(first_handlers, logging_setup.get_managed_handlers())
            self.assertEqual(self.root.level, logging.WARNING)
            self.assertTrue(all(h.level == logging.WARNING for h in first_handlers))

    def test_worker_process_logs_reach_the_single_file_and_stream_tail(self):
        import stream

        log_dir, _console_output = self._capture_log_output("DEBUG")
        buffer_handler = getattr(stream, "_log_buffer_handler", None)
        if buffer_handler is not None and buffer_handler not in self.root.handlers:
            self.root.addHandler(buffer_handler)
        with stream._STREAM_LOG_LOCK:
            stream._STREAM_LOGS.clear()

        log_queue, level = logging_setup.get_logging_context()
        marker = "CENTRAL-WORKER-LOG-" + str(time.time_ns())
        process = mp.get_context("spawn").Process(
            target=_emit_central_worker_record, args=(log_queue, level, marker)
        )
        process.start()
        process.join(timeout=15)
        if process.is_alive():
            process.terminate()
            process.join(timeout=3)
            self.fail("logging worker did not exit")
        self.assertEqual(process.exitcode, 0)
        self.assertTrue(logging_setup.flush_logging(timeout=5.0))

        file_text = (Path(log_dir) / "robot.log").read_text(encoding="utf-8")
        self.assertIn(marker, file_text)
        with stream._STREAM_LOG_LOCK:
            buffered = list(stream._STREAM_LOGS)
        worker_entry = next((item for item in buffered
                             if marker in item.get("message", "")
                             and item.get("logger") == "traffic_sign_detector.worker_test"), None)
        self.assertIsNotNone(worker_entry)
        self.assertTrue(worker_entry["process"].startswith("SpawnProcess"))
        self.assertGreater(worker_entry["process_id"], 0)
        self.assertTrue(worker_entry["thread"])

    def test_different_log_directory_cannot_silently_split_an_active_session(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            logging_setup.configure_logging(level="INFO", log_dir=first)
            with self.assertRaises(RuntimeError):
                logging_setup.configure_logging(level="INFO", log_dir=second)

    def test_invalid_level_is_rejected(self):
        with tempfile.TemporaryDirectory() as log_dir:
            with self.assertRaises(ValueError):
                logging_setup.configure_logging(level="VERBOSE", log_dir=log_dir)


if __name__ == "__main__":
    unittest.main()
