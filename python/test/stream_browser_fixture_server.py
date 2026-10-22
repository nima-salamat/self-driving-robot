"""Hardware-free local server for the Stream browser smoke test."""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

# These credentials must remain empty in the isolated, localhost-only fixture.
os.environ["STREAM_USERNAME"] = ""
os.environ["STREAM_PASSWORD"] = ""

import stream
from stream import WebStreamer


class FakeArduinoConnection:
    """Simulated serial transport for browser tests; never opens a physical port."""

    enabled = True
    connected = True
    state = "CONNECTED"
    automatic_commands_enabled = False

    def __init__(self):
        self.commands = []

    def telemetry_status(self, limit=50):
        return {
            "state": "CONNECTED",
            "connected": True,
            "lines": [],
            "lines_received": 0,
            "bytes_received": 0,
            "dropped_lines": 0,
            "buffered_lines": 0,
            "line_rate_hz": 0.0,
            "last_line_age_s": None,
            "reconnect_failures": 0,
            "connected_age_s": 1.0,
            "error": None,
        }

    def send_custom_command(self, command):
        self.commands.append(command)
        return True

    def send_custom_command_with_ack(self, command, timeout=0.75):
        self.commands.append(command)
        return {
            "transmitted": True,
            "acknowledged": True,
            "command_id": len(self.commands),
            "ack_status": "RECEIVED",
            "timed_out": False,
        }

    def set_automatic_commands_enabled(self, enabled):
        self.automatic_commands_enabled = bool(enabled)
        return self.automatic_commands_enabled


def main():
    port = int(os.environ.get("STREAM_BROWSER_TEST_PORT", "41982"))
    tmp = tempfile.TemporaryDirectory(prefix="stream-browser-test-")
    stream.BASE_DIR = tmp.name
    output_dir = str(Path(tmp.name) / "output")
    os.makedirs(output_dir, exist_ok=True)
    config = SimpleNamespace(
        MODE="city",
        STREAM=True,
        STREAM_ALLOW_CONTROL=True,
        STREAM_HOST="127.0.0.1",
        STREAM_PORT=port,
        RECORD_VIDEO=False,
        OUTPUT_DIR=output_dir,
        USE_BEV=False,
        USE_ML_LANE_DETECTOR=False,
        CITY_LANE_DETECTOR="default",
        RUN_LVL="STOP",
        WITHOUT_ARDUINO=False,
        READ_ARDUINO_OUTPUT=True,
        SEND_AUTOMATIC_ARDUINO_COMMANDS=False,
        arduino_connection=FakeArduinoConnection(),
        debug_frames_list=[np.zeros((240, 320, 3), dtype=np.uint8)],
        stream_frame_seq=1,
    )
    streamer = WebStreamer(config)
    app = streamer.app
    print(f"STREAM_BROWSER_TEST_READY:{port}", flush=True)
    try:
        app.run(host="127.0.0.1", port=port, threaded=True, use_reloader=False)
    finally:
        tmp.cleanup()

if __name__ == "__main__":
    main()
