HTML_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Interactive ROI & Settings</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>

:root {
  color-scheme: dark;
  --bg: #0b1119;
  --panel: #121b27;
  --panel-raised: #182332;
  --border: #2b3949;
  --accent: #22d3ee;
  --accent-soft: rgba(34, 211, 238, .12);
  --muted: #9bacbd;
  --txt: #e6edf5;
}
* { box-sizing: border-box; }
html, body { width: 100%; height: 100%; margin: 0; overflow: hidden; }
body {
  padding: 0;
  font-family: Inter, "Segoe UI", Roboto, Arial, sans-serif;
  color: var(--txt);
  background: var(--bg);
}
.container {
  width: 100%;
  height: 100vh;
  height: 100dvh;
  max-width: none;
  margin: 0;
  padding: 8px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 330px;
  gap: 8px;
  align-items: stretch;
  overflow: hidden;
}
.container > .card {
  min-width: 0;
  min-height: 0;
  height: 100%;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: 0 8px 28px rgba(0, 0, 0, .2);
}
.header {
  flex: 0 0 auto;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 32px;
  margin-bottom: 8px;
}
.h1 { font-size: 16px; font-weight: 700; white-space: nowrap; }
.header > .small { min-width: 0; line-height: 1.35; }
.controls {
  flex: 0 0 auto;
  display: flex;
  gap: 6px;
  align-items: center;
  min-height: 34px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
select, input[type=number], input[type=color], input[type=checkbox], input[type=range] {
  background: #0b1420;
  color: var(--txt);
  border: 1px solid var(--border);
  padding: 5px 7px;
  border-radius: 5px;
}
input[type=checkbox] { accent-color: var(--accent); }
input[type=range] { accent-color: var(--accent); }
button.btn {
  background: var(--accent);
  color: #06202a;
  border: 1px solid transparent;
  padding: 7px 10px;
  border-radius: 5px;
  cursor: pointer;
  font-weight: 700;
  transition: background .15s ease;
}
button.btn:hover { background: #67e8f9; }
button.ghost {
  background: #101925;
  border: 1px solid var(--border);
  color: var(--txt);
  padding: 6px 9px;
  border-radius: 5px;
  cursor: pointer;
}
button.ghost:hover { border-color: var(--accent); background: var(--accent-soft); }
button:disabled, input:disabled, select:disabled { opacity: .45; cursor: not-allowed; }
.canvas-stage {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 1 1 auto;
  min-width: 0;
  min-height: 80px;
  overflow: hidden;
  padding: 5px;
  border: 1px solid #344456;
  border-radius: 6px;
  background-color: #080d14;
  background-image:
    linear-gradient(rgba(115, 145, 170, .08) 1px, transparent 1px),
    linear-gradient(90deg, rgba(115, 145, 170, .08) 1px, transparent 1px);
  background-size: 24px 24px;
}
canvas {
  width: 100%;
  height: auto;
  max-width: 100%;
  max-height: 100%;
  aspect-ratio: 3 / 2;
  border-radius: 3px;
  display: block;
  background: #000;
}
.label { width: 145px; color: var(--muted); font-size: 12px; }
.small { font-size: 12px; color: var(--muted); }
.right-panel {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
  min-height: 0;
  height: 100%;
  overflow-y: auto;
  overflow-x: hidden;
  padding-right: 1px;
  overscroll-behavior: contain;
  scrollbar-width: thin;
  scrollbar-color: #33475b transparent;
}
.dock-panel {
  flex: 0 0 auto;
  min-width: 0;
  overflow: hidden;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 6px;
}
.dock-summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 38px;
  padding: 9px 11px;
  list-style: none;
  cursor: pointer;
  user-select: none;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: .02em;
}
.dock-summary::-webkit-details-marker { display: none; }
.dock-summary:hover { background: rgba(255,255,255,.025); }
.dock-panel[open] .dock-summary {
  color: var(--accent);
  background: var(--accent-soft);
  border-bottom: 1px solid var(--border);
}
.dock-chevron { color: var(--muted); transition: transform .15s ease; }
.dock-panel[open] .dock-chevron { transform: rotate(180deg); }
.dock-content { padding: 10px; min-width: 0; }
.dock-content > .section-title { display: none; }
.inputs { max-height: 220px; overflow: auto; padding-right: 5px; }
.input-wrap { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.counter { min-width: 64px; text-align: center; }
.section-title { font-weight: 700; margin-bottom: 10px; font-size: 14px; color: var(--accent); }
.toggle-row { display: flex; gap: 7px; align-items: center; margin-bottom: 7px; flex-wrap: wrap; }
.notice {
  background: rgba(255,255,255,.025);
  padding: 8px;
  border: 1px solid rgba(255,255,255,.05);
  border-radius: 5px;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.45;
}
.workspace-statusbar {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 25px;
  padding: 3px 2px 1px;
  color: #a6bacb;
  font: 11px ui-monospace, SFMono-Regular, Consolas, monospace;
  white-space: nowrap;
  overflow: hidden;
}
.workspace-statusbar .cad-help { overflow: hidden; text-overflow: ellipsis; }
.workspace-statusbar .cad-area { margin-left: auto; color: var(--accent); }
.status-line { margin-top: 4px; font-size: 12px; color: var(--accent); }
.small-muted { font-size: 11px; color: var(--muted); }
.form-row { display: flex; gap: 7px; align-items: center; margin: 5px 0; flex-wrap: wrap; }
.toast {
  position: fixed;
  right: 16px;
  bottom: 16px;
  max-width: min(420px, calc(100vw - 32px));
  background: #101925;
  border: 1px solid var(--border);
  padding: 10px 13px;
  border-radius: 6px;
  color: var(--txt);
  box-shadow: 0 8px 30px rgba(0,0,0,.4);
  z-index: 9999;
}
.encoder-map-link {
  margin-left: auto;
  flex: 0 0 auto;
  color: var(--accent);
  font-size: 11px;
  text-decoration: none;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 5px;
  white-space: nowrap;
}
.encoder-map-link:hover { background: var(--accent-soft); }
.container.dock-hidden { grid-template-columns: minmax(0, 1fr); }
.container.dock-hidden .right-panel { display: none; }
@media (max-width: 1050px) {
  .container { grid-template-columns: minmax(0, 1fr) 285px; }
  .h1 { font-size: 14px; }
  .header > .small { display: none; }
  .label { width: 125px; }
}
@media (max-width: 720px) {
  .container { grid-template-columns: minmax(0, 1fr); padding: 5px; }
  .container > .card { padding: 7px; }
  .right-panel {
    display: none;
    position: fixed;
    z-index: 100;
    top: 50px;
    right: 5px;
    bottom: 5px;
    width: min(330px, calc(100vw - 10px));
    height: auto;
    padding: 5px;
    background: #0b1119;
    border: 1px solid var(--border);
    border-radius: 7px;
    box-shadow: 0 14px 45px rgba(0,0,0,.6);
  }
  .container.show-dock .right-panel { display: flex; }
  .header { gap: 6px; }
  .h1 { font-size: 13px; }
  .controls { gap: 4px; }
  .controls .small { font-size: 11px; }
  #workspace_zoom { width: 58px !important; }
  .workspace-statusbar { gap: 7px; font-size: 10px; }
  .workspace-statusbar .cad-help { display: none; }
  .encoder-map-link { padding: 5px; font-size: 10px; }
}

</style>
</head>
<body>
<div class="container">
  <div class="card">
    <div class="header">
      <div class="h1">Interactive ROI Editor — {{ mode|capitalize }} Mode</div>
      <div class="small">Drag to move/resize bounding boxes or BEV corners. Use sliders for Trapezoid shapes. <span id="mode_features" style="color:var(--accent);"></span></div>
      {% if encoder_map_enabled %}<a class="encoder-map-link" href="/encoder-map">Odometry Map ↗</a>{% endif %}
      <button id="toggle_dock_btn" type="button" class="ghost">Hide Panels</button>
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
    <div id="canvas_stage" class="canvas-stage">
      <canvas id="video_canvas" width="900" height="600"></canvas>
    </div>
    <div class="workspace-statusbar" aria-live="off">
      <span id="cad_cursor_x">X: — px</span>
      <span id="cad_cursor_y">Y: — px</span>
      <span id="cad_cursor_u">U: — %</span>
      <span id="cad_cursor_v">V: — %</span>
      <span class="cad-help">Drag ROI edges/handles or BEV corner points · coordinates are shown relative to the camera image</span>
      <span id="cad_selected_area" class="cad-area">Area: NONE</span>
    </div>
    <div style="margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
      <button id="apply_all" class="btn">Apply Base Settings</button>
      <button id="refresh_vals" class="ghost">Refresh Feed</button>
      <button id="download_json" class="ghost">Download JSON</button>
      <div style="flex:1"></div>
      <div class="small">Tip: Freeze frame to tune angles accurately</div>
    </div>
  </div>

  <div class="right-panel">
    <details class="dock-panel"><summary class="dock-summary"><span>Arduino Telemetry</span><span class="dock-chevron" aria-hidden="true">⌄</span></summary><div class="dock-content">
      <div id="control_notice" class="notice" style="margin-bottom:10px;"></div>
      <div class="section-title">Arduino Telemetry</div>
      <div id="arduino_status" class="small status-line">Waiting for serial state...</div>
      <pre id="arduino_output" style="max-height:180px;overflow:auto;margin:8px 0 0;padding:8px;background:#050b15;border-radius:8px;color:var(--txt);font-size:12px;white-space:pre-wrap"></pre>
    </div></details>

  
      <details class="dock-panel" open><summary class="dock-summary"><span>Runtime Health</span><span class="dock-chevron" aria-hidden="true">⌄</span></summary><div class="dock-content">
        <div class="section-title">Runtime Health</div>
        <div id="health_state" class="status-line">State: UNKNOWN</div>
        <div id="health_faults" class="small">Faults: none</div>
        <div id="health_metrics" class="small" style="margin-top:6px;"></div>
      </div></details>

    <details class="dock-panel"><summary class="dock-summary"><span>Bird's Eye View (BEV) Config</span><span class="dock-chevron" aria-hidden="true">⌄</span></summary><div class="dock-content">
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
    </div></details>

    <details class="dock-panel"><summary class="dock-summary"><span>ROI Shape & Factors</span><span class="dock-chevron" aria-hidden="true">⌄</span></summary><div class="dock-content">
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
    </div></details>

    <details class="dock-panel"><summary class="dock-summary"><span>Bounding Box Adjustments</span><span class="dock-chevron" aria-hidden="true">⌄</span></summary><div class="dock-content">
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
    </div></details>

    <details class="dock-panel"><summary class="dock-summary"><span>Display & Colors</span><span class="dock-chevron" aria-hidden="true">⌄</span></summary><div class="dock-content"> <div class="section-title">Display & Colors</div>
      <div class="toggle-row"><label><input type="checkbox" id="vis_rl" checked> Right Lane</label><input type="color" id="color_rl" value="{{ ui.colors.RL }}"></div>
      <div class="toggle-row"><label><input type="checkbox" id="vis_ll" checked> Left Lane</label><input type="color" id="color_ll" value="{{ ui.colors.LL }}"></div>
      <div class="toggle-row"><label><input type="checkbox" id="vis_cw" checked> Crosswalk</label><input type="color" id="color_cw" value="{{ ui.colors.CW }}"></div>
      <div class="toggle-row"><label><input type="checkbox" id="vis_st" checked> Sign/Tag</label><input type="color" id="color_st" value="{{ ui.colors.ST }}"></div>
      <div class="toggle-row"><label><input type="checkbox" id="vis_obj" checked> Object</label><input type="color" id="color_obj" value="{{ ui.colors.OBJ }}"></div>
      <div class="toggle-row"><label><input type="checkbox" id="vis_bev" checked> BEV Area</label><input type="color" id="color_bev" value="{{ ui.colors.BEV }}"></div>
    </div></details>

    <details class="dock-panel"><summary class="dock-summary"><span>Vision Advanced Limits</span><span class="dock-chevron" aria-hidden="true">⌄</span></summary><div class="dock-content">
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
    </div></details>

    <details class="dock-panel"><summary class="dock-summary"><span>Stream Controls</span><span class="dock-chevron" aria-hidden="true">⌄</span></summary><div class="dock-content">
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
    </div></details>

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
const STREAM_CONTROL_ALLOWED = {{ stream_control|default(false)|tojson }};

const controlNotice = document.getElementById('control_notice');
if (controlNotice) {
    controlNotice.textContent = STREAM_CONTROL_ALLOWED
        ? 'Dashboard control is enabled.'
        : 'Dashboard is read-only. Enable STREAM_ALLOW_CONTROL or restart without --stream-read-only to allow runtime changes.';
}

let selectedVar = 'NONE';
let markerHighlight = null;
let fetchFrameTimer = null;
let valUpdateTimer = null;
let healthUpdateTimer = null;
let arduinoUpdateTimer = null;
let dragState = null;
let debounceTimers = {};
let isFrozen = false;
let isRecording = false;
let syncActive = true;

// Poll API endpoints through a shared circuit breaker. When the Python process
// disappears, stop flooding it with requests and probe again with backoff.
let dashboardApiOnline = true;
let dashboardApiFailureCount = 0;
let dashboardApiRetryAt = 0;
let dashboardApiProbeInFlight = false;

function updateDashboardConnectionState(online) {
    const state = document.getElementById('health_state');
    const faults = document.getElementById('health_faults');
    if(!online) {
        if(state) state.textContent = 'State: SERVER UNREACHABLE — retrying';
        if(faults) faults.textContent = 'Faults: waiting for the Python server to respond';
    }
}

function noteDashboardApiFailure(err) {
    const wasOnline = dashboardApiOnline;
    dashboardApiOnline = false;
    dashboardApiFailureCount += 1;
    const delayMs = Math.min(
        30000,
        1000 * Math.pow(2, Math.min(dashboardApiFailureCount - 1, 5))
    );
    dashboardApiRetryAt = Date.now() + delayMs;
    updateDashboardConnectionState(false);
    if(wasOnline) {
        console.warn('Robot server is unreachable; polling paused with retry backoff:', err && err.message ? err.message : err);
    }
}

function noteDashboardApiSuccess() {
    const wasOffline = !dashboardApiOnline;
    dashboardApiOnline = true;
    dashboardApiFailureCount = 0;
    dashboardApiRetryAt = 0;
    if(wasOffline) {
        const state = document.getElementById('health_state');
        if(state) state.textContent = 'State: Connected; refreshing runtime status...';
        const faults = document.getElementById('health_faults');
        if(faults) faults.textContent = 'Faults: refreshing...';
        showToast('Connection to robot server restored');
    }
}

async function fetchDashboardJson(url, options = {}) {
    if(Date.now() < dashboardApiRetryAt) return null;

    const isRecoveryProbe = !dashboardApiOnline;
    if(isRecoveryProbe && dashboardApiProbeInFlight) return null;
    if(isRecoveryProbe) dashboardApiProbeInFlight = true;

    try {
        const response = await fetch(url, options);
        const data = await response.json().catch(() => ({}));
        if(!response.ok) {
            throw new Error(data.message || ('HTTP ' + response.status));
        }
        noteDashboardApiSuccess();
        return data;
    } catch(err) {
        noteDashboardApiFailure(err);
        return null;
    } finally {
        if(isRecoveryProbe) dashboardApiProbeInFlight = false;
    }
}

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
        .then(async r => {
            const data = await r.json().catch(() => ({}));
            if(!r.ok) throw new Error(data.message || 'HTTP ' + r.status);
            return data;
        })
        .then(j=>{
            if(j && j.success){
                advanced = j.advanced;
                updateShapeUIFromData();
                showToast('Advanced settings saved');
            } else {
                showToast((j && j.message) || 'Could not save advanced settings');
            }
        })
        .catch(err => {
            console.error('Failed to save advanced settings:', err);
            showToast('Advanced settings failed: ' + err.message);
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
    fetchFrameOnce();
}

let frameRequestInFlight = false;
let hasRenderedFrame = false;
let frameRequestFailures = 0;
let frameRetryAt = 0;

function showCameraConnectionState(message){
    if(hasRenderedFrame) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.save();
    ctx.fillStyle = '#94a3b8';
    ctx.font = '16px Segoe UI, Arial, sans-serif';
    ctx.textBaseline = 'top';
    ctx.fillText(message, 16, 16);
    ctx.restore();
    drawOverlays();
}

function fetchFrameOnce(){
    if(!syncActive || frameRequestInFlight || !dashboardApiOnline) return;
    if(Date.now() < frameRetryAt) return;

    frameRequestInFlight = true;
    const img = new Image();
    img.decoding = 'async';

    img.onload = () => {
        try {
            if(!syncActive) return;

            const rect = canvas.getBoundingClientRect();
            const dispW = Math.floor(rect.width);
            const dispH = Math.floor(rect.height);
            if(dispW <= 0 || dispH <= 0) return;

            if(canvas.width !== dispW || canvas.height !== dispH) {
                canvas.width = dispW;
                canvas.height = dispH;
            }

            ctx.clearRect(0, 0, canvas.width, canvas.height);
            const b = getImgBounds();
            ctx.drawImage(img, b.ix, b.iy, b.iw, b.ih);
            drawOverlays();

            hasRenderedFrame = true;
            frameRequestFailures = 0;
            frameRetryAt = 0;
        } catch(err) {
            console.error('Failed to render camera frame:', err);
            showCameraConnectionState('Camera frame received, but display failed.');
        } finally {
            frameRequestInFlight = false;
        }
    };

    img.onerror = () => {
        frameRequestFailures += 1;
        frameRetryAt = Date.now() + Math.min(
            5000,
            250 * Math.pow(2, Math.min(frameRequestFailures - 1, 5))
        );

        try {
            // Keep the last good image. A transient 204/no-frame response must not
            // blank a working preview; keep retrying until a valid frame arrives.
            if(!hasRenderedFrame) {
                showCameraConnectionState(
                    frameRequestFailures > 3
                        ? 'Waiting for camera frames...'
                        : 'Connecting to camera...'
                );
            }
        } catch(err) {
            console.error('Failed to update camera connection state:', err);
        } finally {
            frameRequestInFlight = false;
        }
    };

    // Register callbacks before setting src so fast local responses cannot
    // complete before the browser has installed the handlers.
    img.src = '/video_feed_frame?t=' + Date.now();
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
        .then(async r => {
            const result = await r.json().catch(() => ({}));
            if(!r.ok) throw new Error(result.message || 'HTTP ' + r.status);
            return result;
        })
        .then(j=>{
            if(j && j.values){
                values = j.values;
                updateInputsFromValues(); drawOverlays();
                showToast('Base Updated');
            } else {
                showToast((j && j.message) || 'Could not update base settings');
            }
        })
        .catch(err => {
            console.error('Failed to update base settings:', err);
            showToast('Settings update failed: ' + err.message);
        });
}

/* ---------- Stream API Actions ---------- */
document.getElementById('refresh_vals').addEventListener('click', ()=>{
    if(!syncActive) return showToast('Requests are stopped!');
    fetchDashboardJson('/get_values').then(j=>{ if(j && j.values){ values=j.values; updateInputsFromValues(); drawOverlays(); }});
    loadAdvanced();
});
document.getElementById('clear_selection').addEventListener('click', ()=>{ select.value='NONE'; selectedVar='NONE'; markerHighlight=null; drawOverlays(); });
document.getElementById('download_json').addEventListener('click', ()=>{
    fetchDashboardJson('/get_values').then(j=>{
        if(!j || !j.values) return;
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
        fetchFrameTimer = null;
        clearInterval(valUpdateTimer);
        valUpdateTimer = null;
        clearInterval(healthUpdateTimer);
        healthUpdateTimer = null;
        clearInterval(arduinoUpdateTimer);
        arduinoUpdateTimer = null;
        updateFrameModeText();
        showToast('All Sync Stopped');
    } else {
        stopAllBtn.textContent = 'Stop All Sync & Requests';
        stopAllBtn.style.background = '#ef4444'; // Red for stop
        startFrameLoop();
        if(!valUpdateTimer) valUpdateTimer = setInterval(fetchValuesLoop, 4000);
        if(!healthUpdateTimer) healthUpdateTimer = setInterval(updateHealth, 1000);
        if(!arduinoUpdateTimer) arduinoUpdateTimer = setInterval(updateArduinoOutput, 1000);
        fetchValuesLoop();
        updateHealth();
        updateArduinoOutput();
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
    fetchDashboardJson('/get_advanced').then(j=>{
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
function updateHealth(){
    if(!syncActive) return;
    fetchDashboardJson('/api/health')
        .then(j=>{
            if(!j) return;
            const h = j.health || {};
            const m = j.metrics || {};
            const t = m.timing || {};
            const state = document.getElementById('health_state');
            const faults = document.getElementById('health_faults');
            const metrics = document.getElementById('health_metrics');
            state.textContent = 'State: ' + (h.state || 'UNKNOWN');
            const names = Object.keys(h.faults || {});
            const details = names.map(name => {
                const fault = h.faults[name] || {};
                return name + (fault.message ? ': ' + fault.message : '');
            });
            faults.textContent = 'Faults: ' + (details.length ? details.join(' | ') : 'none');
            const loop = t.loop || {};
            const camera = t.camera || {};
            const perception = t.perception || {};
            const serial = t.serial || {};
            metrics.textContent =
                'FPS avg ' + (m.avg_fps || 0).toFixed(1) +
                ' | loop p95 ' + (loop.p95_ms || 0).toFixed(1) + ' ms' +
                ' | loop max ' + (loop.max_ms || 0).toFixed(1) + ' ms' +
                ' | camera p95 ' + (camera.p95_ms || 0).toFixed(1) + ' ms' +
                ' | perception p95 ' + (perception.p95_ms || 0).toFixed(1) + ' ms' +
                ' | serial p95 ' + (serial.p95_ms || 0).toFixed(1) + ' ms' +
                (j.perception_confidence ? ' | Confidence ' + j.perception_confidence.score.toFixed(2) + ' (' + (j.perception_confidence.valid?'valid':'invalid') + ')' : '') +
                (j.speed_decision ? ' | Speed: ' + j.speed_decision.target + ' ' + j.speed_decision.reason : '') +
                (j.obstacle_diagnostics ? ' | Obstacle: ' + j.obstacle_diagnostics.state + ' — ' + j.obstacle_diagnostics.reason : '');
        })
        .catch(()=>{});
}

function updateArduinoOutput(){
    if(!syncActive) return;
    fetchDashboardJson('/api/arduino-output')
        .then(j=>{
            if(!j) return;
            const status = document.getElementById('arduino_status');
            const output = document.getElementById('arduino_output');
            status.textContent = 'State: ' + (j.state || 'UNKNOWN') + ' | Connected: ' + (j.connected ? 'yes' : 'no');
            output.textContent = (j.lines || []).join('\\n');
            output.scrollTop = output.scrollHeight;
        })
        .catch(()=>{});
}

function fetchValuesLoop() {
    if(!syncActive) return;
    fetchDashboardJson('/get_values').then(j=>{ if(j && j.values){ values=j.values; updateInputsFromValues(); }});
}

function loadModeFeatures(){
    fetchDashboardJson('/api/mode').then(j=>{
        if(!j) return;
        const f=j.features || {};
        const c=j.capabilities || {};
        const lane = f.lane_detector || 'default';
        document.getElementById('mode_features').textContent =
            'Lane: ' + lane +
            ' | BEV: ' + (f.bev ? 'on' : 'off') +
            ' | ML: ' + (f.ml_lane_detector ? 'on' : 'off') +
            ' | Marker: ' + (f.marker_mode || 'none');

        const disable = (el, condition, reason) => {
            if(!el) return;
            el.disabled = condition;
            if(condition) el.title = reason;
        };
        const controls = [
            [document.getElementById('use_bev_toggle'), !c.supports_bev, 'BEV is not supported by the active mode.'],
            [document.getElementById('confirm_bev_inputs'), !c.supports_bev, 'BEV is not supported by the active mode.'],
            [document.getElementById('lane_roi_mode'), !c.supports_lane_roi, 'Lane ROI controls are not used by the active lane detector.'],
            [document.getElementById('confirm_shape'), !c.supports_lane_roi, 'Lane ROI controls are not used by the active lane detector.'],
            [document.getElementById('rl_factor'), !c.supports_lane_roi, 'Lane ROI controls are not used by the active lane detector.'],
            [document.getElementById('ll_factor'), !c.supports_lane_roi, 'Lane ROI controls are not used by the active lane detector.'],
            [document.getElementById('cross_thresh'), !c.supports_crosswalk, 'Crosswalk processing is not supported by the active mode.'],
            [document.getElementById('crosswalk_sleep'), !c.supports_crosswalk, 'Crosswalk processing is not supported by the active mode.'],
            [document.getElementById('crosswalk_thresh_spend'), !c.supports_crosswalk, 'Crosswalk processing is not supported by the active mode.'],
            [document.getElementById('cw_trap_mode'), !c.supports_crosswalk_trapezoid, 'Crosswalk trapezoid processing is not supported by the active mode.'],
            [document.getElementById('cw_factor'), !c.supports_crosswalk_trapezoid, 'Crosswalk trapezoid processing is not supported by the active mode.'],
            [document.getElementById('obj_trap_mode'), !c.supports_object_detection, 'Object detection is not supported by the active mode.'],
            [document.getElementById('obj_factor'), !c.supports_object_detection, 'Object detection is not supported by the active mode.'],
            [document.getElementById('with_sign'), !c.supports_sign, 'Traffic-sign processing is not supported by the active mode.'],
            [document.getElementById('with_apriltag'), !c.supports_apriltag, 'AprilTag processing is not supported by the active mode.']
        ];
        controls.forEach(item=>disable(item[0], item[1], item[2]));
        if(!STREAM_CONTROL_ALLOWED){
            document.querySelectorAll('button,input,select').forEach(el=>{
                if(el.id !== 'download_json' && el.id !== 'toggle_dock_btn') el.disabled = true;
            });
        }
        document.querySelectorAll('input[name^="CW_"]').forEach(el=>disable(el, !c.supports_crosswalk, 'Crosswalk ROI is not consumed by the active mode.'));
        document.querySelectorAll('input[name^="OBJ_"]').forEach(el=>disable(el, !c.supports_object_detection, 'Object detection ROI is not used by the active mode.'));
    }).catch(()=>{});
}


function setupCadWorkspace() {
    const workspace = document.querySelector('.container');
    const dockToggle = document.getElementById('toggle_dock_btn');
    const isNarrow = () => window.matchMedia('(max-width: 720px)').matches;
    const isDockVisible = () => isNarrow()
        ? workspace.classList.contains('show-dock')
        : !workspace.classList.contains('dock-hidden');

    function setDockVisible(visible) {
        if(isNarrow()) {
            workspace.classList.toggle('show-dock', visible);
            workspace.classList.remove('dock-hidden');
        } else {
            workspace.classList.toggle('dock-hidden', !visible);
            workspace.classList.remove('show-dock');
        }
        dockToggle.textContent = visible ? 'Hide Panels' : 'Show Panels';
        dockToggle.setAttribute('aria-expanded', String(visible));
    }

    dockToggle.addEventListener('click', () => setDockVisible(!isDockVisible()));
    window.addEventListener('resize', () => setDockVisible(isDockVisible()));
    setDockVisible(!isNarrow());

    const readout = {
        x: document.getElementById('cad_cursor_x'),
        y: document.getElementById('cad_cursor_y'),
        u: document.getElementById('cad_cursor_u'),
        v: document.getElementById('cad_cursor_v'),
        area: document.getElementById('cad_selected_area')
    };
    function updateCadReadout(event) {
        const rect = canvas.getBoundingClientRect();
        if(rect.width <= 0 || rect.height <= 0) return;
        const pointX = event.clientX - rect.left;
        const pointY = event.clientY - rect.top;
        const imageBounds = getImgBounds();
        const u = (pointX - imageBounds.ix) / imageBounds.iw;
        const v = (pointY - imageBounds.iy) / imageBounds.ih;
        readout.x.textContent = 'X: ' + Math.round(u * canvas.width) + ' px';
        readout.y.textContent = 'Y: ' + Math.round(v * canvas.height) + ' px';
        readout.u.textContent = 'U: ' + (u * 100).toFixed(1) + ' %';
        readout.v.textContent = 'V: ' + (v * 100).toFixed(1) + ' %';
    }
    canvas.addEventListener('mousemove', updateCadReadout, {passive: true});
    canvas.addEventListener('mouseleave', () => {
        readout.x.textContent = 'X: — px';
        readout.y.textContent = 'Y: — px';
        readout.u.textContent = 'U: — %';
        readout.v.textContent = 'V: — %';
    }, {passive: true});
    const selectArea = () => {
        readout.area.textContent = 'Area: ' + (select.value || 'NONE');
    };
    select.addEventListener('change', selectArea);
    selectArea();
}

function initApp(){
    setupCadWorkspace();
    updateInputsFromValues();
    loadModeFeatures(); 
    document.getElementById('vis_rl').checked = ui.visible.RL;
    document.getElementById('vis_ll').checked = ui.visible.LL;
    document.getElementById('vis_cw').checked = ui.visible.CW;
    document.getElementById('vis_st').checked = ui.visible.ST !== false;
    document.getElementById('vis_obj').checked = ui.visible.OBJ !== false;
    document.getElementById('vis_bev').checked = ui.visible.BEV !== false; 
    loadAdvanced();
    updateFrameModeText();
    startFrameLoop();

    // Start each poller once at page load; immediate requests avoid stale
    // "UNKNOWN"/"Waiting" status until the user toggles sync controls.
    fetchValuesLoop();
    updateHealth();
    updateArduinoOutput();
    valUpdateTimer = setInterval(fetchValuesLoop, 4000);
    healthUpdateTimer = setInterval(updateHealth, 1000);
    arduinoUpdateTimer = setInterval(updateArduinoOutput, 1000);
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
