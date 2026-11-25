function refreshRuntime(snapshot){
  const health = snapshot && snapshot.payload ? snapshot.payload
    : snapshot || (window.__streamLatestHealth && window.__streamLatestHealth.payload);
  if(!health)return;
  try{
    const h=health.health||{},m=health.metrics||{},timing=m.timing||{},camera=timing.camera||{},perception=timing.perception||{},loop=timing.loop||{},rate=health.processing_rate||{};
    const fps=Number(rate.achieved_fps)||Number(m.avg_fps)||0;extRuntimeSample.push({fps:fps,loop:Number(loop.mean_ms)||0,perception:Number(perception.mean_ms)||0});extRuntimeSample=extRuntimeSample.slice(-60);
    drawSparkline('ext_fps_chart',extRuntimeSample.map(function(v){return v.fps;}));drawSparkline('ext_latency_chart',extRuntimeSample.map(function(v){return v.loop;}));drawSparkline('ext_perception_chart',extRuntimeSample.map(function(v){return v.perception;}));
    const faults=h.faults||{};const faultNames=Object.keys(faults);$('ext_health_summary').textContent='State: '+(h.state||h.lifecycle||'UNKNOWN')+' · FPS: '+fps.toFixed(1)+' · Faults: '+faultNames.length;
    $('ext_runtime_details').textContent=JSON.stringify({health:h,metrics:m,processing_rate:rate,control:health.control,camera:health.camera,stream:health.stream},null,2);
    $('ext_sign_status').textContent=JSON.stringify(health.sign_detector||((h.resources||{}).sign_detector)||{active:false},null,2);
    $('ext_confidence_status').textContent=JSON.stringify({perception_confidence:health.perception_confidence,speed_decision:health.speed_decision},null,2);
    $('ext_obstacle_status').textContent=JSON.stringify(health.obstacle_diagnostics||null,null,2);
  }catch(err){$('ext_health_summary').textContent='Runtime telemetry unavailable: '+err.message;}
}
window.addEventListener('stream:health',function(event){
  if(extensionPollingEnabled)refreshRuntime(event.detail);
});
function renderLiveFeatureControls(snapshot){
  const root=$('ext_live_feature_rows');if(!root)return;root.replaceChildren();
  const live=snapshot.live||{},canControl=!!snapshot.controls_enabled&&STREAM_CONTROL_ALLOWED;
  const checks=[
    ['DETECT_OBJECT','Object detection',live.DETECT_OBJECT],
    ['USE_BEV','Bird’s-eye transform',live.USE_BEV],
    ['RECORD_VIDEO','Video recording',live.RECORD_VIDEO]
  ];
  checks.forEach(function(item){
    const feature=item[0],meta=item[2]||{},row=document.createElement('div');row.className='ext-list-row';
    const left=document.createElement('div');left.style.display='grid';left.style.gap='2px';left.style.minWidth='0';
    const title=document.createElement('strong');title.textContent=item[1];left.appendChild(title);
    const note=document.createElement('span');note.className='small-muted';note.textContent=meta.description||'';left.appendChild(note);row.appendChild(left);
    const control=document.createElement('input');control.type='checkbox';control.checked=!!meta.enabled;control.disabled=!canControl||!meta.available;control.title=meta.available?'Live control':'Unsupported by active mode/lane pipeline';
    control.onchange=function(){applyLiveFeature(feature,control.checked).catch(function(err){showToast(err.message);refreshFeatureStatus();});};row.appendChild(control);root.appendChild(row);
  });
  const marker=live.marker_mode||{},row=document.createElement('div');row.className='ext-list-row';
  const label=document.createElement('label');label.textContent='Marker detector';label.style.flex='1';row.appendChild(label);
  const select=document.createElement('select');[['none','Off'],['sign','Traffic signs'],['apriltag','AprilTag']].forEach(function(pair){const opt=document.createElement('option');opt.value=pair[0];opt.textContent=pair[1];select.appendChild(opt);});
  select.value=marker.value||'none';select.disabled=!canControl||!marker.available;select.onchange=function(){applyLiveFeature('marker_mode',select.value).catch(function(err){showToast(err.message);refreshFeatureStatus();});};row.appendChild(select);root.appendChild(row);
  if(!canControl){const note=document.createElement('div');note.className='small-muted';note.textContent='Read-only mode: live feature changes are disabled.';root.appendChild(note);}
}
async function applyLiveFeature(feature,value){
  if(!STREAM_CONTROL_ALLOWED)throw new Error('Dashboard is read-only.');
  const descriptions={DETECT_OBJECT:'Change object detection for live frames?',USE_BEV:'Change the bird’s-eye transform live? Re-check lane overlays before moving.',RECORD_VIDEO:'Change video recording state?',marker_mode:'Change the active sign/AprilTag detector?'};
  if(!confirm((descriptions[feature]||'Apply this live feature change?')+' This update is saved to the active mode config.'))return;
  const before=currentConfig?jsonClone(currentConfig):await readConfig();
  const response=await nativeFetch('/api/features',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({feature:feature,value:value})});
  const data=await response.json().catch(function(){return {};});if(!response.ok)throw new Error(data.message||('HTTP '+response.status));
  const after=await readConfig();
  rememberUndo(before,after);
  currentConfig=after;showToast('Updated '+feature);noteWorkspaceEvent('info','Live feature changed: '+feature+'='+String(value));await refreshFeatureStatus();
}
async function refreshFeatureStatus(){
  try{
    const mode=await nativeFetch('/api/mode',{cache:'no-store'}).then(function(r){return r.json();});const f=mode.features||{},c=mode.capabilities||{};
    const features=await nativeFetch('/api/features',{cache:'no-store'}).then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.json();});
    renderLiveFeatureControls(features);
    const rows=[
      ['Traffic lights',features.restart_required&&features.restart_required.TRAFFIC_LIGHTS_ENABLED],
      ['Confidence-aware speed',features.restart_required&&features.restart_required.CONFIDENCE_AWARE_ENABLED],
      ['Adaptive obstacle avoidance',features.restart_required&&features.restart_required.ADAPTIVE_OBSTACLE_AVOIDANCE_ENABLED],
      ['Encoder map',features.restart_required&&features.restart_required.ENCODER_MAP_ENABLED]
    ];
    const newline=String.fromCharCode(10);
    $('ext_feature_status').textContent=rows.map(function(r){const meta=r[1]||{};return r[0]+': '+(meta.enabled?'enabled':'disabled')+' — '+(meta.reason||'startup configuration');}).join(newline)+newline+newline+'Lane detector: '+(f.lane_detector||'unknown')+newline+'ML lane detector: '+String(!!f.ml_lane_detector)+newline+'Mode capabilities:'+newline+JSON.stringify(c,null,2);
    if(f.encoder_map){$('ext_encoder_embed').hidden=false;$('ext_encoder_status').textContent='Encoder odometry is active.';if(!$('ext_encoder_frame').src||!$('ext_encoder_frame').src.endsWith('/encoder-map'))$('ext_encoder_frame').src='/encoder-map';}
    else{$('ext_encoder_embed').hidden=true;$('ext_encoder_status').textContent='Encoder map is disabled (enable with --encoder-map and compatible firmware, then restart).';}
    const setStatusSectionVisible=function(element,visible){if(!element)return;element.style.display=visible?'':'none';if(element.previousElementSibling)element.previousElementSibling.style.display=visible?'':'none';};
    setStatusSectionVisible($('ext_traffic_status'),mode.mode==='city');
    setStatusSectionVisible($('ext_race_status'),mode.mode==='race');
    window.extActiveMode=mode.mode;
  }catch(err){$('ext_feature_status').textContent='Feature query failed: '+err.message;}
}
async function refreshTrafficAndRace(){
  const mode=window.extActiveMode;
  if(mode==='city'){
    try{
      const light=await nativeFetch('/api/traffic-lights',{cache:'no-store'}).then(async function(r){const j=await r.json();if(!r.ok)throw new Error(j.reason||j.message||('HTTP '+r.status));return j;});
      $('ext_traffic_status').textContent=JSON.stringify(light,null,2);
    }catch(err){$('ext_traffic_status').textContent='Traffic-light status unavailable: '+err.message;}
    return;
  }
  if(mode==='race'){
    try{
      const race=await nativeFetch('/api/race',{cache:'no-store'}).then(async function(r){const j=await r.json();if(!r.ok)throw new Error(j.reason||j.message||('HTTP '+r.status));return j;});
      $('ext_race_status').textContent=JSON.stringify(race,null,2);
    }catch(err){$('ext_race_status').textContent='Race lifecycle unavailable: '+err.message;}
  }
}
async function refreshCameraSettings(){
  try{
    const data=await nativeFetch('/api/camera/settings',{cache:'no-store'}).then(function(r){return r.json();});const c=data.camera||{};
    cameraSupportedControlNames=c.control_names||[];cameraSettingsEditable=!!c.supported;
    $('ext_camera_support').textContent=c.supported?'Picamera2 controls detected. Available controls: '+cameraSupportedControlNames.join(', '):'Not editable: '+(c.reason||'camera controls unavailable');
    const ranges=c.control_ranges||{};
    [['ExposureTime','ext_exposure'],['AnalogueGain','ext_gain']].forEach(function(pair){
      const range=ranges[pair[0]]||{},input=$(pair[1]);
      if(range.min!=null&&Number.isFinite(Number(range.min)))input.min=String(range.min);
      else input.removeAttribute('min');
      if(range.max!=null&&Number.isFinite(Number(range.max)))input.max=String(range.max);
      else input.removeAttribute('max');
      const step=pair[0]==='ExposureTime'?'100':'0.1';input.step=step;
      input.title=(range.min!=null||range.max!=null)?'Sensor limits: '+(range.min==null?'unreported':range.min)+' to '+(range.max==null?'unreported':range.max):'The API validates against sensor-supported limits';
    });
    const controls=c.controls||{};
    if(controls.ExposureTime!=null&&!cameraControlIsDrafted('ext_exposure'))$('ext_exposure').value=String(controls.ExposureTime);
    if(controls.AnalogueGain!=null&&!cameraControlIsDrafted('ext_gain'))$('ext_gain').value=String(controls.AnalogueGain);
    if(!cameraControlIsDrafted('ext_auto_exposure'))$('ext_auto_exposure').checked=!!controls.AeEnable;
    if(!cameraControlIsDrafted('ext_auto_wb'))$('ext_auto_wb').checked=!!controls.AwbEnable;
    updateCameraControlsEnabled();
  }catch(err){$('ext_camera_support').textContent='Camera capability read failed: '+err.message;}
}
function updateCameraControlsEnabled(){
  const writable=!!cameraSettingsEditable&&STREAM_CONTROL_ALLOWED;
  $('ext_exposure').disabled=!writable||$('ext_auto_exposure').checked||!cameraSupportedControlNames.includes('ExposureTime');
  $('ext_gain').disabled=!writable||$('ext_auto_exposure').checked||!cameraSupportedControlNames.includes('AnalogueGain');
  $('ext_auto_exposure').disabled=!writable||!cameraSupportedControlNames.includes('AeEnable');
  $('ext_auto_wb').disabled=!writable||!cameraSupportedControlNames.includes('AwbEnable');
  $('ext_apply_camera').disabled=!writable||!cameraSupportedControlNames.some(function(key){return ['ExposureTime','AnalogueGain','AeEnable','AwbEnable'].includes(key);});
}
async function refreshProcessingRate(){
  try{
    const data=await nativeFetch('/api/processing-rate',{cache:'no-store'}).then(async function(r){const j=await r.json();if(!r.ok)throw new Error(j.message||('HTTP '+r.status));return j;});
    if(data.target_fps!=null&&!processingRateDraftDirty&&document.activeElement!==$('ext_target_fps'))$('ext_target_fps').value=String(data.target_fps);
    $('ext_fps_status').textContent=data.available?'Live · '+Number(data.target_fps).toFixed(1)+' FPS':'Unavailable';
    $('ext_target_fps').disabled=!data.available||!STREAM_CONTROL_ALLOWED;$('ext_apply_fps').disabled=!data.available||!STREAM_CONTROL_ALLOWED;
  }catch(err){$('ext_fps_status').textContent=err.message;}
}
async function refreshSafety(){
  try{
    const response=await nativeFetch('/api/safety',{cache:'no-store'});
    const data=await response.json();if(!response.ok)throw new Error(data.message||('HTTP '+response.status));
    const safetyText='Robot motion: RUN_LVL='+data.run_level+' · '+(data.software_stop_active?'STOPPED':'MOVE');
    if($('ext_safety_state').textContent!==safetyText)$('ext_safety_state').textContent=safetyText;
    $('ext_software_stop').disabled=!data.controls_enabled||data.software_stop_active;
    $('ext_software_resume').disabled=!data.controls_enabled||!data.software_stop_active;
    
  }catch(err){$('ext_safety_state').textContent='Robot motion status unavailable: '+err.message;}
}
async function refreshSignRequests(){
  try{
    const response=await nativeFetch('/api/sign-requests',{cache:'no-store'});
    const data=await response.json();if(!response.ok)throw new Error(data.message||('HTTP '+response.status));
    const state=$('ext_sign_requests_state');
    if(!data.available){
      state.textContent='Sign inference worker unavailable for this mode';
    }else{
      state.textContent='Request gate: '+(data.requests_enabled?'ENABLED':'PAUSED')
        +' · phase gate: '+(data.phase_paused?'PAUSED':'open')
        +' · worker '+(data.worker_alive?'alive':'offline')
        +' · queued '+data.queue_depth
        +(data.inference_in_flight?' · inference in flight':'')
        +' · RUN_LVL='+data.run_level+' (independent)';
    }
    $('ext_sign_requests_pause').disabled=!data.controls_enabled||!data.available||!data.requests_enabled;
    $('ext_sign_requests_resume').disabled=!data.controls_enabled||!data.available||data.requests_enabled;
  }catch(err){$('ext_sign_requests_state').textContent='Sign request status unavailable: '+err.message;}
}
async function signRequestsAction(action){
  if(!STREAM_CONTROL_ALLOWED)throw new Error('Dashboard is read-only.');
  const response=await nativeFetch('/api/sign-requests',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:action})});
  const data=await response.json().catch(function(){return {};});
  if(!response.ok)throw new Error(data.message||('HTTP '+response.status));
  const label=action==='pause'?'Sign detection requests paused':'Sign detection requests resumed';
  showToast(label+' · RUN_LVL unchanged ('+data.run_level+')');
  noteWorkspaceEvent(action==='pause'?'warn':'info',label+'; robot RUN_LVL unchanged: '+data.run_level);
  await refreshSignRequests();
}
async function refreshServerLogs(){
  const level=encodeURIComponent($('ext_log_level').value||'ALL'),q=encodeURIComponent($('ext_log_search').value||'');
  try{
    const data=await nativeFetch('/api/logs?limit=200&level='+level+'&q='+q,{cache:'no-store'}).then(async function(r){const j=await r.json();if(!r.ok)throw new Error(j.message||('HTTP '+r.status));return j;});
    serverLogsVisible=data.items||[];$('ext_server_logs').textContent=serverLogsVisible.map(function(item){return new Date(item.timestamp*1000).toLocaleTimeString()+' '+item.level.padEnd(8)+' '+item.logger+' — '+item.message;}).join(String.fromCharCode(10))||'No matching in-memory runtime logs.';
  }catch(err){$('ext_server_logs').textContent='Log API unavailable: '+err.message;}
}
async function safetyAction(action,options){
  const settings=options||{};
  if(!STREAM_CONTROL_ALLOWED)throw new Error('Dashboard is read-only.');
  if(action==='stop'&&!settings.skipConfirm&&!confirm('Request the active Python mode loop to stop robot motion? This is software control, not a hardware E-stop.'))return;
  if(action==='resume'&&!confirm('Resume motion? Confirm the track is clear and the robot is safe to move.'))return;
  const data=await nativeFetch('/api/safety',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:action})}).then(async function(r){const j=await r.json();if(!r.ok)throw new Error(j.message||('HTTP '+r.status));return j;});
  
  showToast(action==='stop'?'Force Stop requested · RUN_LVL=STOP':'Motion resume requested');noteWorkspaceEvent(action==='stop'?'warn':'info','Dashboard RUN_LVL '+(action==='stop'?'STOP':'MOVE')+' requested'+(settings.source==='keyboard'?' via Ctrl+Shift+Space':settings.source==='command-palette'?' via Command Palette':''));await Promise.all([refreshSafety(),refreshSignRequests()]);
}
async function toggleMotionSafetyFromKeyboard(){
  if(motionHotkeyActionInFlight)return;
  if(!STREAM_CONTROL_ALLOWED)throw new Error('Dashboard is read-only.');
  motionHotkeyActionInFlight=true;
  try{
    const response=await nativeFetch('/api/safety',{cache:'no-store'});
    const state=await response.json();
    if(!response.ok)throw new Error(state.message||('HTTP '+response.status));
    if(!state.controls_enabled)throw new Error('Dashboard is read-only.');
    const action=String(state.run_level||'MOVE').trim().toUpperCase()==='STOP'?'resume':'stop';
    await safetyAction(action,{skipConfirm:action==='stop',source:'keyboard'});
  }finally{motionHotkeyActionInFlight=false;}
}
function openStreamExitDialog(){
  const dialog=$('ext_stream_exit_dialog');
  const confirmButton=$('ext_stream_exit_confirm');
  const error=$('ext_stream_exit_error');
  if(streamShutdownRequestedLocally)return;
  $('ext_stream_exit_title').textContent='Exit Stream?';
  $('ext_stream_exit_message').textContent=STREAM_CONTROL_ALLOWED
    ? 'This stops the Stream HTTP server and sets STREAM=False in the current process, like running without --stream. The robot’s main City/Race loop, perception, and motion control keep running. This does not stop the robot.'
    : 'Stream shutdown is disabled because this dashboard is running in read-only mode. Restart without --stream-read-only to enable runtime controls.';
  error.hidden=true;error.textContent='';
  confirmButton.textContent='Stop Stream';
  confirmButton.disabled=!STREAM_CONTROL_ALLOWED;
  $('ext_stream_exit_cancel').hidden=false;
  $('ext_stream_exit_close').disabled=false;
  dialog.classList.add('is-open');dialog.setAttribute('aria-hidden','false');
  $('ext_stream_exit_cancel').focus();
}
window.openStreamExitDialog=openStreamExitDialog;
function closeStreamExitDialog(){
  if(streamShutdownRequestedLocally)return;
  const dialog=$('ext_stream_exit_dialog');
  dialog.classList.remove('is-open');dialog.setAttribute('aria-hidden','true');
}
async function requestStreamShutdown(){
  if(!STREAM_CONTROL_ALLOWED)throw new Error('Stream shutdown is disabled in read-only mode.');
  if(streamShutdownRequestedLocally)return;
  const confirmButton=$('ext_stream_exit_confirm');
  const cancelButton=$('ext_stream_exit_cancel');
  const closeButton=$('ext_stream_exit_close');
  const message=$('ext_stream_exit_message');
  const error=$('ext_stream_exit_error');
  confirmButton.disabled=true;cancelButton.disabled=true;closeButton.disabled=true;
  confirmButton.textContent='Stopping…';error.hidden=true;error.textContent='';
  try{
    const response=await nativeFetch('/api/stream-control/stop',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'stop'}),cache:'no-store'});
    const data=await response.json().catch(function(){return {};});
    if(!response.ok)throw new Error(data.message||('HTTP '+response.status));
    if(!data.success)throw new Error(data.message||'Stream shutdown was not accepted.');
    streamShutdownRequestedLocally=true;
    $('ext_stream_exit_title').textContent='Stream is shutting down';
    message.textContent=data.already_stopped
      ? 'The Stream HTTP server is already stopped. The robot runtime remains independent.'
      : 'Shutdown accepted. The Stream HTTP server is closing and STREAM is now false in this running process. City/Race, perception, and the robot motion loop continue running. This dashboard is leaving; restart with --stream to open it again.';
    confirmButton.textContent='Stream stopping…';
    cancelButton.hidden=true;
    $('menu_live_status').textContent='STREAM STOPPING';
    if(extHealthTimer){clearInterval(extHealthTimer);extHealthTimer=null;}
    noteWorkspaceEvent('warn','Stream shutdown requested from File → Exit; robot runtime remains active.');
    showToast('Stream shutdown requested; robot runtime remains active.');
    // Leave enough time for the confirmation to be read, then exit this
    // now-disconnected dashboard page and stop its browser-side polling loops.
    window.setTimeout(function(){window.location.replace('about:blank');},1500);
  }catch(err){
    confirmButton.disabled=false;cancelButton.disabled=false;closeButton.disabled=false;
    confirmButton.textContent='Stop Stream';
    error.textContent='Could not stop Stream: '+err.message;error.hidden=false;
    showToast('Stream shutdown failed: '+err.message);
    throw err;
  }
}
async function applyProcessingRate(){
  const before=currentConfig?jsonClone(currentConfig):await readConfig();
  const submittedVersion=processingRateDraftVersion;
  const fps=Number($('ext_target_fps').value);
  const data=await nativeFetch('/api/processing-rate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target_fps:fps})}).then(async function(r){const j=await r.json();if(!r.ok)throw new Error(j.message||('HTTP '+r.status));return j;});
  if(processingRateDraftVersion===submittedVersion){
    processingRateDraftDirty=false;
    $('ext_target_fps').value=String(data.target_fps);
  }
  $('ext_fps_status').textContent='Saved · '+Number(data.target_fps).toFixed(1)+' FPS'+(processingRateDraftDirty?' · newer edit not applied':'');
  currentConfig=await readConfig().catch(function(){return currentConfig;});rememberUndo(before,currentConfig);showToast('Processing-rate limit applied and saved');
}
async function refreshCameraCalibrations(){
  const status=$('ext_calibration_status'),select=$('ext_calibration_file');
  if(!status||!select)return;
  try{
    const response=await nativeFetch('/api/camera/calibrations',{cache:'no-store'});
    const data=await response.json().catch(function(){return {};});
    if(!response.ok)throw new Error(data.message||('HTTP '+response.status));
    select.replaceChildren();
    let validCount=0;
    (data.files||[]).forEach(function(file){
      const option=document.createElement('option');
      option.value=file.reference||'';
      option.textContent=(file.valid?'':'⚠ Invalid · ')+file.filename
        +(file.active?' · Active':'')
        +(file.quality_status?' · '+file.quality_status:'');
      option.title=file.valid?'':'Not selectable: '+(file.error||'invalid calibration');
      option.disabled=!file.valid;
      if(file.valid)validCount+=1;
      select.appendChild(option);
    });
    if(data.active_reference&&(data.files||[]).some(function(f){return f.valid&&f.reference===data.active_reference;})){
      select.value=data.active_reference;
    }else if(validCount){
      const first=(data.files||[]).find(function(f){return f.valid;});
      select.value=first.reference;
    }else{
      const option=document.createElement('option');option.value='';option.textContent='No valid calibration files';option.disabled=true;select.appendChild(option);
    }
    const enabled=$('ext_calibration_enabled');
    if(enabled)enabled.checked=!!data.enabled;
    const apply=$('ext_calibration_apply');
    if(apply)apply.disabled=!STREAM_CONTROL_ALLOWED||validCount===0;
    const upload=$('ext_calibration_upload');
    if(upload)upload.disabled=!STREAM_CONTROL_ALLOWED;
    status.textContent=String(data.mode||'mode').toUpperCase()
      +' · RUN_LVL='+String(data.run_level||'UNKNOWN')
      +' · '+(data.enabled?'undistortion ON':'undistortion OFF')
      +' · '+validCount+' valid calibration file(s)'
      +(data.active_calibration?' · Active: '+data.active_calibration.filename:' · Active file missing or invalid');
    status.title=data.active_reference||'No active calibration reference';
    return data;
  }catch(error){
    status.textContent='Calibration profiles unavailable: '+(error&&error.message?error.message:'request failed');
    const apply=$('ext_calibration_apply');if(apply)apply.disabled=true;
  }
}
async function uploadCameraCalibration(){
  if(!STREAM_CONTROL_ALLOWED)throw new Error('Dashboard is read-only.');
  const input=$('ext_calibration_upload_file');
  if(!input||!input.files||!input.files[0])throw new Error('Choose a .npz calibration file first.');
  const file=input.files[0];
  if(!/\.npz$/i.test(file.name))throw new Error('Only .npz calibration files are supported.');
  const status=$('ext_calibration_status');
  if(status)status.textContent='Uploading and validating '+file.name+'…';
  const body=new FormData();body.append('file',file,file.name);
  const response=await nativeFetch('/api/camera/calibrations',{method:'POST',body:body});
  const data=await response.json().catch(function(){return {};});
  if(!response.ok)throw new Error(data.message||('HTTP '+response.status));
  input.value='';
  await refreshCameraCalibrations();
  const select=$('ext_calibration_file');
  if(select&&data.reference)select.value=data.reference;
  if(status)status.textContent=data.message||'Calibration uploaded and validated. Apply to activate it.';
  showToast('Calibration uploaded and validated; it has not been activated yet.');
}
async function applyCameraCalibrationSelection(){
  if(!STREAM_CONTROL_ALLOWED)throw new Error('Dashboard is read-only.');
  const select=$('ext_calibration_file'),enabled=$('ext_calibration_enabled');
  const reference=select?select.value:'';
  if(!reference)throw new Error('Select a valid camera calibration profile first.');
  const response=await nativeFetch('/api/camera/calibrations',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({action:'select',reference:reference,enabled:!!(enabled&&enabled.checked)})
  });
  const data=await response.json().catch(function(){return {};});
  if(!response.ok)throw new Error(data.message||('HTTP '+response.status));
  const status=$('ext_calibration_status');
  if(status)status.textContent=data.message+' · '+(data.enabled?'enabled':'disabled')+' · '+data.reference;
  showToast(data.message||'Camera calibration selection saved.');
  await refreshCameraCalibrations();
}
async function saveFrameOverlaySettings(){
  if(!STREAM_CONTROL_ALLOWED)throw new Error('Dashboard is read-only.');
  const keys=['fps','realfps','status','applied_angle','vision_angle','servo_center','crosswalk','sign','last_tag','error','lane_type','speed','confidence','obstacle','servo_guide','candidate_labels'];
  const frame_overlay={};
  keys.forEach(function(key){
    const input=$('ext_overlay_'+key);
    frame_overlay[key]=!!(input&&input.checked);
  });
  const response=await nativeFetch('/set_ui',{
    method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({frame_overlay:frame_overlay})
  });
  const data=await response.json().catch(function(){return {};});
  if(!response.ok)throw new Error(data.message||('HTTP '+response.status));
  const status=$('ext_overlay_status');
  if(status)status.textContent='Saved · '+keys.filter(function(key){return frame_overlay[key];}).length+' telemetry field(s) selected.';
  showToast('Frame text overlay preferences saved for this mode.');
}
async function applyCameraControls(){
  const before=currentConfig?jsonClone(currentConfig):await readConfig();
  const payload={};
  if(cameraSupportedControlNames.includes('AeEnable')){
    payload.AeEnable=!!$('ext_auto_exposure').checked;
  }
  if(cameraSupportedControlNames.includes('AwbEnable')){
    payload.AwbEnable=!!$('ext_auto_wb').checked;
  }
  if(!$('ext_auto_exposure').checked){
    if(cameraSupportedControlNames.includes('ExposureTime'))payload.ExposureTime=Number($('ext_exposure').value);
    if(cameraSupportedControlNames.includes('AnalogueGain'))payload.AnalogueGain=Number($('ext_gain').value);
  }
  if(!Object.keys(payload).length)throw new Error('This camera does not expose any supported runtime controls.');
  const controlIds={ExposureTime:'ext_exposure',AnalogueGain:'ext_gain',AeEnable:'ext_auto_exposure',AwbEnable:'ext_auto_wb'};
  const submittedVersions=Object.create(null);
  Object.keys(controlIds).forEach(function(key){submittedVersions[controlIds[key]]=cameraDraftVersions[controlIds[key]]||0;});
  const response=await nativeFetch('/api/camera/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const data=await response.json().catch(function(){return {};});
  if(!response.ok)throw new Error(data.message||('HTTP '+response.status));
  Object.keys(payload).forEach(function(key){
    const id=controlIds[key];
    if(id&&(cameraDraftVersions[id]||0)===submittedVersions[id])cameraDraftDirty.delete(id);
  });
  await refreshCameraSettings();
  currentConfig=await readConfig().catch(function(){return currentConfig;});rememberUndo(before,currentConfig);showToast('Runtime camera controls applied');
}
