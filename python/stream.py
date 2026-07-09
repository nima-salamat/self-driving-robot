# =========================
# stream.py
# =========================
import logging
import cv2
import json
import time
import os
from flask import Flask, Response, request, render_template_string, jsonify
import threading
import base_config as temp_conf
from template import HTML_TEMPLATE
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
    "CW_TOP_ROI", "CW_BOTTOM_ROI", "CW_LEFT_ROI", "CW_RIGHT_ROI"
]

# --- Advanced variables (Including new Trapezoid Settings & BEV) ---
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
    "RL_TOP_WIDTH_FACTOR": 0.5,
    "LL_TOP_WIDTH_FACTOR": 0.5,
    "CW_TOP_WIDTH_FACTOR": 0.6,

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

# UI settings filename and functions
def ui_filename():
    mode = getattr(temp_conf, "MODE", "mode")
    return f"{mode}_ui.json"

def load_ui_settings():
    fname = ui_filename()
    default_ui = {
        "colors": {"RL":"#ff7b7b", "LL":"#7bffb8", "CW":"#ffd27b", "BEV":"#d946ef"},
        "visible": {"RL":True, "LL":True, "CW":True, "BEV":True}
    }
    if os.path.exists(fname):
        try:
            with open(fname, "r") as f:
                data = json.load(f)
                ui = {
                    "colors": data.get("colors", default_ui["colors"]),
                    "visible": data.get("visible", default_ui["visible"])
                }
                # Fallbacks in case old config doesn't have BEV
                if "BEV" not in ui["colors"]: ui["colors"]["BEV"] = default_ui["colors"]["BEV"]
                if "BEV" not in ui["visible"]: ui["visible"]["BEV"] = default_ui["visible"]["BEV"]
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
    data = {var: float(getattr(conf, var, 0.0)) for var in VARIABLES}
    
    # Update with Advanced Variables
    data.update({
        "LANE_THRESHOLD": int(getattr(conf, "LANE_THRESHOLD", ADVANCED_VARS["LANE_THRESHOLD"])),
        "CROSSWALK_THRESHOLD": int(getattr(conf, "CROSSWALK_THRESHOLD", ADVANCED_VARS["CROSSWALK_THRESHOLD"])),
        "CROSSWALK_SLEEP": float(getattr(conf, "CROSSWALK_SLEEP", ADVANCED_VARS["CROSSWALK_SLEEP"])),
        "CROSSWALK_THRESH_SPEND": float(getattr(conf, "CROSSWALK_THRESH_SPEND", ADVANCED_VARS["CROSSWALK_THRESH_SPEND"])),
        "RUN_LVL": str(getattr(conf, "RUN_LVL", ADVANCED_VARS["RUN_LVL"])),
        "WITH_SIGN": bool(getattr(conf, "WITH_SIGN", ADVANCED_VARS["WITH_SIGN"])),
        "WITH_APRILTAG": bool(getattr(conf, "WITH_APRILTAG", ADVANCED_VARS["WITH_APRILTAG"])),
        "READ_SIGN_THRESHOLD": int(getattr(conf, "READ_SIGN_THRESHOLD", ADVANCED_VARS["READ_SIGN_THRESHOLD"])),
        "TURN_RIGHT": int(getattr(conf, "TURN_RIGHT", ADVANCED_VARS["TURN_RIGHT"])),
        "TURN_LEFT": int(getattr(conf, "TURN_LEFT", ADVANCED_VARS["TURN_LEFT"])),
        "STRAIGHT": int(getattr(conf, "STRAIGHT", ADVANCED_VARS["STRAIGHT"])),
        "STOP": int(getattr(conf, "STOP", ADVANCED_VARS["STOP"])),
        "RECORD_VIDEO": bool(getattr(conf, "RECORD_VIDEO", ADVANCED_VARS["RECORD_VIDEO"])),
        
        # Shape variables
        "LANE_ROI_MODE": str(getattr(conf, "LANE_ROI_MODE", ADVANCED_VARS["LANE_ROI_MODE"])),
        "CW_TRAPEZOID_MODE": bool(getattr(conf, "CW_TRAPEZOID_MODE", ADVANCED_VARS["CW_TRAPEZOID_MODE"])),
        "RL_TOP_WIDTH_FACTOR": float(getattr(conf, "RL_TOP_WIDTH_FACTOR", ADVANCED_VARS["RL_TOP_WIDTH_FACTOR"])),
        "LL_TOP_WIDTH_FACTOR": float(getattr(conf, "LL_TOP_WIDTH_FACTOR", ADVANCED_VARS["LL_TOP_WIDTH_FACTOR"])),
        "CW_TOP_WIDTH_FACTOR": float(getattr(conf, "CW_TOP_WIDTH_FACTOR", ADVANCED_VARS["CW_TOP_WIDTH_FACTOR"])),
        
        # BEV Variables
        "USE_BEV": bool(getattr(conf, "USE_BEV", ADVANCED_VARS["USE_BEV"])),
        "BEV_SRC_TL_X": float(getattr(conf, "BEV_SRC_TL_X", ADVANCED_VARS["BEV_SRC_TL_X"])),
        "BEV_SRC_TL_Y": float(getattr(conf, "BEV_SRC_TL_Y", ADVANCED_VARS["BEV_SRC_TL_Y"])),
        "BEV_SRC_TR_X": float(getattr(conf, "BEV_SRC_TR_X", ADVANCED_VARS["BEV_SRC_TR_X"])),
        "BEV_SRC_TR_Y": float(getattr(conf, "BEV_SRC_TR_Y", ADVANCED_VARS["BEV_SRC_TR_Y"])),
        "BEV_SRC_BR_X": float(getattr(conf, "BEV_SRC_BR_X", ADVANCED_VARS["BEV_SRC_BR_X"])),
        "BEV_SRC_BR_Y": float(getattr(conf, "BEV_SRC_BR_Y", ADVANCED_VARS["BEV_SRC_BR_Y"])),
        "BEV_SRC_BL_X": float(getattr(conf, "BEV_SRC_BL_X", ADVANCED_VARS["BEV_SRC_BL_X"])),
        "BEV_SRC_BL_Y": float(getattr(conf, "BEV_SRC_BL_Y", ADVANCED_VARS["BEV_SRC_BL_Y"]))
    })
    try:
        with open(filename, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        logger.exception("Failed writing config JSON")


# --- Flask routes ---
@app.route('/')
def index():
    values = {var: float(getattr(conf, var, 0.0)) for var in VARIABLES}
    advanced_current = {
        "LANE_THRESHOLD": int(getattr(conf, "LANE_THRESHOLD", ADVANCED_VARS["LANE_THRESHOLD"])),
        "CROSSWALK_THRESHOLD": int(getattr(conf, "CROSSWALK_THRESHOLD", ADVANCED_VARS["CROSSWALK_THRESHOLD"])),
        "RUN_LVL": getattr(conf, "RUN_LVL", ADVANCED_VARS["RUN_LVL"]),
        "WITH_SIGN": bool(getattr(conf, "WITH_SIGN", ADVANCED_VARS["WITH_SIGN"])),
        "WITH_APRILTAG": bool(getattr(conf, "WITH_APRILTAG", ADVANCED_VARS["WITH_APRILTAG"])),
        "LANE_ROI_MODE": str(getattr(conf, "LANE_ROI_MODE", ADVANCED_VARS["LANE_ROI_MODE"])),
        "CW_TRAPEZOID_MODE": bool(getattr(conf, "CW_TRAPEZOID_MODE", ADVANCED_VARS["CW_TRAPEZOID_MODE"])),
        "RL_TOP_WIDTH_FACTOR": float(getattr(conf, "RL_TOP_WIDTH_FACTOR", ADVANCED_VARS["RL_TOP_WIDTH_FACTOR"])),
        "LL_TOP_WIDTH_FACTOR": float(getattr(conf, "LL_TOP_WIDTH_FACTOR", ADVANCED_VARS["LL_TOP_WIDTH_FACTOR"])),
        "CW_TOP_WIDTH_FACTOR": float(getattr(conf, "CW_TOP_WIDTH_FACTOR", ADVANCED_VARS["CW_TOP_WIDTH_FACTOR"])),
        
        "USE_BEV": bool(getattr(conf, "USE_BEV", ADVANCED_VARS["USE_BEV"])),
        "BEV_SRC_TL_X": float(getattr(conf, "BEV_SRC_TL_X", ADVANCED_VARS["BEV_SRC_TL_X"])),
        "BEV_SRC_TL_Y": float(getattr(conf, "BEV_SRC_TL_Y", ADVANCED_VARS["BEV_SRC_TL_Y"])),
        "BEV_SRC_TR_X": float(getattr(conf, "BEV_SRC_TR_X", ADVANCED_VARS["BEV_SRC_TR_X"])),
        "BEV_SRC_TR_Y": float(getattr(conf, "BEV_SRC_TR_Y", ADVANCED_VARS["BEV_SRC_TR_Y"])),
        "BEV_SRC_BR_X": float(getattr(conf, "BEV_SRC_BR_X", ADVANCED_VARS["BEV_SRC_BR_X"])),
        "BEV_SRC_BR_Y": float(getattr(conf, "BEV_SRC_BR_Y", ADVANCED_VARS["BEV_SRC_BR_Y"])),
        "BEV_SRC_BL_X": float(getattr(conf, "BEV_SRC_BL_X", ADVANCED_VARS["BEV_SRC_BL_X"])),
        "BEV_SRC_BL_Y": float(getattr(conf, "BEV_SRC_BL_Y", ADVANCED_VARS["BEV_SRC_BL_Y"]))
    }
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
                    val = max(0.0, min(1.0, val))
                    setattr(conf, var, val)
                    updated[var] = val
                except:
                    pass
        if updated:
            save_conf_to_json()
        return jsonify(success=True, values={var: float(getattr(conf, var, 0.0)) for var in VARIABLES})
    except:
        return jsonify(success=False)

@app.route('/get_values')
def get_values():
    return jsonify(values={var: float(getattr(conf, var, 0.0)) for var in VARIABLES})

@app.route('/get_advanced')
def get_advanced():
    return jsonify(advanced={
        "LANE_THRESHOLD": int(getattr(conf, "LANE_THRESHOLD", ADVANCED_VARS["LANE_THRESHOLD"])),
        "CROSSWALK_THRESHOLD": int(getattr(conf, "CROSSWALK_THRESHOLD", ADVANCED_VARS["CROSSWALK_THRESHOLD"])),
        "RUN_LVL": getattr(conf, "RUN_LVL", ADVANCED_VARS["RUN_LVL"]),
        "WITH_SIGN": bool(getattr(conf, "WITH_SIGN", ADVANCED_VARS["WITH_SIGN"])),
        "WITH_APRILTAG": bool(getattr(conf, "WITH_APRILTAG", ADVANCED_VARS["WITH_APRILTAG"])),
        "LANE_ROI_MODE": str(getattr(conf, "LANE_ROI_MODE", ADVANCED_VARS["LANE_ROI_MODE"])),
        "CW_TRAPEZOID_MODE": bool(getattr(conf, "CW_TRAPEZOID_MODE", ADVANCED_VARS["CW_TRAPEZOID_MODE"])),
        "RL_TOP_WIDTH_FACTOR": float(getattr(conf, "RL_TOP_WIDTH_FACTOR", ADVANCED_VARS["RL_TOP_WIDTH_FACTOR"])),
        "LL_TOP_WIDTH_FACTOR": float(getattr(conf, "LL_TOP_WIDTH_FACTOR", ADVANCED_VARS["LL_TOP_WIDTH_FACTOR"])),
        "CW_TOP_WIDTH_FACTOR": float(getattr(conf, "CW_TOP_WIDTH_FACTOR", ADVANCED_VARS["CW_TOP_WIDTH_FACTOR"])),
        
        "USE_BEV": bool(getattr(conf, "USE_BEV", ADVANCED_VARS["USE_BEV"])),
        "BEV_SRC_TL_X": float(getattr(conf, "BEV_SRC_TL_X", ADVANCED_VARS["BEV_SRC_TL_X"])),
        "BEV_SRC_TL_Y": float(getattr(conf, "BEV_SRC_TL_Y", ADVANCED_VARS["BEV_SRC_TL_Y"])),
        "BEV_SRC_TR_X": float(getattr(conf, "BEV_SRC_TR_X", ADVANCED_VARS["BEV_SRC_TR_X"])),
        "BEV_SRC_TR_Y": float(getattr(conf, "BEV_SRC_TR_Y", ADVANCED_VARS["BEV_SRC_TR_Y"])),
        "BEV_SRC_BR_X": float(getattr(conf, "BEV_SRC_BR_X", ADVANCED_VARS["BEV_SRC_BR_X"])),
        "BEV_SRC_BR_Y": float(getattr(conf, "BEV_SRC_BR_Y", ADVANCED_VARS["BEV_SRC_BR_Y"])),
        "BEV_SRC_BL_X": float(getattr(conf, "BEV_SRC_BL_X", ADVANCED_VARS["BEV_SRC_BL_X"])),
        "BEV_SRC_BL_Y": float(getattr(conf, "BEV_SRC_BL_Y", ADVANCED_VARS["BEV_SRC_BL_Y"]))
    })

@app.route('/set_advanced', methods=['POST'])
def set_advanced():
    data = request.get_json() or {}
    try:
        if "LANE_THRESHOLD" in data: setattr(conf, "LANE_THRESHOLD", max(0, min(255, int(data["LANE_THRESHOLD"]))))
        if "CROSSWALK_THRESHOLD" in data: setattr(conf, "CROSSWALK_THRESHOLD", max(0, min(255, int(data["CROSSWALK_THRESHOLD"]))))
        if "RUN_LVL" in data: setattr(conf, "RUN_LVL", data["RUN_LVL"] if data["RUN_LVL"] in ("MOVE","STOP") else "MOVE")
        
        if "WITH_SIGN" in data or "WITH_APRILTAG" in data:
            use_sign = bool(data.get("WITH_SIGN", getattr(conf, "WITH_SIGN", True)))
            setattr(conf, "WITH_SIGN", use_sign)
            setattr(conf, "WITH_APRILTAG", not use_sign)
            
        # Shape Config handling
        if "LANE_ROI_MODE" in data: setattr(conf, "LANE_ROI_MODE", str(data["LANE_ROI_MODE"]))
        if "CW_TRAPEZOID_MODE" in data: setattr(conf, "CW_TRAPEZOID_MODE", bool(data["CW_TRAPEZOID_MODE"]))
        if "RL_TOP_WIDTH_FACTOR" in data: setattr(conf, "RL_TOP_WIDTH_FACTOR", float(data["RL_TOP_WIDTH_FACTOR"]))
        if "LL_TOP_WIDTH_FACTOR" in data: setattr(conf, "LL_TOP_WIDTH_FACTOR", float(data["LL_TOP_WIDTH_FACTOR"]))
        if "CW_TOP_WIDTH_FACTOR" in data: setattr(conf, "CW_TOP_WIDTH_FACTOR", float(data["CW_TOP_WIDTH_FACTOR"]))
        
        # BEV Config handling
        if "USE_BEV" in data: setattr(conf, "USE_BEV", bool(data["USE_BEV"]))
        for bev_key in ["BEV_SRC_TL_X", "BEV_SRC_TL_Y", "BEV_SRC_TR_X", "BEV_SRC_TR_Y", "BEV_SRC_BR_X", "BEV_SRC_BR_Y", "BEV_SRC_BL_X", "BEV_SRC_BL_Y"]:
            if bev_key in data:
                setattr(conf, bev_key, max(0.0, min(1.0, float(data[bev_key]))))
        
    except Exception as e:
        logger.exception("Invalid advanced payload")
        return jsonify(success=False), 400
        
    save_conf_to_json()
    # fetch updated states
    return jsonify(success=True, advanced=get_advanced().get_json()['advanced'])

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