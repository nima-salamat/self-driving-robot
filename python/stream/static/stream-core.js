
/* ---------- Globals ---------- */
const canvas = document.getElementById('video_canvas');
const ctx = canvas.getContext('2d');
const select = document.getElementById('variable_select');
const inputsContainer = document.getElementById('inputs_container');
const showRectsCheckbox = document.getElementById('show_rects');
const frameModeDisplay = document.getElementById('frame_mode');

let values = window.STREAM_BOOTSTRAP.values;
let ui = window.STREAM_BOOTSTRAP.ui;
let advanced = window.STREAM_BOOTSTRAP.advanced;
const STREAM_CONTROL_ALLOWED = !!window.STREAM_BOOTSTRAP.streamControl;

const controlNotice = document.getElementById('control_notice');
if (controlNotice) {
    controlNotice.textContent = STREAM_CONTROL_ALLOWED
        ? 'Dashboard control is enabled.'
        : 'Dashboard is read-only. Enable STREAM_ALLOW_CONTROL or restart without --stream-read-only to allow runtime changes.';
}

let selectedVar = 'NONE';
let markerHighlight = null;
let roiAppearance = {labelFontSize:12, labelFontWeight:'700', outlineThickness:2, handleSize:10};
let gridMode = 'off', gridSpacing = 0.05, gridOpacity = 0.35, gridThickness = 1, gridDotSize = 2;
function isEditorSnapEnabled(){return typeof window.__isEditorSnapEnabled === 'function' && window.__isEditorSnapEnabled();}
function snapNormalized(value, spacing){const step=Math.max(0.001,Math.min(1,Number(spacing==null?gridSpacing:spacing)||0.05));return round01(Math.round(Number(value)/step)*step);}
let fetchFrameTimer = null;
let streamDisplayFps = 8.3; // Matches the previous 120 ms browser refresh cadence.
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
    if(wasOnline){noteWorkspaceEvent('error','Robot dashboard connection lost: '+(err&&err.message?err.message:err));recordApiEvent('error','Dashboard request failed: '+(err&&err.message?err.message:err));}
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
    if(wasOffline){noteWorkspaceEvent('info','Robot dashboard connection restored');recordApiEvent('info','Dashboard requests responding again');}
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
let workspaceZoom=1,viewPanX=0,viewPanY=0,viewPanState=null,lastFrameImage=null,frameSourceWidth=0,frameSourceHeight=0,workspaceTool='select',workspaceViewLocked=false;
const WORKSPACE_EVENT_LIMIT=250;let workspaceEvents=[],workspaceApiEvents=[];
let lastLoggedHealthState=null,lastLoggedFaultSignature=null,lastLoggedArduinoState=null,lastLoggedModeSignature=null;
function noteWorkspaceEvent(level,message,channel='events'){const entry={time:new Date(),level:String(level||'info').toLowerCase(),message:String(message||'')};const store=channel==='api'?workspaceApiEvents:workspaceEvents;store.push(entry);if(store.length>WORKSPACE_EVENT_LIMIT)store.splice(0,store.length-WORKSPACE_EVENT_LIMIT);renderWorkspaceEventLog(channel);}
let workspaceConsolePaused=false,workspaceConsoleAutoScroll=true,workspaceConsoleQuery='',workspaceConsoleLevel='ALL';
function renderWorkspaceEventLog(channel='events'){
  if(workspaceConsolePaused)return;
  const store=channel==='api'?workspaceApiEvents:workspaceEvents;
  const root=document.getElementById(channel==='api'?'console_api':'console_events');if(!root)return;
  root.replaceChildren();
  const query=workspaceConsoleQuery.trim().toLowerCase();
  const selected=store.slice().reverse().filter(function(entry){
    const level=String(entry.level||'info').toUpperCase();
    return (workspaceConsoleLevel==='ALL'||level===workspaceConsoleLevel)&&(!query||(String(entry.message||'')+' '+level).toLowerCase().includes(query));
  });
  if(!selected.length){const e=document.createElement('div');e.className='console-empty';e.textContent=store.length?'No matching console entries.':channel==='api'?'No request diagnostics yet.':'No events yet.';root.appendChild(e);}
  else for(const entry of selected){
    const row=document.createElement('div');row.className='console-entry';
    const stamp=document.createElement('span');stamp.className='console-time';
    const time=entry.time instanceof Date?entry.time:new Date(entry.time||Date.now());
    stamp.textContent=time.toLocaleTimeString([],{hour12:false})+'.'+String(time.getMilliseconds()).padStart(3,'0');
    const levelName=String(entry.level||'info').toUpperCase();
    const level=document.createElement('span');level.className='console-level '+(levelName==='ERROR'?'error':levelName==='WARN'?'warn':'');level.textContent=levelName;
    const msg=document.createElement('span');msg.className='console-message';msg.textContent=entry.message;
    row.append(stamp,level,msg);root.appendChild(row);
  }
  if(workspaceConsoleAutoScroll)root.scrollTop=0;
  const c=document.getElementById('console_count');if(c)c.textContent=workspaceEvents.length+' events · '+workspaceApiEvents.length+' requests';
}
function recordApiEvent(level,message){noteWorkspaceEvent(level,message,'api');}
function setWorkspaceZoom(next,ax=canvas.width/2,ay=canvas.height/2,log=true){
  const slider=document.getElementById('workspace_zoom');
  if(workspaceViewLocked){if(slider)slider.value=String(workspaceZoom);return false;}
  const z=Math.max(.3,Math.min(4,Number(next)||1));if(Math.abs(z-workspaceZoom)<.0001)return true;
  const b=getImgBounds(),base=getBaseImgBounds(),u=(ax-b.ix)/b.iw,v=(ay-b.iy)/b.ih;workspaceZoom=z;
  const nw=base.iw*z,nh=base.ih*z,scale=Math.max(0.0001,base.scale||1);
  viewPanX=(ax-u*nw-(canvas.width-nw)/2)/scale;viewPanY=(ay-v*nh-(canvas.height-nh)/2)/scale;
  if(slider)slider.value=String(z);renderWorkspaceCanvas();updateZoomStatus();
  if(log)noteWorkspaceEvent('info','View zoom: '+Math.round(z*100)+'%');return true;
}
function updateWorkspaceViewLockUI(){
  const button=document.getElementById('workspace_view_lock');
  const slider=document.getElementById('workspace_zoom');
  const zoomPercent=document.getElementById('workspace_zoom_percent');
  const shackle=document.getElementById('workspace_lock_shackle');
  const label=document.getElementById('workspace_view_lock_label');
  const message=workspaceViewLocked?'Unlock view (allow zoom and pan)':'Lock zoom and camera position';
  if(button){button.setAttribute('aria-pressed',String(workspaceViewLocked));button.setAttribute('aria-label',message);button.title=message;button.classList.toggle('is-locked',workspaceViewLocked);}
  if(shackle)shackle.setAttribute('d',workspaceViewLocked?'M7 10V7a5 5 0 0 1 10 0v3':'M7 10V7a5 5 0 0 1 9.5-2');
  if(label)label.textContent=workspaceViewLocked?'View Locked':'Lock View';
  if(slider)slider.disabled=workspaceViewLocked;
  if(zoomPercent)zoomPercent.disabled=workspaceViewLocked;
  document.querySelectorAll('[data-action="zoom-in"],[data-action="zoom-out"],[data-action="fit-view"]').forEach(function(control){control.disabled=workspaceViewLocked;control.setAttribute('aria-disabled',String(workspaceViewLocked));});
  const fitButton=document.getElementById('center_reset');if(fitButton){fitButton.disabled=workspaceViewLocked;fitButton.setAttribute('aria-disabled',String(workspaceViewLocked));}
  document.querySelectorAll('[data-tool="pan"]').forEach(function(control){control.disabled=workspaceViewLocked;control.setAttribute('aria-disabled',String(workspaceViewLocked));});
}
function setWorkspaceViewLocked(locked,log=true,persist=true){
  const next=!!locked;if(next===workspaceViewLocked){updateWorkspaceViewLockUI();return workspaceViewLocked;}
  workspaceViewLocked=next;
  if(workspaceViewLocked)viewPanState=null;
  updateWorkspaceViewLockUI();
  if(log)noteWorkspaceEvent('info',workspaceViewLocked?'View locked: zoom and camera position are fixed':'View unlocked: zoom and pan are available');
  if(persist&&typeof window.onWorkspaceViewLockChanged==='function')window.onWorkspaceViewLockChanged(workspaceViewLocked);
  return workspaceViewLocked;
}
window.isWorkspaceViewLocked=()=>workspaceViewLocked;
window.setWorkspaceViewLocked=setWorkspaceViewLocked;
function fitWorkspaceView(log=true){
  if(workspaceViewLocked)return false;
  syncCameraCanvasSize();workspaceZoom=1;viewPanX=0;viewPanY=0;document.getElementById('workspace_zoom').value='1';
  renderWorkspaceCanvas();if(typeof window.drawPrecisionOverlay==='function')window.drawPrecisionOverlay();updateZoomStatus();
  if(log)noteWorkspaceEvent('info','View reset to fit camera frame');return true;
}
function updateZoomStatus(){
  const el=document.getElementById('menu_live_status');
  if(el)el.textContent=(isFrozen?'FROZEN':'LIVE')+' · '+String(window.STREAM_BOOTSTRAP.mode||'mode').toUpperCase();
  const pct=document.getElementById('workspace_zoom_percent');
  // Preserve an in-progress edit while other UI events refresh the zoom state.
  if(pct&&document.activeElement!==pct)pct.value=Math.round(workspaceZoom*100)+'%';
}
function applyWorkspaceZoomPercent(){
  const input=document.getElementById('workspace_zoom_percent');
  if(!input)return false;
  const raw=String(input.value||'').trim();
  const match=raw.match(/^(?:([0-9]+(?:\.[0-9]*)?)|(\.[0-9]+))\s*%?$/);
  const currentLabel=Math.round(workspaceZoom*100)+'%';
  if(!match){input.value=currentLabel;showToast('Enter a zoom percentage from 30% to 400%.');return false;}
  const percent=Number(match[1]!==undefined?match[1]:match[2]);
  if(!Number.isFinite(percent)||percent<30||percent>400){input.value=currentLabel;showToast('Zoom must be between 30% and 400%.');return false;}
  const applied=setWorkspaceZoom(percent/100,canvas.width/2,canvas.height/2);
  if(!applied){input.value=currentLabel;showToast('Unlock the view before changing zoom.');return false;}
  input.value=Math.round(workspaceZoom*100)+'%';
  return true;
}
const zoomPercentInput=document.getElementById('workspace_zoom_percent');
if(zoomPercentInput){
  zoomPercentInput.addEventListener('focus',function(){this.select();});
  zoomPercentInput.addEventListener('keydown',function(event){
    if(event.key==='Enter'){event.preventDefault();if(applyWorkspaceZoomPercent())this.blur();}
    else if(event.key==='Escape'){event.preventDefault();this.value=Math.round(workspaceZoom*100)+'%';this.blur();}
  });
  zoomPercentInput.addEventListener('blur',applyWorkspaceZoomPercent);
}
document.getElementById('workspace_zoom').addEventListener('input',e=>setWorkspaceZoom(parseFloat(e.target.value),canvas.width/2,canvas.height/2));
document.getElementById('workspace_view_lock').addEventListener('click',()=>setWorkspaceViewLocked(!workspaceViewLocked));
updateWorkspaceViewLockUI();

/* Camera frame fullscreen: scale the canvas bitmap to the viewport while
   preserving the source frame aspect ratio and native coordinate system. */
function isCameraStageFullscreen(){
  const stage=document.getElementById('canvas_stage');
  return !!stage && (document.fullscreenElement===stage || document.webkitFullscreenElement===stage);
}
function syncCameraCanvasSize(){
  const stage=document.getElementById('canvas_stage');
  const button=document.getElementById('camera_fullscreen_btn');
  if(!stage || !canvas)return;
  const active=isCameraStageFullscreen();
  if(button){
    button.textContent=active?'⤢ Exit Fullscreen':'⛶ Fullscreen';
    button.setAttribute('aria-pressed',String(active));
    button.setAttribute('aria-label',active?'Exit camera fullscreen':'Expand camera frame to fullscreen');
    button.title=active?'Exit camera fullscreen (Esc)':'Expand camera frame to fullscreen';
  }
  /* The canvas is the fixed viewport. The camera image is aspect-fitted inside it,
     then zoomed/panned within the same clipping area so letterboxed space is usable. */
  const bounds=stage.getBoundingClientRect();
  const style=window.getComputedStyle(stage);
  const paddingX=(parseFloat(style.paddingLeft)||0)+(parseFloat(style.paddingRight)||0);
  const paddingY=(parseFloat(style.paddingTop)||0)+(parseFloat(style.paddingBottom)||0);
  const availableWidth=Math.max(1,stage.clientWidth-paddingX);
  const availableHeight=Math.max(1,stage.clientHeight-paddingY);
  if(!bounds.width||!bounds.height||!Number.isFinite(availableWidth)||!Number.isFinite(availableHeight))return;
  const width=Math.max(1,Math.round(availableWidth));
  const height=Math.max(1,Math.round(availableHeight));
  const resized=canvas.width!==width||canvas.height!==height;
  if(canvas.width!==width)canvas.width=width;
  if(canvas.height!==height)canvas.height=height;
  canvas.style.width=width+'px';
  canvas.style.height=height+'px';
  canvas.style.maxWidth='none';
  canvas.style.maxHeight='none';
  if(resized)renderWorkspaceCanvas();
}
async function toggleCameraFullscreen(){
  const stage=document.getElementById('canvas_stage');
  if(!stage)return;
  try{
    if(isCameraStageFullscreen()){
      if(document.exitFullscreen)await document.exitFullscreen();
      else if(document.webkitExitFullscreen)document.webkitExitFullscreen();
      return;
    }
    if(stage.requestFullscreen)await stage.requestFullscreen();
    else if(stage.webkitRequestFullscreen)stage.webkitRequestFullscreen();
    else {showToast('Fullscreen is not supported by this browser.');return;}
  }catch(error){
    showToast('Could not change camera fullscreen: '+(error&&error.message?error.message:'request denied'));
  }
}
function handleCameraFullscreenChange(){
  window.requestAnimationFrame(function(){
    syncCameraCanvasSize();
    renderWorkspaceCanvas();
  });
}
document.addEventListener('fullscreenchange',handleCameraFullscreenChange);
document.addEventListener('webkitfullscreenchange',handleCameraFullscreenChange);
window.addEventListener('resize',function(){
  syncCameraCanvasSize();
});
/* Refit if the settings dock or event console changes the stage dimensions. */
const cameraStage=document.getElementById('canvas_stage');
if(cameraStage&&typeof ResizeObserver!=='undefined'){
  const cameraStageObserver=new ResizeObserver(function(){
    window.requestAnimationFrame(syncCameraCanvasSize);
  });
  cameraStageObserver.observe(cameraStage);
}

/* ---------- Utilities & Math ---------- */
function clamp01(v){ return Math.max(0, Math.min(1, v)); }
function round01(v){ return Math.round(v*1000)/1000; }
function roundPixelNormalized(v){return Math.round(Number(v)*1000000)/1000000;} 
function showToast(text, timeout=2500){
    const t = document.getElementById('toast');
    t.textContent = text;
    t.style.display = 'block';
    if(typeof noteWorkspaceEvent==='function')noteWorkspaceEvent('info',text);
    setTimeout(()=> t.style.display='none', timeout);
}
function varColorByKey(key){
  let hex = key==='RL' ? ui.colors.RL : key==='LL' ? ui.colors.LL : key==='CW' ? ui.colors.CW :
    key==='ST' ? (ui.colors.ST || '#bf7bff') : key==='OBJ' ? (ui.colors.OBJ || '#ff5757') :
    key==='BEV' ? (ui.colors.BEV || '#d946ef') : '#9ad0ff';
  const opacity = Number((ui.opacity || {})[key] == null ? 1 : (ui.opacity || {})[key]);
  if(!hex || opacity >= 0.999) return hex || '#9ad0ff';
  const parts = String(hex).match(/^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i);
  if(!parts) return hex;
  return 'rgba(' + parseInt(parts[1],16) + ',' + parseInt(parts[2],16) + ',' + parseInt(parts[3],16) + ',' + Math.max(0,Math.min(1,opacity)) + ')';
}
function updateFrameModeText(){
    frameModeDisplay.textContent = !syncActive ? 'Dashboard requests: PAUSED' : (isFrozen ? 'Camera frame: Frozen (for precise tuning)' : 'Camera frame: Live');
}
function sendAdvanced(payload) {
    if(!syncActive) return showToast('Requests are stopped!');
    recordApiEvent('info','Saving advanced properties: '+Object.keys(payload).join(', '));
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
            recordApiEvent('error', 'Failed to save advanced settings: ' + err.message);
            console.error('Failed to save advanced settings:', err);
            showToast('Advanced settings failed: ' + err.message);
        });
}

// Convert image norm coords (0-1) to physical canvas coords, honoring workspace zoom
function getSourceFrameSize(){return{width:Math.max(1,Number(frameSourceWidth)||Number(lastFrameImage&&lastFrameImage.naturalWidth)||canvas.width),height:Math.max(1,Number(frameSourceHeight)||Number(lastFrameImage&&lastFrameImage.naturalHeight)||canvas.height)};}
function getGridStepX(){const source=getSourceFrameSize();return Math.max(0.001,Math.min(1,(Number(gridSpacing)||0.05)*source.height/source.width));}
function getBaseImgBounds(){const w=canvas.width,h=canvas.height,source=getSourceFrameSize(),scale=Math.min(w/source.width,h/source.height),iw=source.width*scale,ih=source.height*scale;return{ix:(w-iw)/2,iy:(h-ih)/2,iw,ih,scale,sourceWidth:source.width,sourceHeight:source.height};}
function getImgBounds(){const w=canvas.width,h=canvas.height,base=getBaseImgBounds(),iw=base.iw*workspaceZoom,ih=base.ih*workspaceZoom;return{ix:(w-iw)/2+viewPanX*base.scale,iy:(h-ih)/2+viewPanY*base.scale,iw,ih};}
function getOverlayScale(){return Math.max(.01,(getBaseImgBounds().scale||1)*(Number(workspaceZoom)||1));}
function canvasPointFromEvent(e){const r=canvas.getBoundingClientRect();if(!r.width||!r.height)return{x:0,y:0};return{x:(e.clientX-r.left)*canvas.width/r.width,y:(e.clientY-r.top)*canvas.height/r.height};}
function renderWorkspaceCanvas(){ctx.clearRect(0,0,canvas.width,canvas.height);if(lastFrameImage){const b=getImgBounds();ctx.drawImage(lastFrameImage,b.ix,b.iy,b.iw,b.ih);}drawOverlays();if(typeof window.drawPrecisionOverlay==='function')window.drawPrecisionOverlay();}

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

function getStreamDisplayFps(){return streamDisplayFps;}
function setStreamDisplayFps(value){
    const fps=Number(value);
    if(!Number.isFinite(fps)||fps<1||fps>30)throw new RangeError('Stream display FPS must be between 1 and 30.');
    streamDisplayFps=Math.round(fps*10)/10;
    if(fetchFrameTimer){
        clearInterval(fetchFrameTimer);
        fetchFrameTimer=setInterval(fetchFrameOnce,Math.max(33,Math.round(1000/streamDisplayFps)));
    }
    return streamDisplayFps;
}
window.getStreamDisplayFps=getStreamDisplayFps;
window.setStreamDisplayFps=setStreamDisplayFps;
function startFrameLoop(){
    if(fetchFrameTimer) clearInterval(fetchFrameTimer);
    fetchFrameTimer = setInterval(fetchFrameOnce, Math.max(33,Math.round(1000/streamDisplayFps)));
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

            // Keep source dimensions separate from the viewport backing store.
            // This preserves the camera aspect ratio inside a stage-sized canvas.
            const frameWidth = img.naturalWidth || img.width;
            const frameHeight = img.naturalHeight || img.height;
            if(frameWidth <= 0 || frameHeight <= 0) return;
            frameSourceWidth=frameWidth;
            frameSourceHeight=frameHeight;
            lastFrameImage=img;
            syncCameraCanvasSize();
            const rect = canvas.getBoundingClientRect();
            if(rect.width <= 0 || rect.height <= 0) return;
            renderWorkspaceCanvas();

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
function drawHandle(cx,cy,size,fill,stroke){
    const z=getOverlayScale();
    ctx.beginPath();ctx.fillStyle=fill;ctx.strokeStyle=stroke||'#000';
    ctx.lineWidth=Math.max(.5,(Number(roiAppearance.outlineThickness)||2)*z*.5);
    ctx.rect(cx-size/2,cy-size/2,size,size);ctx.fill();ctx.stroke();
}

function drawPolygon(points,color,isHighlight,labelText,r,fillAlpha=0.35){
    const z=getOverlayScale();
    ctx.beginPath();ctx.moveTo(points[0].x,points[0].y);for(let i=1;i<points.length;i++)ctx.lineTo(points[i].x,points[i].y);ctx.closePath();
    ctx.fillStyle=color;ctx.globalAlpha=fillAlpha;ctx.fill();ctx.globalAlpha=1;
    ctx.strokeStyle=isHighlight?'#fff':color;
    ctx.lineWidth=Math.max(.5,(Number(roiAppearance.outlineThickness)||2)*z+(isHighlight?z:0));
    ctx.setLineDash(isHighlight?[6*z,4*z]:[]);ctx.stroke();ctx.setLineDash([]);
    if(r&&labelText){
      const fs=Math.max(4,Math.min(64,(Number(roiAppearance.labelFontSize)||12)*z));
      ctx.font=String(roiAppearance.labelFontWeight||'700')+' '+fs+'px Arial,sans-serif';
      const pad=4*z,w=Math.ceil(ctx.measureText(labelText).width+pad*2),h=Math.ceil(fs+5*z);
      ctx.fillStyle=color;ctx.fillRect(r.x+4*z,r.y+4*z,w,h);ctx.fillStyle='#012';ctx.textBaseline='top';ctx.fillText(labelText,r.x+8*z,r.y+6*z);
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
            
            const z=getOverlayScale(),fs=Math.max(4,(Number(roiAppearance.labelFontSize)||12)*z);
            ctx.fillStyle=bevColor;ctx.fillRect(pts[0].x,pts[0].y-20*z,90*z,18*z);ctx.fillStyle='#fff';
            ctx.font=String(roiAppearance.labelFontWeight||'700')+' '+fs+'px Arial,sans-serif';ctx.fillText("BEV Region",pts[0].x+5*z,pts[0].y-7*z);
            const size=Math.max(2,(Number(roiAppearance.handleSize)||10)*z);
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
            
            const z=getOverlayScale();ctx.globalAlpha=1;
            ctx.strokeStyle=isHL?'rgba(255,255,255,.95)':'rgba(255,255,255,.24)';
            ctx.lineWidth=Math.max(.5,(Number(roiAppearance.outlineThickness)||2)*.5*z);
            ctx.setLineDash(isHL?[6*z,4*z]:[]);ctx.strokeRect(r.x,r.y,r.w,r.h);ctx.setLineDash([]);
            const size=Math.max(2,(Number(roiAppearance.handleSize)||10)*z);
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
    if(!showRectsCheckbox.checked)return {type:'none'};
    const scale=getOverlayScale();const size = Math.max(4,(Number(roiAppearance.handleSize)||10)*scale/2+3*scale);
    
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

canvas.addEventListener('auxclick',e=>{if(e.button===1)e.preventDefault();});canvas.addEventListener('contextmenu',e=>e.preventDefault());
canvas.addEventListener('wheel',e=>{e.preventDefault();const p=canvasPointFromEvent(e);setWorkspaceZoom(workspaceZoom*(e.deltaY<0?1.12:1/1.12),p.x,p.y);},{passive:false});
canvas.addEventListener('mousedown',e=>{
    if(e.button===1||(e.button===0&&workspaceTool==='pan')){e.preventDefault();if(workspaceViewLocked){showToast('View is locked. Unlock it to zoom or pan.');return;}const p=canvasPointFromEvent(e);viewPanState={startX:p.x,startY:p.y,originalX:viewPanX,originalY:viewPanY,imageScale:Math.max(0.0001,getBaseImgBounds().scale||1)};dragState=null;canvas.style.cursor='grabbing';noteWorkspaceEvent('info','Pan started (middle mouse / hand tool)');return;}
    if(e.button!==0||!syncActive||workspaceTool!=='select')return;
    const p=canvasPointFromEvent(e),px=p.x,py=p.y;
    const hit = hitTest(px, py);
    
    if(hit.group === 'BEV') {
        dragState = {type:'resize', group:'BEV', corner:hit.corner, start:{x:px,y:py}, orig: {...advanced}};
        markerHighlight = 'BEV';selectedVar='BEV_'+hit.corner;select.value=selectedVar;document.getElementById('prop_target').value=selectedVar;
        window.syncPropertiesSelection(selectedVar);
    } 
    else if(hit.type==='handle'){
        dragState = {type:'resize', group:hit.group, corner:hit.corner, origRect:hit.rect, start:{x:px,y:py}};
        markerHighlight = hit.group;
        selectedVar = hit.group;
        select.value = hit.group;
        document.getElementById('prop_target').value = hit.group;
        window.syncPropertiesSelection(hit.group);
    } 
    else if(hit.type==='inside'){
        dragState = {type:'move', group:hit.group, origRect:hit.rect, start:{x:px,y:py}};
        markerHighlight = hit.group;
        selectedVar = hit.group;
        select.value = hit.group;
        document.getElementById('prop_target').value = hit.group;
        window.syncPropertiesSelection(hit.group);
    } 
    else {
        dragState=null;markerHighlight=null;selectedVar='NONE';select.value='NONE';document.getElementById('prop_target').value='NONE';
        if(window.syncPropertiesSelection)window.syncPropertiesSelection('NONE');renderWorkspaceCanvas();
    }
});

canvas.addEventListener('mousemove',e=>{
    const p=canvasPointFromEvent(e),px=p.x,py=p.y;
    if(viewPanState){const scale=Math.max(0.0001,viewPanState.imageScale||1);viewPanX=viewPanState.originalX+(px-viewPanState.startX)/scale;viewPanY=viewPanState.originalY+(py-viewPanState.startY)/scale;canvas.style.cursor='grabbing';renderWorkspaceCanvas();return;}
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
        window.syncPropertiesSelection('BEV_' + c);
        
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
        const width=orig.r-orig.l,height=orig.b-orig.t;
        nx_l=Math.max(0,Math.min(1-width,orig.l+dnx));nx_r=nx_l+width;
        nx_t=Math.max(0,Math.min(1-height,orig.t+dny));nx_b=nx_t+height;
    } else {
        if(dragState.corner==='nw'){ nx_t = clamp01(orig.t + dny); nx_l = clamp01(orig.l + dnx); }
        if(dragState.corner==='ne'){ nx_t = clamp01(orig.t + dny); nx_r = clamp01(orig.r + dnx); }
        if(dragState.corner==='sw'){ nx_b = clamp01(orig.b + dny); nx_l = clamp01(orig.l + dnx); }
        if(dragState.corner==='se'){ nx_b = clamp01(orig.b + dny); nx_r = clamp01(orig.r + dnx); }
        if(nx_b <= nx_t) nx_b = nx_t + 0.01;
        if(nx_r <= nx_l) nx_r = nx_l + 0.01;
    }
    if(isEditorSnapEnabled()){
        const stepX=getGridStepX(),stepY=Math.max(.025,Math.min(.25,Number(gridSpacing)||.05));
        if(dragState.type==='move'){
            const w=nx_r-nx_l,h=nx_b-nx_t;nx_l=Math.max(0,Math.min(1-w,snapNormalized(nx_l,stepX)));nx_t=Math.max(0,Math.min(1-h,snapNormalized(nx_t,stepY)));nx_r=nx_l+w;nx_b=nx_t+h;
        }else{
            if(dragState.corner==='nw'||dragState.corner==='sw')nx_l=clamp01(snapNormalized(nx_l,stepX));
            if(dragState.corner==='ne'||dragState.corner==='se')nx_r=clamp01(snapNormalized(nx_r,stepX));
            if(dragState.corner==='nw'||dragState.corner==='ne')nx_t=clamp01(snapNormalized(nx_t,stepY));
            if(dragState.corner==='sw'||dragState.corner==='se')nx_b=clamp01(snapNormalized(nx_b,stepY));
            if(nx_r-nx_l<.01){if(dragState.corner==='nw'||dragState.corner==='sw')nx_l=Math.max(0,nx_r-.01);else nx_r=Math.min(1,nx_l+.01);}
            if(nx_b-nx_t<.01){if(dragState.corner==='nw'||dragState.corner==='ne')nx_t=Math.max(0,nx_b-.01);else nx_b=Math.min(1,nx_t+.01);}
        }
    }
    values[topVar] = round01(nx_t); values[bottomVar] = round01(nx_b);
    values[leftVar] = round01(nx_l); values[rightVar] = round01(nx_r);
    updateInputsFromValues(); 
    drawOverlays();
    window.syncPropertiesSelection(group);
    
    if(debounceTimers[group]) clearTimeout(debounceTimers[group]);
    debounceTimers[group] = setTimeout(()=>{
        sendUpdate({[topVar]:values[topVar], [bottomVar]:values[bottomVar], [leftVar]:values[leftVar], [rightVar]:values[rightVar]});
    }, 220);
});

window.addEventListener('mouseup',()=>{
    if(viewPanState){viewPanState=null;canvas.style.cursor=workspaceTool==='pan'?'grab':'default';noteWorkspaceEvent('info','Pan finished');return;}
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
function sendUpdate(data){
    if(!syncActive) return;
    recordApiEvent('info','Saving ROI/config fields: '+Object.keys(data).join(', '));
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
                if(window.syncPropertiesSelection)window.syncPropertiesSelection(document.getElementById('prop_target').value);
                showToast('Base Updated');
            } else {
                showToast((j && j.message) || 'Could not update base settings');
            }
        })
        .catch(err => {
            recordApiEvent('error', 'Failed to update base settings: ' + err.message);
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
document.getElementById('clear_selection').addEventListener('click',()=>{select.value='NONE';selectedVar='NONE';markerHighlight=null;document.getElementById('prop_target').value='NONE';if(window.syncPropertiesSelection)window.syncPropertiesSelection('NONE');renderWorkspaceCanvas();});

/* ---------- Pause Dashboard Requests Logic (robot RUN_LVL is unchanged) ---------- */
const stopAllBtn = document.getElementById('stop_all_btn');
stopAllBtn.addEventListener('click', () => {
    syncActive = !syncActive;
    if(!syncActive) {
        stopAllBtn.textContent = 'Resume Dashboard Requests';
        stopAllBtn.style.background = '#22c55e'; // Green when resuming
        clearInterval(fetchFrameTimer);
        fetchFrameTimer = null;
        clearInterval(valUpdateTimer);
        valUpdateTimer = null;
        clearInterval(healthUpdateTimer);
        healthUpdateTimer = null;
        clearInterval(arduinoUpdateTimer);
        arduinoUpdateTimer = null;
        if(typeof window.setStreamExtensionPollingEnabled==='function')window.setStreamExtensionPollingEnabled(false);
        updateFrameModeText();
        showToast('Dashboard polling paused; robot motion is unchanged');
    } else {
        stopAllBtn.textContent = 'Pause Dashboard Requests';
        stopAllBtn.style.background = '#ef4444'; // Red for pause
        if(typeof window.setStreamExtensionPollingEnabled==='function')window.setStreamExtensionPollingEnabled(true);
        startFrameLoop();
        if(!valUpdateTimer) valUpdateTimer = setInterval(fetchValuesLoop, 4000);
        if(!healthUpdateTimer) healthUpdateTimer = setInterval(updateHealth, 1000);
        if(!arduinoUpdateTimer) arduinoUpdateTimer = setInterval(updateArduinoOutput, 1000);
        fetchValuesLoop();
        updateHealth();
        updateArduinoOutput();
        updateFrameModeText();
        showToast('Dashboard polling resumed; robot run state is unchanged');
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
    fetch('/freeze_frame', {method:'POST'}).then(()=> {isFrozen=true; updateFrameModeText(); updateZoomStatus(); showToast('Frame frozen'); noteWorkspaceEvent('info','Camera frame frozen');})
});
document.getElementById('unfreeze_btn').addEventListener('click', ()=> {
    if(!syncActive) return showToast('Requests are stopped!');
    fetch('/unfreeze_frame', {method:'POST'}).then(()=> {isFrozen=false; updateFrameModeText(); updateZoomStatus(); showToast('Back to live'); noteWorkspaceEvent('info','Live camera resumed');})
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
            noteWorkspaceEvent('info',isRecording?'Video recording started':'Video recording stopped');
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
            const healthStateName = String(h.state || 'UNKNOWN');
            state.textContent = 'State: ' + healthStateName;
            if(lastLoggedHealthState !== healthStateName) {
                noteWorkspaceEvent(healthStateName === 'HEALTHY' || healthStateName === 'OK' ? 'info' : 'warn', 'Runtime health state: ' + (lastLoggedHealthState || 'initial') + ' → ' + healthStateName);
                lastLoggedHealthState = healthStateName;
            }
            const names = Object.keys(h.faults || {});
            const details = names.map(name => {
                const fault = h.faults[name] || {};
                return name + (fault.message ? ': ' + fault.message : '');
            });
            const faultSignature = details.join(' | ');
            faults.textContent = 'Faults: ' + (details.length ? faultSignature : 'none');
            if(lastLoggedFaultSignature !== faultSignature) {
                if(faultSignature) noteWorkspaceEvent('error', 'Runtime faults: ' + faultSignature);
                else if(lastLoggedFaultSignature) noteWorkspaceEvent('info', 'Runtime faults cleared');
                lastLoggedFaultSignature = faultSignature;
            }
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
            const arduinoStateText = 'State: ' + (j.state || 'UNKNOWN') + ' | Connected: ' + (j.connected ? 'yes' : 'no');
            status.textContent = arduinoStateText;
            if(lastLoggedArduinoState !== arduinoStateText) {
                noteWorkspaceEvent(j.connected ? 'info' : 'warn', 'Arduino telemetry: ' + arduinoStateText);
                lastLoggedArduinoState = arduinoStateText;
            }
            output.textContent = (j.lines || []).join('\\n');
            output.scrollTop = output.scrollHeight;
        })
        .catch(()=>{});
}

function fetchValuesLoop(){
 if(!syncActive)return;
 fetchDashboardJson('/get_values').then(j=>{
  if(!j||!j.values)return;
  values=j.values;updateInputsFromValues();
  const active=document.activeElement;
  const editingProperty=active&&['prop_left','prop_top','prop_right','prop_bottom','prop_point_x','prop_point_y'].includes(active.id);
  if(!editingProperty&&window.syncPropertiesSelection)window.syncPropertiesSelection(document.getElementById('prop_target').value);
  drawOverlays();
 });
}

function loadModeFeatures(){
    fetchDashboardJson('/api/mode').then(j=>{
        if(!j) return;
        const f=j.features || {};
        const c=j.capabilities || {};
        const lane = f.lane_detector || 'default';
        const modeSignature = String(lane) + ' | BEV: ' + (f.bev ? 'on' : 'off') + ' | ML: ' + (f.ml_lane_detector ? 'on' : 'off') + ' | Marker: ' + (f.marker_mode || 'none');
        document.getElementById('mode_features').textContent = 'Lane: ' + lane + ' | BEV: ' + (f.bev ? 'on' : 'off') + ' | ML: ' + (f.ml_lane_detector ? 'on' : 'off') + ' | Marker: ' + (f.marker_mode || 'none');
        if(lastLoggedModeSignature !== modeSignature) { noteWorkspaceEvent('info', 'Runtime mode features: ' + modeSignature); lastLoggedModeSignature = modeSignature; }

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
                if(!['refresh_vals','toggle_dock_btn','camera_fullscreen_btn','workspace_view_lock','workspace_zoom','variable_select','clear_selection','center_reset','prop_target','prop_revert_btn','tool_overlays_btn','console_toggle_btn','console_clear_btn','roi_settings_open','roi_settings_close','roi_settings_cancel','roi_settings_reset','roi_settings_apply','roi_setting_grid_mode','roi_setting_grid_spacing','roi_setting_grid_opacity','roi_setting_grid_thickness','roi_setting_grid_dot_size','roi_setting_grid_color','roi_setting_keyboard_nudge','roi_setting_stream_fps','roi_setting_snap','roi_setting_label_size','roi_setting_label_weight','roi_setting_outline_thickness','roi_setting_handle_size','ext_grid','ext_snap','ext_crosshair'].includes(el.id)&&!el.hasAttribute('data-tool')&&!el.hasAttribute('data-action')&&!el.hasAttribute('data-console-tab'))el.disabled=true;
            });
        }
        document.querySelectorAll('input[name^="CW_"]').forEach(el=>disable(el, !c.supports_crosswalk, 'Crosswalk ROI is not consumed by the active mode.'));
        document.querySelectorAll('input[name^="OBJ_"]').forEach(el=>disable(el, !c.supports_object_detection, 'Object detection ROI is not used by the active mode.'));
    }).catch(()=>{});
}


function openStreamShortcuts(){
  const dialog=document.getElementById('shortcut_dialog');if(!dialog)return;
  window.__streamShortcutReturnFocus=document.activeElement;
  dialog.classList.add('is-open');dialog.setAttribute('aria-hidden','false');
  const close=document.getElementById('shortcut_close');if(close)close.focus();
}
function closeStreamShortcuts(){
  const dialog=document.getElementById('shortcut_dialog');if(!dialog)return;
  dialog.classList.remove('is-open');dialog.setAttribute('aria-hidden','true');
  const target=window.__streamShortcutReturnFocus;window.__streamShortcutReturnFocus=null;
  if(target&&typeof target.focus==='function')target.focus();
}
window.openStreamShortcuts=openStreamShortcuts;
window.closeStreamShortcuts=closeStreamShortcuts;
function setupCadWorkspace(){
const workspace=document.querySelector('.container'),dockToggle=document.getElementById('toggle_dock_btn'),consoleDock=document.getElementById('bottom_console'),consoleToggle=document.getElementById('console_toggle_btn'),consoleClear=document.getElementById('console_clear_btn'),propTarget=document.getElementById('prop_target');let consoleTab='events';
const narrow=()=>window.matchMedia('(max-width:720px)').matches;
let dockIsOpen=!narrow();
const dockVisible=()=>dockIsOpen;
function setDock(open){
  dockIsOpen=Boolean(open);
  const isNarrow=narrow();
  workspace.classList.toggle('show-dock',isNarrow&&dockIsOpen);
  workspace.classList.toggle('dock-hidden',!isNarrow&&!dockIsOpen);
  const dockLabel=dockToggle.querySelector('#toggle_dock_label');if(dockLabel)dockLabel.textContent=dockIsOpen?'Hide Panels':'Show Panels';else dockToggle.textContent=dockIsOpen?'Hide Panels':'Show Panels';
  dockToggle.setAttribute('aria-expanded',String(dockIsOpen));
  dockToggle.setAttribute('aria-label',dockIsOpen?'Hide settings panels':'Show settings panels');
  const menuDockToggle=document.querySelector('[data-action="toggle-properties"]');
  if(menuDockToggle)menuDockToggle.textContent=dockIsOpen?'Hide Panels':'Show Panels';
  window.requestAnimationFrame(()=>{syncCameraCanvasSize();renderWorkspaceCanvas();if(typeof window.drawPrecisionOverlay==='function')window.drawPrecisionOverlay();});
}
window.ensureStreamDockVisible=()=>setDock(true);
dockToggle.addEventListener('click',()=>{
  const open=!dockIsOpen;
  setDock(open);
  noteWorkspaceEvent('info','Settings dock '+(open?'shown':'hidden'));
});
const shortcutDialog=document.getElementById('shortcut_dialog'),shortcutClose=document.getElementById('shortcut_close'),shortcutDone=document.getElementById('shortcut_done');
if(shortcutClose)shortcutClose.addEventListener('click',closeStreamShortcuts);
if(shortcutDone)shortcutDone.addEventListener('click',closeStreamShortcuts);
if(shortcutDialog)shortcutDialog.addEventListener('click',e=>{if(e.target===shortcutDialog)closeStreamShortcuts();});
window.addEventListener('resize',()=>setDock(dockIsOpen));
setDock(dockIsOpen);
function setConsoleOpen(open){consoleDock.classList.toggle('console-open',open);consoleToggle.setAttribute('aria-expanded',String(open));}
consoleToggle.addEventListener('click',()=>setConsoleOpen(!consoleDock.classList.contains('console-open')));
consoleClear.addEventListener('click',()=>{if(consoleTab==='api')workspaceApiEvents=[];else workspaceEvents=[];renderWorkspaceEventLog(consoleTab);noteWorkspaceEvent('info','Event log cleared',consoleTab);});
document.querySelectorAll('[data-console-tab]').forEach(b=>b.addEventListener('click',()=>{consoleTab=b.dataset.consoleTab;document.querySelectorAll('[data-console-tab]').forEach(t=>t.setAttribute('aria-selected',String(t===b)));document.getElementById('console_events').hidden=consoleTab!=='events';document.getElementById('console_api').hidden=consoleTab!=='api';renderWorkspaceEventLog(consoleTab);}));
document.querySelectorAll('.menu-group').forEach(m=>m.addEventListener('toggle',()=>{if(m.open)document.querySelectorAll('.menu-group').forEach(o=>{if(o!==m)o.open=false;});}));document.addEventListener('click',e=>{if(!e.target.closest('.menu-group'))document.querySelectorAll('.menu-group').forEach(m=>m.open=false);});
function setTool(tool){if(tool==='pan'&&workspaceViewLocked){showToast('View is locked. Unlock it to pan.');tool='select';}workspaceTool=tool==='pan'?'pan':'select';document.querySelectorAll('[data-tool]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.tool===workspaceTool)));canvas.style.cursor=workspaceTool==='pan'?'grab':'default';noteWorkspaceEvent('info',workspaceTool==='pan'?'Hand / Pan tool selected':'Select / Edit ROI tool selected');if(typeof window.onStreamWorkspaceToolChanged==='function')window.onStreamWorkspaceToolChanged(workspaceTool);}
window.setStreamWorkspaceTool=setTool;
function zoomBy(f){setWorkspaceZoom(workspaceZoom*f,canvas.width/2,canvas.height/2);}
function toggleOverlays(){showRectsCheckbox.checked=!showRectsCheckbox.checked;document.getElementById('tool_overlays_btn').setAttribute('aria-pressed',String(showRectsCheckbox.checked));renderWorkspaceCanvas();noteWorkspaceEvent('info','Overlays '+(showRectsCheckbox.checked?'shown':'hidden'));}
function toggleProperties(){const p=document.querySelector('.properties-panel');if(!dockVisible()){setDock(true);if(p)p.open=true;noteWorkspaceEvent('info','Properties panel shown');return;}if(p){p.open=!p.open;noteWorkspaceEvent('info','Properties panel '+(p.open?'opened':'closed'));}}
document.querySelectorAll('[data-tool]').forEach(b=>b.addEventListener('click',()=>setTool(b.dataset.tool)));
document.querySelectorAll('[data-action]').forEach(b=>b.addEventListener('click',()=>{switch(b.dataset.action){
case 'export-config':if(window.exportFullConfig)window.exportFullConfig().catch(err=>showToast('Export failed: '+err.message));else showToast('Full configuration export is unavailable.');break;case 'refresh-config':if(window.reloadFullConfig)window.reloadFullConfig().catch(err=>showToast('Reload failed: '+err.message));else document.getElementById('refresh_vals').click();noteWorkspaceEvent('info','Full configuration refresh requested');break;
case 'take-picture':document.getElementById('take_picture_btn').click();break;case 'exit-stream':if(window.openStreamExitDialog)window.openStreamExitDialog();else showToast('Stream exit dialog is unavailable.');break;case 'clear-selection':document.getElementById('clear_selection').click();break;case 'properties':toggleProperties();break;case 'toggle-properties':document.getElementById('toggle_dock_btn').click();break;
case 'zoom-in':zoomBy(1.2);break;case 'zoom-out':zoomBy(1/1.2);break;case 'fit-view':fitWorkspaceView();break;case 'toggle-fullscreen':toggleCameraFullscreen();break;case 'toggle-overlays':toggleOverlays();break;case 'toggle-console':setConsoleOpen(!consoleDock.classList.contains('console-open'));break;
case 'tool-select':setTool('select');break;case 'tool-pan':setTool('pan');break;case 'freeze':document.getElementById('freeze_btn').click();break;case 'unfreeze':document.getElementById('unfreeze_btn').click();break;
case 'help':openStreamShortcuts();break;}if(b.closest('.menu-group'))b.closest('.menu-group').open=false;}));
document.getElementById('center_reset').addEventListener('click',()=>fitWorkspaceView());document.getElementById('camera_fullscreen_btn').addEventListener('click',toggleCameraFullscreen);document.getElementById('tool_overlays_btn').addEventListener('click',toggleOverlays);
document.addEventListener('keydown',e=>{
  const tag=e.target&&e.target.tagName?e.target.tagName.toLowerCase():'';
  if(e.code==='F1'){e.preventDefault();openStreamShortcuts();return;}
  if((e.ctrlKey||e.metaKey)&&e.code==='Backquote'){e.preventDefault();setConsoleOpen(!consoleDock.classList.contains('console-open'));return;}
  if(['input','textarea','select'].includes(tag)||e.target?.isContentEditable)return;
  if(e.code==='Slash'&&e.shiftKey&&!e.ctrlKey&&!e.metaKey&&!e.altKey){e.preventDefault();openStreamShortcuts();return;}
  if(e.code==='Escape'){
    if(document.getElementById('shortcut_dialog')?.classList.contains('is-open')){closeStreamShortcuts();return;}
    document.querySelectorAll('.menu-group').forEach(m=>m.open=false);return;
  }
  if(e.ctrlKey||e.metaKey||e.altKey)return;
  if(e.code==='KeyH')setTool('pan');else if(e.code==='KeyV')setTool('select');else if(e.code==='Digit0')fitWorkspaceView();else if(e.code==='KeyO')toggleOverlays();else if(e.code==='KeyF')toggleCameraFullscreen();else if(e.code==='Equal'||e.code==='NumpadAdd')zoomBy(1.2);else if(e.code==='Minus'||e.code==='NumpadSubtract')zoomBy(1/1.2);
 });
function names(g){const p=g+'_';return{top:p+'TOP_ROI',bottom:p+'BOTTOM_ROI',left:p+'LEFT_ROI',right:p+'RIGHT_ROI'};}
function info(){if(propTarget.value==='NONE')return{kind:'none'};return propTarget.value.startsWith('BEV_')?{kind:'point',corner:propTarget.value.slice(4)}:{kind:'roi',group:propTarget.value};}
function syncPropertiesSelection(target){
 if(!target)target='NONE';propTarget.value=target;const st=info();
 document.getElementById('prop_roi_fields').hidden=st.kind!=='roi';document.getElementById('prop_point_fields').hidden=st.kind!=='point';
 const mirror=document.getElementById('roi_mirror_actions');if(mirror)mirror.hidden=!(st.kind==='roi'&&(st.group==='RL'||st.group==='LL'));
 if(st.kind==='none'){
  selectedVar='NONE';select.value='NONE';markerHighlight=null;document.getElementById('properties_mode').textContent='No object selected';
  ['prop_left','prop_top','prop_right','prop_bottom','prop_point_x','prop_point_y'].forEach(id=>document.getElementById(id).value='');
  document.getElementById('prop_hint').textContent='Select an ROI or BEV control point to inspect or edit.';document.getElementById('cad_selected_area').textContent='Object: NONE';return;
 }
 if(st.kind==='roi'){
  selectedVar=st.group;select.value=st.group;const n=names(st.group);
  document.getElementById('properties_mode').textContent=({RL:'Right Lane ROI',LL:'Left Lane ROI',CW:'Crosswalk ROI',ST:'Sign / Tag ROI',OBJ:'Object ROI'})[st.group]+' · bounds';
  document.getElementById('prop_left').value=values[n.left]??'';document.getElementById('prop_top').value=values[n.top]??'';document.getElementById('prop_right').value=values[n.right]??'';document.getElementById('prop_bottom').value=values[n.bottom]??'';
  document.getElementById('prop_hint').textContent='Normalized camera coordinates (0–1). Drag this ROI, use arrow keys, or edit fields.';document.getElementById('cad_selected_area').textContent='Object: '+st.group;
 }else{
  selectedVar='BEV_'+st.corner;select.value=selectedVar;document.getElementById('properties_mode').textContent='BEV · '+st.corner+' control point';
  document.getElementById('prop_point_x').value=advanced['BEV_SRC_'+st.corner+'_X']??'';document.getElementById('prop_point_y').value=advanced['BEV_SRC_'+st.corner+'_Y']??'';
  document.getElementById('prop_hint').textContent='BEV point coordinates range from -5 to 5. Drag the corner or edit X/Y, then Apply.';document.getElementById('cad_selected_area').textContent='Object: BEV '+st.corner;
 }
}
window.syncPropertiesSelection=syncPropertiesSelection;
propTarget.addEventListener('change',()=>{const st=info();markerHighlight=st.kind==='point'?'BEV':st.kind==='roi'?st.group:null;syncPropertiesSelection(propTarget.value);renderWorkspaceCanvas();noteWorkspaceEvent('info','Properties target selected: '+propTarget.value);});
document.getElementById('prop_apply_btn').addEventListener('click',()=>{if(!syncActive)return showToast('Requests are stopped!');const s=info();if(s.kind==='roi'){const n=names(s.group);let l=Number(document.getElementById('prop_left').value),t=Number(document.getElementById('prop_top').value),r=Number(document.getElementById('prop_right').value),b=Number(document.getElementById('prop_bottom').value);if(![l,t,r,b].every(Number.isFinite))return showToast('Enter valid numeric ROI coordinates');l=clamp01(l);t=clamp01(t);r=clamp01(r);b=clamp01(b);if(r-l<.01||b-t<.01)return showToast('ROI requires right > left and bottom > top');values[n.left]=round01(l);values[n.top]=round01(t);values[n.right]=round01(r);values[n.bottom]=round01(b);updateInputsFromValues();renderWorkspaceCanvas();sendUpdate({[n.top]:values[n.top],[n.bottom]:values[n.bottom],[n.left]:values[n.left],[n.right]:values[n.right]});syncPropertiesSelection(s.group);noteWorkspaceEvent('info',s.group+' ROI properties applied');}
else if(s.kind==='point'){const c=s.corner,x=Number(document.getElementById('prop_point_x').value),y=Number(document.getElementById('prop_point_y').value);if(!Number.isFinite(x)||!Number.isFinite(y))return showToast('Enter valid BEV point coordinates');advanced['BEV_SRC_'+c+'_X']=Math.max(-5,Math.min(5,round01(x)));advanced['BEV_SRC_'+c+'_Y']=Math.max(-5,Math.min(5,round01(y)));updateShapeUIFromData();renderWorkspaceCanvas();sendAdvanced({['BEV_SRC_'+c+'_X']:advanced['BEV_SRC_'+c+'_X'],['BEV_SRC_'+c+'_Y']:advanced['BEV_SRC_'+c+'_Y']});syncPropertiesSelection('BEV_'+c);noteWorkspaceEvent('info','BEV '+c+' point properties applied');}else{return showToast('Select an ROI or BEV point first.');}});
document.getElementById('prop_revert_btn').addEventListener('click',()=>syncPropertiesSelection(propTarget.value));
function mirrorLaneRoi(source,destination){
 if(!STREAM_CONTROL_ALLOWED)return showToast('Dashboard is read-only; ROI changes are disabled.');if(!syncActive)return showToast('Requests are stopped!');
 const src=names(source),dst=names(destination),l=Number(values[src.left]),r=Number(values[src.right]),t=Number(values[src.top]),b=Number(values[src.bottom]);
 if(![l,r,t,b].every(Number.isFinite)||r-l<.01||b-t<.01)return showToast('Source ROI geometry is invalid; mirroring was not applied.');
 const left=round01(1-r),right=round01(1-l);if(right-left<.01)return showToast('Mirrored ROI is invalid.');
 values[dst.left]=left;values[dst.right]=right;values[dst.top]=round01(t);values[dst.bottom]=round01(b);
 const sourceFactorKey=source+'_TOP_WIDTH_FACTOR',destinationFactorKey=destination+'_TOP_WIDTH_FACTOR',factorPayload={};
 if(Object.prototype.hasOwnProperty.call(advanced,sourceFactorKey)&&Object.prototype.hasOwnProperty.call(advanced,destinationFactorKey)&&Number.isFinite(Number(advanced[sourceFactorKey]))){
   advanced[destinationFactorKey]=Math.max(0,Math.min(1,Number(advanced[sourceFactorKey])));
   factorPayload[destinationFactorKey]=advanced[destinationFactorKey];
   updateShapeUIFromData();
 }
 markerHighlight=destination;selectedVar=destination;select.value=destination;propTarget.value=destination;updateInputsFromValues();renderWorkspaceCanvas();syncPropertiesSelection(destination);
 sendUpdate({[dst.top]:values[dst.top],[dst.bottom]:values[dst.bottom],[dst.left]:values[dst.left],[dst.right]:values[dst.right]});
 if(Object.keys(factorPayload).length)sendAdvanced(factorPayload);
 noteWorkspaceEvent('info','Mirrored '+source+' ROI to '+destination+' around normalized image center, including lane shape when available.');
 showToast('Mirrored '+(source==='LL'?'Left':'Right')+' ROI to '+(destination==='RL'?'Right':'Left')+'.');
}
document.getElementById('mirror_left_to_right').addEventListener('click',()=>mirrorLaneRoi('LL','RL'));
document.getElementById('mirror_right_to_left').addEventListener('click',()=>mirrorLaneRoi('RL','LL'));
let keyboardRoiSaveTimer=null,keyboardRoiPendingGroup=null;
function flushKeyboardRoiMove(){if(keyboardRoiSaveTimer){clearTimeout(keyboardRoiSaveTimer);keyboardRoiSaveTimer=null;}const g=keyboardRoiPendingGroup;keyboardRoiPendingGroup=null;if(!g||!['RL','LL','CW','ST','OBJ'].includes(g))return;const n=names(g);sendUpdate({[n.top]:values[n.top],[n.bottom]:values[n.bottom],[n.left]:values[n.left],[n.right]:values[n.right]});}
function scheduleKeyboardRoiMove(g){keyboardRoiPendingGroup=g;if(keyboardRoiSaveTimer)clearTimeout(keyboardRoiSaveTimer);keyboardRoiSaveTimer=setTimeout(flushKeyboardRoiMove,220);}
document.addEventListener('keydown',function(e){
 const dirs={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};const d=dirs[e.code]||dirs[e.key];if(!d)return;
 const target=e.target,tag=target&&target.tagName?target.tagName.toLowerCase():'';
 if(['input','textarea','select','button'].includes(tag)||target?.isContentEditable||document.getElementById('roi_settings_dialog').classList.contains('is-open'))return;
 if(workspaceTool!=='select'||!STREAM_CONTROL_ALLOWED||!syncActive)return;const g=markerHighlight;if(!['RL','LL','CW','ST','OBJ'].includes(g))return;
 const n=names(g),l=Number(values[n.left]),r=Number(values[n.right]),t=Number(values[n.top]),b=Number(values[n.bottom]);if(![l,r,t,b].every(Number.isFinite))return;e.preventDefault();
 const source=getSourceFrameSize();
 const pixelStep=(typeof window.__getStreamKeyboardNudgePx==='function'?window.__getStreamKeyboardNudgePx():5)*(e.shiftKey?5:1);
 const stepX=pixelStep/source.width,stepY=pixelStep/source.height,w=r-l,h=b-t;
 let nl=l+d[0]*stepX,nt=t+d[1]*stepY;
 // Arrow-key nudging stays pixel-accurate even when mouse drag snapping is enabled.
 nl=Math.max(0,Math.min(1-w,nl));nt=Math.max(0,Math.min(1-h,nt));
 values[n.left]=roundPixelNormalized(nl);values[n.right]=roundPixelNormalized(nl+w);values[n.top]=roundPixelNormalized(nt);values[n.bottom]=roundPixelNormalized(nt+h);
 selectedVar=g;select.value=g;propTarget.value=g;markerHighlight=g;updateInputsFromValues();syncPropertiesSelection(g);renderWorkspaceCanvas();scheduleKeyboardRoiMove(g);
});
document.addEventListener('keyup',e=>{if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.code)||['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))flushKeyboardRoiMove();});window.addEventListener('blur',flushKeyboardRoiMove);

const readout={x:document.getElementById('cad_cursor_x'),y:document.getElementById('cad_cursor_y'),u:document.getElementById('cad_cursor_u'),v:document.getElementById('cad_cursor_v'),area:document.getElementById('cad_selected_area')};
function updateCadReadout(e){const r=canvas.getBoundingClientRect();if(!r.width||!r.height)return;const p=canvasPointFromEvent(e),b=getImgBounds(),u=(p.x-b.ix)/b.iw,v=(p.y-b.iy)/b.ih;if(u<0||u>1||v<0||v>1){readout.x.textContent='X: — px';readout.y.textContent='Y: — px';readout.u.textContent='U: — %';readout.v.textContent='V: — %';return;}const source=getSourceFrameSize();readout.x.textContent='X: '+Math.round(u*source.width)+' px';readout.y.textContent='Y: '+Math.round(v*source.height)+' px';readout.u.textContent='U: '+(u*100).toFixed(1)+' %';readout.v.textContent='V: '+(v*100).toFixed(1)+' %';}
canvas.addEventListener('mousemove',updateCadReadout,{passive:true});canvas.addEventListener('mouseleave',()=>{if(!viewPanState){readout.x.textContent='X: — px';readout.y.textContent='Y: — px';readout.u.textContent='U: — %';readout.v.textContent='V: — %';}},{passive:true});
select.addEventListener('change',()=>{flushKeyboardRoiMove();const t=select.value;if(t==='NONE'){markerHighlight=null;selectedVar='NONE';document.getElementById('prop_target').value='NONE';window.syncPropertiesSelection('NONE');}else if(t.startsWith('BEV_')){markerHighlight='BEV';selectedVar=t;document.getElementById('prop_target').value=t;window.syncPropertiesSelection(t);}else if(['RL','LL','CW','ST','OBJ'].includes(t)){markerHighlight=t;selectedVar=t;document.getElementById('prop_target').value=t;window.syncPropertiesSelection(t);}readout.area.textContent='Object: '+(t==='NONE'?'NONE':t.startsWith('BEV_')?'BEV '+t.slice(4):t);renderWorkspaceCanvas();});
noteWorkspaceEvent('info','Workspace initialized; middle mouse pans and wheel zooms at cursor');renderWorkspaceEventLog('events');renderWorkspaceEventLog('api');window.syncPropertiesSelection('NONE');updateZoomStatus();
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
