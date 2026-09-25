import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from stream import WebStreamer


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


if __name__ == "__main__":
    unittest.main()
