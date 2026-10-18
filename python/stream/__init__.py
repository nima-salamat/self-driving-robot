import logging
import cv2
import json
import os
import socket
import ipaddress
import math
import re
from urllib.parse import urlsplit
import threading
import time
from collections import deque
from flask import Flask, Response, request, render_template, render_template_string, jsonify
from werkzeug.serving import WSGIRequestHandler, make_server
from .template import HTML_TEMPLATE
from .capabilities import mode_capabilities, marker_mode, set_marker_mode
from base_config import BASE_DIR

logger = logging.getLogger(__name__)

CONFIG_HISTORY_LIMIT = 50
STREAM_LOG_LIMIT = 500

# Serialize state-file operations across dashboard threads. RLock is required
# because history recording holds the lock while calling _write_json_atomic.
_STATE_FILE_LOCKS = {}
_STATE_FILE_LOCKS_GUARD = threading.Lock()


def _state_file_lock(filename):
    """Return a process-wide re-entrant lock for a state file path."""
    normalized = os.path.normcase(os.path.abspath(os.fspath(filename)))
    with _STATE_FILE_LOCKS_GUARD:
        lock = _STATE_FILE_LOCKS.get(normalized)
        if lock is None:
            lock = threading.RLock()
            _STATE_FILE_LOCKS[normalized] = lock
        return lock


_STREAM_LOG_LOCK = threading.RLock()
_STREAM_LOGS = deque(maxlen=STREAM_LOG_LIMIT)
_SECRET_PATTERNS = (
    # Redact bearer credentials first; otherwise the authorization-key rule
    # can replace only the word "Bearer" and leave the credential behind.
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/-]+=*"),
    re.compile(r"(?i)(token|password|passwd|secret|api[_-]?key|authorization)(\s*[:=]\s*)([^\s,;]+)"),
)


def _redact_log_message(message):
    value = str(message)[:2000]
    for pattern in _SECRET_PATTERNS:
        if "bearer" in pattern.pattern.lower():
            value = pattern.sub("Bearer [REDACTED]", value)
        else:
            value = pattern.sub(lambda match: match.group(1) + match.group(2) + "[REDACTED]", value)
    return value


class _StreamLogBuffer(logging.Handler):
    def emit(self, record):
        try:
            name = str(record.name or "")
            allowed = (name == "stream" or name.startswith((
                "stream.", "modes.", "vision.", "controller.", "arduino.",
                "traffic_sign_detector.", "manager.", "utils.", "main"
            )))
            if not allowed:
                return
            entry = {
                "timestamp": time.time(),
                "level": record.levelname,
                "logger": name[:120],
                "message": _redact_log_message(self.format(record)),
            }
            with _STREAM_LOG_LOCK:
                _STREAM_LOGS.append(entry)
        except Exception:
            self.handleError(record)


if not any(isinstance(handler, _StreamLogBuffer) for handler in logging.getLogger().handlers):
    _log_buffer_handler = _StreamLogBuffer()
    _log_buffer_handler.setLevel(logging.NOTSET)
    _log_buffer_handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger().addHandler(_log_buffer_handler)

VARIABLES = [
    "RL_TOP_ROI", "RL_BOTTOM_ROI", "RL_LEFT_ROI", "RL_RIGHT_ROI",
    "LL_TOP_ROI", "LL_BOTTOM_ROI", "LL_LEFT_ROI", "LL_RIGHT_ROI",
    "CW_TOP_ROI", "CW_BOTTOM_ROI", "CW_LEFT_ROI", "CW_RIGHT_ROI",
    "ST_TOP_ROI", "ST_BOTTOM_ROI", "ST_LEFT_ROI", "ST_RIGHT_ROI",
    "OBJ_TOP_ROI", "OBJ_BOTTOM_ROI", "OBJ_LEFT_ROI", "OBJ_RIGHT_ROI"  
]

ADVANCED_VARS = {
    "LANE_THRESHOLD": 180,
    "CROSSWALK_THRESHOLD": 180,
    "CROSSWALK_SLEEP": 3.0,
    "CROSSWALK_THRESH_SPEND": 8.0,
    "RUN_LVL": "MOVE",
    "WITH_SIGN": True,
    "WITH_APRILTAG": False,
    "READ_SIGN_THRESHOLD": 5,
    "TURN_RIGHT": 2,
    "TURN_LEFT": 3,
    "STRAIGHT": 4,
    "STOP": 5,
    "RECORD_VIDEO": False,
    "DETECT_OBJECT": False,

    "LANE_ROI_MODE": "trapezoid", 
    "CW_TRAPEZOID_MODE": True,
    "ST_TRAPEZOID_MODE": True,    
    "OBJ_TRAPEZOID_MODE": True,
    "RL_TOP_WIDTH_FACTOR": 0.5,
    "LL_TOP_WIDTH_FACTOR": 0.5,
    "CW_TOP_WIDTH_FACTOR": 0.6,
    "ST_TOP_WIDTH_FACTOR": 0.8,
    "OBJ_TOP_WIDTH_FACTOR": 0.8,

    "USE_BEV": True,
    "BEV_SRC_TL_X": 0.35,
    "BEV_SRC_TL_Y": 0.60,
    "BEV_SRC_TR_X": 0.65,
    "BEV_SRC_TR_Y": 0.60,
    "BEV_SRC_BR_X": 1.00,
    "BEV_SRC_BR_Y": 1.00,
    "BEV_SRC_BL_X": 0.00,
    "BEV_SRC_BL_Y": 1.00
}

from .auth_api import StreamAuthMixin, register_auth_routes
from .controls_api import StreamControlsMixin
from .configuration_api import StreamConfigurationMixin
from .runtime_api import StreamRuntimeMixin
from .pages_api import StreamPagesMixin
from .media_api import StreamMediaMixin

class WebStreamer(StreamAuthMixin, StreamControlsMixin, StreamConfigurationMixin, StreamRuntimeMixin, StreamPagesMixin, StreamMediaMixin):
    def __init__(self, config):
        self.config = config
        self.app = Flask(__name__)
        self._initialize_stream_auth(os.path.join(str(BASE_DIR), ".env"))

        self.ui_settings = self.load_ui_settings()

        self._jpeg_cache_lock = threading.Lock()
        self._frame_lock = getattr(config, "stream_frame_lock", None)
        if self._frame_lock is None:
            self._frame_lock = threading.RLock()
            setattr(config, "stream_frame_lock", self._frame_lock)
        self._jpeg_cache_frame_id = None
        self._jpeg_cache = None
        self._jpeg_cache_quality = None
        if not hasattr(config, "STREAM_JPEG_QUALITY"):
            config.STREAM_JPEG_QUALITY = 85
        self._setup_routes()

    def _setup_routes(self):
        from .pages_api import register_page_routes
        from .controls_api import register_control_routes
        from .media_api import register_media_routes
        from .runtime_api import register_runtime_routes
        from .configuration_api import register_configuration_routes

        register_auth_routes(self.app, self)
        register_page_routes(self.app, self)
        register_control_routes(self.app, self)
        register_media_routes(self.app, self)
        register_runtime_routes(self.app, self)
        register_configuration_routes(self.app, self)


def _stream_access_urls(bind_host, port):
    """Return browser URLs for the configured bind address."""
    bind_host = str(bind_host or "0.0.0.0")
    port = int(port)

    def format_host(host):
        return f"[{host}]" if ":" in host and not host.startswith("[") else host

    if bind_host not in {"0.0.0.0", ""}:
        return [f"http://{format_host(bind_host)}:{port}"]

    addresses = {"127.0.0.1"}
    try:
        for info in socket.getaddrinfo(
            socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM
        ):
            address = info[4][0]
            if not address.startswith(("127.", "169.254.")):
                addresses.add(address)
    except OSError:
        logger.debug("Could not enumerate local IPv4 addresses", exc_info=True)

    # A UDP connect selects the outbound interface without sending a packet.
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 80))
        address = probe.getsockname()[0]
        if not address.startswith(("127.", "169.254.")):
            addresses.add(address)
    except OSError:
        logger.debug("Could not determine the active LAN address", exc_info=True)
    finally:
        probe.close()

    return [
        f"http://{address}:{port}"
        for address in sorted(addresses, key=lambda item: (item != "127.0.0.1", item))
    ]


def _make_stream_request_handler(log_requests=False):
    """Build a request handler that can suppress high-volume HTTP access logs.

    Suppression is scoped to this Stream server. Werkzeug errors and application
    exceptions retain their normal logging behavior.
    """
    class StreamRequestHandler(WSGIRequestHandler):
        def log_request(self, code="-", size="-"):
            if log_requests:
                super().log_request(code, size)

    return StreamRequestHandler


def start_stream(config):
    config.stream_start_error = None
    config.stream_shutdown_requested = False
    ready_event = getattr(config, "stream_ready_event", None)
    if ready_event is None:
        ready_event = threading.Event()
        config.stream_ready_event = ready_event
    else:
        ready_event.clear()

    try:
        streamer = WebStreamer(config)
    except Exception as exc:
        config.stream_start_error = f"{type(exc).__name__}: {exc}"
        ready_event.set()
        print(
            f"[Stream] ERROR: could not initialize dashboard: "
            f"{config.stream_start_error}",
            flush=True,
        )
        logger.exception("Failed to initialize Stream dashboard")
        return

    bind_host = str(getattr(config, "STREAM_HOST", "0.0.0.0"))
    requested_port = int(getattr(config, "STREAM_PORT", 5000))
    try:
        server = make_server(
            bind_host,
            requested_port,
            streamer.app,
            threaded=True,
            request_handler=_make_stream_request_handler(
                bool(getattr(config, "STREAM_REQUEST_LOGS", False))
            ),
        )
    except Exception as exc:
        config.stream_start_error = f"{type(exc).__name__}: {exc}"
        ready_event.set()
        # The web dashboard is an optional diagnostics/control surface.
        # A bind failure must not signal a robot shutdown; report it clearly
        # while leaving the robot's main loop under its own safety controls.
        print(
            f"[Stream] ERROR: could not bind to {bind_host}:{requested_port}: "
            f"{config.stream_start_error}",
            flush=True,
        )
        logger.exception("Failed to start stream server")
        return

    config.streamer = streamer
    config.stream_server = server
    ready_event.set()

    server_address = getattr(server, "server_address", (bind_host, requested_port))
    actual_port = int(getattr(server, "server_port", server_address[1]))
    urls = _stream_access_urls(bind_host, actual_port)
    print(f"[Stream] Listening on {bind_host}:{actual_port}", flush=True)

    wildcard_bind = bind_host in {"0.0.0.0", ""}
    controls_enabled = bool(
        getattr(config, "STREAM_ALLOW_CONTROL", False)
    )
    if streamer.auth_enabled:
        logger.info("Stream dashboard authentication is enabled.")
        if wildcard_bind:
            logger.warning(
                "Stream login uses plain HTTP; credentials and session cookies are not "
                "encrypted in transit. Use only on a trusted network or place Stream "
                "behind an HTTPS reverse proxy."
            )
    elif wildcard_bind and controls_enabled:
        logger.warning(
            "Dashboard controls are enabled on all network interfaces without "
            "authentication. Use only on a trusted LAN; pass --stream-read-only "
            "or bind to 127.0.0.1 on untrusted networks."
        )
    elif wildcard_bind:
        logger.warning(
            "Stream telemetry is exposed on all network interfaces without "
            "authentication. Use only on a trusted LAN or bind to 127.0.0.1."
        )

    for url in urls:
        host = urlsplit(url).hostname or ""
        label = "Dashboard"
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None

        if host in {"localhost", "::1"} or (
            address is not None and address.is_loopback
        ):
            label = "Dashboard (local)"
        elif (
            isinstance(address, ipaddress.IPv4Address)
            and address.is_private
            and not address.is_link_local
        ):
            label = "Dashboard (LAN)"

        print(f"[Stream] {label}: {url}", flush=True)

    if not wildcard_bind:
        print(
            "[Stream] Local/custom binding only. Use --stream-host 0.0.0.0 "
            "to allow access from other devices on your LAN.",
            flush=True,
        )
    logger.info("Stream dashboard available at %s", ", ".join(urls))

    try:
        server.serve_forever()
    finally:
        server.server_close()
        if getattr(config, "stream_server", None) is server:
            config.stream_server = None
        if getattr(config, "streamer", None) is streamer:
            config.streamer = None


def publish_debug_frame(config, frame):
    """Publish only the newest frame, preserving the legacy list API."""
    if frame is None:
        return
    lock = getattr(config, "stream_frame_lock", None)
    if lock is None:
        lock = threading.RLock()
        setattr(config, "stream_frame_lock", lock)
    with lock:
        frames = getattr(config, "debug_frames_list", None)
        if frames is None:
            frames = []
            setattr(config, "debug_frames_list", frames)
        frames[:] = [frame.copy()]
        config.stream_frame_seq = getattr(config, "stream_frame_seq", 0) + 1
        timestamps = getattr(config, "stream_frame_timestamps", None)
        if timestamps is None:
            timestamps = deque(maxlen=120)
            setattr(config, "stream_frame_timestamps", timestamps)
        timestamps.append(time.monotonic())


def stop_stream(config):
    server = getattr(config, "stream_server", None)
    if server is None:
        return False
    try:
        server.shutdown()
        return True
    except Exception:
        logger.exception("Failed to stop stream server")
        return False


ENCODER_MAP_TEMPLATE = """<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'><title>Estimated Odometry</title>
<style>body{font:16px sans-serif;background:#081426;color:#e6eef6;margin:2rem}canvas{background:#030914;border:1px solid #334155;width:min(90vw,800px);height:500px}.warn{color:#fbbf24}a{color:#67e8f9}</style></head><body>
<h1>Estimated Odometry</h1><p>The map integrates encoder pulses with the final servo command reported by Arduino (including the PID controller output when PID mode is enabled). Road-wheel angle is estimated from the active mode's servo limits and measured angle calibration; it is not physical wheel-angle feedback. Slip, backlash, missed counts and drivetrain geometry can cause drift.</p>
<p id='state'>Waiting for telemetry...</p><canvas id='map' width='800' height='500'></canvas><pre id='details'></pre><button id='reset'>Reset displayed origin</button> <a href='/'>Dashboard</a>
<script>const c=document.getElementById('map'),x=c.getContext('2d');function draw(d){document.getElementById('state').textContent=d.valid?'Continuous estimate':'ODOMETRY GAP: '+d.reason;document.getElementById('state').className=d.valid?'':'warn';document.getElementById('details').textContent=JSON.stringify({signed_pulses:d.signed_pulses,travel_cm:d.travel_cm,position_cm:[d.x_cm,d.y_cm],heading_rad:d.heading_rad,servo_command:d.servo_command,steering_angle_source:d.steering_angle_source,road_wheel_angle_deg:d.road_wheel_angle_deg,servo_center:d.servo_center,pulse_distance_cm:d.pulse_distance_cm,steering_calibration:[d.road_wheel_angle_at_servo_min_deg,d.road_wheel_angle_at_servo_max_deg],sample_age_s:d.sample_age_s,trajectory_available:d.trajectory_available,reason:d.reason},null,2);x.clearRect(0,0,c.width,c.height);const h=d.history||[],valid=h.filter(p=>p.valid&&p.x_cm!==null);if(!valid.length)return;const xs=valid.map(p=>p.x_cm),ys=valid.map(p=>p.y_cm),scale=Math.min(400/(Math.max(...xs)-Math.min(...xs)||1),250/(Math.max(...ys)-Math.min(...ys)||1));let prev=null;for(const p of h){if(!p.valid||p.gap||p.x_cm===null){prev=null;continue}const q={x:c.width/2+p.x_cm*scale,y:c.height/2-p.y_cm*scale};if(prev){x.beginPath();x.moveTo(prev.x,prev.y);x.lineTo(q.x,q.y);x.strokeStyle='#22d3ee';x.lineWidth=2;x.stroke()}x.fillStyle='#f8fafc';x.fillRect(q.x-2,q.y-2,4,4);prev=q}}async function poll(){try{const r=await fetch('/api/encoder-map',{cache:'no-store'});if(r.ok)draw(await r.json())}catch(e){}setTimeout(poll,250)}poll();document.getElementById('reset').onclick=async()=>{await fetch('/api/encoder-map/reset-origin',{method:'POST'});};</script></body></html>"""
