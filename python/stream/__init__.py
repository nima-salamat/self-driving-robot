import logging
import cv2
import json
import os
import socket
import ipaddress
from urllib.parse import urlsplit
import threading
import time
from collections import deque
from flask import Flask, Response, request, render_template_string, jsonify
from werkzeug.serving import make_server
from .template import HTML_TEMPLATE
from .capabilities import mode_capabilities, marker_mode, set_marker_mode
from base_config import BASE_DIR

logger = logging.getLogger(__name__)

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


class WebStreamer:
    def __init__(self, config):
        self.config = config
        self.app = Flask(__name__)
        
        self.ui_settings = self.load_ui_settings()
        
        self._jpeg_cache_lock = threading.Lock()
        self._frame_lock = getattr(config, "stream_frame_lock", None)
        if self._frame_lock is None:
            self._frame_lock = threading.RLock()
            setattr(config, "stream_frame_lock", self._frame_lock)
        self._jpeg_cache_frame_id = None
        self._jpeg_cache = None
        self._setup_routes()

    def get_base_var(self, var):
        default = 1.0 if ("BOTTOM" in var or "RIGHT" in var) else 0.0
        return float(getattr(self.config, var, default))

    def get_all_advanced(self):
        res = {}
        for k, default_v in ADVANCED_VARS.items():
            val = getattr(self.config, k, default_v)
            if type(default_v) == bool: res[k] = bool(val)
            elif type(default_v) == int: res[k] = int(val)
            elif type(default_v) == float: res[k] = float(val)
            else: res[k] = str(val)
        return res

    def ui_filename(self):
        mode = getattr(self.config, "MODE", "mode")
        return os.path.join(str(BASE_DIR), f"{mode}_ui.json")

    def load_ui_settings(self):
        fname = self.ui_filename()
        default_ui = {
            "colors": {"RL":"#ff7b7b", "LL":"#7bffb8", "CW":"#ffd27b", "BEV":"#d946ef", "ST":"#bf7bff", "OBJ":"#ff5757"}, 
            "visible": {"RL":True, "LL":True, "CW":True, "BEV":True, "ST":True, "OBJ":True} 
        }
        if os.path.exists(fname):
            try:
                with open(fname, "r") as f:
                    data = json.load(f)
                    ui = {
                        "colors": data.get("colors", default_ui["colors"]),
                        "visible": data.get("visible", default_ui["visible"])
                    }
                    for key in default_ui["colors"]:
                        if key not in ui["colors"]: ui["colors"][key] = default_ui["colors"][key]
                    for key in default_ui["visible"]:
                        if key not in ui["visible"]: ui["visible"][key] = default_ui["visible"][key]
                    return ui
            except Exception:
                logger.exception("Failed load UI settings")
        return default_ui

    def save_ui_settings(self):
        fname = self.ui_filename()
        try:
            with open(fname, "w") as f:
                json.dump(self.ui_settings, f, indent=2)
        except Exception:
            logger.exception("Failed writing UI settings")

    def config_filename(self):
        mode = getattr(self.config, "MODE", "mode")
        return os.path.join(str(BASE_DIR), f"{mode}.json")

    def save_conf_to_json(self):
        filename = self.config_filename()
        data = {var: self.get_base_var(var) for var in VARIABLES}
        data.update(self.get_all_advanced())
        try:
            with open(filename, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            logger.exception("Failed writing config JSON")


    def _setup_routes(self):
        self.app.add_url_rule('/', 'index', self.index)
        self.app.add_url_rule('/update_conf', 'update_conf', self.update_conf, methods=['POST'])
        self.app.add_url_rule('/get_values', 'get_values', self.get_values)
        self.app.add_url_rule('/get_advanced', 'get_advanced', self.get_advanced)
        self.app.add_url_rule('/set_advanced', 'set_advanced', self.set_advanced, methods=['POST'])
        self.app.add_url_rule('/get_ui', 'get_ui', self.get_ui)
        self.app.add_url_rule('/set_ui', 'set_ui', self.set_ui, methods=['POST'])
        self.app.add_url_rule('/video_feed_frame', 'video_feed_frame', self.video_feed_frame)
        self.app.add_url_rule('/video_feed', 'video_feed', self.video_feed)
        self.app.add_url_rule('/api/mode', 'mode', self.mode)
        self.app.add_url_rule('/api/arduino-output', 'arduino_output', self.arduino_output)
        self.app.add_url_rule('/api/health', 'health', self.health)
        self.app.add_url_rule('/encoder-map', 'encoder_map_page', self.encoder_map_page)
        self.app.add_url_rule('/api/encoder-map', 'encoder_map_api', self.encoder_map_api)
        self.app.add_url_rule('/api/encoder-map/reset-origin', 'encoder_map_reset_origin', self.encoder_map_reset_origin, methods=['POST'])
        self.app.add_url_rule('/take_picture', 'take_picture', self.take_picture, methods=['POST'])
        self.app.add_url_rule('/toggle_record', 'toggle_record', self.toggle_record, methods=['POST'])
        self.app.add_url_rule('/freeze_frame', 'freeze_frame', self.freeze_frame, methods=['POST'])
        self.app.add_url_rule('/unfreeze_frame', 'unfreeze_frame', self.unfreeze_frame, methods=['POST'])

    def index(self):
        values = {var: self.get_base_var(var) for var in VARIABLES}
        advanced_current = self.get_all_advanced()
        response = Response(
            render_template_string(
                HTML_TEMPLATE,
                variables=VARIABLES,
                values=values,
                ui=self.ui_settings,
                advanced=advanced_current,
                mode=getattr(self.config, "MODE", "mode"),
                stream_control=bool(
                    getattr(self.config, "STREAM_ALLOW_CONTROL", False)
                ),
                capabilities=mode_capabilities(self.config),
                encoder_map_enabled=bool(getattr(self.config, "ENCODER_MAP_ENABLED", False)),
            ),
            mimetype="text/html",
        )
        # The dashboard contains inline JavaScript. Do not let a browser reuse
        # an old broken script after the local robot runtime has been updated.
        response.headers.update({
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        })
        return response

    def encoder_map_page(self):
        if not bool(getattr(self.config, "ENCODER_MAP_ENABLED", False)):
            return Response("Not Found", status=404)
        return Response(ENCODER_MAP_TEMPLATE, mimetype="text/html")

    def encoder_map_api(self):
        if not bool(getattr(self.config, "ENCODER_MAP_ENABLED", False)):
            return jsonify(error="encoder map is disabled"), 404
        odometry = getattr(self.config, "encoder_odometry", None)
        if odometry is None:
            return jsonify(error="encoder odometry is not initialized"), 503
        return jsonify(odometry.snapshot())

    def encoder_map_reset_origin(self):
        if not bool(getattr(self.config, "ENCODER_MAP_ENABLED", False)):
            return jsonify(error="encoder map is disabled"), 404
        if not self._control_allowed():
            return self._control_denied()
        odometry = getattr(self.config, "encoder_odometry", None)
        if odometry is None:
            return jsonify(error="encoder odometry is not initialized"), 503
        odometry.reset_display_origin()
        return jsonify(success=True, message="display origin reset; hardware unchanged")

    def _feature_diagnostics(self):
        payload = {}
        if getattr(self.config, "CONFIDENCE_AWARE_ENABLED", False):
            payload["perception_confidence"] = getattr(self.config, "perception_confidence", None)
            payload["speed_decision"] = getattr(self.config, "speed_decision", None)
        if getattr(self.config, "ADAPTIVE_OBSTACLE_AVOIDANCE_ENABLED", False):
            payload["obstacle_diagnostics"] = getattr(self.config, "obstacle_diagnostics", None)
        return payload

    def _control_allowed(self):
        return bool(getattr(self.config, "STREAM_ALLOW_CONTROL", False))

    def _control_denied(self):
        return jsonify(success=False, message="stream control is disabled"), 403

    def update_conf(self):
        if not self._control_allowed():
            return self._control_denied()
        try:
            data = request.get_json(silent=True)
            if data is None:
                data = request.form.to_dict()
            if not isinstance(data, dict):
                return jsonify(
                    success=False,
                    message="request body must be an object",
                ), 400
            updated = {}
            for var in VARIABLES:
                if var not in data:
                    continue
                try:
                    val = float(data[var])
                except (TypeError, ValueError):
                    return jsonify(
                        success=False,
                        message=f"{var} must be numeric",
                    ), 400
                if not 0.0 <= val <= 1.0:
                    return jsonify(
                        success=False,
                        message=f"{var} must be between 0 and 1",
                    ), 400
                setattr(self.config, var, val)
                updated[var] = val
            if updated:
                self.save_conf_to_json()
            return jsonify(
                success=True,
                values={var: self.get_base_var(var) for var in VARIABLES},
            )
        except Exception:
            logger.exception("Failed to update stream configuration")
            return jsonify(
                success=False,
                message="Failed to update stream configuration",
            ), 500

    def get_values(self):
        return jsonify(values={var: self.get_base_var(var) for var in VARIABLES})

    def get_advanced(self):
        return jsonify(advanced=self.get_all_advanced())

    def set_advanced(self):
        if not self._control_allowed():
            return self._control_denied()
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(
                success=False,
                message="request body must be a JSON object",
            ), 400
        capabilities = mode_capabilities(self.config)
        unsupported = []
        if "USE_BEV" in data and not capabilities.get("supports_bev", False):
            unsupported.append("USE_BEV")
        crosswalk_keys = {
            "CROSSWALK_THRESHOLD",
            "CROSSWALK_SLEEP",
            "CROSSWALK_THRESH_SPEND",
            "CW_TRAPEZOID_MODE",
            "CW_TOP_WIDTH_FACTOR",
        }
        if (
            any(key in data for key in crosswalk_keys)
            and not capabilities.get("supports_crosswalk", False)
        ):
            unsupported.extend(
                sorted(key for key in crosswalk_keys if key in data)
            )
        lane_shape_keys = {
            "LANE_ROI_MODE",
            "RL_TOP_WIDTH_FACTOR",
            "LL_TOP_WIDTH_FACTOR",
        }
        if (
            any(key in data for key in lane_shape_keys)
            and not capabilities.get("supports_lane_roi", False)
        ):
            unsupported.extend(
                sorted(key for key in lane_shape_keys if key in data)
            )
        if unsupported:
            return jsonify(
                success=False,
                message="unsupported controls for active mode",
                unsupported=unsupported,
            ), 409
        try:
            for k, default_v in ADVANCED_VARS.items():
                if k in data:
                    val = data[k]
                    if k in ("LANE_THRESHOLD", "CROSSWALK_THRESHOLD"): 
                        val = max(0, min(255, int(val)))
                    elif k.startswith("BEV_SRC_"): 
                        val = max(-5.0, min(5.0, float(val)))
                    
                    expected_type = type(default_v)
                    if expected_type == bool:
                        if not isinstance(val, bool):
                            raise ValueError(f"{k} must be boolean")
                    elif expected_type == int: val = int(val)
                    elif expected_type == float: val = float(val)
                    else: val = str(val)
                    
                    setattr(self.config, k, val)

            if "RUN_LVL" in data: 
                setattr(self.config, "RUN_LVL", data["RUN_LVL"] if data["RUN_LVL"] in ("MOVE","STOP") else "MOVE")
                
            if "WITH_SIGN" in data or "WITH_APRILTAG" in data:
                sign = data.get(
                    "WITH_SIGN",
                    getattr(self.config, "WITH_SIGN", False),
                )
                tag = data.get(
                    "WITH_APRILTAG",
                    getattr(self.config, "WITH_APRILTAG", False),
                )
                if not isinstance(sign, bool) or not isinstance(tag, bool):
                    raise ValueError(
                        "WITH_SIGN and WITH_APRILTAG must be boolean"
                    )
                if sign and tag:
                    raise ValueError(
                        "WITH_SIGN and WITH_APRILTAG cannot both be true"
                    )
                set_marker_mode(
                    self.config,
                    "sign" if sign else "apriltag" if tag else "none",
                )
            
        except Exception as e:
            logger.exception("Invalid advanced payload")
            return jsonify(success=False), 400
            
        self.save_conf_to_json()
        return jsonify(success=True, advanced=self.get_all_advanced())

    def get_ui(self): 
        return jsonify(ui=self.ui_settings)

    def set_ui(self):
        if not self._control_allowed():
            return self._control_denied()
        data = request.get_json() or {}
        if "colors" in data: 
            self.ui_settings["colors"].update({k:v for k,v in data["colors"].items() if k in self.ui_settings["colors"]})
        if "visible" in data: 
            self.ui_settings["visible"].update({k:bool(v) for k,v in data["visible"].items() if k in self.ui_settings["visible"]})
        self.save_ui_settings()
        return jsonify(success=True, ui=self.ui_settings)

    def video_feed_frame(self):
        with self._frame_lock:
            frozen = getattr(self.config, "frozen_debug_frame", None)
            if frozen is not None:
                frame = frozen.copy()
            else:
                frames_list = getattr(self.config, "debug_frames_list", [])
                frame = (
                    (
                        frames_list[-1].copy()
                        if hasattr(frames_list[-1], "copy")
                        else frames_list[-1]
                    )
                    if frames_list and frames_list[-1] is not None
                    else None
                )
        
        cache_headers = {
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        }

        if frame is None:
            response = Response("", status=204)
            response.headers.update(cache_headers)
            return response

        frame_id = getattr(self.config, "stream_frame_seq", id(frame))
        with self._jpeg_cache_lock:
            if frame_id != self._jpeg_cache_frame_id or self._jpeg_cache is None:
                try:
                    ret, buffer = cv2.imencode(".jpg", frame)
                    if not ret:
                        response = Response("", status=204)
                        response.headers.update(cache_headers)
                        return response
                    payload = buffer.tobytes()
                except Exception:
                    logger.exception("Failed to encode stream frame")
                    response = Response("", status=503)
                    response.headers.update(cache_headers)
                    return response
                self._jpeg_cache = payload
                self._jpeg_cache_frame_id = frame_id
            payload = self._jpeg_cache

        response = Response(payload, mimetype="image/jpeg")
        response.headers.update(cache_headers)
        response.headers["X-Stream-Frame-Sequence"] = str(frame_id)
        for key, value in self._feature_diagnostics().items():
            if value is not None:
                response.headers["X-Robot-" + key.replace("_", "-")] = json.dumps(value, separators=(",", ":"))
        return response

    def mode(self):
        mode = getattr(self.config, "MODE", "mode")
        capabilities = mode_capabilities(self.config)
        return jsonify(
            mode=mode,
            config_file=os.path.basename(self.config_filename()),
            features={
                "lane_detector": capabilities.get("lane_detector", "default"),
                "ml_lane_detector": capabilities.get("ml_lane_detector", False),
                "bev": bool(
                    capabilities.get("supports_bev", False)
                    and capabilities.get("bev", False)
                ),
                "stream": capabilities.get("stream_enabled", False),
                "encoder_map": capabilities.get("encoder_map_enabled", False),
                "confidence_aware": capabilities.get("confidence_aware_enabled", False),
                "adaptive_obstacle_avoidance": capabilities.get("adaptive_obstacle_avoidance_enabled", False),
                "recording": capabilities.get("recording_enabled", False),
                "sign": capabilities.get("sign_enabled", False),
                "apriltag": capabilities.get("apriltag_enabled", False),
                "object_detection": capabilities.get(
                    "object_detection_enabled", False
                ),
                "crosswalk": capabilities.get("supports_crosswalk", False),
                "marker_mode": marker_mode(self.config),
            },
            capabilities=capabilities,
            controlling_settings={
                "lane_detector": (
                    "CITY_LANE_DETECTOR"
                    if mode == "city"
                    else "USE_ML_LANE_DETECTOR"
                ),
                "marker_mode": ["WITH_SIGN", "WITH_APRILTAG"],
                "bev": "USE_BEV",
            },
        )

    def video_feed(self):
        def generate():
            last_frame_id = None
            while True:
                with self._frame_lock:
                    frozen = getattr(self.config, "frozen_debug_frame", None)
                    if frozen is not None:
                        frame = frozen.copy()
                        frame_id = "frozen"
                    else:
                        frames_list = getattr(
                            self.config,
                            "debug_frames_list",
                            [],
                        )
                        frame = (
                            (
                                frames_list[-1].copy()
                                if hasattr(frames_list[-1], "copy")
                                else frames_list[-1]
                            )
                            if frames_list and frames_list[-1] is not None
                            else None
                        )
                        frame_id = getattr(
                            self.config,
                            "stream_frame_seq",
                            id(frame) if frame is not None else None,
                        )

                if frame is None:
                    time.sleep(0.05)
                    continue

                try:
                    ret, buffer = cv2.imencode(
                        ".jpg",
                        frame,
                        [cv2.IMWRITE_JPEG_QUALITY, 85],
                    )
                except Exception:
                    logger.exception("Failed to encode MJPEG stream frame")
                    time.sleep(0.05)
                    continue

                if not ret:
                    time.sleep(0.05)
                    continue

                last_frame_id = frame_id
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + buffer.tobytes()
                    + b"\r\n"
                )

        return Response(
            generate(),
            mimetype="multipart/x-mixed-replace; boundary=frame",
        )

    def health(self):
        monitor = getattr(self.config, "health_monitor", None)
        metrics = getattr(self.config, "runtime_metrics", None)
        controller = getattr(self.config, "robot_controller", None)

        payload = {
            "health": (
                monitor.snapshot_runtime(self.config)
                if monitor is not None
                else {"state": "UNKNOWN", "lifecycle": "UNKNOWN", "faults": {}}
            ),
            "metrics": metrics.snapshot() if metrics is not None else {},
        }
        if getattr(self.config, "CONFIDENCE_AWARE_ENABLED", False):
            payload["perception_confidence"] = getattr(self.config, "perception_confidence", None)
            payload["speed_decision"] = getattr(self.config, "speed_decision", None)
        if getattr(self.config, "ADAPTIVE_OBSTACLE_AVOIDANCE_ENABLED", False):
            payload["obstacle_diagnostics"] = getattr(self.config, "obstacle_diagnostics", None)

        sign_detector = getattr(self.config, "sign_detector", None)
        output_manager = getattr(self.config, "output_manager", None)
        if sign_detector is not None:
            payload["sign_detector"] = sign_detector.status()
        if output_manager is not None:
            payload["recording"] = output_manager.stats()

        if controller is not None:
            command = controller.last_command
            payload["control"] = {
                "angle": controller.last_angle,
                "speed": controller.current_speed,
                "command": command,
                "command_age_ms": (
                    max(0.0, (time.monotonic() - command["transmitted_at"]) * 1000.0)
                    if command and command.get("transmitted_at") is not None
                    else None
                ),
            }

        payload["stream"] = {
            "frame_seq": getattr(self.config, "stream_frame_seq", 0),
            "buffered_frames": len(
                getattr(self.config, "debug_frames_list", [])
            ),
        }
        camera = getattr(self.config, "camera", None)
        if camera is not None:
            payload["camera"] = {
                "requested_fps": getattr(
                    camera, "requested_frame_rate", None
                ),
                "measured_fps": getattr(
                    camera, "measured_frame_rate", None
                ),
                "hardware_limits": (
                    camera.get_frame_rate_limits()
                    if hasattr(camera, "get_frame_rate_limits")
                    else None
                ),
            }
        return jsonify(payload)
    def arduino_output(self):
        connection = getattr(self.config, "arduino_connection", None)
        if connection is None:
            return jsonify(enabled=False, connected=False, state="DISCONNECTED", lines=[])
        status = connection.telemetry_status(limit=50)
        status["enabled"] = bool(getattr(self.config, "READ_ARDUINO_OUTPUT", False))
        return jsonify(status)

    def take_picture(self):
        if not self._control_allowed():
            return self._control_denied()
        setattr(self.config, "TAKE_PICTURE", True)
        return jsonify(success=True)

    def toggle_record(self):
        if not self._control_allowed():
            return self._control_denied()
        current = getattr(self.config, "RECORD_VIDEO", False)
        new_val = not current
        setattr(self.config, "RECORD_VIDEO", new_val)
        self.save_conf_to_json()
        return jsonify(success=True, recording=new_val)

    def freeze_frame(self):
        if not self._control_allowed():
            return self._control_denied()
        with self._frame_lock:
            frames_list = getattr(self.config, "debug_frames_list", [])
            if frames_list:
                setattr(
                    self.config,
                    "frozen_debug_frame",
                    frames_list[-1].copy(),
                )
                return jsonify(success=True)
        return jsonify(success=False, message="No frame available")

    def unfreeze_frame(self):
        if not self._control_allowed():
            return self._control_denied()
        if hasattr(self.config, "frozen_debug_frame"):
            delattr(self.config, "frozen_debug_frame")
        return jsonify(success=True)

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


def start_stream(config):
    config.stream_start_error = None
    ready_event = getattr(config, "stream_ready_event", None)
    if ready_event is None:
        ready_event = threading.Event()
        config.stream_ready_event = ready_event
    else:
        ready_event.clear()

    streamer = WebStreamer(config)
    bind_host = str(getattr(config, "STREAM_HOST", "0.0.0.0"))
    requested_port = int(getattr(config, "STREAM_PORT", 5000))
    try:
        server = make_server(
            bind_host,
            requested_port,
            streamer.app,
            threaded=True,
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
    if wildcard_bind and controls_enabled:
        logger.warning(
            "Dashboard controls are enabled on all network interfaces without "
            "authentication. Use only on a trusted LAN; pass --stream-read-only "
            "or bind to 127.0.0.1 on untrusted networks."
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
<h1>Estimated Odometry</h1><p>Encoder pulses and calibrated steering integration are estimates, not ground-truth localization. Slip, backlash, missed counts and drivetrain geometry cause drift.</p>
<p id='state'>Waiting for telemetry...</p><canvas id='map' width='800' height='500'></canvas><pre id='details'></pre><button id='reset'>Reset displayed origin</button> <a href='/'>Dashboard</a>
<script>const c=document.getElementById('map'),x=c.getContext('2d');function draw(d){document.getElementById('state').textContent=d.valid?'Continuous estimate':'ODOMETRY GAP: '+d.reason;document.getElementById('state').className=d.valid?'':'warn';document.getElementById('details').textContent=JSON.stringify({signed_pulses:d.signed_pulses,travel_cm:d.travel_cm,position_cm:[d.x_cm,d.y_cm],heading_rad:d.heading_rad,servo_command:d.servo_command,servo_center:d.servo_center,pulse_distance_cm:d.pulse_distance_cm,steering_calibration:[d.road_wheel_angle_at_servo_min_deg,d.road_wheel_angle_at_servo_max_deg],sample_age_s:d.sample_age_s,trajectory_available:d.trajectory_available,reason:d.reason},null,2);x.clearRect(0,0,c.width,c.height);const h=d.history||[],valid=h.filter(p=>p.valid&&p.x_cm!==null);if(!valid.length)return;const xs=valid.map(p=>p.x_cm),ys=valid.map(p=>p.y_cm),scale=Math.min(400/(Math.max(...xs)-Math.min(...xs)||1),250/(Math.max(...ys)-Math.min(...ys)||1));let prev=null;for(const p of h){if(!p.valid||p.gap||p.x_cm===null){prev=null;continue}const q={x:c.width/2+p.x_cm*scale,y:c.height/2-p.y_cm*scale};if(prev){x.beginPath();x.moveTo(prev.x,prev.y);x.lineTo(q.x,q.y);x.strokeStyle='#22d3ee';x.lineWidth=2;x.stroke()}x.fillStyle='#f8fafc';x.fillRect(q.x-2,q.y-2,4,4);prev=q}}async function poll(){try{const r=await fetch('/api/encoder-map',{cache:'no-store'});if(r.ok)draw(await r.json())}catch(e){}setTimeout(poll,250)}poll();document.getElementById('reset').onclick=async()=>{await fetch('/api/encoder-map/reset-origin',{method:'POST'});};</script></body></html>"""
