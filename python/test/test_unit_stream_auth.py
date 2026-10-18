import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from stream import WebStreamer
from stream.auth_api import load_stream_credentials


class StreamAuthTests(unittest.TestCase):
    @staticmethod
    def make_config():
        return types.SimpleNamespace(
            MODE="city",
            STREAM=True,
            STREAM_ALLOW_CONTROL=False,
            RECORD_VIDEO=False,
            USE_BEV=False,
            USE_ML_LANE_DETECTOR=False,
            debug_frames_list=[],
            stream_frame_seq=0,
            OUTPUT_DIR="output",
        )

    def make_streamer(self, env):
        # Isolate tests from a developer's real python/.env file.
        with tempfile.TemporaryDirectory() as tmp:
            with patch("stream.BASE_DIR", tmp), patch.dict(os.environ, env, clear=True):
                return WebStreamer(self.make_config())

    def test_dotenv_credentials_are_loaded_without_overriding_process_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "# dashboard login\nSTREAM_USERNAME='pi operator'\n"
                'STREAM_PASSWORD="strong = pass"\n',
                encoding="utf-8",
            )
            environ = {}
            self.assertEqual(
                load_stream_credentials(env_file, environ=environ),
                ("pi operator", "strong = pass"),
            )

            overridden = {"STREAM_USERNAME": "environment-user"}
            self.assertEqual(
                load_stream_credentials(env_file, environ=overridden),
                ("environment-user", "strong = pass"),
            )

    def test_partial_credentials_fail_closed(self):
        with patch.dict(os.environ, {"STREAM_USERNAME": "robot-user"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "set both STREAM_USERNAME"):
                WebStreamer(self.make_config())

    def test_auth_is_disabled_when_both_credentials_are_unset(self):
        streamer = self.make_streamer({})
        client = streamer.app.test_client()

        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(streamer.auth_enabled)
        self.assertEqual(client.get("/login").status_code, 302)

    def test_dashboard_and_api_require_login_when_credentials_are_set(self):
        streamer = self.make_streamer(
            {"STREAM_USERNAME": "robot-user", "STREAM_PASSWORD": "unique-secret"}
        )

        client = streamer.app.test_client()
        page = client.get("/")
        self.assertEqual(page.status_code, 302)
        self.assertEqual(page.headers["Location"], "/login")

        private_api = client.get("/api/health")
        self.assertEqual(private_api.status_code, 401)
        self.assertEqual(private_api.get_json()["message"], "authentication required")
        self.assertEqual(client.get("/video_feed_frame").status_code, 401)

        login_page = client.get("/login")
        self.assertEqual(login_page.status_code, 200)
        self.assertIn('name="password"', login_page.get_data(as_text=True))

        bad_origin = client.post(
            "/login",
            data={"username": "robot-user", "password": "unique-secret"},
            headers={"Origin": "http://attacker.example"},
        )
        self.assertEqual(bad_origin.status_code, 403)

        wrong_password = client.post(
            "/login",
            data={"username": "robot-user", "password": "wrong"},
            headers={"Origin": "http://localhost"},
        )
        self.assertEqual(wrong_password.status_code, 401)

        success = client.post(
            "/login",
            data={"username": "robot-user", "password": "unique-secret"},
            headers={"Origin": "http://localhost"},
        )
        self.assertEqual(success.status_code, 302)
        self.assertEqual(success.headers["Location"], "/")

        dashboard = client.get("/")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("Log out", dashboard.get_data(as_text=True))

        # Authentication does not override the existing read-only control policy.
        control = client.post(
            "/api/safety",
            json={"action": "stop"},
            headers={"Origin": "http://localhost"},
        )
        self.assertEqual(control.status_code, 403)
        self.assertEqual(control.get_json()["message"], "stream control is disabled")

        cross_site_control = client.post(
            "/api/safety",
            json={"action": "stop"},
            headers={"Origin": "http://attacker.example"},
        )
        self.assertEqual(cross_site_control.status_code, 403)

        logout = client.post("/logout", headers={"Origin": "http://localhost"})
        self.assertEqual(logout.status_code, 302)
        self.assertEqual(client.get("/").status_code, 302)

    def test_login_rate_limits_failed_attempts(self):
        streamer = self.make_streamer(
            {"STREAM_USERNAME": "robot-user", "STREAM_PASSWORD": "unique-secret"}
        )

        client = streamer.app.test_client()
        for index in range(5):
            response = client.post(
                "/login",
                data={"username": "robot-user", "password": f"wrong-{index}"},
                headers={"Origin": "http://localhost"},
            )
            self.assertEqual(response.status_code, 401 if index < 4 else 429)
        blocked = client.post(
            "/login",
            data={"username": "robot-user", "password": "unique-secret"},
            headers={"Origin": "http://localhost"},
        )
        self.assertEqual(blocked.status_code, 429)


if __name__ == "__main__":
    unittest.main()
