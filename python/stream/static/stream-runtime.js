/* ---------- Init ---------- */
function updateHealth(){
    if(!syncActive) return;
    fetchDashboardJson('/api/health')
        .then(j=>{
            if(!j) return;
            window.__streamLatestHealth = {payload:j, receivedAt:Date.now()};
            window.dispatchEvent(new CustomEvent('stream:health', {detail:window.__streamLatestHealth}));
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
            const faultSignature = names.slice().sort().map(name => {
                const fault = (h.faults || {})[name] || {};
                return name + ':' + String(fault.severity || 'unknown');
            }).join(' | ');
            const faultDetails = details.join(' | ');
            faults.textContent = 'Faults: ' + (faultDetails || 'none');
            if(lastLoggedFaultSignature !== faultSignature) {
                if(faultSignature) noteWorkspaceEvent('error', 'Runtime faults: ' + faultDetails);
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

function setArduinoHardwareNotice(id,message,tone='info'){
    const node=document.getElementById(id);
    if(!node)return;
    node.textContent=message;
    node.dataset.tone=tone;
}
function syncAutomaticCommandButton(button,enabled){
    if(!button)return;
    const on=!!enabled;
    button.setAttribute('aria-pressed',String(on));
    button.dataset.enabled=String(on);
    button.classList.toggle('is-enabled',on);
    button.classList.toggle('is-disabled',!on);
    button.textContent=on?'ON · ENABLED':'OFF · SUPPRESSED';
    button.title=on
        ?'Automatic Python control/configuration commands are enabled. Click to suppress them.'
        :'Automatic Python control/configuration commands are suppressed. Click to enable them.';
    button.setAttribute('aria-label',on
        ?'Automatic Python control/configuration commands enabled; click to disable'
        :'Automatic Python control/configuration commands suppressed; click to enable');
}
function updateArduinoHardwareUi(j){
    const withoutArduino=j.without_arduino===true;
    const connected=!withoutArduino&&j.connected===true;
    const telemetryNotice=withoutArduino
        ?'Arduino is disabled for this run (--without-arduino). No serial port is opened, so telemetry and manual commands are unavailable. The automatic-command preference can still be saved for a future hardware-enabled run.'
        :connected
            ?'Arduino serial connection is active. Telemetry and custom commands are available.'
            :'Arduino is not currently connected. The background reconnect worker may recover; commands cannot be sent until the serial link reconnects.';
    const commandNotice=withoutArduino
        ?'Unavailable: this run uses --without-arduino. Custom commands are blocked because no Arduino serial connection is opened.'
        :connected
            ?'Arduino is connected. Custom commands can be sent; they bypass the automatic Python-command setting.'
            :'Unavailable: Arduino is disconnected. Custom commands will remain disabled until reconnect succeeds.';
    const tone=withoutArduino?'error':connected?'success':'warning';
    setArduinoHardwareNotice('arduino_hardware_notice',telemetryNotice,tone);
    setArduinoHardwareNotice('console_arduino_notice',telemetryNotice,tone);
    setArduinoHardwareNotice('arduino_commands_hardware_notice',commandNotice,tone);

    const form=document.getElementById('arduino_command_form');
    const pending=!!(form&&form.dataset.sending==='true');
    const canSend=STREAM_CONTROL_ALLOWED&&!withoutArduino&&connected&&!pending;
    const input=document.getElementById('arduino_custom_command');
    const sendButton=document.getElementById('arduino_command_send_btn');
    if(input)input.disabled=!canSend;
    if(sendButton)sendButton.disabled=!canSend;
    const feedback=document.getElementById('arduino_command_feedback');
    if(feedback&&!pending){
        if(withoutArduino) feedback.textContent='Unavailable: --without-arduino is active. Restart without that flag to send serial commands.';
        else if(!STREAM_CONTROL_ALLOWED) feedback.textContent='Unavailable: this dashboard is read-only; custom commands are disabled.';
        else if(!connected) feedback.textContent='Arduino is disconnected. Waiting for the serial reconnect worker; no command has been sent.';
        else if(feedback.textContent.startsWith('Unavailable:')||feedback.textContent.startsWith('Arduino is disconnected.')) {
            feedback.textContent='Ready. Arduino is connected. Stop the robot or lift the wheels before testing motion commands.';
        }
    }
    const output=document.getElementById('arduino_output');
    const lines=Array.isArray(j.lines)?j.lines:[];
    if(output){
        output.textContent = (j.lines || []).join('\\n');
        output.scrollTop=output.scrollHeight;
        const placeholder=output.parentElement&&output.parentElement.querySelector('.console-empty');
        if(placeholder){
            placeholder.hidden=lines.length>0;
            if(withoutArduino)placeholder.textContent='Serial output is unavailable because this run uses --without-arduino.';
            else if(!connected)placeholder.textContent='No serial output: Arduino is disconnected. Waiting for reconnect.';
            else placeholder.textContent='Connected; waiting for Arduino serial telemetry…';
        }
    }
    return {withoutArduino,connected,state:String(j.state||'UNKNOWN')};
}
function updateArduinoOutput(){
    if(!syncActive)return;
    fetchDashboardJson('/api/arduino-output')
        .then(j=>{
            if(!j)return;
            const button=document.getElementById('arduino_auto_commands_enabled');
            const policyStatus=document.getElementById('arduino_command_policy_status');
            const policyKnown=typeof j.automatic_commands_enabled==='boolean';
            const pending=!!(button&&button.dataset.pending==='true');
            if(button&&policyKnown&&!pending)syncAutomaticCommandButton(button,j.automatic_commands_enabled);
            if(policyStatus&&policyKnown&&!pending){
                policyStatus.textContent=j.without_arduino===true
                    ?'Saved preference: '+(j.automatic_commands_enabled?'ON':'OFF')+'. This run cannot send to Arduino because --without-arduino is active.'
                    :j.automatic_commands_enabled
                        ?'Automatic Python control/configuration commands are enabled.'
                        :'Automatic Python control/configuration commands are suppressed. Manual commands remain available when connected.';
            }
            const hardware=updateArduinoHardwareUi(j);
            const stateText=hardware.withoutArduino?'DISABLED (--without-arduino)':'State: '+hardware.state+' | Connected: '+(hardware.connected?'yes':'no');
            if(lastLoggedArduinoState!==stateText){
                noteWorkspaceEvent(hardware.connected?'info':'warn','Arduino telemetry: '+stateText);
                lastLoggedArduinoState=stateText;
            }
        }).catch(()=>{});
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
        syncStreamPermissionUI();
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
document.querySelectorAll('.left-toolbar .tool-button[title]').forEach(function(button){
  if(button.querySelector('.tool-tip')){
    if(!button.hasAttribute('aria-label'))button.setAttribute('aria-label',button.title);
    button.removeAttribute('title');
  }
});
const narrow=()=>window.matchMedia('(max-width:720px)').matches;
let dockIsOpen=!narrow();
const dockVisible=()=>dockIsOpen;
function setDock(open){
  dockIsOpen=Boolean(open);
  const isNarrow=narrow();
  workspace.classList.toggle('show-dock',isNarrow&&dockIsOpen);
  workspace.classList.toggle('dock-hidden',!isNarrow&&!dockIsOpen);
  const dockText=isNarrow?(dockIsOpen?'Close Menu':'Menu'):(dockIsOpen?'Hide Panels':'Show Panels');
  const dockLabel=dockToggle.querySelector('#toggle_dock_label');if(dockLabel)dockLabel.textContent=dockText;else dockToggle.textContent=dockText;
  dockToggle.setAttribute('aria-expanded',String(dockIsOpen));
  dockToggle.setAttribute('aria-label',isNarrow?(dockIsOpen?'Close left settings menu':'Open left settings menu'):(dockIsOpen?'Hide settings panels':'Show settings panels'));
  const drawerBackdrop=document.getElementById('settings_drawer_backdrop');if(drawerBackdrop)drawerBackdrop.hidden=!(isNarrow&&dockIsOpen);
  const menuDockToggle=document.querySelector('[data-action="toggle-properties"]');
  if(menuDockToggle)menuDockToggle.textContent=dockIsOpen?'Hide Panels':'Show Panels';
  window.requestAnimationFrame(()=>{syncCameraCanvasSize();renderWorkspaceCanvas();if(typeof window.drawPrecisionOverlay==='function')window.drawPrecisionOverlay();});
}
window.ensureStreamDockVisible=()=>setDock(true);
dockToggle.addEventListener('click',()=>{
  const open=!dockIsOpen;
  setDock(open);
  noteWorkspaceEvent('info',(narrow()?'Left settings menu ':'Settings dock ')+(open?'shown':'hidden'));
});
const drawerBackdrop=document.getElementById('settings_drawer_backdrop');
if(drawerBackdrop)drawerBackdrop.addEventListener('click',()=>{setDock(false);noteWorkspaceEvent('info','Left settings menu closed');});
const shortcutDialog=document.getElementById('shortcut_dialog'),shortcutClose=document.getElementById('shortcut_close'),shortcutDone=document.getElementById('shortcut_done');
if(shortcutClose)shortcutClose.addEventListener('click',closeStreamShortcuts);
if(shortcutDone)shortcutDone.addEventListener('click',closeStreamShortcuts);
if(shortcutDialog)shortcutDialog.addEventListener('click',e=>{if(e.target===shortcutDialog)closeStreamShortcuts();});
window.addEventListener('resize',()=>setDock(dockIsOpen));
setDock(dockIsOpen);
let pythonLogPollTimer=null,pythonLogRequestInFlight=false,pythonLogsClearedAfter=0;
async function refreshPythonLogs(){
  if(consoleTab!=='python'||!consoleDock.classList.contains('console-open')||!syncActive||workspaceConsolePaused||pythonLogRequestInFlight)return;
  pythonLogRequestInFlight=true;
  try{
    const response=await fetch('/api/logs?limit=200',{cache:'no-store'});
    if(!response.ok)throw new Error('HTTP '+response.status);
    const payload=await response.json();
    const items=Array.isArray(payload.items)?payload.items:[];
    workspacePythonLogs=items.slice().reverse()
      .filter(entry=>Number(entry.timestamp||0)>=pythonLogsClearedAfter)
      .map(entry=>({
        time:new Date(Number(entry.timestamp||0)*1000),
        level:(String(entry.level||'INFO').toUpperCase()==='WARNING'?'WARN':String(entry.level||'INFO').toUpperCase()==='CRITICAL'?'ERROR':String(entry.level||'INFO').toUpperCase()),
        message:String(entry.logger||'python')+' · '+String(entry.message||'')
      }));
    renderWorkspaceEventLog('python');
  }catch(error){
    const root=document.getElementById('console_python');
    if(root){root.replaceChildren();const empty=document.createElement('div');empty.className='console-empty';empty.textContent='Unable to load Python logs: '+String(error&&error.message||error);root.appendChild(empty);}
  }finally{pythonLogRequestInFlight=false;}
}
function updatePythonLogPolling(){
  const shouldPoll=consoleTab==='python'&&consoleDock.classList.contains('console-open')&&syncActive&&!workspaceConsolePaused;
  if(shouldPoll&&!pythonLogPollTimer){refreshPythonLogs();pythonLogPollTimer=setInterval(refreshPythonLogs,2000);}
  else if(!shouldPoll&&pythonLogPollTimer){clearInterval(pythonLogPollTimer);pythonLogPollTimer=null;}
}
function setConsoleOpen(open){
  const visible=!!open;
  consoleDock.classList.toggle('console-open',visible);
  consoleToggle.setAttribute('aria-expanded',String(visible));
  const toolButton=document.querySelector('.left-toolbar [data-action="toggle-console"]');
  if(toolButton){
    toolButton.setAttribute('aria-pressed',String(visible));
    toolButton.setAttribute('aria-label',visible?'Close Event Console':'Open Event Console');
  }
  updatePythonLogPolling();
}
consoleToggle.addEventListener('click',()=>setConsoleOpen(!consoleDock.classList.contains('console-open')));
setConsoleOpen(consoleDock.classList.contains('console-open'));
consoleClear.addEventListener('click',()=>{
  if(consoleTab==='arduino'){
    const output=document.getElementById('arduino_output');
    if(output)output.textContent='';
    noteWorkspaceEvent('info','Arduino serial output view cleared; the next poll may show buffered firmware output again');
    return;
  }
  if(consoleTab==='arduino-commands'){
    const feedback=document.getElementById('arduino_command_feedback');
    if(feedback)feedback.textContent='Command feedback cleared.';
    noteWorkspaceEvent('info','Arduino command feedback cleared');
    return;
  }
  if(consoleTab==='api')workspaceApiEvents=[];
  else if(consoleTab==='python'){workspacePythonLogs=[];pythonLogsClearedAfter=Date.now()/1000+0.01;}
  else workspaceEvents=[];
  renderWorkspaceEventLog(consoleTab);
  if(consoleTab==='python')noteWorkspaceEvent('info','Python log view cleared; server log history is unchanged');
  else noteWorkspaceEvent('info','Event log cleared',consoleTab);
});
document.querySelectorAll('[data-console-tab]').forEach(b=>b.addEventListener('click',()=>{
  consoleTab=b.dataset.consoleTab;
  document.querySelectorAll('[data-console-tab]').forEach(t=>t.setAttribute('aria-selected',String(t===b)));
  document.getElementById('console_events').hidden=consoleTab!=='events';
  document.getElementById('console_api').hidden=consoleTab!=='api';
  document.getElementById('console_python').hidden=consoleTab!=='python';
  const arduinoPane=document.getElementById('console_arduino');
  if(arduinoPane)arduinoPane.hidden=consoleTab!=='arduino';
  const arduinoCommandPane=document.getElementById('console_arduino_commands');
  if(arduinoCommandPane)arduinoCommandPane.hidden=consoleTab!=='arduino-commands';
  if(!consoleDock.classList.contains('console-open'))setConsoleOpen(true);
  if(consoleTab!=='arduino'&&consoleTab!=='arduino-commands')renderWorkspaceEventLog(consoleTab);
  if(consoleTab==='arduino-commands'){
    updateArduinoOutput();
    const commandInput=document.getElementById('arduino_custom_command');
    if(commandInput)commandInput.focus();
  }
  updatePythonLogPolling();
}));
document.querySelectorAll('.menu-group').forEach(m=>m.addEventListener('toggle',()=>{if(m.open)document.querySelectorAll('.menu-group').forEach(o=>{if(o!==m)o.open=false;});}));document.addEventListener('click',e=>{if(!e.target.closest('.menu-group'))document.querySelectorAll('.menu-group').forEach(m=>m.open=false);});
const consolePause=document.getElementById('console_pause');if(consolePause)consolePause.addEventListener('change',()=>{workspaceConsolePaused=consolePause.checked;updatePythonLogPolling();if(!workspaceConsolePaused&&consoleTab!=='arduino')renderWorkspaceEventLog(consoleTab);});
function setTool(tool){if(tool==='pan'&&workspaceViewLocked){showToast('View is locked. Unlock it to pan.');tool='select';}workspaceTool=tool==='pan'?'pan':'select';document.querySelectorAll('[data-tool]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.tool===workspaceTool)));canvas.style.cursor=workspaceTool==='pan'?'grab':'default';noteWorkspaceEvent('info',workspaceTool==='pan'?'Hand / Pan tool selected':'Select / Edit ROI tool selected');if(typeof window.onStreamWorkspaceToolChanged==='function')window.onStreamWorkspaceToolChanged(workspaceTool);}
window.setStreamWorkspaceTool=setTool;
function zoomBy(f){setWorkspaceZoom(workspaceZoom*f,canvas.width/2,canvas.height/2);}
function toggleOverlays(){showRectsCheckbox.checked=!showRectsCheckbox.checked;syncOverlayControlUI();renderWorkspaceCanvas();noteWorkspaceEvent('info','Overlays '+(showRectsCheckbox.checked?'shown':'hidden'));}
function toggleProperties(){const p=document.querySelector('.properties-panel');if(!dockVisible()){setDock(true);if(p)p.open=true;noteWorkspaceEvent('info','Properties panel shown');return;}if(p){p.open=!p.open;noteWorkspaceEvent('info','Properties panel '+(p.open?'opened':'closed'));}}
document.querySelectorAll('[data-tool]').forEach(b=>b.addEventListener('click',()=>setTool(b.dataset.tool)));
document.querySelectorAll('[data-action]').forEach(b=>b.addEventListener('click',()=>{switch(b.dataset.action){
case 'export-config':if(window.exportFullConfig)window.exportFullConfig().catch(err=>showToast('Export failed: '+err.message));else showToast('Full configuration export is unavailable.');break;case 'import-config':{const input=document.getElementById('ext_config_file');if(input)input.click();else showToast('Full configuration import is unavailable.');break;}case 'refresh-config':if(window.reloadFullConfig)window.reloadFullConfig().catch(err=>showToast('Reload failed: '+err.message));else document.getElementById('refresh_vals').click();noteWorkspaceEvent('info','Full configuration refresh requested');break;
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
    document.querySelectorAll('.menu-group').forEach(m=>m.open=false);
    if(narrow()&&dockIsOpen){setDock(false);return;}
    return;
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
  document.getElementById('prop_hint').textContent='Select an ROI or BEV control point to inspect or edit.';document.getElementById('cad_selected_area').textContent='Object: None';return;
 }
 if(st.kind==='roi'){
  selectedVar=st.group;select.value=st.group;const n=names(st.group);
  document.getElementById('properties_mode').textContent=({RL:'Right Lane ROI',LL:'Left Lane ROI',CW:'Crosswalk ROI',ST:'Sign / Tag ROI',OBJ:'Object ROI',ML:'Maneuver Left ROI',MR:'Maneuver Right ROI'})[st.group]+' · bounds';
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
else if(s.kind==='point'){const c=s.corner,x=Number(document.getElementById('prop_point_x').value),y=Number(document.getElementById('prop_point_y').value);if(!Number.isFinite(x)||!Number.isFinite(y))return showToast('Enter valid BEV point coordinates');advanced['BEV_SRC_'+c+'_X']=Math.max(-5,Math.min(5,round01(x)));advanced['BEV_SRC_'+c+'_Y']=Math.max(-5,Math.min(5,round01(y)));updateShapeUIFromData();renderWorkspaceCanvas();sendAdvanced({['BEV_SRC_'+c+'_X']:advanced['BEV_SRC_'+c+'_X'],['BEV_SRC_'+c+'_Y']:advanced['BEV_SRC_'+c+'_Y']}).then(function(saved){if(saved){syncPropertiesSelection('BEV_'+c);noteWorkspaceEvent('info','BEV '+c+' point properties applied');}});}else{return showToast('Select an ROI or BEV point first.');}});
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
 markerHighlight=source;selectedVar=source;select.value=source;propTarget.value=source;updateInputsFromValues();renderWorkspaceCanvas();syncPropertiesSelection(source);
 sendUpdate({[dst.top]:values[dst.top],[dst.bottom]:values[dst.bottom],[dst.left]:values[dst.left],[dst.right]:values[dst.right]});
 if(Object.keys(factorPayload).length)sendAdvanced(factorPayload);
 noteWorkspaceEvent('info','Mirrored '+source+' ROI to '+destination+' around normalized image center, including lane shape when available.');
 showToast('Mirrored '+(source==='LL'?'Left':'Right')+' ROI to '+(destination==='RL'?'Right':'Left')+'.');
}
document.getElementById('mirror_selected_to_opposite').addEventListener('click',()=>{const st=info();if(st.kind!=='roi'||!['RL','LL'].includes(st.group))return showToast('Select RL or LL before mirroring.');mirrorLaneRoi(st.group,st.group==='RL'?'LL':'RL');});
let keyboardRoiSaveTimer=null,keyboardRoiPendingGroup=null;
function flushKeyboardRoiMove(){if(keyboardRoiSaveTimer){clearTimeout(keyboardRoiSaveTimer);keyboardRoiSaveTimer=null;}const g=keyboardRoiPendingGroup;keyboardRoiPendingGroup=null;if(!g||!['RL','LL','CW','ST','OBJ','ML','MR'].includes(g))return;const n=names(g);sendUpdate({[n.top]:values[n.top],[n.bottom]:values[n.bottom],[n.left]:values[n.left],[n.right]:values[n.right]});}
function scheduleKeyboardRoiMove(g){keyboardRoiPendingGroup=g;if(keyboardRoiSaveTimer)clearTimeout(keyboardRoiSaveTimer);keyboardRoiSaveTimer=setTimeout(flushKeyboardRoiMove,220);}
document.addEventListener('keydown',function(e){
 const dirs={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]};const d=dirs[e.code]||dirs[e.key];if(!d)return;
 const target=e.target,tag=target&&target.tagName?target.tagName.toLowerCase():'';
 if(['input','textarea','select','button'].includes(tag)||target?.isContentEditable||document.getElementById('roi_settings_dialog').classList.contains('is-open'))return;
 if(workspaceTool!=='select'||!STREAM_CONTROL_ALLOWED||!syncActive)return;const g=markerHighlight;if(!['RL','LL','CW','ST','OBJ','ML','MR'].includes(g))return;
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
function clearCadReadout(){
  readout.x.textContent='X: — px';
  readout.y.textContent='Y: — px';
  readout.u.textContent='U: — %';
  readout.v.textContent='V: — %';
}
function updateCadReadout(e){
  const r=canvas.getBoundingClientRect();
  if(!r.width||!r.height){clearCadReadout();return;}
  const p=canvasPointFromEvent(e),b=getImgBounds(),source=getSourceFrameSize();
  if(!Number.isFinite(p.x)||!Number.isFinite(p.y)||!Number.isFinite(b.iw)||!Number.isFinite(b.ih)||b.iw<=0||b.ih<=0){clearCadReadout();return;}
  // Keep the frame origin at (0,0); letterbox/pan space produces extrapolated coordinates.
  const u=(p.x-b.ix)/b.iw,v=(p.y-b.iy)/b.ih,outside=u<0||u>1||v<0||v>1;
  readout.x.textContent='X: '+Math.round(u*source.width)+' px';
  readout.y.textContent='Y: '+Math.round(v*source.height)+' px';
  readout.u.textContent='U: '+(u*100).toFixed(1)+' %';
  readout.v.textContent='V: '+(v*100).toFixed(1)+' %';
  const description=outside?'Extrapolated from image origin (0,0); pointer is outside the displayed frame.':'Image-relative coordinates.';
  readout.x.title=description;readout.y.title=description;readout.u.title=description;readout.v.title=description;
}
canvas.addEventListener('mousemove',updateCadReadout,{passive:true});
canvas.addEventListener('mouseleave',clearCadReadout,{passive:true});
window.addEventListener('blur',clearCadReadout,{passive:true});
select.addEventListener('change',()=>{flushKeyboardRoiMove();const t=select.value;if(t==='NONE'){markerHighlight=null;selectedVar='NONE';document.getElementById('prop_target').value='NONE';window.syncPropertiesSelection('NONE');}else if(t.startsWith('BEV_')){markerHighlight='BEV';selectedVar=t;document.getElementById('prop_target').value=t;window.syncPropertiesSelection(t);}else if(['RL','LL','CW','ST','OBJ','ML','MR'].includes(t)){markerHighlight=t;selectedVar=t;document.getElementById('prop_target').value=t;window.syncPropertiesSelection(t);}readout.area.textContent='Object: '+(t==='NONE'?'NONE':t.startsWith('BEV_')?'BEV '+t.slice(4):t);renderWorkspaceCanvas();});
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
    if(['RL','LL','CW','ST','OBJ','ML','MR'].includes(g)) return g+'_TOP_ROI';
    return 'RL_TOP_ROI'; 
}


// Manual commands bypass the automatic Python-command gate, but still require a live Arduino.
(function bindArduinoCommandConsole(){
  const policyToggle=document.getElementById('arduino_auto_commands_enabled');
  const policyStatus=document.getElementById('arduino_command_policy_status');
  const form=document.getElementById('arduino_command_form');
  const input=document.getElementById('arduino_custom_command');
  const sendButton=document.getElementById('arduino_command_send_btn');
  const feedback=document.getElementById('arduino_command_feedback');

  if(policyToggle){
    const initial=window.STREAM_BOOTSTRAP&&window.STREAM_BOOTSTRAP.advanced
      ?window.STREAM_BOOTSTRAP.advanced.SEND_AUTOMATIC_ARDUINO_COMMANDS:undefined;
    syncAutomaticCommandButton(policyToggle,typeof initial==='boolean'?initial:policyToggle.getAttribute('aria-pressed')==='true');
    policyToggle.disabled=!STREAM_CONTROL_ALLOWED;
    policyToggle.addEventListener('click',async()=>{
      if(!STREAM_CONTROL_ALLOWED)return;
      const previous=policyToggle.getAttribute('aria-pressed')==='true';
      const requested=!previous;
      policyToggle.disabled=true;
      policyToggle.dataset.pending='true';
      syncAutomaticCommandButton(policyToggle,requested);
      if(policyStatus)policyStatus.textContent='Saving automatic-command policy…';
      try{
        const response=await fetch('/set_advanced',{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({SEND_AUTOMATIC_ARDUINO_COMMANDS:requested})
        });
        const result=await response.json().catch(()=>({}));
        if(!response.ok||!result.success)throw new Error(result.message||('HTTP '+response.status));
        const saved=!!result.advanced.SEND_AUTOMATIC_ARDUINO_COMMANDS;
        syncAutomaticCommandButton(policyToggle,saved);
        const withoutArduino=!!(result.advanced&&result.advanced.WITHOUT_ARDUINO);
        if(policyStatus)policyStatus.textContent=withoutArduino
          ?'Preference saved: '+(saved?'ON':'OFF')+'. This run uses --without-arduino, so hardware commands remain unavailable.'
          :saved?'Automatic Python control/configuration commands are enabled.':'Automatic Python control/configuration commands are suppressed. Manual commands remain available when connected.';
        noteWorkspaceEvent('info',saved?'Automatic Python Arduino commands enabled':'Automatic Python Arduino commands suppressed');
      }catch(error){
        syncAutomaticCommandButton(policyToggle,previous);
        if(policyStatus)policyStatus.textContent='Could not save policy: '+(error.message||error);
        showToast('Could not save Arduino command policy');
      }finally{
        delete policyToggle.dataset.pending;
        policyToggle.disabled=!STREAM_CONTROL_ALLOWED;
      }
    });
  }

  if(form&&input&&sendButton){
    // Local command history behaves like an interactive serial console: Up/Down recall only;
    // pressing Enter/Send is still the only action that transmits a command.
    const commandHistoryKey='self-driving-robot:arduino-command-history:'+String((window.STREAM_BOOTSTRAP&&window.STREAM_BOOTSTRAP.mode)||'default').toLowerCase();
    let commandHistoryStorage=null;try{commandHistoryStorage=window.localStorage;}catch(_){}
    const commandHistory=window.StreamState.createCommandHistory({storage:commandHistoryStorage,key:commandHistoryKey,limit:100});
    const commandHistoryList=document.getElementById('arduino_command_history_list');
    const commandHistoryCount=document.getElementById('arduino_command_history_count');
    const commandHistoryClear=document.getElementById('arduino_command_history_clear');
    const commandFavoriteKey='self-driving-robot:arduino-command-favorites:'+String((window.STREAM_BOOTSTRAP&&window.STREAM_BOOTSTRAP.mode)||'default').toLowerCase();
    const commandFavorites=window.StreamState.createCommandFavorites({storage:commandHistoryStorage,key:commandFavoriteKey,limit:25});
    const commandFavoriteList=document.getElementById('arduino_command_favorites_list');
    const commandFavoriteCount=document.getElementById('arduino_command_favorite_count');
    const commandFavoriteAdd=document.getElementById('arduino_command_favorite_add');
    function syncCommandFavoriteAdd(){if(commandFavoriteAdd)commandFavoriteAdd.disabled=!input.value.trim();}
    function renderArduinoCommandFavorites(){
      const items=commandFavorites.snapshot();
      if(commandFavoriteCount)commandFavoriteCount.textContent=String(items.length);
      if(!commandFavoriteList)return;
      commandFavoriteList.replaceChildren();
      if(!items.length){const empty=document.createElement('li');empty.className='arduino-history-empty';empty.textContent='No favorite commands saved yet.';commandFavoriteList.appendChild(empty);return;}
      items.slice().reverse().forEach(function(item){
        const row=document.createElement('li'),load=document.createElement('button'),remove=document.createElement('button');
        load.type='button';load.className='arduino-favorite-load';load.setAttribute('aria-label','Load favorite '+item.label);
        const label=document.createElement('span');label.className='arduino-favorite-label';label.textContent=item.label;
        const command=document.createElement('span');command.className='arduino-favorite-command';command.textContent=item.command;
        load.appendChild(label);load.appendChild(command);
        load.addEventListener('click',function(){
          input.value=item.command;commandHistory.edit(item.command);syncCommandFavoriteAdd();
          try{input.setSelectionRange(item.command.length,item.command.length);}catch(_){}
          input.focus();if(feedback)feedback.textContent='Loaded favorite "'+item.label+'"; press Enter or Send to transmit.';
        });
        remove.type='button';remove.className='ghost arduino-favorite-delete';remove.textContent='×';
        remove.title='Remove favorite '+item.label;remove.setAttribute('aria-label','Remove favorite '+item.label);
        remove.addEventListener('click',function(){commandFavorites.remove(item.label);renderArduinoCommandFavorites();});
        row.appendChild(load);row.appendChild(remove);commandFavoriteList.appendChild(row);
      });
    }
    if(commandFavoriteAdd)commandFavoriteAdd.addEventListener('click',function(){
      const command=input.value.trim();
      if(!command){if(feedback)feedback.textContent='Enter a command before saving a favorite.';return;}
      const label=window.prompt('Name this favorite (1–48 characters):','');
      if(label===null)return;
      const item=commandFavorites.add(label,command);
      if(!item){if(feedback)feedback.textContent='Favorite not saved: enter a name and one ASCII command line without control characters.';return;}
      renderArduinoCommandFavorites();
      if(feedback)feedback.textContent='Favorite saved: '+item.label+'. Loading it will not send it.';
    });
    function renderArduinoCommandHistory(){
      const items=commandHistory.snapshot();
      if(commandHistoryCount)commandHistoryCount.textContent=String(items.length);
      if(commandHistoryClear)commandHistoryClear.disabled=items.length===0;
      if(!commandHistoryList)return;
      commandHistoryList.replaceChildren();
      if(!items.length){
        const empty=document.createElement('li');empty.className='arduino-history-empty';empty.textContent='No commands sent in this browser for this mode yet.';commandHistoryList.appendChild(empty);return;
      }
      items.slice().reverse().forEach(function(value){
        const row=document.createElement('li'),button=document.createElement('button');
        button.type='button';button.className='arduino-history-entry';button.textContent=value;
        button.title='Fill the command field only; does not send this command.';
        button.addEventListener('click',function(){
          input.value=value;commandHistory.edit(value);syncCommandFavoriteAdd();
          try{input.setSelectionRange(value.length,value.length);}catch(_){}
          input.focus();
          if(feedback)feedback.textContent='Loaded from history; press Enter or Send to transmit.';
        });
        row.appendChild(button);commandHistoryList.appendChild(row);
      });
    }
    if(commandHistoryClear)commandHistoryClear.addEventListener('click',function(){
      commandHistory.clear();commandHistory.resetAfterSend();renderArduinoCommandHistory();
      if(feedback)feedback.textContent='Saved command history cleared for this mode.';
    });
    renderArduinoCommandHistory();
    function recallArduinoCommand(direction){
      const result=commandHistory.move(direction,input.value);if(!result.handled)return false;
      input.value=result.value;const end=input.value.length;try{input.setSelectionRange(end,end);}catch(_){}
      return true;
    }
    input.addEventListener('keydown',function(event){
      if(event.isComposing||event.altKey||event.ctrlKey||event.metaKey)return;
      if(event.key==='ArrowUp'){if(recallArduinoCommand(-1)){event.preventDefault();event.stopPropagation();}}
      else if(event.key==='ArrowDown'){if(recallArduinoCommand(1)){event.preventDefault();event.stopPropagation();}}
    });
    input.addEventListener('input',function(){commandHistory.edit(input.value);syncCommandFavoriteAdd();});
    renderArduinoCommandFavorites();
    syncCommandFavoriteAdd();
    form.addEventListener('submit',async(event)=>{
      event.preventDefault();
      const command=input.value.trim();
      if(!command){if(feedback)feedback.textContent='Enter a command before sending.';input.focus();return;}
      if(input.disabled||sendButton.disabled){
        if(feedback)feedback.textContent='Command not sent: Arduino is unavailable for this run or this dashboard is read-only.';
        return;
      }
      form.dataset.sending='true';
      sendButton.disabled=true;
      if(feedback)feedback.textContent='Sending custom command…';
      try{
        const ackToggle=document.getElementById('arduino_command_wait_ack');
        const waitForAck=!!(ackToggle&&ackToggle.checked);
        const response=await fetch('/api/arduino-command',{
          method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command,wait_for_ack:waitForAck})
        });
        const result=await response.json().catch(()=>({}));
        if(!response.ok||!result.success)throw new Error(result.message||('HTTP '+response.status));
        if(result.delivery_status==='acknowledged_not_executed'){
          if(feedback)feedback.textContent='Arduino ACK #'+result.command_id+': command reached the firmware command loop; physical execution is NOT confirmed.';
          noteWorkspaceEvent('info','Arduino acknowledged command receipt #'+result.command_id+'; execution remains unconfirmed.','arduino-commands');
        }else if(result.delivery_status==='ack_timeout'){
          if(feedback)feedback.textContent='No Arduino ACK for command #'+result.command_id+'. The command may have been received; do not blindly retry a motion command.';
          noteWorkspaceEvent('warn','ACK timeout for Arduino command #'+result.command_id+'; outcome is unknown.','arduino-commands');
        }else if(result.delivery_status==='transmitted_unconfirmed'){
          if(feedback)feedback.textContent='Transmitted: '+result.command+' — serial write succeeded; Arduino acknowledgement and execution are not confirmed.';
          noteWorkspaceEvent('info','Custom Arduino command transmitted without firmware ACK: '+result.command,'arduino-commands');
        }else if(feedback)feedback.textContent='Sent: '+result.command;
        commandHistory.remember(result.command||command);
        commandHistory.resetAfterSend();
        renderArduinoCommandHistory();
        input.value='';
      }catch(error){
        if(feedback)feedback.textContent='Command failed: '+(error.message||error);
        noteWorkspaceEvent('error','Custom Arduino command failed: '+(error.message||error),'arduino-commands');
      }finally{
        delete form.dataset.sending;
        updateArduinoOutput();
        input.focus();
      }
    });
  }
})();

