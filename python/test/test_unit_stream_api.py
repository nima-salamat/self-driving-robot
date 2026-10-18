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

    def test_city_and_race_stream_defaults_are_disabled(self):
        from modes.city import config_city
        from modes.race import config_race

        for config in (config_city, config_race):
            with self.subTest(mode=config.MODE):
                self.assertFalse(config.STREAM)

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
        self.assertIn("fault.message", html)
        self.assertIn("details.join(' | ')", html)
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
        scripts = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
        self.assertGreaterEqual(len(scripts), 2, "Expected dashboard and extension inline scripts")

        with tempfile.TemporaryDirectory() as tmp_dir:
            for index, script in enumerate(scripts):
                with self.subTest(inline_script=index):
                    script_path = Path(tmp_dir) / f"stream-dashboard-{index}.js"
                    script_path.write_text(script, encoding="utf-8")
                    result = subprocess.run(
                        [node, "--check", str(script_path)],
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_full_config_export_contains_all_ui_sections_and_current_mode(self):
        client = WebStreamer(self.make_config()).app.test_client()
        response = client.get("/api/config/full")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["mode"], "city")
        self.assertIn("RL_TOP_ROI", data["values"])
        self.assertIn("LANE_THRESHOLD", data["advanced"])
        self.assertIn("colors", data["ui"])
        self.assertIn("visible", data["ui"])
        self.assertIn("opacity", data["ui"])
        self.assertIn("runtime", data)

    def test_full_config_import_is_read_only_until_controls_are_enabled(self):
        config = self.make_config()
        client = WebStreamer(config).app.test_client()
        payload = {
            "schema_version": 1,
            "mode": "city",
            "values": {"RL_TOP_ROI": 0.25},
            "advanced": {},
            "ui": {},
        }

        response = client.post("/api/config/full", json=payload)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(config.RL_TOP_ROI if hasattr(config, "RL_TOP_ROI") else 0.0, 0.0)

    def test_saving_dashboard_settings_preserves_unrelated_mode_config(self):
        import json
        import tempfile

        config = self.make_config()
        streamer = WebStreamer(config)
        with tempfile.TemporaryDirectory() as tmp_dir, patch("stream.BASE_DIR", tmp_dir):
            filename = Path(tmp_dir) / "city.json"
            original = {
                "SPEED": 220,
                "SIGN_AREA_MIN_PX2": 1234,
                "WITH_SIGN": True,
                "CUSTOM_MODE_SETTING": {"enabled": True},
                "RL_TOP_ROI": 0.2,
            }
            filename.write_text(json.dumps(original), encoding="utf-8")
            config.RL_TOP_ROI = 0.35

            self.assertTrue(streamer.save_conf_to_json())
            saved = json.loads(filename.read_text(encoding="utf-8"))

        self.assertEqual(saved["SPEED"], 220)
        self.assertEqual(saved["SIGN_AREA_MIN_PX2"], 1234)
        self.assertEqual(saved["CUSTOM_MODE_SETTING"], {"enabled": True})
        self.assertEqual(saved["RL_TOP_ROI"], 0.35)

    def test_full_config_round_trip_and_history_are_persisted_atomically(self):
        import tempfile

        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        streamer = WebStreamer(config)
        client = streamer.app.test_client()

        with tempfile.TemporaryDirectory() as tmp_dir, patch("stream.BASE_DIR", tmp_dir):
            exported = client.get("/api/config/full")
            self.assertEqual(exported.status_code, 200)
            payload = exported.get_json()
            payload["values"]["RL_TOP_ROI"] = 0.25

            applied = client.post("/api/config/full", json=payload)
            self.assertEqual(applied.status_code, 200, applied.get_data(as_text=True))
            self.assertTrue(applied.get_json()["success"])
            self.assertEqual(config.RL_TOP_ROI, 0.25)

            history = client.get("/api/config/history")
            self.assertEqual(history.status_code, 200)
            self.assertGreaterEqual(len(history.get_json()["items"]), 1)

    def test_full_config_rejects_wrong_mode_and_non_finite_roi(self):
        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        client = WebStreamer(config).app.test_client()
        base = {
            "schema_version": 1,
            "mode": "city",
            "values": {},
            "advanced": {},
            "ui": {},
        }

        wrong_mode = dict(base, mode="race")
        response = client.post("/api/config/full", json=wrong_mode)
        self.assertEqual(response.status_code, 400)

        bad_roi = dict(base, values={"RL_TOP_ROI": float("nan")})
        response = client.post("/api/config/full", json=bad_roi)
        self.assertEqual(response.status_code, 400)

    def test_workspace_rejects_out_of_range_annotations_and_saves_profiles(self):
        import tempfile

        client = WebStreamer(self.make_config()).app.test_client()
        with tempfile.TemporaryDirectory() as tmp_dir, patch("stream.BASE_DIR", tmp_dir):
            bad = client.post(
                "/api/workspace",
                json={"action": "save_workspace", "workspace": {
                    "annotations": [{"kind": "marker", "u": 1.5, "v": 0.2}]
                }},
            )
            self.assertEqual(bad.status_code, 400)

            saved = client.post(
                "/api/workspace",
                json={"action": "save_profile", "name": "Night layout",
                      "workspace": {"view": {"zoom": 1.5, "grid": True}}},
            )
            self.assertEqual(saved.status_code, 200, saved.get_data(as_text=True))
            loaded = client.post(
                "/api/workspace",
                json={"action": "load_profile", "name": "Night layout"},
            )
            self.assertEqual(loaded.status_code, 200)
            self.assertEqual(loaded.get_json()["workspace"]["view"]["zoom"], 1.5)

    def test_software_stop_endpoint_is_gated_and_clearly_not_hardware_emergency_stop(self):
        import tempfile

        config = self.make_config()
        client = WebStreamer(config).app.test_client()
        denied = client.post("/api/safety", json={"action": "stop"})
        self.assertEqual(denied.status_code, 403)

        config.STREAM_ALLOW_CONTROL = True
        with tempfile.TemporaryDirectory() as tmp_dir, patch("stream.BASE_DIR", tmp_dir):
            stopped = client.post("/api/safety", json={"action": "stop"})
            self.assertEqual(stopped.status_code, 200)
            self.assertEqual(config.RUN_LVL, "STOP")
            self.assertFalse(stopped.get_json()["hardware_emergency_stop"])

            resumed = client.post("/api/safety", json={"action": "resume"})
            self.assertEqual(resumed.status_code, 200)
            self.assertEqual(config.RUN_LVL, "MOVE")

    def test_server_log_endpoint_redacts_bearer_credentials(self):
        import logging

        config = self.make_config()
        client = WebStreamer(config).app.test_client()
        secret = "super-secret-token-123"
        logging.getLogger("stream.redaction_test").warning(
            "Authorization: Bearer %s", secret
        )

        response = client.get("/api/logs?level=WARNING&q=authorization&limit=10")

        self.assertEqual(response.status_code, 200)
        serialized = response.get_data(as_text=True)
        self.assertNotIn(secret, serialized)
        self.assertIn("[REDACTED]", serialized)

    def test_config_import_and_advanced_edit_cannot_bypass_software_stop(self):
        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        config.RUN_LVL = "STOP"
        client = WebStreamer(config).app.test_client()

        payload = client.get("/api/config/full").get_json()
        payload["advanced"]["RUN_LVL"] = "MOVE"
        imported = client.post("/api/config/full", json=payload)
        self.assertEqual(imported.status_code, 400)
        self.assertEqual(config.RUN_LVL, "STOP")

        edited = client.post("/set_advanced", json={"RUN_LVL": "MOVE"})
        self.assertEqual(edited.status_code, 409)
        self.assertEqual(config.RUN_LVL, "STOP")

        # The dedicated software-safety action remains the explicit resume path.
        resumed = client.post("/api/safety", json={"action": "resume"})
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(config.RUN_LVL, "MOVE")

    def test_roi_batch_validation_does_not_apply_a_partial_update(self):
        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        config.RL_TOP_ROI = 0.15
        config.RL_BOTTOM_ROI = 0.85
        response = WebStreamer(config).app.test_client().post(
            "/update_conf",
            json={"RL_TOP_ROI": 0.25, "RL_BOTTOM_ROI": "not-a-number"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(config.RL_TOP_ROI, 0.15)
        self.assertEqual(config.RL_BOTTOM_ROI, 0.85)

    def test_advanced_batch_rolls_back_when_a_later_value_is_invalid(self):
        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        config.LANE_THRESHOLD = 125
        config.WITH_SIGN = False
        config.WITH_APRILTAG = False
        response = WebStreamer(config).app.test_client().post(
            "/set_advanced",
            json={"LANE_THRESHOLD": 160, "WITH_SIGN": True, "WITH_APRILTAG": True},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(config.LANE_THRESHOLD, 125)
        self.assertFalse(config.WITH_SIGN)
        self.assertFalse(config.WITH_APRILTAG)

    def test_live_feature_rolls_back_when_config_persistence_fails(self):
        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        streamer = WebStreamer(config)
        client = streamer.app.test_client()

        with patch.object(streamer, "save_conf_to_json", return_value=False):
            response = client.post(
                "/api/features",
                json={"feature": "DETECT_OBJECT", "value": True},
            )

        self.assertEqual(response.status_code, 500)
        self.assertFalse(getattr(config, "DETECT_OBJECT", False))

    def test_layer_settings_roll_back_when_atomic_persistence_fails(self):
        import json

        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        streamer = WebStreamer(config)
        client = streamer.app.test_client()
        before = json.loads(json.dumps(streamer.ui_settings))

        with patch.object(streamer, "save_ui_settings", return_value=False):
            response = client.post("/set_ui", json={"visible": {"RL": False}})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(streamer.ui_settings, before)

    def test_software_stop_is_retained_when_persistence_fails(self):
        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        streamer = WebStreamer(config)
        client = streamer.app.test_client()

        with patch.object(streamer, "save_conf_to_json", return_value=False):
            stopped = client.post("/api/safety", json={"action": "stop"})
            self.assertEqual(stopped.status_code, 500)
            self.assertEqual(config.RUN_LVL, "STOP")
            self.assertTrue(stopped.get_json()["software_stop_active"])

            resumed = client.post("/api/safety", json={"action": "resume"})
            self.assertEqual(resumed.status_code, 500)
            self.assertEqual(config.RUN_LVL, "STOP")
            self.assertTrue(resumed.get_json()["software_stop_active"])

    def test_camera_api_exposes_sensor_ranges_and_rejects_out_of_range_controls(self):
        import tempfile

        class FakePicam:
            camera_controls = {
                "ExposureTime": (100, 100000, 10000),
                "AnalogueGain": (1.0, 16.0, 6.0),
                "AeEnable": (False, True, False),
                "AwbEnable": (False, True, False),
            }

            def __init__(self):
                self.applied = []

            def set_controls(self, controls):
                self.applied.append(dict(controls))

        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        picam = FakePicam()
        config.camera = types.SimpleNamespace(
            pi_mode=True,
            picam=picam,
            _dashboard_image_controls={
                "ExposureTime": 10000,
                "AnalogueGain": 6.0,
                "AeEnable": False,
                "AwbEnable": False,
            },
            requested_frame_rate=30,
            measured_frame_rate=29,
        )
        streamer = WebStreamer(config)
        client = streamer.app.test_client()

        with tempfile.TemporaryDirectory() as tmp_dir, patch("stream.BASE_DIR", tmp_dir):
            status = client.get("/api/camera/settings")
            self.assertEqual(status.status_code, 200)
            camera = status.get_json()["camera"]
            self.assertEqual(camera["control_ranges"]["ExposureTime"], {"min": 100.0, "max": 100000.0})
            self.assertEqual(camera["control_ranges"]["AnalogueGain"], {"min": 1.0, "max": 16.0})

            invalid = client.post("/api/camera/settings", json={"ExposureTime": 100001})
            self.assertEqual(invalid.status_code, 400)
            self.assertEqual(picam.applied, [])

            valid = client.post("/api/camera/settings", json={"ExposureTime": 20000})
            self.assertEqual(valid.status_code, 200)
            self.assertEqual(picam.applied, [{"ExposureTime": 20000}])

    def test_camera_and_processing_rate_report_unavailable_capabilities_cleanly(self):
        streamer = WebStreamer(self.make_config())
        client = streamer.app.test_client()

        camera = client.get("/api/camera/settings")
        self.assertEqual(camera.status_code, 200)
        self.assertFalse(camera.get_json()["camera"]["available"])

        rate = client.get("/api/processing-rate")
        self.assertEqual(rate.status_code, 200)
        self.assertFalse(rate.get_json()["available"])

        config = streamer.config
        config.STREAM_ALLOW_CONTROL = True
        denied = client.post("/api/processing-rate", json={"target_fps": 25})
        self.assertEqual(denied.status_code, 409)

    def test_config_preset_can_be_queried_for_comparison(self):
        import tempfile

        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        client = WebStreamer(config).app.test_client()
        with tempfile.TemporaryDirectory() as tmp_dir, patch("stream.BASE_DIR", tmp_dir):
            saved = client.post("/api/config/presets", json={"action": "save", "name": "Stable"})
            self.assertEqual(saved.status_code, 200, saved.get_data(as_text=True))
            queried = client.get("/api/config/presets?name=Stable")
            self.assertEqual(queried.status_code, 200)
            self.assertIn("config", queried.get_json())

    def test_custom_preview_roi_geometry_and_drawing_tool_are_validated(self):
        import tempfile

        client = WebStreamer(self.make_config()).app.test_client()
        with tempfile.TemporaryDirectory() as tmp_dir, patch("stream.BASE_DIR", tmp_dir):
            valid = client.post(
                "/api/workspace",
                json={"action": "save_workspace", "workspace": {
                    "view": {"tool": "roi_trapezoid", "rightPaneWidth": 380},
                    "annotations": [{
                        "kind": "roi_trapezoid", "x": 0.1, "y": 0.2,
                        "w": 0.5, "h": 0.4, "topFactor": 0.45,
                        "label": "Preview-only region"
                    }],
                }},
            )
            self.assertEqual(valid.status_code, 200, valid.get_data(as_text=True))
            bad = client.post(
                "/api/workspace",
                json={"action": "save_workspace", "workspace": {
                    "annotations": [{
                        "kind": "roi_rect", "x": 0.8, "y": 0.2,
                        "w": 0.4, "h": 0.2
                    }],
                }},
            )
            self.assertEqual(bad.status_code, 400)

    def test_live_feature_controls_are_gated_and_persisted(self):
        import tempfile

        config = self.make_config()
        config.apply_marker_mode = lambda mode: (
            setattr(config, "WITH_SIGN", mode == "sign"),
            setattr(config, "WITH_APRILTAG", mode == "apriltag"),
            setattr(config, "USE_SIGN", mode == "sign"),
        )
        client = WebStreamer(config).app.test_client()

        before = client.get("/api/features")
        self.assertEqual(before.status_code, 200)
        self.assertFalse(before.get_json()["controls_enabled"])

        config.STREAM_ALLOW_CONTROL = True
        with tempfile.TemporaryDirectory() as tmp_dir, patch("stream.BASE_DIR", tmp_dir):
            enabled = client.post(
                "/api/features",
                json={"feature": "DETECT_OBJECT", "value": True},
            )
            self.assertEqual(enabled.status_code, 200, enabled.get_data(as_text=True))
            self.assertTrue(config.DETECT_OBJECT)
            exported = client.get("/api/config/full").get_json()
            self.assertTrue(exported["advanced"]["DETECT_OBJECT"])

            marker = client.post(
                "/api/features",
                json={"feature": "marker_mode", "value": "apriltag"},
            )
            self.assertEqual(marker.status_code, 200, marker.get_data(as_text=True))
            self.assertTrue(config.WITH_APRILTAG)
            self.assertFalse(config.WITH_SIGN)

            startup_only = client.post(
                "/api/features",
                json={"feature": "TRAFFIC_LIGHTS_ENABLED", "value": True},
            )
            self.assertEqual(startup_only.status_code, 400)

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
