import logging
import cv2
import json
import os
from flask import Flask, Response, request, render_template_string, jsonify
from .template import HTML_TEMPLATE

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
        return f"{mode}_ui.json"

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
        return f"{mode}.json"

    def save_conf_to_json(self):
        filename = self.config_filename()
        data = {var: self.get_base_var(var) for var in VARIABLES}
        data.update(self.get_all_advanced())
        try:
            print(filename)
            with open(filename, "w") as f:
                print(data)
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
        self.app.add_url_rule('/take_picture', 'take_picture', self.take_picture, methods=['POST'])
        self.app.add_url_rule('/toggle_record', 'toggle_record', self.toggle_record, methods=['POST'])
        self.app.add_url_rule('/freeze_frame', 'freeze_frame', self.freeze_frame, methods=['POST'])
        self.app.add_url_rule('/unfreeze_frame', 'unfreeze_frame', self.unfreeze_frame, methods=['POST'])
        self.app.add_url_rule('/shutdown', 'shutdown', self.shutdown, methods=['POST'])

    def index(self):
        values = {var: self.get_base_var(var) for var in VARIABLES}
        advanced_current = self.get_all_advanced()
        return render_template_string(HTML_TEMPLATE, variables=VARIABLES, values=values, 
                                      ui=self.ui_settings, advanced=advanced_current, 
                                      mode=getattr(self.config, "MODE", "mode"))

    def update_conf(self):
        try:
            data = request.get_json() or request.form.to_dict()
            updated = {}
            for var in VARIABLES:
                if var in data:
                    try:
                        val = float(data[var])
                        val = max(0.0, min(1.0, val))
                        setattr(self.config, var, val)
                        updated[var] = val
                    except:
                        pass
            if updated:
                self.save_conf_to_json()
            return jsonify(success=True, values={var: self.get_base_var(var) for var in VARIABLES})
        except:
            return jsonify(success=False)

    def get_values(self):
        return jsonify(values={var: self.get_base_var(var) for var in VARIABLES})

    def get_advanced(self):
        return jsonify(advanced=self.get_all_advanced())

    def set_advanced(self):
        data = request.get_json() or {}
        try:
            for k, default_v in ADVANCED_VARS.items():
                if k in data:
                    val = data[k]
                    if k in ("LANE_THRESHOLD", "CROSSWALK_THRESHOLD"): 
                        val = max(0, min(255, int(val)))
                    elif k.startswith("BEV_SRC_"): 
                        val = max(-5.0, min(5.0, float(val)))
                    
                    expected_type = type(default_v)
                    if expected_type == bool: val = bool(val)
                    elif expected_type == int: val = int(val)
                    elif expected_type == float: val = float(val)
                    else: val = str(val)
                    
                    setattr(self.config, k, val)

            if "RUN_LVL" in data: 
                setattr(self.config, "RUN_LVL", data["RUN_LVL"] if data["RUN_LVL"] in ("MOVE","STOP") else "MOVE")
                
            if "WITH_SIGN" in data or "WITH_APRILTAG" in data:
                use_sign = bool(data.get("WITH_SIGN", getattr(self.config, "WITH_SIGN", True)))
                setattr(self.config, "WITH_SIGN", use_sign)
                setattr(self.config, "WITH_APRILTAG", not use_sign)
            
        except Exception as e:
            logger.exception("Invalid advanced payload")
            return jsonify(success=False), 400
            
        self.save_conf_to_json()
        return jsonify(success=True, advanced=self.get_all_advanced())

    def get_ui(self): 
        return jsonify(ui=self.ui_settings)

    def set_ui(self):
        data = request.get_json() or {}
        if "colors" in data: 
            self.ui_settings["colors"].update({k:v for k,v in data["colors"].items() if k in self.ui_settings["colors"]})
        if "visible" in data: 
            self.ui_settings["visible"].update({k:bool(v) for k,v in data["visible"].items() if k in self.ui_settings["visible"]})
        self.save_ui_settings()
        return jsonify(success=True, ui=self.ui_settings)

    def video_feed_frame(self):
        frozen = getattr(self.config, "frozen_debug_frame", None)
        if frozen is not None: 
            frame = frozen
        else:
            frames_list = getattr(self.config, "debug_frames_list", [])
            frame = frames_list[-1] if frames_list else None
        
        if frame is None: 
            return Response('', status=204)
        ret, buffer = cv2.imencode('.jpg', frame)
        if not ret: 
            return Response('', status=204)
        return Response(buffer.tobytes(), mimetype='image/jpeg')

    def take_picture(self):
        setattr(self.config, "TAKE_PICTURE", True)
        return jsonify(success=True)

    def toggle_record(self):
        current = getattr(self.config, "RECORD_VIDEO", False)
        new_val = not current
        setattr(self.config, "RECORD_VIDEO", new_val)
        self.save_conf_to_json()
        return jsonify(success=True, recording=new_val)

    def freeze_frame(self):
        frames_list = getattr(self.config, "debug_frames_list", [])
        if frames_list:
            setattr(self.config, "frozen_debug_frame", frames_list[-1].copy())
            return jsonify(success=True)
        return jsonify(success=False, message="No frame available")

    def unfreeze_frame(self):
        if hasattr(self.config, "frozen_debug_frame"): 
            delattr(self.config, "frozen_debug_frame")
        return jsonify(success=True)

    def shutdown(self): 
        os._exit(0)


def start_stream(config):

    streamer = WebStreamer(config)
    streamer.app.run(host='0.0.0.0', port=5000, threaded=True, debug=False)