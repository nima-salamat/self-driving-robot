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
.container{max-width:1300px;margin:0 auto;display:grid;grid-template-columns: 1fr 480px;gap:18px;align-items:start}
.card{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.03);padding:14px;border-radius:10px;box-shadow: 0 6px 24px rgba(2,6,23,0.6)}
.header{display:flex;align-items:center;gap:12px;margin-bottom:8px}
.h1{font-size:18px;font-weight:600}
.controls{display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap}
select,input[type=number],input[type=color],input[type=checkbox],input[type=range]{background:#071428;color:var(--txt);border:1px solid rgba(255,255,255,0.04);padding:6px 8px;border-radius:6px}
input[type=range]{accent-color: var(--accent);}
button.btn{background:var(--accent);color:#012; border:none;padding:8px 12px;border-radius:8px;cursor:pointer;font-weight:600; transition: 0.2s;}
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
      <div class="small">Drag to move/resize bounding boxes or BEV corners. Use sliders for Trapezoid shapes.</div>
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
      
      <label class="small" style="color:var(--accent); font-weight:bold;">
        View Zoom <input id="workspace_zoom" type="range" min="0.3" max="1.5" step="0.1" value="1.0" style="width:70px; vertical-align:middle;">
      </label>

      <label class="small" style="color:var(--accent); font-weight:bold; margin-left: 10px;">Show Overlays <input id="show_rects" type="checkbox" checked></label>
      <div id="frame_mode" class="small status-line" style="margin-left: 10px;">Mode: Live</div>
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
      <div class="section-title">Bird's Eye View (BEV) Config</div>
      <div class="form-row" style="margin-bottom: 10px;">
        <label class="label" style="color:var(--txt); font-weight:bold;">Enable BEV System</label>
        <input type="checkbox" id="use_bev_toggle">
      </div>
      
      <div class="inputs" id="bev_inputs_container" style="max-height:160px; overflow-y:auto; font-size:12px;">
        <div class="input-wrap"><div class="label">TL_X</div><input id="BEV_SRC_TL_X" type="number" step="0.01" class="counter"></div>
        <div class="input-wrap"><div class="label">TL_Y</div><input id="BEV_SRC_TL_Y" type="number" step="0.01" class="counter"></div>
        <div class="input-wrap"><div class="label">TR_X</div><input id="BEV_SRC_TR_X" type="number" step="0.01" class="counter"></div>
        <div class="input-wrap"><div class="label">TR_Y</div><input id="BEV_SRC_TR_Y" type="number" step="0.01" class="counter"></div>
        <div class="input-wrap"><div class="label">BR_X</div><input id="BEV_SRC_BR_X" type="number" step="0.01" class="counter"></div>
        <div class="input-wrap"><div class="label">BR_Y</div><input id="BEV_SRC_BR_Y" type="number" step="0.01" class="counter"></div>
        <div class="input-wrap"><div class="label">BL_X</div><input id="BEV_SRC_BL_X" type="number" step="0.01" class="counter"></div>
        <div class="input-wrap"><div class="label">BL_Y</div><input id="BEV_SRC_BL_Y" type="number" step="0.01" class="counter"></div>
      </div>
      <div style="margin-top:10px">
         <button id="confirm_bev_inputs" class="btn">Apply BEV Inputs</button>
      </div>
    </div>

    <div class="card">
      <div class="section-title">ROI Shape & Factors</div>
      <div class="form-row"><label class="label">Lane Mode</label>
        <select id="lane_roi_mode" style="width: 140px;">
          <option value="rectangle">Rectangle</option><option value="trapezoid">Trapezoid</option>
        </select>
      </div>
      <div class="form-row"><label class="label">RL Top factor</label><input id="rl_factor" type="range" min="0.0" max="1.0" step="0.02" style="width: 100px;"><span id="rl_factor_val" class="small" style="width:30px;"></span></div>
      <div class="form-row"><label class="label">LL Top factor</label><input id="ll_factor" type="range" min="0.0" max="1.0" step="0.02" style="width: 100px;"><span id="ll_factor_val" class="small" style="width:30px;"></span></div>
      <hr style="border-color: rgba(255,255,255,0.05); margin: 8px 0;">
      <div class="form-row"><label class="label">Crosswalk Trapezoid</label><input type="checkbox" id="cw_trap_mode"></div>
      <div class="form-row"><label class="label">CW Top Factor</label><input id="cw_factor" type="range" min="0.0" max="1.0" step="0.02" style="width: 100px;"><span id="cw_factor_val" class="small" style="width:30px;"></span></div>
      <hr style="border-color: rgba(255,255,255,0.05); margin: 8px 0;">
      <div class="form-row"><label class="label">Sign/Tag Trapezoid</label><input type="checkbox" id="st_trap_mode"></div>
      <div class="form-row"><label class="label">ST Top Factor</label><input id="st_factor" type="range" min="0.0" max="1.0" step="0.02" style="width: 100px;"><span id="st_factor_val" class="small" style="width:30px;"></span></div>
      <hr style="border-color: rgba(255,255,255,0.05); margin: 8px 0;">
      <div class="form-row"><label class="label">Object Trapezoid</label><input type="checkbox" id="obj_trap_mode"></div>
      <div class="form-row"><label class="label">OBJ Top Factor</label><input id="obj_factor" type="range" min="0.0" max="1.0" step="0.02" style="width: 100px;"><span id="obj_factor_val" class="small" style="width:30px;"></span></div>
      <div style="margin-top:10px"><button id="confirm_shape" class="btn">Save Shapes to System</button></div>
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

    <div class="card"> <div class="section-title">Display & Colors</div>
      <div class="toggle-row"><label><input type="checkbox" id="vis_rl" checked> Right Lane</label><input type="color" id="color_rl" value="{{ ui.colors.RL }}"></div>
      <div class="toggle-row"><label><input type="checkbox" id="vis_ll" checked> Left Lane</label><input type="color" id="color_ll" value="{{ ui.colors.LL }}"></div>
      <div class="toggle-row"><label><input type="checkbox" id="vis_cw" checked> Crosswalk</label><input type="color" id="color_cw" value="{{ ui.colors.CW }}"></div>
      <div class="toggle-row"><label><input type="checkbox" id="vis_st" checked> Sign/Tag</label><input type="color" id="color_st" value="{{ ui.colors.ST }}"></div>
      <div class="toggle-row"><label><input type="checkbox" id="vis_obj" checked> Object</label><input type="color" id="color_obj" value="{{ ui.colors.OBJ }}"></div>
      <div class="toggle-row"><label><input type="checkbox" id="vis_bev" checked> BEV Area</label><input type="color" id="color_bev" value="{{ ui.colors.BEV }}"></div>
    </div>

    <div class="card">
      <div class="section-title">Vision Advanced Limits</div>
      <div class="inputs" style="max-height:200px; overflow-y:auto; font-size:12px;">
        <div class="form-row"><label class="label">LANE_THRESHOLD</label><input id="lane_threshold" type="number" min="0" max="255" step="1" class="counter"></div>
        <div class="form-row"><label class="label">CW_THRESHOLD</label><input id="cross_thresh" type="number" min="0" max="255" step="1" class="counter"></div>
        <div class="form-row"><label class="label">CW_SLEEP (s)</label><input id="crosswalk_sleep" type="number" min="0" step="0.1" class="counter"></div>
        <div class="form-row"><label class="label">CW_THRESH_SPEND</label><input id="crosswalk_thresh_spend" type="number" min="0" step="0.1" class="counter"></div>
        <div class="form-row"><label class="label">READ_SIGN_THRESH</label><input id="read_sign_threshold" type="number" min="0" step="1" class="counter"></div>
        <div class="form-row"><label class="label">TURN_RIGHT Lvl</label><input id="turn_right" type="number" min="0" step="1" class="counter"></div>
        <div class="form-row"><label class="label">TURN_LEFT Lvl</label><input id="turn_left" type="number" min="0" step="1" class="counter"></div>
        <div class="form-row"><label class="label">STRAIGHT Lvl</label><input id="straight" type="number" min="0" step="1" class="counter"></div>
        <div class="form-row"><label class="label">STOP Lvl</label><input id="stop_lvl" type="number" min="0" step="1" class="counter"></div>
        
        <div class="form-row"><label class="label">RUN_LVL</label>
          <select id="run_lvl" class="counter"><option value="MOVE">MOVE</option><option value="STOP">STOP</option></select>
        </div>
        <div class="form-row"><label class="label">Use Signs Vision</label><input type="checkbox" id="with_sign"></div>
        <div class="form-row"><label class="label">Use AprilTag</label><input type="checkbox" id="with_apriltag"></div>
      </div>
      <div style="display:flex;gap:8px;margin-top:12px"><button id="confirm_advanced" class="btn">Confirm Advanced Limits</button></div>
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
      <hr style="border-color: rgba(255,255,255,0.05); margin: 8px 0;">
      <div class="form-row">
        <button id="stop_all_btn" class="btn" style="background:#ef4444; color:white; width:100%;">Stop All Sync & Requests</button>
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
let valUpdateTimer = null;
let dragState = null;
let debounceTimers = {};
let isFrozen = false;
let isRecording = false;
let syncActive = true; 

// Workspace Zoom Variable
let workspaceZoom = 1.0;
document.getElementById('workspace_zoom').addEventListener('input', (e) => {
    workspaceZoom = parseFloat(e.target.value);
    drawOverlays(); 
});

/* ---------- Utilities & Math ---------- */
function clamp01(v){ return Math.max(0, Math.min(1, v)); }
function round01(v){ return Math.round(v*1000)/1000; } 
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
  if(key==='ST') return ui.colors.ST || '#bf7bff';
  if(key==='OBJ') return ui.colors.OBJ || '#ff5757';
  if(key==='BEV') return ui.colors.BEV || '#d946ef';
  return '#9ad0ff';
}
function updateFrameModeText(){
    frameModeDisplay.textContent = !syncActive ? 'Mode: STOPPED' : (isFrozen ? 'Mode: Frozen (for precise tuning)' : 'Mode: Live');
}
function sendAdvanced(payload) {
    if(!syncActive) return showToast('Requests are stopped!');
    fetch('/set_advanced',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})
        .then(r=>r.json()).then(j=>{
            if(j && j.success){
                advanced = j.advanced;
                updateShapeUIFromData();
            }
        });
}

// Convert image norm coords (0-1) to physical canvas coords, honoring workspace zoom
function getImgBounds() {
    const w = canvas.width;
    const h = canvas.height;
    const iw = w * workspaceZoom;
    const ih = h * workspaceZoom;
    const ix = (w - iw) / 2;
    const iy = (h - ih) / 2;
    return {ix, iy, iw, ih};
}

function toCanvas(nx, ny) {
    const b = getImgBounds();
    return { x: b.ix + nx * b.iw, y: b.iy + ny * b.ih };
}

/* ---------- Canvas frame loop ---------- */
function rectFromVars(topVar, bottomVar, leftVar, rightVar){
    const t = parseFloat(values[topVar]); const b = parseFloat(values[bottomVar]);
    const l = parseFloat(values[leftVar]); const r = parseFloat(values[rightVar]);
    if (isNaN(t)||isNaN(b)||isNaN(l)||isNaN(r)) return null;
    
    // Calculate physical canvas points using zoom
    const tl = toCanvas(l, t);
    const br = toCanvas(r, b);
    
    return {
        x: tl.x, y: tl.y, 
        w: Math.max(2, br.x - tl.x), h: Math.max(2, br.y - tl.y), 
        t, b, l, r
    };
}

function computeRects(){
    return {
        RL: rectFromVars('RL_TOP_ROI','RL_BOTTOM_ROI','RL_LEFT_ROI','RL_RIGHT_ROI'),
        LL: rectFromVars('LL_TOP_ROI','LL_BOTTOM_ROI','LL_LEFT_ROI','LL_RIGHT_ROI'),
        CW: rectFromVars('CW_TOP_ROI','CW_BOTTOM_ROI','CW_LEFT_ROI','CW_RIGHT_ROI'),
        ST: rectFromVars('ST_TOP_ROI','ST_BOTTOM_ROI','ST_LEFT_ROI','ST_RIGHT_ROI'),
        OBJ: rectFromVars('OBJ_TOP_ROI','OBJ_BOTTOM_ROI','OBJ_LEFT_ROI','OBJ_RIGHT_ROI')
    };
}

function startFrameLoop(){
    if(fetchFrameTimer) clearInterval(fetchFrameTimer);
    fetchFrameTimer = setInterval(fetchFrameOnce, 120);
}

function fetchFrameOnce(){
    if(!syncActive) return;
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
        
        ctx.clearRect(0,0,canvas.width,canvas.height);
        
        // Draw the image according to the Zoom level
        const b = getImgBounds();
        ctx.drawImage(img, b.ix, b.iy, b.iw, b.ih);
        
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

function drawPolygon(points, color, isHighlight, labelText, r, fillAlpha=0.35) {
    ctx.beginPath();
    ctx.moveTo(points[0].x, points[0].y);
    for(let i=1; i<points.length; i++) ctx.lineTo(points[i].x, points[i].y);
    ctx.closePath();
    
    ctx.fillStyle = color;
    ctx.globalAlpha = fillAlpha;
    ctx.fill();
    
    ctx.globalAlpha = 1;
    ctx.strokeStyle = isHighlight ? '#ffffff' : color;
    ctx.lineWidth = isHighlight ? 3 : 2;
    ctx.stroke();

    if (r && labelText) {
        ctx.fillStyle = color;
        ctx.fillRect(r.x + 6, r.y + 6, 120, 18);
        ctx.fillStyle = '#012';
        ctx.font = 'bold 12px Arial';
        ctx.fillText(labelText, r.x + 10, r.y + 19);
    }
}

function drawOverlays(){
    const showRects = showRectsCheckbox.checked;
    const rects = computeRects();
    ctx.save();
    
    if(showRects){
        const laneMode = advanced.LANE_ROI_MODE || 'rectangle';
        const cwMode = advanced.CW_TRAPEZOID_MODE !== false; 
        const stMode = advanced.ST_TRAPEZOID_MODE !== false; 
        const objMode = advanced.OBJ_TRAPEZOID_MODE !== false;
        
        // 1. Draw BEV
        if(ui.visible['BEV'] && advanced.USE_BEV !== false) {
            const bevColor = varColorByKey('BEV');
            const isBevHL = (markerHighlight === 'BEV');
            const pts = [
                toCanvas(advanced.BEV_SRC_TL_X, advanced.BEV_SRC_TL_Y),
                toCanvas(advanced.BEV_SRC_TR_X, advanced.BEV_SRC_TR_Y),
                toCanvas(advanced.BEV_SRC_BR_X, advanced.BEV_SRC_BR_Y),
                toCanvas(advanced.BEV_SRC_BL_X, advanced.BEV_SRC_BL_Y)
            ];
            
            drawPolygon(pts, bevColor, isBevHL, null, null, 0.15); 
            
            ctx.fillStyle = bevColor;
            ctx.fillRect(pts[0].x, pts[0].y - 20, 90, 18);
            ctx.fillStyle = '#fff';
            ctx.font = 'bold 12px Arial';
            ctx.fillText("BEV Region", pts[0].x + 5, pts[0].y - 7);

            const size = 12;
            for(let p of pts) drawHandle(p.x, p.y, size, '#fff', bevColor);
        }

        // 2. Draw ROIs
        for(const key of ['RL','LL','CW','ST','OBJ']){
            if(!ui.visible[key]) continue;
            const r = rects[key];
            if(!r) continue;
            
            const color = varColorByKey(key);
            const isHL = (markerHighlight === key);
            
            if(key === 'RL') {
                if(laneMode === 'trapezoid'){
                    let factor = advanced.RL_TOP_WIDTH_FACTOR;
                    let pts = [{x:r.x, y:r.y}, {x:r.x+(r.w*factor), y:r.y}, {x:r.x+r.w, y:r.y+r.h}, {x:r.x, y:r.y+r.h}];
                    drawPolygon(pts, color, isHL, "RL (Trapezoid)", r);
                } else {
                    let pts = [{x:r.x,y:r.y}, {x:r.x+r.w,y:r.y}, {x:r.x+r.w,y:r.y+r.h}, {x:r.x,y:r.y+r.h}];
                    drawPolygon(pts, color, isHL, "RL (Rectangle)", r);
                }
            } 
            else if(key === 'LL') {
                if(laneMode === 'trapezoid'){
                    let factor = advanced.LL_TOP_WIDTH_FACTOR;
                    let pts = [{x:(r.x+r.w)-(r.w*factor), y:r.y}, {x:r.x+r.w, y:r.y}, {x:r.x+r.w, y:r.y+r.h}, {x:r.x, y:r.y+r.h}];
                    drawPolygon(pts, color, isHL, "LL (Trapezoid)", r);
                } else {
                    let pts = [{x:r.x,y:r.y}, {x:r.x+r.w,y:r.y}, {x:r.x+r.w,y:r.y+r.h}, {x:r.x,y:r.y+r.h}];
                    drawPolygon(pts, color, isHL, "LL (Rectangle)", r);
                }
            }
            else if(key === 'CW') {
                if(cwMode){
                    let factor = advanced.CW_TOP_WIDTH_FACTOR;
                    let pts = [{x:r.x+(r.w*(1-factor)/2), y:r.y}, {x:r.x+(r.w*(1+factor)/2), y:r.y}, {x:r.x+r.w, y:r.y+r.h}, {x:r.x, y:r.y+r.h}];
                    drawPolygon(pts, color, isHL, "CW (Isosceles)", r);
                } else {
                    let pts = [{x:r.x,y:r.y}, {x:r.x+r.w,y:r.y}, {x:r.x+r.w,y:r.y+r.h}, {x:r.x,y:r.y+r.h}];
                    drawPolygon(pts, color, isHL, "CW (Rectangle)", r);
                }
            }
            else if(key === 'ST') {
                if(stMode){
                    let factor = advanced.ST_TOP_WIDTH_FACTOR;
                    let pts = [{x:r.x+(r.w*(1-factor)/2), y:r.y}, {x:r.x+(r.w*(1+factor)/2), y:r.y}, {x:r.x+r.w, y:r.y+r.h}, {x:r.x, y:r.y+r.h}];
                    drawPolygon(pts, color, isHL, "ST (Isosceles)", r);
                } else {
                    let pts = [{x:r.x,y:r.y}, {x:r.x+r.w,y:r.y}, {x:r.x+r.w,y:r.y+r.h}, {x:r.x,y:r.y+r.h}];
                    drawPolygon(pts, color, isHL, "ST (Rectangle)", r);
                }
            }
            else if(key === 'OBJ') {
                if(objMode){
                    let factor = advanced.OBJ_TOP_WIDTH_FACTOR;
                    let pts = [{x:r.x+(r.w*(1-factor)/2), y:r.y}, {x:r.x+(r.w*(1+factor)/2), y:r.y}, {x:r.x+r.w, y:r.y+r.h}, {x:r.x, y:r.y+r.h}];
                    drawPolygon(pts, color, isHL, "OBJ (Isosceles)", r);
                } else {
                    let pts = [{x:r.x,y:r.y}, {x:r.x+r.w,y:r.y}, {x:r.x+r.w,y:r.y+r.h}, {x:r.x,y:r.y+r.h}];
                    drawPolygon(pts, color, isHL, "OBJ (Rectangle)", r);
                }
            }
            
            ctx.globalAlpha = 1.0;
            ctx.strokeStyle = 'rgba(255,255,255,0.3)';
            ctx.lineWidth = 1;
            ctx.setLineDash([4, 4]);
            ctx.strokeRect(r.x, r.y, r.w, r.h);
            ctx.setLineDash([]);
            
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
    const size = 12;
    
    if(ui.visible['BEV'] && advanced.USE_BEV !== false) {
        const bevCorners = {
            TL: toCanvas(advanced.BEV_SRC_TL_X, advanced.BEV_SRC_TL_Y),
            TR: toCanvas(advanced.BEV_SRC_TR_X, advanced.BEV_SRC_TR_Y),
            BR: toCanvas(advanced.BEV_SRC_BR_X, advanced.BEV_SRC_BR_Y),
            BL: toCanvas(advanced.BEV_SRC_BL_X, advanced.BEV_SRC_BL_Y)
        };
        for(const c of Object.keys(bevCorners)){
            const {x:cx, y:cy} = bevCorners[c];
            if(px >= cx-size && px <= cx+size && py >= cy-size && py <= cy+size){
                return {type:'handle', group:'BEV', corner:c};
            }
        }
    }

    const rects = computeRects();
    for(const key of ['RL','LL','CW','ST','OBJ']){
        if(!ui.visible[key]) continue;
        const r = rects[key];
        if(!r) continue;
        
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
    if(!syncActive) return;
    const rectB = canvas.getBoundingClientRect();
    const px = e.clientX - rectB.left;
    const py = e.clientY - rectB.top;
    const hit = hitTest(px, py);
    
    if(hit.group === 'BEV') {
        dragState = {type:'resize', group:'BEV', corner:hit.corner, start:{x:px,y:py}, orig: {...advanced}};
        markerHighlight = 'BEV';
    } 
    else if(hit.type==='handle'){
        dragState = {type:'resize', group:hit.group, corner:hit.corner, origRect:hit.rect, start:{x:px,y:py}};
        markerHighlight = hit.group;
        selectedVar = mapGroupToDefaultVar(hit.group);
        select.value = selectedVar;
    } 
    else if(hit.type==='inside'){
        dragState = {type:'move', group:hit.group, origRect:hit.rect, start:{x:px,y:py}};
        markerHighlight = hit.group;
        selectedVar = mapGroupToDefaultVar(hit.group);
        select.value = selectedVar;
    } 
    else {
        dragState = null;
        markerHighlight = null;
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
    
    if(!dragState || !syncActive) return;
    const dx = px - dragState.start.x;
    const dy = py - dragState.start.y;
    
    const b = getImgBounds();
    const dnx = dx / b.iw; // Scale delta accurately by workspace zoom
    const dny = dy / b.ih;
    
    if(dragState.group === 'BEV'){
        const c = dragState.corner; 
        
        // Removed 0-1 restriction. Allowing bounds from -5 to 5.
        let nx = Math.max(-5.0, Math.min(5.0, dragState.orig['BEV_SRC_'+c+'_X'] + dnx));
        let ny = Math.max(-5.0, Math.min(5.0, dragState.orig['BEV_SRC_'+c+'_Y'] + dny));
        
        advanced['BEV_SRC_'+c+'_X'] = round01(nx);
        advanced['BEV_SRC_'+c+'_Y'] = round01(ny);
        
        updateShapeUIFromData(); 
        drawOverlays();
        
        if(debounceTimers['BEV']) clearTimeout(debounceTimers['BEV']);
        debounceTimers['BEV'] = setTimeout(()=>{
            sendAdvanced({
                ['BEV_SRC_'+c+'_X']: advanced['BEV_SRC_'+c+'_X'],
                ['BEV_SRC_'+c+'_Y']: advanced['BEV_SRC_'+c+'_Y']
            });
        }, 220);
        return; 
    }
    
    const group = dragState.group;
    let topVar, bottomVar, leftVar, rightVar;
    if(group==='RL'){ topVar='RL_TOP_ROI'; bottomVar='RL_BOTTOM_ROI'; leftVar='RL_LEFT_ROI'; rightVar='RL_RIGHT_ROI'; }
    else if(group==='LL'){ topVar='LL_TOP_ROI'; bottomVar='LL_BOTTOM_ROI'; leftVar='LL_LEFT_ROI'; rightVar='LL_RIGHT_ROI'; }
    else if(group==='CW'){ topVar='CW_TOP_ROI'; bottomVar='CW_BOTTOM_ROI'; leftVar='CW_LEFT_ROI'; rightVar='CW_RIGHT_ROI'; }
    else if(group==='ST'){ topVar='ST_TOP_ROI'; bottomVar='ST_BOTTOM_ROI'; leftVar='ST_LEFT_ROI'; rightVar='ST_RIGHT_ROI'; }
    else { topVar='OBJ_TOP_ROI'; bottomVar='OBJ_BOTTOM_ROI'; leftVar='OBJ_LEFT_ROI'; rightVar='OBJ_RIGHT_ROI'; }
    
    const orig = dragState.origRect;
    let nx_t = orig.t, nx_b = orig.b, nx_l = orig.l, nx_r = orig.r;
    
    if(dragState.type==='move'){
        nx_t = clamp01(orig.t + dny); nx_b = clamp01(orig.b + dny);
        nx_l = clamp01(orig.l + dnx); nx_r = clamp01(orig.r + dnx);
        if(nx_r - nx_l < 0.02){ const mid = (nx_l + nx_r)/2; nx_l = mid - 0.01; nx_r = mid + 0.01; }
        if(nx_b - nx_t < 0.02){ const mid = (nx_t + nx_b)/2; nx_t = mid - 0.01; nx_b = mid + 0.01; }
    } else {
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
    if(!dragState || !syncActive) {
        dragState = null;
        canvas.style.cursor = 'default';
        return;
    }
    
    if(dragState.group === 'BEV') {
        const c = dragState.corner;
        sendAdvanced({
            ['BEV_SRC_'+c+'_X']: advanced['BEV_SRC_'+c+'_X'],
            ['BEV_SRC_'+c+'_Y']: advanced['BEV_SRC_'+c+'_Y']
        });
    } else {
        const group = dragState.group;
        let topVar, bottomVar, leftVar, rightVar;
        if(group==='RL'){ topVar='RL_TOP_ROI'; bottomVar='RL_BOTTOM_ROI'; leftVar='RL_LEFT_ROI'; rightVar='RL_RIGHT_ROI'; }
        else if(group==='LL'){ topVar='LL_TOP_ROI'; bottomVar='LL_BOTTOM_ROI'; leftVar='LL_LEFT_ROI'; rightVar='LL_RIGHT_ROI'; }
        else if(group==='CW'){ topVar='CW_TOP_ROI'; bottomVar='CW_BOTTOM_ROI'; leftVar='CW_LEFT_ROI'; rightVar='CW_RIGHT_ROI'; }
        else if(group==='ST'){ topVar='ST_TOP_ROI'; bottomVar='ST_BOTTOM_ROI'; leftVar='ST_LEFT_ROI'; rightVar='ST_RIGHT_ROI'; }
        else { topVar='OBJ_TOP_ROI'; bottomVar='OBJ_BOTTOM_ROI'; leftVar='OBJ_LEFT_ROI'; rightVar='OBJ_RIGHT_ROI'; }
        sendUpdate({[topVar]:values[topVar], [bottomVar]:values[bottomVar], [leftVar]:values[leftVar], [rightVar]:values[rightVar]});
    }
    
    dragState = null;
    canvas.style.cursor = 'default';
});

/* ---------- Advanced & BEV Settings logic ---------- */
const shapeInputs = {
    lane_mode: document.getElementById('lane_roi_mode'),
    rl_factor: document.getElementById('rl_factor'),
    ll_factor: document.getElementById('ll_factor'),
    cw_trap_mode: document.getElementById('cw_trap_mode'),
    cw_factor: document.getElementById('cw_factor'),
    st_trap_mode: document.getElementById('st_trap_mode'),
    st_factor: document.getElementById('st_factor'),
    obj_trap_mode: document.getElementById('obj_trap_mode'),
    obj_factor: document.getElementById('obj_factor'),
    rl_val: document.getElementById('rl_factor_val'),
    ll_val: document.getElementById('ll_factor_val'),
    cw_val: document.getElementById('cw_factor_val'),
    st_val: document.getElementById('st_factor_val'),
    obj_val: document.getElementById('obj_factor_val'),
    use_bev: document.getElementById('use_bev_toggle'),
    bev_tl_x: document.getElementById('BEV_SRC_TL_X'),
    bev_tl_y: document.getElementById('BEV_SRC_TL_Y'),
    bev_tr_x: document.getElementById('BEV_SRC_TR_X'),
    bev_tr_y: document.getElementById('BEV_SRC_TR_Y'),
    bev_br_x: document.getElementById('BEV_SRC_BR_X'),
    bev_br_y: document.getElementById('BEV_SRC_BR_Y'),
    bev_bl_x: document.getElementById('BEV_SRC_BL_X'),
    bev_bl_y: document.getElementById('BEV_SRC_BL_Y')
};

function updateShapeUIFromData() {
    shapeInputs.lane_mode.value = advanced.LANE_ROI_MODE || 'rectangle';
    shapeInputs.rl_factor.value = advanced.RL_TOP_WIDTH_FACTOR;
    shapeInputs.ll_factor.value = advanced.LL_TOP_WIDTH_FACTOR;
    shapeInputs.cw_trap_mode.checked = advanced.CW_TRAPEZOID_MODE;
    shapeInputs.cw_factor.value = advanced.CW_TOP_WIDTH_FACTOR;
    shapeInputs.st_trap_mode.checked = advanced.ST_TRAPEZOID_MODE;
    shapeInputs.st_factor.value = advanced.ST_TOP_WIDTH_FACTOR;
    shapeInputs.obj_trap_mode.checked = advanced.OBJ_TRAPEZOID_MODE;
    shapeInputs.obj_factor.value = advanced.OBJ_TOP_WIDTH_FACTOR;
    
    shapeInputs.rl_val.textContent = parseFloat(advanced.RL_TOP_WIDTH_FACTOR).toFixed(2);
    shapeInputs.ll_val.textContent = parseFloat(advanced.LL_TOP_WIDTH_FACTOR).toFixed(2);
    shapeInputs.cw_val.textContent = parseFloat(advanced.CW_TOP_WIDTH_FACTOR).toFixed(2);
    shapeInputs.st_val.textContent = parseFloat(advanced.ST_TOP_WIDTH_FACTOR).toFixed(2);
    shapeInputs.obj_val.textContent = parseFloat(advanced.OBJ_TOP_WIDTH_FACTOR).toFixed(2);
    
    shapeInputs.use_bev.checked = advanced.USE_BEV;
    shapeInputs.bev_tl_x.value = advanced.BEV_SRC_TL_X.toFixed(3);
    shapeInputs.bev_tl_y.value = advanced.BEV_SRC_TL_Y.toFixed(3);
    shapeInputs.bev_tr_x.value = advanced.BEV_SRC_TR_X.toFixed(3);
    shapeInputs.bev_tr_y.value = advanced.BEV_SRC_TR_Y.toFixed(3);
    shapeInputs.bev_br_x.value = advanced.BEV_SRC_BR_X.toFixed(3);
    shapeInputs.bev_br_y.value = advanced.BEV_SRC_BR_Y.toFixed(3);
    shapeInputs.bev_bl_x.value = advanced.BEV_SRC_BL_X.toFixed(3);
    shapeInputs.bev_bl_y.value = advanced.BEV_SRC_BL_Y.toFixed(3);

    drawOverlays();
}

function handleShapeSlider() {
    advanced.LANE_ROI_MODE = shapeInputs.lane_mode.value;
    advanced.RL_TOP_WIDTH_FACTOR = parseFloat(shapeInputs.rl_factor.value);
    advanced.LL_TOP_WIDTH_FACTOR = parseFloat(shapeInputs.ll_factor.value);
    advanced.CW_TRAPEZOID_MODE = shapeInputs.cw_trap_mode.checked;
    advanced.CW_TOP_WIDTH_FACTOR = parseFloat(shapeInputs.cw_factor.value);
    advanced.ST_TRAPEZOID_MODE = shapeInputs.st_trap_mode.checked;
    advanced.ST_TOP_WIDTH_FACTOR = parseFloat(shapeInputs.st_factor.value);
    advanced.OBJ_TRAPEZOID_MODE = shapeInputs.obj_trap_mode.checked;
    advanced.OBJ_TOP_WIDTH_FACTOR = parseFloat(shapeInputs.obj_factor.value);
    
    shapeInputs.rl_val.textContent = advanced.RL_TOP_WIDTH_FACTOR.toFixed(2);
    shapeInputs.ll_val.textContent = advanced.LL_TOP_WIDTH_FACTOR.toFixed(2);
    shapeInputs.cw_val.textContent = advanced.CW_TOP_WIDTH_FACTOR.toFixed(2);
    shapeInputs.st_val.textContent = advanced.ST_TOP_WIDTH_FACTOR.toFixed(2);
    shapeInputs.obj_val.textContent = advanced.OBJ_TOP_WIDTH_FACTOR.toFixed(2);
    drawOverlays();
}

['input', 'change'].forEach(evt => {
    shapeInputs.lane_mode.addEventListener(evt, handleShapeSlider);
    shapeInputs.rl_factor.addEventListener(evt, handleShapeSlider);
    shapeInputs.ll_factor.addEventListener(evt, handleShapeSlider);
    shapeInputs.cw_trap_mode.addEventListener(evt, handleShapeSlider);
    shapeInputs.cw_factor.addEventListener(evt, handleShapeSlider);
    shapeInputs.st_trap_mode.addEventListener(evt, handleShapeSlider);
    shapeInputs.st_factor.addEventListener(evt, handleShapeSlider);
    shapeInputs.obj_trap_mode.addEventListener(evt, handleShapeSlider);
    shapeInputs.obj_factor.addEventListener(evt, handleShapeSlider);
});

shapeInputs.use_bev.addEventListener('change', (e) => {
    sendAdvanced({ USE_BEV: e.target.checked });
    showToast('BEV System ' + (e.target.checked ? 'Enabled' : 'Disabled'));
});

document.getElementById('confirm_bev_inputs').addEventListener('click', () => {
    sendAdvanced({
        BEV_SRC_TL_X: parseFloat(shapeInputs.bev_tl_x.value) || 0,
        BEV_SRC_TL_Y: parseFloat(shapeInputs.bev_tl_y.value) || 0,
        BEV_SRC_TR_X: parseFloat(shapeInputs.bev_tr_x.value) || 0,
        BEV_SRC_TR_Y: parseFloat(shapeInputs.bev_tr_y.value) || 0,
        BEV_SRC_BR_X: parseFloat(shapeInputs.bev_br_x.value) || 0,
        BEV_SRC_BR_Y: parseFloat(shapeInputs.bev_br_y.value) || 0,
        BEV_SRC_BL_X: parseFloat(shapeInputs.bev_bl_x.value) || 0,
        BEV_SRC_BL_Y: parseFloat(shapeInputs.bev_bl_y.value) || 0
    });
    showToast('BEV Points Saved');
});

document.getElementById('confirm_shape').addEventListener('click', ()=>{
    sendAdvanced({
        LANE_ROI_MODE: advanced.LANE_ROI_MODE,
        RL_TOP_WIDTH_FACTOR: advanced.RL_TOP_WIDTH_FACTOR,
        LL_TOP_WIDTH_FACTOR: advanced.LL_TOP_WIDTH_FACTOR,
        CW_TRAPEZOID_MODE: advanced.CW_TRAPEZOID_MODE,
        CW_TOP_WIDTH_FACTOR: advanced.CW_TOP_WIDTH_FACTOR,
        ST_TRAPEZOID_MODE: advanced.ST_TRAPEZOID_MODE,
        ST_TOP_WIDTH_FACTOR: advanced.ST_TOP_WIDTH_FACTOR,
        OBJ_TRAPEZOID_MODE: advanced.OBJ_TRAPEZOID_MODE,
        OBJ_TOP_WIDTH_FACTOR: advanced.OBJ_TOP_WIDTH_FACTOR
    });
    showToast('Shape Config Saved');
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
        if(!syncActive) return showToast('Requests are stopped!');
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
        if(!syncActive) return;
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
    if(!syncActive) return showToast('Requests are stopped!');
    const data = {};
    inputsContainer.querySelectorAll('input').forEach(input=>{
        const name = input.name;
        let val = parseFloat(input.value);
        if(!isNaN(val)) data[name] = clamp01(round01(val));
    });
    sendUpdate(data);
});
function sendUpdate(data){
    if(!syncActive) return;
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
    if(!syncActive) return showToast('Requests are stopped!');
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

/* ---------- Stop All Sync Button Logic ---------- */
const stopAllBtn = document.getElementById('stop_all_btn');
stopAllBtn.addEventListener('click', () => {
    syncActive = !syncActive;
    if(!syncActive) {
        stopAllBtn.textContent = 'Resume All Sync & Requests';
        stopAllBtn.style.background = '#22c55e'; // Green when resuming
        clearInterval(fetchFrameTimer);
        clearInterval(valUpdateTimer);
        updateFrameModeText();
        showToast('All Sync Stopped');
    } else {
        stopAllBtn.textContent = 'Stop All Sync & Requests';
        stopAllBtn.style.background = '#ef4444'; // Red for stop
        startFrameLoop();
        valUpdateTimer = setInterval(fetchValuesLoop, 4000);
        updateFrameModeText();
        showToast('Sync Resumed');
    }
});

/* ---------- Advanced API Sync ---------- */
const advInputs = {
    lane_threshold: document.getElementById('lane_threshold'),
    cross_thresh: document.getElementById('cross_thresh'),
    cross_sleep: document.getElementById('crosswalk_sleep'),
    cross_thresh_spend: document.getElementById('crosswalk_thresh_spend'),
    read_sign_thresh: document.getElementById('read_sign_threshold'),
    turn_right: document.getElementById('turn_right'),
    turn_left: document.getElementById('turn_left'),
    straight: document.getElementById('straight'),
    stop_lvl: document.getElementById('stop_lvl'),
    run_lvl: document.getElementById('run_lvl'),
    with_sign: document.getElementById('with_sign'),
    with_apriltag: document.getElementById('with_apriltag')
};

function loadAdvanced(){
    if(!syncActive) return;
    fetch('/get_advanced').then(r=>r.json()).then(j=>{
        if(j && j.advanced){
            advanced = j.advanced;
            advInputs.lane_threshold.value = advanced.LANE_THRESHOLD;
            advInputs.cross_thresh.value = advanced.CROSSWALK_THRESHOLD;
            advInputs.cross_sleep.value = advanced.CROSSWALK_SLEEP;
            advInputs.cross_thresh_spend.value = advanced.CROSSWALK_THRESH_SPEND;
            advInputs.read_sign_thresh.value = advanced.READ_SIGN_THRESHOLD;
            advInputs.turn_right.value = advanced.TURN_RIGHT;
            advInputs.turn_left.value = advanced.TURN_LEFT;
            advInputs.straight.value = advanced.STRAIGHT;
            advInputs.stop_lvl.value = advanced.STOP;
            advInputs.run_lvl.value = advanced.RUN_LVL;
            advInputs.with_sign.checked = advanced.WITH_SIGN;
            advInputs.with_apriltag.checked = advanced.WITH_APRILTAG;
            updateShapeUIFromData();
        }
    });
}

document.getElementById('confirm_advanced').addEventListener('click', ()=>{
    sendAdvanced({
        LANE_THRESHOLD: parseInt(advInputs.lane_threshold.value)||0,
        CROSSWALK_THRESHOLD: parseInt(advInputs.cross_thresh.value)||0,
        CROSSWALK_SLEEP: parseFloat(advInputs.cross_sleep.value)||0,
        CROSSWALK_THRESH_SPEND: parseFloat(advInputs.cross_thresh_spend.value)||0,
        READ_SIGN_THRESHOLD: parseInt(advInputs.read_sign_thresh.value)||0,
        TURN_RIGHT: parseInt(advInputs.turn_right.value)||0,
        TURN_LEFT: parseInt(advInputs.turn_left.value)||0,
        STRAIGHT: parseInt(advInputs.straight.value)||0,
        STOP: parseInt(advInputs.stop_lvl.value)||0,
        RUN_LVL: advInputs.run_lvl.value,
        WITH_SIGN: advInputs.with_sign.checked,
        WITH_APRILTAG: advInputs.with_apriltag.checked
    });
    showToast('Advanced Limits Saved');
});

/* ---------- Color & Vis Listeners ---------- */
['vis_rl','vis_ll','vis_cw','vis_st','vis_obj','vis_bev'].forEach(id => {
    document.getElementById(id).addEventListener('change', (e) => {
        let key = id.replace('vis_', '').toUpperCase();
        ui.visible[key] = e.target.checked;
        if(syncActive) {
            fetch('/set_ui',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({visible: ui.visible})});
        }
        drawOverlays();
    });
});
['color_rl','color_ll','color_cw','color_st','color_obj','color_bev'].forEach(id => {
    document.getElementById(id).addEventListener('change', (e) => {
        let key = id.replace('color_', '').toUpperCase();
        ui.colors[key] = e.target.value;
        if(syncActive) {
            fetch('/set_ui',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({colors: ui.colors})});
        }
        drawOverlays();
    });
});

/* ---------- Buttons setup ---------- */
document.getElementById('freeze_btn').addEventListener('click', ()=> {
    if(!syncActive) return showToast('Requests are stopped!');
    fetch('/freeze_frame', {method:'POST'}).then(()=> {isFrozen=true; updateFrameModeText(); showToast('Frame frozen');})
});
document.getElementById('unfreeze_btn').addEventListener('click', ()=> {
    if(!syncActive) return showToast('Requests are stopped!');
    fetch('/unfreeze_frame', {method:'POST'}).then(()=> {isFrozen=false; updateFrameModeText(); showToast('Back to live');})
});

document.getElementById('take_picture_btn').addEventListener('click', () => {
    if(!syncActive) return showToast('Requests are stopped!');
    fetch('/take_picture', {method: 'POST'}).then(r => r.json()).then(j => { if (j && j.success) showToast('Picture Taken!'); });
});

document.getElementById('toggle_record_btn').addEventListener('click', () => {
    if(!syncActive) return showToast('Requests are stopped!');
    fetch('/toggle_record', {method: 'POST'}).then(r => r.json()).then(j => {
        if (j && j.success) {
            isRecording = j.recording;
            const statusDiv = document.getElementById('record_status');
            const btn = document.getElementById('toggle_record_btn');
            statusDiv.textContent = 'Recording: ' + (isRecording ? 'Yes' : 'No');
            statusDiv.style.color = isRecording ? '#ef4444' : 'var(--accent)';
            btn.textContent = isRecording ? 'Stop Recording' : 'Start Recording';
            showToast(isRecording ? 'Recording Started' : 'Recording Stopped');
        }
    });
});

/* ---------- Init ---------- */
function fetchValuesLoop() {
    if(!syncActive) return;
    fetch('/get_values').then(r=>r.json()).then(j=>{ if(j && j.values){ values=j.values; updateInputsFromValues(); }});
}

function initApp(){
    updateInputsFromValues(); 
    document.getElementById('vis_rl').checked = ui.visible.RL;
    document.getElementById('vis_ll').checked = ui.visible.LL;
    document.getElementById('vis_cw').checked = ui.visible.CW;
    document.getElementById('vis_st').checked = ui.visible.ST !== false;
    document.getElementById('vis_obj').checked = ui.visible.OBJ !== false;
    document.getElementById('vis_bev').checked = ui.visible.BEV !== false; 
    loadAdvanced();
    updateFrameModeText();
    startFrameLoop();
    valUpdateTimer = setInterval(fetchValuesLoop, 4000);
}
initApp();

function mapGroupToDefaultVar(g){ 
    if(g==='RL') return 'RL_TOP_ROI'; 
    if(g==='LL') return 'LL_TOP_ROI'; 
    if(g==='CW') return 'CW_TOP_ROI'; 
    if(g==='ST') return 'ST_TOP_ROI'; 
    if(g==='OBJ') return 'OBJ_TOP_ROI'; 
    return 'RL_TOP_ROI'; 
}
</script>
</body>
</html>
"""