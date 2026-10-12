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
