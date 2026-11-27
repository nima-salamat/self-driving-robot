function setConfigDialogOpen(id,open){
  const modal=$(id);if(!modal)return;
  modal.classList.toggle('is-open',!!open);
  modal.setAttribute('aria-hidden',open?'false':'true');
  if(open){
    modal.querySelectorAll('input,textarea,select').forEach(function(control){
      if(control.id==='pid_auto_update_kp'){control.disabled=true;return;}
      control.disabled=!STREAM_CONTROL_ALLOWED;
    });
    const apply=modal.querySelector('button[id$="_apply"]');if(apply)apply.disabled=!STREAM_CONTROL_ALLOWED;
  }
}

const CROSSWALK_CHAIN_LIMIT=16;
const CROSSWALK_CHAIN_ROUTES={
  left:{key:'CITY_CROSSWALK_TURN_LEFT_SEQUENCE',label:'LEFT'},
  straight:{key:'CITY_CROSSWALK_STRAIGHT_SEQUENCE',label:'STRAIGHT'},
  right:{key:'CITY_CROSSWALK_TURN_RIGHT_SEQUENCE',label:'RIGHT'}
};
let maneuverCrosswalkChains={left:[],straight:[],right:[]};
let maneuverActiveChainRoute='left';
let maneuverEncoderPulseCm=0.4;
let maneuverServoCenter=95;

function crosswalkChainDefaultStep(){
  return {direction:'f',distanceM:0.20,pwm:150,servo:maneuverServoCenter};
}
function crosswalkChainPulseCount(distanceM){
  if(!Number.isFinite(maneuverEncoderPulseCm)||maneuverEncoderPulseCm<=0)throw new Error('ENCODER_PULSE_DISTANCE_CM must be a positive calibrated value.');
  const count=Math.round(Number(distanceM)*100/maneuverEncoderPulseCm);
  if(!Number.isFinite(count)||count<1||count>10000)throw new Error('This distance converts to an invalid pulse count (allowed: 1–10000).');
  return count;
}
function parseCrosswalkChain(sequence){
  const raw=String(sequence||'').trim();
  if(!raw)return [crosswalkChainDefaultStep()];
  const tokens=raw.split(/\s+/);
  if(tokens.length%4!==0||tokens.length>64)throw new Error('Existing chain must contain up to 16 groups of four tokens.');
  const steps=[];
  for(let i=0;i<tokens.length;i+=4){
    const direction=tokens[i].toLowerCase();
    const pwm=Number(tokens[i+1]),pulses=Number(tokens[i+2]),servo=Number(tokens[i+3]);
    if(!['f','b'].includes(direction)||![pwm,pulses,servo].every(Number.isInteger)||pwm<0||pwm>255||pulses<1||pulses>10000||servo<0||servo>180){
      throw new Error('Invalid existing Arduino command group: '+tokens.slice(i,i+4).join(' '));
    }
    steps.push({direction:direction,distanceM:(pulses*maneuverEncoderPulseCm)/100,pwm:pwm,servo:servo});
  }
  return steps;
}
function serializeCrosswalkChain(route){
  const steps=maneuverCrosswalkChains[route]||[];
  if(!steps.length)throw new Error(CROSSWALK_CHAIN_ROUTES[route].label+' route needs at least one command step.');
  if(steps.length>CROSSWALK_CHAIN_LIMIT)throw new Error('Firmware allows at most '+CROSSWALK_CHAIN_LIMIT+' command groups in one route.');
  const builder=$('crosswalk_chain_builder');
  const servoMin=Number(builder&&builder.dataset.servoMin)||0;
  const servoMax=Number(builder&&builder.dataset.servoMax)||180;
  const groups=steps.map(function(step,index){
    const distance=Number(step.distanceM),pwm=Number(step.pwm),servo=Number(step.servo);
    if(!['f','b'].includes(step.direction))throw new Error('Step '+(index+1)+': choose forward or reverse.');
    if(!Number.isFinite(distance)||distance<0.05||distance>40)throw new Error('Step '+(index+1)+': distance must be between 0.05 and 40 metres.');
    if(!Number.isInteger(pwm)||pwm<0||pwm>255)throw new Error('Step '+(index+1)+': PWM must be an integer from 0 to 255.');
    if(!Number.isInteger(servo)||servo<servoMin||servo>servoMax)throw new Error('Step '+(index+1)+': servo command must be between '+servoMin+'° and '+servoMax+'° for this robot.');
    const pulses=crosswalkChainPulseCount(distance);
    return step.direction+' '+pwm+' '+pulses+' '+servo;
  });
  const sequence=groups.join(' ');
  if(sequence.length>512)throw new Error(CROSSWALK_CHAIN_ROUTES[route].label+' route exceeds the 512-character Arduino sequence limit.');
  return sequence;
}
function updateCrosswalkChainPreview(){
  const route=maneuverActiveChainRoute;
  const steps=maneuverCrosswalkChains[route]||[];
  const count=$('crosswalk_chain_count');
  const heading=$('crosswalk_chain_heading');
  const preview=$('crosswalk_chain_preview');
  const estimate=$('crosswalk_chain_estimate');
  const add=$('crosswalk_chain_add');
  if(count)count.textContent=steps.length+' / '+CROSSWALK_CHAIN_LIMIT+' steps';
  if(heading)heading.textContent=CROSSWALK_CHAIN_ROUTES[route].label+' route · command chain';
  if(add)add.disabled=!STREAM_CONTROL_ALLOWED||steps.length>=CROSSWALK_CHAIN_LIMIT;
  if(preview){
    try{preview.textContent=serializeCrosswalkChain(route);}
    catch(error){preview.textContent='Configure a valid step to preview the Arduino command.';}
  }
  if(estimate){
    try{
      const pulseCounts=steps.map(function(step){return crosswalkChainPulseCount(Number(step.distanceM));});
      const total=pulseCounts.reduce(function(sum,value){return sum+value;},0);
      estimate.textContent=steps.length+' step(s) · '+total+' estimated encoder pulses at '+maneuverEncoderPulseCm.toFixed(4)+' cm/pulse. Actual travel depends on measured calibration, wheel slip and drivetrain response.';
    }catch(error){estimate.textContent=error.message;}
  }
}
function renderCrosswalkChainEditor(){
  const host=$('crosswalk_chain_steps');
  if(!host)return;
  const builder=$('crosswalk_chain_builder');
  const servoMin=Number(builder&&builder.dataset.servoMin)||0;
  const servoMax=Number(builder&&builder.dataset.servoMax)||180;
  host.replaceChildren();
  Object.keys(CROSSWALK_CHAIN_ROUTES).forEach(function(route){
    const tab=builder&&builder.querySelector('[data-chain-route="'+route+'"]');
    if(tab){const active=route===maneuverActiveChainRoute;tab.classList.toggle('is-active',active);tab.setAttribute('aria-selected',active?'true':'false');tab.disabled=!STREAM_CONTROL_ALLOWED;}
  });
  (maneuverCrosswalkChains[maneuverActiveChainRoute]||[]).forEach(function(step,index){
    const row=document.createElement('div');row.className='crosswalk-step-row';
    const number=document.createElement('div');number.className='crosswalk-step-number';number.textContent='STEP '+(index+1);row.appendChild(number);
    function addField(title,control){
      const label=document.createElement('label');label.appendChild(document.createTextNode(title));label.appendChild(control);row.appendChild(label);
    }
    const direction=document.createElement('select');
    [['f','Forward'],['b','Reverse']].forEach(function(option){const node=document.createElement('option');node.value=option[0];node.textContent=option[1];direction.appendChild(node);});
    direction.value=step.direction;direction.disabled=!STREAM_CONTROL_ALLOWED;
    direction.addEventListener('change',function(){step.direction=direction.value;updateCrosswalkChainPreview();});
    addField('Direction',direction);

    const distance=document.createElement('input');distance.type='number';distance.min='0.05';distance.max='40';distance.step='0.05';distance.value=Number(step.distanceM).toFixed(2);distance.disabled=!STREAM_CONTROL_ALLOWED;
    const pulseHint=document.createElement('span');pulseHint.className='crosswalk-step-pulses';
    function refreshPulseHint(){try{pulseHint.textContent='≈ '+crosswalkChainPulseCount(Number(distance.value))+' pulses';}catch(error){pulseHint.textContent='Pulse estimate unavailable';}}
    distance.addEventListener('input',function(){step.distanceM=Number(distance.value);refreshPulseHint();updateCrosswalkChainPreview();});
    refreshPulseHint();
    const distanceWrap=document.createElement('div');distanceWrap.appendChild(distance);distanceWrap.appendChild(pulseHint);
    addField('Distance (metres)',distanceWrap);

    const speed=document.createElement('input');speed.type='number';speed.min='0';speed.max='255';speed.step='1';speed.value=String(step.pwm);speed.disabled=!STREAM_CONTROL_ALLOWED;
    speed.addEventListener('input',function(){step.pwm=Number(speed.value);updateCrosswalkChainPreview();});
    addField('Speed · PWM',speed);

    const angle=document.createElement('input');angle.type='number';angle.min=String(servoMin);angle.max=String(servoMax);angle.step='1';angle.value=String(step.servo);angle.disabled=!STREAM_CONTROL_ALLOWED;
    angle.addEventListener('input',function(){step.servo=Number(angle.value);updateCrosswalkChainPreview();});
    addField('Servo angle · °',angle);

    const remove=document.createElement('button');remove.type='button';remove.className='ghost crosswalk-step-remove';remove.textContent='Remove';remove.disabled=!STREAM_CONTROL_ALLOWED;
    remove.addEventListener('click',function(){maneuverCrosswalkChains[maneuverActiveChainRoute].splice(index,1);renderCrosswalkChainEditor();});
    row.appendChild(remove);
    host.appendChild(row);
  });
  if(!(maneuverCrosswalkChains[maneuverActiveChainRoute]||[]).length){
    const empty=document.createElement('p');empty.className='small-muted';empty.textContent='No steps yet. Add a command to build this route.';host.appendChild(empty);
  }
  updateCrosswalkChainPreview();
}
function initializeCrosswalkChains(advanced){
  const builder=$('crosswalk_chain_builder');
  if(!builder)return;
  const calibration=Number(advanced.ENCODER_PULSE_DISTANCE_CM!=null?advanced.ENCODER_PULSE_DISTANCE_CM:builder.dataset.encoderPulseCm);
  if(!Number.isFinite(calibration)||calibration<=0)throw new Error('A valid ENCODER_PULSE_DISTANCE_CM calibration is required before building metre-based routes.');
  maneuverEncoderPulseCm=calibration;
  maneuverServoCenter=Number(advanced.SERVO_CENTER==null?95:advanced.SERVO_CENTER);
  const calibrationLabel=$('crosswalk_encoder_calibration');
  if(calibrationLabel)calibrationLabel.textContent=maneuverEncoderPulseCm.toFixed(4)+' cm / pulse';
  const metreCount=$('crosswalk_chain_builder').querySelector('.crosswalk-pulse-calibration .small-muted:last-child');
  if(metreCount)metreCount.textContent='1 metre ≈ '+Math.round(100/maneuverEncoderPulseCm)+' pulses';
  Object.keys(CROSSWALK_CHAIN_ROUTES).forEach(function(route){
    const key=CROSSWALK_CHAIN_ROUTES[route].key;
    const textarea=$(route==='left'?'maneuver_city_left':route==='right'?'maneuver_city_right':'maneuver_city_straight');
    const sequence=advanced[key]||(textarea?textarea.value:'');
    maneuverCrosswalkChains[route]=parseCrosswalkChain(sequence);
  });
  maneuverActiveChainRoute='left';
  renderCrosswalkChainEditor();
}
function syncCrosswalkChainsToTextareas(body){
  Object.keys(CROSSWALK_CHAIN_ROUTES).forEach(function(route){
    const sequence=serializeCrosswalkChain(route);
    const key=CROSSWALK_CHAIN_ROUTES[route].key;
    const textarea=$(route==='left'?'maneuver_city_left':route==='right'?'maneuver_city_right':'maneuver_city_straight');
    if(textarea)textarea.value=sequence;
    body.advanced[key]=sequence;
  });
}

async function openManeuverConfigDialog(){
  try{
    const fresh=await readConfig();currentConfig=jsonClone(fresh);
    const a=fresh.advanced||{};
    [
      ['maneuver_obstacle_left','OBSTACLE_LANE_LEFT_SEQUENCE'],
      ['maneuver_obstacle_right','OBSTACLE_LANE_RIGHT_SEQUENCE'],
      ['maneuver_crosswalk_vertical_min','CROSSWALK_VERTICAL_MIN_LINES'],
      ['maneuver_crosswalk_horizontal_min','CROSSWALK_HORIZONTAL_MIN_LINES']
    ].forEach(function(pair){const input=$(pair[0]);if(input&&a[pair[1]]!=null)input.value=String(a[pair[1]]);});
    if(String(window.STREAM_BOOTSTRAP.mode||'').toLowerCase()==='city')initializeCrosswalkChains(a);
    setConfigDialogOpen('ext_maneuver_settings_dialog',true);
    const first=$('maneuver_obstacle_left');if(first&&!first.disabled)first.focus();
  }catch(error){showToast('Could not load maneuver configuration: '+error.message);}
}
async function saveManeuverConfigDialog(){
  if(!STREAM_CONTROL_ALLOWED)throw new Error('Dashboard is read-only.');
  const fresh=await readConfig();currentConfig=jsonClone(fresh);
  const body=jsonClone(fresh);body.advanced=body.advanced||{};
  const isCity=String(window.STREAM_BOOTSTRAP.mode||'').toLowerCase()==='city';
  const required=[
    ['maneuver_obstacle_left','OBSTACLE_LANE_LEFT_SEQUENCE'],
    ['maneuver_obstacle_right','OBSTACLE_LANE_RIGHT_SEQUENCE']
  ];
  if(isCity){
    syncCrosswalkChainsToTextareas(body);
    body.advanced.ENCODER_PULSE_DISTANCE_CM=maneuverEncoderPulseCm;
    [['maneuver_crosswalk_vertical_min','CROSSWALK_VERTICAL_MIN_LINES'],['maneuver_crosswalk_horizontal_min','CROSSWALK_HORIZONTAL_MIN_LINES']].forEach(function(pair){
      const raw=$(pair[0]).value.trim();
      if(!raw)throw new Error(pair[1]+' is required.');
      const value=Number(raw);
      if(!Number.isInteger(value)||value<0||value>1000)throw new Error(pair[1]+' must be an integer from 0 to 1000.');
      body.advanced[pair[1]]=value;
    });
  }
  required.forEach(function(pair){
    const input=$(pair[0]);if(!input)return;
    if(!input.value.trim())throw new Error(pair[1]+' cannot be empty.');
    body.advanced[pair[1]]=input.value.trim();
  });
  await applyFullConfig(body,isCity?'Updated City crosswalk hardcode chains and thresholds':'Updated Race obstacle sequences',true);
  setConfigDialogOpen('ext_maneuver_settings_dialog',false);
  showToast(isCity?'Saved and applied to future City crosswalk detections. The robot never moves just because settings were saved.':'Saved to race.json. Arduino startup lane sequences are configured by the next robot initialization.');
}
async function applyServoCenter(){
  if(!STREAM_CONTROL_ALLOWED)throw new Error('Dashboard is read-only.');
  const input=$('ext_servo_center'),status=$('ext_servo_center_status');
  if(!input)throw new Error('Servo center control is unavailable.');
  const center=Number(input.value),minimum=Number(input.min),maximum=Number(input.max);
  if(!Number.isInteger(center)||!Number.isFinite(center)||center<=minimum||center>=maximum){
    throw new Error('SERVO_CENTER must be an integer strictly between '+minimum+' and '+maximum+'.');
  }
  const fresh=await readConfig();
  const advanced=fresh.advanced||{};
  const current=Number(advanced.SERVO_CENTER==null?95:advanced.SERVO_CENTER);
  const runLevel=String(advanced.RUN_LVL||'MOVE').trim().toUpperCase();
  if(center!==current&&runLevel!=='STOP'){
    throw new Error('Set RUN_LVL=STOP first. Servo center cannot be changed while the robot is in MOVE.');
  }
  const body=jsonClone(fresh);
  body.advanced=body.advanced||{};
  body.advanced.SERVO_CENTER=center;
  await applyFullConfig(body,'Updated '+String(window.STREAM_BOOTSTRAP.mode||'mode').toUpperCase()+' servo center',true);
  input.value=String(center);
  const mode=String(window.STREAM_BOOTSTRAP.mode||'city').toLowerCase()==='race'?'race':'city';
  if(status)status.textContent='Saved to '+mode+'.json and applied to the active steering calibration. No servo command was sent.';
  showToast('SERVO_CENTER saved for '+mode+'.json: '+center+'°');
}
async function openPidConfigDialog(){
  try{
    const fresh=await readConfig();currentConfig=jsonClone(fresh);
    const a=fresh.advanced||{};
    [['pid_kp','KP'],['pid_ki','KI'],['pid_kd','KD'],['pid_kt','KT'],['pid_min_dt','PID_MIN_DT'],['pid_max_dt','PID_MAX_DT'],['pid_derivative_filter','PID_DERIVATIVE_FILTER']]
      .forEach(function(pair){if($(pair[0])&&a[pair[1]]!=null)$(pair[0]).value=String(a[pair[1]]);});
    const limits=Array.isArray(a.OUTPUT_LIMITS)?a.OUTPUT_LIMITS:[-80,80];
    $('pid_output_min').value=String(limits[0]);$('pid_output_max').value=String(limits[1]);
    $('pid_use_enabled').checked=!!a.USE_PID;$('pid_auto_update_kp').checked=!!a.AUTO_UPDATE_KP;
    setConfigDialogOpen('ext_pid_settings_dialog',true);
    if($('pid_kp')&&!$('pid_kp').disabled)$('pid_kp').focus();
  }catch(error){showToast('Could not load PID settings: '+error.message);}
}
async function savePidConfigDialog(){
  if(!STREAM_CONTROL_ALLOWED)throw new Error('Dashboard is read-only.');
  const fields=[
    ['pid_kp','KP',-100,100],['pid_ki','KI',-100,100],['pid_kd','KD',-100,100],
    ['pid_kt','KT',0,10],['pid_min_dt','PID_MIN_DT',0.0001,1],
    ['pid_max_dt','PID_MAX_DT',0.001,5],['pid_derivative_filter','PID_DERIVATIVE_FILTER',0,1]
  ];
  const values={};
  fields.forEach(function(row){
    const value=Number($(row[0]).value);
    if(!Number.isFinite(value)||value<row[2]||value>row[3])throw new Error(row[1]+' must be between '+row[2]+' and '+row[3]+'.');
    values[row[1]]=value;
  });
  if(values.PID_MAX_DT<values.PID_MIN_DT)throw new Error('PID_MAX_DT must be greater than or equal to PID_MIN_DT.');
  const low=Number($('pid_output_min').value),high=Number($('pid_output_max').value);
  if(!Number.isFinite(low)||!Number.isFinite(high)||low< -255||high>255||low>=high)throw new Error('Output limits must be ordered numbers within -255 to 255.');
  const fresh=await readConfig();currentConfig=jsonClone(fresh);
  const body=jsonClone(fresh);body.advanced=body.advanced||{};
  Object.keys(values).forEach(function(key){body.advanced[key]=values[key];});
  body.advanced.OUTPUT_LIMITS=[low,high];body.advanced.USE_PID=$('pid_use_enabled').checked;
  await applyFullConfig(body,'Updated '+String(window.STREAM_BOOTSTRAP.mode||'mode').toUpperCase()+' PID settings',true);
  setConfigDialogOpen('ext_pid_settings_dialog',false);
  showToast('PID settings saved to the active mode JSON and applied to the live controller.');
}

function installExtension(){
  const stage=$('canvas_stage');if(stage&&canvas){
    let svg=$('ext_precision_overlay');if(!svg){svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.id='ext_precision_overlay';svg.setAttribute('aria-hidden','true');stage.appendChild(svg);}
    canvas.addEventListener('pointerdown',onCustomPointerDown,true);
    installCoordinatePairPaste();
    canvas.addEventListener('pointermove',function(e){const point=pointFromEvent(e);if(extCrosshair&&!crosshairPinned)extCrosshairPoint=point;rulerHoverPoint=(editorTool==='ruler'&&rulerStart&&point)?snapshotRulerPoint(point):null;if(extCrosshair||crosshairPinned||(editorTool==='ruler'&&rulerStart))drawPrecisionOverlay();});
  }
  if($('ext_export_annotations'))$('ext_export_annotations').onclick=function(){downloadText(JSON.stringify(extAnnotations,null,2),'roboy-annotations.json','application/json');};
  $('ext_grid').addEventListener('change',function(){if(this.checked){if(gridMode==='off')gridMode=lastVisibleGridMode;extGrid=gridMode!=='off';}else{if(gridMode==='grid'||gridMode==='dots')lastVisibleGridMode=gridMode;gridMode='off';extGrid=false;}renderWorkspaceCanvas();scheduleWorkspaceSave();});
  $('roi_settings_open').addEventListener('click',openEditorSettings);$('roi_settings_close').addEventListener('click',()=>closeEditorSettings(true));$('roi_settings_cancel').addEventListener('click',()=>closeEditorSettings(true));
  $('roi_settings_apply').addEventListener('click',async()=>{const qualityInput=$('roi_setting_jpeg_quality');const requestedQuality=qualityInput?Number(qualityInput.value):streamJpegQuality;try{if(requestedQuality!==streamJpegQuality||streamQualityDraftDirty){if(!STREAM_CONTROL_ALLOWED)throw new Error('Stream controls are disabled; JPEG quality was not changed.');const response=await nativeFetch('/api/stream/quality',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({quality:requestedQuality})});const data=await response.json().catch(()=>({}));if(!response.ok)throw new Error(data.message||('HTTP '+response.status));streamJpegQuality=Number(data.quality);}previewEditorSettings();scheduleWorkspaceSave();closeEditorSettings(false);showToast('Editor settings applied'+(requestedQuality!==85?' · JPEG quality '+streamJpegQuality:''));}catch(error){showToast('Could not apply JPEG quality: '+(error&&error.message?error.message:'request failed'));}});$('roi_settings_reset').addEventListener('click',resetEditorSettingsDraft);
  const settingsModalElement=$('roi_settings_dialog');settingsModalElement.addEventListener('click',e=>{if(e.target===settingsModalElement)closeEditorSettings(true);});settingsModalElement.querySelectorAll('input,select').forEach(el=>['input','change'].forEach(evt=>el.addEventListener(evt,previewEditorSettings)));
  const jpegQualityInput=$('roi_setting_jpeg_quality');
  if(jpegQualityInput)jpegQualityInput.addEventListener('input',function(){streamQualityDraftDirty=true;const label=$('roi_setting_jpeg_quality_value');if(label)label.textContent=this.value+' / 100';});
  $('ext_snap').addEventListener('change',function(){extSnap=this.checked;scheduleWorkspaceSave();});
  $('ext_crosshair').addEventListener('change',function(){extCrosshair=this.checked;crosshairPinned=false;extCrosshairPoint=null;if(canvas)canvas.classList.toggle('crosshair-active',extCrosshair);updateActiveToolBanner();drawPrecisionOverlay();updateEditorStatus(extCrosshair?'Crosshair active: move to inspect coordinates, click to pin/copy, or press Esc to exit.':'Crosshair disabled; the pinned point was cleared.');persistCrosshairWorkspaceNow();});
  $('ext_measure_scale_apply').addEventListener('click',function(){const value=Number($('ext_measure_mm_per_px').value);if(!Number.isFinite(value)||value<0||value>10000){showToast('Scale must be 0 to 10000 mm per image pixel.');return;}mmPerSourcePixel=value;drawPrecisionOverlay();scheduleWorkspaceSave();updateEditorStatus(value>0?'Metric ruler enabled on a calibrated plane; perspective/depth affects accuracy.':'Metric scale disabled; ruler shows pixels.');showToast(value>0?'Planar scale applied.':'Pixel measurements enabled.');});
  $('ext_overlays').addEventListener('change',function(){showRectsCheckbox.checked=this.checked;if(typeof window.syncStreamOverlayControlUI==='function')window.syncStreamOverlayControlUI();renderWorkspaceCanvas();scheduleWorkspaceSave();});
  showRectsCheckbox.addEventListener('change',function(){if($('ext_overlays'))$('ext_overlays').checked=this.checked;if(typeof window.syncStreamOverlayControlUI==='function')window.syncStreamOverlayControlUI();});
  $('ext_annotate_btn').onclick=function(){setEditorTool(editorTool==='annotate'?'select':'annotate');};
  $('ext_ruler').addEventListener('change',function(){setEditorTool(this.checked?'ruler':'select');});
  $('ext_clear_annotations').onclick=function(){if(!extAnnotations.length)return;if(confirm('Clear all notes and ruler measurements from the workspace?')){extAnnotations=[];refreshAnnotationList();syncLayerControls();drawPrecisionOverlay();scheduleWorkspaceSave();}};
  $('ext_save_workspace').onclick=function(){saveWorkspace().then(function(){showToast('Workspace layout saved');}).catch(function(err){showToast(err.message);});};
  if($('ext_workspace_save_retry'))$('ext_workspace_save_retry').onclick=function(){saveWorkspace().catch(function(err){showToast('Workspace save failed: '+err.message);});};
  $('ext_capture_frame').onclick=addFrameSnapshot;$('ext_clear_gallery').onclick=function(){extFrameGallery=[];renderFrameGallery();};
  $('ext_profile_save').onclick=function(){profileAction('save').catch(function(e){showToast(e.message);});};$('ext_profile_load').onclick=function(){profileAction('load').catch(function(e){showToast(e.message);});};$('ext_profile_delete').onclick=function(){profileAction('delete').catch(function(e){showToast(e.message);});};
  const configFileInput=$('ext_config_file');
  if(configFileInput)configFileInput.addEventListener('change',function(){if(this.files&&this.files[0])importFullConfigFile(this.files[0]);this.value='';});
  $('ext_preset_save').onclick=function(){presetAction('save').then(refreshHistory).catch(function(e){showToast(e.message);});};
  $('ext_preset_apply').onclick=function(){presetAction('apply').catch(function(e){showToast(e.message);});};
  $('ext_preset_delete').onclick=function(){presetAction('delete').catch(function(e){showToast(e.message);});};
  $('ext_compare_preset').onclick=function(){comparePreset().catch(function(e){showToast(e.message);});};$('ext_history_refresh').onclick=function(){refreshHistory().catch(function(e){showToast(e.message);});};$('ext_history_restore').onclick=function(){restoreHistory().catch(function(e){showToast(e.message);});};
  $('ext_apply_fps').onclick=function(){applyProcessingRate().catch(function(e){showToast(e.message);});};$('ext_apply_camera').onclick=function(){applyCameraControls().catch(function(e){showToast(e.message);});};
  $('ext_calibration_apply').onclick=function(){applyCameraCalibrationSelection().catch(function(error){showToast('Could not apply calibration: '+error.message);const status=$('ext_calibration_status');if(status)status.textContent=error.message;});};
  $('ext_calibration_refresh').onclick=function(){refreshCameraCalibrations();};
  $('ext_calibration_upload').onclick=function(){uploadCameraCalibration().catch(function(error){showToast('Could not upload calibration: '+error.message);const status=$('ext_calibration_status');if(status)status.textContent=error.message;});};
  $('ext_overlay_apply').onclick=function(){saveFrameOverlaySettings().catch(function(error){showToast('Could not save frame overlay: '+error.message);const status=$('ext_overlay_status');if(status)status.textContent=error.message;});};
  refreshCameraCalibrations();
  $('ext_sign_requests_pause').onclick=function(){signRequestsAction('pause').catch(function(e){showToast(e.message);});};$('ext_sign_requests_resume').onclick=function(){signRequestsAction('resume').catch(function(e){showToast(e.message);});};
  $('ext_software_stop').onclick=function(){safetyAction('stop').catch(function(e){showToast(e.message);});};$('ext_software_resume').onclick=function(){safetyAction('resume').catch(function(e){showToast(e.message);});};
  $('ext_exposure').addEventListener('input',function(){markCameraDraftDirty('ext_exposure');});
  $('ext_gain').addEventListener('input',function(){markCameraDraftDirty('ext_gain');});
  $('ext_auto_exposure').addEventListener('change',function(){markCameraDraftDirty('ext_auto_exposure');updateCameraControlsEnabled();});
  $('ext_auto_wb').addEventListener('change',function(){markCameraDraftDirty('ext_auto_wb');});
  $('ext_target_fps').addEventListener('input',function(){processingRateDraftDirty=true;processingRateDraftVersion+=1;});
  $('ext_log_refresh').onclick=function(){refreshServerLogs();};$('ext_log_level').addEventListener('change',refreshServerLogs);$('ext_log_search').addEventListener('input',function(){clearTimeout(window.extLogDebounce);window.extLogDebounce=setTimeout(refreshServerLogs,250);});
  $('console_filter').addEventListener('input',function(){workspaceConsoleQuery=this.value;['events','api','python'].forEach(renderWorkspaceEventLog);});
  $('console_level').addEventListener('change',function(){workspaceConsoleLevel=this.value;['events','api','python'].forEach(renderWorkspaceEventLog);});
  $('console_pause').addEventListener('change',function(){workspaceConsolePaused=this.checked;if(!workspaceConsolePaused){['events','api','python'].forEach(renderWorkspaceEventLog);}});
  $('console_autoscroll').addEventListener('change',function(){workspaceConsoleAutoScroll=this.checked;if(workspaceConsoleAutoScroll){['events','api','python'].forEach(renderWorkspaceEventLog);}});
  $('console_export_btn').onclick=function(){downloadText(JSON.stringify({exported_at:new Date().toISOString(),events:workspaceEvents.map(function(e){return {time:e.time instanceof Date?e.time.toISOString():e.time,level:e.level,message:e.message};}),requests:workspaceApiEvents.map(function(e){return {time:e.time instanceof Date?e.time.toISOString():e.time,level:e.level,message:e.message};}),python_logs:workspacePythonLogs.map(function(e){return {time:e.time instanceof Date?e.time.toISOString():e.time,level:e.level,message:e.message};})},null,2),'roboy-workspace-console.json','application/json');};
  $('ext_log_export').onclick=function(){downloadText(JSON.stringify(serverLogsVisible,null,2),'roboy-runtime-logs.json','application/json');};
  $('ext_export_annotations').onclick=function(){downloadText(JSON.stringify(extAnnotations,null,2),'roboy-'+String(window.STREAM_BOOTSTRAP.mode || 'mode').toLowerCase()+'-annotations.json','application/json');};
  $('ext_open_palette').onclick=openCommandPalette;
  $('ext_crosswalk_hardcode_open').onclick=function(){openManeuverConfigDialog();};
  $('ext_maneuver_settings_open').onclick=function(){openManeuverConfigDialog();};
  const crosswalkBuilder=$('crosswalk_chain_builder');
  if(crosswalkBuilder){
    crosswalkBuilder.addEventListener('click',function(event){
      const routeButton=event.target.closest('[data-chain-route]');
      if(routeButton){
        maneuverActiveChainRoute=routeButton.dataset.chainRoute;
        renderCrosswalkChainEditor();
        return;
      }
      if(event.target.closest('#crosswalk_chain_add')){
        const chain=maneuverCrosswalkChains[maneuverActiveChainRoute]||[];
        if(chain.length>=CROSSWALK_CHAIN_LIMIT){showToast('Arduino queue capacity is '+CROSSWALK_CHAIN_LIMIT+' steps per route.');return;}
        chain.push(crosswalkChainDefaultStep());
        renderCrosswalkChainEditor();
      }
    });
  }
  $('ext_maneuver_settings_close').onclick=function(){setConfigDialogOpen('ext_maneuver_settings_dialog',false);};
  $('ext_maneuver_settings_cancel').onclick=function(){setConfigDialogOpen('ext_maneuver_settings_dialog',false);};
  $('ext_maneuver_settings_apply').onclick=function(){saveManeuverConfigDialog().catch(function(error){showToast('Could not save maneuver settings: '+error.message);});};
  $('ext_maneuver_settings_dialog').addEventListener('click',function(event){if(event.target===this)setConfigDialogOpen('ext_maneuver_settings_dialog',false);});
  $('ext_pid_settings_open').onclick=function(){openPidConfigDialog();};$('ext_apply_servo_center').onclick=function(){applyServoCenter().catch(function(error){showToast('Could not apply servo center: '+error.message);const status=$('ext_servo_center_status');if(status)status.textContent=error.message;});};
  $('ext_pid_settings_close').onclick=function(){setConfigDialogOpen('ext_pid_settings_dialog',false);};
  $('ext_pid_settings_cancel').onclick=function(){setConfigDialogOpen('ext_pid_settings_dialog',false);};
  $('ext_pid_settings_apply').onclick=function(){savePidConfigDialog().catch(function(error){showToast('Could not save PID settings: '+error.message);});};
  $('ext_pid_settings_dialog').addEventListener('click',function(event){if(event.target===this)setConfigDialogOpen('ext_pid_settings_dialog',false);});
  document.addEventListener('keydown',function(event){
    if(event.key!=='Escape')return;
    ['ext_maneuver_settings_dialog','ext_pid_settings_dialog'].forEach(function(id){const modal=$(id);if(modal&&modal.classList.contains('is-open')){event.preventDefault();setConfigDialogOpen(id,false);}});
  });
  $('ext_stream_exit_close').onclick=closeStreamExitDialog;
  $('ext_stream_exit_cancel').onclick=closeStreamExitDialog;
  $('ext_stream_exit_confirm').onclick=function(){requestStreamShutdown().catch(function(){});};
  $('ext_stream_exit_dialog').addEventListener('click',function(e){if(e.target===this)closeStreamExitDialog();});
  document.addEventListener('keydown',function(e){if(e.key==='Escape'&&$('ext_stream_exit_dialog').classList.contains('is-open')){e.preventDefault();e.stopImmediatePropagation();closeStreamExitDialog();}});
  $('active_tool_cancel').onclick=exitActiveTools;
  $('ext_encoder_reset').onclick=async function(){if(!confirm('Reset only the displayed odometry origin? Hardware counters will not be reset.'))return;const r=await nativeFetch('/api/encoder-map/reset-origin',{method:'POST'});const j=await r.json();if(!r.ok)throw new Error(j.error||('HTTP '+r.status));showToast('Displayed odometry origin reset');};
  $('ext_frame_compare_close').onclick=function(){$('ext_frame_compare').style.display='none';};
  $('ext_frame_compare').addEventListener('click',function(e){if(e.target===this)this.style.display='none';});
  $('ext_command_palette').addEventListener('click',function(e){if(e.target===this)closeCommandPalette();});buildCommandPalette();initializeResize();initializeConsoleResize();installWorkspaceKeyboardShortcuts();enableReadOnlyState();
  document.addEventListener('keydown',function(e){
    // Toggle robot motion with Ctrl+Shift+Space: stop while moving; resume while stopped.
    // Resume still requires confirmation. This is separate from /api/sign-requests.
    if(e.ctrlKey&&e.shiftKey&&(e.code==='Space'||e.key===' ')){
      if(e.repeat)return;
      e.preventDefault();
      toggleMotionSafetyFromKeyboard().catch(function(err){showToast('Motion toggle failed: '+err.message);});
      return;
    }
    if((e.ctrlKey||e.metaKey)&&e.code==='KeyK'){e.preventDefault();openCommandPalette();return;}
    if((e.ctrlKey||e.metaKey)&&e.shiftKey&&e.code==='KeyE'){e.preventDefault();exportFullConfig().catch(function(err){showToast('Export failed: '+err.message);});return;}
    if((e.ctrlKey||e.metaKey)&&e.code==='KeyS'){e.preventDefault();saveWorkspace().then(function(){showToast('Workspace saved');}).catch(function(err){showToast('Save failed: '+err.message);});return;}
    if($('ext_command_palette').style.display==='flex'&&e.code==='Escape'){e.preventDefault();closeCommandPalette();return;}
    if(e.code==='Escape'&&!$('roi_settings_dialog').classList.contains('is-open')&&!$('ext_stream_exit_dialog').classList.contains('is-open')&&(editorTool!=='select'||extCrosshair||crosshairPinned||extCrosshairPoint)){e.preventDefault();e.stopPropagation();exitActiveTools();return;}
    if(e.target&&(['INPUT','SELECT','TEXTAREA'].includes(e.target.tagName)||e.target.isContentEditable))return;
    if((e.ctrlKey||e.metaKey)&&e.code==='KeyZ'){e.preventDefault();if(e.shiftKey)doRedo();else doUndo();return;}
    if((e.ctrlKey||e.metaKey)&&e.code==='KeyY'){e.preventDefault();doRedo();return;}
    if(!e.ctrlKey&&!e.metaKey&&!e.altKey){
      if(e.code==='KeyG')$('ext_grid').click();
      else if(e.code==='KeyX')$('ext_crosshair').click();
      else if(e.code==='KeyN')setEditorTool('annotate');
      else if(e.code==='KeyR'){$('ext_ruler').checked=!$('ext_ruler').checked;$('ext_ruler').dispatchEvent(new Event('change'));}
    }
  });
  document.querySelectorAll('.right-panel details.dock-panel').forEach(function(panel){panel.addEventListener('toggle',scheduleWorkspaceSave);});
  window.addEventListener('resize',drawPrecisionOverlay);
}
async function initializeExtension(){
  try{currentConfig=await readConfig();if(currentConfig.ui&&currentConfig.ui.opacity)ui.opacity=currentConfig.ui.opacity;}catch(err){if(typeof recordApiEvent==='function')recordApiEvent('warn','Extended config API unavailable: '+err.message);}
  syncLayerControls();syncLegacyLayerControls();installExtension();refreshAnnotationList();drawPrecisionOverlay();
  if(extensionPollingEnabled){
    refreshWorkspaceProfiles().catch(function(err){if(typeof recordApiEvent==='function')recordApiEvent('warn','Workspace load failed: '+err.message);});
    refreshPresets().catch(function(err){if(typeof recordApiEvent==='function')recordApiEvent('warn','Preset list failed: '+err.message);});
    refreshHistory().catch(function(err){if(typeof recordApiEvent==='function')recordApiEvent('warn','History read failed: '+err.message);});
    refreshRuntime();refreshFeatureStatus();refreshTrafficAndRace();refreshCameraSettings();refreshProcessingRate();refreshSafety();refreshSignRequests();refreshServerLogs();
    startExtensionPolling();
  }
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',initializeExtension,{once:true});else initializeExtension();
})();

