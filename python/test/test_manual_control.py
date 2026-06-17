
import sys
import os
prev_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(prev_dir)

import os
import time
import json
import threading
import logging
import signal
from math import hypot
from pathlib import Path

from flask import Flask, Response, render_template_string, request
from flask_socketio import SocketIO, emit, disconnect

try:
    import cv2
except Exception:
    cv2 = None

try:
    import modes.city.config_city as config_city
except Exception:
    class _Cfg: pass
    config_city = _Cfg()
    config_city.SERVO_CENTER = 90
    config_city.SPEED = 255

# Camera adapter: try project camera, else dummy
try:
    from vision.camera import Camera
except Exception:
    try:
        import numpy as np
    except Exception:
        np = None
    class Camera:
        def __init__(self):
            self._w, self._h = 640, 360
        def capture_frame(self, resize=False):
            if np is None or cv2 is None:
                return None
            return (50 * np.ones((self._h, self._w, 3), dtype='uint8'))
        def release(self): pass

# Controller adapter: try project controller, else dummy
try:
    from controller import controller as hw
except Exception:
    class _DummyHW:
        def set_angle(self, a): logging.getLogger().info("DHW angle=%s", a)
        def set_speed(self, s): logging.getLogger().info("DHW speed=%s", s)
        def stop(self): logging.getLogger().info("DHW STOP")
        @property
        def connection(self): return None
    hw = _DummyHW()

# ---------- Config ----------
HOST = os.getenv('MANUAL_HOST', '0.0.0.0')
PORT = int(os.getenv('MANUAL_PORT', '5010'))
MANUAL_TOKEN = os.getenv('MANUAL_TOKEN', 'changeme')
STATE_FILE = os.getenv('MANUAL_STATE_FILE', 'manual_enterprise_settings.json')
Path('.').mkdir(parents=True, exist_ok=True)

SERVO_CENTER = getattr(config_city, 'SERVO_CENTER', 90)
DEFAULT_MAX_SPEED = getattr(config_city, 'SPEED', 255)

CONTROL_HZ = 60.0
UI_HZ = 20.0
WATCHDOG_MULT = 3.0

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(name)s: %(message)s')
log = logging.getLogger('manual_enterprise')

# ---------- Defaults & persistence ----------
def default_settings():
    return {
        'deadman': 1.0,
        'jpeg_quality': 70,
        'max_speed': DEFAULT_MAX_SPEED,
        'speed_limit': DEFAULT_MAX_SPEED,
        'angle_limit_deg': 60.0,
        'angle_trim': 0.0,
        'smoothing_mode': 'alpha',  # 'alpha' or 'pid'
        'angle_alpha': 0.18,
        'speed_alpha': 0.20,
        'angle_pid': [2.0, 0.0, 0.25],
        'speed_pid': [3.0, 0.0, 0.15],
        'keyboard_sensitivity': 1.0,
        'invert_mobile_y': False,
        'record_inputs': False
    }

def load_settings():
    s = default_settings()
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                j = json.load(f)
            s.update(j)
        except Exception:
            log.exception('load settings failed')
    return s

def save_settings(s):
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(s, f, indent=2)
    except Exception:
        log.exception('save settings failed')

# ---------- State ----------
settings = load_settings()
state_lock = threading.Lock()
state = {
    'angle': float(SERVO_CENTER) + float(settings.get('angle_trim', 0.0)),
    'speed': 0.0,
    'angle_target': float(SERVO_CENTER) + float(settings.get('angle_trim', 0.0)),
    'speed_target': 0.0,
    'last_ui': time.monotonic(),
    'last_cmd': time.monotonic(),
    'clients': {},
    'seq_seen': {},
    'settings': settings
}

cam = Camera()

# ---------- PID ----------
class PID:
    def __init__(self, kp, ki, kd, imax=1000.0):
        self.kp, self.ki, self.kd = kp, ki, kd
        self.i = 0.0
        self.last = None
        self.imax = imax
    def step(self, target, value, dt):
        err = target - value
        self.i += err * dt
        if self.i > self.imax: self.i = self.imax
        if self.i < -self.imax: self.i = -self.imax
        d = 0.0 if self.last is None else (err - self.last) / dt
        self.last = err
        return self.kp*err + self.ki*self.i + self.kd*d

pid_angle = PID(*settings.get('angle_pid', [2.0,0,0.25]))
pid_speed = PID(*settings.get('speed_pid', [3.0,0,0.15]))

# ---------- Flask + SocketIO ----------
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins='*', async_mode='threading')

# ---------- Socket handlers ----------
@socketio.on('connect')
def on_connect(auth):
    token = request.args.get('token') or (auth.get('token') if isinstance(auth, dict) else None)
    sid = request.sid
    log.info('connect attempt sid=%s token=%s', sid, str(token)[:10])
    if token != MANUAL_TOKEN:
        log.warning('rejecting connect sid=%s (bad token)', sid)
        disconnect()
        return
    with state_lock:
        state['clients'][sid] = {'last_seen': time.monotonic()}
    emit('init', {'angle': state['angle'], 'speed': state['speed'], 'settings': state['settings']})
    log.info('client connected %s', sid)

@socketio.on('disconnect')
def on_disconnect():
    sid = request.sid
    log.info('disconnect %s', sid)
    with state_lock:
        state['clients'].pop(sid, None)
        state['seq_seen'].pop(sid, None)

@socketio.on('input')
def on_input(msg):
    sid = request.sid
    seq = msg.get('seq')
    if seq is None:
        emit('cmd_nack', {'seq': None, 'err': 'no_seq'})
        return
    with state_lock:
        last = state['seq_seen'].get(sid)
        if last is not None and seq <= last:
            emit('cmd_ack', {'seq': seq})
            return
        state['seq_seen'][sid] = seq
        state['last_cmd'] = time.monotonic()
        state['clients'].setdefault(sid, {})['last_seen'] = time.monotonic()
        state['last_ui'] = time.monotonic()

        try:
            forward = float(msg.get('forward', 0.0))
            steer = float(msg.get('steer', 0.0))
            speed_scale = float(msg.get('speed_scale', 1.0))
        except Exception:
            emit('cmd_nack', {'seq': seq, 'err': 'bad_payload'})
            return

        forward = max(-1.0, min(1.0, forward))
        steer = max(-1.0, min(1.0, steer))
        speed_scale = max(0.0, min(1.0, speed_scale))

        s = state['settings']
        if msg.get('is_mobile') and s.get('invert_mobile_y', False):
            forward = -forward

        angle_limit = float(s.get('angle_limit_deg', 60.0))
        angle_target = SERVO_CENTER + float(s.get('angle_trim', 0.0)) + steer * angle_limit
        angle_target = max(0.0, min(180.0, angle_target))

        max_speed = int(s.get('speed_limit', s.get('max_speed', DEFAULT_MAX_SPEED)))
        speed_target = max_speed * forward * speed_scale

        state['angle_target'] = angle_target
        state['speed_target'] = speed_target

    emit('cmd_ack', {'seq': seq})

@socketio.on('set_setting')
def on_set_setting(msg):
    key = msg.get('key')
    val = msg.get('value')
    if key is None: return
    with state_lock:
        s = state['settings']
        try:
            if key in ('deadman','angle_alpha','speed_alpha','angle_limit_deg','speed_limit','keyboard_sensitivity','angle_trim'):
                s[key] = float(val)
            elif key in ('jpeg_quality','max_speed'):
                s[key] = int(val)
            elif key in ('invert_mobile_y','record_inputs'):
                s[key] = bool(val)
            elif key == 'smoothing_mode' and val in ('alpha','pid'):
                s[key] = val
            elif key in ('angle_pid','speed_pid') and isinstance(val, (list,tuple)) and len(val)==3:
                s[key] = [float(v) for v in val]
            else:
                pass
            # rebuild PID
            global pid_angle, pid_speed
            pid_angle = PID(*s.get('angle_pid', [2.0,0,0.25]))
            pid_speed = PID(*s.get('speed_pid', [3.0,0,0.15]))
            save_settings(s)
            emit('setting_ack', {'key': key, 'value': s.get(key)})
        except Exception:
            log.exception('set_setting fail')

@socketio.on('heartbeat')
def on_heartbeat(msg):
    sid = request.sid
    with state_lock:
        state['last_ui'] = time.monotonic()
        state['clients'].setdefault(sid, {})['last_seen'] = time.monotonic()
    emit('heartbeat_ack', {'t': msg.get('t'), 'server': time.time()})

# ---------- Broadcaster ----------
def broadcaster():
    interval = 1.0 / UI_HZ
    while True:
        with state_lock:
            payload = {
                'angle': state['angle'], 'speed': state['speed'],
                'angle_target': state['angle_target'], 'speed_target': state['speed_target'],
                'settings': state['settings'], 'clients': len(state['clients'])
            }
        socketio.emit('state', payload)
        socketio.sleep(interval)

# ---------- Control loop ----------
_stop = threading.Event()
def control_loop():
    global pid_angle, pid_speed
    last = time.monotonic()
    interval = 1.0 / CONTROL_HZ
    while not _stop.is_set():
        now = time.monotonic()
        dt = max(1e-4, now - last)
        last = now
        with state_lock:
            s = state
            sett = s['settings']
            if now - s['last_ui'] > sett.get('deadman',1.0):
                s['speed_target'] = 0.0
            if sett.get('smoothing_mode','alpha') == 'pid':
                a_cmd = pid_angle.step(s['angle_target'], s['angle'], dt)
                sp_cmd = pid_speed.step(s['speed_target'], s['speed'], dt)
                s['angle'] += a_cmd * dt
                s['speed'] += sp_cmd * dt
            else:
                aa = float(sett.get('angle_alpha',0.18))
                sa = float(sett.get('speed_alpha',0.20))
                scale = dt * CONTROL_HZ
                a_alpha = 1.0 - pow(1.0-aa, scale)
                s_alpha = 1.0 - pow(1.0-sa, scale)
                s['angle'] += (s['angle_target'] - s['angle']) * a_alpha
                s['speed'] += (s['speed_target'] - s['speed']) * s_alpha
            s['angle'] = max(0.0, min(180.0, s['angle']))
            maxs = int(sett.get('speed_limit', sett.get('max_speed', DEFAULT_MAX_SPEED)))
            s['speed'] = max(-maxs, min(maxs, s['speed']))
            angle_hw = int(round(s['angle']))
            speed_hw = int(round(s['speed']))
        try:
            hw.set_angle(angle_hw)
            if abs(speed_hw) < 3:
                hw.stop()
            else:
                hw.set_speed(speed_hw)
        except Exception:
            log.exception('hardware apply error')
        with state_lock:
            if time.monotonic() - state['last_ui'] > state['settings'].get('deadman',1.0) * WATCHDOG_MULT:
                try:
                    hw.stop()
                    state['speed_target'] = 0.0
                except Exception:
                    pass
        time.sleep(interval)

# ---------- MJPEG ----------
def mjpeg_stream():
    while True:
        frame = cam.capture_frame(resize=False)
        if frame is None:
            time.sleep(0.01); continue
        q = int(state['settings'].get('jpeg_quality',70))
        if cv2 is None:
            time.sleep(0.1); continue
        ok, jpg = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), q])
        if not ok:
            time.sleep(0.01); continue
        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg.tobytes() + b"\r\n")

# ---------- UI (full HTML + JS) ----------
INDEX_HTML = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"/>
<title>Robot — Pro Manual Controller</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap" rel="stylesheet">
<style>
:root{
  --bg0:#03121a; --card:#071a20; --glass:rgba(255,255,255,0.04);
  --accent:#06c3d8; --danger:#ff5c5c; --muted:#a8bdc6; --text:#eaf6f8;
  --radius:12px; --glass-2: rgba(255,255,255,0.02);
}
*{box-sizing:border-box;font-family:Inter,system-ui,-apple-system,Segoe UI,Roboto,Arial}
html,body{height:100%;margin:0;background:linear-gradient(180deg,var(--bg0),#062431);color:var(--text);overflow:hidden}
img#video{position:fixed;inset:0;width:100%;height:100%;object-fit:cover;z-index:0;background:#000}

/* HUD */
.hud{position:fixed;left:16px;top:16px;background:rgba(0,0,0,0.45);padding:10px 14px;border-radius:14px;z-index:40;display:flex;gap:16px;align-items:center;font-weight:700}
.hud .item{font-size:13px;color:var(--muted);display:flex;flex-direction:column}
.hud .item strong{color:var(--text);font-size:15px;margin-top:4px}

/* TOP BUTTONS */
.top-controls{position:fixed;right:16px;top:16px;display:flex;gap:8px;z-index:40}
.btn{background:var(--accent);border:none;color:#012;padding:8px 12px;border-radius:10px;font-weight:700;cursor:pointer;box-shadow:0 10px 28px rgba(0,0,0,0.55)}
.btn.ghost{background:transparent;border:1px solid rgba(255,255,255,0.04);color:var(--muted)}
.small-btn{padding:6px 8px;font-size:13px;border-radius:8px}

/* JOYSTICK */
.joy{position:fixed;left:14px;bottom:14px;width:180px;height:180px;border-radius:50%;background:linear-gradient(180deg,var(--glass-2),rgba(0,0,0,0.05));z-index:45;display:flex;align-items:center;justify-content:center;touch-action:none;box-shadow:0 12px 40px rgba(0,0,0,0.6)}
.knob{width:64px;height:64px;border-radius:50%;background:var(--accent);box-shadow:0 8px 22px rgba(0,0,0,0.6);transform:translate(0,0);transition:transform 0.02s linear}

/* PEDAL */
.pedal{position:fixed;right:14px;bottom:14px;width:86px;height:240px;border-radius:12px;background:var(--glass);z-index:45;padding:12px;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;gap:8px;box-shadow:0 12px 40px rgba(0,0,0,0.6)}
.pedal .track{position:relative;width:44px;height:180px;background:rgba(255,255,255,0.03);border-radius:22px;overflow:hidden}
.pedal .thumb{position:absolute;left:50%;transform:translate(-50%,0);width:56px;height:36px;border-radius:10px;background:linear-gradient(180deg,var(--accent),#0aa9c0);box-shadow:0 6px 18px rgba(0,0,0,0.6)}
.pedal .label{font-size:13px;color:var(--muted)}

/* E-STOP */
.estop{position:fixed;right:14px;bottom:270px;z-index:45}
.estop button{background:var(--danger);border:none;color:white;padding:14px;border-radius:12px;font-weight:800;cursor:pointer;min-width:120px;box-shadow:0 18px 40px rgba(0,0,0,0.6)}

/* QUICK PANEL */
.quick{position:fixed;left:50%;bottom:0;transform:translateX(-50%);width:100%;max-width:560px;background:linear-gradient(180deg, rgba(0,0,0,0.45), rgba(0,0,0,0.28));padding:12px;border-radius:12px 12px 0 0;z-index:38;transition:transform .28s}
.quick.closed{transform:translateX(-50%) translateY(86%)}
.quick .handle{text-align:center;color:var(--muted);font-size:13px;cursor:pointer}
.row-flex{display:flex;gap:12px;align-items:center}

/* MODAL */
.overlay{position:fixed;inset:0;background:rgba(0,0,0,0.6);display:none;align-items:center;justify-content:center;z-index:60}
.overlay.show{display:flex}
.modal{width:min(920px,96vw);max-width:920px;background:linear-gradient(180deg,#071a20,#042127);padding:18px;border-radius:12px;color:var(--text);box-shadow:0 30px 80px rgba(0,0,0,0.7);max-height:86vh;overflow:auto}
.modal h3{margin:0 0 8px 0}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.form-line{display:flex;flex-direction:column;gap:6px;margin-top:12px}
.form-line label{color:var(--muted);font-size:13px}
.form-row{display:flex;align-items:center;justify-content:space-between;gap:8px}
.range{width:100%}
.value-badge{min-width:66px;text-align:center;background:rgba(255,255,255,0.03);padding:6px;border-radius:8px;color:var(--muted)}

/* small screens */
@media(max-width:820px){
  .grid{grid-template-columns:1fr}
  .joy{left:8px;bottom:12px;width:150px;height:150px}
  .knob{width:52px;height:52px}
  .estop button{min-width:100px}
}
</style>
</head>
<body>

<img id="video" src="/video_feed" alt="live camera">

<!-- HUD -->
<div class="hud" id="hud">
  <div class="item">Speed <strong id="hud_speed">0</strong></div>
  <div class="item">Angle <strong id="hud_angle">90</strong></div>
  <div class="item">Clients <strong id="hud_clients">0</strong></div>
  <div class="item">Ping <strong id="hud_ping">— ms</strong></div>
</div>

<!-- top -->
<div class="top-controls">
  <button id="btnSettings" class="btn ghost small-btn">Settings</button>
  <button id="btnFull" class="btn small-btn">Fullscreen</button>
</div>

<!-- joystick -->
<div class="joy" id="joy" aria-label="joystick">
  <div class="knob" id="knob"></div>
</div>

<!-- pedal -->
<div class="pedal" id="pedal">
  <div class="label">Brake / Throttle</div>
  <div class="track" id="pedal_track">
    <div class="thumb" id="pedal_thumb"></div>
  </div>
  <div class="label" id="pedal_val">0%</div>
</div>

<!-- E-STOP -->
<div class="estop"><button id="estop_btn">E-STOP</button></div>

<!-- quick -->
<div class="quick" id="quickPanel">
  <div class="handle" id="quickToggle">▲ Quick Control (tap to toggle)</div>
  <div class="row-flex" style="margin-top:10px">
    <div style="flex:1">
      <div class="form-row"><label class="label">Speed limit</label><div class="value-badge" id="speed_limit_lbl">255</div></div>
      <input id="speed_limit" class="range" type="range" min="0" max="1023" value="255">
    </div>
    <div style="width:12px"></div>
    <div style="flex:1">
      <div class="form-row"><label class="label">Angle limit</label><div class="value-badge" id="angle_limit_lbl">60°</div></div>
      <input id="angle_limit" class="range" type="range" min="10" max="90" value="60">
    </div>
  </div>
</div>

<!-- settings modal -->
<div id="overlay" class="overlay" role="dialog" aria-modal="true">
  <div class="modal" role="document" id="settings_modal">
    <h3>Advanced Settings</h3>
    <div class="grid">
      <div>
        <div class="form-line">
          <label>Deadman (s)</label>
          <div class="form-row"><input id="deadman" type="number" step="0.1" min="0.2" max="10" value="1.0"><div class="value-badge">sec</div></div>
        </div>

        <div class="form-line">
          <label>JPEG quality</label>
          <div class="form-row"><input id="jpegq" type="number" min="10" max="95" value="70"><div class="value-badge">%</div></div>
        </div>

        <div class="form-line">
          <label>Max speed (HW)</label>
          <div class="form-row"><input id="max_speed" type="number" min="0" max="4096" value="255"><div class="value-badge">units</div></div>
        </div>

        <div class="form-line">
          <label>Keyboard sensitivity</label>
          <div class="form-row"><input id="kb_sens" type="number" step="0.1" min="0.2" max="3.0" value="1.0"><div class="value-badge">x</div></div>
        </div>
      </div>
      
      <div class="form-line">
        <label>Keyboard return speed</label>
        <div class="form-row">
            <input
            id="kb_return"
            type="number"
            step="0.01"
            min="0.02"
            max="0.4"
            value="0.12">
            <div class="value-badge">rate</div>
        </div>
        </div>


      <div>
        <div class="form-line">
          <label>Smoothing (alpha)</label>
          <div class="form-row"><input id="alpha" type="number" step="0.01" min="0.01" max="0.9" value="0.18"><div class="value-badge" id="alpha_val">0.18</div></div>
        </div>

        <div class="form-line">
          <label>Joystick size (px)</label>
          <div class="form-row"><input id="jsize" type="number" min="120" max="300" value="180"><div class="value-badge" id="jsize_val">180</div></div>
        </div>

        <div class="form-line">
          <label>Joystick deadzone (%)</label>
          <div class="form-row"><input id="jdead" type="number" min="0" max="40" value="5"><div class="value-badge" id="jdead_val">5%</div></div>
        </div>

        <div class="form-line">
          <label>Pedal deadzone (%)</label>
          <div class="form-row"><input id="pdead" type="number" min="0" max="40" value="4"><div class="value-badge" id="pdead_val">4%</div></div>
        </div>
      </div>
    </div>

    <div style="margin-top:16px;display:flex;gap:10px;justify-content:flex-end">
      <button id="cancel_settings" class="btn ghost">Cancel</button>
      <button id="save_settings" class="btn">Save & Apply</button>
    </div>
  </div>
</div>

<script src="https://cdn.socket.io/4.7.2/socket.io.min.js"></script>
<script>
/* =========================
   English UI + Ping / Keyboard-steer fix
   ========================= */

/* Socket */
const TOKEN = prompt('MANUAL token (press enter to skip)','changeme') || 'changeme';
const socket = io({ query: { token: TOKEN } });

socket.on('connect', ()=> console.log('socket connected'));
socket.on('disconnect', ()=> console.log('socket disconnected'));
socket.on('connect_error', e => console.warn('socket error', e));

/* Show server state if provided */
socket.on('state', s => {
  if(s && typeof s.clients !== 'undefined') document.getElementById('hud_clients').textContent = s.clients;
});

/* Ping (heartbeat) — compute RTT when server replies with heartbeat_ack */
socket.on('heartbeat_ack', (m) => {
  // server should echo t back or include server time; we compute RTT using client's original t
  const now = Date.now();
  const sent = m.t || now;
  const rtt = Math.max(0, now - sent);
  document.getElementById('hud_ping').textContent = rtt + ' ms';
});

/* Basic send helpers */
let seq = 1;
function nextSeq(){ return seq++; }
function sendInput(payload){
  const p = {
    seq: nextSeq(),
    forward: Number(payload.forward || 0),
    steer: Number(payload.steer || 0),
    speed_scale: Number(payload.speed_scale || 1.0),
    t: Date.now(),
    is_mobile: /Mobi|Android|iPhone|iPad|iPod/.test(navigator.userAgent)
  };
  socket.emit('input', p);
}

/* Local storage helpers */
function ls(key){ return localStorage.getItem('man_'+key); }
function lsSet(key,v){ localStorage.setItem('man_'+key, String(v)); }


loadSettingsToUI();

/* UI refs */
const joy = document.getElementById('joy'), knob = document.getElementById('knob');
const pedalTrack = document.getElementById('pedal_track'), pedalThumb = document.getElementById('pedal_thumb'), pedalVal = document.getElementById('pedal_val');
const quickPanel = document.getElementById('quickPanel');
const overlay = document.getElementById('overlay');
const btnSettings = document.getElementById('btnSettings'), btnFull = document.getElementById('btnFull');
const estopBtn = document.getElementById('estop_btn');

/* Client settings/state */
let settings = {
  deadman: Number(document.getElementById('deadman').value),
  jpegq: Number(document.getElementById('jpegq').value),
  max_speed: Number(document.getElementById('max_speed').value),
  speed_limit: Number(document.getElementById('speed_limit').value || 255),
  angle_limit: Number(document.getElementById('angle_limit').value),
  alpha: Number(document.getElementById('alpha').value),
  jsize: Number(document.getElementById('jsize').value),
  jdead: Number(document.getElementById('jdead').value)/100.0,
  pdead: Number(document.getElementById('pdead').value)/100.0,
  kb_sens: Number(document.getElementById('kb_sens').value),
  kb_return: Number(document.getElementById('kb_return').value),

};

/* Apply joystick size */
function applyJoystickSize(){
  const px = Math.max(120, Math.min(300, Number(settings.jsize)));
  joy.style.width = px + 'px'; joy.style.height = px + 'px';
  const knobSize = Math.round(px * 0.35);
  knob.style.width = knobSize + 'px'; knob.style.height = knobSize + 'px';
}
applyJoystickSize();

/* Joystick implementation */
let pointerId = null, joyRect=null, origin=null, maxR=null;
let current = { forward: 0, steer: 0 };
let target = { forward: 0, steer: 0 };

function clamp(v,min,max){ return Math.max(min, Math.min(max, v)); }

function joyStart(e){
  const ev = e.touches ? e.changedTouches[0] : e;
  pointerId = (ev.pointerId !== undefined) ? ev.pointerId : ('t'+Date.now());
  try{ if(e.pointerId) e.target.setPointerCapture && e.target.setPointerCapture(e.pointerId); }catch(_){}
  joyRect = joy.getBoundingClientRect();
  origin = { x: joyRect.left + joyRect.width/2, y: joyRect.top + joyRect.height/2 };
  maxR = Math.min(joyRect.width, joyRect.height)/2 - 8;
  joyMove(e);
  e.preventDefault && e.preventDefault();
}
function joyMove(e){
  const ev = e.touches ? e.touches[0] : e;
  if(pointerId !== null && e.pointerId !== undefined && e.pointerId !== pointerId) return;
  if(!origin) return;
  let dx = ev.clientX - origin.x, dy = ev.clientY - origin.y;
  const d = Math.hypot(dx, dy);
  if(d > maxR){ dx = dx * (maxR/d); dy = dy * (maxR/d); }
  knob.style.transform = `translate(${dx}px, ${dy}px)`;
  const nx = dx / maxR;
  const ny = -dy / maxR; // up positive forward
  const fx = Math.abs(nx) < settings.jdead ? 0 : nx;
  const fy = Math.abs(ny) < settings.jdead ? 0 : ny;
  target.steer = clamp(fx, -1, 1);
  target.forward = clamp(fy, -1, 1);
}
function joyEnd(e){
  try{ if(e.pointerId) e.target.releasePointerCapture && e.target.releasePointerCapture(e.pointerId); }catch(_){}
  pointerId = null; joyRect = origin = maxR = null;
  knob.style.transform = 'translate(0, 0)';
  target.steer = 0; target.forward = 0;
}
joy.addEventListener('pointerdown', joyStart, {passive:false});
window.addEventListener('pointermove', (e)=>{ if(pointerId !== null) joyMove(e); }, {passive:false});
window.addEventListener('pointerup', (e)=>{ if(pointerId !== null) joyEnd(e); }, {passive:false});
joy.addEventListener('touchstart', (ev)=> joyStart(ev.changedTouches[0]), {passive:false});
joy.addEventListener('touchmove', (ev)=> joyMove(ev.changedTouches[0]), {passive:false});
joy.addEventListener('touchend', (ev)=> joyEnd(ev.changedTouches[0]), {passive:false});

/* Pedal */
let pedalRect=null, pedalActive=false;
function pedalStart(e){
  const ev = e.touches ? e.changedTouches[0] : e;
  pedalRect = pedalTrack.getBoundingClientRect();
  pedalActive = true;
  pedalMove(e);
  e.preventDefault && e.preventDefault();
}
function pedalMove(e){
  if(!pedalRect) return;
  const ev = e.touches ? e.touches[0] : e;
  const y = Math.max(0, Math.min(pedalRect.height, ev.clientY - pedalRect.top));
  const mid = pedalRect.height/2;
  const v = (mid - y) / mid; // -1..1
  const vdead = Math.abs(v) < settings.pdead ? 0 : v;
  const thumbY = y - (pedalThumb.offsetHeight/2);
  pedalThumb.style.top = thumbY + 'px';
  pedalVal.textContent = Math.round(vdead * 100) + '%';
  target.forward = clamp(vdead, -1, 1);
}
function pedalEnd(e){
  pedalActive = false; pedalRect = null;
  pedalThumb.style.top = (pedalTrack.clientHeight/2 - pedalThumb.offsetHeight/2) + 'px';
  pedalVal.textContent = '0%';
  if(pointerId === null) target.forward = 0;
}
pedalTrack.addEventListener('pointerdown', pedalStart, {passive:false});
window.addEventListener('pointermove', (e)=>{ if(pedalActive) pedalMove(e); }, {passive:false});
window.addEventListener('pointerup', (e)=>{ if(pedalActive) pedalEnd(e); }, {passive:false});
pedalTrack.addEventListener('touchstart', (ev)=> pedalStart(ev.changedTouches[0]), {passive:false});
pedalTrack.addEventListener('touchmove', (ev)=> pedalMove(ev.changedTouches[0]), {passive:false});
pedalTrack.addEventListener('touchend', (ev)=> pedalEnd(ev.changedTouches[0]), {passive:false});

/* Keyboard ramp/decay (fixed to update steer) */
const keyState = { up:false, down:false, left:false, right:false };
const keyAccel = { forward:0, steer:0 };
function getKbAccel() {
  return 0.05 * (Number(document.getElementById('kb_sens').value) || settings.kb_sens);
}

function getKbReturn() {
  return Number(document.getElementById('kb_return').value) || settings.kb_return;
}

window.addEventListener('keydown', (e)=>{
  if(e.repeat) return;
  if(['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.code)) e.preventDefault();
  const k = e.key.toLowerCase();
  if(k==='w' || e.code==='ArrowUp') keyState.up = true;
  if(k==='s' || e.code==='ArrowDown') keyState.down = true;
  if(k==='a' || e.code==='ArrowLeft') keyState.left = true;
  if(k==='d' || e.code==='ArrowRight') keyState.right = true;
});
window.addEventListener('keyup', (e)=>{
  const k = e.key.toLowerCase();
  if(k==='w' || e.code==='ArrowUp') keyState.up = false;
  if(k==='s' || e.code==='ArrowDown') keyState.down = false;
  if(k==='a' || e.code==='ArrowLeft') keyState.left = false;
  if(k==='d' || e.code==='ArrowRight') keyState.right = false;
});

/* Gamepad */
let gpIndex = null;
window.addEventListener('gamepadconnected', e => { gpIndex = e.gamepad.index; });
window.addEventListener('gamepaddisconnected', e => { if(gpIndex===e.gamepad.index) gpIndex=null; });
function pollGamepad(){
  if(gpIndex!==null){
    const g = navigator.getGamepads()[gpIndex];
    if(g){
      target.steer = clamp(g.axes[0]||0, -1,1);
      target.forward = clamp(-(g.axes[1]||0), -1,1);
    }
  }
  requestAnimationFrame(pollGamepad);
}
pollGamepad();

/* Send + smoothing loop (keyboard-steer fix included) */
setInterval(()=>{
    // keyboard influence
    let kf=0, ks=0;
    if(keyState.up) kf += 1;
    if(keyState.down) kf -= 1;
    if(keyState.left) ks -= 1;
    if(keyState.right) ks += 1;
    const m = Math.hypot(kf, ks) || 1; kf/=m; ks/=m;
    const ACC = getKbAccel();
    const RET = getKbReturn();

    if (kf !== 0)
    keyAccel.forward += kf * ACC;
    else
    keyAccel.forward += (0 - keyAccel.forward) * RET;

    if (ks !== 0)
    keyAccel.steer += ks * ACC;
    else
    keyAccel.steer += (0 - keyAccel.steer) * RET;


  // when joystick/pedal not active, keyboard drives both forward and steer
  if(pointerId === null && !pedalActive){
    target.forward = clamp(keyAccel.forward * Number(document.getElementById('kb_sens').value || settings.kb_sens), -1,1);
    target.steer  = clamp(keyAccel.steer  * Number(document.getElementById('kb_sens').value || settings.kb_sens), -1,1);
  }

  // smoothing
  const alpha = clamp(Number(document.getElementById('alpha').value || settings.alpha), 0.01, 0.9);
  current.forward = (current.forward || 0) + (target.forward - (current.forward || 0)) * alpha;
  current.steer  = (current.steer  || 0) + (target.steer  - (current.steer || 0)) * alpha;

  // map to hardware values
  const speedLimit = Number(document.getElementById('speed_limit').value || settings.speed_limit);
  const angleLimit = Number(document.getElementById('angle_limit').value || settings.angle_limit);
  const hwSpeed = Math.round(current.forward * speedLimit);
  const hwAngle = Math.round(90 + current.steer * angleLimit);

  // update HUD
  document.getElementById('hud_speed').textContent = hwSpeed;
  document.getElementById('hud_angle').textContent = hwAngle;
  document.getElementById('speed_limit_lbl').textContent = speedLimit;
  document.getElementById('angle_limit_lbl').textContent = angleLimit + '°';

  // send normalized forward/steer (-1..1) and speed_scale (speedLimit / max_speed)
  const speedScale = speedLimit / (Number(document.getElementById('max_speed').value || settings.max_speed) || 1);
  sendInput({ forward: current.forward, steer: current.steer, speed_scale: speedScale });

}, 60); // ~16Hz

/* Heartbeat (send periodically, server should reply with heartbeat_ack) */
setInterval(()=> socket.emit('heartbeat', { t: Date.now() }), 2000);

/* Quick toggle */
document.getElementById('quickToggle').addEventListener('click', ()=> quickPanel.classList.toggle('closed'));

/* Settings modal open/save */
btnSettings.addEventListener('click', ()=> {
  loadSettingsToUI();
  overlay.classList.add('show'); document.body.style.overflow = 'hidden';
});
document.getElementById('cancel_settings').addEventListener('click', ()=> {
  overlay.classList.remove('show'); document.body.style.overflow='';
});
document.getElementById('save_settings').addEventListener('click', ()=>{
  const sd = {
    deadman: Number(document.getElementById('deadman').value),
    jpegq: Number(document.getElementById('jpegq').value),
    max_speed: Number(document.getElementById('max_speed').value),
    speed_limit: Number(document.getElementById('speed_limit').value),
    angle_limit: Number(document.getElementById('angle_limit').value),
    alpha: Number(document.getElementById('alpha').value),
    jsize: Number(document.getElementById('jsize').value),
    jdead: Number(document.getElementById('jdead').value)/100.0,
    pdead: Number(document.getElementById('pdead').value)/100.0,
    kb_sens: Number(document.getElementById('kb_sens').value),
    kb_return: Number(document.getElementById('kb_return').value),

  };
  // persist locally
  Object.entries(sd).forEach(([k,v]) => lsSet(k,v));
  // apply client state
  settings = Object.assign(settings, sd);
  applyJoystickSize();
  // push to server
  socket.emit('set_setting', { key:'deadman', value: sd.deadman });
  socket.emit('set_setting', { key:'jpeg_quality', value: sd.jpegq });
  socket.emit('set_setting', { key:'max_speed', value: sd.max_speed });
  socket.emit('set_setting', { key:'speed_limit', value: sd.speed_limit });
  socket.emit('set_setting', { key:'angle_limit_deg', value: sd.angle_limit });
  socket.emit('set_setting', { key:'angle_alpha', value: sd.alpha });
  socket.emit('set_setting', { key:'keyboard_sensitivity', value: sd.kb_sens });
  overlay.classList.remove('show'); document.body.style.overflow='';
});

/* Fullscreen (lock landscape on mobile when possible) */
btnFull.addEventListener('click', async ()=>{
  try{
    if(!document.fullscreenElement){
      await document.documentElement.requestFullscreen();
      try{ if(screen.orientation && screen.orientation.lock) await screen.orientation.lock('landscape-primary'); } catch(_){}
      btnFull.textContent = 'Exit Fullscreen';
    } else {
      await document.exitFullscreen();
      btnFull.textContent = 'Fullscreen';
    }
  }catch(e){ console.warn('fullscreen failed', e); }
});

/* E-STOP */
estopBtn.addEventListener('click', ()=>{
  target.forward = 0; target.steer = 0; current.forward = 0; current.steer = 0;
  sendInput({ forward: 0, steer: 0, speed_scale: 0});
  socket.emit('set_setting', { key:'max_speed', value: 0 });
  setTimeout(()=> socket.emit('set_setting', { key:'max_speed', value: Number(document.getElementById('max_speed').value || settings.max_speed) }), 800);
});

/* Live UI bindings for modal sliders */
['speed_limit','angle_limit','alpha','jsize','jdead','pdead'].forEach(id=>{
  const el = document.getElementById(id);
  if(!el) return;
  el.addEventListener('input', ()=> {
    if(id==='angle_limit') document.getElementById('angle_limit_lbl').textContent = el.value + '°';
    if(id==='speed_limit') document.getElementById('speed_limit_lbl').textContent = el.value;
    if(id==='alpha') document.getElementById('alpha_val').textContent = el.value;
    if(id==='jsize') document.getElementById('jsize_val').textContent = el.value;
    if(id==='jdead') document.getElementById('jdead_val').textContent = el.value + '%';
    if(id==='pdead') document.getElementById('pdead_val').textContent = el.value + '%';
  });
});

/* Utility: load settings before open */
function loadSettingsToUI(){
  
  const keys = [
  'deadman','jpegq','max_speed',
  'speed_limit','angle_limit',
  'alpha','jsize','jdead','pdead',
  'kb_sens','kb_return'
];

  keys.forEach(k=>{
    const v = ls(k);
    if(v !== null){
      const el = document.getElementById(k);
      if(el) el.value = v;
    }
  });
  document.getElementById('speed_limit_lbl').textContent = document.getElementById('speed_limit').value;
  document.getElementById('angle_limit_lbl').textContent = document.getElementById('angle_limit').value + '°';
  document.getElementById('alpha_val').textContent = document.getElementById('alpha').value;
}

/* Initial message */
console.log('Ready — UI is English, ping is shown in HUD. Keyboard steer bug fixed: keyboard updates target.steer when joystick is not active.');
</script>
</body>
</html>

"""

# ---------- Routes ----------
@app.route('/')
def index():
    return render_template_string(INDEX_HTML)

@app.route('/video_feed')
def video_feed():
    return Response(mjpeg_stream(), mimetype='multipart/x-mixed-replace; boundary=frame')

# ---------- Shutdown & start ----------
def _shutdown(*args):
    log.info('shutdown: stopping hw & camera')
    try: hw.stop()
    except Exception: pass
    try: cam.release()
    except Exception: pass
    os._exit(0)

signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)

if __name__ == '__main__':
    log.info('Starting manual_controller_enterprise (fixed) on %s:%s (token=%s)', HOST, PORT, MANUAL_TOKEN)
    t_ctrl = threading.Thread(target=control_loop, daemon=True); t_ctrl.start()
    socketio.start_background_task(broadcaster)
    try:
        socketio.run(app, host=HOST, port=PORT, allow_unsafe_werkzeug=True)
    except Exception:
        log.exception('server failed')
