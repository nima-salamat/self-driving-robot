
(function(){
'use strict';
const $ = function(id){return document.getElementById(id)};
const jsonClone = function(value){return JSON.parse(JSON.stringify(value));};
const EXT_LAYERS = ['RL','LL','CW','ST','OBJ','BEV'];
let extGrid=false, extSnap=false, extCrosshair=false, extAnnotationsVisible=true, extCrosshairPoint=null;
let gridColor='#69bed2', keyboardNudgePx=5, streamFps=8.3, streamJpegQuality=85, streamQualityDraftDirty=false;
window.__isEditorSnapEnabled=()=>extSnap;
window.__getStreamKeyboardNudgePx=()=>keyboardNudgePx;
let editorTool='select', rulerStart=null, rulerHoverPoint=null, internalWorkspaceToolSync=false, extAnnotations=[], extFrameGallery=[], extRuntimeSample=[];
let undoStack=[], redoStack=[], currentConfig=null, internalConfigWrite=0, extSaveTimer=null, extHealthTimer=null, extSettingsTimer=null;
let serverLogsVisible=[], workspaceProfileNames=[], presetNames=[], historyItems=[];
let frameCompareImage=null, cameraSupportedControlNames=[], cameraSettingsEditable=false;
const cameraDraftDirty = new Set();
const cameraDraftVersions = Object.create(null);
let processingRateDraftDirty = false;
let processingRateDraftVersion = 0;
function markCameraDraftDirty(id){cameraDraftDirty.add(id);cameraDraftVersions[id]=(cameraDraftVersions[id]||0)+1;}
function cameraControlIsDrafted(id){const control=$(id);return cameraDraftDirty.has(id)||document.activeElement===control;}
const nativeFetch = window.fetch.bind(window);
let motionHotkeyActionInFlight=false, streamShutdownRequestedLocally=false, extensionPollingEnabled=true;
function stopExtensionPolling(){
  extensionPollingEnabled=false;
  if(extHealthTimer){clearInterval(extHealthTimer);extHealthTimer=null;}
  if(extSettingsTimer){clearInterval(extSettingsTimer);extSettingsTimer=null;}
}
function startExtensionPolling(){
  if(!extensionPollingEnabled||streamShutdownRequestedLocally)return;
  if(!extHealthTimer)extHealthTimer=setInterval(function(){if(streamShutdownRequestedLocally)return;refreshTrafficAndRace();refreshSafety();refreshSignRequests();},1800);
  if(!extSettingsTimer)extSettingsTimer=setInterval(function(){if(streamShutdownRequestedLocally)return;refreshCameraSettings();refreshProcessingRate();},8000);
}
window.setStreamExtensionPollingEnabled=function(enabled){
  extensionPollingEnabled=!!enabled;
  if(!extensionPollingEnabled){stopExtensionPolling();return;}
  if(streamShutdownRequestedLocally)return;
  startExtensionPolling();
  refreshRuntime();refreshFeatureStatus();refreshTrafficAndRace();refreshCameraSettings();refreshProcessingRate();refreshSafety();refreshSignRequests();refreshServerLogs();
};

function normalizedConfig(snapshot){
  if(!snapshot || typeof snapshot!=='object') return null;
  const copy=jsonClone(snapshot);
  delete copy.exported_at; delete copy.controls_enabled; delete copy.success;
  return copy.config && copy.config.schema_version ? normalizedConfig(copy.config) : copy;
}
function sameConfig(a,b){try{return JSON.stringify(normalizedConfig(a))===JSON.stringify(normalizedConfig(b));}catch(_){return false;}}
async function readConfig(){
  const response=await nativeFetch('/api/config/full',{cache:'no-store'});
  if(!response.ok) throw new Error('Config API returned HTTP '+response.status);
  return normalizedConfig(await response.json());
}
function updateUndoButtons(){
  if($('ext_undo')) $('ext_undo').disabled=!STREAM_CONTROL_ALLOWED||undoStack.length===0;
  if($('ext_redo')) $('ext_redo').disabled=!STREAM_CONTROL_ALLOWED||redoStack.length===0;
  if($('ext_undo_status')) $('ext_undo_status').textContent='Undo: '+undoStack.length+' · Redo: '+redoStack.length;
}
function rememberUndo(before,after){
  if(before&&!sameConfig(before,after)){
    undoStack.push(jsonClone(before));undoStack=undoStack.slice(-40);redoStack=[];updateUndoButtons();
  }
}
function restoreTrackingStack(){
  undoStack=undoStack.slice(-40);redoStack=redoStack.slice(-40);updateUndoButtons();
}
function isTrackedMutation(url,method){
  if(method!=='POST')return false;
  return ['/update_conf','/set_advanced','/set_ui','/api/config/full','/api/processing-rate','/api/camera/settings','/api/safety','/api/features','/toggle_record'].some(function(path){return url.split('?')[0].endsWith(path);});
}
window.fetch=async function(input,init){
  const url=typeof input==='string'?input:(input&&input.url)||'';
  const method=String((init&&init.method)||(input&&input.method)||'GET').toUpperCase();
  const track=isTrackedMutation(url,method)&&internalConfigWrite===0;
  const before=currentConfig?jsonClone(currentConfig):null;
  let response;
  try{response=await nativeFetch(input,init);}catch(err){throw err;}
  if(track&&response&&response.ok){
    try{
      const next=await readConfig();
      rememberUndo(before,next);
      currentConfig=next;updateUndoButtons();
    }catch(err){if(typeof recordApiEvent==='function')recordApiEvent('warn','Configuration tracker refresh failed: '+err.message);}
  }
  return response;
};

function addSVG(name,attrs,parent){
  const node=document.createElementNS('http://www.w3.org/2000/svg',name);
  Object.keys(attrs||{}).forEach(function(key){node.setAttribute(key,String(attrs[key]));});
  (parent||$('ext_precision_overlay')).appendChild(node);return node;
}
function extImageBounds(){
  try{return getImgBounds();}catch(_){return {ix:0,iy:0,iw:canvas.width,ih:canvas.height};}
}
function drawPrecisionOverlay(){
  const svg=$('ext_precision_overlay'),stage=$('canvas_stage');
  if(!svg||!canvas||!stage)return;
  const z=getOverlayScale();
  const canvasRect=canvas.getBoundingClientRect(),stageRect=stage.getBoundingClientRect();
  const contentLeft=stageRect.left+stage.clientLeft,contentTop=stageRect.top+stage.clientTop;
  svg.style.left=(canvasRect.left-contentLeft)+'px';
  svg.style.top=(canvasRect.top-contentTop)+'px';
  svg.style.width=Math.max(1,canvasRect.width)+'px';
  svg.style.height=Math.max(1,canvasRect.height)+'px';
  svg.setAttribute('viewBox','0 0 '+canvas.width+' '+canvas.height);
  svg.replaceChildren();
  const b=extImageBounds();
  const visibleGrid=gridMode!=='off'&&extGrid&&(!currentConfig||!currentConfig.ui||!currentConfig.ui.visible||currentConfig.ui.visible.GRID!==false);
  if(visibleGrid){
    // Spacing is measured as a fraction of image height. Convert X spacing
    // into normalized U coordinates so visible cells are square in pixels.
    const stepY=Math.max(.025,Math.min(.25,Number(gridSpacing)||.05));
    const stepX=typeof getGridStepX==='function'?getGridStepX():stepY*b.ih/Math.max(1,b.iw);
    const stroke= /^#[0-9a-f]{6}$/i.test(gridColor)?gridColor:'#69bed2';
    const alpha=Math.max(.05,Math.min(1,Number(gridOpacity)||.35));
    if(gridMode==='dots'){
      const radius=Math.max(.6,Number(gridDotSize||2)*z);
      for(let column=0;column*stepX<=1.000001;column++){
        const u=column*stepX;
        for(let row=0;row*stepY<=1.000001;row++){
          const v=row*stepY;
          addSVG('circle',{cx:b.ix+b.iw*u,cy:b.iy+b.ih*v,r:radius,fill:stroke,'fill-opacity':alpha});
        }
      }
    }else{
      for(let u=stepX;u<1;u+=stepX){const x=b.ix+b.iw*u;addSVG('line',{x1:x,y1:b.iy,x2:x,y2:b.iy+b.ih,stroke:stroke,'stroke-opacity':alpha,'stroke-width':Math.max(.4,gridThickness*z)});}
      for(let v=stepY;v<1;v+=stepY){const y=b.iy+b.ih*v;addSVG('line',{x1:b.ix,y1:y,x2:b.ix+b.iw,y2:y,stroke:stroke,'stroke-opacity':alpha,'stroke-width':Math.max(.4,gridThickness*z)});}
    }
    addSVG('rect',{x:b.ix,y:b.iy,width:b.iw,height:b.ih,fill:'none',stroke:stroke,'stroke-opacity':alpha,'stroke-width':Math.max(.5,gridThickness*z)});
  }
  if(extCrosshair&&extCrosshairPoint){
    addSVG('line',{x1:b.ix,y1:extCrosshairPoint.y,x2:b.ix+b.iw,y2:extCrosshairPoint.y,stroke:'#f8fafc','stroke-width':z,'stroke-dasharray':(6*z)+' '+(4*z)});
    addSVG('line',{x1:extCrosshairPoint.x,y1:b.iy,x2:extCrosshairPoint.x,y2:b.iy+b.ih,stroke:'#f8fafc','stroke-width':z,'stroke-dasharray':(6*z)+' '+(4*z)});
    const label=addSVG('text',{x:extCrosshairPoint.x+8*z,y:extCrosshairPoint.y-8*z,fill:'#fff','font-size':11*z,'paint-order':'stroke','stroke':'#07101a','stroke-width':3*z});
    label.textContent='U '+(((extCrosshairPoint.x-b.ix)/b.iw)*100).toFixed(1)+'% · V '+(((extCrosshairPoint.y-b.iy)/b.ih)*100).toFixed(1)+'%';
  }
  if(editorTool==='ruler'&&rulerStart&&rulerHoverPoint){
    const x1=b.ix+rulerStart.u*b.iw,y1=b.iy+rulerStart.v*b.ih;
    const x2=b.ix+rulerHoverPoint.u*b.iw,y2=b.iy+rulerHoverPoint.v*b.ih;
    const distance=Math.hypot((rulerHoverPoint.u-rulerStart.u)*(frameSourceWidth||canvas.width),(rulerHoverPoint.v-rulerStart.v)*(frameSourceHeight||canvas.height));
    addSVG('line',{x1:x1,y1:y1,x2:x2,y2:y2,stroke:'#22d3ee','stroke-width':Math.max(1,2*z),'stroke-dasharray':(6*z)+' '+(3*z)});
    addSVG('circle',{cx:x1,cy:y1,r:Math.max(3,(Number(roiAppearance.handleSize)||10)*.45*z),fill:'#22d3ee',stroke:'#e0faff','stroke-width':z});
    addSVG('circle',{cx:x2,cy:y2,r:Math.max(3,(Number(roiAppearance.handleSize)||10)*.45*z),fill:'#22d3ee',stroke:'#e0faff','stroke-width':z});
    const distanceLabel=addSVG('text',{x:(x1+x2)/2+7*z,y:(y1+y2)/2-7*z,fill:'#e0faff','font-size':Math.max(10,(Number(roiAppearance.labelFontSize)||12)*z),'font-weight':'700','paint-order':'stroke',stroke:'#07101a','stroke-width':3*z});
    distanceLabel.textContent=distance.toFixed(1)+' px';
  }
  if(!extAnnotationsVisible)return;
  const baseOutline=Math.max(.5,Number(roiAppearance.outlineThickness)||2);
  const baseLabel=Math.max(6,Number(roiAppearance.labelFontSize)||12);
  const baseHandle=Math.max(4,Number(roiAppearance.handleSize)||10);
  const labelWeight=String(roiAppearance.labelFontWeight||'700');
  extAnnotations.forEach(function(item,index){
    const color=item.color||'#fbbf24';
    if(item.kind==='roi'||item.kind==='roi_rect'||item.kind==='roi_trapezoid')return;
    const x=b.ix+Number(item.u||0)*b.iw,y=b.iy+Number(item.v||0)*b.ih;
    if(item.kind==='ruler'&&item.u2!=null&&item.v2!=null){
      const x2=b.ix+item.u2*b.iw,y2=b.iy+item.v2*b.ih;
      addSVG('line',{x1:x,y1:y,x2:x2,y2:y2,stroke:color,'stroke-width':baseOutline*z});
      addSVG('circle',{cx:x,cy:y,r:baseHandle*.35*z,fill:color});addSVG('circle',{cx:x2,cy:y2,r:baseHandle*.35*z,fill:color});
      const label=addSVG('text',{x:(x+x2)/2+5*z,y:(y+y2)/2-5*z,fill:color,'font-size':baseLabel*z,'font-weight':labelWeight,'paint-order':'stroke',stroke:'#07101a','stroke-width':1.5*baseOutline*z});
      label.textContent=item.label||Math.hypot((item.u2-item.u)*b.iw,(item.v2-item.v)*b.ih).toFixed(1)+' px';
    }else{
      addSVG('circle',{cx:x,cy:y,r:baseHandle*.6*z,fill:'rgba(251,191,36,.2)',stroke:color,'stroke-width':baseOutline*z});
      addSVG('line',{x1:x-baseHandle*z,y1:y,x2:x+baseHandle*z,y2:y,stroke:color,'stroke-width':baseOutline*z});
      addSVG('line',{x1:x,y1:y-baseHandle*z,x2:x,y2:y+baseHandle*z,stroke:color,'stroke-width':baseOutline*z});
      if(item.label){const label=addSVG('text',{x:x+baseHandle*z,y:y-0.8*baseLabel*z,fill:color,'font-size':baseLabel*z,'font-weight':labelWeight,'paint-order':'stroke',stroke:'#07101a','stroke-width':1.5*baseOutline*z});label.textContent=item.label;}
    }
  });
}
window.drawPrecisionOverlay=drawPrecisionOverlay;

function updateEditorStatus(text){if($('ext_editor_status'))$('ext_editor_status').textContent=text;}
function updateActiveToolBanner(){
  const banner=$('active_tool_banner'),label=$('active_tool_label');if(!banner||!label)return;
  const active=editorTool!=='select';
  banner.hidden=!active;
  if(!active)return;
  const messages={
    pan:'Pan mode is active · drag the camera to move the view',
    annotate:'Note / marker mode is active · click the image to place an annotation',
    ruler:rulerStart?'Ruler mode is active · move to preview the distance, click again to finish':'Ruler mode is active · click two points to measure distance'
  };
  label.textContent=messages[editorTool]||('Tool mode: '+editorTool);
}
function setEditorTool(tool,syncCore=true,persist=true){
  editorTool=['select','pan','annotate','ruler'].includes(tool)?tool:'select';
  rulerStart=null;rulerHoverPoint=null;
  if($('ext_ruler'))$('ext_ruler').checked=editorTool==='ruler';
  ['ext_annotate_btn','ext_ruler'].forEach(function(id){
    if($(id))$(id).classList.toggle('ext-tool-active',(id==='ext_ruler'&&editorTool==='ruler')||(id==='ext_annotate_btn'&&editorTool==='annotate'));
  });
  if(syncCore&&typeof window.setStreamWorkspaceTool==='function'){
    internalWorkspaceToolSync=true;
    try{window.setStreamWorkspaceTool(editorTool==='pan'?'pan':'select');}finally{internalWorkspaceToolSync=false;}
  }
  if(canvas)canvas.style.cursor=editorTool==='pan'?'grab':(['annotate','ruler'].includes(editorTool)?'crosshair':'default');
  const messages={ruler:'Ruler active: click two points inside the image.',annotate:'Annotation mode active: click the image to add a note or marker.',pan:'Pan mode active: drag the camera view.'};
  updateEditorStatus(messages[editorTool]||'Select / Edit ROI mode active.');
  updateActiveToolBanner();
  if(typeof window.refreshStreamCommandPalette==='function')window.refreshStreamCommandPalette();
  if(persist)scheduleWorkspaceSave();
  drawPrecisionOverlay();
}
window.onStreamWorkspaceToolChanged=function(tool){
  if(internalWorkspaceToolSync)return;
  setEditorTool(tool==='pan'?'pan':'select',false,true);
};
window.onWorkspaceViewLockChanged=function(){
  scheduleWorkspaceSave();
  if(typeof window.refreshStreamCommandPalette==='function')window.refreshStreamCommandPalette();
};
function pointFromEvent(event){
  const rect=canvas.getBoundingClientRect();
  const x=(event.clientX-rect.left)*(canvas.width/rect.width),y=(event.clientY-rect.top)*(canvas.height/rect.height);
  const b=extImageBounds();
  if(x<b.ix||x>b.ix+b.iw||y<b.iy||y>b.iy+b.ih)return null;
  let u=(x-b.ix)/b.iw,v=(y-b.iy)/b.ih;
  if(extSnap){const step=Math.max(.025,Math.min(.25,Number(gridSpacing)||.05));u=Math.round(u/step)*step;v=Math.round(v/step)*step;}
  u=Math.max(0,Math.min(1,u));v=Math.max(0,Math.min(1,v));
  return {x:b.ix+u*b.iw,y:b.iy+v*b.ih,u:u,v:v};
}
function refreshAnnotationList(){
  const root=$('ext_annotations_list');if(!root)return;root.replaceChildren();
  if(!extAnnotations.length){const empty=document.createElement('div');empty.className='small-muted';empty.textContent='No annotations yet. Add a note or measure a distance.';root.appendChild(empty);syncLayerControls();return;}
  extAnnotations.forEach(function(item,index){
    const row=document.createElement('div');row.className='ext-list-row annotation-row';
    const label=document.createElement('span');label.textContent=(index+1)+'. '+(item.kind||'marker')+(item.label?': '+item.label:'');row.appendChild(label);
    const remove=document.createElement('button');remove.type='button';remove.className='ghost annotation-delete';remove.textContent='Delete ×';remove.title='Delete this annotation';remove.setAttribute('aria-label','Delete annotation '+(index+1));
    remove.onclick=function(){const currentIndex=extAnnotations.indexOf(item);if(currentIndex<0)return;extAnnotations.splice(currentIndex,1);refreshAnnotationList();drawPrecisionOverlay();scheduleWorkspaceSave();};
    row.appendChild(remove);root.appendChild(row);
  });
  syncLayerControls();
}
let settingsBeforeOpen=null,settingsReturnFocus=null;
function currentEditorSettings(){return{gridMode,gridSpacing,gridOpacity,gridThickness,gridDotSize,gridColor,keyboardNudgePx,streamFps,snap:extSnap,roiAppearance:{labelFontSize:roiAppearance.labelFontSize,labelFontWeight:String(roiAppearance.labelFontWeight),outlineThickness:roiAppearance.outlineThickness,handleSize:roiAppearance.handleSize}};}
function syncSettingsFormControls(a){$('roi_setting_grid_mode').value=a.gridMode;$('roi_setting_grid_spacing').value=String(a.gridSpacing);$('roi_setting_grid_spacing_value').textContent=Number((a.gridSpacing*100).toFixed(1))+'% of frame height';$('roi_setting_grid_color').value=a.gridColor||'#69bed2';$('roi_setting_stream_fps').value=String(a.streamFps||8.3);$('roi_setting_stream_fps_value').textContent=Number(a.streamFps||8.3).toFixed(1)+' FPS target';$('roi_setting_grid_opacity').value=String(a.gridOpacity);$('roi_setting_grid_thickness').value=String(a.gridThickness);$('roi_setting_grid_dot_size').value=String(a.gridDotSize);$('roi_setting_keyboard_nudge').value=String(a.keyboardNudgePx||5);$('roi_setting_snap').checked=!!a.snap;$('roi_setting_label_size').value=String(a.roiAppearance.labelFontSize);$('roi_setting_label_size_value').textContent=a.roiAppearance.labelFontSize+' px at 100%';$('roi_setting_label_weight').value=String(a.roiAppearance.labelFontWeight);$('roi_setting_outline_thickness').value=String(a.roiAppearance.outlineThickness);$('roi_setting_handle_size').value=String(a.roiAppearance.handleSize);}
function applyEditorSettings(a,redraw=true){gridMode=['off','grid','dots'].includes(a.gridMode)?a.gridMode:'off';gridSpacing=Math.max(.025,Math.min(.25,Number(a.gridSpacing)||.05));gridColor=/^#[0-9a-f]{6}$/i.test(String(a.gridColor||''))?String(a.gridColor).toLowerCase():'#69bed2';streamFps=Math.max(1,Math.min(30,Math.round((Number(a.streamFps)||8.3)*10)/10));if(typeof window.setStreamDisplayFps==='function')window.setStreamDisplayFps(streamFps);gridOpacity=Math.max(.05,Math.min(1,Number(a.gridOpacity)||.35));gridThickness=Math.max(.5,Math.min(3,Number(a.gridThickness)||1));gridDotSize=Math.max(1,Math.min(6,Number(a.gridDotSize)||2));keyboardNudgePx=Math.round(Math.max(1,Math.min(100,Number(a.keyboardNudgePx)||5)));extGrid=gridMode!=='off';extSnap=!!a.snap;const r=a.roiAppearance||{};roiAppearance={labelFontSize:Math.max(6,Math.min(32,Number(r.labelFontSize)||12)),labelFontWeight:['400','500','600','700'].includes(String(r.labelFontWeight))?String(r.labelFontWeight):'700',outlineThickness:Math.max(.5,Math.min(6,Number(r.outlineThickness)||2)),handleSize:Math.max(4,Math.min(24,Number(r.handleSize)||10))};if($('ext_grid'))$('ext_grid').checked=extGrid;if($('ext_snap'))$('ext_snap').checked=extSnap;if(redraw){renderWorkspaceCanvas();drawPrecisionOverlay();}}
function readEditorSettingsForm(){return{gridMode:$('roi_setting_grid_mode').value,gridSpacing:Number($('roi_setting_grid_spacing').value),gridColor:$('roi_setting_grid_color').value,streamFps:Number($('roi_setting_stream_fps').value),gridOpacity:Number($('roi_setting_grid_opacity').value),gridThickness:Number($('roi_setting_grid_thickness').value),gridDotSize:Number($('roi_setting_grid_dot_size').value),keyboardNudgePx:Number($('roi_setting_keyboard_nudge').value),snap:$('roi_setting_snap').checked,roiAppearance:{labelFontSize:Number($('roi_setting_label_size').value),labelFontWeight:$('roi_setting_label_weight').value,outlineThickness:Number($('roi_setting_outline_thickness').value),handleSize:Number($('roi_setting_handle_size').value)}};}
function previewEditorSettings(){const a=readEditorSettingsForm();applyEditorSettings(a);syncSettingsFormControls(a);}
async function refreshStreamJpegQualityFromServer(){try{const response=await nativeFetch('/api/stream/quality',{cache:'no-store'});if(!response.ok)return;const data=await response.json();const quality=Number(data.quality);if(!Number.isInteger(quality)||quality<30||quality>100)return;streamJpegQuality=quality;const qualityInput=$('roi_setting_jpeg_quality');const qualityValue=$('roi_setting_jpeg_quality_value');if(qualityInput&&!streamQualityDraftDirty&&$('roi_settings_dialog').classList.contains('is-open')){qualityInput.value=String(quality);if(qualityValue)qualityValue.textContent=quality+' / 100';}}catch(error){if(typeof recordApiEvent==='function')recordApiEvent('warn','Could not read Stream JPEG quality: '+(error&&error.message?error.message:'request failed'));}}
function openEditorSettings(){const m=$('roi_settings_dialog');streamQualityDraftDirty=false;settingsBeforeOpen=currentEditorSettings();settingsReturnFocus=document.activeElement;syncSettingsFormControls(settingsBeforeOpen);const qualityInput=$('roi_setting_jpeg_quality');if(qualityInput){qualityInput.value=String(streamJpegQuality);qualityInput.disabled=!STREAM_CONTROL_ALLOWED;}const qualityValue=$('roi_setting_jpeg_quality_value');if(qualityValue)qualityValue.textContent=streamJpegQuality+' / 100';m.classList.add('is-open');m.setAttribute('aria-hidden','false');$('roi_setting_grid_mode').focus();refreshStreamJpegQualityFromServer();}
function closeEditorSettings(restore){const m=$('roi_settings_dialog');if(restore&&settingsBeforeOpen)applyEditorSettings(settingsBeforeOpen);if(restore){const qualityInput=$('roi_setting_jpeg_quality');if(qualityInput)qualityInput.value=String(streamJpegQuality);const qualityValue=$('roi_setting_jpeg_quality_value');if(qualityValue)qualityValue.textContent=streamJpegQuality+' / 100';}m.classList.remove('is-open');m.setAttribute('aria-hidden','true');streamQualityDraftDirty=false;if(settingsReturnFocus&&settingsReturnFocus.focus)settingsReturnFocus.focus();settingsBeforeOpen=null;}
function resetEditorSettingsDraft(){const a={gridMode:'off',gridSpacing:.05,gridColor:'#69bed2',streamFps:8.3,gridOpacity:.35,gridThickness:1,gridDotSize:2,keyboardNudgePx:5,snap:false,roiAppearance:{labelFontSize:12,labelFontWeight:'700',outlineThickness:2,handleSize:10}};syncSettingsFormControls(a);const qualityInput=$('roi_setting_jpeg_quality');if(qualityInput)qualityInput.value=String(STREAM_CONTROL_ALLOWED?85:streamJpegQuality);streamQualityDraftDirty=!!STREAM_CONTROL_ALLOWED;const qualityValue=$('roi_setting_jpeg_quality_value');if(qualityValue)qualityValue.textContent=(qualityInput?qualityInput.value:streamJpegQuality)+' / 100';applyEditorSettings(a);}
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&$('roi_settings_dialog').classList.contains('is-open')){e.preventDefault();closeEditorSettings(true);}});

async function copyCoordinateText(text){
  try{if(navigator.clipboard&&window.isSecureContext){await navigator.clipboard.writeText(text);return true;}}catch(_){}
  const input=document.createElement('textarea');input.value=text;input.setAttribute('readonly','');
  input.style.position='fixed';input.style.left='-9999px';input.style.top='0';document.body.appendChild(input);
  input.select();let copied=false;try{copied=document.execCommand('copy');}catch(_){}input.remove();
  if(!copied)throw new Error('Clipboard access is blocked by this browser.');
  return true;
}
function onCustomPointerDown(event){
  if(extCrosshair&&event.button===0){
    event.preventDefault();event.stopPropagation();event.stopImmediatePropagation();
    const point=pointFromEvent(event);
    if(!point){showToast('Click inside the visible camera frame to capture U,V coordinates.');return;}
    extCrosshairPoint={x:point.x,y:point.y};
    const coordinateText=point.u.toFixed(3)+', '+point.v.toFixed(3);
    extCrosshair=false;if($('ext_crosshair'))$('ext_crosshair').checked=false;
    if(canvas)canvas.classList.remove('crosshair-active');
    drawPrecisionOverlay();scheduleWorkspaceSave();
    copyCoordinateText(coordinateText).then(function(){
      updateEditorStatus('Captured and copied normalized point (U, V): '+coordinateText+'. Paste into an ROI corner in Properties.');
      showToast('Copied U, V: '+coordinateText+' · Paste into Left/Top or Right/Bottom, then Apply.');
      if(typeof noteWorkspaceEvent==='function')noteWorkspaceEvent('info','Crosshair point copied: '+coordinateText);
    }).catch(function(){
      updateEditorStatus('Captured U, V: '+coordinateText+'. Clipboard unavailable; coordinates are shown here.');
      showToast('Point: '+coordinateText+' · Clipboard unavailable.');
    });
    return;
  }
  if(!['annotate','ruler'].includes(editorTool)||event.button!==0)return;
  const point=pointFromEvent(event);if(!point)return;
  event.preventDefault();event.stopPropagation();event.stopImmediatePropagation();
  if(editorTool==='annotate'){
    let label=window.prompt('Annotation label (optional):','');
    if(label===null)return;
    label=String(label).trim().slice(0,80);
    extAnnotations.push({kind:label?'note':'marker',u:point.u,v:point.v,label:label,color:'#fbbf24'});
    if(extAnnotations.length>250)extAnnotations.shift();
    refreshAnnotationList();syncLayerControls();drawPrecisionOverlay();scheduleWorkspaceSave();
    updateEditorStatus('Annotation placed at U '+(point.u*100).toFixed(1)+'%, V '+(point.v*100).toFixed(1)+'%.');
  }else if(!rulerStart){
    rulerStart=point;rulerHoverPoint=point;updateEditorStatus('Ruler start marked. Move the pointer to preview distance; click the second point to finish.');updateActiveToolBanner();drawPrecisionOverlay();
  }else{
    const start=rulerStart;rulerStart=null;
    if(editorTool==='ruler'){
      const distance=Math.hypot((point.u-start.u)*(frameSourceWidth||canvas.width),(point.v-start.v)*(frameSourceHeight||canvas.height));
      extAnnotations.push({kind:'ruler',u:start.u,v:start.v,u2:point.u,v2:point.v,label:distance.toFixed(1)+' px',color:'#22d3ee'});rulerHoverPoint=null;
      updateEditorStatus('Ruler saved: '+distance.toFixed(1)+' image pixels.');updateActiveToolBanner();syncLayerControls();
    }
    if(extAnnotations.length>250)extAnnotations.shift();
    refreshAnnotationList();drawPrecisionOverlay();scheduleWorkspaceSave();
  }
}
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
  layers.ANNOTATIONS={visible:extAnnotationsVisible,opacity:1};layers.GRID={visible:gridMode!=='off',opacity:gridOpacity};
  const panels={};document.querySelectorAll('.right-panel details.dock-panel').forEach(p=>{if(p.id)panels[p.id]=p.open;});
  const rect=document.querySelector('.right-panel').getBoundingClientRect(),paneWidth=parseFloat(getComputedStyle(document.querySelector('.container')).getPropertyValue('--right-pane-width'))||rect.width||315;
  return {view:{zoom:workspaceZoom,panX:viewPanX,panY:viewPanY,viewLocked:typeof window.isWorkspaceViewLocked==='function'?window.isWorkspaceViewLocked():false,grid:gridMode!=='off',gridMode:gridMode,gridSpacing:gridSpacing,gridColor:gridColor,gridOpacity:gridOpacity,gridThickness:gridThickness,gridDotSize:gridDotSize,keyboardNudgePx:keyboardNudgePx,streamFps:streamFps,snap:extSnap,crosshair:extCrosshair,showRuler:editorTool==='ruler',overlays:!!showRectsCheckbox.checked,tool:editorTool,rightPaneWidth:paneWidth},
    roiAppearance:{labelFontSize:roiAppearance.labelFontSize,labelFontWeight:String(roiAppearance.labelFontWeight),outlineThickness:roiAppearance.outlineThickness,handleSize:roiAppearance.handleSize},panels:panels,layers:layers,annotations:extAnnotations};
}
async function saveWorkspace(){
  const response=await nativeFetch('/api/workspace',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'save_workspace',workspace:collectWorkspace()})});
  const data=await response.json().catch(function(){return {};});if(!response.ok)throw new Error(data.message||('HTTP '+response.status));return data;
}
function scheduleWorkspaceSave(){
  if(extSaveTimer)clearTimeout(extSaveTimer);
  extSaveTimer=setTimeout(function(){saveWorkspace().catch(function(err){if(typeof recordApiEvent==='function')recordApiEvent('warn','Workspace persistence failed: '+err.message);});},450);
}
function applyWorkspace(workspace){
  if(!workspace||typeof workspace!=='object')return;const view=workspace.view||{};
  if(typeof view.zoom==='number'&&typeof setWorkspaceZoom==='function'){workspaceZoom=Math.max(.3,Math.min(4,view.zoom));viewPanX=Number(view.panX)||0;viewPanY=Number(view.panY)||0;$('workspace_zoom').value=String(workspaceZoom);}
  gridMode=['off','grid','dots'].includes(view.gridMode)?view.gridMode:(view.grid===true?'grid':'off');
  gridSpacing=Math.max(.025,Math.min(.25,Number(view.gridSpacing)||.05));gridColor=/^#[0-9a-f]{6}$/i.test(String(view.gridColor||''))?String(view.gridColor).toLowerCase():'#69bed2';gridOpacity=Math.max(.05,Math.min(1,Number(view.gridOpacity)||.35));
  gridThickness=Math.max(.5,Math.min(3,Number(view.gridThickness)||1));gridDotSize=Math.max(1,Math.min(6,Number(view.gridDotSize)||2));keyboardNudgePx=Math.round(Math.max(1,Math.min(100,Number(view.keyboardNudgePx)||5)));if(view.streamFps!=null){streamFps=Math.max(1,Math.min(30,Math.round(Number(view.streamFps)*10)/10));if(typeof window.setStreamDisplayFps==='function')window.setStreamDisplayFps(streamFps);}
  const a=workspace.roiAppearance&&typeof workspace.roiAppearance==='object'?workspace.roiAppearance:{};
  roiAppearance={labelFontSize:Math.max(6,Math.min(32,Number(a.labelFontSize)||12)),labelFontWeight:['400','500','600','700'].includes(String(a.labelFontWeight))?String(a.labelFontWeight):'700',outlineThickness:Math.max(.5,Math.min(6,Number(a.outlineThickness)||2)),handleSize:Math.max(4,Math.min(24,Number(a.handleSize)||10))};
  extGrid=gridMode!=='off';extSnap=!!view.snap;extCrosshair=!!view.crosshair;
  if($('ext_grid'))$('ext_grid').checked=extGrid;if($('ext_snap'))$('ext_snap').checked=extSnap;if($('ext_crosshair'))$('ext_crosshair').checked=extCrosshair;
  if($('ext_overlays'))$('ext_overlays').checked=view.overlays!==false;if(typeof view.overlays==='boolean')showRectsCheckbox.checked=view.overlays;
  if(typeof window.syncStreamOverlayControlUI==='function')window.syncStreamOverlayControlUI();
  editorTool=['select','pan','annotate','ruler'].includes(view.tool)?view.tool:'select';
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
  const map={RL:'rl',LL:'ll',CW:'cw',ST:'st',OBJ:'obj',BEV:'bev'};
  Object.keys(map).forEach(function(key){const vis=$('vis_'+map[key]),color=$('color_'+map[key]);if(vis)vis.checked=ui.visible[key]!==false;if(color)color.value=(ui.colors||{})[key]||'#ffffff';});
}
function syncLayerControls(){
  const root=$('ext_layer_rows');if(!root)return;root.replaceChildren();
  EXT_LAYERS.forEach(function(key){
    const row=document.createElement('div');row.className='ext-layer-row';
    const check=document.createElement('input');check.type='checkbox';check.checked=ui.visible[key]!==false;check.title='Show/hide '+key;check.onchange=function(){ui.visible[key]=check.checked;syncLegacyLayerControls();saveUILayers();};row.appendChild(check);
    const label=document.createElement('span');label.textContent=({RL:'Right lane',LL:'Left lane',CW:'Crosswalk',ST:'Sign / tag',OBJ:'Object region',BEV:'Bird eye view'})[key]||key;row.appendChild(label);
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
  workspaceProfileNames=data.profiles||[];const select=$('ext_profile_select');select.replaceChildren();
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
  const keys=['fps','realfps','status','applied_angle','vision_angle','servo_center','crosswalk','sign','last_tag','error','lane_type','speed','confidence','obstacle'];
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
function paletteNormalize(value){
  const raw=String(value==null?'':value);
  return (typeof raw.normalize==='function'?raw.normalize('NFKC'):raw).toLocaleLowerCase();
}
function palettePanelTrail(detail){
  const parts=[];let current=detail;
  while(current&&current.matches&&current.matches('details.dock-panel')){
    const summary=current.querySelector(':scope > summary');
    const name=summary?summary.textContent.replace(/\s+/g,' ').trim():'Panel';
    if(name)parts.push(name);
    current=current.parentElement?current.parentElement.closest('details.dock-panel'):null;
  }
  return parts.reverse().join(' › ')||'Settings';
}
function settingSearchEntries(){
  const entries=[],seen=new Set();
  function add(label,panelTitle,detail,target,focusTarget,modal,kind){
    const name=String(label||'').replace(/\s+/g,' ').trim();
    if(name.length<2)return;
    const node=target||detail||focusTarget;if(!node)return;
    const identity=(panelTitle+'|'+name+'|'+(node.id||node.tagName||'item')).toLocaleLowerCase();
    if(seen.has(identity))return;seen.add(identity);
    const extra=[node.id,node.title,node.getAttribute&&node.getAttribute('aria-label'),focusTarget&&focusTarget.id,focusTarget&&focusTarget.placeholder].filter(Boolean).join(' ');
    entries.push({label:name,panelTitle:panelTitle,detail:detail,target:node,focusTarget:focusTarget||node,modal:!!modal,kind:kind||'SETTING',
      searchable:paletteNormalize(name+' '+panelTitle+' '+extra+' '+(kind||'setting'))});
  }
  document.querySelectorAll('.right-panel details.dock-panel').forEach(function(detail){
    const summary=detail.querySelector(':scope > summary');
    const panelTitle=palettePanelTrail(detail);
    if(summary)add('Open panel: '+summary.textContent,panelTitle,detail,summary,summary,false,'PANEL');
    detail.querySelectorAll('.dock-content label,.dock-content .section-title,.dock-content h3,.dock-content button,.dock-content .small-muted,.dock-content .settings-note').forEach(function(node){
      if(node.closest('details.dock-panel')!==detail)return;
      let focus=node.control||null;
      if(node.tagName==='LABEL'){
        if(!focus&&node.htmlFor)focus=document.getElementById(node.htmlFor);
        if(!focus)focus=node.querySelector('input,select,textarea,button');
      }
      const kind=node.matches('button')?'ACTION':node.matches('label')?'SETTING':'SECTION';
      add(node.textContent,panelTitle,detail,node,focus||node,false,kind);
    });
    detail.querySelectorAll('.dock-content input,.dock-content select,.dock-content textarea').forEach(function(control){
      if(control.closest('details.dock-panel')!==detail)return;
      const labels=control.labels?Array.from(control.labels):[];
      const label=labels.map(function(x){return x.textContent;}).join(' ').trim()||control.getAttribute('aria-label')||control.title||control.placeholder||control.name||control.id;
      if(!label)return;
      if(labels.length)return;
      add(label,panelTitle,detail,control,control,false,'SETTING');
    });
    detail.querySelectorAll('.dock-content select').forEach(function(control){
      if(control.closest('details.dock-panel')!==detail)return;
      Array.from(control.options||[]).forEach(function(option){
        if(!option.textContent.trim())return;
        const label=(control.labels&&control.labels.length?Array.from(control.labels).map(function(x){return x.textContent;}).join(' '):control.getAttribute('aria-label')||control.id)+' · '+option.textContent.trim();
        add(label,panelTitle,detail,control,control,false,'OPTION');
      });
    });
  });
  const editorSettings=document.getElementById('roi_settings_dialog');
  if(editorSettings){
    editorSettings.querySelectorAll('.settings-section h3').forEach(function(node){
      add(node.textContent,'Editor Settings',null,node,node,true,'SECTION');
    });
    editorSettings.querySelectorAll('.settings-section label').forEach(function(node){
      const focus=node.control||(node.htmlFor?document.getElementById(node.htmlFor):node.querySelector('input,select,textarea'));
      add(node.textContent,'Editor Settings',null,node,focus||node,true,'SETTING');
    });
    editorSettings.querySelectorAll('.settings-section select').forEach(function(control){
      Array.from(control.options||[]).forEach(function(option){
        add((control.labels&&control.labels.length?Array.from(control.labels).map(function(x){return x.textContent;}).join(' '):'Editor setting')+' · '+option.textContent,'Editor Settings',null,control,control,true,'OPTION');
      });
    });
    editorSettings.querySelectorAll('.settings-note').forEach(function(node){
      add(node.textContent,'Editor Settings',null,node,node,true,'HELP');
    });
  }
  return entries;
}
function navigateToPaletteSetting(entry){
  closeCommandPalette();
  function revealAndFocus(){
    if(entry.modal){
      const modal=$('roi_settings_dialog');
      if(modal&&!modal.classList.contains('is-open'))$('roi_settings_open').click();
    }else if(typeof window.ensureStreamDockVisible==='function'){
      window.ensureStreamDockVisible();
    }
    if(entry.detail){
      const ancestors=[];let detail=entry.detail;
      while(detail&&detail.matches&&detail.matches('details.dock-panel')){
        ancestors.push(detail);
        detail=detail.parentElement?detail.parentElement.closest('details.dock-panel'):null;
      }
      ancestors.reverse().forEach(function(panel){panel.open=true;});
    }
    window.requestAnimationFrame(function(){
      window.requestAnimationFrame(function(){
        const target=entry.target;
        if(!target||!target.isConnected)return;
        target.scrollIntoView({behavior:'smooth',block:'center',inline:'nearest'});
        const focus=entry.focusTarget;
        if(focus&&typeof focus.focus==='function'&&!focus.disabled){
          try{focus.focus({preventScroll:true});}catch(_){focus.focus();}
        }
        if(target.__paletteHighlightTimer)clearTimeout(target.__paletteHighlightTimer);
        target.classList.remove('palette-setting-highlight');
        void target.offsetWidth;
        target.classList.add('palette-setting-highlight');
        target.__paletteHighlightTimer=setTimeout(function(){
          target.classList.remove('palette-setting-highlight');
          target.__paletteHighlightTimer=null;
        },2100);
      });
    });
  }
  revealAndFocus();
}
function isPaletteCommandActive(name){
  if(name==='view-lock')return typeof window.isWorkspaceViewLocked==='function'&&window.isWorkspaceViewLocked();
  if(name==='select')return editorTool==='select';
  if(name==='pan')return editorTool==='pan';
  if(name==='annotate')return editorTool==='annotate';
  if(name==='ruler')return editorTool==='ruler';
  if(name==='grid')return !!($('ext_grid')&&$('ext_grid').checked);
  if(name==='crosshair')return !!($('ext_crosshair')&&$('ext_crosshair').checked);
  if(name==='overlays')return !!($('ext_overlays')&&$('ext_overlays').checked);
  if(name==='profile')return !!($('ext_editor_panel')&&$('ext_editor_panel').open&&document.activeElement===$('ext_profile_name'));
  if(name==='preset')return !!($('ext_config_panel')&&$('ext_config_panel').open&&document.activeElement===$('ext_preset_name'));
  return false;
}
function isEditableKeyboardTarget(target){
  return !!(target&&(
    target.isContentEditable||
    ['INPUT','TEXTAREA','SELECT'].includes(target.tagName)||
    target.closest&&target.closest('[contenteditable="true"]')
  ));
}
function toggleSettingsPanels(){
  const button=$('toggle_dock_btn');
  if(button)button.click();
}
function focusPanelNavigation(){
  const container=document.querySelector('.container');
  if(typeof window.ensureStreamDockVisible==='function')window.ensureStreamDockVisible();
  else if(container&&(container.classList.contains('dock-hidden')||(window.matchMedia('(max-width: 720px)').matches&&!container.classList.contains('show-dock'))))toggleSettingsPanels();
  window.requestAnimationFrame(function(){
    const first=document.querySelector('.right-panel details.dock-panel > summary');
    if(first)first.focus();
    else showToast('Settings panel navigation is unavailable.');
  });
}
function adjustSettingsPanelWidth(direction){
  if(window.innerWidth<721)return;
  const container=document.querySelector('.container');
  const panel=document.querySelector('.right-panel');
  if(!container||!panel||container.classList.contains('dock-hidden'))return;
  const current=parseFloat(getComputedStyle(container).getPropertyValue('--right-pane-width'))||panel.getBoundingClientRect().width||315;
  const minimum=250,maximum=Math.max(minimum,Math.min(700,window.innerWidth-360));
  const width=Math.round(Math.max(minimum,Math.min(maximum,current+(direction>0?24:-24))));
  container.style.setProperty('--right-pane-width',width+'px');
  const handle=$('panel_resize_handle');
  if(handle){
    handle.setAttribute('aria-valuenow',String(width));
    handle.setAttribute('aria-valuetext',width+' pixels wide');
  }
  if(typeof scheduleWorkspaceSave==='function')scheduleWorkspaceSave();
}
function consoleResizeLimits(){
  const mobile=window.matchMedia('(max-width: 720px)').matches;
  const shortLandscape=window.matchMedia('(max-width: 900px) and (orientation: landscape) and (max-height: 520px)').matches;
  const minimum=mobile?84:96;
  const maximum=Math.max(minimum,Math.min(shortLandscape?200:(mobile?360:520),window.innerHeight*(shortLandscape?0.42:(mobile?0.55:0.62)),window.innerHeight-(mobile?80:120)));
  return {minimum:minimum,maximum:maximum};
}
function changeConsoleHeight(direction){
  const dock=$('bottom_console'),toggle=$('console_toggle_btn'),handle=$('console_resize_handle');
  if(!dock||!toggle)return;
  const bounds=consoleResizeLimits(),isOpen=dock.classList.contains('console-open');
  let current=parseFloat(dock.style.getPropertyValue('--console-resize-height'));
  if(!Number.isFinite(current))current=isOpen?(dock.getBoundingClientRect().height||178):178;
  if(direction>0){
    if(!isOpen){
      const height=Math.max(bounds.minimum,Math.min(bounds.maximum,178));
      dock.style.setProperty('--console-resize-height',height+'px');
      toggle.click();
      if(handle){handle.setAttribute('aria-valuenow',String(height));handle.setAttribute('aria-valuetext',height+' pixels tall');}
    }else{
      const height=Math.max(bounds.minimum,Math.min(bounds.maximum,current+24));
      dock.style.setProperty('--console-resize-height',height+'px');
      if(handle){handle.setAttribute('aria-valuenow',String(height));handle.setAttribute('aria-valuetext',height+' pixels tall');}
    }
  }else if(isOpen){
    if(current<=bounds.minimum+24){
      toggle.click();
      if(handle)handle.setAttribute('aria-valuetext','Closed. Drag upward to open and downward to close.');
    }else{
      const height=Math.max(bounds.minimum,current-24);
      dock.style.setProperty('--console-resize-height',height+'px');
      if(handle){handle.setAttribute('aria-valuenow',String(height));handle.setAttribute('aria-valuetext',height+' pixels tall');}
    }
  }
  if(typeof scheduleWorkspaceSave==='function')scheduleWorkspaceSave();
}
function openTopMenu(menuId){
  const menu=document.querySelector('.app-menubar .menu-group[data-menu-id="'+menuId+'"]');
  if(!menu)return;
  document.querySelectorAll('.app-menubar .menu-group').forEach(function(item){item.open=item===menu;});
  const first=menu.querySelector('.menu-dropdown button:not(:disabled)');
  const summary=menu.querySelector(':scope > summary');
  if(first)first.focus();else if(summary)summary.focus();
}
function installWorkspaceKeyboardShortcuts(){
  const menuKeyMap={KeyF:'file',KeyE:'edit',KeyV:'view',KeyT:'tools',KeyH:'help'};
  function isAltGraph(event){return !!(event.getModifierState&&event.getModifierState('AltGraph'));}
  function syncMnemonicHints(event){
    const bar=document.querySelector('.app-menubar');
    if(bar)bar.classList.toggle('shortcuts-visible',!!(event&&event.ctrlKey&&event.altKey&&!event.metaKey&&!isAltGraph(event)));
  }
  document.addEventListener('keydown',function(event){
    syncMnemonicHints(event);
    const target=event.target;
    const menuItem=target&&target.closest?target.closest('.menu-dropdown button'):null;
    if(menuItem&&menuItem.closest('.menu-group[open]')){
      const menu=menuItem.closest('.menu-group[open]');
      const items=Array.from(menu.querySelectorAll('.menu-dropdown button:not(:disabled)'));
      const index=items.indexOf(menuItem);
      if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){
        event.preventDefault();
        let next=index;
        if(event.key==='ArrowDown')next=(index+1)%items.length;
        else if(event.key==='ArrowUp')next=(index-1+items.length)%items.length;
        else if(event.key==='Home')next=0;
        else next=items.length-1;
        if(items[next])items[next].focus();
        return;
      }
      if(event.key==='Escape'){
        event.preventDefault();event.stopPropagation();menu.open=false;
        const summary=menu.querySelector(':scope > summary');if(summary)summary.focus();
        return;
      }
    }
    if(target&&target.matches&&target.matches('.right-panel .dock-panel > summary')){
      const summaries=Array.from(document.querySelectorAll('.right-panel .dock-panel > summary'));
      const index=summaries.indexOf(target);
      if(event.key==='ArrowDown'||event.key==='ArrowUp'){
        event.preventDefault();
        const delta=event.key==='ArrowDown'?1:-1;
        const next=(index+delta+summaries.length)%summaries.length;
        if(summaries[next])summaries[next].focus();
        return;
      }
      if(event.key==='Home'||event.key==='End'){
        event.preventDefault();
        const next=event.key==='Home'?summaries[0]:summaries[summaries.length-1];
        if(next)next.focus();
        return;
      }
      // Space and Enter keep native <summary> toggle behaviour.
    }
    const palette=$('ext_command_palette');
    if(palette&&palette.style.display==='flex')return;
    if(!(event.ctrlKey&&event.altKey&&!event.metaKey)||isAltGraph(event))return;
    const menuId=menuKeyMap[event.code];
    if(event.repeat&&(menuId||['KeyP','KeyC','KeyR'].includes(event.code)))return;
    if(menuId){
      if(isEditableKeyboardTarget(target))return;
      event.preventDefault();event.stopPropagation();
      openTopMenu(menuId);
      return;
    }
    if(isEditableKeyboardTarget(target))return;
    switch(event.code){
      case 'KeyP':
        event.preventDefault();event.stopPropagation();
        if(event.shiftKey)focusPanelNavigation();
        else toggleSettingsPanels();
        return;
      case 'KeyC':
        event.preventDefault();event.stopPropagation();
        if($('console_toggle_btn'))$('console_toggle_btn').click();
        return;
      case 'KeyW':
        event.preventDefault();event.stopPropagation();changeConsoleHeight(1);return;
      case 'KeyS':
        event.preventDefault();event.stopPropagation();changeConsoleHeight(-1);return;
      case 'KeyA':
        event.preventDefault();event.stopPropagation();adjustSettingsPanelWidth(1);return;
      case 'KeyD':
        event.preventDefault();event.stopPropagation();adjustSettingsPanelWidth(-1);return;
      case 'KeyR':
        event.preventDefault();event.stopPropagation();
        if($('refresh_vals'))$('refresh_vals').click();
        else showToast('Configuration refresh control is unavailable.');
        return;
    }
  },true);
  document.addEventListener('keyup',syncMnemonicHints,true);
  window.addEventListener('blur',function(){
    const bar=document.querySelector('.app-menubar');if(bar)bar.classList.remove('shortcuts-visible');
  });
  document.addEventListener('visibilitychange',function(){
    if(document.hidden){const bar=document.querySelector('.app-menubar');if(bar)bar.classList.remove('shortcuts-visible');}
  });
}

function buildCommandPalette(){
  const commands=[
    ['Toggle settings panels','toggle-panels','Ctrl+Alt+P','show hide sidebar panel'],
    ['Focus settings panel navigation','focus-panels','Ctrl+Alt+Shift+P','navigate panel menus with arrows space enter'],
    ['Toggle Event Console','toggle-console','Ctrl+Alt+C / Ctrl+Backtick','open close events log console'],
    ['Increase Event Console height','console-grow','Ctrl+Alt+W','grow taller resize up'],
    ['Decrease Event Console height / close at minimum','console-shrink','Ctrl+Alt+S','shrink shorter resize down'],
    ['Widen settings panel','panel-widen','Ctrl+Alt+A','move divider left wider'],
    ['Narrow settings panel','panel-narrow','Ctrl+Alt+D','move divider right narrower'],
    ['Refresh configuration values and advanced settings','refresh-config','Ctrl+Alt+R','refresh config values feed advanced settings'],
    ['Open File menu','menu-file','Ctrl+Alt+F','file menu export import refresh capture exit'],
    ['Open Edit menu','menu-edit','Ctrl+Alt+E','edit menu properties selection'],
    ['Open View menu','menu-view','Ctrl+Alt+V','view menu zoom full screen overlay console panels'],
    ['Open Tools menu','menu-tools','Ctrl+Alt+T','tools select pan freeze live frame'],
    ['Open Help menu','menu-help','Ctrl+Alt+H','help shortcuts guide'],
    ['Select / Edit operational ROI','select','V'],['Pan camera view','pan','H'],['Toggle view lock','view-lock',''],
    ['Keyboard shortcuts','shortcuts','F1'],['Export full configuration','export','Ctrl+Shift+E','download configuration JSON'],
    ['Import full configuration','import','','load configuration JSON'],['Save workspace layout','workspace','Ctrl+S'],
    ['Undo','undo','Ctrl+Z'],['Redo','redo','Ctrl+Y / Ctrl+Shift+Z'],
    ['Fit camera frame','fit','0'],['Zoom in','zoom-in','+'],['Zoom out','zoom-out','−'],
    ['Toggle camera fullscreen','fullscreen','F'],['Toggle ROI overlays','overlays','O'],['Toggle grid','grid','G'],
    ['Toggle crosshair','crosshair','X'],['Use annotation tool','annotate','N'],['Use pixel ruler','ruler','R'],
    ['Show or hide Properties section','properties','','properties inspector'],
    ['Clear selection','clear-selection','','deselect clear current roi'],
    ['Take camera picture','take-picture','','capture still image photograph'],
    ['Exit Stream server','exit-stream','','stop server exit dashboard'],
    ['Freeze camera frame','freeze','','pause live frame'],['Return to live camera','unfreeze','','resume live frame'],
    ['Save workspace profile','profile',''],['Save configuration preset','preset',''],
    ['Capture frame snapshot','snapshot',''],['Refresh runtime diagnostics','health',''],['Refresh server logs','logs',''],
    ['Open encoder map','encoder',''],['Open camera controls','camera',''],
    ['Toggle Robot Motion (RUN_LVL)','toggle-motion','Ctrl+Shift+Space'],
    ['Force Stop (RUN_LVL → STOP)','stop',''],['Resume motion (confirmation)','resume','']
  ];
  const commandList=$('ext_command_list'),settingsList=$('ext_settings_results'),search=$('ext_command_search');
  function renderResults(){
    const query=paletteNormalize(search.value.trim());
    commandList.replaceChildren();settingsList.replaceChildren();
    const matchedCommands=commands.filter(function(entry){return !query||paletteNormalize(entry[0]+' '+entry[2]+' '+(entry[3]||'')).includes(query);});
    matchedCommands.forEach(function(entry){
      const button=document.createElement('button');button.type='button';button.className='palette-command-result';
      const badge=document.createElement('span');badge.className='palette-kind-badge command-kind';badge.textContent='COMMAND';
      const label=document.createElement('span');label.className='palette-result-label';label.textContent=entry[0];
      const shortcut=document.createElement('span');shortcut.className='palette-result-shortcut';shortcut.textContent=entry[2]||'Run';
      const active=document.createElement('span');active.className='palette-active-indicator';active.textContent=isPaletteCommandActive(entry[1])?'✓':'';active.hidden=!isPaletteCommandActive(entry[1]);active.setAttribute('aria-label',active.hidden?'':'Currently active');
      button.append(badge,label,shortcut,active);button.onclick=function(){closeCommandPalette();executeCommand(entry[1]);};commandList.appendChild(button);
    });
    $('ext_command_count').textContent=String(matchedCommands.length);
    if(!query){
      const empty=document.createElement('div');empty.className='palette-empty';empty.textContent='Type a keyword to search setting names, values, and panel options.';settingsList.appendChild(empty);
      $('ext_settings_count').textContent='Search';return;
    }
    const matchedSettings=settingSearchEntries().filter(function(entry){return entry.searchable.includes(query);});
    matchedSettings.sort(function(a,b){
      const aExact=paletteNormalize(a.label).startsWith(query)?0:1,bExact=paletteNormalize(b.label).startsWith(query)?0:1;
      return aExact-bExact||a.label.localeCompare(b.label);
    });
    matchedSettings.slice(0,60).forEach(function(entry){
      const button=document.createElement('button');button.type='button';button.className='palette-setting-result';
      const badge=document.createElement('span');badge.className='palette-kind-badge '+(entry.kind==='PANEL'?'panel-kind':entry.kind==='OPTION'?'option-kind':'setting-kind');badge.textContent=entry.kind;
      const textBox=document.createElement('span');textBox.className='palette-setting-copy';
      const label=document.createElement('span');label.className='palette-result-label';label.textContent=entry.label;
      const crumb=document.createElement('span');crumb.className='palette-setting-crumb';crumb.textContent=entry.panelTitle;
      textBox.append(label,crumb);button.append(badge,textBox);
      button.onclick=function(){navigateToPaletteSetting(entry);};settingsList.appendChild(button);
    });
    if(!matchedSettings.length){
      const empty=document.createElement('div');empty.className='palette-empty';empty.textContent='No matching settings or panel options.';settingsList.appendChild(empty);
    }
    $('ext_settings_count').textContent=String(matchedSettings.length);
  }
  search.oninput=renderResults;window.refreshStreamCommandPalette=renderResults;renderResults();
}
function openCommandPalette(){
  const modal=$('ext_command_palette');modal.style.display='flex';modal.setAttribute('aria-hidden','false');
  $('ext_command_search').value='';$('ext_command_search').focus();$('ext_command_search').dispatchEvent(new Event('input'));
}
function closeCommandPalette(){
  const modal=$('ext_command_palette');modal.style.display='none';modal.setAttribute('aria-hidden','true');
}
function executeCommand(name){
  const actions={
    'toggle-panels':toggleSettingsPanels,'focus-panels':focusPanelNavigation,
    'toggle-console':function(){if($('console_toggle_btn'))$('console_toggle_btn').click();},
    'console-grow':function(){changeConsoleHeight(1);},'console-shrink':function(){changeConsoleHeight(-1);},
    'panel-widen':function(){adjustSettingsPanelWidth(1);},'panel-narrow':function(){adjustSettingsPanelWidth(-1);},
    'refresh-config':function(){if($('refresh_vals'))$('refresh_vals').click();},
    'menu-file':function(){openTopMenu('file');},'menu-edit':function(){openTopMenu('edit');},'menu-view':function(){openTopMenu('view');},'menu-tools':function(){openTopMenu('tools');},'menu-help':function(){openTopMenu('help');},
    'zoom-in':function(){const b=document.querySelector('[data-action="zoom-in"]');if(b)b.click();},
    'zoom-out':function(){const b=document.querySelector('[data-action="zoom-out"]');if(b)b.click();},
    fullscreen:function(){const b=document.querySelector('[data-action="toggle-fullscreen"]');if(b)b.click();},
    properties:function(){const b=document.querySelector('[data-action="properties"]');if(b)b.click();},
    'clear-selection':function(){if($('clear_selection'))$('clear_selection').click();},
    'take-picture':function(){if($('take_picture_btn'))$('take_picture_btn').click();},
    'exit-stream':function(){if(window.openStreamExitDialog)window.openStreamExitDialog();else showToast('Stream exit dialog is unavailable.');},
    freeze:function(){const b=$('freeze_btn');if(b)b.click();},unfreeze:function(){const b=$('unfreeze_btn');if(b)b.click();},
    shortcuts:function(){if(window.openStreamShortcuts)window.openStreamShortcuts();},
    export:exportFullConfig,import:function(){$('ext_config_file').click();},undo:doUndo,redo:doRedo,
    fit:function(){fitWorkspaceView();},overlays:function(){$('ext_overlays').click();},grid:function(){$('ext_grid').click();},crosshair:function(){$('ext_crosshair').click();},
    'view-lock':function(){if(typeof window.setWorkspaceViewLocked==='function')window.setWorkspaceViewLocked(!window.isWorkspaceViewLocked());},
    select:function(){setEditorTool('select');},pan:function(){setEditorTool(editorTool==='pan'?'select':'pan');},
    annotate:function(){setEditorTool(editorTool==='annotate'?'select':'annotate');},ruler:function(){setEditorTool(editorTool==='ruler'?'select':'ruler');},
    snapshot:addFrameSnapshot,workspace:function(){saveWorkspace().then(function(){showToast('Workspace saved');}).catch(function(e){showToast(e.message);});},
    profile:function(){$('ext_editor_panel').open=true;$('ext_profile_name').focus();},
    preset:function(){$('ext_config_panel').open=true;$('ext_preset_name').focus();},
    health:function(){refreshRuntime().then(function(){showToast('Runtime diagnostics refreshed');});},
    logs:refreshServerLogs,
    camera:function(){$('ext_camera_panel').open=true;$('ext_camera_panel').scrollIntoView({behavior:'smooth',block:'nearest'});},
    encoder:function(){if($('ext_encoder_embed').hidden)showToast('Encoder map requires --encoder-map and compatible firmware restart.');else $('ext_encoder_frame').scrollIntoView({behavior:'smooth'});},
    'toggle-motion':toggleMotionSafetyFromKeyboard,
    stop:function(){safetyAction('stop',{skipConfirm:true,source:'command-palette'}).catch(function(e){showToast(e.message);});},
    resume:function(){safetyAction('resume').catch(function(e){showToast(e.message);});}
  };
  if(actions[name])Promise.resolve(actions[name]()).catch(function(err){showToast(err.message||String(err));});
}
function enableReadOnlyState(){
  if(STREAM_CONTROL_ALLOWED)return;
  ['ext_apply_servo_center','ext_export_config','ext_import_config','ext_undo','ext_redo','ext_preset_save','ext_preset_apply','ext_preset_delete','ext_history_restore','ext_profile_save','ext_profile_delete','ext_apply_fps','ext_apply_camera','ext_sign_requests_pause','ext_sign_requests_resume','ext_software_stop','ext_software_resume','ext_save_workspace'].forEach(function(id){if($(id))$(id).disabled=true;});
}
function initializeResize(){
  const container=document.querySelector('.container'),panel=document.querySelector('.right-panel'),handle=$('panel_resize_handle');
  if(!container||!panel||!handle)return;
  let active=false,startX=0,startWidth=315;
  function limits(){
    const minimum=250;
    const maximum=Math.max(minimum,Math.min(700,window.innerWidth-360));
    return {minimum:minimum,maximum:maximum};
  }
  function announceWidth(width){
    const bounds=limits();
    handle.setAttribute('aria-valuemin',String(bounds.minimum));
    handle.setAttribute('aria-valuemax',String(bounds.maximum));
    handle.setAttribute('aria-valuenow',String(Math.round(width)));
    handle.setAttribute('aria-valuetext',Math.round(width)+' pixels wide');
  }
  function setWidth(requested){
    const bounds=limits();
    const width=Math.round(Math.min(bounds.maximum,Math.max(bounds.minimum,Number(requested)||315)));
    container.style.setProperty('--right-pane-width',width+'px');
    announceWidth(width);
  }
  function finishResize(){
    if(!active)return;
    active=false;
    container.classList.remove('panel-resizing');
    scheduleWorkspaceSave();
  }
  handle.addEventListener('pointerdown',function(event){
    if(window.innerWidth<721||(event.button!==0&&event.pointerType!=='touch'))return;
    active=true;
    startX=event.clientX;
    startWidth=parseFloat(getComputedStyle(container).getPropertyValue('--right-pane-width'))||panel.getBoundingClientRect().width;
    container.classList.add('panel-resizing');
    handle.setPointerCapture(event.pointerId);
    event.preventDefault();
  });
  handle.addEventListener('pointermove',function(event){
    if(!active)return;
    setWidth(startWidth-(event.clientX-startX));
  });
  handle.addEventListener('pointerup',finishResize);
  handle.addEventListener('pointercancel',finishResize);
  handle.addEventListener('keydown',function(event){
    if(window.innerWidth<721)return;
    const bounds=limits();
    const current=parseFloat(getComputedStyle(container).getPropertyValue('--right-pane-width'))||panel.getBoundingClientRect().width;
    if(event.key==='ArrowLeft'){event.preventDefault();setWidth(current+24);scheduleWorkspaceSave();}
    else if(event.key==='ArrowRight'){event.preventDefault();setWidth(current-24);scheduleWorkspaceSave();}
    else if(event.key==='Home'){event.preventDefault();setWidth(bounds.minimum);scheduleWorkspaceSave();}
    else if(event.key==='End'){event.preventDefault();setWidth(bounds.maximum);scheduleWorkspaceSave();}
  });
  window.addEventListener('resize',function(){
    if(window.innerWidth<721)return;
    const saved=parseFloat(getComputedStyle(container).getPropertyValue('--right-pane-width'));
    if(Number.isFinite(saved))setWidth(saved);
    else announceWidth(panel.getBoundingClientRect().width);
  });
  announceWidth(parseFloat(getComputedStyle(container).getPropertyValue('--right-pane-width'))||panel.getBoundingClientRect().width);
}
function initializeConsoleResize(){
  const consoleDock=$('bottom_console'),handle=$('console_resize_handle'),toggle=$('console_toggle_btn');
  if(!consoleDock||!handle||!toggle)return;
  let active=false,startY=0,startHeight=178,lastExpandedHeight=178;
  function limits(){
    const mobile=window.matchMedia('(max-width: 720px)').matches;
    const shortLandscape=window.matchMedia('(max-width: 900px) and (orientation: landscape) and (max-height: 520px)').matches;
    const minimum=mobile?84:96;
    const maximum=Math.max(minimum,Math.min(
      shortLandscape?200:(mobile?360:520),
      window.innerHeight*(shortLandscape?0.42:(mobile?0.55:0.62)),
      window.innerHeight-(mobile?80:120)
    ));
    return {minimum:minimum,maximum:maximum,mobile:mobile};
  }
  function closedHeight(bounds){return bounds.mobile?38:42;}
  function isOpen(){return consoleDock.classList.contains('console-open');}
  function toggleOpen(open){
    if(isOpen()!==open)toggle.click();
  }
  function announceSize(height){
    const bounds=limits(),closed=closedHeight(bounds),open=isOpen();
    handle.setAttribute('aria-valuemin',String(closed));
    handle.setAttribute('aria-valuemax',String(Math.round(bounds.maximum)));
    handle.setAttribute('aria-valuenow',String(Math.round(open?Math.max(closed,Math.min(bounds.maximum,height)):closed)));
    handle.setAttribute('aria-valuetext',open?Math.round(height)+' pixels tall':'Closed. Drag upward to open and downward to close.');
  }
  function setHeight(requested,allowCollapsedRange){
    const bounds=limits(),closed=closedHeight(bounds);
    const minimum=allowCollapsedRange?closed:bounds.minimum;
    const numeric=Number(requested);
    const finite=Number.isFinite(numeric)?numeric:bounds.minimum;
    const height=Math.round(Math.min(bounds.maximum,Math.max(minimum,finite)));
    consoleDock.style.setProperty('--console-resize-height',height+'px');
    if(height>=bounds.minimum)lastExpandedHeight=height;
    announceSize(height);
    return height;
  }
  function finishResize(){
    if(!active)return;
    const bounds=limits(),height=consoleDock.getBoundingClientRect().height;
    if(isOpen()&&height<bounds.minimum){
      /* Closing by drag shouldn't poison the remembered expanded height. */
      consoleDock.style.setProperty('--console-resize-height',Math.max(bounds.minimum,lastExpandedHeight)+'px');
      toggleOpen(false);
    }else if(isOpen()){
      setHeight(height,false);
    }else{
      consoleDock.style.setProperty('--console-resize-height',Math.max(bounds.minimum,lastExpandedHeight)+'px');
    }
    active=false;
    consoleDock.classList.remove('console-resizing');
    announceSize(consoleDock.getBoundingClientRect().height);
  }
  handle.addEventListener('pointerdown',function(event){
    if(event.button!==0&&event.pointerType!=='touch')return;
    const bounds=limits();
    active=true;
    startY=event.clientY;
    startHeight=consoleDock.getBoundingClientRect().height;
    lastExpandedHeight=isOpen()?Math.max(bounds.minimum,startHeight):Math.max(bounds.minimum,parseFloat(consoleDock.style.getPropertyValue('--console-resize-height'))||178);
    consoleDock.classList.add('console-resizing');
    try{handle.setPointerCapture(event.pointerId);}catch(_error){}
    event.preventDefault();
  });
  handle.addEventListener('pointermove',function(event){
    if(!active)return;
    const bounds=limits(),closed=closedHeight(bounds);
    const requested=startHeight-(event.clientY-startY);
    if(requested<=closed){
      /* Dragging down past the collapsed height closes the console. */
      consoleDock.style.setProperty('--console-resize-height',Math.max(bounds.minimum,lastExpandedHeight)+'px');
      toggleOpen(false);
      announceSize(closed);
      return;
    }
    /* The same grip expands upward and collapses downward, continuously. */
    const height=setHeight(requested,true);
    toggleOpen(true);
    if(height>=bounds.minimum)lastExpandedHeight=height;
    announceSize(height);
  });
  handle.addEventListener('pointerup',finishResize);
  handle.addEventListener('pointercancel',finishResize);
  handle.addEventListener('keydown',function(event){
    const bounds=limits(),closed=closedHeight(bounds),current=consoleDock.getBoundingClientRect().height;
    if(event.key==='ArrowUp'){
      event.preventDefault();
      if(!isOpen()){setHeight(bounds.minimum,false);toggleOpen(true);}
      else setHeight(current+24,false);
    }else if(event.key==='ArrowDown'){
      event.preventDefault();
      if(isOpen()&&current<=bounds.minimum+24){
        consoleDock.style.setProperty('--console-resize-height',Math.max(bounds.minimum,lastExpandedHeight)+'px');
        toggleOpen(false);
      }else if(isOpen())setHeight(current-24,false);
    }else if(event.key==='Home'){
      event.preventDefault();
      if(isOpen())setHeight(bounds.minimum,false);
      else announceSize(closed);
    }else if(event.key==='End'){
      event.preventDefault();
      setHeight(bounds.maximum,false);
      toggleOpen(true);
    }
  });
  window.addEventListener('resize',function(){
    const bounds=limits();
    if(!isOpen()){announceSize(closedHeight(bounds));return;}
    const saved=parseFloat(consoleDock.style.getPropertyValue('--console-resize-height'));
    if(Number.isFinite(saved))setHeight(saved,false);
    else announceSize(consoleDock.getBoundingClientRect().height);
  });
  const saved=parseFloat(consoleDock.style.getPropertyValue('--console-resize-height'));
  if(Number.isFinite(saved)&&saved>=limits().minimum)lastExpandedHeight=saved;
  announceSize(consoleDock.getBoundingClientRect().height);
}
function installCoordinatePairPaste(){
  ['prop_left','prop_top','prop_right','prop_bottom','prop_point_x','prop_point_y'].forEach(function(id){
    const field=$(id);if(!field)return;
    field.addEventListener('paste',function(event){
      const transfer=event.clipboardData||window.clipboardData;
      const text=transfer&&transfer.getData?transfer.getData('text'):'';
      const match=String(text||'').match(/^\s*(-?(?:\d+\.?\d*|\.\d+))\s*[,;\s]\s*(-?(?:\d+\.?\d*|\.\d+))\s*$/);
      if(!match)return;
      const a=Number(match[1]),b=Number(match[2]);if(!Number.isFinite(a)||!Number.isFinite(b))return;
      const target=$('prop_target')?$('prop_target').value:'NONE';
      let ids=[];
      if(['RL','LL','CW','ST','OBJ'].includes(target)){
        if(a<0||a>1||b<0||b>1){showToast('ROI coordinates must be between 0 and 1.');event.preventDefault();return;}
        if(['prop_left','prop_top'].includes(id))ids=['prop_left','prop_top'];
        else if(['prop_right','prop_bottom'].includes(id))ids=['prop_right','prop_bottom'];
        else return;
      }else if(target.startsWith('BEV_')&&['prop_point_x','prop_point_y'].includes(id)){
        if(a< -5||a>5||b< -5||b>5){showToast('BEV coordinates must be between -5 and 5.');event.preventDefault();return;}
        ids=['prop_point_x','prop_point_y'];
      }else return;
      event.preventDefault();
      $(ids[0]).value=a.toFixed(3);$(ids[1]).value=b.toFixed(3);
      const hint=$('prop_hint');if(hint)hint.textContent='Point pasted as U/X='+a.toFixed(3)+', V/Y='+b.toFixed(3)+'. Click Apply to save this ROI corner.';
      updateEditorStatus('Coordinate pair pasted into '+ids.join(' and ')+'. Click Apply to save.');
      showToast('Pasted coordinate pair into '+(ids[0]==='prop_left'?'ROI first corner':ids[0]==='prop_right'?'ROI second corner':'BEV point')+'. Click Apply.');
    });
  });
}

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
async function openManeuverConfigDialog(){
  try{
    const fresh=await readConfig();currentConfig=jsonClone(fresh);
    const a=fresh.advanced||{};
    [
      ['maneuver_obstacle_left','OBSTACLE_LANE_LEFT_SEQUENCE'],
      ['maneuver_obstacle_right','OBSTACLE_LANE_RIGHT_SEQUENCE'],
      ['maneuver_city_right','CITY_CROSSWALK_TURN_RIGHT_SEQUENCE'],
      ['maneuver_city_left','CITY_CROSSWALK_TURN_LEFT_SEQUENCE'],
      ['maneuver_city_straight','CITY_CROSSWALK_STRAIGHT_SEQUENCE'],
      ['maneuver_crosswalk_vertical_min','CROSSWALK_VERTICAL_MIN_LINES'],
      ['maneuver_crosswalk_horizontal_min','CROSSWALK_HORIZONTAL_MIN_LINES']
    ].forEach(function(pair){const input=$(pair[0]);if(input&&a[pair[1]]!=null)input.value=String(a[pair[1]]);});
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
  if(isCity)required.push(
    ['maneuver_city_right','CITY_CROSSWALK_TURN_RIGHT_SEQUENCE'],
    ['maneuver_city_left','CITY_CROSSWALK_TURN_LEFT_SEQUENCE'],
    ['maneuver_city_straight','CITY_CROSSWALK_STRAIGHT_SEQUENCE']
  );
  required.forEach(function(pair){
    const input=$(pair[0]);if(!input)return;
    if(!input.value.trim())throw new Error(pair[1]+' cannot be empty.');
    body.advanced[pair[1]]=input.value.trim();
  });
  if(isCity){
    [['maneuver_crosswalk_vertical_min','CROSSWALK_VERTICAL_MIN_LINES'],['maneuver_crosswalk_horizontal_min','CROSSWALK_HORIZONTAL_MIN_LINES']].forEach(function(pair){
      const value=Number($(pair[0]).value);
      if(!Number.isInteger(value)||value<1||value>1000)throw new Error(pair[1]+' must be an integer from 1 to 1000.');
      body.advanced[pair[1]]=value;
    });
  }
  await applyFullConfig(body,isCity?'Updated City maneuvers and crosswalk thresholds':'Updated Race obstacle sequences',true);
  setConfigDialogOpen('ext_maneuver_settings_dialog',false);
  showToast(isCity?'Saved to city.json. Arduino startup lane sequences are sent at the next robot initialization.':'Saved to race.json. Arduino startup lane sequences are sent at the next robot initialization.');
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
    canvas.addEventListener('pointermove',function(e){const point=pointFromEvent(e);extCrosshairPoint=point?{x:point.x,y:point.y}:null;rulerHoverPoint=(editorTool==='ruler'&&rulerStart&&point)?point:null;if(extCrosshair||(editorTool==='ruler'&&rulerStart))drawPrecisionOverlay();});
  }
  if($('ext_export_annotations'))$('ext_export_annotations').onclick=function(){downloadText(JSON.stringify(extAnnotations,null,2),'roboy-annotations.json','application/json');};
  $('ext_grid').addEventListener('change',function(){gridMode=this.checked?(gridMode==='dots'?'dots':'grid'):'off';extGrid=gridMode!=='off';drawPrecisionOverlay();scheduleWorkspaceSave();});
  $('roi_settings_open').addEventListener('click',openEditorSettings);$('roi_settings_close').addEventListener('click',()=>closeEditorSettings(true));$('roi_settings_cancel').addEventListener('click',()=>closeEditorSettings(true));
  $('roi_settings_apply').addEventListener('click',async()=>{const qualityInput=$('roi_setting_jpeg_quality');const requestedQuality=qualityInput?Number(qualityInput.value):streamJpegQuality;try{if(requestedQuality!==streamJpegQuality||streamQualityDraftDirty){if(!STREAM_CONTROL_ALLOWED)throw new Error('Stream controls are disabled; JPEG quality was not changed.');const response=await nativeFetch('/api/stream/quality',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({quality:requestedQuality})});const data=await response.json().catch(()=>({}));if(!response.ok)throw new Error(data.message||('HTTP '+response.status));streamJpegQuality=Number(data.quality);}previewEditorSettings();scheduleWorkspaceSave();closeEditorSettings(false);showToast('Editor settings applied'+(requestedQuality!==85?' · JPEG quality '+streamJpegQuality:''));}catch(error){showToast('Could not apply JPEG quality: '+(error&&error.message?error.message:'request failed'));}});$('roi_settings_reset').addEventListener('click',resetEditorSettingsDraft);
  const settingsModalElement=$('roi_settings_dialog');settingsModalElement.addEventListener('click',e=>{if(e.target===settingsModalElement)closeEditorSettings(true);});settingsModalElement.querySelectorAll('input,select').forEach(el=>['input','change'].forEach(evt=>el.addEventListener(evt,previewEditorSettings)));
  const jpegQualityInput=$('roi_setting_jpeg_quality');
  if(jpegQualityInput)jpegQualityInput.addEventListener('input',function(){streamQualityDraftDirty=true;const label=$('roi_setting_jpeg_quality_value');if(label)label.textContent=this.value+' / 100';});
  $('ext_snap').addEventListener('change',function(){extSnap=this.checked;scheduleWorkspaceSave();});
  $('ext_crosshair').addEventListener('change',function(){extCrosshair=this.checked;if(canvas)canvas.classList.toggle('crosshair-active',extCrosshair);drawPrecisionOverlay();scheduleWorkspaceSave();if(extCrosshair)updateEditorStatus('Crosshair active: click a point inside the camera image to copy normalized U, V coordinates.');});
  $('ext_overlays').addEventListener('change',function(){showRectsCheckbox.checked=this.checked;if(typeof window.syncStreamOverlayControlUI==='function')window.syncStreamOverlayControlUI();renderWorkspaceCanvas();scheduleWorkspaceSave();});
  showRectsCheckbox.addEventListener('change',function(){if($('ext_overlays'))$('ext_overlays').checked=this.checked;if(typeof window.syncStreamOverlayControlUI==='function')window.syncStreamOverlayControlUI();});
  $('ext_annotate_btn').onclick=function(){setEditorTool(editorTool==='annotate'?'select':'annotate');};
  $('ext_ruler').addEventListener('change',function(){setEditorTool(this.checked?'ruler':'select');});
  $('ext_clear_annotations').onclick=function(){if(!extAnnotations.length)return;if(confirm('Clear all notes and ruler measurements from the workspace?')){extAnnotations=[];refreshAnnotationList();syncLayerControls();drawPrecisionOverlay();scheduleWorkspaceSave();}};
  $('ext_save_workspace').onclick=function(){saveWorkspace().then(function(){showToast('Workspace layout saved');}).catch(function(err){showToast(err.message);});};
  $('ext_capture_frame').onclick=addFrameSnapshot;$('ext_clear_gallery').onclick=function(){extFrameGallery=[];renderFrameGallery();};
  $('ext_profile_save').onclick=function(){profileAction('save').catch(function(e){showToast(e.message);});};$('ext_profile_load').onclick=function(){profileAction('load').catch(function(e){showToast(e.message);});};$('ext_profile_delete').onclick=function(){profileAction('delete').catch(function(e){showToast(e.message);});};
  $('ext_export_config').onclick=function(){exportFullConfig().catch(function(e){showToast(e.message);});};
  $('ext_import_config').onclick=function(){$('ext_config_file').click();};$('ext_config_file').addEventListener('change',function(){if(this.files&&this.files[0])importFullConfigFile(this.files[0]);this.value='';});
  $('ext_undo').onclick=doUndo;$('ext_redo').onclick=doRedo;
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
  $('ext_maneuver_settings_open').onclick=function(){openManeuverConfigDialog();};
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
  document.addEventListener('keydown',function(e){if(e.key==='Escape'&&$('ext_stream_exit_dialog').classList.contains('is-open')){e.preventDefault();closeStreamExitDialog();}});
  $('active_tool_cancel').onclick=function(){setEditorTool('select');};
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
    if($('ext_command_palette').style.display==='flex'&&e.code==='Escape'){closeCommandPalette();return;}
    if(e.target&&(['INPUT','SELECT','TEXTAREA'].includes(e.target.tagName)||e.target.isContentEditable))return;
    if(e.code==='Escape'&&editorTool!=='select'&&!$('roi_settings_dialog').classList.contains('is-open')){e.preventDefault();setEditorTool('select');return;}
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
