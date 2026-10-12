import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from stream import WebStreamer, publish_debug_frame


class StreamApiTests(unittest.TestCase):
    def make_config(self):
        return types.SimpleNamespace(
            MODE="city",
            STREAM=True,
            STREAM_ALLOW_CONTROL=False,
            RECORD_VIDEO=False,
            USE_BEV=False,
            USE_ML_LANE_DETECTOR=False,
            CITY_LANE_DETECTOR="blsf-beta",
            debug_frames_list=[np.zeros((32, 48, 3), dtype=np.uint8)],
            stream_frame_seq=1,
            OUTPUT_DIR="output",
        )

    def test_wildcard_bind_discovers_private_lan_address(self):
        from unittest.mock import patch
        import socket
        from stream import _stream_access_urls

        class RouteProbe:
            def connect(self, _target):
                pass

            def getsockname(self):
                return ("192.168.1.42", 49152)

            def close(self):
                pass

        with patch(
            "stream.socket.getaddrinfo",
            return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.42", 0))
            ],
        ), patch("stream.socket.gethostname", return_value="robot"), patch(
            "stream.socket.socket", return_value=RouteProbe()
        ):
            urls = _stream_access_urls("0.0.0.0", 5000)

        self.assertIn("http://127.0.0.1:5000", urls)
        self.assertIn("http://192.168.1.42:5000", urls)

    def test_read_only_cli_flag_disables_dashboard_controls(self):
        from unittest.mock import patch
        from utils.parser import parse_args

        with patch.object(sys, "argv", ["main.py", "--stream-read-only"]):
            args = parse_args()

        self.assertIs(args.stream_control, False)

    def test_stream_control_cli_flags_are_mutually_exclusive(self):
        from unittest.mock import patch
        from utils.parser import parse_args

        with patch.object(
            sys,
            "argv",
            ["main.py", "--stream-control", "--stream-read-only"],
        ), self.assertRaises(SystemExit):
            parse_args()

    def test_controls_are_enabled_when_config_allows_updates(self):
        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        streamer = WebStreamer(config)
        client = streamer.app.test_client()

        with patch.object(streamer, "save_conf_to_json"):
            response = client.post(
                "/update_conf",
                json={"RL_TOP_ROI": 0.25},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])
        self.assertEqual(config.RL_TOP_ROI, 0.25)

    def test_read_only_mode_returns_clear_forbidden_message(self):
        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = False
        response = WebStreamer(config).app.test_client().post(
            "/update_conf",
            json={"RL_TOP_ROI": 0.25},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.get_json()["message"],
            "stream control is disabled",
        )

    def test_city_and_race_defaults_allow_lan_dashboard_controls(self):
        from modes.city import config_city
        from modes.race import config_race

        for config in (config_city, config_race):
            with self.subTest(mode=config.MODE):
                self.assertEqual(config.STREAM_HOST, "0.0.0.0")
                self.assertTrue(config.STREAM_ALLOW_CONTROL)

    def test_mode_endpoint_reports_active_city_detector(self):
        streamer = WebStreamer(self.make_config())
        client = streamer.app.test_client()

        response = client.get("/api/mode")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["mode"], "city")
        self.assertEqual(data["features"]["lane_detector"], "blsf-beta")
        self.assertFalse(data["features"]["bev"])

    def test_mjpeg_endpoint_has_stream_content_type(self):
        config = self.make_config()
        streamer = WebStreamer(config)
        client = streamer.app.test_client()

        response = client.get(
            "/video_feed",
            buffered=False,
        )

        self.assertIn(
            "multipart/x-mixed-replace",
            response.content_type,
        )
        response.close()

    def test_index_page_keeps_javascript_newline_escape_valid(self):
        response = WebStreamer(self.make_config()).app.test_client().get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))
        html = response.get_data(as_text=True)

        # HTML_TEMPLATE is a Python triple-quoted string. The rendered
        # JavaScript must contain a backslash+n escape, not a literal newline
        # inside a single-quoted JavaScript string.
        self.assertIn(
            "output.textContent = (j.lines || []).join('\\n');",
            html,
        )
        self.assertNotIn(
            "output.textContent = (j.lines || []).join('\n');",
            html,
        )

    def test_dashboard_polling_uses_backoff_when_server_is_unreachable(self):
        response = WebStreamer(self.make_config()).app.test_client().get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)

        self.assertIn("async function fetchDashboardJson", html)
        self.assertIn("dashboardApiRetryAt", html)
        self.assertRegex(html, r"Math\.min\(\s*30000")
        self.assertIn("fetchDashboardJson('/api/health')", html)
        self.assertIn("fetchDashboardJson('/api/arduino-output')", html)
        self.assertIn("fetchDashboardJson('/get_values')", html)
        self.assertIn("let frameRetryAt = 0;", html)
        self.assertIn("if(!syncActive || frameRequestInFlight || !dashboardApiOnline) return;", html)

    def test_rendered_inline_javascript_passes_node_syntax_check(self):
        import re
        import shutil
        import subprocess
        import tempfile

        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is not installed; JavaScript syntax check skipped")

        response = WebStreamer(self.make_config()).app.test_client().get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        script_match = re.search(r"<script>(.*?)</script>", html, re.DOTALL)
        self.assertIsNotNone(script_match, "Rendered page has no inline script")

        with tempfile.TemporaryDirectory() as tmp_dir:
            script_path = Path(tmp_dir) / "stream-dashboard.js"
            script_path.write_text(script_match.group(1), encoding="utf-8")
            result = subprocess.run(
                [node, "--check", str(script_path)],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_video_frame_endpoint_does_not_cache_live_frames(self):
        config = self.make_config()
        config.debug_frames_list = []
        config.stream_frame_seq = 0
        streamer = WebStreamer(config)
        client = streamer.app.test_client()

        publish_debug_frame(
            config,
            np.zeros((32, 48, 3), dtype=np.uint8),
        )
        first = client.get("/video_feed_frame")

        publish_debug_frame(
            config,
            np.full((32, 48, 3), 255, dtype=np.uint8),
        )
        second = client.get("/video_feed_frame")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(first.data, second.data)
        self.assertEqual(second.headers["X-Stream-Frame-Sequence"], "2")
        self.assertIn("no-store", second.headers["Cache-Control"])

    def test_missing_video_frame_is_retryable_and_not_cacheable(self):
        config = self.make_config()
        config.debug_frames_list = []
        config.stream_frame_seq = 0
        response = WebStreamer(config).app.test_client().get(
            "/video_feed_frame"
        )

        self.assertEqual(response.status_code, 204)
        self.assertIn("no-store", response.headers["Cache-Control"])


if __name__ == "__main__":
    unittest.main()
