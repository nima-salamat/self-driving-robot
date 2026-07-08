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

# --- Advanced variables (Including new Trapezoid Settings) ---
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
    "CW_TOP_WIDTH_FACTOR": 0.6
}

# UI settings filename and functions
def ui_filename():
    mode = getattr(temp_conf, "MODE", "mode")
    return f"{mode}_ui.json"

def load_ui_settings():
    fname = ui_filename()
    if os.path.exists(fname):
        try:
            with open(fname, "r") as f:
                data = json.load(f)
                return {
                    "colors": data.get("colors", {"RL":"#ff7b7b","LL":"#7bffb8","CW":"#ffd27b"}),
                    "visible": data.get("visible", {"RL":True,"LL":True,"CW":True})
                }
        except Exception:
            logger.exception("Failed load UI settings")
    return {"colors":{"RL":"#ff7b7b","LL":"#7bffb8","CW":"#ffd27b"},"visible":{"RL":True,"LL":True,"CW":True}}

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
        
        # New Shape variables
        "LANE_ROI_MODE": str(getattr(conf, "LANE_ROI_MODE", ADVANCED_VARS["LANE_ROI_MODE"])),
        "CW_TRAPEZOID_MODE": bool(getattr(conf, "CW_TRAPEZOID_MODE", ADVANCED_VARS["CW_TRAPEZOID_MODE"])),
        "RL_TOP_WIDTH_FACTOR": float(getattr(conf, "RL_TOP_WIDTH_FACTOR", ADVANCED_VARS["RL_TOP_WIDTH_FACTOR"])),
        "LL_TOP_WIDTH_FACTOR": float(getattr(conf, "LL_TOP_WIDTH_FACTOR", ADVANCED_VARS["LL_TOP_WIDTH_FACTOR"])),
        "CW_TOP_WIDTH_FACTOR": float(getattr(conf, "CW_TOP_WIDTH_FACTOR", ADVANCED_VARS["CW_TOP_WIDTH_FACTOR"]))
    })
    try:
        with open(filename, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        logger.exception("Failed writing config JSON")


# --- HTML template ---
HTML_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Interactive ROI & Settings</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{
  --bg:#071426; --card:#0b1220; --accent:#06b6d4; --muted:#94a3b8; --txt:#e6eef6;
}
*{box-sizing:border-box}
body{margin:0;font-family:Inter,Segoe UI,Roboto,Arial;background:linear-gradient(180deg,#071026 0%, #07142a 100%);color:var(--txt);padding:18px}
.container{max-width:1250px;margin:0 auto;display:grid;grid-template-columns: 1fr 460px;gap:18px;align-items:start}
.card{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.03);padding:14px;border-radius:10px;box-shadow: 0 6px 24px rgba(2,6,23,0.6)}
.header{display:flex;align-items:center;gap:12px;margin-bottom:8px}
.h1{font-size:18px;font-weight:600}
.controls{display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap}
select,input[type=number],input[type=color],input[type=checkbox],input[type=range]{background:#071428;color:var(--txt);border:1px solid rgba(255,255,255,0.04);padding:6px 8px;border-radius:6px}
input[type=range]{accent-color: var(--accent);}
button.btn{background:var(--accent);color:#012; border:none;padding:8px 12px;border-radius:8px;cursor:pointer;font-weight:600}
button.ghost{background:transparent;border:1px solid rgba(255,255,255,0.06);color:var(--txt);padding:7px 10px;border-radius:8px;cursor:pointer}
canvas{width:100%;height:auto;border-radius:8px;display:block;background:#000}
.label{width:160px;color:var(--muted);font-size:13px}
.small{font-size:13px;color:var(--muted)}
.right-panel{display:flex;flex-direction:column;gap:12px}
.inputs{max-height:220px;overflow:auto;padding-right:6px}
.input-wrap{display:flex;align-items:center;gap:8px;margin-bottom:6px}
.counter{min-width:72px;text-align:center}
.section-title{font-weight:700;margin-bottom:10px;font-size:15px; color:var(--accent);}
.toggle-row{display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap}
.notice{background:rgba(255,255,255,0.02);padding:8px;border-radius:8px;color:var(--muted);font-size:13px}
.toast{position:fixed;right:20px;bottom:20px;background:#0b1220;border:1px solid rgba(255,255,255,0.06);padding:10px 14px;border-radius:8px;color:var(--txt);box-shadow:0 8px 30px rgba(2,6,23,0.6); z-index: 9999;}
.form-row{display:flex;gap:8px;align-items:center;margin:6px 0;flex-wrap:wrap}
.small-muted{font-size:12px;color:var(--muted)}
.status-line{margin-top:4px;font-size:13px;color:var(--accent)}
</style>
</head>
<body>
<div class="container">
  <div class="card">
    <div class="header">
      <div class="h1">Interactive ROI Editor</div>
      <div class="small">Drag to move/resize bounding boxes. Use sliders for Trapezoid shapes.</div>
    </div>
    <div class="controls">
      <label class="small" for="variable_select">Select Area</label>
      <select id="variable_select">
        <option value="NONE">-- NONE --</option>
        {% for var in variables %}
          <option value="{{ var }}">{{ var }}</option>
        {% endfor %}
      </select>
      <button id="clear_selection" class="ghost">Clear</button>
      <button id="center_reset" class="ghost">Center Base</button>
      <div style="flex:1"></div>
      <label class="small" style="color:var(--accent); font-weight:bold;">Show ROIs <input id="show_rects" type="checkbox" checked></label>
      <div id="frame_mode" class="small status-line">Mode: Live</div>
    </div>
    <canvas id="video_canvas" width="900" height="600"></canvas>
    <div style="margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <button id="apply_all" class="btn">Apply Base Settings</button>
      <button id="refresh_vals" class="ghost">Refresh Feed</button>
      <button id="download_json" class="ghost">Download JSON</button>
      <div style="flex:1"></div>
      <div class="small">Tip: Freeze frame to tune angles accurately</div>
    </div>
  </div>

  <div class="right-panel">
  
    <div class="card">
      <div class="section-title">ROI Shape & Factors</div>
      
      <div class="form-row">
        <label class="label">Lane Shape Mode</label>
        <select id="lane_roi_mode" style="width: 140px;">
          <option value="rectangle">Rectangle</option>
          <option value="trapezoid">Trapezoid</option>
        </select>
      </div>
      
      <div class="form-row">
        <label class="label">Right Lane Top factor</label>
        <input id="rl_factor" type="range" min="0.0" max="1.0" step="0.02" style="width: 100px;">
        <span id="rl_factor_val" class="small" style="width:30px;"></span>
      </div>
      
      <div class="form-row">
        <label class="label">Left Lane Top factor</label>
        <input id="ll_factor" type="range" min="0.0" max="1.0" step="0.02" style="width: 100px;">
        <span id="ll_factor_val" class="small" style="width:30px;"></span>
      </div>
      
      <hr style="border-color: rgba(255,255,255,0.05); margin: 8px 0;">
      
      <div class="form-row">
        <label class="label">Crosswalk Trapezoid</label>
        <input type="checkbox" id="cw_trap_mode">
      </div>
      
      <div class="form-row">
        <label class="label">CW Top Factor</label>
        <input id="cw_factor" type="range" min="0.0" max="1.0" step="0.02" style="width: 100px;">
        <span id="cw_factor_val" class="small" style="width:30px;"></span>
      </div>

      <div style="margin-top:10px">
         <button id="confirm_shape" class="btn">Save Shapes to System</button>
      </div>
    </div>

    <div class="card">
      <div class="section-title">Bounding Box Adjustments</div>
      <div class="inputs" id="inputs_container">
        {% for var in variables %}
        <div class="input-wrap">
          <div class="label">{{ var }}</div>
          <input name="{{ var }}" type="number" step="0.01" min="0" max="1" class="counter" value="{{ '%.2f' % values[var] }}">
          <button type="button" class="ghost btn-inc" data-var="{{ var }}" data-delta="0.05">+0.05</button>
          <button type="button" class="ghost btn-inc" data-var="{{ var }}" data-delta="-0.05">-0.05</button>
        </div>
        {% endfor %}
      </div>
    </div>

    <div class="card" style="display:none;"> <div class="section-title">ROI Colors</div>
      <div class="toggle-row"><label><input type="checkbox" id="vis_rl" checked> Right Lane</label><input type="color" id="color_rl" value="{{ ui.colors.RL }}"></div>
      <div class="toggle-row"><label><input type="checkbox" id="vis_ll" checked> Left Lane</label><input type="color" id="color_ll" value="{{ ui.colors.LL }}"></div>
      <div class="toggle-row"><label><input type="checkbox" id="vis_cw" checked> Crosswalk</label><input type="color" id="color_cw" value="{{ ui.colors.CW }}"></div>
    </div>

    <div class="card">
      <div class="section-title">Stream Controls</div>
      <div class="form-row">
        <button id="take_picture_btn" class="btn">Take Picture</button>
        <button id="toggle_record_btn" class="btn">Start Recording</button>
        <div id="record_status" class="small-muted status-line" style="margin-left: 10px;">Recording: No</div>
      </div>
      <div class="form-row">
        <button id="freeze_btn" class="ghost">Freeze Frame</button>
        <button id="unfreeze_btn" class="ghost">Unfreeze Frame</button>
      </div>
    </div>

    <div class="card">
      <div class="section-title">Vision Advanced Limits</div>
      <div class="form-row"><label class="label">LANE_THRESHOLD</label><input id="lane_threshold" type="number" min="0" max="255" step="1"></div>
      <div class="form-row"><label class="label">CW_THRESHOLD</label><input id="cross_thresh" type="number" min="0" max="255" step="1"></div>
      <div class="form-row"><label class="label">RUN_LVL</label>
        <select id="run_lvl">
          <option value="MOVE">MOVE</option>
          <option value="STOP">STOP</option>
        </select>
      </div>
      <div class="form-row"><label class="label">Use Signs Vision</label><input type="checkbox" id="with_sign"></div>
      <div class="form-row"><label class="label">Use AprilTag</label><input type="checkbox" id="with_apriltag"></div>
      
      <div style="display:flex;gap:8px;margin-top:12px">
        <button id="confirm_advanced" class="btn">Confirm Advanced</button>
        <button id="cancel_advanced" class="ghost">Cancel</button>
        <div id="advanced_msg" class="small-muted"></div>
      </div>
    </div>

  </div>
</div>

<div id="toast" class="toast" style="display:none"></div>

<script>
/* ---------- Globals ---------- */
const canvas = document.getElementById('video_canvas');
const ctx = canvas.getContext('2d');
const select = document.getElementById('variable_select');
const inputsContainer = document.getElementById('inputs_container');
const showRectsCheckbox = document.getElementById('show_rects');
const frameModeDisplay = document.getElementById('frame_mode');

let values = {{ values|tojson }};
let ui = {{ ui|tojson }};
let advanced = {{ advanced|tojson }};

let selectedVar = 'NONE';
let markerHighlight = null;
let fetchFrameTimer = null;
let dragState = null;
let debounceTimers = {};
let isFrozen = false;
let isRecording = false;

/* ---------- Utilities ---------- */
function clamp01(v){ return Math.max(0, Math.min(1, v)); }
function round01(v){ return Math.round(v*100)/100; }
function showToast(text, timeout=2500){
    const t = document.getElementById('toast');
    t.textContent = text;
    t.style.display = 'block';
    setTimeout(()=> t.style.display='none', timeout);
}
function varColorByKey(key){
  if(key==='RL') return ui.colors.RL;
  if(key==='LL') return ui.colors.LL;
  if(key==='CW') return ui.colors.CW;
  return '#9ad0ff';
}
function updateFrameModeText(){
    frameModeDisplay.textContent = isFrozen ? 'Mode: Frozen (for precise tuning)' : 'Mode: Live';
}

/* ---------- Canvas frame loop ---------- */
function rectFromVars(topVar, bottomVar, leftVar, rightVar, width, height){
    const t = parseFloat(values[topVar]); const b = parseFloat(values[bottomVar]);
    const l = parseFloat(values[leftVar]); const r = parseFloat(values[rightVar]);
    if (isNaN(t)||isNaN(b)||isNaN(l)||isNaN(r)) return null;
    return {x: l*width, y: t*height, w: Math.max(2,(r-l)*width), h: Math.max(2,(b-t)*height), t, b, l, r};
}
function computeRects(){
    const w = canvas.width, h = canvas.height;
    return {
        RL: rectFromVars('RL_TOP_ROI','RL_BOTTOM_ROI','RL_LEFT_ROI','RL_RIGHT_ROI', w, h),
        LL: rectFromVars('LL_TOP_ROI','LL_BOTTOM_ROI','LL_LEFT_ROI','LL_RIGHT_ROI', w, h),
        CW: rectFromVars('CW_TOP_ROI','CW_BOTTOM_ROI','CW_LEFT_ROI','CW_RIGHT_ROI', w, h)
    };
}
function startFrameLoop(){
    if(fetchFrameTimer) clearInterval(fetchFrameTimer);
    fetchFrameTimer = setInterval(fetchFrameOnce, 120);
}
startFrameLoop();

function fetchFrameOnce(){
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.src = '/video_feed_frame?t=' + Date.now();
    img.onload = () => {
        const rect = canvas.getBoundingClientRect();
        const dispW = Math.floor(rect.width);
        const dispH = Math.floor(rect.height);
        if (canvas.width !== dispW || canvas.height !== dispH) {
            canvas.width = dispW; canvas.height = dispH;
        }
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        drawOverlays();
    };
    img.onerror = () => {
        ctx.clearRect(0,0,canvas.width,canvas.height);
        drawOverlays();
    };
}

/* ---------- Overlays (Shapes & Rects) ---------- */
function drawHandle(cx, cy, size, fill, stroke){
    ctx.beginPath();
    ctx.fillStyle = fill;
    ctx.strokeStyle = stroke || '#000';
    ctx.lineWidth = 1;
    ctx.rect(cx - size/2, cy - size/2, size, size);
    ctx.fill(); ctx.stroke();
}

function drawPolygon(points, color, isHighlight, labelText, r) {
    ctx.beginPath();
    ctx.moveTo(points[0].x, points[0].y);
    for(let i=1; i<points.length; i++){
        ctx.lineTo(points[i].x, points[i].y);
    }
    ctx.closePath();
    
    // Fill shape
    ctx.fillStyle = color;
    ctx.globalAlpha = 0.35;
    ctx.fill();
    
    // Stroke shape
    ctx.globalAlpha = 1;
    ctx.strokeStyle = isHighlight ? '#ffffff' : color;
    ctx.lineWidth = isHighlight ? 3 : 2;
    ctx.stroke();

    // Label tag
    ctx.fillStyle = color;
    ctx.fillRect(r.x + 6, r.y + 6, 120, 18);
    ctx.fillStyle = '#012';
    ctx.font = 'bold 12px Arial';
    ctx.fillText(labelText, r.x + 10, r.y + 19);
}

function drawOverlays(){
    const showRects = showRectsCheckbox.checked;
    const rects = computeRects();
    ctx.save();
    
    if(showRects){
        // Read shape configs
        const laneMode = advanced.LANE_ROI_MODE || 'rectangle';
        const cwMode = advanced.CW_TRAPEZOID_MODE !== false; // true by default
        
        for(const key of ['RL','LL','CW']){
            if(!ui.visible[key]) continue;
            const r = rects[key];
            if(!r) continue;
            
            const color = varColorByKey(key);
            const isHL = (markerHighlight === key);
            
            // Draw Main Shape based on Geometry
            if(key === 'RL') {
                if(laneMode === 'trapezoid'){
                    let factor = advanced.RL_TOP_WIDTH_FACTOR;
                    let pts = [
                        {x: r.x, y: r.y},                                    // Top-Left (straight)
                        {x: r.x + (r.w * factor), y: r.y},                   // Top-Right (slanted)
                        {x: r.x + r.w, y: r.y + r.h},                        // Bottom-Right
                        {x: r.x, y: r.y + r.h}                               // Bottom-Left
                    ];
                    drawPolygon(pts, color, isHL, "RL (Trapezoid)", r);
                } else {
                    let pts = [{x:r.x,y:r.y}, {x:r.x+r.w,y:r.y}, {x:r.x+r.w,y:r.y+r.h}, {x:r.x,y:r.y+r.h}];
                    drawPolygon(pts, color, isHL, "RL (Rectangle)", r);
                }
            } 
            else if(key === 'LL') {
                if(laneMode === 'trapezoid'){
                    let factor = advanced.LL_TOP_WIDTH_FACTOR;
                    let pts = [
                        {x: (r.x + r.w) - (r.w * factor), y: r.y},           // Top-Left (slanted)
                        {x: r.x + r.w, y: r.y},                              // Top-Right (straight)
                        {x: r.x + r.w, y: r.y + r.h},                        // Bottom-Right
                        {x: r.x, y: r.y + r.h}                               // Bottom-Left
                    ];
                    drawPolygon(pts, color, isHL, "LL (Trapezoid)", r);
                } else {
                    let pts = [{x:r.x,y:r.y}, {x:r.x+r.w,y:r.y}, {x:r.x+r.w,y:r.y+r.h}, {x:r.x,y:r.y+r.h}];
                    drawPolygon(pts, color, isHL, "LL (Rectangle)", r);
                }
            }
            else if(key === 'CW') {
                if(cwMode){
                    let factor = advanced.CW_TOP_WIDTH_FACTOR;
                    let pts = [
                        {x: r.x + (r.w * (1 - factor) / 2), y: r.y},         // Top-Left
                        {x: r.x + (r.w * (1 + factor) / 2), y: r.y},         // Top-Right
                        {x: r.x + r.w, y: r.y + r.h},                        // Bottom-Right
                        {x: r.x, y: r.y + r.h}                               // Bottom-Left
                    ];
                    drawPolygon(pts, color, isHL, "CW (Isosceles)", r);
                } else {
                    let pts = [{x:r.x,y:r.y}, {x:r.x+r.w,y:r.y}, {x:r.x+r.w,y:r.y+r.h}, {x:r.x,y:r.y+r.h}];
                    drawPolygon(pts, color, isHL, "CW (Rectangle)", r);
                }
            }
            
            // Bounding Box handles and thin stroke (Container)
            ctx.globalAlpha = 1.0;
            ctx.strokeStyle = 'rgba(255,255,255,0.3)';
            ctx.lineWidth = 1;
            ctx.setLineDash([4, 4]);
            ctx.strokeRect(r.x, r.y, r.w, r.h);
            ctx.setLineDash([]);
            
            // Draw Resize Handles (Always on Bounding Box corners)
            const size = 10;
            drawHandle(r.x, r.y, size, '#fff', color);
            drawHandle(r.x + r.w, r.y, size, '#fff', color);
            drawHandle(r.x, r.y + r.h, size, '#fff', color);
            drawHandle(r.x + r.w, r.y + r.h, size, '#fff', color);
        }
    }
    ctx.restore();
}

/* ---------- Hit testing & Drag Bounding Box ---------- */
function hitTest(px, py){
    const rects = computeRects();
    for(const key of ['RL','LL','CW']){
        if(!ui.visible[key]) continue;
        const r = rects[key];
        if(!r) continue;
        const size = 12;
        const corners = {nw:{x:r.x,y:r.y}, ne:{x:r.x+r.w,y:r.y}, sw:{x:r.x,y:r.y+r.h}, se:{x:r.x+r.w,y:r.y+r.h}};
        for(const c of Object.keys(corners)){
            const {x:cx,y:cy} = corners[c];
            if(px >= cx-size && px <= cx+size && py >= cy-size && py <= cy+size){
                return {type:'handle', group:key, corner:c, rect:r};
            }
        }
        if(px >= r.x && px <= r.x+r.w && py >= r.y && py <= r.y+r.h){
            return {type:'inside', group:key, rect:r};
        }
    }
    return {type:'none'};
}
canvas.addEventListener('mousedown', e=>{
    const rectB = canvas.getBoundingClientRect();
    const px = e.clientX - rectB.left;
    const py = e.clientY - rectB.top;
    const hit = hitTest(px, py);
    if(hit.type==='handle'){
        dragState = {type:'resize', group:hit.group, corner:hit.corner, origRect:hit.rect, start:{x:px,y:py}};
        markerHighlight = hit.group;
        selectedVar = mapGroupToDefaultVar(hit.group);
        select.value = selectedVar;
    } else if(hit.type==='inside'){
        dragState = {type:'move', group:hit.group, origRect:hit.rect, start:{x:px,y:py}};
        markerHighlight = hit.group;
        selectedVar = mapGroupToDefaultVar(hit.group);
        select.value = selectedVar;
    } else {
        dragState = null;
    }
});
canvas.addEventListener('mousemove', e=>{
    const rectB = canvas.getBoundingClientRect();
    const px = e.clientX - rectB.left;
    const py = e.clientY - rectB.top;
    const hover = hitTest(px, py);
    if(dragState){
        canvas.style.cursor = dragState.type==='move' ? 'grabbing' : 'nwse-resize';
    } else if(hover.type==='handle'){
        canvas.style.cursor = 'nwse-resize';
    } else if(hover.type==='inside'){
        canvas.style.cursor = 'move';
    } else {
        canvas.style.cursor = 'default';
    }
    if(!dragState) return;
    const dx = px - dragState.start.x;
    const dy = py - dragState.start.y;
    const w = canvas.width, h = canvas.height;
    const group = dragState.group;
    let topVar, bottomVar, leftVar, rightVar;
    if(group==='RL'){ topVar='RL_TOP_ROI'; bottomVar='RL_BOTTOM_ROI'; leftVar='RL_LEFT_ROI'; rightVar='RL_RIGHT_ROI'; }
    else if(group==='LL'){ topVar='LL_TOP_ROI'; bottomVar='LL_BOTTOM_ROI'; leftVar='LL_LEFT_ROI'; rightVar='LL_RIGHT_ROI'; }
    else { topVar='CW_TOP_ROI'; bottomVar='CW_BOTTOM_ROI'; leftVar='CW_LEFT_ROI'; rightVar='CW_RIGHT_ROI'; }
    const orig = dragState.origRect;
    let nx_t = orig.t, nx_b = orig.b, nx_l = orig.l, nx_r = orig.r;
    
    if(dragState.type==='move'){
        const dnx = dx/w, dny = dy/h;
        nx_t = clamp01(orig.t + dny); nx_b = clamp01(orig.b + dny);
        nx_l = clamp01(orig.l + dnx); nx_r = clamp01(orig.r + dnx);
        if(nx_r - nx_l < 0.02){ const mid = (nx_l + nx_r)/2; nx_l = mid - 0.01; nx_r = mid + 0.01; }
        if(nx_b - nx_t < 0.02){ const mid = (nx_t + nx_b)/2; nx_t = mid - 0.01; nx_b = mid + 0.01; }
    } else {
        const dnx = dx/w, dny = dy/h;
        if(dragState.corner==='nw'){ nx_t = clamp01(orig.t + dny); nx_l = clamp01(orig.l + dnx); }
        if(dragState.corner==='ne'){ nx_t = clamp01(orig.t + dny); nx_r = clamp01(orig.r + dnx); }
        if(dragState.corner==='sw'){ nx_b = clamp01(orig.b + dny); nx_l = clamp01(orig.l + dnx); }
        if(dragState.corner==='se'){ nx_b = clamp01(orig.b + dny); nx_r = clamp01(orig.r + dnx); }
        if(nx_b <= nx_t) nx_b = nx_t + 0.01;
        if(nx_r <= nx_l) nx_r = nx_l + 0.01;
    }
    values[topVar] = round01(nx_t); values[bottomVar] = round01(nx_b);
    values[leftVar] = round01(nx_l); values[rightVar] = round01(nx_r);
    updateInputsFromValues(); 
    drawOverlays();
    
    if(debounceTimers[group]) clearTimeout(debounceTimers[group]);
    debounceTimers[group] = setTimeout(()=>{
        sendUpdate({[topVar]:values[topVar], [bottomVar]:values[bottomVar], [leftVar]:values[leftVar], [rightVar]:values[rightVar]});
    }, 220);
});
window.addEventListener('mouseup', ()=>{
    if(!dragState) return;
    const group = dragState.group;
    let topVar, bottomVar, leftVar, rightVar;
    if(group==='RL'){ topVar='RL_TOP_ROI'; bottomVar='RL_BOTTOM_ROI'; leftVar='RL_LEFT_ROI'; rightVar='RL_RIGHT_ROI'; }
    else if(group==='LL'){ topVar='LL_TOP_ROI'; bottomVar='LL_BOTTOM_ROI'; leftVar='LL_LEFT_ROI'; rightVar='LL_RIGHT_ROI'; }
    else { topVar='CW_TOP_ROI'; bottomVar='CW_BOTTOM_ROI'; leftVar='CW_LEFT_ROI'; rightVar='CW_RIGHT_ROI'; }
    sendUpdate({[topVar]:values[topVar], [bottomVar]:values[bottomVar], [leftVar]:values[leftVar], [rightVar]:values[rightVar]});
    dragState = null;
    canvas.style.cursor = 'default';
});

/* ---------- Shape Settings logic (Trapezoid UI sync) ---------- */
const shapeInputs = {
    lane_mode: document.getElementById('lane_roi_mode'),
    rl_factor: document.getElementById('rl_factor'),
    ll_factor: document.getElementById('ll_factor'),
    cw_trap_mode: document.getElementById('cw_trap_mode'),
    cw_factor: document.getElementById('cw_factor'),
    rl_val: document.getElementById('rl_factor_val'),
    ll_val: document.getElementById('ll_factor_val'),
    cw_val: document.getElementById('cw_factor_val')
};

function updateShapeUIFromData() {
    shapeInputs.lane_mode.value = advanced.LANE_ROI_MODE || 'rectangle';
    shapeInputs.rl_factor.value = advanced.RL_TOP_WIDTH_FACTOR;
    shapeInputs.ll_factor.value = advanced.LL_TOP_WIDTH_FACTOR;
    shapeInputs.cw_trap_mode.checked = advanced.CW_TRAPEZOID_MODE;
    shapeInputs.cw_factor.value = advanced.CW_TOP_WIDTH_FACTOR;
    
    shapeInputs.rl_val.textContent = parseFloat(advanced.RL_TOP_WIDTH_FACTOR).toFixed(2);
    shapeInputs.ll_val.textContent = parseFloat(advanced.LL_TOP_WIDTH_FACTOR).toFixed(2);
    shapeInputs.cw_val.textContent = parseFloat(advanced.CW_TOP_WIDTH_FACTOR).toFixed(2);
    drawOverlays();
}

function handleShapeSlider() {
    advanced.LANE_ROI_MODE = shapeInputs.lane_mode.value;
    advanced.RL_TOP_WIDTH_FACTOR = parseFloat(shapeInputs.rl_factor.value);
    advanced.LL_TOP_WIDTH_FACTOR = parseFloat(shapeInputs.ll_factor.value);
    advanced.CW_TRAPEZOID_MODE = shapeInputs.cw_trap_mode.checked;
    advanced.CW_TOP_WIDTH_FACTOR = parseFloat(shapeInputs.cw_factor.value);
    
    shapeInputs.rl_val.textContent = advanced.RL_TOP_WIDTH_FACTOR.toFixed(2);
    shapeInputs.ll_val.textContent = advanced.LL_TOP_WIDTH_FACTOR.toFixed(2);
    shapeInputs.cw_val.textContent = advanced.CW_TOP_WIDTH_FACTOR.toFixed(2);
    drawOverlays();
}

['input', 'change'].forEach(evt => {
    shapeInputs.lane_mode.addEventListener(evt, handleShapeSlider);
    shapeInputs.rl_factor.addEventListener(evt, handleShapeSlider);
    shapeInputs.ll_factor.addEventListener(evt, handleShapeSlider);
    shapeInputs.cw_trap_mode.addEventListener(evt, handleShapeSlider);
    shapeInputs.cw_factor.addEventListener(evt, handleShapeSlider);
});

document.getElementById('confirm_shape').addEventListener('click', ()=>{
    const payload = {
        LANE_ROI_MODE: advanced.LANE_ROI_MODE,
        RL_TOP_WIDTH_FACTOR: advanced.RL_TOP_WIDTH_FACTOR,
        LL_TOP_WIDTH_FACTOR: advanced.LL_TOP_WIDTH_FACTOR,
        CW_TRAPEZOID_MODE: advanced.CW_TRAPEZOID_MODE,
        CW_TOP_WIDTH_FACTOR: advanced.CW_TOP_WIDTH_FACTOR
    };
    fetch('/set_advanced',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})
        .then(r=>r.json()).then(j=>{
            if(j && j.success) showToast('Shape Config Saved');
        });
});

/* ---------- Manual Box inputs ---------- */
function updateInputsFromValues(){
    inputsContainer.querySelectorAll('input').forEach(input=>{
        const name = input.name;
        if(values[name]!==undefined) input.value = round01(values[name]).toFixed(2);
    });
}
document.querySelectorAll('.btn-inc').forEach(btn=>{
    btn.addEventListener('click', ()=>{
        const v = btn.dataset.var;
        const d = parseFloat(btn.dataset.delta);
        const input = inputsContainer.querySelector(`input[name="${v}"]`);
        let val = parseFloat(input.value)||0;
        val = clamp01(round01(val + d));
        input.value = val.toFixed(2);
        debounceSendSingle(v, val);
    });
});
function debounceSendSingle(name, val){
    if(debounceTimers[name]) clearTimeout(debounceTimers[name]);
    debounceTimers[name] = setTimeout(()=>{ sendUpdate({[name]:val}); }, 250);
}
inputsContainer.querySelectorAll('input').forEach(input=>{
    input.addEventListener('input', e=>{
        const name = e.target.name;
        let v = parseFloat(e.target.value);
        if(isNaN(v)) return;
        v = clamp01(round01(v));
        values[name]=v;
        debounceSendSingle(name, v);
        drawOverlays();
    });
});
document.getElementById('apply_all').addEventListener('click', ()=>{
    const data = {};
    inputsContainer.querySelectorAll('input').forEach(input=>{
        const name = input.name;
        let val = parseFloat(input.value);
        if(!isNaN(val)) data[name] = clamp01(round01(val));
    });
    sendUpdate(data);
});
function sendUpdate(data){
    fetch('/update_conf',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})
        .then(r=>r.json()).then(j=>{
            if(j && j.values){
                values = j.values;
                updateInputsFromValues(); drawOverlays();
                showToast('Base Updated');
            }
        });
}

/* ---------- Stream API Actions ---------- */
document.getElementById('refresh_vals').addEventListener('click', ()=>{
    fetch('/get_values').then(r=>r.json()).then(j=>{ if(j && j.values){ values=j.values; updateInputsFromValues(); drawOverlays(); }});
    loadAdvanced();
});
document.getElementById('clear_selection').addEventListener('click', ()=>{ select.value='NONE'; selectedVar='NONE'; markerHighlight=null; drawOverlays(); });
document.getElementById('download_json').addEventListener('click', ()=>{
    fetch('/get_values').then(r=>r.json()).then(j=>{
        const blob = new Blob([JSON.stringify(j.values, null, 2)], {type:'application/json'});
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a'); a.href=url; a.download='config.json'; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    });
});

/* ---------- Advanced API Sync ---------- */
const advInputs = {
    lane_threshold: document.getElementById('lane_threshold'),
    cross_thresh: document.getElementById('cross_thresh'),
    run_lvl: document.getElementById('run_lvl'),
    with_sign: document.getElementById('with_sign'),
    with_apriltag: document.getElementById('with_apriltag'),
    advMsg: document.getElementById('advanced_msg')
};

function loadAdvanced(){
    fetch('/get_advanced').then(r=>r.json()).then(j=>{
        if(j && j.advanced){
            advanced = j.advanced;
            advInputs.lane_threshold.value = advanced.LANE_THRESHOLD;
            advInputs.cross_thresh.value = advanced.CROSSWALK_THRESHOLD;
            advInputs.run_lvl.value = advanced.RUN_LVL;
            advInputs.with_sign.checked = advanced.WITH_SIGN;
            advInputs.with_apriltag.checked = advanced.WITH_APRILTAG;
            updateShapeUIFromData();
        }
    });
}

document.getElementById('confirm_advanced').addEventListener('click', ()=>{
    const payload = {
        LANE_THRESHOLD: parseInt(advInputs.lane_threshold.value)||0,
        CROSSWALK_THRESHOLD: parseInt(advInputs.cross_thresh.value)||0,
        RUN_LVL: advInputs.run_lvl.value,
        WITH_SIGN: advInputs.with_sign.checked,
        WITH_APRILTAG: advInputs.with_apriltag.checked
    };
    fetch('/set_advanced',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})
        .then(r=>r.json()).then(j=>{
            if(j && j.success){
                advanced = j.advanced;
                loadAdvanced();
                showToast('Advanced Logic Saved');
            }
        });
});

/* ---------- Buttons setup ---------- */
document.getElementById('freeze_btn').addEventListener('click', ()=>fetch('/freeze_frame', {method:'POST'}).then(()=> {isFrozen=true; updateFrameModeText(); showToast('Frame frozen');}));
document.getElementById('unfreeze_btn').addEventListener('click', ()=>fetch('/unfreeze_frame', {method:'POST'}).then(()=> {isFrozen=false; updateFrameModeText(); showToast('Back to live');}));

/* ---------- Init ---------- */
function initApp(){
    updateInputsFromValues(); 
    document.getElementById('vis_rl').checked = ui.visible.RL;
    document.getElementById('vis_ll').checked = ui.visible.LL;
    document.getElementById('vis_cw').checked = ui.visible.CW;
    loadAdvanced();
    updateFrameModeText();
}
initApp();
setInterval(()=>fetch('/get_values').then(r=>r.json()).then(j=>{ if(j && j.values){ values=j.values; updateInputsFromValues(); }}), 4000);

function groupFromVar(v){ if(v.startsWith('RL_')) return 'RL'; if(v.startsWith('LL_')) return 'LL'; return 'CW'; }
function mapGroupToDefaultVar(g){ if(g==='RL') return 'RL_TOP_ROI'; if(g==='LL') return 'LL_TOP_ROI'; return 'CW_TOP_ROI'; }
</script>
</body>
</html>
"""

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
        "CW_TOP_WIDTH_FACTOR": float(getattr(conf, "CW_TOP_WIDTH_FACTOR", ADVANCED_VARS["CW_TOP_WIDTH_FACTOR"]))
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
        "CW_TOP_WIDTH_FACTOR": float(getattr(conf, "CW_TOP_WIDTH_FACTOR", ADVANCED_VARS["CW_TOP_WIDTH_FACTOR"]))
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
