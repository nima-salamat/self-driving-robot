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
.controls{display:grid;gap:10px}
.row{display:flex;gap:8px;align-items:center;justify-content:space-between;flex-wrap:wrap}
button,input{font:inherit}
button{border:0;border-radius:8px;padding:8px 12px;cursor:pointer}
.primary{background:var(--accent);color:#012}
.ghost{background:transparent;border:1px solid rgba(255,255,255,.1);color:var(--txt)}
input{background:#071428;color:var(--txt);border:1px solid rgba(255,255,255,.1);border-radius:7px;padding:7px;width:100px}
.status{display:grid;gap:6px;padding:10px;background:#050b15;border-radius:8px;font-size:13px}
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
  </div>

  <div class="card controls">
    <div>
      <strong>Capture / Calibration</strong>
      <div class="small">Use different board positions, tilt, distance, and image coverage.</div>
    </div>

    <div class="status">
      <div>Detection: <span id="detection" class="warn">waiting</span></div>
      <div>Captured: <span id="captured">0</span></div>
      <div>Camera: <span id="camera">-</span></div>
      <div>Requested FPS: <span id="requested_fps">-</span></div>
      <div>Measured FPS: <span id="actual_fps">-</span></div>
      <div>Calibration: <span id="calibration_state">not calibrated</span></div>
      <div id="metrics" class="small"></div>
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
    <div class="small">
      Output: <code>assets/camera_calibration.npz</code>
    </div>
  </div>
</div>

<script>
async function getStatus(){
  try{
    const r=await fetch('/api/status');
    const s=await r.json();
    document.getElementById('captured').textContent=s.captured_images;
    document.getElementById('camera').textContent=
      s.camera_mode + ' / ' + s.width + 'x' + s.height;
    document.getElementById('requested_fps').textContent=
      Number(s.requested_fps).toFixed(1);
    document.getElementById('actual_fps').textContent=
      s.actual_fps === null ? '-' : Number(s.actual_fps).toFixed(1);

    const detection=document.getElementById('detection');
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

document.getElementById('capture').onclick=async()=>{
  const result=await post('/api/capture');
  alert(result.message || (result.saved ? 'Captured' : 'Not captured'));
};

document.getElementById('clear').onclick=async()=>{
  if(!confirm('Delete captured calibration images?')) return;
  const result=await post('/api/clear');
  alert(result.message || 'Done');
};

document.getElementById('calibrate').onclick=async()=>{
  const result=await post('/api/calibrate');
  alert(result.message || 'Calibration started');
};

getStatus();
setInterval(getStatus,500);
</script>
</body>
</html>
"""
