CALIBRATION_HTML = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Camera Calibration</title>
<style>
:root{
  --bg:#050b16;
  --panel:#0b1424;
  --panel-2:#0e1a2d;
  --line:rgba(255,255,255,.09);
  --text:#eef5ff;
  --muted:#8ea2bb;
  --cyan:#22d3ee;
  --green:#4ade80;
  --amber:#fbbf24;
  --red:#fb7185;
  --shadow:0 16px 50px rgba(0,0,0,.28);
}
*{box-sizing:border-box}
html{background:var(--bg)}
body{
  margin:0;
  min-height:100vh;
  color:var(--text);
  font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  background:
    radial-gradient(circle at 10% 0%,rgba(34,211,238,.08),transparent 28%),
    radial-gradient(circle at 100% 10%,rgba(96,165,250,.07),transparent 24%),
    var(--bg);
}
button,input,select{font:inherit}
button{
  border:1px solid transparent;
  border-radius:10px;
  min-height:40px;
  padding:9px 14px;
  color:var(--text);
  background:var(--panel-2);
  border-color:var(--line);
  cursor:pointer;
  transition:.16s ease;
}
button:hover:not(:disabled){transform:translateY(-1px);border-color:rgba(255,255,255,.16)}
button:disabled{opacity:.45;cursor:not-allowed}
button.primary{background:linear-gradient(135deg,#22d3ee,#38bdf8);color:#06202b;border-color:transparent;font-weight:700}
button.danger{color:#ffd9df;border-color:rgba(251,113,133,.25)}
input,select{
  width:100%;
  min-height:40px;
  padding:9px 11px;
  border-radius:10px;
  color:var(--text);
  background:#071122;
  border:1px solid var(--line);
  outline:none;
}
input:focus,select:focus{border-color:rgba(34,211,238,.6);box-shadow:0 0 0 3px rgba(34,211,238,.08)}
.container{width:min(1450px,calc(100% - 28px));margin:0 auto;padding:18px 0 28px}
header{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:16px}
h1{margin:0;font-size:22px;letter-spacing:-.02em}
.subtitle{margin-top:5px;color:var(--muted);font-size:13px;line-height:1.5}
.header-meta{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}
.pill{display:inline-flex;align-items:center;gap:7px;border:1px solid var(--line);background:rgba(255,255,255,.025);padding:7px 10px;border-radius:999px;color:var(--muted);font-size:12px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--muted)}
.dot.ok{background:var(--green)}.dot.warn{background:var(--amber)}.dot.err{background:var(--red)}.dot.live{background:var(--cyan);box-shadow:0 0 0 5px rgba(34,211,238,.08)}
.banner{display:none;padding:12px 14px;margin-bottom:16px;border-radius:12px;border:1px solid var(--line);background:var(--panel);box-shadow:var(--shadow);font-size:13px}
.banner.show{display:block}
.banner.error{border-color:rgba(251,113,133,.3);color:#ffd6dd}
.banner.info{border-color:rgba(34,211,238,.3);color:#cff8ff}
.layout{display:grid;grid-template-columns:minmax(0,1.65fr) minmax(360px,.95fr);gap:16px;align-items:start}
.card{background:rgba(11,20,36,.9);border:1px solid var(--line);border-radius:15px;box-shadow:var(--shadow);overflow:hidden}
.card-head{padding:15px 16px 12px;border-bottom:1px solid var(--line)}
.card-head strong{font-size:14px}.card-head p{margin:5px 0 0;font-size:12px;color:var(--muted);line-height:1.45}
.stream{padding:12px}
.stream-box{position:relative;background:#02050a;border:1px solid rgba(255,255,255,.06);border-radius:12px;overflow:hidden}
.stream-box img{display:block;width:100%;height:auto;aspect-ratio:4/3;object-fit:contain;background:#000}
.stream-foot{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:10px 2px 0;color:var(--muted);font-size:12px}
.control-stack{display:grid;gap:12px;padding:12px}
.section{border:1px solid var(--line);border-radius:12px;background:rgba(255,255,255,.018)}
.section summary{cursor:pointer;list-style:none;padding:12px 13px;font-size:13px;font-weight:700}
.section summary::-webkit-details-marker{display:none}
.section summary:after{content:"+";float:right;color:var(--muted)}
.section[open] summary:after{content:"−"}
.section-body{padding:0 13px 13px;display:grid;gap:10px}
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.field{display:grid;gap:6px}.field label{font-size:11px;color:var(--muted)}.field small{font-size:10px;color:var(--muted)}
.actions{display:flex;gap:8px;flex-wrap:wrap}.actions > *{flex:1 1 140px}
.form-row{display:flex;gap:8px;align-items:end}.form-row > .field{flex:1}
.status-line{display:flex;align-items:center;justify-content:space-between;gap:12px}
.status-label{font-size:12px;color:var(--muted)}.status-value{font-size:13px;font-weight:650;text-align:right}
.result{padding:12px;border-radius:11px;background:#071122;border:1px solid var(--line);display:grid;gap:7px}
.result h3{margin:0;font-size:12px}
.badge{display:inline-flex;align-items:center;justify-content:center;min-height:27px;padding:5px 9px;border-radius:999px;font-size:11px;font-weight:800;letter-spacing:.02em;border:1px solid var(--line)}
.badge.ok{background:rgba(74,222,128,.1);border-color:rgba(74,222,128,.25);color:#baf7cd}
.badge.warn{background:rgba(251,191,36,.1);border-color:rgba(251,191,36,.24);color:#ffe9aa}
.badge.err{background:rgba(251,113,133,.1);border-color:rgba(251,113,133,.25);color:#ffd5dd}
.badge.muted{background:rgba(255,255,255,.03);color:var(--muted)}
.reason{padding:9px 10px;border-radius:9px;background:#08101e;color:var(--muted);font-size:11px;line-height:1.45}
.progress-wrap{display:grid;gap:7px}
.progress-meta{display:flex;justify-content:space-between;font-size:11px;color:var(--muted)}
.progress{height:8px;border-radius:999px;background:#050b15;overflow:hidden}.progress > span{display:block;height:100%;width:0%;background:linear-gradient(90deg,#22d3ee,#38bdf8);transition:width .25s ease}
.diversity{display:grid;grid-template-columns:repeat(3,1fr);gap:4px;padding:8px;border-radius:10px;background:#050b15;border:1px solid rgba(255,255,255,.05)}
.cell{height:31px;border-radius:6px;background:#0a1526;position:relative;display:flex;align-items:center;justify-content:center;color:#5d718c;font-size:10px}
.cell.active{background:rgba(34,211,238,.12);color:#baf8ff;border:1px solid rgba(34,211,238,.22)}
.gallery{display:grid;grid-template-columns:145px 1fr;gap:10px;align-items:start}
.gallery select{min-height:38px}.gallery img{width:100%;height:180px;object-fit:contain;background:#000;border:1px solid var(--line);border-radius:10px}
.metric-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.metric{padding:9px;border-radius:9px;background:rgba(255,255,255,.02);border:1px solid rgba(255,255,255,.05)}
.metric span{display:block;font-size:10px;color:var(--muted)}.metric strong{display:block;margin-top:3px;font-size:12px}
.note{font-size:11px;color:var(--muted);line-height:1.5}code{font-size:.9em;color:#cceffd}
@media(max-width:1050px){.layout{grid-template-columns:1fr}.header-meta{justify-content:flex-start}}
@media(max-width:640px){.container{width:min(100% - 14px,1450px);padding-top:10px}header{display:block}.header-meta{margin-top:10px}.grid-2{grid-template-columns:1fr}.gallery{grid-template-columns:1fr}.gallery img{height:220px}.form-row{display:grid;grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="container">
  <header>
    <div>
      <h1>Camera Calibration</h1>
      <div class="subtitle">Capture accepted chessboard views, calibrate the intrinsic model, then preview the live camera with the saved correction. Detection is throttled independently from the camera stream so the live feed stays responsive.</div>
    </div>
    <div class="header-meta">
      <div class="pill"><span id="camera_dot" class="dot"></span><span id="camera_meta">Camera waiting</span></div>
      <div class="pill"><span class="dot live"></span><span id="fps_meta">Camera · detection</span></div>
    </div>
  </header>

  <div id="banner" class="banner"></div>

  <div class="layout">
    <section class="card">
      <div class="card-head">
        <strong>Live camera</strong>
        <p>Move the physical checkerboard through different positions, distances and tilts. The overlay reflects the most recent detector pass.</p>
      </div>
      <div class="stream">
        <div class="stream-box">
          <img src="/video_feed" alt="Live calibration camera stream">
        </div>
        <div class="stream-foot">
          <span id="detector_meta">Detector: —</span>
          <span id="detection_age">Detection: waiting</span>
        </div>
      </div>

      <div class="control-stack">
        <div class="section">
          <details open>
            <summary>Detection diagnostics</summary>
            <div class="section-body">
              <div class="grid-2">
                <div class="field">
                  <label>Actual detector input</label>
                  <select id="debug_view">
                    <option value="detector">Detector input (full-resolution gray)</option>
                    <option value="clahe">CLAHE recovery view</option>
                    <option value="invert">Inverted recovery view</option>
                    <option value="gray">Full-resolution grayscale</option>
                    <option value="normalized">Auto contrast</option>
                    <option value="fixed">Fixed threshold</option>
                    <option value="otsu">Otsu threshold</option>
                    <option value="adaptive">Adaptive threshold</option>
                  </select>
                </div>
                <div class="field">
                  <label>Fixed threshold</label>
                  <input id="debug_threshold" type="number" min="0" max="255" step="1" value="128">
                </div>
              </div>
              <div class="grid-2">
                <div class="field">
                  <label>Adaptive block</label>
                  <input id="debug_adaptive_block" type="number" min="3" step="2" value="21">
                </div>
                <div class="field">
                  <label>Adaptive C</label>
                  <input id="debug_adaptive_c" type="number" min="-20" max="20" step="1" value="5">
                </div>
              </div>
              <div class="note">The direct detector input is full-resolution grayscale. Otsu and adaptive thresholding are also tried automatically as fallback detector inputs; these previews refresh only when their settings change.</div>
              <img id="debug_preview" alt="Detector diagnostic preview" style="width:100%;max-height:260px;object-fit:contain;background:#000;border-radius:10px;border:1px solid var(--line)">
            </div>
          </details>
        </div>

        <div class="section">
          <details>
            <summary>Captured images</summary>
            <div class="section-body">
              <div class="gallery">
                <select id="capture_select" size="7"></select>
                <img id="capture_preview" alt="Selected calibration capture" style="display:none">
              </div>
              <div class="note">Each accepted capture stores its detector corners and quality metadata next to the JPEG, so calibration does not need to detect those frames again.</div>
            </div>
          </details>
        </div>
      </div>
    </section>

    <aside class="card">
      <div class="card-head">
        <strong>Calibration workspace</strong>
        <p>Configure the board once, collect diverse views, then run the calibration model.</p>
      </div>

      <div class="control-stack">
        <div class="result">
          <div class="status-line">
            <span class="status-label">Board state</span>
            <span id="board_state" class="badge muted">WAITING</span>
          </div>
          <div id="board_message" class="reason">Waiting for the camera.</div>
        </div>

        <div class="progress-wrap">
          <div class="progress-meta">
            <span>Accepted captures</span>
            <strong id="capture_progress_text">0 / 10</strong>
          </div>
          <div class="progress"><span id="capture_progress"></span></div>
        </div>

        <div class="result">
          <div class="status-line">
            <span class="status-label">View diversity</span>
            <span id="diversity_text" class="status-value">0 / 9 regions covered</span>
          </div>
          <div id="diversity_grid" class="diversity"></div>
          <div class="note">Auto-capture prefers new image regions and meaningful pose changes instead of taking timer-based duplicates.</div>
        </div>

        <div class="section">
          <details open>
            <summary>Board configuration</summary>
            <div class="section-body">
              <div class="grid-2">
                <div class="field"><label for="board_dimension_kind">Board dimensions mean</label><select id="board_dimension_kind"><option value="squares">Physical squares (default)</option><option value="inner_corners">Inner corners (common board specification)</option></select></div>
                <div class="field"><label for="board_cols">Columns</label><input id="board_cols" type="number" min="2" max="100" step="1" value="12"></div>
                <div class="field"><label for="board_rows">Rows</label><input id="board_rows" type="number" min="2" max="100" step="1" value="8"></div>
                <div class="field"><label for="square_size">Square size</label><input id="square_size" type="number" min="0.001" step="0.1" value="1"><small>Any consistent unit; stored as metadata.</small></div>
                <div class="field"><label for="min_valid_images">Minimum captures</label><input id="min_valid_images" type="number" min="3" max="500" step="1" value="10"></div>
              </div>
              <div class="note">Inner corners: <strong id="inner_corners">11 × 7</strong> · Physical board: <strong id="board_physical_size">12 × 8</strong>. If your board is sold as “7 × 9 corners”, choose <em>Inner corners</em> and enter 7 × 9 (the actual printed board is 8 × 10 squares).</div>
              <button id="apply_board">Apply board settings</button>
            </div>
          </details>
        </div>

        <div class="section">
          <details open>
            <summary>Detector & auto-capture</summary>
            <div class="section-body">
              <div class="grid-2">
                <div class="field">
                  <label for="detector_mode">Detector</label>
                  <select id="detector_mode">
                    <option value="auto">Auto (SB → Classic fallback)</option>
                    <option value="classic">Classic</option>
                    <option value="sb">SB</option>
                  </select>
                </div>
                <div class="field">
                  <label for="auto_capture_interval">Minimum interval (s)</label>
                  <input id="auto_capture_interval" type="number" min="0.2" max="30" step="0.1" value="1">
                </div>
              </div>
              <label class="status-line">
                <span class="status-label">Auto-capture accepted views</span>
                <input id="auto_capture_enabled" type="checkbox" style="width:18px;min-height:18px">
              </label>
              <div class="note">Auto mode tries a direct pass first and enters recovery preprocessing only after that fails.</div>
              <button id="apply_detection">Apply detection options</button>
            </div>
          </details>
        </div>

        <div class="section">
          <details>
            <summary>Quality thresholds</summary>
            <div class="section-body">
              <div class="grid-2">
                <div class="field"><label for="min_coverage">Minimum coverage</label><input id="min_coverage" type="number" min="0.001" max="1" step="0.001" value="0.03"></div>
                <div class="field"><label for="min_sharpness">Minimum sharpness</label><input id="min_sharpness" type="number" min="0.1" step="1" value="10"></div>
                <div class="field"><label for="min_edge_margin">Minimum edge margin</label><input id="min_edge_margin" type="number" min="0.001" max="0.5" step="0.001" value="0.01"></div>
                <div class="field"><label for="duplicate_distance">Duplicate distance</label><input id="duplicate_distance" type="number" min="0.001" max="5" step="0.005" value="0.05"></div>
              </div>
              <button id="apply_quality">Apply quality thresholds</button>
            </div>
          </details>
        </div>

        <div class="section">
          <details>
            <summary>Camera & calibration actions</summary>
            <div class="section-body">
              <div class="form-row">
                <div class="field"><label for="fps">Camera FPS</label><input id="fps" type="number" min="1" max="120" step="1" value="30"></div>
                <button id="apply_fps">Apply FPS</button>
              </div>
              <div class="actions">
                <button id="capture" class="primary">Capture accepted view</button>
                <button id="clear" class="danger">Clear captures</button>
              </div>
              <button id="calibrate" class="primary">Run calibration</button>
              <button id="preview_model" disabled>Show calibration preview</button>
              <div class="result">
                <h3>Calibration result</h3>
                <div class="status-line"><span class="status-label">State</span><span id="calibration_state" class="badge muted">NOT CALIBRATED</span></div>
                <div class="metric-grid">
                  <div class="metric"><span>RMS</span><strong id="rms">—</strong></div>
                  <div class="metric"><span>Mean reprojection</span><strong id="mean_error">—</strong></div>
                  <div class="metric"><span>Max view error</span><strong id="max_error">—</strong></div>
                  <div class="metric"><span>Quality gate</span><strong id="quality_status">—</strong></div>
                </div>
                <div id="calibration_message" class="reason">No calibration has been run.</div>
              </div>
              <div class="note">Output: <code>assets/camera_calibration.npz</code></div>
            </div>
          </details>
        </div>
      </div>
    </aside>
  </div>
</div>

<script>
const $ = (id) => document.getElementById(id);
let settingsLoaded = false;
let qualityLoaded = false;
let boardLoaded = false;
let lastCaptureCount = -1;
let debugTimer = null;
let statusTimer = null;
let statusInFlight = false;
let statusFailures = 0;
let bannerTimer = null;

function showBanner(message, kind="error"){
  const el = $("banner");
  el.textContent = message || "Unknown error";
  el.className = "banner show " + kind;
}
function hideBanner(){
  const el = $("banner");
  el.className = "banner";
  el.textContent = "";
}
function showTransient(message){
  clearTimeout(bannerTimer);
  showBanner(message,"info");
  bannerTimer = setTimeout(hideBanner,2200);
}
function noteStatusFailure(_error){
  statusFailures += 1;
  // Status polling is background work. Never turn a missed poll into a
  // flashing error banner; reflect a persistent outage in the header only.
  if(statusFailures >= 3){
    $("camera_dot").className="dot err";
    $("camera_meta").textContent="Calibration backend unavailable";
  }
}
function noteStatusSuccess(){
  statusFailures = 0;
}
async function api(url, options={}, meta={}){
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 6000);
  try{
    const response = await fetch(
      url,
      {
        ...options,
        signal:controller.signal,
        cache:"no-store"
      }
    );
    let payload = null;
    try{ payload = await response.json(); }catch(_){ payload = null; }
    if(!response.ok){
      const message = payload && payload.message
        ? payload.message
        : "Request failed (" + response.status + ")";
      throw new Error(message);
    }
    if(payload && payload.success === false){
      throw new Error(payload.message || "Request failed");
    }
    return payload;
  }catch(error){
    if(meta.silent) throw error;
    const message = error && error.name === "AbortError"
      ? "Calibration backend request timed out."
      : (error && error.message) || "Calibration request failed.";
    showBanner(message,"error");
    throw error;
  }finally{
    clearTimeout(timer);
  }
}
async function post(url,body={}){
  return api(url,{
    method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify(body)
  });
}
function badgeForState(state){
  if(state === "READY_FOR_CAPTURE") return ["READY FOR CAPTURE","ok"];
  if(state === "DETECTED_BUT_REJECTED") return ["DETECTED · QUALITY REJECTED","warn"];
  if(state === "NOT_DETECTED") return ["NOT DETECTED","muted"];
  return [String(state || "WAITING").replace(/_/g," "),"muted"];
}
function applyBoardState(s){
  const useInnerCorners=$("board_dimension_kind").value==="inner_corners";
  const dimensions=useInnerCorners ? s.checkerboard_inner_corners : s.board_squares;
  $("board_cols").value = dimensions[0];
  $("board_rows").value = dimensions[1];
  $("square_size").value = Number(s.square_size).toString();
  $("min_valid_images").value = s.min_valid_images;
  $("inner_corners").textContent = s.checkerboard_inner_corners[0] + " × " + s.checkerboard_inner_corners[1];
  $("board_physical_size").textContent = (s.board_squares[0] * Number(s.square_size)).toFixed(1) + " × " + (s.board_squares[1] * Number(s.square_size)).toFixed(1);
}
function updateBoardPreview(){
  const cols=Number($("board_cols").value), rows=Number($("board_rows").value), size=Number($("square_size").value);
  const useInnerCorners=$("board_dimension_kind").value==="inner_corners";
  const innerCols=useInnerCorners ? cols : cols-1;
  const innerRows=useInnerCorners ? rows : rows-1;
  const squareCols=useInnerCorners ? cols+1 : cols;
  const squareRows=useInnerCorners ? rows+1 : rows;
  if(innerCols>=1 && innerRows>=1) $("inner_corners").textContent=innerCols+" × "+innerRows;
  if(squareCols>=2 && squareRows>=2 && size>0) $("board_physical_size").textContent=(squareCols*size).toFixed(1)+" × "+(squareRows*size).toFixed(1);
}
function renderDiversity(diversity){
  const grid=$("diversity_grid");
  grid.innerHTML="";
  const cells=diversity && Array.isArray(diversity.grid) ? diversity.grid : new Array(9).fill(0);
  cells.forEach((count)=>{
    const cell=document.createElement("div");
    cell.className="cell"+(count ? " active":"");
    cell.textContent=count ? "×"+count : "—";
    grid.appendChild(cell);
  });
  $("diversity_text").textContent=(diversity ? diversity.occupied_cells : 0)+" / 9 regions covered";
}
function setCalibrationState(state){
  const cls = state==="calibrated" ? "ok" : (state==="quality_failed" || state==="calibrating") ? "warn" : state==="failed" ? "err" : "muted";
  $("calibration_state").textContent=String(state||"NOT CALIBRATED").replace(/_/g," ").toUpperCase();
  $("calibration_state").className="badge "+cls;
}
function renderStatus(s){
  const b=badgeForState(s.detection_state);
  $("board_state").textContent=b[0];
  $("board_state").className="badge "+b[1];
  $("board_message").textContent=s.detection_message || "Waiting for detection.";
  $("capture_progress_text").textContent=s.captured_images+" / "+s.min_valid_images;
  $("capture_progress").style.width=Math.min(100,(Number(s.captured_images)/Math.max(1,Number(s.min_valid_images)))*100)+"%";
  renderDiversity(s.diversity || {occupied_cells:0,grid:new Array(9).fill(0)});
  $("camera_meta").textContent=s.camera_mode+" · "+s.width+"×"+s.height;
  $("camera_dot").className="dot "+(s.last_camera_error ? "err":"ok");
  $("fps_meta").textContent=Number(s.actual_fps || s.requested_fps || 0).toFixed(1)+" FPS camera · "+Number(s.detection_fps || 0).toFixed(1)+" FPS detection";
  $("detector_meta").textContent="Detector: "+(s.detector || "not found")+(s.detection_view ? " · "+s.detection_view : "");
  $("detection_age").textContent=s.detection_age_ms==null ? "Detection: waiting" : "Detection: "+Number(s.detection_age_ms).toFixed(0)+" ms old";
  $("capture").disabled=s.detection_state!=="READY_FOR_CAPTURE" || s.calibration_state==="calibrating";
  $("calibrate").disabled=s.calibration_state==="calibrating" || Number(s.captured_images)<Number(s.min_valid_images);
  $("preview_model").disabled=s.calibration_state!=="calibrated";
  $("preview_model").textContent=s.calibration_preview_enabled ? "Show raw camera" : "Show calibration preview";
  $("rms").textContent=s.rms==null ? "—" : Number(s.rms).toFixed(4)+" px";
  $("mean_error").textContent=s.mean_reprojection_error==null ? "—" : Number(s.mean_reprojection_error).toFixed(4)+" px";
  $("max_error").textContent=s.max_reprojection_error==null ? "—" : Number(s.max_reprojection_error).toFixed(4)+" px";
  $("quality_status").textContent=s.quality_status || "not evaluated";
  $("calibration_message").textContent=s.last_calibration_message || (s.last_camera_error ? s.last_camera_error : "No calibration has been run.");
  setCalibrationState(s.calibration_state);
  $("fps").value=Number(s.requested_fps || 30).toFixed(0);
}
async function getStatus(){
  if(statusInFlight) return;
  statusInFlight=true;
  try{
    const s=await api("/api/status",{}, {silent:true});
    noteStatusSuccess();
    renderStatus(s);

    if(!settingsLoaded){
      $("detector_mode").value=s.detector_mode;
      $("auto_capture_enabled").checked=!!s.auto_capture_enabled;
      $("auto_capture_interval").value=Number(s.auto_capture_interval).toFixed(1);
      settingsLoaded=true;
    }
    if(!qualityLoaded){
      $("min_coverage").value=Number(s.min_coverage).toFixed(3);
      $("min_sharpness").value=Number(s.min_sharpness).toFixed(1);
      $("min_edge_margin").value=Number(s.min_edge_margin).toFixed(3);
      $("duplicate_distance").value=Number(s.duplicate_distance).toFixed(3);
      qualityLoaded=true;
    }
    if(!boardLoaded){
      applyBoardState(s);
      boardLoaded=true;
      updateBoardPreview();
    }
    if(lastCaptureCount!==s.captured_images){
      lastCaptureCount=s.captured_images;
      await refreshCaptures(false);
    }

    // Camera errors belong to the camera state, not to network connectivity.
    if(s.last_camera_error){
      showBanner(s.last_camera_error,"error");
    }
  }catch(error){
    noteStatusFailure(error);
  }finally{
    statusInFlight=false;
    scheduleStatusPoll();
  }
}
async function refreshCaptures(selectNewest=true){
  try{
    const data=await api("/api/captures",{}, {silent:true});
    const select=$("capture_select"), previous=select.value;
    select.innerHTML="";
    for(const item of data.captures || []){
      const option=document.createElement("option");
      option.value=item.url;
      option.textContent=item.filename;
      select.appendChild(option);
    }
    if(data.captures && data.captures.length){
      select.value=selectNewest ? data.captures[0].url : previous;
      if(!select.value) select.value=data.captures[0].url;
      $("capture_preview").src=select.value;
      $("capture_preview").style.display="block";
    }else $("capture_preview").style.display="none";
  }catch(_){}
}
function refreshDebugFrame(){
  const params=new URLSearchParams({
    view:$("debug_view").value,
    threshold:$("debug_threshold").value,
    adaptive_block:$("debug_adaptive_block").value,
    adaptive_c:$("debug_adaptive_c").value,
    t:String(Date.now())
  });
  $("debug_preview").src="/api/debug_frame?"+params.toString();
}
function scheduleDebugRefresh(delay=150){
  clearTimeout(debugTimer);
  debugTimer=setTimeout(refreshDebugFrame,delay);
}
function scheduleStatusPoll(){
  clearTimeout(statusTimer);
  if(!document.hidden) statusTimer=setTimeout(getStatus,750);
}
$("debug_view").addEventListener("change",()=>scheduleDebugRefresh(0));
$("debug_threshold").addEventListener("input",()=>{if($("debug_view").value==="fixed")scheduleDebugRefresh();});
$("debug_adaptive_block").addEventListener("input",()=>{if($("debug_view").value==="adaptive")scheduleDebugRefresh();});
$("debug_adaptive_c").addEventListener("input",()=>{if($("debug_view").value==="adaptive")scheduleDebugRefresh();});
document.addEventListener("visibilitychange",()=>{if(!document.hidden){getStatus();scheduleDebugRefresh(0);}else{clearTimeout(statusTimer);}});
["board_dimension_kind","board_cols","board_rows","square_size"].forEach((id)=>$(id).addEventListener("input",updateBoardPreview));
$("apply_fps").onclick=async()=>{try{await post("/api/settings",{fps:Number($("fps").value)});hideBanner();}catch(_){}};
$("apply_board").onclick=async()=>{
  const button=$("apply_board");button.disabled=true;
  try{
    const useInnerCorners=$("board_dimension_kind").value==="inner_corners";
    const result=await post("/api/settings",{
      board_cols:Number($("board_cols").value)+(useInnerCorners ? 1 : 0),
      board_rows:Number($("board_rows").value)+(useInnerCorners ? 1 : 0),
      square_size:Number($("square_size").value),
      min_valid_images:Number($("min_valid_images").value)
    });
    applyBoardState(result);boardLoaded=true;settingsLoaded=true;qualityLoaded=true;hideBanner();
  }catch(_){}
  finally{button.disabled=false;}
};
$("apply_detection").onclick=async()=>{
  try{
    const result=await post("/api/settings",{
      detector_mode:$("detector_mode").value,
      auto_capture_enabled:$("auto_capture_enabled").checked,
      auto_capture_interval:Number($("auto_capture_interval").value)
    });
    $("detector_mode").value=result.detector_mode;
    $("auto_capture_enabled").checked=!!result.auto_capture_enabled;
    $("auto_capture_interval").value=Number(result.auto_capture_interval).toFixed(1);
    settingsLoaded=true;hideBanner();
  }catch(_){}
};
$("apply_quality").onclick=async()=>{
  try{
    const result=await post("/api/settings",{
      min_coverage:Number($("min_coverage").value),
      min_sharpness:Number($("min_sharpness").value),
      min_edge_margin:Number($("min_edge_margin").value),
      duplicate_distance:Number($("duplicate_distance").value)
    });
    $("min_coverage").value=Number(result.min_coverage).toFixed(3);
    $("min_sharpness").value=Number(result.min_sharpness).toFixed(1);
    $("min_edge_margin").value=Number(result.min_edge_margin).toFixed(3);
    $("duplicate_distance").value=Number(result.duplicate_distance).toFixed(3);
    qualityLoaded=true;hideBanner();
  }catch(_){}
};
$("capture_select").onchange=()=>{
  const value=$("capture_select").value;
  if(value){$("capture_preview").src=value;$("capture_preview").style.display="block";}
};
$("capture").onclick=async()=>{
  try{
    const result=await post("/api/capture");
    showTransient(result.message || "Capture complete.");
    await refreshCaptures(true);await getStatus();setTimeout(hideBanner,1800);
  }catch(_){}
};
$("clear").onclick=async()=>{
  if(!confirm("Delete all captured calibration images and their metadata?"))return;
  try{
    const result=await post("/api/clear");
    showTransient(result.message || "Captures cleared.");
    await refreshCaptures(true);await getStatus();setTimeout(hideBanner,1600);
  }catch(_){}
};
$("calibrate").onclick=async()=>{
  try{
    const result=await post("/api/calibrate");
    showTransient(result.message || "Calibration started.");
    await getStatus();setTimeout(hideBanner,1500);
  }catch(_){}
};
$("preview_model").onclick=async()=>{
  const enabled=$("preview_model").textContent.includes("Show calibration preview");
  try{await post("/api/preview",{enabled});await getStatus();}catch(_){}
};
updateBoardPreview();renderDiversity({occupied_cells:0,grid:new Array(9).fill(0)});refreshCaptures(true);refreshDebugFrame();getStatus();
</script>
</body>
</html>
"""
