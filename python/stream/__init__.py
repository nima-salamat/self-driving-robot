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
from flask import Flask, Response, request, render_template_string, jsonify
from werkzeug.serving import WSGIRequestHandler, make_server
from .template import HTML_TEMPLATE
from .capabilities import mode_capabilities, marker_mode, set_marker_mode
from base_config import BASE_DIR

logger = logging.getLogger(__name__)

CONFIG_HISTORY_LIMIT = 50
STREAM_LOG_LIMIT = 500
_STREAM_LOG_LOCK = threading.RLock()
_STREAM_LOGS = deque(maxlen=STREAM_LOG_LIMIT)
_SECRET_PATTERNS = (
    re.compile(r"(?i)(token|password|passwd|secret|api[_-]?key|authorization)(\s*[:=]\s*)([^\s,;]+)"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/-]+=*"),
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
            "visible": {"RL":True, "LL":True, "CW":True, "BEV":True, "ST":True, "OBJ":True},
            "opacity": {"RL":1.0, "LL":1.0, "CW":1.0, "BEV":0.8, "ST":1.0, "OBJ":1.0}
        }
        if os.path.exists(fname):
            try:
                with open(fname, "r") as f:
                    data = json.load(f)
                    ui = {
                        "colors": data.get("colors", default_ui["colors"]),
                        "visible": data.get("visible", default_ui["visible"]),
                        "opacity": data.get("opacity", default_ui["opacity"])
                    }
                    for key in default_ui["colors"]:
                        if key not in ui["colors"]: ui["colors"][key] = default_ui["colors"][key]
                    for key in default_ui["visible"]:
                        if key not in ui["visible"]: ui["visible"][key] = default_ui["visible"][key]
                        if key not in ui["opacity"]: ui["opacity"][key] = default_ui["opacity"][key]
                    return ui
            except Exception:
                logger.exception("Failed load UI settings")
        return default_ui

    def save_ui_settings(self):
        fname = self.ui_filename()
        try:
            os.makedirs(os.path.dirname(fname), exist_ok=True)
            with open(fname, "w", encoding="utf-8") as f:
                json.dump(self.ui_settings, f, indent=2, allow_nan=False)
        except Exception:
            logger.exception("Failed writing UI settings")

    def config_filename(self):
        mode = getattr(self.config, "MODE", "mode")
        return os.path.join(str(BASE_DIR), f"{mode}.json")

    def save_conf_to_json(self):
        filename = self.config_filename()
        data = {var: self.get_base_var(var) for var in VARIABLES}
        data.update(self.get_all_advanced())
        target_rate = getattr(self.config, "processing_rate_controller", None)
        if target_rate is not None:
            data["TARGET_PROCESSING_FPS"] = float(target_rate.target_fps)
        try:
            with open(filename, "w") as f:
                json.dump(data, f, indent=2, allow_nan=False)
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
        self.app.add_url_rule('/api/config/full', 'full_config', self.full_config, methods=['GET', 'POST'])
        self.app.add_url_rule('/api/config/history', 'config_history', self.config_history, methods=['GET', 'POST'])
        self.app.add_url_rule('/api/config/presets', 'config_presets', self.config_presets, methods=['GET', 'POST'])
        self.app.add_url_rule('/api/workspace', 'workspace_api', self.workspace_api, methods=['GET', 'POST'])
        self.app.add_url_rule('/api/logs', 'server_logs', self.server_logs)
        self.app.add_url_rule('/api/traffic-lights', 'traffic_lights_api', self.traffic_lights_api)
        self.app.add_url_rule('/api/race', 'race_status_api', self.race_status_api)
        self.app.add_url_rule('/api/camera/settings', 'camera_settings_api', self.camera_settings_api, methods=['GET', 'POST'])
        self.app.add_url_rule('/api/processing-rate', 'processing_rate_api', self.processing_rate_api, methods=['GET', 'POST'])
        self.app.add_url_rule('/api/safety', 'safety_api', self.safety_api, methods=['GET', 'POST'])
        self.app.add_url_rule('/api/features', 'features_api', self.features_api, methods=['GET', 'POST'])
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
            before = self._full_config_snapshot()
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
                self._record_config_history("before ROI update", before)
                self._record_config_history("ROI settings updated")
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
        before = self._full_config_snapshot()
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
        self._record_config_history("before advanced settings update", before)
        self._record_config_history("advanced settings updated")
        return jsonify(success=True, advanced=self.get_all_advanced())

    def get_ui(self): 
        return jsonify(ui=self.ui_settings)

    def set_ui(self):
        if not self._control_allowed():
            return self._control_denied()
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(success=False, message="request body must be a JSON object"), 400
        for group in ("colors", "visible", "opacity"):
            if group in data and not isinstance(data[group], dict):
                return jsonify(success=False, message=f"{group} must be a JSON object"), 400
        before = self._full_config_snapshot()
        try:
            for key, value in data.get("colors", {}).items():
                if key not in self.ui_settings["colors"] or not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                    raise ValueError("colors must be six-digit hex colors for known layers")
            for key, value in data.get("visible", {}).items():
                if key not in self.ui_settings["visible"] or not isinstance(value, bool):
                    raise ValueError("visible must contain boolean values for known layers")
            for key, value in data.get("opacity", {}).items():
                if key not in self.ui_settings["visible"] or isinstance(value, bool):
                    raise ValueError("opacity must contain numeric values for known layers")
                number = float(value)
                if not math.isfinite(number) or not 0 <= number <= 1:
                    raise ValueError("opacity must be between 0 and 1")
            self.ui_settings["colors"].update({k:v.lower() for k,v in data.get("colors", {}).items()})
            self.ui_settings["visible"].update(data.get("visible", {}))
            self.ui_settings.setdefault("opacity", {}).update({k:float(v) for k,v in data.get("opacity", {}).items()})
            self.save_ui_settings()
            self._record_config_history("before layer update", before)
            self._record_config_history("layer visibility/color/opacity update")
            return jsonify(success=True, ui=self.ui_settings)
        except (TypeError, ValueError) as exc:
            return jsonify(success=False, message=str(exc)), 400

    def _mode_slug(self):
        raw = str(getattr(self.config, "MODE", "mode")).lower()
        slug = "".join(ch for ch in raw if ch.isalnum() or ch in "-_")
        return slug[:32] or "mode"

    def _state_filename(self, suffix):
        return os.path.join(str(BASE_DIR), f"{self._mode_slug()}_{suffix}.json")

    @staticmethod
    def _write_json_atomic(filename, data):
        directory = os.path.dirname(filename) or "."
        os.makedirs(directory, exist_ok=True)
        temporary = filename + ".tmp"
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False, allow_nan=False)
        os.replace(temporary, filename)

    @staticmethod
    def _read_json_file(filename, default):
        try:
            with open(filename, "r", encoding="utf-8") as handle:
                value = json.load(handle)
            return value if isinstance(value, dict) else default
        except FileNotFoundError:
            return default
        except (OSError, ValueError, TypeError):
            logger.exception("Unable to read dashboard state file")
            return default

    def _camera_settings_snapshot(self, camera):
        if camera is None:
            return {"available": False, "reason": "camera is not initialized"}
        if not bool(getattr(camera, "pi_mode", False)):
            return {"available": False, "supported": False, "reason": "runtime tuning currently supports Picamera2 only",
                    "requested_fps": getattr(camera, "requested_frame_rate", None),
                    "measured_fps": getattr(camera, "measured_frame_rate", None)}
        picam = getattr(camera, "picam", None)
        controls = getattr(picam, "camera_controls", {}) if picam is not None else {}
        saved = getattr(camera, "_dashboard_image_controls", {"ExposureTime": 10000, "AnalogueGain": 6.0, "AeEnable": False, "AwbEnable": False})
        allowed_controls = {"ExposureTime", "AnalogueGain", "AeEnable", "AwbEnable"}
        current = {key: value for key, value in saved.items() if key in controls and key in allowed_controls}
        return {"available": picam is not None, "supported": picam is not None, "mode": "picam",
                "requested_fps": getattr(camera, "requested_frame_rate", None),
                "measured_fps": getattr(camera, "measured_frame_rate", None),
                "hardware_limits": camera.get_frame_rate_limits() if hasattr(camera, "get_frame_rate_limits") else None,
                "control_names": sorted(str(key) for key in controls.keys()),
                "controls": current}

    def _full_config_snapshot(self):
        rate = getattr(self.config, "processing_rate_controller", None)
        camera = getattr(self.config, "camera", None)
        return {
            "schema_version": 1,
            "mode": self._mode_slug(),
            "values": {var: self.get_base_var(var) for var in VARIABLES},
            "advanced": self.get_all_advanced(),
            "ui": json.loads(json.dumps(self.ui_settings)),
            "runtime": {
                "target_processing_fps": (
                    float(getattr(rate, "target_fps"))
                    if rate is not None and getattr(rate, "target_fps", None) is not None
                    else getattr(self.config, "TARGET_PROCESSING_FPS", None)
                ),
                "camera": self._camera_settings_snapshot(camera),
            },
        }

    def _history_file(self):
        return self._state_filename("config_history")

    def _record_config_history(self, label, snapshot=None):
        try:
            data = self._read_json_file(self._history_file(), {"items": []})
            items = data.get("items", [])
            if not isinstance(items, list):
                items = []
            state = snapshot or self._full_config_snapshot()
            signature = json.dumps(state, sort_keys=True, separators=(",", ":"), allow_nan=False)
            if items:
                previous = items[-1]
                previous_state = previous.get("snapshot", {}) if isinstance(previous, dict) else {}
                if json.dumps(previous_state, sort_keys=True, separators=(",", ":"), allow_nan=False) == signature:
                    return
            items.append({"id": int(time.time() * 1000), "timestamp": time.time(),
                          "label": str(label)[:100], "snapshot": state})
            self._write_json_atomic(self._history_file(), {"version": 1, "items": items[-CONFIG_HISTORY_LIMIT:]})
        except Exception:
            logger.exception("Failed to record dashboard configuration history")

    def _normalize_full_config(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("configuration must be a JSON object")
        if payload.get("schema_version", 1) not in (1,):
            raise ValueError("unsupported configuration schema version")
        if str(payload.get("mode", "")).lower() != self._mode_slug():
            raise ValueError("configuration mode does not match the active robot mode")
        raw_values = payload.get("values", {})
        raw_advanced = payload.get("advanced", {})
        raw_ui = payload.get("ui", {})
        if not isinstance(raw_values, dict) or not isinstance(raw_advanced, dict) or not isinstance(raw_ui, dict):
            raise ValueError("values, advanced, and ui must be objects")
        unknown_values = sorted(set(raw_values) - set(VARIABLES))
        unknown_advanced = sorted(set(raw_advanced) - set(ADVANCED_VARS))
        if unknown_values or unknown_advanced:
            raise ValueError("unknown configuration keys: " + ", ".join(unknown_values + unknown_advanced))
        values = {}
        for key, value in raw_values.items():
            if isinstance(value, bool):
                raise ValueError(f"{key} must be numeric")
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"{key} must be numeric") from None
            if not math.isfinite(number) or not 0.0 <= number <= 1.0:
                raise ValueError(f"{key} must be finite and between 0 and 1")
            values[key] = number

        capabilities = mode_capabilities(self.config)
        if ("USE_BEV" in raw_advanced
                and not capabilities.get("supports_bev", False)
                and bool(raw_advanced["USE_BEV"]) != bool(getattr(self.config, "USE_BEV", False))):
            raise ValueError("USE_BEV cannot be changed by the active perception pipeline")
        crosswalk_keys = {"CROSSWALK_THRESHOLD", "CROSSWALK_SLEEP", "CROSSWALK_THRESH_SPEND", "CW_TRAPEZOID_MODE", "CW_TOP_WIDTH_FACTOR"}
        lane_shape_keys = {"LANE_ROI_MODE", "RL_TOP_WIDTH_FACTOR", "LL_TOP_WIDTH_FACTOR"}
        changed_crosswalk = any(
            key in raw_advanced and raw_advanced[key] != getattr(self.config, key, ADVANCED_VARS[key])
            for key in crosswalk_keys
        )
        changed_lane_shape = any(
            key in raw_advanced and raw_advanced[key] != getattr(self.config, key, ADVANCED_VARS[key])
            for key in lane_shape_keys
        )
        if changed_crosswalk and not capabilities.get("supports_crosswalk", False):
            raise ValueError("crosswalk settings cannot be changed by the active mode")
        if changed_lane_shape and not capabilities.get("supports_lane_roi", False):
            raise ValueError("lane ROI settings cannot be changed by the active lane detector")

        advanced = {}
        for key, value in raw_advanced.items():
            default = ADVANCED_VARS[key]
            if type(default) is bool:
                if not isinstance(value, bool):
                    raise ValueError(f"{key} must be boolean")
                normalized = value
            elif type(default) is int:
                if isinstance(value, bool):
                    raise ValueError(f"{key} must be an integer")
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    raise ValueError(f"{key} must be an integer") from None
                if not math.isfinite(number) or not number.is_integer():
                    raise ValueError(f"{key} must be a finite integer")
                normalized = int(number)
            elif type(default) is float:
                if isinstance(value, bool):
                    raise ValueError(f"{key} must be numeric")
                try:
                    normalized = float(value)
                except (TypeError, ValueError):
                    raise ValueError(f"{key} must be numeric") from None
                if not math.isfinite(normalized):
                    raise ValueError(f"{key} must be finite")
            else:
                normalized = str(value)
            if key in {"LANE_THRESHOLD", "CROSSWALK_THRESHOLD"} and not 0 <= normalized <= 255:
                raise ValueError(f"{key} must be between 0 and 255")
            if key == "LANE_ROI_MODE" and normalized not in {"rectangle", "trapezoid"}:
                raise ValueError("LANE_ROI_MODE must be rectangle or trapezoid")
            if key == "RUN_LVL" and normalized not in {"MOVE", "STOP"}:
                raise ValueError("RUN_LVL must be MOVE or STOP")
            if key.endswith("_WIDTH_FACTOR") and not 0.0 <= normalized <= 1.0:
                raise ValueError(f"{key} must be between 0 and 1")
            if key.startswith("BEV_SRC_") and not -5.0 <= normalized <= 5.0:
                raise ValueError(f"{key} must be between -5 and 5")
            advanced[key] = normalized
        if advanced.get("WITH_SIGN", getattr(self.config, "WITH_SIGN", False)) and advanced.get("WITH_APRILTAG", getattr(self.config, "WITH_APRILTAG", False)):
            raise ValueError("WITH_SIGN and WITH_APRILTAG cannot both be enabled")

        ui = json.loads(json.dumps(self.ui_settings))
        colors, visible, opacity = raw_ui.get("colors", {}), raw_ui.get("visible", {}), raw_ui.get("opacity", {})
        if not all(isinstance(obj, dict) for obj in (colors, visible, opacity)):
            raise ValueError("ui.colors, ui.visible, and ui.opacity must be objects")
        ui.setdefault("opacity", {key: 1.0 for key in ui["visible"]})
        for key, value in colors.items():
            if key not in ui["colors"] or not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                raise ValueError(f"invalid UI color for {key}")
            ui["colors"][key] = value.lower()
        for key, value in visible.items():
            if key not in ui["visible"] or not isinstance(value, bool):
                raise ValueError(f"invalid UI visibility for {key}")
            ui["visible"][key] = value
        for key, value in opacity.items():
            if key not in ui["visible"] or isinstance(value, bool):
                raise ValueError(f"invalid layer opacity for {key}")
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"invalid layer opacity for {key}") from None
            if not math.isfinite(number) or not 0.0 <= number <= 1.0:
                raise ValueError(f"layer opacity for {key} must be between 0 and 1")
            ui["opacity"][key] = number

        runtime = payload.get("runtime", {})
        if runtime is not None and not isinstance(runtime, dict):
            raise ValueError("runtime must be an object")
        normalized_runtime = {}
        if isinstance(runtime, dict) and runtime.get("target_processing_fps") is not None:
            if getattr(self.config, "processing_rate_controller", None) is None:
                raise ValueError("live processing-rate control is unavailable in this runtime")
            try:
                fps = float(runtime["target_processing_fps"])
            except (TypeError, ValueError):
                raise ValueError("target_processing_fps must be numeric") from None
            if not math.isfinite(fps) or not 1.0 <= fps <= 60.0:
                raise ValueError("target_processing_fps must be between 1 and 60")
            normalized_runtime["target_processing_fps"] = fps
        if isinstance(runtime, dict):
            raw_camera = runtime.get("camera", {})
            raw_controls = raw_camera.get("controls", {}) if isinstance(raw_camera, dict) else {}
            if isinstance(raw_controls, dict) and raw_controls and raw_camera.get("supported"):
                camera = getattr(self.config, "camera", None)
                if camera is None or not getattr(camera, "pi_mode", False) or getattr(camera, "picam", None) is None:
                    raise ValueError("configuration includes Picamera2 controls but this runtime has no compatible camera")
                supported = getattr(camera.picam, "camera_controls", {})
                normalized_controls = {}
                for key, value in raw_controls.items():
                    if key not in {"ExposureTime", "AnalogueGain", "AeEnable", "AwbEnable"}:
                        continue
                    if key not in supported:
                        raise ValueError(f"camera does not support imported control {key}")
                    if key in {"AeEnable", "AwbEnable"}:
                        if not isinstance(value, bool):
                            raise ValueError(f"{key} must be boolean")
                        normalized_controls[key] = value
                    else:
                        number = float(value)
                        if not math.isfinite(number):
                            raise ValueError(f"{key} must be finite")
                        bounds = supported.get(key)
                        if isinstance(bounds, (tuple, list)) and len(bounds) >= 2 and not float(bounds[0]) <= number <= float(bounds[1]):
                            raise ValueError(f"{key} is outside this camera's supported range")
                        normalized_controls[key] = int(round(number)) if key == "ExposureTime" else number
                if normalized_controls:
                    normalized_runtime["camera_controls"] = normalized_controls
        return {"schema_version": 1, "mode": self._mode_slug(), "values": values,
                "advanced": advanced, "ui": ui, "runtime": normalized_runtime}

    def _apply_full_config(self, payload, label="configuration restore"):
        normalized = self._normalize_full_config(payload)
        before = self._full_config_snapshot()
        try:
            for key, value in normalized["values"].items():
                setattr(self.config, key, value)
            for key, value in normalized["advanced"].items():
                if key not in {"WITH_SIGN", "WITH_APRILTAG"}:
                    setattr(self.config, key, value)
            if "WITH_SIGN" in normalized["advanced"] or "WITH_APRILTAG" in normalized["advanced"]:
                sign = normalized["advanced"].get("WITH_SIGN", getattr(self.config, "WITH_SIGN", False))
                tag = normalized["advanced"].get("WITH_APRILTAG", getattr(self.config, "WITH_APRILTAG", False))
                set_marker_mode(self.config, "sign" if sign else "apriltag" if tag else "none")
            self.ui_settings = normalized["ui"]
            self.save_ui_settings()
            if "target_processing_fps" in normalized["runtime"]:
                fps = normalized["runtime"]["target_processing_fps"]
                self.config.processing_rate_controller.set_target_fps(fps)
                setattr(self.config, "TARGET_PROCESSING_FPS", fps)
            if "camera_controls" in normalized["runtime"]:
                camera = self.config.camera
                camera.picam.set_controls(normalized["runtime"]["camera_controls"])
                current = dict(getattr(camera, "_dashboard_image_controls", {}))
                current.update(normalized["runtime"]["camera_controls"])
                setattr(camera, "_dashboard_image_controls", current)
            self.save_conf_to_json()
            self._record_config_history("before " + label, before)
            self._record_config_history(label, self._full_config_snapshot())
            return self._full_config_snapshot()
        except Exception:
            for key, value in before.get("values", {}).items():
                setattr(self.config, key, value)
            for key, value in before.get("advanced", {}).items():
                if key not in {"WITH_SIGN", "WITH_APRILTAG"}:
                    setattr(self.config, key, value)
            try:
                set_marker_mode(self.config, "sign" if before["advanced"].get("WITH_SIGN") else "apriltag" if before["advanced"].get("WITH_APRILTAG") else "none")
            except Exception:
                logger.exception("Could not roll back marker mode after failed import")
            before_runtime = before.get("runtime", {})
            old_rate = before_runtime.get("target_processing_fps")
            rate = getattr(self.config, "processing_rate_controller", None)
            if rate is not None and old_rate is not None:
                try:
                    rate.set_target_fps(old_rate)
                    setattr(self.config, "TARGET_PROCESSING_FPS", old_rate)
                except Exception:
                    logger.exception("Could not roll back processing rate after failed import")
            old_camera = before_runtime.get("camera", {})
            old_controls = old_camera.get("controls", {}) if isinstance(old_camera, dict) else {}
            camera = getattr(self.config, "camera", None)
            if old_controls and camera is not None and getattr(camera, "picam", None) is not None:
                try:
                    camera.picam.set_controls(old_controls)
                    setattr(camera, "_dashboard_image_controls", dict(old_controls))
                except Exception:
                    logger.exception("Could not roll back camera controls after failed import")
            self.ui_settings = before["ui"]
            self.save_ui_settings()
            raise

    def full_config(self):
        if request.method == "GET":
            snapshot = self._full_config_snapshot()
            snapshot["exported_at"] = time.time()
            snapshot["controls_enabled"] = self._control_allowed()
            return jsonify(snapshot)
        if not self._control_allowed():
            return self._control_denied()
        payload = request.get_json(silent=True)
        try:
            result = self._apply_full_config(payload, "imported configuration")
            return jsonify(success=True, config=result)
        except (TypeError, ValueError) as exc:
            return jsonify(success=False, message=str(exc)), 400
        except Exception:
            logger.exception("Failed to apply full dashboard configuration")
            return jsonify(success=False, message="configuration apply failed"), 500

    def config_history(self):
        data = self._read_json_file(self._history_file(), {"items": []})
        items = data.get("items", []) if isinstance(data.get("items", []), list) else []
        items = items[-CONFIG_HISTORY_LIMIT:]
        if request.method == "GET":
            summary = []
            for index, item in enumerate(items):
                snap = item.get("snapshot", {}) if isinstance(item, dict) else {}
                summary.append({"index": index, "id": item.get("id"), "timestamp": item.get("timestamp"),
                                "label": item.get("label", "Configuration"), "mode": snap.get("mode"),
                                "advanced_keys": len(snap.get("advanced", {})), "roi_keys": len(snap.get("values", {}))})
            return jsonify(items=summary, limit=CONFIG_HISTORY_LIMIT)
        if not self._control_allowed():
            return self._control_denied()
        body = request.get_json(silent=True) or {}
        if body.get("action") != "restore":
            return jsonify(success=False, message="action must be restore"), 400
        try:
            index = int(body.get("index"))
        except (TypeError, ValueError):
            return jsonify(success=False, message="index must be an integer"), 400
        if index < 0 or index >= len(items):
            return jsonify(success=False, message="history index not found"), 404
        try:
            result = self._apply_full_config(items[index].get("snapshot"), "restored history")
            return jsonify(success=True, config=result)
        except (TypeError, ValueError) as exc:
            return jsonify(success=False, message=str(exc)), 400
        except Exception:
            logger.exception("Failed to restore configuration history")
            return jsonify(success=False, message="history restore failed"), 500

    def config_presets(self):
        filename = self._state_filename("config_presets")
        data = self._read_json_file(filename, {"presets": {}})
        presets = data.get("presets", {}) if isinstance(data.get("presets", {}), dict) else {}
        if request.method == "GET":
            requested_name = str(request.args.get("name", "")).strip()
            if requested_name:
                preset = presets.get(requested_name)
                if not preset:
                    return jsonify(success=False, message="preset not found"), 404
                return jsonify(name=requested_name, mode=preset.get("mode"), saved_at=preset.get("saved_at"),
                               config=preset.get("config"))
            return jsonify(presets=[{"name": name, "mode": value.get("mode"), "saved_at": value.get("saved_at")}
                                    for name, value in sorted(presets.items())])
        if not self._control_allowed():
            return self._control_denied()
        body = request.get_json(silent=True) or {}
        action, name = str(body.get("action", "")), str(body.get("name", "")).strip()
        if not name or len(name) > 48 or not re.fullmatch(r"[A-Za-z0-9 _.-]+", name):
            return jsonify(success=False, message="preset name must be 1-48 safe characters"), 400
        if action == "save":
            presets[name] = {"mode": self._mode_slug(), "saved_at": time.time(), "config": self._full_config_snapshot()}
        elif action == "delete":
            if name not in presets:
                return jsonify(success=False, message="preset not found"), 404
            del presets[name]
        elif action == "apply":
            preset = presets.get(name)
            if not preset:
                return jsonify(success=False, message="preset not found"), 404
            try:
                result = self._apply_full_config(preset.get("config"), "applied preset " + name)
            except (TypeError, ValueError) as exc:
                return jsonify(success=False, message=str(exc)), 400
            except Exception:
                logger.exception("Failed to apply configuration preset")
                return jsonify(success=False, message="preset apply failed"), 500
            self._write_json_atomic(filename, {"version": 1, "presets": presets})
            return jsonify(success=True, config=result)
        else:
            return jsonify(success=False, message="action must be save, delete, or apply"), 400
        self._write_json_atomic(filename, {"version": 1, "presets": presets})
        return jsonify(success=True, presets=[{"name": key, "mode": value.get("mode"), "saved_at": value.get("saved_at")} for key, value in sorted(presets.items())])

    def _workspace_default(self):
        return {"version": 1, "workspace": {}, "profiles": {}}

    def _sanitize_workspace(self, workspace):
        if not isinstance(workspace, dict):
            raise ValueError("workspace must be a JSON object")
        if len(json.dumps(workspace, ensure_ascii=False)) > 250000:
            raise ValueError("workspace data exceeds 250 KB")
        clean = {}
        view = workspace.get("view", {})
        if not isinstance(view, dict):
            raise ValueError("view must be an object")
        clean_view = {}
        for key, minimum, maximum in (("zoom", 0.3, 4.0), ("panX", -100000.0, 100000.0), ("panY", -100000.0, 100000.0), ("rightPaneWidth", 250.0, 700.0)):
            if key in view:
                value = view[key]
                if isinstance(value, bool):
                    raise ValueError(f"view.{key} must be numeric")
                value = float(value)
                if not math.isfinite(value) or not minimum <= value <= maximum:
                    raise ValueError(f"view.{key} is out of range")
                clean_view[key] = value
        for key in ("grid", "snap", "crosshair", "showRuler", "overlays"):
            if key in view:
                if not isinstance(view[key], bool):
                    raise ValueError(f"view.{key} must be boolean")
                clean_view[key] = view[key]
        if "tool" in view:
            if view["tool"] not in {"select", "pan", "annotate", "ruler", "roi"}:
                raise ValueError("view.tool is invalid")
            clean_view["tool"] = view["tool"]
        clean["view"] = clean_view
        panels = workspace.get("panels", {})
        if not isinstance(panels, dict):
            raise ValueError("panels must be an object")
        clean["panels"] = {str(key)[:80]: value for key, value in panels.items() if isinstance(value, bool)}
        layers = workspace.get("layers", {})
        if not isinstance(layers, dict):
            raise ValueError("layers must be an object")
        clean_layers = {}
        for key, layer in layers.items():
            if key not in {"RL", "LL", "CW", "ST", "OBJ", "BEV", "ANNOTATIONS", "GRID"} or not isinstance(layer, dict):
                continue
            entry = {}
            if "visible" in layer:
                if not isinstance(layer["visible"], bool):
                    raise ValueError(f"layers.{key}.visible must be boolean")
                entry["visible"] = layer["visible"]
            if "opacity" in layer:
                val = float(layer["opacity"])
                if not math.isfinite(val) or not 0 <= val <= 1:
                    raise ValueError(f"layers.{key}.opacity must be between 0 and 1")
                entry["opacity"] = val
            clean_layers[key] = entry
        clean["layers"] = clean_layers
        annotations = workspace.get("annotations", [])
        if not isinstance(annotations, list) or len(annotations) > 250:
            raise ValueError("annotations must be a list of at most 250 items")
        clean_annotations = []
        for item in annotations:
            if not isinstance(item, dict) or item.get("kind") not in {"marker", "note", "ruler", "roi"}:
                raise ValueError("annotation has an unsupported kind")
            entry = {"kind": item["kind"]}
            for key in ("u", "v", "u2", "v2"):
                if key in item:
                    val = float(item[key])
                    if not math.isfinite(val) or not 0 <= val <= 1:
                        raise ValueError("annotation coordinates must be normalized between 0 and 1")
                    entry[key] = val
            if "label" in item:
                entry["label"] = str(item["label"])[:80]
            if "color" in item and isinstance(item["color"], str) and re.fullmatch(r"#[0-9a-fA-F]{6}", item["color"]):
                entry["color"] = item["color"].lower()
            clean_annotations.append(entry)
        clean["annotations"] = clean_annotations
        return clean

    def workspace_api(self):
        filename = self._state_filename("workspace")
        data = self._read_json_file(filename, self._workspace_default())
        if not isinstance(data.get("profiles"), dict):
            data["profiles"] = {}
        if request.method == "GET":
            return jsonify(version=1, workspace=data.get("workspace", {}), profiles=sorted(data["profiles"].keys()))
        body = request.get_json(silent=True) or {}
        action = str(body.get("action", "save_workspace"))
        try:
            if action == "save_workspace":
                data["workspace"] = self._sanitize_workspace(body.get("workspace", {}))
            elif action == "save_profile":
                name = str(body.get("name", "")).strip()
                if not name or len(name) > 48 or not re.fullmatch(r"[A-Za-z0-9 _.-]+", name):
                    raise ValueError("profile name must be 1-48 safe characters")
                data["profiles"][name] = self._sanitize_workspace(body.get("workspace", {}))
            elif action == "delete_profile":
                name = str(body.get("name", "")).strip()
                if name not in data["profiles"]:
                    return jsonify(success=False, message="profile not found"), 404
                del data["profiles"][name]
            elif action == "load_profile":
                name = str(body.get("name", "")).strip()
                if name not in data["profiles"]:
                    return jsonify(success=False, message="profile not found"), 404
                return jsonify(success=True, workspace=data["profiles"][name], name=name)
            else:
                return jsonify(success=False, message="unsupported workspace action"), 400
            self._write_json_atomic(filename, data)
            return jsonify(success=True, workspace=data.get("workspace", {}), profiles=sorted(data["profiles"].keys()))
        except (TypeError, ValueError) as exc:
            return jsonify(success=False, message=str(exc)), 400
        except Exception:
            logger.exception("Failed to persist dashboard workspace")
            return jsonify(success=False, message="workspace save failed"), 500

    def server_logs(self):
        try:
            limit = max(1, min(200, int(request.args.get("limit", "100"))))
        except (TypeError, ValueError):
            return jsonify(success=False, message="limit must be an integer"), 400
        query = str(request.args.get("q", "")).strip().lower()[:120]
        level = str(request.args.get("level", "ALL")).upper()
        levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
        if level != "ALL" and level not in levels:
            return jsonify(success=False, message="invalid log level"), 400
        with _STREAM_LOG_LOCK:
            entries = list(_STREAM_LOGS)
        selected = []
        for entry in reversed(entries):
            if level != "ALL" and levels.get(entry["level"], 0) < levels[level]:
                continue
            if query and query not in (entry["message"] + " " + entry["logger"]).lower():
                continue
            selected.append(dict(entry))
            if len(selected) >= limit:
                break
        return jsonify(items=selected, count=len(selected), buffer_limit=STREAM_LOG_LIMIT,
                       source="in-memory runtime log buffer")

    def traffic_lights_api(self):
        if self._mode_slug() != "city":
            return jsonify(enabled=False, available=False, reason="traffic-light status is city-only"), 409
        robot = getattr(self.config, "runtime_robot", None)
        enabled = bool(getattr(self.config, "TRAFFIC_LIGHTS_ENABLED", False))
        window = getattr(robot, "traffic_light_window", None) if robot is not None else None
        return jsonify(available=robot is not None, enabled=enabled,
                       wait_before_check=bool(getattr(self.config, "TRAFFIC_LIGHT_WAIT_BEFORE_CHECK", False)),
                       status=getattr(robot, "_traffic_light_status", getattr(self.config, "traffic_light_status", "UNKNOWN")) if robot is not None else "runtime object unavailable",
                       last_state=getattr(robot, "_traffic_light_last_state", None) if robot is not None else None,
                       confirmation_window=window.snapshot() if window is not None and callable(getattr(window, "snapshot", None)) else None,
                       restart_required=not enabled)

    def race_status_api(self):
        if self._mode_slug() != "race":
            return jsonify(available=False, reason="race lifecycle is race-only"), 409
        robot = getattr(self.config, "runtime_robot", None)
        if robot is None:
            return jsonify(available=False, reason="race runtime object unavailable")
        gate, finish, hold = (getattr(robot, "race_start_gate", None),
                              getattr(robot, "race_finish", None), getattr(robot, "stop_hold", None))
        return jsonify(available=True, start_gate_enabled=gate is not None,
                       start_gate_released=bool(getattr(gate, "released", True)) if gate is not None else True,
                       motion_released=bool(getattr(robot, "_race_start_gate_motion_released", True)),
                       timer_started=bool(getattr(robot, "_race_timer_started", False)),
                       finishing=bool(getattr(finish, "finishing", False)) if finish is not None else False,
                       finished=bool(getattr(finish, "finished", False)) if finish is not None else False,
                       stop_hold_active=bool(getattr(hold, "active", False)) if hold is not None else False,
                       sign_observation_fresh=bool(getattr(robot, "last_sign_observation_fresh", False)),
                       stop_detector=getattr(robot, "stop_hold_detector_kind", None),
                       run_level=str(getattr(self.config, "RUN_LVL", "MOVE")))

    def camera_settings_api(self):
        camera = getattr(self.config, "camera", None)
        if request.method == "GET":
            return jsonify(camera=self._camera_settings_snapshot(camera))
        if not self._control_allowed():
            return self._control_denied()
        if camera is None or not bool(getattr(camera, "pi_mode", False)) or getattr(camera, "picam", None) is None:
            return jsonify(success=False, message="runtime camera controls require an initialized Picamera2 camera"), 409
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return jsonify(success=False, message="request body must be an object"), 400
        allowed = {"ExposureTime", "AnalogueGain", "AeEnable", "AwbEnable"}
        if not body or set(body) - allowed:
            return jsonify(success=False, message="only ExposureTime, AnalogueGain, AeEnable, and AwbEnable are accepted"), 400
        supported = getattr(camera.picam, "camera_controls", {})
        controls = {}
        try:
            for key, value in body.items():
                if key not in supported:
                    return jsonify(success=False, message=f"camera does not support {key}"), 409
                if key in {"AeEnable", "AwbEnable"}:
                    if not isinstance(value, bool):
                        raise ValueError(f"{key} must be boolean")
                    controls[key] = value
                else:
                    if isinstance(value, bool):
                        raise ValueError(f"{key} must be numeric")
                    number = float(value)
                    if not math.isfinite(number):
                        raise ValueError(f"{key} must be finite")
                    bounds = supported.get(key)
                    if isinstance(bounds, (tuple, list)) and len(bounds) >= 2:
                        lower, upper = float(bounds[0]), float(bounds[1])
                        if not lower <= number <= upper:
                            raise ValueError(f"{key} must be between the camera-supported limits {lower:g} and {upper:g}")
                    controls[key] = int(round(number)) if key == "ExposureTime" else number
            before = self._full_config_snapshot()
            camera.picam.set_controls(controls)
            current = dict(getattr(camera, "_dashboard_image_controls", {}))
            current.update(controls)
            setattr(camera, "_dashboard_image_controls", current)
            self._record_config_history("before camera settings update", before)
            self._record_config_history("camera settings updated")
            logger.info("Dashboard applied camera controls: %s", ", ".join(sorted(controls)))
            return jsonify(success=True, camera=self._camera_settings_snapshot(camera))
        except (TypeError, ValueError) as exc:
            return jsonify(success=False, message=str(exc)), 400
        except Exception:
            logger.exception("Failed to apply runtime Picamera2 controls")
            return jsonify(success=False, message="camera rejected these controls"), 502

    def processing_rate_api(self):
        rate = getattr(self.config, "processing_rate_controller", None)
        if request.method == "GET":
            return jsonify(available=rate is not None, runtime_only=True,
                           target_fps=getattr(rate, "target_fps", getattr(self.config, "TARGET_PROCESSING_FPS", None)) if rate is not None else None,
                           diagnostics=rate.snapshot() if rate is not None and hasattr(rate, "snapshot") else None)
        if not self._control_allowed():
            return self._control_denied()
        if rate is None or not callable(getattr(rate, "set_target_fps", None)):
            return jsonify(success=False, message="the active runtime does not expose live processing-rate control"), 409
        body = request.get_json(silent=True) or {}
        try:
            fps = float(body.get("target_fps"))
            if not math.isfinite(fps) or not 1.0 <= fps <= 60.0:
                raise ValueError("target_fps must be between 1 and 60")
            before = self._full_config_snapshot()
            rate.set_target_fps(fps)
            setattr(self.config, "TARGET_PROCESSING_FPS", fps)
            self.save_conf_to_json()
            self._record_config_history("before processing rate update", before)
            self._record_config_history("processing rate updated")
            return jsonify(success=True, persisted=True, target_fps=rate.target_fps, diagnostics=rate.snapshot())
        except (TypeError, ValueError) as exc:
            return jsonify(success=False, message=str(exc)), 400

    def safety_api(self):
        if request.method == "GET":
            level = str(getattr(self.config, "RUN_LVL", "MOVE"))
            return jsonify(controls_enabled=self._control_allowed(), run_level=level,
                           software_stop_active=level == "STOP",
                           disclaimer="Software stop is processed by the active Python control loop; it is not a hardware emergency stop.")
        if not self._control_allowed():
            return self._control_denied()
        body = request.get_json(silent=True) or {}
        action = body.get("action")
        if action not in {"stop", "resume"}:
            return jsonify(success=False, message="action must be stop or resume"), 400
        # The mode loop owns the MCU latch; do not send a guessed raw serial command.
        setattr(self.config, "RUN_LVL", "STOP" if action == "stop" else "MOVE")
        self.save_conf_to_json()
        self._record_config_history("dashboard software " + action)
        logger.warning("Dashboard requested software %s (mode=%s)", action, self._mode_slug())
        return jsonify(success=True, action=action, run_level=getattr(self.config, "RUN_LVL"),
                       software_stop_active=action == "stop", hardware_emergency_stop=False)

    def _feature_snapshot(self):
        capabilities = mode_capabilities(self.config)
        robot = getattr(self.config, "runtime_robot", None)
        traffic_detector_ready = bool(
            robot is not None
            and getattr(robot, "traffic_light_detector", None) is not None
            and getattr(robot, "traffic_light_window", None) is not None
        )
        return {
            "mode": self._mode_slug(),
            "controls_enabled": self._control_allowed(),
            "live": {
                "DETECT_OBJECT": {
                    "enabled": bool(getattr(self.config, "DETECT_OBJECT", False)),
                    "available": bool(capabilities.get("supports_object_detection", False)),
                    "description": "Object detection is checked each control cycle; the detector is constructed by the active mode.",
                },
                "RECORD_VIDEO": {
                    "enabled": bool(getattr(self.config, "RECORD_VIDEO", False)),
                    "available": bool(capabilities.get("supports_recording", False)),
                    "description": "Recording flag is consumed by the active mode's output manager.",
                },
                "USE_BEV": {
                    "enabled": bool(getattr(self.config, "USE_BEV", False)),
                    "available": bool(capabilities.get("supports_bev", False)),
                    "description": "Bird's-eye transform can be changed live only when supported by the active lane pipeline.",
                },
                "marker_mode": {
                    "value": marker_mode(self.config),
                    "available": bool(capabilities.get("supports_sign", False) and capabilities.get("supports_apriltag", False)),
                    "description": "Marker mode uses the mode's existing runtime apply_marker_mode callback.",
                },
            },
            "restart_required": {
                "TRAFFIC_LIGHTS_ENABLED": {
                    "enabled": bool(getattr(self.config, "TRAFFIC_LIGHTS_ENABLED", False)),
                    "available": traffic_detector_ready,
                    "restart_required_to_enable": not traffic_detector_ready,
                    "reason": "City-only opt-in constructed by --traffic-lights at startup; dashboard will not silently create or bypass its safety gate.",
                },
                "CONFIDENCE_AWARE_ENABLED": {
                    "enabled": bool(getattr(self.config, "CONFIDENCE_AWARE_ENABLED", False)),
                    "reason": "Estimator/limiter lifecycle is created during mode initialization; requires --confidence-aware and restart.",
                },
                "ADAPTIVE_OBSTACLE_AVOIDANCE_ENABLED": {
                    "enabled": bool(getattr(self.config, "ADAPTIVE_OBSTACLE_AVOIDANCE_ENABLED", False)),
                    "reason": "Planner and firmware lane-ownership negotiation are startup-time; requires --adaptive-obstacle-avoidance and compatible firmware.",
                },
                "ENCODER_MAP_ENABLED": {
                    "enabled": bool(getattr(self.config, "ENCODER_MAP_ENABLED", False)),
                    "reason": "Odometry and serial telemetry contract are initialized at startup; requires --encoder-map and compatible firmware.",
                },
            },
        }

    def features_api(self):
        if request.method == "GET":
            return jsonify(self._feature_snapshot())
        if not self._control_allowed():
            return self._control_denied()
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return jsonify(success=False, message="request body must be a JSON object"), 400
        feature = str(body.get("feature", ""))
        value = body.get("value")
        capabilities = mode_capabilities(self.config)
        before = self._full_config_snapshot()
        try:
            if feature == "DETECT_OBJECT":
                if not capabilities.get("supports_object_detection", False):
                    return jsonify(success=False, message="object detection is unsupported by the active mode"), 409
                if not isinstance(value, bool):
                    raise ValueError("DETECT_OBJECT value must be boolean")
                setattr(self.config, "DETECT_OBJECT", value)
            elif feature == "RECORD_VIDEO":
                if not capabilities.get("supports_recording", False):
                    return jsonify(success=False, message="recording is unsupported by the active mode"), 409
                if not isinstance(value, bool):
                    raise ValueError("RECORD_VIDEO value must be boolean")
                setattr(self.config, "RECORD_VIDEO", value)
            elif feature == "USE_BEV":
                if not capabilities.get("supports_bev", False):
                    return jsonify(success=False, message="BEV cannot be changed by the active lane pipeline"), 409
                if not isinstance(value, bool):
                    raise ValueError("USE_BEV value must be boolean")
                setattr(self.config, "USE_BEV", value)
            elif feature == "marker_mode":
                value = str(value).lower()
                if value not in {"none", "sign", "apriltag"}:
                    raise ValueError("marker_mode must be none, sign, or apriltag")
                if value == "sign" and not capabilities.get("supports_sign", False):
                    return jsonify(success=False, message="traffic sign detection is unsupported by this mode"), 409
                if value == "apriltag" and not capabilities.get("supports_apriltag", False):
                    return jsonify(success=False, message="AprilTag detection is unsupported by this mode"), 409
                set_marker_mode(self.config, value)
            else:
                return jsonify(success=False, message="feature is not runtime-controllable; check restart_required status"), 400
            self.save_conf_to_json()
            self._record_config_history("before feature change " + feature, before)
            self._record_config_history("feature changed: " + feature)
            logger.info("Dashboard live feature change: %s=%s", feature, value)
            return jsonify(success=True, feature=feature, value=value, state=self._feature_snapshot())
        except (TypeError, ValueError) as exc:
            return jsonify(success=False, message=str(exc)), 400
        except Exception:
            logger.exception("Failed to apply live feature change")
            return jsonify(success=False, message="feature change failed"), 500

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
        processing_rate = getattr(self.config, "processing_rate_controller", None)
        if processing_rate is not None:
            payload["processing_rate"] = processing_rate.snapshot()

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
