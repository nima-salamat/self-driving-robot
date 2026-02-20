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

# --- ROI variable names ---
VARIABLES = [
    "RL_TOP_ROI", "RL_BOTTOM_ROI", "RL_LEFT_ROI", "RL_RIGHT_ROI",
    "LL_TOP_ROI", "LL_BOTTOM_ROI", "LL_LEFT_ROI", "LL_RIGHT_ROI",
    "CW_TOP_ROI", "CW_BOTTOM_ROI", "CW_LEFT_ROI", "CW_RIGHT_ROI"
]

# --- Advanced variables ---
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
    "RECORD_VIDEO": False
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
        "RUN_LVL": getattr(conf, "RUN_LVL", ADVANCED_VARS["RUN_LVL"]),
        "WITH_SIGN": bool(getattr(conf, "WITH_SIGN", ADVANCED_VARS["WITH_SIGN"])),
        "WITH_APRILTAG": bool(getattr(conf, "WITH_APRILTAG", ADVANCED_VARS["WITH_APRILTAG"])),
        "READ_SIGN_THRESHOLD": int(getattr(conf, "READ_SIGN_THRESHOLD", ADVANCED_VARS["READ_SIGN_THRESHOLD"])),
        "TURN_RIGHT": int(getattr(conf, "TURN_RIGHT", ADVANCED_VARS["TURN_RIGHT"])),
        "TURN_LEFT": int(getattr(conf, "TURN_LEFT", ADVANCED_VARS["TURN_LEFT"])),
        "STRAIGHT": int(getattr(conf, "STRAIGHT", ADVANCED_VARS["STRAIGHT"])),
        "STOP": int(getattr(conf, "STOP", ADVANCED_VARS["STOP"])),
        "RECORD_VIDEO": bool(getattr(conf, "RECORD_VIDEO", ADVANCED_VARS["RECORD_VIDEO"])),
    })
    try:
        with open(filename, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        logger.exception("Failed writing config JSON")

# --- HTML template (updated with new controls & advanced fields) ---
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
select,input[type=number],input[type=color],input[type=checkbox]{background:#071428;color:var(--txt);border:1px solid rgba(255,255,255,0.04);padding:6px 8px;border-radius:6px}
button.btn{background:var(--accent);color:#012; border:none;padding:8px 12px;border-radius:8px;cursor:pointer;font-weight:600}
button.ghost{background:transparent;border:1px solid rgba(255,255,255,0.06);color:var(--txt);padding:7px 10px;border-radius:8px;cursor:pointer}
canvas{width:100%;height:auto;border-radius:8px;display:block;background:#000}
.label{width:160px;color:var(--muted);font-size:13px}
.small{font-size:13px;color:var(--muted)}
.right-panel{display:flex;flex-direction:column;gap:12px}
.inputs{max-height:460px;overflow:auto;padding-right:6px}
.input-wrap{display:flex;align-items:center;gap:8px;margin-bottom:6px}
.counter{min-width:72px;text-align:center}
.section-title{font-weight:700;margin-bottom:10px;font-size:15px}
.toggle-row{display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap}
.notice{background:rgba(255,255,255,0.02);padding:8px;border-radius:8px;color:var(--muted);font-size:13px}
.toast{position:fixed;right:20px;bottom:20px;background:#0b1220;border:1px solid rgba(255,255,255,0.06);padding:10px 14px;border-radius:8px;color:var(--txt);box-shadow:0 8px 30px rgba(2,6,23,0.6)}
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
      <div class="small">Drag to move/resize • Click rectangle to select • Overlays drawn on current frame</div>
    </div>
    <div class="controls">
      <label class="small" for="variable_select">Select</label>
      <select id="variable_select">
        <option value="NONE">-- NONE --</option>
        {% for var in variables %}
          <option value="{{ var }}">{{ var }}</option>
        {% endfor %}
      </select>
      <button id="clear_selection" class="ghost">Clear</button>
      <button id="center_reset" class="ghost">Center</button>
      <div style="flex:1"></div>
      <label class="small">Show ROIs <input id="show_rects" type="checkbox" checked></label>
      <div id="frame_mode" class="small status-line">Mode: Live</div>
    </div>
    <canvas id="video_canvas" width="900" height="600"></canvas>
    <div style="margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <button id="apply_all" class="btn">Apply All</button>
      <button id="refresh_vals" class="ghost">Refresh</button>
      <button id="download_json" class="ghost">Download JSON</button>
      <div style="flex:1"></div>
      <div class="small">Tip: Freeze frame for precise ROI tuning</div>
    </div>
  </div>

  <div class="right-panel">
    <div class="card">
      <div class="section-title">Manual ROI Values</div>
      <div class="inputs" id="inputs_container">
        {% for var in variables %}
        <div class="input-wrap">
          <div class="label">{{ var }}</div>
          <input name="{{ var }}" type="number" step="0.01" min="0" max="1" class="counter" value="{{ '%.2f' % values[var] }}">
          <button type="button" class="ghost btn-inc" data-var="{{ var }}" data-delta="0.1">+0.1</button>
          <button type="button" class="ghost btn-inc" data-var="{{ var }}" data-delta="-0.1">-0.1</button>
        </div>
        {% endfor %}
      </div>
    </div>

    <div class="card">
      <div class="section-title">ROI Visibility & Colors</div>
      <div class="toggle-row"><label><input type="checkbox" id="vis_rl" checked> Right Lane</label><input type="color" id="color_rl" value="{{ ui.colors.RL }}"></div>
      <div class="toggle-row"><label><input type="checkbox" id="vis_ll" checked> Left Lane</label><input type="color" id="color_ll" value="{{ ui.colors.LL }}"></div>
      <div class="toggle-row"><label><input type="checkbox" id="vis_cw" checked> Crosswalk</label><input type="color" id="color_cw" value="{{ ui.colors.CW }}"></div>
    </div>

    <div class="card">
      <div class="section-title">Stream Controls</div>
      <div class="form-row">
        <button id="take_picture_btn" class="btn">Take Picture</button>
      </div>
      <div class="form-row">
        <button id="toggle_record_btn" class="btn">Start Recording</button>
        <div id="record_status" class="small-muted status-line">Recording: No</div>
      </div>
      <div class="form-row">
        <button id="freeze_btn" class="ghost">Freeze Frame</button>
        <button id="unfreeze_btn" class="ghost">Unfreeze Frame</button>
      </div>
    </div>

    <div class="card">
      <div class="section-title">Advanced Settings (Confirm to apply)</div>
      <div class="form-row"><label class="label">LANE_THRESHOLD</label><input id="lane_threshold" type="number" min="0" max="255" step="1"></div>
      <div class="form-row"><label class="label">CROSSWALK_THRESHOLD</label><input id="cross_thresh" type="number" min="0" max="255" step="1"></div>
      <div class="form-row"><label class="label">CROSSWALK_SLEEP (sec)</label><input id="cross_sleep" type="number" step="0.1" min="0"></div>
      <div class="form-row"><label class="label">CROSSWALK_THRESH_SPEND (sec)</label><input id="cross_spend" type="number" step="0.1" min="0"></div>
      <div class="form-row"><label class="label">RUN_LVL</label>
        <select id="run_lvl">
          <option value="MOVE">MOVE</option>
          <option value="STOP">STOP</option>
        </select>
      </div>
      <div class="form-row"><label class="label">Use Signs</label><input type="checkbox" id="with_sign"></div>
      <div class="form-row"><label class="label">Use AprilTag</label><input type="checkbox" id="with_apriltag"></div>
      <div class="form-row"><label class="label">READ_SIGN_THRESHOLD</label><input id="read_sign_threshold" type="number" min="0" step="1"></div>
      <div class="form-row"><label class="label">TURN_RIGHT ID</label><input id="turn_right_id" type="number" min="0" step="1"></div>
      <div class="form-row"><label class="label">TURN_LEFT ID</label><input id="turn_left_id" type="number" min="0" step="1"></div>
      <div class="form-row"><label class="label">STRAIGHT ID</label><input id="straight_id" type="number" min="0" step="1"></div>
      <div class="form-row"><label class="label">STOP ID</label><input id="stop_id" type="number" min="0" step="1"></div>

      <div style="display:flex;gap:8px;margin-top:12px">
        <button id="confirm_advanced" class="btn">Confirm</button>
        <button id="cancel_advanced" class="ghost">Cancel</button>
        <div style="flex:1"></div>
        <div id="advanced_msg" class="small-muted"></div>
      </div>
    </div>

    <div class="card">
      <div class="section-title">Live ROI JSON</div>
      <pre id="values_json" style="white-space:pre-wrap;color:var(--muted);font-size:13px;margin:0">{{ values|tojson }}</pre>
    </div>
  </div>
</div>

<div id="toast" class="toast" style="display:none"></div>

<script>
/* ---------- Globals ---------- */
const canvas = document.getElementById('video_canvas');
const ctx = canvas.getContext('2d');
const select = document.getElementById('variable_select');
const valuesPre = document.getElementById('values_json');
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

/* ---------- Overlays ---------- */
function drawHandle(cx, cy, size, fill, stroke){
    ctx.beginPath();
    ctx.fillStyle = fill;
    ctx.strokeStyle = stroke || '#000';
    ctx.lineWidth = 1;
    ctx.rect(cx - size/2, cy - size/2, size, size);
    ctx.fill(); ctx.stroke();
}
function drawOverlays(){
    const showRects = showRectsCheckbox.checked;
    const rects = computeRects();
    ctx.save();
    if(showRects){
        for(const key of ['RL','LL','CW']){
            if(!ui.visible[key]) continue;
            const r = rects[key];
            if(!r) continue;
            const color = varColorByKey(key);
            ctx.globalAlpha = 0.28;
            ctx.fillStyle = color;
            ctx.fillRect(r.x, r.y, r.w, r.h);
            ctx.globalAlpha = 1;
            ctx.strokeStyle = (markerHighlight === key)? '#ffffff' : color;
            ctx.lineWidth = (markerHighlight === key)? 3 : 2;
            ctx.strokeRect(r.x + 0.5, r.y + 0.5, r.w - 1, r.h - 1);
            ctx.fillStyle = color;
            ctx.fillRect(r.x + 6, r.y + 6, 120, 18);
            ctx.fillStyle = '#012';
            ctx.font = '12px Arial';
            ctx.fillText(key, r.x + 10, r.y + 19);
            ctx.fillStyle = '#fff';
            ctx.font = '11px Arial';
            const nums = `${(r.t).toFixed(2)}, ${(r.l).toFixed(2)}, ${(r.w/canvas.width).toFixed(2)}, ${(r.h/canvas.height).toFixed(2)}`;
            ctx.fillText(nums, r.x + 6, r.y + r.h - 6);
            const size = 10;
            drawHandle(r.x, r.y, size, '#fff', color);
            drawHandle(r.x + r.w, r.y, size, '#fff', color);
            drawHandle(r.x, r.y + r.h, size, '#fff', color);
            drawHandle(r.x + r.w, r.y + r.h, size, '#fff', color);
        }
    }
    ctx.restore();
}

/* ---------- Hit testing & drag (unchanged, only minor cleanup) ---------- */
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
    updateInputsFromValues(); updateValuesPre(); drawOverlays();
    if(debounceTimers[group]) clearTimeout(debounceTimers[group]);
    debounceTimers[group] = setTimeout(()=>{
        sendUpdate({[topVar]:values[topVar], [bottomVar]:values[bottomVar], [leftVar]:values[leftVar], [rightVar]:values[rightVar]}, true);
    }, 220);
});
window.addEventListener('mouseup', ()=>{
    if(!dragState) return;
    const group = dragState.group;
    let topVar, bottomVar, leftVar, rightVar;
    if(group==='RL'){ topVar='RL_TOP_ROI'; bottomVar='RL_BOTTOM_ROI'; leftVar='RL_LEFT_ROI'; rightVar='RL_RIGHT_ROI'; }
    else if(group==='LL'){ topVar='LL_TOP_ROI'; bottomVar='LL_BOTTOM_ROI'; leftVar='LL_LEFT_ROI'; rightVar='LL_RIGHT_ROI'; }
    else { topVar='CW_TOP_ROI'; bottomVar='CW_BOTTOM_ROI'; leftVar='CW_LEFT_ROI'; rightVar='CW_RIGHT_ROI'; }
    sendUpdate({[topVar]:values[topVar], [bottomVar]:values[bottomVar], [leftVar]:values[leftVar], [rightVar]:values[rightVar]}, true);
    dragState = null;
    canvas.style.cursor = 'default';
});

/* ---------- Click to set single variable ---------- */
canvas.addEventListener('click', e=>{
    if(dragState) return;
    const rect = canvas.getBoundingClientRect();
    const clickX = (e.clientX - rect.left) / rect.width;
    const clickY = (e.clientY - rect.top) / rect.height;
    const px = clickX * canvas.width;
    const py = clickY * canvas.height;
    const hit = hitTest(px, py);
    if(hit.type==='inside'){
        selectedVar = mapGroupToDefaultVar(hit.group);
        select.value = selectedVar;
        markerHighlight = hit.group;
        drawOverlays();
        return;
    }
    if(select.value==='NONE'){ markerHighlight=null; drawOverlays(); return; }
    const group = groupFromVar(select.value);
    if(!ui.visible[group]){
        if(!confirm(`${group} hidden. Show?`)){ select.value='NONE'; selectedVar='NONE'; markerHighlight=null; drawOverlays(); return; }
        ui.visible[group]=true; saveUiSettingsLocal(); drawOverlays();
    }
    let toSend = select.value.includes('LEFT') || select.value.includes('RIGHT') ? clickX : clickY;
    toSend = clamp01(round01(toSend));
    fetch('/set_variable',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({variable:select.value,value:toSend})})
        .then(r=>r.json()).then(j=>{ if(j.success){ values[select.value]=toSend; updateInputsFromValues(); updateValuesPre(); drawOverlays(); }});
});

/* ---------- Manual inputs ---------- */
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
    debounceTimers[name] = setTimeout(()=>{ sendUpdate({[name]:val}, true); }, 250);
}
inputsContainer.querySelectorAll('input').forEach(input=>{
    input.addEventListener('input', e=>{
        const name = e.target.name;
        let v = parseFloat(e.target.value);
        if(isNaN(v)) return;
        v = clamp01(round01(v));
        values[name]=v;
        updateValuesPre();
        debounceSendSingle(name, v);
    });
});
document.getElementById('apply_all').addEventListener('click', ()=>{
    const data = {};
    inputsContainer.querySelectorAll('input').forEach(input=>{
        const name = input.name;
        let val = parseFloat(input.value);
        if(isNaN(val)) return;
        val = clamp01(round01(val));
        data[name]=val;
    });
    sendUpdate(data, true);
});
function sendUpdate(data, echoReturn=false){
    fetch('/update_conf',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})
        .then(r=>r.json()).then(j=>{
            if(j && j.values){
                values = j.values;
                updateInputsFromValues(); updateValuesPre(); drawOverlays();
                showToast('Saved');
            }
        });
}

/* ---------- UI controls ---------- */
document.getElementById('refresh_vals').addEventListener('click', refreshValues);
function refreshValues(){
    fetch('/get_values').then(r=>r.json()).then(j=>{ if(j && j.values){ values=j.values; updateInputsFromValues(); updateValuesPre(); drawOverlays(); }});
}
document.getElementById('clear_selection').addEventListener('click', ()=>{ select.value='NONE'; selectedVar='NONE'; markerHighlight=null; drawOverlays(); });
document.getElementById('center_reset').addEventListener('click', ()=>{
    if(select.value==='NONE') return;
    fetch('/set_variable',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({variable:select.value,value:0.5})})
        .then(r=>r.json()).then(j=>{ if(j.success){ values[select.value]=0.5; updateInputsFromValues(); updateValuesPre(); drawOverlays(); showToast('Centered'); }});
});
document.getElementById('download_json').addEventListener('click', ()=>{
    fetch('/get_values').then(r=>r.json()).then(j=>{
        const blob = new Blob([JSON.stringify(j.values, null, 2)], {type:'application/json'});
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a'); a.href=url; a.download='{{ mode }}.json'; document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(url);
    });
});

/* ---------- Visibility & colors ---------- */
function saveUiSettingsLocal(){
    fetch('/set_ui',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(ui)})
        .then(r=>r.json()).then(j=>{ if(j.success) showToast('UI saved'); });
}
['vis_rl','vis_ll','vis_cw'].forEach(id=>{
    document.getElementById(id).addEventListener('change', e=>{
        const key = id.replace('vis_','').toUpperCase();
        ui.visible[key] = e.target.checked;
        if(!ui.visible[key] && markerHighlight===key){ markerHighlight=null; select.value='NONE'; selectedVar='NONE'; }
        saveUiSettingsLocal(); drawOverlays();
    });
});
['color_rl','color_ll','color_cw'].forEach(id=>{
    document.getElementById(id).addEventListener('input', e=>{
        const key = id.replace('color_','').toUpperCase();
        ui.colors[key] = e.target.value;
        saveUiSettingsLocal(); drawOverlays();
    });
});

/* ---------- Stream controls ---------- */
document.getElementById('take_picture_btn').addEventListener('click', ()=>{
    fetch('/take_picture', {method:'POST'}).then(r=>r.json()).then(j=>{
        if(j.success) showToast('Picture request sent');
    });
});
document.getElementById('toggle_record_btn').addEventListener('click', ()=>{
    fetch('/toggle_record', {method:'POST'}).then(r=>r.json()).then(j=>{
        if(j.success){
            isRecording = j.recording;
            document.getElementById('toggle_record_btn').textContent = isRecording ? 'Stop Recording' : 'Start Recording';
            document.getElementById('record_status').textContent = `Recording: ${isRecording ? 'Yes' : 'No'}`;
            showToast(isRecording ? 'Recording started' : 'Recording stopped');
        }
    });
});
document.getElementById('freeze_btn').addEventListener('click', ()=>{
    fetch('/freeze_frame', {method:'POST'}).then(r=>r.json()).then(j=>{
        if(j.success){
            isFrozen = true;
            updateFrameModeText();
            showToast('Frame frozen');
        }
    });
});
document.getElementById('unfreeze_btn').addEventListener('click', ()=>{
    fetch('/unfreeze_frame', {method:'POST'}).then(r=>r.json()).then(j=>{
        if(j.success){
            isFrozen = false;
            updateFrameModeText();
            showToast('Back to live');
        }
    });
});

/* ---------- Advanced settings ---------- */
const advInputs = {
    lane_threshold: document.getElementById('lane_threshold'),
    cross_thresh: document.getElementById('cross_thresh'),
    cross_sleep: document.getElementById('cross_sleep'),
    cross_spend: document.getElementById('cross_spend'),
    run_lvl: document.getElementById('run_lvl'),
    with_sign: document.getElementById('with_sign'),
    with_apriltag: document.getElementById('with_apriltag'),
    read_sign_threshold: document.getElementById('read_sign_threshold'),
    turn_right_id: document.getElementById('turn_right_id'),
    turn_left_id: document.getElementById('turn_left_id'),
    straight_id: document.getElementById('straight_id'),
    stop_id: document.getElementById('stop_id'),
    advMsg: document.getElementById('advanced_msg')
};
function loadAdvanced(){
    fetch('/get_advanced').then(r=>r.json()).then(j=>{
        if(j && j.advanced){
            advanced = j.advanced;
            advInputs.lane_threshold.value = advanced.LANE_THRESHOLD;
            advInputs.cross_thresh.value = advanced.CROSSWALK_THRESHOLD;
            advInputs.cross_sleep.value = advanced.CROSSWALK_SLEEP;
            advInputs.cross_spend.value = advanced.CROSSWALK_THRESH_SPEND;
            advInputs.run_lvl.value = advanced.RUN_LVL;
            advInputs.with_sign.checked = advanced.WITH_SIGN;
            advInputs.with_apriltag.checked = advanced.WITH_APRILTAG;
            advInputs.read_sign_threshold.value = advanced.READ_SIGN_THRESHOLD;
            advInputs.turn_right_id.value = advanced.TURN_RIGHT;
            advInputs.turn_left_id.value = advanced.TURN_LEFT;
            advInputs.straight_id.value = advanced.STRAIGHT;
            advInputs.stop_id.value = advanced.STOP;
            advInputs.advMsg.textContent = '';
        }
    });
}
loadAdvanced();

document.getElementById('confirm_advanced').addEventListener('click', ()=>{
    const payload = {
        LANE_THRESHOLD: parseInt(advInputs.lane_threshold.value)||0,
        CROSSWALK_THRESHOLD: parseInt(advInputs.cross_thresh.value)||0,
        CROSSWALK_SLEEP: parseFloat(advInputs.cross_sleep.value)||0,
        CROSSWALK_THRESH_SPEND: parseFloat(advInputs.cross_spend.value)||0,
        RUN_LVL: advInputs.run_lvl.value,
        WITH_SIGN: advInputs.with_sign.checked,
        WITH_APRILTAG: advInputs.with_apriltag.checked,
        READ_SIGN_THRESHOLD: parseInt(advInputs.read_sign_threshold.value)||0,
        TURN_RIGHT: parseInt(advInputs.turn_right_id.value)||0,
        TURN_LEFT: parseInt(advInputs.turn_left_id.value)||0,
        STRAIGHT: parseInt(advInputs.straight_id.value)||0,
        STOP: parseInt(advInputs.stop_id.value)||0
    };
    fetch('/set_advanced',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})
        .then(r=>r.json()).then(j=>{
            if(j && j.success){
                advanced = j.advanced;
                loadAdvanced();
                showToast('Advanced settings applied');
                refreshValues();
                setTimeout(()=>advInputs.advMsg.textContent='',2000);
            } else {
                advInputs.advMsg.textContent = 'Failed';
            }
        });
});
document.getElementById('cancel_advanced').addEventListener('click', ()=>{ loadAdvanced(); showToast('Cancelled'); });

/* ---------- Init ---------- */
function refreshInit(){
    updateInputsFromValues(); updateValuesPre(); drawOverlays();
    document.getElementById('vis_rl').checked = ui.visible.RL;
    document.getElementById('vis_ll').checked = ui.visible.LL;
    document.getElementById('vis_cw').checked = ui.visible.CW;
    document.getElementById('color_rl').value = ui.colors.RL;
    document.getElementById('color_ll').value = ui.colors.LL;
    document.getElementById('color_cw').value = ui.colors.CW;
    document.getElementById('toggle_record_btn').textContent = 'Start Recording';
    document.getElementById('record_status').textContent = 'Recording: No';
    updateFrameModeText();
}
refreshInit();
setInterval(refreshValues, 4000);
function updateValuesPre(){ valuesPre.textContent = JSON.stringify(values, null, 2); }
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
        "CROSSWALK_SLEEP": float(getattr(conf, "CROSSWALK_SLEEP", ADVANCED_VARS["CROSSWALK_SLEEP"])),
        "CROSSWALK_THRESH_SPEND": float(getattr(conf, "CROSSWALK_THRESH_SPEND", ADVANCED_VARS["CROSSWALK_THRESH_SPEND"])),
        "RUN_LVL": getattr(conf, "RUN_LVL", ADVANCED_VARS["RUN_LVL"]),
        "WITH_SIGN": bool(getattr(conf, "WITH_SIGN", ADVANCED_VARS["WITH_SIGN"])),
        "WITH_APRILTAG": bool(getattr(conf, "WITH_APRILTAG", ADVANCED_VARS["WITH_APRILTAG"])),
        "READ_SIGN_THRESHOLD": int(getattr(conf, "READ_SIGN_THRESHOLD", ADVANCED_VARS["READ_SIGN_THRESHOLD"])),
        "TURN_RIGHT": int(getattr(conf, "TURN_RIGHT", ADVANCED_VARS["TURN_RIGHT"])),
        "TURN_LEFT": int(getattr(conf, "TURN_LEFT", ADVANCED_VARS["TURN_LEFT"])),
        "STRAIGHT": int(getattr(conf, "STRAIGHT", ADVANCED_VARS["STRAIGHT"])),
        "STOP": int(getattr(conf, "STOP", ADVANCED_VARS["STOP"])),
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
        jsonify(success=False)
        

@app.route('/set_variable', methods=['POST'])
def set_variable():
    data = request.get_json() or {}
    var = data.get('variable')
    val = float(data.get('value', 0))
    val = max(0.0, min(1.0, val))
    if var in VARIABLES:
        setattr(conf, var, val)
        save_conf_to_json()
        return jsonify(success=True)
    return jsonify(success=False), 400

@app.route('/get_values')
def get_values():

    return jsonify(values={var: float(getattr(conf, var, 0.0)) for var in VARIABLES})

@app.route('/get_advanced')
def get_advanced():
    return jsonify(advanced={
        "LANE_THRESHOLD": int(getattr(conf, "LANE_THRESHOLD", ADVANCED_VARS["LANE_THRESHOLD"])),
        "CROSSWALK_THRESHOLD": int(getattr(conf, "CROSSWALK_THRESHOLD", ADVANCED_VARS["CROSSWALK_THRESHOLD"])),
        "CROSSWALK_SLEEP": float(getattr(conf, "CROSSWALK_SLEEP", ADVANCED_VARS["CROSSWALK_SLEEP"])),
        "CROSSWALK_THRESH_SPEND": float(getattr(conf, "CROSSWALK_THRESH_SPEND", ADVANCED_VARS["CROSSWALK_THRESH_SPEND"])),
        "RUN_LVL": getattr(conf, "RUN_LVL", ADVANCED_VARS["RUN_LVL"]),
        "WITH_SIGN": bool(getattr(conf, "WITH_SIGN", ADVANCED_VARS["WITH_SIGN"])),
        "WITH_APRILTAG": bool(getattr(conf, "WITH_APRILTAG", ADVANCED_VARS["WITH_APRILTAG"])),
        "READ_SIGN_THRESHOLD": int(getattr(conf, "READ_SIGN_THRESHOLD", ADVANCED_VARS["READ_SIGN_THRESHOLD"])),
        "TURN_RIGHT": int(getattr(conf, "TURN_RIGHT", ADVANCED_VARS["TURN_RIGHT"])),
        "TURN_LEFT": int(getattr(conf, "TURN_LEFT", ADVANCED_VARS["TURN_LEFT"])),
        "STRAIGHT": int(getattr(conf, "STRAIGHT", ADVANCED_VARS["STRAIGHT"])),
        "STOP": int(getattr(conf, "STOP", ADVANCED_VARS["STOP"])),
    })

@app.route('/set_advanced', methods=['POST'])
def set_advanced():
    data = request.get_json() or {}
    try:
        if "LANE_THRESHOLD" in data:
            setattr(conf, "LANE_THRESHOLD", max(0, min(255, int(data["LANE_THRESHOLD"]))))
        if "CROSSWALK_THRESHOLD" in data:
            setattr(conf, "CROSSWALK_THRESHOLD", max(0, min(255, int(data["CROSSWALK_THRESHOLD"]))))
        if "CROSSWALK_SLEEP" in data:
            setattr(conf, "CROSSWALK_SLEEP", float(data["CROSSWALK_SLEEP"]))
        if "CROSSWALK_THRESH_SPEND" in data:
            setattr(conf, "CROSSWALK_THRESH_SPEND", float(data["CROSSWALK_THRESH_SPEND"]))
        if "RUN_LVL" in data:
            setattr(conf, "RUN_LVL", data["RUN_LVL"] if data["RUN_LVL"] in ("MOVE","STOP") else "MOVE")
        if "WITH_SIGN" in data or "WITH_APRILTAG" in data:
            use_sign = bool(data.get("WITH_SIGN", getattr(conf, "WITH_SIGN", True)))
            setattr(conf, "WITH_SIGN", use_sign)
            setattr(conf, "WITH_APRILTAG", not use_sign)
        if "READ_SIGN_THRESHOLD" in data:
            setattr(conf, "READ_SIGN_THRESHOLD", max(0, int(data["READ_SIGN_THRESHOLD"])))
        if "TURN_RIGHT" in data:
            setattr(conf, "TURN_RIGHT", max(0, int(data["TURN_RIGHT"])))
        if "TURN_LEFT" in data:
            setattr(conf, "TURN_LEFT", max(0, int(data["TURN_LEFT"])))
        if "STRAIGHT" in data:
            setattr(conf, "STRAIGHT", max(0, int(data["STRAIGHT"])))
        if "STOP" in data:
            setattr(conf, "STOP", max(0, int(data["STOP"])))
    except Exception as e:
        logger.exception("Invalid advanced payload")
        return jsonify(success=False), 400
    save_conf_to_json()
    return jsonify(success=True, advanced=getattr(app, 'get_advanced')().get_json()['advanced'])

@app.route('/get_ui')
def get_ui():
    return jsonify(ui=UI_SETTINGS)

@app.route('/set_ui', methods=['POST'])
def set_ui():
    data = request.get_json() or {}
    if "colors" in data:
        UI_SETTINGS["colors"].update({k:v for k,v in data["colors"].items() if k in UI_SETTINGS["colors"]})
    if "visible" in data:
        UI_SETTINGS["visible"].update({k:bool(v) for k,v in data["visible"].items() if k in UI_SETTINGS["visible"]})
    save_ui_settings(UI_SETTINGS)
    return jsonify(success=True, ui=UI_SETTINGS)

@app.route('/video_feed_frame')
def video_feed_frame():
    # Prioritize frozen frame, otherwise latest from debug_frames_list
    frozen = getattr(conf, "frozen_debug_frame", None)
    if frozen is not None:
        frame = frozen
    else:
        frames_list = getattr(conf, "debug_frames_list", [])
        frame = frames_list[-1] if frames_list else None
    if frame is None:
        return Response('', status=204)
    ret, buffer = cv2.imencode('.jpg', frame)
    if not ret:
        return Response('', status=204)
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
        frozen = frames_list[-1].copy()
        setattr(conf, "frozen_debug_frame", frozen)
        return jsonify(success=True)
    return jsonify(success=False, message="No frame available")

@app.route('/unfreeze_frame', methods=['POST'])
def unfreeze_frame():
    if hasattr(conf, "frozen_debug_frame"):
        delattr(conf, "frozen_debug_frame")
    return jsonify(success=True)

@app.route("/shutdown", methods=["POST"])
def shutdown():
    os._exit(0)

def start_stream():
    app.run(host='0.0.0.0', port=5000, threaded=True, debug=False)
