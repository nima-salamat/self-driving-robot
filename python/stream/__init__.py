import logging
import cv2
import json
import time
import os
from flask import Flask, Response, request, render_template_string, jsonify
import threading
import base_config as temp_conf
from .template import HTML_TEMPLATE

# choose config module
if temp_conf.CONFIG_MODULE is not None:
    conf = temp_conf.CONFIG_MODULE
else:
    conf = temp_conf

logger = logging.getLogger(__name__)
stop_event = threading.Event()
app = Flask(__name__)

# --- ROI variable names (Bounding Boxes) ---
VARIABLES = [
    "RL_TOP_ROI", "RL_BOTTOM_ROI", "RL_LEFT_ROI", "RL_RIGHT_ROI",
    "LL_TOP_ROI", "LL_BOTTOM_ROI", "LL_LEFT_ROI", "LL_RIGHT_ROI",
    "CW_TOP_ROI", "CW_BOTTOM_ROI", "CW_LEFT_ROI", "CW_RIGHT_ROI",
    "ST_TOP_ROI", "ST_BOTTOM_ROI", "ST_LEFT_ROI", "ST_RIGHT_ROI",
    "OBJ_TOP_ROI", "OBJ_BOTTOM_ROI", "OBJ_LEFT_ROI", "OBJ_RIGHT_ROI"  
]

def get_base_var(var):
    """Helper to return 1.0 default for BOTTOM/RIGHT, and 0.0 for TOP/LEFT"""
    default = 1.0 if ("BOTTOM" in var or "RIGHT" in var) else 0.0
    return float(getattr(conf, var, default))

# --- Advanced variables (Includes all system limits & ST/OBJ setup) ---
ADVANCED_VARS = {
    # Vision & General Limits
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
    
    # ROI Shape Setup
    "LANE_ROI_MODE": "trapezoid", 
    "CW_TRAPEZOID_MODE": True,
    "ST_TRAPEZOID_MODE": True,    
    "OBJ_TRAPEZOID_MODE": True,
    "RL_TOP_WIDTH_FACTOR": 0.5,
    "LL_TOP_WIDTH_FACTOR": 0.5,
    "CW_TOP_WIDTH_FACTOR": 0.6,
    "ST_TOP_WIDTH_FACTOR": 0.8,
    "OBJ_TOP_WIDTH_FACTOR": 0.8,

    # BEV Setup
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

# Dynamic helper to extract all advanced variables properly typed
def get_all_advanced():
    res = {}
    for k, default_v in ADVANCED_VARS.items():
        val = getattr(conf, k, default_v)
        if type(default_v) == bool: res[k] = bool(val)
        elif type(default_v) == int: res[k] = int(val)
        elif type(default_v) == float: res[k] = float(val)
        else: res[k] = str(val)
    return res

# UI settings filename and functions
def ui_filename():
    mode = getattr(temp_conf, "MODE", "mode")
    return f"{mode}_ui.json"

def load_ui_settings():
    fname = ui_filename()
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
                # Fallbacks in case old config doesn't have missing keys
                for key in default_ui["colors"]:
                    if key not in ui["colors"]: ui["colors"][key] = default_ui["colors"][key]
                for key in default_ui["visible"]:
                    if key not in ui["visible"]: ui["visible"][key] = default_ui["visible"][key]
                return ui
        except Exception:
            logger.exception("Failed load UI settings")
    return default_ui

def save_ui_settings(settings):
    fname = ui_filename()
    try:
        with open(fname, "w") as f:
            json.dump(settings, f, indent=2)
    except Exception:
        logger.exception("Failed writing UI settings")

UI_SETTINGS = load_ui_settings()

# save ROI + advanced to JSON
def config_filename():
    mode = getattr(temp_conf, "MODE", "mode")
    return f"{mode}.json"

def save_conf_to_json():
    filename = config_filename()
    # Save base ROI points
    data = {var: get_base_var(var) for var in VARIABLES}
    # Save all advanced config seamlessly
    data.update(get_all_advanced())
    
    try:
        with open(filename, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        logger.exception("Failed writing config JSON")

# --- Flask routes ---
@app.route('/')
def index():
    values = {var: get_base_var(var) for var in VARIABLES}
    advanced_current = get_all_advanced()
    return render_template_string(HTML_TEMPLATE, variables=VARIABLES, values=values, ui=UI_SETTINGS, advanced=advanced_current, mode=getattr(temp_conf, "MODE", "mode"))

@app.route('/update_conf', methods=['POST'])
def update_conf():
    try:
        data = request.get_json() or request.form.to_dict()
        updated = {}
        for var in VARIABLES:
            if var in data:
                try:
                    val = float(data[var])
                    val = max(0.0, min(1.0, val)) # Keep standard ROIs within 0-1
                    setattr(conf, var, val)
                    updated[var] = val
                except:
                    pass
        if updated:
            save_conf_to_json()
        return jsonify(success=True, values={var: get_base_var(var) for var in VARIABLES})
    except:
        return jsonify(success=False)

@app.route('/get_values')
def get_values():
    return jsonify(values={var: get_base_var(var) for var in VARIABLES})

@app.route('/get_advanced')
def get_advanced():
    return jsonify(advanced=get_all_advanced())

@app.route('/set_advanced', methods=['POST'])
def set_advanced():
    data = request.get_json() or {}
    try:
        # Loop dynamically so no setting is ever missed
        for k, default_v in ADVANCED_VARS.items():
            if k in data:
                val = data[k]
                
                # Apply limits & Types
                if k in ("LANE_THRESHOLD", "CROSSWALK_THRESHOLD"): val = max(0, min(255, int(val)))
                # ALLOW EXTREME POINTS FOR BEV (e.g., -5.0 to 5.0 instead of 0.0 to 1.0)
                elif k.startswith("BEV_SRC_"): val = max(-5.0, min(5.0, float(val)))
                
                expected_type = type(default_v)
                if expected_type == bool: val = bool(val)
                elif expected_type == int: val = int(val)
                elif expected_type == float: val = float(val)
                else: val = str(val)
                
                setattr(conf, k, val)

        # Linked logic overrides
        if "RUN_LVL" in data: 
            setattr(conf, "RUN_LVL", data["RUN_LVL"] if data["RUN_LVL"] in ("MOVE","STOP") else "MOVE")
            
        if "WITH_SIGN" in data or "WITH_APRILTAG" in data:
            use_sign = bool(data.get("WITH_SIGN", getattr(conf, "WITH_SIGN", True)))
            setattr(conf, "WITH_SIGN", use_sign)
            setattr(conf, "WITH_APRILTAG", not use_sign)
        
    except Exception as e:
        logger.exception("Invalid advanced payload")
        return jsonify(success=False), 400
        
    save_conf_to_json()
    return jsonify(success=True, advanced=get_all_advanced())

@app.route('/get_ui')
def get_ui(): return jsonify(ui=UI_SETTINGS)

@app.route('/set_ui', methods=['POST'])
def set_ui():
    data = request.get_json() or {}
    if "colors" in data: UI_SETTINGS["colors"].update({k:v for k,v in data["colors"].items() if k in UI_SETTINGS["colors"]})
    if "visible" in data: UI_SETTINGS["visible"].update({k:bool(v) for k,v in data["visible"].items() if k in UI_SETTINGS["visible"]})
    save_ui_settings(UI_SETTINGS)
    return jsonify(success=True, ui=UI_SETTINGS)

@app.route('/video_feed_frame')
def video_feed_frame():
    frozen = getattr(conf, "frozen_debug_frame", None)
    if frozen is not None: frame = frozen
    else:
        frames_list = getattr(conf, "debug_frames_list", [])
        frame = frames_list[-1] if frames_list else None
    if frame is None: return Response('', status=204)
    ret, buffer = cv2.imencode('.jpg', frame)
    if not ret: return Response('', status=204)
    return Response(buffer.tobytes(), mimetype='image/jpeg')

@app.route('/take_picture', methods=['POST'])
def take_picture():
    setattr(conf, "TAKE_PICTURE", True)
    return jsonify(success=True)

@app.route('/toggle_record', methods=['POST'])
def toggle_record():
    current = getattr(conf, "RECORD_VIDEO", False)
    new_val = not current
    setattr(conf, "RECORD_VIDEO", new_val)
    save_conf_to_json()
    return jsonify(success=True, recording=new_val)

@app.route('/freeze_frame', methods=['POST'])
def freeze_frame():
    frames_list = getattr(conf, "debug_frames_list", [])
    if frames_list:
        setattr(conf, "frozen_debug_frame", frames_list[-1].copy())
        return jsonify(success=True)
    return jsonify(success=False, message="No frame available")

@app.route('/unfreeze_frame', methods=['POST'])
def unfreeze_frame():
    if hasattr(conf, "frozen_debug_frame"): delattr(conf, "frozen_debug_frame")
    return jsonify(success=True)

@app.route("/shutdown", methods=["POST"])
def shutdown(): os._exit(0)

def start_stream(): app.run(host='0.0.0.0', port=5000, threaded=True, debug=False)