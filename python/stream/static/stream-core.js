
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
const STREAM_VIEW_ONLY_ACTIONS = new Set([
    'export-config', 'refresh-config', 'clear-selection', 'properties',
    'toggle-properties', 'zoom-in', 'zoom-out', 'fit-view', 'toggle-fullscreen',
    'toggle-overlays', 'toggle-console', 'tool-select', 'tool-pan',
    'freeze', 'unfreeze', 'help'
]);
const STREAM_VIEW_ONLY_IDS = new Set([
    'refresh_vals', 'toggle_dock_btn', 'camera_fullscreen_btn', 'freeze_btn', 'unfreeze_btn',
    'workspace_view_lock', 'workspace_zoom', 'variable_select', 'clear_selection',
    'center_reset', 'prop_target', 'prop_revert_btn', 'tool_overlays_btn',
    'show_rects', 'console_toggle_btn', 'console_clear_btn', 'console_filter',
    'console_level', 'console_pause', 'console_autoscroll', 'roi_settings_open',
    'roi_settings_close', 'roi_settings_cancel', 'roi_settings_reset',
    'roi_settings_apply', 'roi_setting_grid_mode', 'roi_setting_grid_spacing',
    'roi_setting_grid_opacity', 'roi_setting_grid_thickness',
    'roi_setting_grid_dot_size', 'roi_setting_grid_color',
    'roi_setting_keyboard_nudge', 'roi_setting_stream_fps', 'roi_setting_snap',
    'roi_setting_label_size', 'roi_setting_label_weight', 'roi_setting_label_shape',
    'roi_setting_outline_thickness', 'roi_setting_handle_size',
    'ext_grid', 'ext_overlays', 'ext_snap', 'ext_crosshair', 'ext_measure_mm_per_px', 'ext_measure_scale_apply',
    'wb_preview_btn', 'wb_profile_select', 'wb_profile_export', 'wb_diagnostics_btn', 'wb_live_stage', 'wb_live_refresh', 'wb_live_auto'
]);
function syncStreamPermissionUI(){
    const permission=STREAM_CONTROL_ALLOWED?'enabled':'read-only';
    document.documentElement.dataset.streamControlPermission=permission;
    if(controlNotice){
        controlNotice.textContent=STREAM_CONTROL_ALLOWED
            ? 'Dashboard control is enabled.'
            : 'Read-only dashboard: runtime/configuration changes are disabled; viewing, zoom, overlays and console tools remain available.';
        controlNotice.setAttribute('role','status');
        controlNotice.dataset.permission=permission;
    }
    if(STREAM_CONTROL_ALLOWED)return;
    document.querySelectorAll('button[data-action]').forEach(function(button){
        if(!STREAM_VIEW_ONLY_ACTIONS.has(button.dataset.action))button.disabled=true;
    });
    document.querySelectorAll('button,input,select').forEach(function(control){
        const viewOnlyAction=control.hasAttribute('data-action')&&STREAM_VIEW_ONLY_ACTIONS.has(control.dataset.action);
        if(!STREAM_VIEW_ONLY_IDS.has(control.id)
            && !control.hasAttribute('data-tool')
            && !control.hasAttribute('data-console-tab')
            && !viewOnlyAction){
            control.disabled=true;
        }
    });
}
syncStreamPermissionUI();

let selectedVar = 'NONE';
let markerHighlight = null;
let roiAppearance = {labelFontSize:12, labelFontWeight:'700', outlineThickness:2, handleSize:10, showShapeType:false};
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
const roiDirtyFields = new Set();
const roiEditVersions = Object.create(null);
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
const WORKSPACE_EVENT_LIMIT=250;let workspaceEvents=[],workspaceApiEvents=[],workspacePythonLogs=[];
let lastLoggedHealthState=null,lastLoggedFaultSignature=null,lastLoggedArduinoState=null,lastLoggedModeSignature=null;
function noteWorkspaceEvent(level,message,channel='events'){const entry={time:new Date(),level:String(level||'info').toLowerCase(),message:String(message||'')};const store=channel==='api'?workspaceApiEvents:workspaceEvents;store.push(entry);if(store.length>WORKSPACE_EVENT_LIMIT)store.splice(0,store.length-WORKSPACE_EVENT_LIMIT);renderWorkspaceEventLog(channel==='api'?'api':'events');}
let workspaceConsolePaused=false,workspaceConsoleAutoScroll=true,workspaceConsoleQuery='',workspaceConsoleLevel='ALL';
function updateConsoleTabCounts(){
  const counters=[
    ['console_count_events',workspaceEvents.length,'events'],
    ['console_count_api',workspaceApiEvents.length,'requests'],
    ['console_count_python',workspacePythonLogs.length,'Python logs']
  ];
  for(const [id,count,label] of counters){
    const badge=document.getElementById(id);
    if(!badge)continue;
    badge.textContent=count>99?'+99':String(count);
    badge.title=String(count)+' '+label;
    badge.setAttribute('aria-label',String(count)+' '+label);
  }
}
function renderWorkspaceEventLog(channel='events'){
  updateConsoleTabCounts();
  if(workspaceConsolePaused)return;
  const store=channel==='api'?workspaceApiEvents:channel==='python'?workspacePythonLogs:workspaceEvents;
  const root=document.getElementById(channel==='api'?'console_api':channel==='python'?'console_python':'console_events');if(!root)return;
  root.replaceChildren();
  const query=workspaceConsoleQuery.trim().toLowerCase();
  const selected=store.slice().reverse().filter(function(entry){
    const level=String(entry.level||'info').toUpperCase();
    return (workspaceConsoleLevel==='ALL'||level===workspaceConsoleLevel)&&(!query||(String(entry.message||'')+' '+level).toLowerCase().includes(query));
  });
  if(!selected.length){const e=document.createElement('div');e.className='console-empty';e.textContent=store.length?'No matching console entries.':channel==='api'?'No request diagnostics yet.':channel==='python'?'No Python runtime logs yet.':'No events yet.';root.appendChild(e);}
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
  if(typeof window.scheduleStreamWorkspaceSave==='function')window.scheduleStreamWorkspaceSave();
  if(log)noteWorkspaceEvent('info','View zoom: '+Math.round(z*100)+'%');return true;
}
function updateWorkspaceViewLockUI(){
  const button=document.getElementById('workspace_view_lock');
  const slider=document.getElementById('workspace_zoom');
  const zoomPercent=document.getElementById('workspace_zoom_percent');
  const shackle=document.getElementById('workspace_lock_shackle');
  const label=document.getElementById('workspace_view_lock_label');
  const message=workspaceViewLocked?'Unlock view (allow zoom and pan)':'Lock zoom and camera position';
  if(button){button.setAttribute('aria-pressed',String(workspaceViewLocked));button.setAttribute('aria-label',message);button.classList.toggle('is-locked',workspaceViewLocked);}
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
    const label=document.getElementById('camera_fullscreen_label');
    const expandIcon=document.getElementById('camera_fullscreen_expand_icon');
    const collapseIcon=document.getElementById('camera_fullscreen_collapse_icon');
    if(label)label.textContent=active?'Exit Fullscreen':'Fullscreen';
    if(expandIcon)expandIcon.style.display=active?'none':'';
    if(collapseIcon)collapseIcon.style.display=active?'':'none';
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
    const paused=!syncActive;
    frameModeDisplay.textContent = paused ? 'Dashboard requests: PAUSED' : (isFrozen ? 'Frozen frame · precise tuning' : '');
    frameModeDisplay.hidden = !paused && !isFrozen;
}
async function sendAdvanced(payload) {
    if(!syncActive) {
        showToast('Requests are stopped!');
        return false;
    }
    recordApiEvent('info','Saving advanced properties: '+Object.keys(payload).join(', '));
    try {
        const response = await fetch('/set_advanced',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
        const data = await response.json().catch(() => ({}));
        if(!response.ok) throw new Error(data.message || 'HTTP ' + response.status);
        if(!data || !data.success) {
            const message = (data && data.message) || 'Could not save advanced settings';
            showToast(message);
            return false;
        }
        advanced = data.advanced;
        updateShapeUIFromData();
        showToast('Advanced settings saved');
        return true;
    } catch(err) {
        recordApiEvent('error', 'Failed to save advanced settings: ' + err.message);
        console.error('Failed to save advanced settings:', err);
        showToast('Advanced settings failed: ' + err.message);
        return false;
    }
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

