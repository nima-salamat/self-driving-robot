CALIBRATION_HTML = """
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Camera Calibration Stream</title>
<style>
:root{--bg:#071426;--card:#0b1220;--accent:#06b6d4;--muted:#94a3b8;--txt:#e6eef6}
*{box-sizing:border-box}
body{margin:0;padding:18px;font-family:Inter,Segoe UI,Roboto,Arial;background:linear-gradient(180deg,#071026,#07142a);color:var(--txt)}
.container{max-width:1250px;margin:auto;display:grid;grid-template-columns:1fr 340px;gap:18px;align-items:start}
.card{background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.05);border-radius:12px;padding:14px}
h1{font-size:18px;margin:0 0 4px}
.small{font-size:13px;color:var(--muted)}
.stream-wrap{background:#000;border-radius:10px;overflow:hidden;position:relative}
.stream-wrap img{display:block;width:100%;height:auto}
.debug-preview{background:#000;border-radius:10px;overflow:hidden}
.debug-preview img{display:block;width:100%;height:auto;min-height:180px;object-fit:contain}
.debug-controls{display:grid;gap:8px;padding:10px;background:#050b15;border-radius:8px}
.debug-controls .row{justify-content:flex-start}
.debug-controls input[type=range]{width:180px}
.debug-note{font-size:12px;color:var(--muted)}
.controls{display:grid;gap:10px}
.row{display:flex;gap:8px;align-items:center;justify-content:space-between;flex-wrap:wrap}
button,input{font:inherit}
button{border:0;border-radius:8px;padding:8px 12px;cursor:pointer}
.primary{background:var(--accent);color:#012}
.ghost{background:transparent;border:1px solid rgba(255,255,255,.1);color:var(--txt)}
input{background:#071428;color:var(--txt);border:1px solid rgba(255,255,255,.1);border-radius:7px;padding:7px;width:100px}
.status{display:grid;gap:6px;padding:10px;background:#050b15;border-radius:8px;font-size:13px}
details{background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.05);border-radius:9px;padding:8px}
summary{cursor:pointer;font-weight:600;padding:4px 2px}
select{background:#071428;color:var(--txt);border:1px solid rgba(255,255,255,.1);border-radius:7px;padding:7px}
.check{display:flex;gap:8px;align-items:center}
.ok{color:#4ade80}.warn{color:#facc15}.err{color:#f87171}
@media(max-width:900px){.container{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="container">
  <div class="card">
    <h1>Camera Calibration Stream</h1>
    <div class="small" style="margin-bottom:10px">
      Live camera feed. The server detects the chessboard continuously; Capture saves only frames with a detected board.
    </div>
    <div class="stream-wrap">
      <img src="/video_feed" alt="Live calibration camera feed">
    </div>

    <details open style="margin-top:12px">
      <summary>Vision debug: what the chessboard detector sees</summary>
      <div class="debug-controls">
        <div class="row">
          <label for="debug_view">View</label>
          <select id="debug_view">
            <option value="gray">Gray (detector input)</option>
            <option value="normalized">Gray + auto contrast</option>
            <option value="fixed">Fixed black/white</option>
            <option value="otsu">Otsu black/white</option>
            <option value="adaptive">Adaptive black/white</option>
          </select>
        </div>
        <div class="row">
          <label for="debug_threshold">Fixed threshold</label>
          <input id="debug_threshold" type="range" min="0" max="255" step="1" value="128">
          <span id="debug_threshold_value">128</span>
        </div>
        <div class="row">
          <label for="debug_adaptive_c">Adaptive C</label>
          <input id="debug_adaptive_c" type="range" min="-20" max="20" step="1" value="5">
          <span id="debug_adaptive_c_value">5</span>
        </div>
        <div class="debug-note">
          The actual chessboard detector receives grayscale. The black/white modes below
          are diagnostic views for tuning lighting/contrast; they do not change calibration.
        </div>
        <div class="debug-preview">
          <img id="debug_preview" alt="Calibration detector debug view">
        </div>
      </div>
    </details>
  </div>

  <div class="card controls">
    <div>
      <strong>Capture / Calibration</strong>
      <div class="small">Use different board positions, tilt, distance, and image coverage.</div>
    </div>

    <details open>
      <summary>Board configuration</summary>
      <div class="status">
      <div><strong>Physical checkerboard</strong></div>
      <div class="row">
        <label for="board_cols">Squares across</label>
        <input id="board_cols" type="number" min="2" max="100" step="1" value="12">
      </div>
      <div class="row">
        <label for="board_rows">Squares down</label>
        <input id="board_rows" type="number" min="2" max="100" step="1" value="8">
      </div>
      <div class="row">
        <label for="square_size">Square size (mm)</label>
        <input id="square_size" type="number" min="0.001" step="0.1" value="1">
      </div>
      <div class="row">
        <label for="min_valid_images">Minimum valid images</label>
        <input id="min_valid_images" type="number" min="3" max="500" step="1" value="10">
      </div>
      <div class="small">
        Inner corners: <span id="inner_corners">11 × 7</span>
        · Physical board: <span id="board_physical_size">12 × 8 mm</span>
      </div>
      <button class="ghost" id="apply_board">Apply board settings</button>
      </div>
    </details>

    <details open>
      <summary>Detection & auto capture</summary>
      <div class="status">
        <div class="row">
          <label for="detector_mode">Detector</label>
          <select id="detector_mode">
            <option value="auto">Auto (Classic → SB)</option>
            <option value="classic">Classic</option>
            <option value="sb">SB (robust)</option>
          </select>
        </div>
        <label class="check">
          <input id="auto_capture_enabled" type="checkbox">
          Auto-capture valid detections
        </label>
        <div class="row">
          <label for="auto_capture_interval">Auto-capture interval (s)</label>
          <input id="auto_capture_interval" type="number" min="0.2" max="30" step="0.1" value="1">
        </div>
        <div class="small">Only quality-approved detections are captured; duplicate views are filtered.</div>
        <button class="ghost" id="apply_detection">Apply detection options</button>
      </div>
    </details>

    <details>
      <summary>Quality thresholds</summary>
      <div class="status">
        <div class="row">
          <label for="min_coverage">Minimum coverage</label>
          <input id="min_coverage" type="number" min="0.001" max="1" step="0.001" value="0.03">
        </div>
        <div class="row">
          <label for="min_sharpness">Minimum sharpness</label>
          <input id="min_sharpness" type="number" min="0.1" step="1" value="20">
        </div>
        <div class="row">
          <label for="min_edge_margin">Minimum edge margin</label>
          <input id="min_edge_margin" type="number" min="0.001" max="0.5" step="0.001" value="0.01">
        </div>
        <div class="row">
          <label for="duplicate_distance">Duplicate distance</label>
          <input id="duplicate_distance" type="number" min="0.001" max="5" step="0.005" value="0.05">
        </div>
        <button class="ghost" id="apply_quality">Apply quality thresholds</button>
      </div>
    </details>

    <details>
      <summary>Captured images</summary>
      <div class="status">
        <select id="capture_select" style="width:100%"></select>
        <img id="capture_preview" alt="Selected calibration capture" style="display:none;width:100%;max-height:300px;object-fit:contain;background:#000;border-radius:8px">
        <div class="small">Newest captures appear first.</div>
      </div>
    </details>

    <div class="status">
      <div>Detection: <span id="detection" class="warn">waiting</span></div>
      <div>Detector: <span id="detector" class="small">-</span></div>
      <div>Capture: <span id="capture_eligible" class="warn">-</span></div>
      <div>Auto-captured: <span id="auto_captured">0</span></div>
      <div>Captured: <span id="captured">0</span></div>
      <div>Camera: <span id="camera">-</span></div>
      <div>Requested FPS: <span id="requested_fps">-</span></div>
      <div>Measured FPS: <span id="actual_fps">-</span></div>
      <div>FPS limits: <span id="fps_limits">-</span></div>
      <div>Calibration: <span id="calibration_state">not calibrated</span></div>
      <div id="metrics" class="small"></div>
      <div id="rejection" class="small err"></div>
    </div>

    <div class="row">
      <label for="fps">Camera FPS</label>
      <input id="fps" type="number" min="1" max="120" step="1" value="30">
    </div>
    <button class="primary" id="apply_fps">Apply camera FPS</button>

    <div class="row">
      <button class="primary" id="capture">Capture valid frame</button>
      <button class="ghost" id="clear">Clear captures</button>
    </div>

    <button class="primary" id="calibrate">Run calibration</button>
    <button class="ghost" id="preview_model" disabled>Run with calibration model</button>
    <div class="small">
      Output: <code>assets/camera_calibration.npz</code>
    </div>
  </div>
</div>

<script>
let boardSettingsLoaded=false;

function applyBoardState(s){
  document.getElementById('board_cols').value=s.board_squares[0];
  document.getElementById('board_rows').value=s.board_squares[1];
  document.getElementById('square_size').value=Number(s.square_size).toFixed(2);
  document.getElementById('min_valid_images').value=s.min_valid_images;
  document.getElementById('inner_corners').textContent=
    s.checkerboard_inner_corners[0] + ' × ' +
    s.checkerboard_inner_corners[1];
  document.getElementById('board_physical_size').textContent=
    (s.board_squares[0] * Number(s.square_size)).toFixed(1) + ' × ' +
    (s.board_squares[1] * Number(s.square_size)).toFixed(1) + ' mm';
}

let detectionSettingsLoaded=false;
let qualitySettingsLoaded=false;
let lastKnownCaptureCount=-1;

let debugTimer=null;

function updateDebugLabels(){
  document.getElementById('debug_threshold_value').textContent =
    document.getElementById('debug_threshold').value;
  document.getElementById('debug_adaptive_c_value').textContent =
    document.getElementById('debug_adaptive_c').value;
}

function refreshDebugFrame(){
  const view=document.getElementById('debug_view').value;
  const threshold=document.getElementById('debug_threshold').value;
  const adaptiveC=document.getElementById('debug_adaptive_c').value;
  const url =
    '/api/debug_frame?view=' + encodeURIComponent(view) +
    '&threshold=' + encodeURIComponent(threshold) +
    '&adaptive_c=' + encodeURIComponent(adaptiveC) +
    '&t=' + Date.now();
  document.getElementById('debug_preview').src=url;
}

function startDebugLoop(){
  clearInterval(debugTimer);
  updateDebugLabels();
  refreshDebugFrame();
  debugTimer=setInterval(refreshDebugFrame, 250);
}

document.getElementById('debug_view').addEventListener('change',refreshDebugFrame);
document.getElementById('debug_threshold').addEventListener('input',()=>{
  updateDebugLabels();
  if(document.getElementById('debug_view').value==='fixed') refreshDebugFrame();
});
document.getElementById('debug_adaptive_c').addEventListener('input',()=>{
  updateDebugLabels();
  if(document.getElementById('debug_view').value==='adaptive') refreshDebugFrame();
});

async function getStatus(){
  try{
    const r=await fetch('/api/status');
    const s=await r.json();
    document.getElementById('captured').textContent=s.captured_images;
    document.getElementById('auto_captured').textContent=s.auto_captured_images;

    if(!detectionSettingsLoaded){
      document.getElementById('detector_mode').value=s.detector_mode;
      document.getElementById('auto_capture_enabled').checked=s.auto_capture_enabled;
      document.getElementById('auto_capture_interval').value=Number(s.auto_capture_interval).toFixed(1);
      detectionSettingsLoaded=true;
    }
    if(!qualitySettingsLoaded){
      document.getElementById('min_coverage').value=Number(s.min_coverage).toFixed(3);
      document.getElementById('min_sharpness').value=Number(s.min_sharpness).toFixed(1);
      document.getElementById('min_edge_margin').value=Number(s.min_edge_margin).toFixed(3);
      document.getElementById('duplicate_distance').value=Number(s.duplicate_distance).toFixed(3);
      qualitySettingsLoaded=true;
    }
    if(lastKnownCaptureCount !== s.captured_images){
      lastKnownCaptureCount=s.captured_images;
      refreshCaptures(false);
    }

    if(!boardSettingsLoaded){
      applyBoardState(s);
      boardSettingsLoaded=true;
    }
    document.getElementById('capture_eligible').textContent =
      s.capture_eligible ? 'ready' : 'not ready';
    document.getElementById('capture_eligible').className =
      s.capture_eligible ? 'ok' : 'warn';
    document.getElementById('fps_limits').textContent =
      s.camera_fps_limits === null ? '-' :
      Number(s.camera_fps_limits[0]).toFixed(1) + ' - ' +
      Number(s.camera_fps_limits[1]).toFixed(1) + ' FPS';
    document.getElementById('rejection').textContent =
      s.last_rejection_reason || '';
    document.getElementById('camera').textContent=
      s.camera_mode + ' / ' + s.width + 'x' + s.height;
    document.getElementById('requested_fps').textContent=
      Number(s.requested_fps).toFixed(1);
    document.getElementById('actual_fps').textContent=
      s.actual_fps === null ? '-' : Number(s.actual_fps).toFixed(1);

    const detection=document.getElementById('detection');
    document.getElementById('preview_model').disabled =
      s.calibration_state !== 'calibrated';
    document.getElementById('preview_model').textContent =
      s.calibration_preview_enabled
        ? 'Show raw camera'
        : 'Run with calibration model';

    document.getElementById('detector').textContent =
      s.detector === 'sb'
        ? 'SB (robust)'
        : s.detector === 'classic'
          ? 'classic'
          : 'not found';
    detection.textContent=s.chessboard_detected
      ? 'detected'
      : 'not detected';
    detection.className=s.chessboard_detected ? 'ok' : 'warn';

    document.getElementById('calibration_state').textContent=
      s.calibration_state;
    document.getElementById('metrics').textContent=
      s.last_calibration_error === null
        ? ''
        : 'RMS: ' + Number(s.last_calibration_error).toFixed(4) +
          ' | reprojection: ' +
          Number(s.mean_reprojection_error || 0).toFixed(4);
  }catch(_){}
}

async function post(url, body){
  const r=await fetch(url,{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify(body || {})
  });
  return r.json();
}

document.getElementById('apply_fps').onclick=async()=>{
  const fps=Number(document.getElementById('fps').value);
  const result=await post('/api/settings',{fps});
  if(!result.success) alert(result.message || 'Failed to update FPS');
};

document.getElementById('apply_board').onclick=async()=>{
  const button=document.getElementById('apply_board');
  const payload={
    board_cols:Number(document.getElementById('board_cols').value),
    board_rows:Number(document.getElementById('board_rows').value),
    square_size:Number(document.getElementById('square_size').value),
    min_valid_images:Number(document.getElementById('min_valid_images').value)
  };

  button.disabled=true;
  const result=await post('/api/settings',payload);
  button.disabled=false;

  if(!result.success){
    alert(result.message || 'Failed to update board settings');
    return;
  }

  applyBoardState(result);
  boardSettingsLoaded=true;
  alert(
    'Board settings applied: ' +
    result.board_squares[0] + ' × ' +
    result.board_squares[1] + ' squares, ' +
    Number(result.square_size).toFixed(2) + ' mm.'
  );
};

document.getElementById('apply_detection').onclick=async()=>{
  const result=await post('/api/settings',{
    detector_mode:document.getElementById('detector_mode').value,
    auto_capture_enabled:document.getElementById('auto_capture_enabled').checked,
    auto_capture_interval:Number(document.getElementById('auto_capture_interval').value)
  });
  if(!result.success){
    alert(result.message || 'Failed to update detection options');
    return;
  }
  detectionSettingsLoaded=true;
  alert('Detection options applied.');
};

document.getElementById('apply_quality').onclick=async()=>{
  const result=await post('/api/settings',{
    min_coverage:Number(document.getElementById('min_coverage').value),
    min_sharpness:Number(document.getElementById('min_sharpness').value),
    min_edge_margin:Number(document.getElementById('min_edge_margin').value),
    duplicate_distance:Number(document.getElementById('duplicate_distance').value)
  });
  if(!result.success){
    alert(result.message || 'Failed to update quality thresholds');
    return;
  }
  qualitySettingsLoaded=true;
  alert('Quality thresholds applied.');
};

async function refreshCaptures(selectNewest=true){
  try{
    const response=await fetch('/api/captures');
    const data=await response.json();
    const select=document.getElementById('capture_select');
    const previous=select.value;
    select.innerHTML='';
    for(const item of data.captures){
      const option=document.createElement('option');
      option.value=item.url;
      option.textContent=item.filename;
      select.appendChild(option);
    }
    if(data.captures.length){
      select.value=selectNewest ? data.captures[0].url : previous;
      if(!select.value) select.value=data.captures[0].url;
      const preview=document.getElementById('capture_preview');
      preview.src=select.value;
      preview.style.display='block';
    }else{
      document.getElementById('capture_preview').style.display='none';
    }
  }catch(_){}
}

document.getElementById('capture_select').onchange=()=>{
  const value=document.getElementById('capture_select').value;
  const preview=document.getElementById('capture_preview');
  if(value){
    preview.src=value;
    preview.style.display='block';
  }
};

document.getElementById('preview_model').onclick=async()=>{
  const enabled=document.getElementById('preview_model').textContent.includes('Run with');
  const result=await post('/api/preview',{enabled});
  if(!result.success){
    alert(result.message || 'Failed to toggle calibration preview');
  }
};

document.getElementById('capture').onclick=async()=>{
  const result=await post('/api/capture');
  alert(result.message || (result.saved ? 'Captured' : 'Not captured'));
  if(result.saved) await refreshCaptures(true);
};

document.getElementById('clear').onclick=async()=>{
  if(!confirm('Delete captured calibration images?')) return;
  const result=await post('/api/clear');
  alert(result.message || 'Done');
  await refreshCaptures(true);
};

document.getElementById('calibrate').onclick=async()=>{
  const result=await post('/api/calibrate');
  alert(result.message || 'Calibration started');
};

function updateBoardPreview(){
  const cols=Number(document.getElementById('board_cols').value);
  const rows=Number(document.getElementById('board_rows').value);
  const size=Number(document.getElementById('square_size').value);
  if(cols >= 2 && rows >= 2){
    document.getElementById('inner_corners').textContent=(cols-1)+' × '+(rows-1);
  }
  if(cols >= 2 && rows >= 2 && size > 0){
    document.getElementById('board_physical_size').textContent=
      (cols*size).toFixed(1)+' × '+(rows*size).toFixed(1)+' mm';
  }
}
['board_cols','board_rows','square_size'].forEach(id=>{
  document.getElementById(id).addEventListener('input',updateBoardPreview);
});
updateBoardPreview();

refreshCaptures(true);
getStatus();
startDebugLoop();
setInterval(getStatus,500);
</script>
</body>
</html>
"""
