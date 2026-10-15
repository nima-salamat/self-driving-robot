import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from stream import _make_stream_request_handler, start_stream
from utils.parser import parse_args
from werkzeug.serving import WSGIRequestHandler


class StreamRequestLoggingTests(unittest.TestCase):
    def test_request_logs_are_disabled_by_default(self):
        args = parse_args([])
        self.assertFalse(args.stream_request_logs)

    def test_request_logs_can_be_enabled_explicitly(self):
        args = parse_args(["--stream", "--stream-request-logs"])
        self.assertTrue(args.stream)
        self.assertTrue(args.stream_request_logs)

    def test_default_handler_suppresses_access_log_calls(self):
        handler_type = _make_stream_request_handler(log_requests=False)
        handler = object.__new__(handler_type)

        with patch.object(WSGIRequestHandler, "log_request") as parent_log:
            handler.log_request(200, 123)
            parent_log.assert_not_called()

    def test_opt_in_handler_emits_access_log_calls(self):
        handler_type = _make_stream_request_handler(log_requests=True)
        handler = object.__new__(handler_type)

        with patch.object(WSGIRequestHandler, "log_request") as parent_log:
            handler.log_request(200, 123)
            parent_log.assert_called_once_with(200, 123)

    def test_start_stream_passes_request_logging_policy_to_server(self):
        class FakeServer:
            server_address = ("127.0.0.1", 5000)
            server_port = 5000

            def serve_forever(self):
                return None

            def server_close(self):
                return None

        for enabled in (False, True):
            with self.subTest(request_logs=enabled):
                import types

                config = types.SimpleNamespace(
                    MODE="test",
                    STREAM_HOST="127.0.0.1",
                    STREAM_PORT=5000,
                    STREAM_ALLOW_CONTROL=False,
                    STREAM_REQUEST_LOGS=enabled,
                )
                server = FakeServer()
                output = io.StringIO()
                with patch("stream.make_server", return_value=server) as make_server, patch(
                    "stream._stream_access_urls", return_value=[]
                ), redirect_stdout(output):
                    start_stream(config)

                handler_type = make_server.call_args.kwargs["request_handler"]
                handler = object.__new__(handler_type)
                with patch.object(WSGIRequestHandler, "log_request") as parent_log:
                    handler.log_request(200, 123)
                    if enabled:
                        parent_log.assert_called_once_with(200, 123)
                    else:
                        parent_log.assert_not_called()


if __name__ == "__main__":
    unittest.main()
