function drawSparkline(id,values){
  const c=$(id);if(!c)return;const w=c.width,h=c.height,ctx=c.getContext('2d');ctx.clearRect(0,0,w,h);ctx.strokeStyle='rgba(148,163,184,.18)';ctx.lineWidth=1;
  for(let y=1;y<4;y++){ctx.beginPath();ctx.moveTo(0,h*y/4);ctx.lineTo(w,h*y/4);ctx.stroke();}
  const valid=values.filter(function(v){return Number.isFinite(v);});if(valid.length<2)return;
  let min=Math.min.apply(null,valid),max=Math.max.apply(null,valid);if(max-min<0.001){max=min+1;}
  ctx.beginPath();ctx.strokeStyle='#22d3ee';ctx.lineWidth=2;
  valid.forEach(function(v,i){const x=i*(w-8)/(valid.length-1)+4,y=h-5-(v-min)/(max-min)*(h-12);if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);});ctx.stroke();
  ctx.fillStyle='#9fb3c8';ctx.font='10px sans-serif';ctx.fillText(max.toFixed(1),4,11);ctx.fillText(min.toFixed(1),4,h-3);
}
function addFrameSnapshot(){
  if(!lastFrameImage||!lastFrameImage.complete||!lastFrameImage.naturalWidth){showToast('No decoded camera frame is available yet');return;}
  try{
    const temp=document.createElement('canvas');const maxW=640;const scale=Math.min(1,maxW/lastFrameImage.naturalWidth);temp.width=Math.max(1,Math.round(lastFrameImage.naturalWidth*scale));temp.height=Math.max(1,Math.round(lastFrameImage.naturalHeight*scale));
    temp.getContext('2d').drawImage(lastFrameImage,0,0,temp.width,temp.height);
    const item={timestamp:new Date().toISOString(),src:temp.toDataURL('image/jpeg',.85),width:temp.width,height:temp.height};extFrameGallery.unshift(item);extFrameGallery=extFrameGallery.slice(0,20);renderFrameGallery();showToast('Frame snapshot added to session history');
  }catch(err){showToast('Frame snapshot failed: '+err.message);}
}
function renderFrameGallery(){
  const root=$('ext_frame_gallery');if(!root)return;root.replaceChildren();
  extFrameGallery.forEach(function(item,index){
    const card=document.createElement('div');card.className='ext-gallery-card';const img=document.createElement('img');img.src=item.src;img.alt='Frame snapshot '+(index+1);card.appendChild(img);
    const info=document.createElement('div');info.textContent=new Date(item.timestamp).toLocaleTimeString()+' · '+item.width+'×'+item.height;card.appendChild(info);
    const row=document.createElement('div');row.style.display='flex';row.style.gap='3px';row.style.padding='4px';
    const cmp=document.createElement('button');cmp.type='button';cmp.className='ghost';cmp.textContent='Compare';cmp.style.flex='1';cmp.onclick=function(){showFrameComparison(item);};row.appendChild(cmp);
    const save=document.createElement('a');save.className='ghost';save.textContent='Save';save.href=item.src;save.download='frame-snapshot-'+(index+1)+'.jpg';save.style.textDecoration='none';save.style.fontSize='11px';row.appendChild(save);card.appendChild(row);root.appendChild(card);
  });
}
function showFrameComparison(item){
  const modal=$('ext_frame_compare');if(!modal)return;
  $('ext_compare_old').src=item.src;
  if(lastFrameImage&&lastFrameImage.complete&&lastFrameImage.naturalWidth){const c=document.createElement('canvas');c.width=lastFrameImage.naturalWidth;c.height=lastFrameImage.naturalHeight;c.getContext('2d').drawImage(lastFrameImage,0,0);$('ext_compare_live').src=c.toDataURL('image/jpeg',.85);}
  $('ext_frame_compare_title').textContent='Snapshot '+new Date(item.timestamp).toLocaleString()+' vs current frame';
  modal.style.display='flex';
}
function downloadText(data,filename,mime){
  const blob=new Blob([data],{type:mime||'application/json'});const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download=filename;document.body.appendChild(link);link.click();link.remove();setTimeout(function(){URL.revokeObjectURL(url);},500);
}
function collectWorkspace(){
  const layers={};EXT_LAYERS.forEach(key=>{layers[key]={visible:!!(ui.visible||{})[key],opacity:Number((ui.opacity||{})[key]==null?1:(ui.opacity||{})[key])};});
  layers.ANNOTATIONS={visible:extAnnotationsVisible,opacity:1};layers.GRID={visible:extGrid,opacity:gridOpacity};
  const panels={};document.querySelectorAll('.right-panel details.dock-panel').forEach(p=>{if(p.id)panels[p.id]=p.open;});
  const rect=document.querySelector('.right-panel').getBoundingClientRect(),paneWidth=parseFloat(getComputedStyle(document.querySelector('.container')).getPropertyValue('--right-pane-width'))||rect.width||315;
  return {view:{zoom:workspaceZoom,panX:viewPanX,panY:viewPanY,viewLocked:typeof window.isWorkspaceViewLocked==='function'?window.isWorkspaceViewLocked():false,grid:extGrid,gridMode:gridMode,gridStyle:lastVisibleGridMode,gridSpacing:gridSpacing,gridColor:gridColor,gridOpacity:gridOpacity,gridThickness:gridThickness,gridDotSize:gridDotSize,keyboardNudgePx:keyboardNudgePx,streamFps:streamFps,snap:extSnap,crosshair:extCrosshair,crosshairPoint:extCrosshairPoint?{space:extCrosshairPoint.space,u:extCrosshairPoint.u,v:extCrosshairPoint.v}:null,mmPerSourcePixel:mmPerSourcePixel,showRuler:editorTool==='ruler',overlays:!!showRectsCheckbox.checked,tool:editorTool,rightPaneWidth:paneWidth},
    roiAppearance:{labelFontSize:roiAppearance.labelFontSize,labelFontWeight:String(roiAppearance.labelFontWeight),outlineThickness:roiAppearance.outlineThickness,handleSize:roiAppearance.handleSize,showShapeType:!!roiAppearance.showShapeType},panels:panels,layers:layers,annotations:extAnnotations};
}
function setWorkspaceSaveStatus(state,message){
  const status=$('ext_workspace_save_status'),retry=$('ext_workspace_save_retry');
  if(status){status.dataset.state=state;status.textContent=message;}
  if(retry){retry.hidden=state!=='error';retry.disabled=state==='saving';}
}
let workspaceSaveRequestSequence=0;
async function saveWorkspace(){
  const sequence=++workspaceSaveRequestSequence;
  setWorkspaceSaveStatus('saving','Saving workspace…');
  const body=JSON.stringify({action:'save_workspace',workspace:collectWorkspace()});
  const request=workspaceSaveChain.catch(function(){}).then(function(){return nativeFetch('/api/workspace',{method:'POST',headers:{'Content-Type':'application/json'},body:body});});
  workspaceSaveChain=request.then(function(){},function(){});
  try{
    const response=await request;
    const data=await response.json().catch(function(){return {};});
    if(!response.ok)throw new Error(data.message||('HTTP '+response.status));
    if(sequence===workspaceSaveRequestSequence)setWorkspaceSaveStatus('saved','Saved · '+new Date().toLocaleTimeString());
    return data;
  }catch(error){
    if(sequence===workspaceSaveRequestSequence)setWorkspaceSaveStatus('error','Save failed: '+(error.message||error));
    throw error;
  }
}
function persistWorkspaceImmediately(){
  if(extSaveTimer){clearTimeout(extSaveTimer);extSaveTimer=null;}
  return saveWorkspace();
}
window.applyStreamWorkspace=function(workspace){applyWorkspace(workspace);renderWorkspaceCanvas();drawPrecisionOverlay();scheduleWorkspaceSave();};
function scheduleWorkspaceSave(){
  if(extSaveTimer)clearTimeout(extSaveTimer);
  // Invalidate older save responses immediately, not after the debounce delay.
  workspaceSaveRequestSequence++;
  setWorkspaceSaveStatus('unsaved','Unsaved changes · save scheduled');
  extSaveTimer=setTimeout(function(){extSaveTimer=null;saveWorkspace().catch(function(err){if(typeof recordApiEvent==='function')recordApiEvent('warn','Workspace persistence failed: '+err.message);});},450);
}
window.scheduleStreamWorkspaceSave=scheduleWorkspaceSave;
window.addEventListener('beforeunload',function(event){
  const status=$('ext_workspace_save_status');
  if(!status||!['unsaved','saving','error'].includes(status.dataset.state))return;
  event.preventDefault();
  event.returnValue='';
});
window.collectStreamWorkspace=collectWorkspace;
function applyWorkspace(workspace){
  if(!workspace||typeof workspace!=='object')return;const view=workspace.view||{};
  if(typeof view.zoom==='number'&&typeof setWorkspaceZoom==='function'){workspaceZoom=Math.max(.3,Math.min(4,view.zoom));viewPanX=Number(view.panX)||0;viewPanY=Number(view.panY)||0;$('workspace_zoom').value=String(workspaceZoom);}
  gridMode=['off','grid','dots'].includes(view.gridMode)?view.gridMode:(view.grid===true?'grid':'off');lastVisibleGridMode=['grid','dots'].includes(view.gridStyle)?view.gridStyle:((gridMode==='grid'||gridMode==='dots')?gridMode:'grid');
  gridSpacing=Math.max(.025,Math.min(.25,Number(view.gridSpacing)||.05));gridColor=/^#[0-9a-f]{6}$/i.test(String(view.gridColor||''))?String(view.gridColor).toLowerCase():'#69bed2';gridOpacity=Math.max(.05,Math.min(1,Number(view.gridOpacity)||.35));
  gridThickness=Math.max(.5,Math.min(3,Number(view.gridThickness)||1));gridDotSize=Math.max(1,Math.min(6,Number(view.gridDotSize)||2));keyboardNudgePx=Math.round(Math.max(1,Math.min(100,Number(view.keyboardNudgePx)||5)));if(view.streamFps!=null){streamFps=Math.max(1,Math.min(8.3,Math.round(Number(view.streamFps)*10)/10));if(typeof window.setStreamDisplayFps==='function')window.setStreamDisplayFps(streamFps);}
  const a=workspace.roiAppearance&&typeof workspace.roiAppearance==='object'?workspace.roiAppearance:{};
  roiAppearance={labelFontSize:Math.max(6,Math.min(32,Number(a.labelFontSize)||12)),labelFontWeight:['400','500','600','700'].includes(String(a.labelFontWeight))?String(a.labelFontWeight):'700',outlineThickness:Math.max(.5,Math.min(6,Number(a.outlineThickness)||2)),handleSize:Math.max(4,Math.min(24,Number(a.handleSize)||10)),showShapeType:a.showShapeType===true};
  const toolState=window.StreamState.normalizeWorkspaceToolState(view);
  extGrid=gridMode!=='off';extSnap=!!view.snap;extCrosshair=toolState.crosshairEnabled;extCrosshairPoint=toolState.crosshairPoint;crosshairPinned=toolState.crosshairPinned;mmPerSourcePixel=Math.max(0,Math.min(10000,Number(view.mmPerSourcePixel)||0));if($('ext_measure_mm_per_px'))$('ext_measure_mm_per_px').value=String(mmPerSourcePixel);
  if($('ext_grid'))$('ext_grid').checked=extGrid;if($('ext_snap'))$('ext_snap').checked=extSnap;if($('ext_crosshair'))$('ext_crosshair').checked=extCrosshair;if(canvas)canvas.classList.toggle('crosshair-active',extCrosshair);
  if($('ext_overlays'))$('ext_overlays').checked=view.overlays!==false;if(typeof view.overlays==='boolean')showRectsCheckbox.checked=view.overlays;
  if(typeof window.syncStreamOverlayControlUI==='function')window.syncStreamOverlayControlUI();
  editorTool=toolState.editorTool;
  const layers=workspace.layers||{};extAnnotationsVisible=!layers.ANNOTATIONS||layers.ANNOTATIONS.visible!==false;
  if(typeof window.setWorkspaceViewLocked==='function')window.setWorkspaceViewLocked(view.viewLocked===true,false,false);
  if(typeof view.rightPaneWidth==='number'&&view.rightPaneWidth>=250&&view.rightPaneWidth<=700)document.querySelector('.container').style.setProperty('--right-pane-width',view.rightPaneWidth+'px');
  Object.keys(workspace.panels||{}).forEach(id=>{const p=$(id);if(p&&p.tagName==='DETAILS')p.open=!!workspace.panels[id];});
  Object.keys(layers).forEach(key=>{const layer=layers[key];if(layer&&EXT_LAYERS.includes(key)){ui.visible[key]=layer.visible!==false;ui.opacity[key]=Number(layer.opacity==null?1:layer.opacity);}});
  if(layers.GRID&&layers.GRID.visible===false){gridMode='off';extGrid=false;}
  extAnnotations=Array.isArray(workspace.annotations)?jsonClone(workspace.annotations).filter(function(item){return item&& !['roi','roi_rect','roi_trapezoid'].includes(item.kind);}).slice(0,250):[];
  setEditorTool(editorTool,true,false);
  syncLayerControls();syncLegacyLayerControls();refreshAnnotationList();renderWorkspaceCanvas();drawPrecisionOverlay();updateZoomStatus();
}
function syncLegacyLayerControls(){
  const map={RL:'rl',LL:'ll',CW:'cw',ST:'st',OBJ:'obj',ML:'ml',MR:'mr',BEV:'bev'};
  Object.keys(map).forEach(function(key){const vis=$('vis_'+map[key]),color=$('color_'+map[key]);if(vis)vis.checked=ui.visible[key]!==false;if(color)color.value=(ui.colors||{})[key]||'#ffffff';});
}
function syncLayerControls(){
  const root=$('ext_layer_rows');if(!root)return;root.replaceChildren();
  EXT_LAYERS.forEach(function(key){
    const row=document.createElement('div');row.className='ext-layer-row';
    const check=document.createElement('input');check.type='checkbox';check.checked=ui.visible[key]!==false;check.title='Show/hide '+key;check.onchange=function(){ui.visible[key]=check.checked;syncLegacyLayerControls();saveUILayers();};row.appendChild(check);
    const label=document.createElement('span');label.textContent=({RL:'Right lane',LL:'Left lane',CW:'Crosswalk',ST:'Sign / tag',OBJ:'Object region',ML:'Maneuver left ROI',MR:'Maneuver right ROI',BEV:'Bird eye view'})[key]||key;row.appendChild(label);
    const color=document.createElement('input');color.type='color';color.value=(ui.colors||{})[key]||'#ffffff';color.title='Layer color';color.oninput=function(){ui.colors[key]=color.value;syncLegacyLayerControls();renderWorkspaceCanvas();scheduleUILayerSave();};row.appendChild(color);
    const opacity=document.createElement('input');opacity.type='range';opacity.min='0';opacity.max='1';opacity.step='.05';opacity.value=String((ui.opacity||{})[key]==null?1:ui.opacity[key]);opacity.title='Layer opacity';opacity.oninput=function(){ui.opacity=ui.opacity||{};ui.opacity[key]=Number(opacity.value);renderWorkspaceCanvas();drawPrecisionOverlay();scheduleUILayerSave();};row.appendChild(opacity);
    root.appendChild(row);
  });
  const annotationRow=document.createElement('div');annotationRow.className='ext-layer-row';annotationRow.style.gridTemplateColumns='18px minmax(0,1fr) auto';
  const annotationCheck=document.createElement('input');annotationCheck.type='checkbox';annotationCheck.checked=extAnnotationsVisible;annotationCheck.title='Show or hide note markers and ruler measurements';
  annotationCheck.onchange=function(){extAnnotationsVisible=annotationCheck.checked;drawPrecisionOverlay();scheduleWorkspaceSave();};
  annotationRow.appendChild(annotationCheck);
  const annotationLabel=document.createElement('span');annotationLabel.textContent='Notes & measurements';annotationRow.appendChild(annotationLabel);
  const annotationNote=document.createElement('span');annotationNote.className='small-muted';annotationNote.textContent=String(extAnnotations.length);annotationRow.appendChild(annotationNote);
  root.appendChild(annotationRow);
}
let uiLayerSaveTimer=null;
function scheduleUILayerSave(){if(uiLayerSaveTimer)clearTimeout(uiLayerSaveTimer);uiLayerSaveTimer=setTimeout(function(){saveUILayers().catch(function(err){showToast('Layer save failed: '+err.message);});},250);}
async function saveUILayers(){
  const before=currentConfig?jsonClone(currentConfig):await readConfig();
  const response=await nativeFetch('/set_ui',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({colors:ui.colors,visible:ui.visible,opacity:ui.opacity||{}})});
  const data=await response.json().catch(function(){return {};});if(!response.ok)throw new Error(data.message||('HTTP '+response.status));
  const after=await readConfig().catch(function(){return currentConfig;});rememberUndo(before,after);currentConfig=after;drawPrecisionOverlay();scheduleWorkspaceSave();return data;
}
function applyConfigToUI(snapshot){
  const cfg=normalizedConfig(snapshot);if(!cfg)return;
  currentConfig=cfg;values=jsonClone(cfg.values||values);advanced=jsonClone(cfg.advanced||advanced);ui=jsonClone(cfg.ui||ui);
  ui.colors=ui.colors||{};ui.visible=ui.visible||{};ui.opacity=ui.opacity||{};
  [['ML','#38bdf8'],['MR','#f59e0b']].forEach(function(item){if(ui.visible[item[0]]==null)ui.visible[item[0]]=true;if(!ui.colors[item[0]])ui.colors[item[0]]=item[1];if(ui.opacity[item[0]]==null)ui.opacity[item[0]]=1;});
  document.querySelectorAll('#inputs_container input[name]').forEach(function(input){if(Object.prototype.hasOwnProperty.call(values,input.name))input.value=String(values[input.name]);});
  const advancedInputs={lane_threshold:'LANE_THRESHOLD',cross_thresh:'CROSSWALK_THRESHOLD',crosswalk_sleep:'CROSSWALK_SLEEP',crosswalk_thresh_spend:'CROSSWALK_THRESH_SPEND',read_sign_threshold:'READ_SIGN_THRESHOLD',turn_right:'TURN_RIGHT',turn_left:'TURN_LEFT',straight:'STRAIGHT',stop_lvl:'STOP'};
  Object.keys(advancedInputs).forEach(function(id){if($(id)&&advanced[advancedInputs[id]]!=null)$(id).value=String(advanced[advancedInputs[id]]);});
  if($('with_sign'))$('with_sign').checked=!!advanced.WITH_SIGN;if($('with_apriltag'))$('with_apriltag').checked=!!advanced.WITH_APRILTAG;
  if(typeof updateInputsFromValues==='function')updateInputsFromValues();
  if(typeof updateShapeUIFromData==='function')updateShapeUIFromData();
  const runtime=cfg.runtime||{};if(runtime.target_processing_fps!=null&&$('ext_target_fps'))$('ext_target_fps').value=String(runtime.target_processing_fps);
  syncLegacyLayerControls();syncLayerControls();
  if(typeof window.syncPropertiesSelection==='function'&&$('prop_target'))window.syncPropertiesSelection($('prop_target').value);
  renderWorkspaceCanvas();drawPrecisionOverlay();
}
async function applyFullConfig(snapshot,label,trackForUndo){
  if(!STREAM_CONTROL_ALLOWED)throw new Error('Dashboard is read-only.');
  const body=normalizedConfig(snapshot);if(!body)throw new Error('Configuration snapshot is invalid.');
  const before=currentConfig?jsonClone(currentConfig):await readConfig();
  internalConfigWrite++;
  try{
    const response=await nativeFetch('/api/config/full',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const data=await response.json().catch(function(){return {};});if(!response.ok)throw new Error(data.message||('HTTP '+response.status));
    applyConfigToUI(data.config);
    const after=normalizedConfig(data.config);
    if(trackForUndo)rememberUndo(before,after);
    noteWorkspaceEvent('info',label||'Configuration restored');return data.config;
  }finally{internalConfigWrite--;}
}
async function doUndo(){
  if(!undoStack.length)return;const target=undoStack.pop(),previous=currentConfig?jsonClone(currentConfig):null;
  if(previous)redoStack.push(previous);
  try{const result=await applyFullConfig(target,'Undo configuration change');currentConfig=normalizedConfig(result);restoreTrackingStack();}
  catch(err){undoStack.push(target);if(previous&&redoStack.length)redoStack.pop();restoreTrackingStack();showToast('Undo failed: '+err.message);}
}
async function doRedo(){
  if(!redoStack.length)return;const target=redoStack.pop(),previous=currentConfig?jsonClone(currentConfig):null;
  if(previous)undoStack.push(previous);
  try{const result=await applyFullConfig(target,'Redo configuration change');currentConfig=normalizedConfig(result);restoreTrackingStack();}
  catch(err){redoStack.push(target);if(previous&&undoStack.length)undoStack.pop();restoreTrackingStack();showToast('Redo failed: '+err.message);}
}
async function refreshWorkspaceProfiles(){
  const data=await nativeFetch('/api/workspace',{cache:'no-store'}).then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.json();});
  workspaceProfileNames=data.profiles||[];
  if(data.migration_warning){updateEditorStatus(data.migration_warning);if(typeof recordApiEvent==='function')recordApiEvent('warn',data.migration_warning);}
  const select=$('ext_profile_select');select.replaceChildren();
  if(!workspaceProfileNames.length){const o=document.createElement('option');o.value='';o.textContent='No saved profiles';select.appendChild(o);}
  workspaceProfileNames.forEach(function(name){const o=document.createElement('option');o.value=name;o.textContent=name;select.appendChild(o);});
  if(data.workspace&&Object.keys(data.workspace).length)applyWorkspace(data.workspace);
}
async function profileAction(action){
  const name=String($('ext_profile_name').value||$('ext_profile_select').value||'').trim();if(!name)throw new Error('Enter or select a workspace profile name.');
  if(action==='delete'&&!confirm('Delete workspace profile "'+name+'"?'))return;
  const response=await nativeFetch('/api/workspace',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:action==='save'?'save_profile':action==='load'?'load_profile':'delete_profile',name:name,workspace:collectWorkspace()})});
  const data=await response.json().catch(function(){return {};});if(!response.ok)throw new Error(data.message||('HTTP '+response.status));
  if(action==='load')applyWorkspace(data.workspace);await refreshWorkspaceProfileNamesOnly();showToast('Workspace profile '+action+': '+name);
}
async function refreshWorkspaceProfileNamesOnly(){
  const d=await nativeFetch('/api/workspace',{cache:'no-store'}).then(function(r){return r.json();});
  workspaceProfileNames=d.profiles||[];const s=$('ext_profile_select');s.replaceChildren();if(!workspaceProfileNames.length){const o=document.createElement('option');o.value='';o.textContent='No saved profiles';s.appendChild(o);}
  workspaceProfileNames.forEach(function(n){const o=document.createElement('option');o.value=n;o.textContent=n;s.appendChild(o);});
}
async function refreshPresets(){
  const data=await nativeFetch('/api/config/presets',{cache:'no-store'}).then(async function(r){const j=await r.json();if(!r.ok)throw new Error(j.message||('HTTP '+r.status));return j;});
  presetNames=data.presets||[];const select=$('ext_preset_select');select.replaceChildren();
  if(!presetNames.length){const o=document.createElement('option');o.value='';o.textContent='No saved presets';select.appendChild(o);}
  presetNames.forEach(function(item){const o=document.createElement('option');o.value=item.name;o.textContent=item.name+' · '+item.mode;select.appendChild(o);});
}
async function presetAction(action){
  const name=String($('ext_preset_name').value||$('ext_preset_select').value||'').trim();if(!name)throw new Error('Enter or select a preset name.');
  if(action==='delete'&&!confirm('Delete configuration preset "'+name+'"?'))return;
  if(action==='apply'&&!confirm('Apply preset "'+name+'"? This changes live robot configuration.'))return;
  const before=action==='apply'?(currentConfig?jsonClone(currentConfig):await readConfig()):null;
  const response=await nativeFetch('/api/config/presets',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:action,name:name})});
  const data=await response.json().catch(function(){return {};});if(!response.ok)throw new Error(data.message||('HTTP '+response.status));
  if(action==='apply'){applyConfigToUI(data.config);const after=normalizedConfig(data.config);if(!sameConfig(before,after)){undoStack.push(before);undoStack=undoStack.slice(-40);redoStack=[];updateUndoButtons();}showToast('Preset applied: '+name);}
  await refreshPresets();if(action==='save')noteWorkspaceEvent('info','Saved configuration preset: '+name);
}
function renderConfigDiff(current,saved){
  const sections=[['ROI values','values'],['Advanced controls','advanced'],['UI settings','ui'],['Runtime settings','runtime']];const lines=[];
  sections.forEach(function(section){const key=section[1],a=current[key]||{},b=saved[key]||{},names=Array.from(new Set(Object.keys(a).concat(Object.keys(b)))).sort(),changes=[];
    names.forEach(function(name){if(JSON.stringify(a[name])!==JSON.stringify(b[name]))changes.push(name+': current='+JSON.stringify(a[name])+' → preset='+JSON.stringify(b[name]));});
    if(changes.length)lines.push('['+section[0]+']',...changes);
  });
  $('ext_config_diff').textContent=lines.join(String.fromCharCode(10))||'No differences between the current configuration and this preset.';
}
async function comparePreset(){
  const name=$('ext_preset_select').value;if(!name)throw new Error('Choose a preset to compare.');
  const response=await nativeFetch('/api/config/presets?name='+encodeURIComponent(name),{cache:'no-store'});
  const data=await response.json();if(!response.ok)throw new Error(data.message||('HTTP '+response.status));
  renderConfigDiff(currentConfig||await readConfig(),data.config);
}
async function refreshHistory(){
  const data=await nativeFetch('/api/config/history',{cache:'no-store'}).then(async function(r){const j=await r.json();if(!r.ok)throw new Error(j.message||('HTTP '+r.status));return j;});
  historyItems=data.items||[];const select=$('ext_history_select');select.replaceChildren();
  if(!historyItems.length){const o=document.createElement('option');o.value='';o.textContent='No saved history';select.appendChild(o);}
  historyItems.slice().reverse().forEach(function(item){const o=document.createElement('option');o.value=String(item.index);o.textContent=new Date(item.timestamp*1000).toLocaleString()+' · '+item.label;select.appendChild(o);});
}
async function restoreHistory(){
  const index=$('ext_history_select').value;if(index==='')throw new Error('Choose a history snapshot first.');
  if(!confirm('Restore the selected configuration snapshot?'))return;
  const before=currentConfig?jsonClone(currentConfig):await readConfig();
  const response=await nativeFetch('/api/config/history',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'restore',index:Number(index)})});
  const data=await response.json();if(!response.ok)throw new Error(data.message||('HTTP '+response.status));
  applyConfigToUI(data.config);const after=normalizedConfig(data.config);
  if(!sameConfig(before,after)){undoStack.push(before);undoStack=undoStack.slice(-40);redoStack=[];updateUndoButtons();}
  showToast('Configuration history restored');await refreshHistory();
}
function importFullConfigFile(file){
  const reader=new FileReader();reader.onload=async function(){try{
    const parsed=JSON.parse(String(reader.result||''));const normalized=normalizedConfig(parsed);
    if(!normalized||!normalized.values||!normalized.advanced||!normalized.ui)throw new Error('JSON is missing required full configuration sections.');
    if(normalized.mode!==String(window.STREAM_BOOTSTRAP.mode || 'mode').toLowerCase())throw new Error('File mode does not match this dashboard.');
    if(!confirm('Import this full configuration into the live robot runtime?'))return;
    const result=await applyFullConfig(normalized,'Imported full configuration',true);showToast('Full configuration imported');currentConfig=normalizedConfig(result);await refreshHistory();
  }catch(err){showToast('Import failed: '+err.message);}};reader.onerror=function(){showToast('Could not read the selected file');};reader.readAsText(file);
}
async function exportFullConfig(){
  const config=await readConfig();config.exported_at=new Date().toISOString();downloadText(JSON.stringify(config,null,2),'roboy-'+String(window.STREAM_BOOTSTRAP.mode || 'mode').toLowerCase()+'-full-config.json','application/json');noteWorkspaceEvent('info','Exported full configuration');
}
window.exportFullConfig=exportFullConfig;
window.reloadFullConfig=async function(){
  const config=await readConfig();
  currentConfig=config;
  applyConfigToUI(config);
  undoStack=[];redoStack=[];updateUndoButtons();
  showToast('Reloaded active configuration from the robot');
  noteWorkspaceEvent('info','Reloaded full configuration from runtime');
  return config;
};
