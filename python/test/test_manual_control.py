
import sys
import os
prev_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(prev_dir)

import os
import time
import json
import math
import secrets
import threading
import logging
import signal
from math import hypot
from pathlib import Path

from flask import Flask, Response, jsonify, render_template_string, request, send_from_directory
from flask_socketio import SocketIO, emit, disconnect

try:
    import cv2
except Exception:
    cv2 = None

try:
    import modes.city.config_city as config_city
except Exception:
    class _Cfg:
        MODE="city"; SERVO_CENTER=95; MIN_SERVO_ANGLE=50; MAX_SERVO_ANGLE=130; SPEED=255; WITHOUT_ARDUINO=True
    config_city=_Cfg()
try:
    from vision.camera import Camera as ProjectCamera
except Exception:
    ProjectCamera=None
try:
    from controller.controller import RobotController as ProjectController
except Exception:
    ProjectController=None
from controller.manual_encoder_map import ManualEncoderMap

class _UnavailableCamera:
    camera_initialized=False
    last_capture_valid=False
    def capture_frame(self,*args,**kwargs): return None,None
    def release(self): return None
class _DummyConnection:
    connected=False
    state="DISCONNECTED"
    last_error="Project controller could not be initialized"
class _DummyHW:
    without_arduino=True
    min_servo_angle=50; max_servo_angle=130; servo_center=95
    connection=_DummyConnection()
    def set_angle(self,_angle): return False
    def set_speed(self,_speed): return False
    def stop(self,reason=None): return False
    def encoder_telemetry(self,limit=100): return []
    def request_encoder_telemetry(self,timeout=.5): return False
    def close(self): return None


# ---------- Config ----------
HOST=os.getenv("MANUAL_HOST","0.0.0.0")
PORT=int(os.getenv("MANUAL_PORT","5010"))
MANUAL_TOKEN=os.getenv("MANUAL_TOKEN") or secrets.token_urlsafe(18)
STATE_FILE=os.getenv("MANUAL_STATE_FILE",str(Path(__file__).with_name("manual_enterprise_settings.json")))
SERVO_CENTER=float(getattr(config_city,"SERVO_CENTER",95))
SERVO_MIN=float(getattr(config_city,"MIN_SERVO_ANGLE",50))
SERVO_MAX=float(getattr(config_city,"MAX_SERVO_ANGLE",130))
DEFAULT_MAX_SPEED=max(0,min(255,int(getattr(config_city,"SPEED",255))))
ENCODER_DEFAULTS={"pulse_distance_cm":getattr(config_city,"ENCODER_PULSE_DISTANCE_CM",None),
 "wheelbase_cm":getattr(config_city,"ENCODER_WHEELBASE_CM",None),
 "road_angle_min_deg":getattr(config_city,"ENCODER_ROAD_ANGLE_MIN_DEG",None),
 "road_angle_max_deg":getattr(config_city,"ENCODER_ROAD_ANGLE_MAX_DEG",None)}

CONTROL_HZ = 60.0
UI_HZ = 20.0
WATCHDOG_MULT = 3.0
PRIORITY_STOP_REFRESH_INTERVAL = 0.10  # Reassert stop at 10 Hz while Space/E-STOP is active

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s %(name)s: %(message)s')
log = logging.getLogger('manual_enterprise')

# ---------- Defaults & persistence ----------
def _servo_angle_for_steer(steer, limit, trim=0.0):
    """Convert normalized steering into a bounded physical servo command."""
    steer = max(-1.0, min(1.0, float(steer)))
    limit = max(10.0, min(90.0, float(limit)))
    trim = max(-30.0, min(30.0, float(trim)))
    angle = SERVO_CENTER + trim + steer * limit
    return int(round(max(SERVO_MIN, min(SERVO_MAX, angle))))


def _priority_stop_due(active, was_active, now, last_sent):
    """Send immediately on activation, then periodically for the duration."""
    return bool(active and (not was_active or now - last_sent >= PRIORITY_STOP_REFRESH_INTERVAL))


def default_settings():
    return {
        'deadman': 1.0,
        'jpeg_quality': 70,
        'max_speed': DEFAULT_MAX_SPEED,
        'speed_limit': DEFAULT_MAX_SPEED,
        'encoder_calibration': dict(ENCODER_DEFAULTS),
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
        target=Path(STATE_FILE);target.parent.mkdir(parents=True,exist_ok=True)
        temporary=target.with_suffix(target.suffix+".tmp")
        with open(temporary,"w",encoding="utf-8") as f:
            json.dump(s,f,indent=2);f.flush();os.fsync(f.fileno())
        os.replace(temporary,target);return True
    except Exception:
        log.exception("save settings failed");return False

# ---------- State ----------
settings = load_settings()
saved_calibration=settings.get('encoder_calibration')
if isinstance(saved_calibration,dict): ENCODER_DEFAULTS.update(saved_calibration)
settings['encoder_calibration']=dict(ENCODER_DEFAULTS)
settings['max_speed']=max(0,min(255,int(settings.get('max_speed',DEFAULT_MAX_SPEED))))
settings['speed_limit']=max(0,min(255,int(settings.get('speed_limit',DEFAULT_MAX_SPEED))))
state_lock=threading.RLock()
state = {
    'angle': float(SERVO_CENTER) + float(settings.get('angle_trim', 0.0)),
    'speed': 0.0,
    'angle_target': float(SERVO_CENTER) + float(settings.get('angle_trim', 0.0)),
    'speed_target': 0.0,
    'speed_immediate': False,
    'steering_immediate': False,
    'hold_stop_clients': set(),
    'last_ui': time.monotonic(),
    'last_cmd': 0.0,
    'estop': False,
    'watchdog_active': True,
    'clients': {},
    'seq_seen': {},
    'settings': settings
}

cam=_UnavailableCamera()
hw=_DummyHW()
camera_lock=threading.RLock()
camera_frame_lock=threading.RLock()
latest_camera_frame=None
manual_encoder_map=ManualEncoderMap(controller=hw,servo_center=SERVO_CENTER,servo_min=SERVO_MIN,
    servo_max=SERVO_MAX,calibration=settings["encoder_calibration"])

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
def _finite_number(value):
    try: n=float(value)
    except (TypeError,ValueError,OverflowError): return None
    return n if math.isfinite(n) else None

@socketio.on("connect")
def on_connect(auth):
    token=request.args.get("token") or (auth.get("token") if isinstance(auth,dict) else None)
    if not secrets.compare_digest(str(token or ""),MANUAL_TOKEN):
        log.warning("Rejected manual-control socket with invalid token");disconnect();return
    with state_lock: state["clients"][request.sid]={"last_seen":time.monotonic()}
    emit("init",{"angle":state["angle"],"speed":state["speed"],"settings":state["settings"],"estop":state["estop"],
                 "hold_stop":bool(state["hold_stop_clients"]),
                 "servo_center":SERVO_CENTER,"servo_min":SERVO_MIN,"servo_max":SERVO_MAX})

@socketio.on("disconnect")
def on_disconnect():
    with state_lock:
        state["clients"].pop(request.sid,None);state["seq_seen"].pop(request.sid,None)
        state["hold_stop_clients"].discard(request.sid)
        state["speed_target"]=state["speed"]=0.0;state["angle_target"]=state["angle"]=SERVO_CENTER
        state["speed_immediate"]=False;state["steering_immediate"]=False
        state["last_cmd"]=0.0;state["watchdog_active"]=True

@socketio.on("input")
def on_input(msg):
    if not isinstance(msg,dict):
        emit("cmd_nack",{"seq":None,"err":"bad_payload"});return
    seq=msg.get("seq")
    if not isinstance(seq,int) or isinstance(seq,bool) or seq<0:
        emit("cmd_nack",{"seq":None,"err":"no_seq"});return
    forward=_finite_number(msg.get("forward",0));steer=_finite_number(msg.get("steer",0));scale=_finite_number(msg.get("speed_scale",1))
    if forward is None or steer is None or scale is None:
        emit("cmd_nack",{"seq":seq,"err":"bad_payload"});return
    forward=max(-1.0,min(1.0,forward));steer=max(-1.0,min(1.0,steer));scale=max(0.0,min(1.0,scale))
    now=time.monotonic()
    with state_lock:
        prev=state["seq_seen"].get(request.sid)
        if prev is not None and seq<=prev:
            emit("cmd_ack",{"seq":seq});return
        if request.sid not in state["clients"]:
            emit("cmd_nack",{"seq":seq,"err":"not_connected"});return
        state["seq_seen"][request.sid]=seq
        state["clients"][request.sid]["last_seen"]=now
        state["last_ui"]=now

        # A held Space stop and E-STOP are server-side motion interlocks.
        # Ignore all motion inputs while either interlock is active.
        if state["hold_stop_clients"] or state["estop"]:
            state["speed_target"]=state["speed"]=0.0
            state["angle_target"]=state["angle"]=SERVO_CENTER
            state["speed_immediate"]=False;state["steering_immediate"]=False
            state["last_cmd"]=0.0;state["watchdog_active"]=True
            emit("cmd_ack",{"seq":seq});return

        s=state["settings"]
        if msg.get("is_mobile") and s.get("invert_mobile_y",False):forward=-forward
        limit=max(10,min(90,float(s.get("angle_limit_deg",60))))
        angle=_servo_angle_for_steer(steer,limit,float(s.get("angle_trim",0.0)))
        max_speed=max(0,min(255,int(s.get("max_speed",DEFAULT_MAX_SPEED))))
        state["last_cmd"]=now;state["watchdog_active"]=False
        state["angle_target"]=angle
        state["speed_target"]=max_speed*forward*scale
        state["speed_immediate"] = msg.get("speed_immediate") is True
        state["steering_immediate"] = msg.get("steering_immediate") is True
    emit("cmd_ack",{"seq":seq})

@socketio.on("set_setting")
def on_set_setting(msg):
    if not isinstance(msg,dict) or not isinstance(msg.get("key"),str):
        emit("setting_nack",{"err":"bad_payload"});return
    key,value=msg["key"],msg.get("value")
    numeric={"deadman":(.2,10),"angle_alpha":(.01,.9),"speed_alpha":(.01,.9),
             "angle_limit_deg":(10,90),"speed_limit":(0,255),"keyboard_sensitivity":(.2,3),"angle_trim":(-30,30)}
    try:
        with state_lock:
            s=state["settings"]
            if key in numeric:
                n=_finite_number(value)
                if n is None:raise ValueError("value must be finite numeric")
                low,high=numeric[key];s[key]=max(low,min(high,n))
            elif key in ("jpeg_quality","max_speed"):
                n=_finite_number(value)
                if n is None:raise ValueError("value must be finite numeric")
                low,high=(10,95) if key=="jpeg_quality" else (0,255)
                s[key]=int(round(max(low,min(high,n))))
            elif key in ("invert_mobile_y","record_inputs") and isinstance(value,bool):s[key]=value
            elif key=="smoothing_mode" and value in ("alpha","pid"):s[key]=value
            elif key in ("angle_pid","speed_pid") and isinstance(value,(list,tuple)) and len(value)==3:
                nums=[_finite_number(v) for v in value]
                if any(v is None for v in nums):raise ValueError("PID values must be finite")
                s[key]=nums
            else:
                emit("setting_nack",{"key":key,"err":"unsupported_setting"});return
            global pid_angle,pid_speed
            pid_angle=PID(*s.get("angle_pid",[2,0,.25]));pid_speed=PID(*s.get("speed_pid",[3,0,.15]))
            snapshot=dict(s);saved=save_settings(snapshot)
        if not saved:emit("setting_nack",{"key":key,"err":"persistence_failed"});return
        emit("setting_ack",{"key":key,"value":snapshot.get(key)})
    except (TypeError,ValueError) as exc:emit("setting_nack",{"key":key,"err":str(exc)})

@socketio.on("hold_stop")
def on_hold_stop(msg):
    """Space is a hold-to-stop interlock; release never restores prior throttle."""
    if not isinstance(msg,dict) or not isinstance(msg.get("active"),bool):
        emit("hold_stop_nack",{"err":"bad_payload"});return
    with state_lock:
        if request.sid not in state["clients"]:
            emit("hold_stop_nack",{"err":"not_connected"});return
        if msg["active"]:
            state["hold_stop_clients"].add(request.sid)
        else:
            state["hold_stop_clients"].discard(request.sid)
        state["speed_target"]=state["speed"]=0.0
        state["angle_target"]=state["angle"]=SERVO_CENTER
        state["speed_immediate"]=False;state["steering_immediate"]=False
        # Require a fresh command after release; never restore an old throttle.
        state["last_cmd"]=0.0;state["watchdog_active"]=True
        active=bool(state["hold_stop_clients"])
    socketio.emit("hold_stop_state",{"active":active},namespace="/")


@socketio.on("heartbeat")
def on_heartbeat(msg):
    now=time.monotonic()
    with state_lock:
        if request.sid in state["clients"]:state["clients"][request.sid]["last_seen"]=now
        state["last_ui"]=now
    # Heartbeat never refreshes the manual motion watchdog.
    emit("heartbeat_ack",{"t":msg.get("t") if isinstance(msg,dict) else None,"server":time.time()})

@socketio.on("emergency_stop")
def on_emergency_stop(_msg=None):
    with state_lock:
        state["estop"]=True;state["speed_target"]=state["speed"]=0.0
        state["angle_target"]=SERVO_CENTER;state["watchdog_active"]=True
    socketio.emit("estop_state",{"active":True})

@socketio.on("reset_estop")
def on_reset_estop(_msg=None):
    with state_lock:
        state["estop"]=False;state["speed_target"]=state["speed"]=0.0
        state["angle_target"]=SERVO_CENTER;state["last_cmd"]=0.0;state["watchdog_active"]=True
    socketio.emit("estop_state",{"active":False})


# ---------- Runtime workers ----------
_stop=threading.Event()
_shutdown_started=threading.Event()
_hardware_command_lock=threading.Lock()
_last_hw_speed=None
_last_hw_angle=None
_last_priority_stop_at=0.0
_priority_stop_was_active=False

def _connection_snapshot():
    conn=getattr(hw,"connection",None)
    connected=bool(not getattr(hw,"without_arduino",False) and conn is not None and getattr(conn,"connected",False))
    return connected,str(getattr(conn,"state","CONNECTED" if connected else "DISCONNECTED"))

def broadcaster():
    while not _stop.is_set():
        connected,conn_state=_connection_snapshot()
        with state_lock:
            payload={"angle":state["angle"],"speed":state["speed"],"angle_target":state["angle_target"],
                     "speed_target":state["speed_target"],"settings":dict(state["settings"]),"clients":len(state["clients"]),
                     "connected":connected,"connection_state":conn_state,"estop":state["estop"],
                     "hold_stop":bool(state["hold_stop_clients"]),"watchdog_active":state["watchdog_active"]}
        socketio.emit("state",payload);socketio.sleep(1.0/UI_HZ)

def control_loop():
    global pid_angle,pid_speed,_last_hw_speed,_last_hw_angle
    global _last_priority_stop_at,_priority_stop_was_active
    last=time.monotonic()
    while not _stop.is_set():
        now=time.monotonic();dt=max(1e-4,now-last);last=now
        with state_lock:
            s=state;sett=s["settings"]
            expired=s["last_cmd"]<=0 or now-s["last_cmd"]>max(.2,float(sett.get("deadman",1)))
            hold_stop_active=bool(s["hold_stop_clients"])
            priority_stop=bool(s["estop"] or hold_stop_active)
            hard=bool(priority_stop or expired or not s["clients"])
            if hard:
                if expired and not s["watchdog_active"]:log.warning("Manual input expired; forcing STOP")
                s["speed_target"]=s["speed"]=0.0;s["angle_target"]=s["angle"]=SERVO_CENTER
                s["speed_immediate"]=False;s["steering_immediate"]=False
                s["watchdog_active"]=bool(expired or priority_stop)
                pid_angle=PID(*sett.get("angle_pid",[2,0,.25]));pid_speed=PID(*sett.get("speed_pid",[3,0,.15]))
            elif sett.get("smoothing_mode","alpha")=="pid":
                if s.get("steering_immediate",False):s["angle"]=s["angle_target"]
                else:s["angle"]+=pid_angle.step(s["angle_target"],s["angle"],dt)*dt
                if s.get("speed_immediate",False):s["speed"]=s["speed_target"]
                else:s["speed"]+=pid_speed.step(s["speed_target"],s["speed"],dt)*dt
                s["watchdog_active"]=False
            else:
                aa=max(.01,min(.9,float(sett.get("angle_alpha",.18))));sa=max(.01,min(.9,float(sett.get("speed_alpha",.20))))
                factor=dt*CONTROL_HZ
                if s.get("steering_immediate",False):s["angle"]=s["angle_target"]
                else:s["angle"]+=(s["angle_target"]-s["angle"])*(1-pow(1-aa,factor))
                if s.get("speed_immediate",False):s["speed"]=s["speed_target"]
                else:s["speed"]+=(s["speed_target"]-s["speed"])*(1-pow(1-sa,factor))
                s["watchdog_active"]=False
            s["angle"]=max(SERVO_MIN,min(SERVO_MAX,s["angle"]));m=max(0,min(255,int(sett.get("max_speed",DEFAULT_MAX_SPEED))))
            s["speed"]=max(-m,min(m,s["speed"]));angle=int(round(s["angle"]));speed=0 if hard or abs(s["speed"])<3 else int(round(s["speed"]))
        connected,_=_connection_snapshot()
        if connected:
            try:
                with _hardware_command_lock:
                    if priority_stop:
                        if _priority_stop_due(priority_stop,_priority_stop_was_active,now,_last_priority_stop_at):
                            _last_priority_stop_at=now
                            hw.stop(reason="manual_keyboard_hold_stop" if hold_stop_active else "manual_estop_hold")
                        _priority_stop_was_active=True
                        # Firmware STOP centers steering and clears queued motion.
                        _last_hw_speed=0;_last_hw_angle=SERVO_CENTER
                    else:
                        _priority_stop_was_active=False
                        if angle!=_last_hw_angle:
                            result=hw.set_angle(angle);_last_hw_angle=None if result is False else angle
                        if speed==0:
                            if _last_hw_speed!=0:hw.stop(reason="manual_neutral_or_deadman")
                            _last_hw_speed=0
                        else:hw.set_speed(speed);_last_hw_speed=speed
            except Exception:
                _last_hw_speed=_last_hw_angle=None;log.exception("Manual hardware command failed")
        else:
            _last_hw_speed=_last_hw_angle=None
            if not priority_stop:_priority_stop_was_active=False
        _stop.wait(1.0/CONTROL_HZ)

def _capture_frame_once():
    if cam is None or cv2 is None:return None
    with camera_lock:result=cam.capture_frame(with_resize=False)
    frame=result[0] if isinstance(result,tuple) else result
    return frame if frame is not None and bool(getattr(cam,"last_capture_valid",frame is not None)) else None

def camera_capture_loop():
    global latest_camera_frame
    while not _stop.is_set():
        try:
            frame=_capture_frame_once()
            if frame is not None:
                with camera_frame_lock:latest_camera_frame=frame.copy()
        except Exception:log.debug("Manual camera capture failed",exc_info=True)
        _stop.wait(1.0/30.0)

def encoder_poll_loop():
    retry=0.0
    while not _stop.is_set():
        try:
            manual_encoder_map.poll_once();snap=manual_encoder_map.snapshot();now=time.monotonic()
            if snap.get("connected") and (not snap.get("telemetry_available") or not snap.get("telemetry_fresh")) and now>=retry:
                manual_encoder_map.request_telemetry(timeout=.25);retry=now+2.0
        except Exception:log.exception("Manual encoder polling failed")
        _stop.wait(.05)

def mjpeg_stream():
    while not _stop.is_set():
        with camera_frame_lock:frame=latest_camera_frame.copy() if latest_camera_frame is not None else None
        if frame is None or cv2 is None:
            _stop.wait(.05);continue
        quality=max(10,min(95,int(state["settings"].get("jpeg_quality",70))))
        ok,jpg=cv2.imencode(".jpg",frame,[int(cv2.IMWRITE_JPEG_QUALITY),quality])
        if not ok:_stop.wait(.02);continue
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"+jpg.tobytes()+b"\r\n"


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
img#video{position:fixed;inset:0;width:100%;height:100%;object-fit:contain;object-position:center;z-index:0;background:#000}

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
.joy{position:fixed;left:14px;bottom:14px;width:180px;height:180px;border-radius:50%;background:linear-gradient(180deg,var(--glass-2),rgba(0,0,0,0.05));z-index:45;display:flex;align-items:center;justify-content:center;touch-action:none;user-select:none;-webkit-user-select:none;box-shadow:0 12px 40px rgba(0,0,0,0.6)}
.joy-caption{position:absolute;top:16px;left:0;right:0;text-align:center;font-weight:800;letter-spacing:.12em;font-size:11px;color:var(--muted);pointer-events:none}
.knob{width:64px;height:64px;border-radius:50%;background:var(--accent);box-shadow:0 8px 22px rgba(0,0,0,0.6);transform:translate(0,0);transition:transform 0.02s linear}

/* PEDAL */
.pedal{position:fixed;right:14px;top:50%;bottom:auto;transform:translateY(-50%);width:100px;height:min(38vh,250px);min-height:190px;border-radius:12px;background:var(--glass);z-index:45;padding:12px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;touch-action:none;user-select:none;-webkit-user-select:none;box-shadow:0 12px 40px rgba(0,0,0,0.6)}
.pedal .track{position:relative;width:44px;height:100%;min-height:125px;background:linear-gradient(to bottom,rgba(28,190,113,.24),rgba(28,190,113,.08) 44%,rgba(255,255,255,.07) 50%,rgba(255,128,55,.08) 56%,rgba(255,88,70,.25));border:1px solid rgba(255,255,255,.12);border-radius:22px;overflow:hidden}
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
.angle-limit-number{width:78px;min-width:78px;padding:6px 5px;border:1px solid rgba(255,255,255,.14);border-radius:8px;background:rgba(0,0,0,.24);color:var(--text);font:700 13px Inter,system-ui,sans-serif;text-align:center;font-variant-numeric:tabular-nums}
.angle-limit-number:focus{outline:2px solid var(--accent);outline-offset:2px;border-color:var(--accent)}
.form-line select{width:100%;padding:9px 10px;border:1px solid rgba(255,255,255,.14);border-radius:8px;background:rgba(0,0,0,.24);color:var(--text);font:500 13px Inter,system-ui,sans-serif}
.form-line select option{background:#071a20;color:var(--text)}

/* small screens */
@media(max-width:820px){
  .grid{grid-template-columns:1fr}
  .joy{left:8px;bottom:12px;width:150px;height:150px}
  .knob{width:52px;height:52px}
  .estop button{min-width:100px}
  .hud{left:8px;top:8px;gap:8px;padding:8px 10px}.hud .item{font-size:10px}.hud .item strong{font-size:12px}
  .top-controls{right:8px;top:66px;gap:5px}.small-btn{font-size:11px;padding:7px 8px}
  .pedal{right:8px;width:82px;height:35vh;min-height:170px}.estop{right:8px;bottom:10px}.estop button{font-size:11px;padding:10px;min-width:84px}
  .quick{max-width:calc(100vw - 140px)}
}
</style>
</head>
<body>

<img id="video" src="/video_feed" alt="live camera">

<!-- HUD -->
<div class="hud" id="hud">
  <div class="item">Speed <strong id="hud_speed">0</strong></div>
  <div class="item">Servo cmd <strong id="hud_angle">95</strong></div><div class="item">Motion <strong id="hud_motion">READY</strong></div><div class="item">Arduino <strong id="hud_connection" data-connected="false">CHECKING</strong></div>
  <div class="item">Clients <strong id="hud_clients">0</strong></div><div class="item">Ping <strong id="hud_ping">— ms</strong></div>
</div>

<!-- top -->
<div class="top-controls">
  <a href="/encoder-map" class="btn ghost small-btn" style="text-decoration:none;display:inline-flex;align-items:center">Encoder map ↗</a>
  <button id="btnSettings" class="btn ghost small-btn">Settings</button>
  <button id="btnFull" class="btn small-btn">Fullscreen</button>
</div>

<!-- joystick -->
<div class="joy" id="joy" aria-label="steering wheel">
  <div class="joy-caption">STEERING</div><div class="knob" id="knob"></div>
</div>

<!-- pedal -->
<div class="pedal" id="pedal">
  <div class="label">FORWARD ↑</div><div class="track" id="pedal_track"><div class="thumb" id="pedal_thumb"></div></div>
  <div class="label" id="pedal_val">0%</div><div class="label">↓ REVERSE</div>
</div>

<!-- E-STOP -->
<div class="estop"><button id="estop_btn" aria-pressed="false">E-STOP</button><button id="estop_reset_btn" hidden>Resume</button></div>

<!-- quick -->
<div class="quick" id="quickPanel">
  <div class="handle" id="quickToggle">▲ Quick Control (tap to toggle)</div>
  <div class="row-flex" style="margin-top:10px">
    <div style="flex:1">
      <div class="form-row"><label class="label">Speed limit</label><div class="value-badge" id="speed_limit_lbl">255</div></div>
      <input id="speed_limit" class="range" type="range" min="0" max="255" value="{{ default_max_speed }}">
    </div>
    <div style="width:12px"></div>
    <div style="flex:1">
      <div class="form-row"><label class="label" for="angle_limit_number">Angle limit (°)</label><input id="angle_limit_number" class="angle-limit-number" type="number" min="10" max="90" step="1" value="60" inputmode="numeric" aria-label="Angle limit in degrees"></div>
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
          <div class="form-row"><input id="max_speed" type="number" min="0" max="255" value="{{ default_max_speed }}"><div class="value-badge">units</div></div>
        </div>

        <div class="form-line">
          <label>Keyboard sensitivity</label>
          <div class="form-row"><input id="kb_sens" type="number" step="0.1" min="0.2" max="3.0" value="1.0"><div class="value-badge">x</div></div>
        </div>
        <div class="form-line">
          <label for="kb_steer_mode">Keyboard steering response</label>
          <select id="kb_steer_mode">
            <option value="hold">Hold to steer; release to recenter</option>
            <option value="progressive">Progressive steering</option>
          </select>
        </div>
        <div class="form-line">
          <label for="kb_speed_ramp">Keyboard acceleration</label>
          <select id="kb_speed_ramp">
            <option value="smooth">Gradual ramp</option>
            <option value="direct">Direct / instant target</option>
          </select>
        </div>
        <div class="form-line">
          <label for="kb_speed_stop">Keyboard stop on key release</label>
          <select id="kb_speed_stop">
            <option value="smooth">Gradual slowdown</option>
            <option value="instant">Immediate stop (0)</option>
          </select>
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
const SERVO_CENTER={{ servo_center|tojson }};
const SERVO_MIN={{ servo_min|tojson }};
const SERVO_MAX={{ servo_max|tojson }};

/* Socket */
const TOKEN=prompt("Enter the MANUAL token printed by the server")||"";
const socket=io({auth:{token:TOKEN}});
socket.on("connect",()=>console.log("Manual control connected"));
socket.on("disconnect",()=>{const e=document.getElementById("hud_connection");if(e){e.textContent="DISCONNECTED";e.dataset.connected="false";}releaseAllInputs();});
socket.on("connect_error",e=>console.warn("Manual socket error",e));
socket.on("init",s=>{if(s){syncEstopUI(!!s.estop);if(s.angle!==undefined)document.getElementById("hud_angle").textContent=Math.round(s.angle);}});
socket.on("state",s=>{if(!s)return;if(s.clients!==undefined)document.getElementById("hud_clients").textContent=s.clients;
 const e=document.getElementById("hud_connection");if(e){e.textContent=s.connected?"CONNECTED":(s.connection_state||"DISCONNECTED");e.dataset.connected=s.connected?"true":"false";}
 if(s.angle!==undefined)document.getElementById("hud_angle").textContent=Math.round(s.angle);
 const motion=document.getElementById("hud_motion");if(motion)motion.textContent=s.estop?"E-STOP":(s.hold_stop?"SPACE STOP":(s.watchdog_active?"STOP / WAIT":"READY"));
 if(s.estop!==undefined)syncEstopUI(!!s.estop);});

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
    speed_scale: payload.speed_scale == null ? 1.0 : Number(payload.speed_scale),
    speed_immediate: payload.speed_immediate === true,
    steering_immediate: payload.steering_immediate === true,
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
  kb_speed_ramp: document.getElementById('kb_speed_ramp').value || 'smooth',
  kb_speed_stop: document.getElementById('kb_speed_stop').value || 'smooth',
  kb_steer_mode: document.getElementById('kb_steer_mode').value || 'hold',

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
let pointerId = null, joyRect=null, origin=null, maxR=null, joyCaptureTarget=null;
let current = { forward: 0, steer: 0 };
let target = { forward: 0, steer: 0 };

function clamp(v,min,max){ return Math.max(min, Math.min(max, v)); }

function joyStart(e){
  const ev = e.touches ? e.changedTouches[0] : e;
  pointerId = (ev.pointerId !== undefined) ? ev.pointerId : ('t'+Date.now());
  joyCaptureTarget=e.target;
  try{ if(e.pointerId !== undefined) e.target.setPointerCapture && e.target.setPointerCapture(e.pointerId); }catch(_){}
  joyRect = joy.getBoundingClientRect();
  origin = { x: joyRect.left + joyRect.width/2, y: joyRect.top + joyRect.height/2 };
  maxR = Math.min(joyRect.width, joyRect.height)/2 - 8;
  joyMove(e);
  e.preventDefault && e.preventDefault();
}
function joyMove(e){
  const ev=e.touches?e.touches[0]:e;
  if(pointerId!==null&&ev.pointerId!==undefined&&ev.pointerId!==pointerId)return;
  if(!origin)return;
  const dx=clamp(ev.clientX-origin.x,-maxR,maxR);
  knob.style.transform="translate("+dx+"px, 0px)";
  const n=dx/maxR;target.steer=Math.abs(n)<settings.jdead?0:clamp(n,-1,1);
}
function joyEnd(e){
  if(e&&e.pointerId!==undefined&&pointerId!==null&&e.pointerId!==pointerId)return;
  try{if(e&&e.pointerId!==undefined&&joyCaptureTarget&&joyCaptureTarget.releasePointerCapture)joyCaptureTarget.releasePointerCapture(e.pointerId);}catch(_){}
  pointerId=null;joyRect=origin=maxR=joyCaptureTarget=null;knob.style.transform="translate(0,0)";target.steer=0;
}
joy.addEventListener("pointerdown",joyStart,{passive:false});
window.addEventListener("pointermove",e=>{if(pointerId!==null)joyMove(e);},{passive:false});
window.addEventListener("pointerup",e=>{if(pointerId!==null)joyEnd(e);},{passive:false});
window.addEventListener("pointercancel",e=>{if(pointerId!==null)joyEnd(e);},{passive:false});

/* Pedal */
let pedalRect=null, pedalActive=false, pedalPointerId=null, pedalCaptureTarget=null;
function pedalStart(e){
  const ev = e.touches ? e.changedTouches[0] : e;
  pedalPointerId=ev.pointerId===undefined?null:ev.pointerId;pedalCaptureTarget=e.target;
  try{if(pedalPointerId!==null&&e.target.setPointerCapture)e.target.setPointerCapture(pedalPointerId);}catch(_){}
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
  if(e&&e.pointerId!==undefined&&pedalPointerId!==null&&e.pointerId!==pedalPointerId)return;
  try{if(e&&e.pointerId!==undefined&&pedalCaptureTarget&&pedalCaptureTarget.releasePointerCapture)pedalCaptureTarget.releasePointerCapture(e.pointerId);}catch(_){}
  pedalActive=false;pedalPointerId=null;pedalCaptureTarget=null;pedalRect=null;
  pedalThumb.style.top = (pedalTrack.clientHeight/2 - pedalThumb.offsetHeight/2) + 'px';
  pedalVal.textContent = '0%';
  target.forward = 0;
}
pedalTrack.addEventListener('pointerdown', pedalStart, {passive:false});
window.addEventListener('pointermove', (e)=>{ if(pedalActive) pedalMove(e); }, {passive:false});
window.addEventListener('pointerup', (e)=>{ if(pedalActive) pedalEnd(e); }, {passive:false});
window.addEventListener('pointercancel', (e)=>{ if(pedalActive) pedalEnd(e); }, {passive:false});

/* Keyboard ramp/decay (fixed to update steer) */
const keyState = { up:false, down:false, left:false, right:false, stop:false };
let gamepadReleaseRequired = false;
const keyAccel = { forward:0, steer:0 };
function getKbAccel() {
  return 0.05 * (Number(document.getElementById('kb_sens').value) || settings.kb_sens);
}

function getKbReturn() {
  return Number(document.getElementById('kb_return').value) || settings.kb_return;
}

window.addEventListener('keydown', (e)=>{
  // Space is a hold-to-stop interlock, not a one-shot key toggle.
  if(e.code==='Space'){
    e.preventDefault();
    if(!e.repeat && !keyState.stop){
      keyState.stop=true;
      keyState.up=keyState.down=keyState.left=keyState.right=false;
      keyAccel.forward=keyAccel.steer=0;
      target.forward=target.steer=current.forward=current.steer=0;
      pointerId=null;joyRect=origin=maxR=joyCaptureTarget=null;
      pedalActive=false;pedalPointerId=null;pedalCaptureTarget=null;pedalRect=null;
      gamepadReleaseRequired=true;
      socket.emit('hold_stop',{active:true,t:Date.now()});
      const motion=document.getElementById('hud_motion');if(motion)motion.textContent='SPACE STOP';
    }
    return;
  }
  if(e.repeat) return;
  if(['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(e.code)) e.preventDefault();
  const k = e.key.toLowerCase();
  if(k==='w' || e.code==='ArrowUp') keyState.up = true;
  if(k==='s' || e.code==='ArrowDown') keyState.down = true;
  if(k==='a' || e.code==='ArrowLeft') keyState.left = true;
  if(k==='d' || e.code==='ArrowRight') keyState.right = true;
});
window.addEventListener('keyup', (e)=>{
  if(e.code==='Space'){
    e.preventDefault();
    if(keyState.stop){
      keyState.stop=false;
      socket.emit('hold_stop',{active:false,t:Date.now()});
      keyState.up=keyState.down=keyState.left=keyState.right=false;
      keyAccel.forward=keyAccel.steer=0;
      target.forward=target.steer=current.forward=current.steer=0;
      const motion=document.getElementById('hud_motion');if(motion)motion.textContent='STOP / WAIT';
    }
    return;
  }
  const k = e.key.toLowerCase();
  if(k==='w' || e.code==='ArrowUp') keyState.up = false;
  if(k==='s' || e.code==='ArrowDown') keyState.down = false;
  if(k==='a' || e.code==='ArrowLeft') keyState.left = false;
  if(k==='d' || e.code==='ArrowRight') keyState.right = false;
});

/* Gamepad: ignore centered axes and yield to touch input. */
let gpIndex=null,gamepadActive=false;
window.addEventListener("gamepadconnected",e=>{gpIndex=e.gamepad.index;});
window.addEventListener("gamepaddisconnected",e=>{if(gpIndex===e.gamepad.index){gpIndex=null;gamepadActive=false;target.forward=target.steer=0;}});
function pollGamepad(){gamepadActive=false;if(gpIndex!==null&&!keyState.stop&&pointerId===null&&!pedalActive){const g=navigator.getGamepads()[gpIndex];if(g){const x=clamp(g.axes[0]||0,-1,1),y=clamp(-(g.axes[1]||0),-1,1);if(gamepadReleaseRequired){if(Math.abs(x)<=.08&&Math.abs(y)<=.08)gamepadReleaseRequired=false;}else{gamepadActive=Math.abs(x)>.08||Math.abs(y)>.08;if(gamepadActive){target.steer=x;target.forward=y;}}}}requestAnimationFrame(pollGamepad);}
pollGamepad();
function syncEstopUI(active){const b=document.getElementById("estop_btn"),r=document.getElementById("estop_reset_btn");if(!b||!r)return;b.setAttribute("aria-pressed",active?"true":"false");b.textContent=active?"E-STOP ACTIVE":"E-STOP";b.disabled=active;r.hidden=!active;}
function releaseAllInputs(){
 if(typeof keyState!=="undefined"){
   keyState.up=keyState.down=keyState.left=keyState.right=false;
   if(keyState.stop){keyState.stop=false;socket.emit('hold_stop',{active:false,t:Date.now()});gamepadReleaseRequired=true;}
 }
 if(typeof keyAccel!=="undefined"){keyAccel.forward=0;keyAccel.steer=0;}
 target.forward=target.steer=current.forward=current.steer=0;pointerId=null;joyRect=origin=maxR=joyCaptureTarget=null;
 pedalActive=false;pedalPointerId=null;pedalCaptureTarget=null;pedalRect=null;knob.style.transform="translate(0,0)";pedalVal.textContent="0%";
 sendInput({forward:0,steer:0,speed_scale:0});
}
window.addEventListener("blur",releaseAllInputs);document.addEventListener("visibilitychange",()=>{if(document.hidden)releaseAllInputs();});


/* Send + smoothing loop (keyboard-steer fix included) */
let lastInputActive=false;
setInterval(()=>{
    // keyboard influence
    let kf=0, ks=0;
    if(keyState.up) kf += 1;
    if(keyState.down) kf -= 1;
    if(keyState.left) ks -= 1;
    if(keyState.right) ks += 1;
    // Throttle and steering are independent car controls: diagonal input must not weaken either axis.
    const ACC = getKbAccel();
    const RET = getKbReturn();
    const keyboardOwnsControls = pointerId === null && !pedalActive && !gamepadActive;
    const kbSpeedRamp = document.getElementById('kb_speed_ramp').value || settings.kb_speed_ramp || 'smooth';
    const kbSpeedStop = document.getElementById('kb_speed_stop').value || settings.kb_speed_stop || 'smooth';
    const kbSteerMode = document.getElementById('kb_steer_mode').value || settings.kb_steer_mode || 'hold';

    if (kf !== 0) {
      if (kbSpeedRamp === 'direct') keyAccel.forward = kf;
      else keyAccel.forward = clamp(keyAccel.forward + kf * ACC, -1, 1);
    } else if (kbSpeedStop === 'instant') {
      keyAccel.forward = 0;
    } else {
      keyAccel.forward += (0 - keyAccel.forward) * RET;
    }

    if (ks !== 0) {
      if (keyboardOwnsControls && kbSteerMode === 'hold') {
        // Hold a stable steering target while A/D or left/right remains pressed.
        keyAccel.steer = ks;
      } else if (kbSteerMode === 'progressive') {
        keyAccel.steer = clamp(keyAccel.steer + ks * ACC, -1, 1);
      }
    } else {
      // Smoothly recenter after releasing the steering key.
      keyAccel.steer += (0 - keyAccel.steer) * RET;
    }


  // when joystick/pedal not active, keyboard drives both forward and steer
  if(keyboardOwnsControls){
    target.forward = clamp(keyAccel.forward * Number(document.getElementById('kb_sens').value || settings.kb_sens), -1,1);
    target.steer  = clamp(keyAccel.steer  * Number(document.getElementById('kb_sens').value || settings.kb_sens), -1,1);
  }

  // Steering remains smoothed. Keyboard throttle can independently ramp or snap.
  const alpha = clamp(Number(document.getElementById('alpha').value || settings.alpha), 0.01, 0.9);
  if (keyboardOwnsControls && kf !== 0 && kbSpeedRamp === 'direct') {
    current.forward = target.forward;
  } else if (keyboardOwnsControls && kf === 0 && kbSpeedStop === 'instant') {
    current.forward = 0;
  } else {
    current.forward = (current.forward || 0) + (target.forward - (current.forward || 0)) * alpha;
  }
  const keyboardSteeringImmediate = keyboardOwnsControls && ks !== 0 && kbSteerMode === 'hold';
  if (keyboardSteeringImmediate) current.steer = target.steer;
  else current.steer = (current.steer || 0) + (target.steer - (current.steer || 0)) * alpha;

  // map to hardware values
  const speedLimit = Number(document.getElementById('speed_limit').value || settings.speed_limit);
  const angleLimit = Number(document.getElementById('angle_limit').value || settings.angle_limit);
  const hwSpeed = Math.round(current.forward * speedLimit);
  // The server reports the bounded servo command; don't display a client-side guess.
  document.getElementById('hud_speed').textContent = hwSpeed;
  document.getElementById('speed_limit_lbl').textContent = speedLimit;
  if(document.activeElement.id !== 'angle_limit_number') document.getElementById('angle_limit_number').value = String(angleLimit);

  // send normalized forward/steer (-1..1) and speed_scale (speedLimit / max_speed)
  const baseMax=Number(document.getElementById("max_speed").value||settings.max_speed)||1;
  const speedScale=clamp(speedLimit/baseMax,0,1);
  const active=!keyState.stop&&(pointerId!==null||pedalActive||gamepadActive||keyState.up||keyState.down||keyState.left||keyState.right||
    Math.abs(keyAccel.forward)>.01||Math.abs(keyAccel.steer)>.01||Math.abs(target.forward)>.01||Math.abs(target.steer)>.01||
    Math.abs(current.forward)>.01||Math.abs(current.steer)>.01);
  const keyboardSpeedImmediate = keyboardOwnsControls && (
    (kf !== 0 && kbSpeedRamp === 'direct') || (kf === 0 && kbSpeedStop === 'instant')
  );
  if(active){sendInput({forward:current.forward,steer:current.steer,speed_scale:speedScale,speed_immediate:keyboardSpeedImmediate,steering_immediate:keyboardSteeringImmediate});lastInputActive=true;}
  else if(lastInputActive){sendInput({forward:0,steer:0,speed_scale:0,speed_immediate:keyboardOwnsControls && kbSpeedStop === 'instant'});lastInputActive=false;}

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
    kb_speed_ramp: document.getElementById('kb_speed_ramp').value,
    kb_speed_stop: document.getElementById('kb_speed_stop').value,
    kb_steer_mode: document.getElementById('kb_steer_mode').value,

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

/* Latched E-STOP: resume never restores throttle automatically. */
estopBtn.addEventListener("click",()=>{releaseAllInputs();socket.emit("emergency_stop",{t:Date.now()});});
document.getElementById("estop_reset_btn").addEventListener("click",()=>socket.emit("reset_estop",{t:Date.now()}));

/* Typed angle limit stays synchronized with the slider and is applied to the controller. */
const angleLimitNumber = document.getElementById('angle_limit_number');
const angleLimitSlider = document.getElementById('angle_limit');
function syncAngleLimitNumber(commit=false){
  if(!angleLimitNumber||!angleLimitSlider)return;
  const raw=angleLimitNumber.value.trim();
  if(raw===''||!Number.isFinite(Number(raw))){
    if(commit)angleLimitNumber.value=angleLimitSlider.value;
    return;
  }
  const parsed=Number(raw);
  if(!commit&&(parsed<10||parsed>90))return; // Keep partial edits possible while typing.
  const value=Math.round(clamp(parsed,10,90));
  angleLimitNumber.value=String(value);
  angleLimitSlider.value=String(value);
  settings.angle_limit=value;
  lsSet('angle_limit',value);
  if(commit)socket.emit('set_setting',{key:'angle_limit_deg',value:value});
}
angleLimitNumber.addEventListener('input',()=>syncAngleLimitNumber(false));
angleLimitNumber.addEventListener('change',()=>syncAngleLimitNumber(true));
angleLimitNumber.addEventListener('blur',()=>syncAngleLimitNumber(true));
angleLimitSlider.addEventListener('change',()=>{
  const value=clamp(Math.round(Number(angleLimitSlider.value)||60),10,90);
  angleLimitSlider.value=String(value);
  angleLimitNumber.value=String(value);
  settings.angle_limit=value;
  lsSet('angle_limit',value);
  socket.emit('set_setting',{key:'angle_limit_deg',value:value});
});

/* Live UI bindings for modal sliders */
['speed_limit','angle_limit','alpha','jsize','jdead','pdead'].forEach(id=>{
  const el = document.getElementById(id);
  if(!el) return;
  el.addEventListener('input', ()=> {
    if(id==='angle_limit') document.getElementById('angle_limit_number').value = el.value;
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
  'kb_sens','kb_return','kb_speed_ramp','kb_speed_stop','kb_steer_mode'
];

  keys.forEach(k=>{
    const v = ls(k);
    if(v !== null){
      const el = document.getElementById(k);
      if(el) el.value = v;
    }
  });
  document.getElementById('speed_limit_lbl').textContent = document.getElementById('speed_limit').value;
  document.getElementById('angle_limit_number').value = document.getElementById('angle_limit').value;
  document.getElementById('alpha_val').textContent = document.getElementById('alpha').value;
}

/* Initial message */
console.log('Ready — UI is English, ping is shown in HUD. Keyboard steer bug fixed: keyboard updates target.steer when joystick is not active.');
</script>
</body>
</html>

"""

# ---------- Routes ----------
@app.route("/")
def index():
    return render_template_string(INDEX_HTML,servo_center=SERVO_CENTER,servo_min=SERVO_MIN,servo_max=SERVO_MAX,default_max_speed=DEFAULT_MAX_SPEED)
@app.route("/video_feed")
def video_feed():
    return Response(mjpeg_stream(),mimetype="multipart/x-mixed-replace; boundary=frame")
@app.route("/encoder-map")
def encoder_map_page():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)),"manual_encoder_map.html")
@app.route("/api/encoder-map")
def encoder_map_api():
    manual_encoder_map.poll_once()
    return jsonify(manual_encoder_map.snapshot())
@app.route("/api/encoder-map/calibration",methods=["POST"])
def encoder_map_calibration_api():
    data=request.get_json(silent=True)
    if not isinstance(data,dict):return jsonify(success=False,message="Send a JSON calibration object."),400
    try:
        calibration=manual_encoder_map.set_calibration(data)
        with state_lock:
            settings["encoder_calibration"]=dict(calibration);saved=save_settings(dict(settings))
        if not saved:return jsonify(success=False,message="Could not save calibration."),500
        return jsonify(success=True,calibration=calibration,state=manual_encoder_map.snapshot())
    except (TypeError,ValueError) as exc:return jsonify(success=False,message=str(exc)),400
@app.route("/api/encoder-map/reset-origin",methods=["POST"])
def encoder_map_reset_origin_api():
    try:manual_encoder_map.reset_origin();return jsonify(success=True,state=manual_encoder_map.snapshot())
    except RuntimeError as exc:return jsonify(success=False,message=str(exc)),409
@app.route("/api/encoder-map/enable",methods=["POST"])
def encoder_map_enable_api():
    connected,status=_connection_snapshot()
    if not connected:return jsonify(success=False,message="Arduino is not connected.",connection_state=status),409
    if not manual_encoder_map.request_telemetry(timeout=.75):return jsonify(success=False,message="No ODOM1 acknowledgement; check firmware and serial connection."),409
    return jsonify(success=True,state=manual_encoder_map.snapshot())

def _initialize_runtime():
    global hw,cam
    config_city.ENCODER_MAP_ENABLED=False
    config_city.ADAPTIVE_OBSTACLE_AVOIDANCE_ENABLED=False
    if hasattr(config_city,"ARDUINO_CONFIG"):config_city.ARDUINO_CONFIG=None
    config_city.SEND_AUTOMATIC_ARDUINO_COMMANDS=True
    hw=ProjectController(config=config_city) if ProjectController is not None else _DummyHW()
    manual_encoder_map.set_controller(hw)
    try:
        if ProjectCamera is None:raise RuntimeError("Project camera backend is unavailable")
        cam=ProjectCamera(config=config_city)
    except Exception:
        log.exception("Camera unavailable; manual control starts without video")
        cam=_UnavailableCamera()
    try:
        if not getattr(hw,"without_arduino",False):hw.stop(reason="manual_controller_startup")
    except Exception:log.exception("Could not send startup STOP")

def _shutdown():
    if _shutdown_started.is_set():return
    _shutdown_started.set();_stop.set()
    try:
        with _hardware_command_lock:
            if hw is not None and not getattr(hw,"without_arduino",False):hw.stop(reason="manual_controller_shutdown")
    except Exception:log.exception("Final STOP failed")
    try:
        conn=getattr(hw,"connection",None)
        if conn is not None and hasattr(conn,"close"):conn.close()
    except Exception:log.exception("Serial shutdown failed")
    try:
        with camera_lock:
            if cam is not None:cam.release()
    except Exception:log.exception("Camera shutdown failed")

def _handle_shutdown_signal(_signum,_frame):raise KeyboardInterrupt

if __name__=="__main__":
    signal.signal(signal.SIGINT,_handle_shutdown_signal);signal.signal(signal.SIGTERM,_handle_shutdown_signal)
    log.info("Starting manual RC controller on %s:%s",HOST,PORT);print(f"MANUAL_TOKEN={MANUAL_TOKEN}",flush=True)
    try:
        _initialize_runtime()
        threading.Thread(target=control_loop,name="manual-control",daemon=True).start()
        threading.Thread(target=camera_capture_loop,name="manual-camera",daemon=True).start()
        threading.Thread(target=encoder_poll_loop,name="manual-encoder",daemon=True).start()
        socketio.start_background_task(broadcaster)
        socketio.run(app,host=HOST,port=PORT,allow_unsafe_werkzeug=True)
    except KeyboardInterrupt:log.info("Manual controller stopped")
    except Exception:
        log.exception("Manual controller failed");raise
    finally:_shutdown()
