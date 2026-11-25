
(function(){
'use strict';
const $ = function(id){return document.getElementById(id)};
const jsonClone = function(value){return JSON.parse(JSON.stringify(value));};
const EXT_LAYERS = ['RL','LL','CW','ST','OBJ','BEV'];
let extGrid=false, extSnap=false, extCrosshair=false, crosshairPinned=false, extAnnotationsVisible=true, extCrosshairPoint=null;
let mmPerSourcePixel=0;
let lastVisibleGridMode='grid';
let gridColor='#69bed2', keyboardNudgePx=5, streamFps=8.3, streamJpegQuality=85, streamQualityDraftDirty=false;
window.__isEditorSnapEnabled=()=>extSnap;
window.__getStreamKeyboardNudgePx=()=>keyboardNudgePx;
let editorTool='select', rulerStart=null, rulerHoverPoint=null, internalWorkspaceToolSync=false, extAnnotations=[], extFrameGallery=[], extRuntimeSample=[];
let undoStack=[], redoStack=[], currentConfig=null, internalConfigWrite=0, extSaveTimer=null, extHealthTimer=null, extSettingsTimer=null;
let workspaceSaveChain=Promise.resolve();
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
function formatRulerDistance(px,space){
 const d=Math.max(0,Number(px)||0);
 if(space==='image'&&mmPerSourcePixel>0){const mm=d*mmPerSourcePixel;if(mm>=1000)return(mm/1000).toFixed(3)+' m';if(mm>=10)return(mm/10).toFixed(2)+' cm';return mm.toFixed(2)+' mm';}
 return d.toFixed(1)+(space==='canvas'?' canvas px':' px');
}
function rulerDistance(a,b){
 if(a.space==='image'&&b.space==='image')return Math.hypot((b.u-a.u)*(frameSourceWidth||canvas.width),(b.v-a.v)*(frameSourceHeight||canvas.height));
 return Math.hypot((b.canvasU-a.canvasU)*canvas.width,(b.canvasV-a.canvasV)*canvas.height);
}
function snapshotRulerPoint(point){
 if(!point)return null;
 return Object.freeze({space:point.space==='canvas'?'canvas':'image',u:Number(point.u),v:Number(point.v),canvasU:Number(point.canvasU),canvasV:Number(point.canvasV),x:Number(point.x),y:Number(point.y)});
}
function rulerPointCanvasXY(point,b){
 if(point.space==='image')return{x:b.ix+point.u*b.iw,y:b.iy+point.v*b.ih,space:point.space,u:point.u,v:point.v,canvasU:point.canvasU,canvasV:point.canvasV};
 return{x:point.canvasU*canvas.width,y:point.canvasV*canvas.height,space:point.space,u:point.u,v:point.v,canvasU:point.canvasU,canvasV:point.canvasV};
}
function annotationXY(item,b){const u=Number(item.u)||0,v=Number(item.v)||0;return item.space==='canvas'?{x:u*canvas.width,y:v*canvas.height}:{x:b.ix+u*b.iw,y:b.iy+v*b.ih};}
function crosshairCanvasPoint(point,b){if(!point)return null;if(point.space==='image'&&Number.isFinite(Number(point.u))&&Number.isFinite(Number(point.v)))return{x:b.ix+Number(point.u)*b.iw,y:b.iy+Number(point.v)*b.ih};if(point.space==='canvas'&&Number.isFinite(Number(point.u))&&Number.isFinite(Number(point.v)))return{x:Number(point.u)*canvas.width,y:Number(point.v)*canvas.height};return{x:Number(point.x)||0,y:Number(point.y)||0};}
function drawPrecisionOverlay(){
 const svg=$('ext_precision_overlay'),stage=$('canvas_stage');if(!svg||!canvas||!stage)return;
 const z=getOverlayScale(),cr=canvas.getBoundingClientRect(),sr=stage.getBoundingClientRect(),left=sr.left+stage.clientLeft,top=sr.top+stage.clientTop;
 svg.style.left=(cr.left-left)+'px';svg.style.top=(cr.top-top)+'px';svg.style.width=Math.max(1,cr.width)+'px';svg.style.height=Math.max(1,cr.height)+'px';
 svg.setAttribute('viewBox','0 0 '+canvas.width+' '+canvas.height);svg.replaceChildren();
 const b=extImageBounds(),visibleGrid=gridMode!=='off'&&extGrid;
 if(visibleGrid){
  // Grid coordinates belong to the image plane. Zoom changes pitch; pan moves its origin.
  const baseStep=Math.max(.001,Math.max(.025,Math.min(.25,Number(gridSpacing)||.05))*b.ih);
  // At low zoom skip whole lattice intervals rather than shifting the grid or rendering thousands of dots.
  const minScreenPitch=gridMode==='dots'?8:10,stride=Math.max(1,Math.ceil(minScreenPitch/baseStep)),step=baseStep*stride;
  const stroke=/^#[0-9a-f]{6}$/i.test(gridColor)?gridColor:'#69bed2',alpha=Math.max(.05,Math.min(1,Number(gridOpacity)||.35));
  const firstColumn=Math.floor((0-b.ix)/step),lastColumn=Math.ceil((canvas.width-b.ix)/step);
  const firstRow=Math.floor((0-b.iy)/step),lastRow=Math.ceil((canvas.height-b.iy)/step);
  if(gridMode==='dots'){
   // Dot radius is screen-stable; dot coordinates and pitch follow image zoom.
   const radius=Math.max(.6,Math.min(24,(Number(gridDotSize)||2)*z));
   for(let i=firstColumn;i<=lastColumn;i++){const x=b.ix+i*step;if(x<0||x>canvas.width)continue;for(let j=firstRow;j<=lastRow;j++){const y=b.iy+j*step;if(y>=0&&y<=canvas.height)addSVG('circle',{cx:x,cy:y,r:radius,fill:stroke,'fill-opacity':alpha});}}
  }else{
   // Keep grid strokes legible while line positions scale with the frame.
   for(let i=firstColumn;i<=lastColumn;i++){const x=b.ix+i*step;if(x>=0&&x<=canvas.width)addSVG('line',{x1:x,y1:0,x2:x,y2:canvas.height,stroke:stroke,'stroke-opacity':alpha,'stroke-width':Math.max(.4,Number(gridThickness)||1)});}
   for(let j=firstRow;j<=lastRow;j++){const y=b.iy+j*step;if(y>=0&&y<=canvas.height)addSVG('line',{x1:0,y1:y,x2:canvas.width,y2:y,stroke:stroke,'stroke-opacity':alpha,'stroke-width':Math.max(.4,Number(gridThickness)||1)});}
  }
  addSVG('rect',{x:b.ix,y:b.iy,width:b.iw,height:b.ih,fill:'none',stroke:stroke,'stroke-opacity':alpha,'stroke-width':Math.max(.5,Number(gridThickness)||1)});
 }
 if(extCrosshairPoint&&(extCrosshair||crosshairPinned)){
  const cp=crosshairCanvasPoint(extCrosshairPoint,b);
  addSVG('line',{x1:0,y1:cp.y,x2:canvas.width,y2:cp.y,stroke:'#f8fafc','stroke-width':z,'stroke-dasharray':(6*z)+' '+(4*z)});
  addSVG('line',{x1:cp.x,y1:0,x2:cp.x,y2:canvas.height,stroke:'#f8fafc','stroke-width':z,'stroke-dasharray':(6*z)+' '+(4*z)});
  const inside=cp.x>=b.ix&&cp.x<=b.ix+b.iw&&cp.y>=b.iy&&cp.y<=b.iy+b.ih;
  const textLabel=extCrosshairPoint.space==='image'?'Image X '+Math.round(Number(extCrosshairPoint.u)*(frameSourceWidth||canvas.width))+' · Y '+Math.round(Number(extCrosshairPoint.v)*(frameSourceHeight||canvas.height))+' px':'Canvas X '+Math.round(cp.x)+' · Y '+Math.round(cp.y)+' px · Z=0 editor plane';
  const label=addSVG('text',{x:Math.max(4,Math.min(canvas.width-240,cp.x+8*z)),y:Math.max(14,Math.min(canvas.height-4,cp.y-8*z)),fill:'#fff','font-size':Math.max(9,11*z),'paint-order':'stroke','stroke':'#07101a','stroke-width':3*z});label.textContent=textLabel;
 }
 if(editorTool==='ruler'&&rulerStart&&rulerHoverPoint){
  const a=rulerPointCanvasXY(rulerStart,b),c=rulerPointCanvasXY(rulerHoverPoint,b);addSVG('line',{x1:a.x,y1:a.y,x2:c.x,y2:c.y,stroke:'#22d3ee','stroke-width':Math.max(1,2*z),'stroke-dasharray':(6*z)+' '+(3*z)});
  addSVG('circle',{cx:a.x,cy:a.y,r:Math.max(3,(Number(roiAppearance.handleSize)||10)*.45*z),fill:'#22d3ee',stroke:'#e0faff','stroke-width':z});addSVG('circle',{cx:c.x,cy:c.y,r:Math.max(3,(Number(roiAppearance.handleSize)||10)*.45*z),fill:'#22d3ee',stroke:'#e0faff','stroke-width':z});
  const label=addSVG('text',{x:(a.x+c.x)/2+7*z,y:(a.y+c.y)/2-7*z,fill:'#e0faff','font-size':Math.max(10,(Number(roiAppearance.labelFontSize)||12)*z),'font-weight':'700','paint-order':'stroke',stroke:'#07101a','stroke-width':3*z});
  label.textContent=formatRulerDistance(rulerDistance(a,c),a.space==='image'&&c.space==='image'?'image':'canvas');
 }
 if(!extAnnotationsVisible)return;
 const outline=Math.max(.5,Number(roiAppearance.outlineThickness)||2),font=Math.max(6,Number(roiAppearance.labelFontSize)||12),handle=Math.max(4,Number(roiAppearance.handleSize)||10),weight=String(roiAppearance.labelFontWeight||'700');
 extAnnotations.forEach(item=>{
  if(['roi','roi_rect','roi_trapezoid'].includes(item.kind))return;const color=item.color||'#fbbf24',p=annotationXY(item,b),x=p.x,y=p.y;
  if(item.kind==='ruler'&&item.u2!=null&&item.v2!=null){
   const q=annotationXY({u:item.u2,v:item.v2,space:item.space},b);
   addSVG('line',{x1:x,y1:y,x2:q.x,y2:q.y,stroke:color,'stroke-width':outline*z});addSVG('circle',{cx:x,cy:y,r:handle*.35*z,fill:color});addSVG('circle',{cx:q.x,cy:q.y,r:handle*.35*z,fill:color});
   const dist=item.space==='canvas'?Math.hypot((item.u2-item.u)*canvas.width,(item.v2-item.v)*canvas.height):Math.hypot((item.u2-item.u)*(frameSourceWidth||canvas.width),(item.v2-item.v)*(frameSourceHeight||canvas.height));
   const label=addSVG('text',{x:(x+q.x)/2+5*z,y:(y+q.y)/2-5*z,fill:color,'font-size':font*z,'font-weight':weight,'paint-order':'stroke',stroke:'#07101a','stroke-width':1.5*outline*z});label.textContent=formatRulerDistance(dist,item.space==='canvas'?'canvas':'image');
  }else{
   addSVG('circle',{cx:x,cy:y,r:handle*.6*z,fill:'rgba(251,191,36,.2)',stroke:color,'stroke-width':outline*z});addSVG('line',{x1:x-handle*z,y1:y,x2:x+handle*z,y2:y,stroke:color,'stroke-width':outline*z});addSVG('line',{x1:x,y1:y-handle*z,x2:x,y2:y+handle*z,stroke:color,'stroke-width':outline*z});
   if(item.label){const label=addSVG('text',{x:x+handle*z,y:y-.8*font*z,fill:color,'font-size':font*z,'font-weight':weight,'paint-order':'stroke',stroke:'#07101a','stroke-width':1.5*outline*z});label.textContent=item.label;}
  }
 });
}


window.drawPrecisionOverlay=drawPrecisionOverlay;
function updateEditorStatus(text){if($('ext_editor_status'))$('ext_editor_status').textContent=text;}
function updateActiveToolBanner(){
  const banner=$('active_tool_banner'),label=$('active_tool_label');if(!banner||!label)return;
  const pinned=!!(crosshairPinned&&extCrosshairPoint),crosshairActive=!!extCrosshair;
  const active=editorTool!=='select'||crosshairActive||pinned;
  banner.hidden=!active;
  if(!active)return;
  if(crosshairActive){
    label.textContent=pinned?'Crosshair mode is active · point pinned; click another point to reposition · Esc to exit':'Crosshair mode is active · move to inspect coordinates, click to pin/copy · Esc to exit';
    return;
  }
  if(pinned){
    label.textContent='Crosshair point pinned · Esc to clear';
    return;
  }
  const messages={
    pan:'Pan mode is active · drag the camera to move the view · Esc to exit',
    annotate:'Note / marker mode is active · click the image to place an annotation · Esc to exit',
    ruler:rulerStart?'Ruler mode is active · move to preview the distance, click again to finish · Esc to exit':'Ruler mode is active · click two points to measure distance · Esc to exit'
  };
  label.textContent=messages[editorTool]||('Tool mode: '+editorTool);
}
function persistCrosshairWorkspaceNow(){
  persistWorkspaceImmediately().catch(function(err){if(typeof recordApiEvent==='function')recordApiEvent('warn','Could not persist Crosshair state: '+err.message);showToast('Crosshair state could not be saved: '+err.message);});
}
function exitActiveTools(){
  const hadCrosshair=!!(extCrosshair||crosshairPinned||extCrosshairPoint);
  if(editorTool!=='select')setEditorTool('select',true,false);
  extCrosshair=false;crosshairPinned=false;extCrosshairPoint=null;
  if($('ext_crosshair'))$('ext_crosshair').checked=false;
  if(canvas)canvas.classList.remove('crosshair-active');
  updateActiveToolBanner();drawPrecisionOverlay();
  updateEditorStatus(hadCrosshair?'Crosshair cleared. Press X to enable it again.':'Select / Edit ROI mode active.');
  persistCrosshairWorkspaceNow();
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
 const r=canvas.getBoundingClientRect();if(!r.width||!r.height)return null;
 let x=(event.clientX-r.left)*(canvas.width/r.width),y=(event.clientY-r.top)*(canvas.height/r.height),b=extImageBounds();
 const pointerInsideImage=x>=b.ix&&x<=b.ix+b.iw&&y>=b.iy&&y<=b.iy+b.ih;
 if(pointerInsideImage&&extSnap){const step=Math.max(8,(Number(gridSpacing)||.05)*b.ih);x=b.ix+Math.round((x-b.ix)/step)*step;y=b.iy+Math.round((y-b.iy)/step)*step;x=Math.max(b.ix,Math.min(b.ix+b.iw,x));y=Math.max(b.iy,Math.min(b.iy+b.ih,y));}
 const canvasU=x/Math.max(1,canvas.width),canvasV=y/Math.max(1,canvas.height),u=(x-b.ix)/Math.max(1,b.iw),v=(y-b.iy)/Math.max(1,b.ih);
 const sourceWidth=Number(frameSourceWidth)||Number(lastFrameImage&&lastFrameImage.naturalWidth)||canvas.width,sourceHeight=Number(frameSourceHeight)||Number(lastFrameImage&&lastFrameImage.naturalHeight)||canvas.height;
 return{x:x,y:y,u:u,v:v,canvasX:x,canvasY:y,canvasU:canvasU,canvasV:canvasV,space:'image',sourceX:Math.round(u*sourceWidth),sourceY:Math.round(v*sourceHeight)};
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
function currentEditorSettings(){return{gridMode,gridSpacing,gridOpacity,gridThickness,gridDotSize,gridColor,keyboardNudgePx,streamFps,snap:extSnap,roiAppearance:{labelFontSize:roiAppearance.labelFontSize,labelFontWeight:String(roiAppearance.labelFontWeight),outlineThickness:roiAppearance.outlineThickness,handleSize:roiAppearance.handleSize,showShapeType:!!roiAppearance.showShapeType}};}
function syncSettingsFormControls(a){$('roi_setting_grid_mode').value=a.gridMode;$('roi_setting_grid_spacing').value=String(a.gridSpacing);$('roi_setting_grid_spacing_value').textContent=Number((a.gridSpacing*100).toFixed(1))+'% of frame height';$('roi_setting_grid_color').value=a.gridColor||'#69bed2';$('roi_setting_stream_fps').value=String(a.streamFps||8.3);$('roi_setting_stream_fps_value').textContent=Number(a.streamFps||8.3).toFixed(1)+' FPS target';$('roi_setting_grid_opacity').value=String(a.gridOpacity);$('roi_setting_grid_thickness').value=String(a.gridThickness);$('roi_setting_grid_dot_size').value=String(a.gridDotSize);$('roi_setting_keyboard_nudge').value=String(a.keyboardNudgePx||5);$('roi_setting_snap').checked=!!a.snap;$('roi_setting_label_size').value=String(a.roiAppearance.labelFontSize);$('roi_setting_label_size_value').textContent=a.roiAppearance.labelFontSize+' px at 100%';$('roi_setting_label_weight').value=String(a.roiAppearance.labelFontWeight);$('roi_setting_label_shape').checked=!!a.roiAppearance.showShapeType;$('roi_setting_outline_thickness').value=String(a.roiAppearance.outlineThickness);$('roi_setting_handle_size').value=String(a.roiAppearance.handleSize);}
function applyEditorSettings(a,redraw=true){if(gridMode==='grid'||gridMode==='dots')lastVisibleGridMode=gridMode;gridMode=['off','grid','dots'].includes(a.gridMode)?a.gridMode:'off';if(gridMode==='grid'||gridMode==='dots')lastVisibleGridMode=gridMode;gridSpacing=Math.max(.025,Math.min(.25,Number(a.gridSpacing)||.05));gridColor=/^#[0-9a-f]{6}$/i.test(String(a.gridColor||''))?String(a.gridColor).toLowerCase():'#69bed2';streamFps=Math.max(1,Math.min(30,Math.round((Number(a.streamFps)||8.3)*10)/10));if(typeof window.setStreamDisplayFps==='function')window.setStreamDisplayFps(streamFps);gridOpacity=Math.max(.05,Math.min(1,Number(a.gridOpacity)||.35));gridThickness=Math.max(.5,Math.min(3,Number(a.gridThickness)||1));gridDotSize=Math.max(1,Math.min(6,Number(a.gridDotSize)||2));keyboardNudgePx=Math.round(Math.max(1,Math.min(100,Number(a.keyboardNudgePx)||5)));extGrid=gridMode!=='off';extSnap=!!a.snap;const r=a.roiAppearance||{};roiAppearance={labelFontSize:Math.max(6,Math.min(32,Number(r.labelFontSize)||12)),labelFontWeight:['400','500','600','700'].includes(String(r.labelFontWeight))?String(r.labelFontWeight):'700',outlineThickness:Math.max(.5,Math.min(6,Number(r.outlineThickness)||2)),handleSize:Math.max(4,Math.min(24,Number(r.handleSize)||10)),showShapeType:r.showShapeType===true};if($('ext_grid'))$('ext_grid').checked=extGrid;if($('ext_snap'))$('ext_snap').checked=extSnap;if(redraw){renderWorkspaceCanvas();drawPrecisionOverlay();}}
function readEditorSettingsForm(){return{gridMode:$('roi_setting_grid_mode').value,gridSpacing:Number($('roi_setting_grid_spacing').value),gridColor:$('roi_setting_grid_color').value,streamFps:Number($('roi_setting_stream_fps').value),gridOpacity:Number($('roi_setting_grid_opacity').value),gridThickness:Number($('roi_setting_grid_thickness').value),gridDotSize:Number($('roi_setting_grid_dot_size').value),keyboardNudgePx:Number($('roi_setting_keyboard_nudge').value),snap:$('roi_setting_snap').checked,roiAppearance:{labelFontSize:Number($('roi_setting_label_size').value),labelFontWeight:$('roi_setting_label_weight').value,showShapeType:$('roi_setting_label_shape').checked,outlineThickness:Number($('roi_setting_outline_thickness').value),handleSize:Number($('roi_setting_handle_size').value)}};}
function previewEditorSettings(){const a=readEditorSettingsForm();applyEditorSettings(a);syncSettingsFormControls(a);}
async function refreshStreamJpegQualityFromServer(){try{const response=await nativeFetch('/api/stream/quality',{cache:'no-store'});if(!response.ok)return;const data=await response.json();const quality=Number(data.quality);if(!Number.isInteger(quality)||quality<30||quality>100)return;streamJpegQuality=quality;const qualityInput=$('roi_setting_jpeg_quality');const qualityValue=$('roi_setting_jpeg_quality_value');if(qualityInput&&!streamQualityDraftDirty&&$('roi_settings_dialog').classList.contains('is-open')){qualityInput.value=String(quality);if(qualityValue)qualityValue.textContent=quality+' / 100';}}catch(error){if(typeof recordApiEvent==='function')recordApiEvent('warn','Could not read Stream JPEG quality: '+(error&&error.message?error.message:'request failed'));}}
function openEditorSettings(){const m=$('roi_settings_dialog');streamQualityDraftDirty=false;settingsBeforeOpen=currentEditorSettings();settingsReturnFocus=document.activeElement;syncSettingsFormControls(settingsBeforeOpen);const qualityInput=$('roi_setting_jpeg_quality');if(qualityInput){qualityInput.value=String(streamJpegQuality);qualityInput.disabled=!STREAM_CONTROL_ALLOWED;}const qualityValue=$('roi_setting_jpeg_quality_value');if(qualityValue)qualityValue.textContent=streamJpegQuality+' / 100';m.classList.add('is-open');m.setAttribute('aria-hidden','false');$('roi_setting_grid_mode').focus();refreshStreamJpegQualityFromServer();}
function closeEditorSettings(restore){const m=$('roi_settings_dialog');if(restore&&settingsBeforeOpen)applyEditorSettings(settingsBeforeOpen);if(restore){const qualityInput=$('roi_setting_jpeg_quality');if(qualityInput)qualityInput.value=String(streamJpegQuality);const qualityValue=$('roi_setting_jpeg_quality_value');if(qualityValue)qualityValue.textContent=streamJpegQuality+' / 100';}m.classList.remove('is-open');m.setAttribute('aria-hidden','true');streamQualityDraftDirty=false;if(settingsReturnFocus&&settingsReturnFocus.focus)settingsReturnFocus.focus();settingsBeforeOpen=null;}
function resetEditorSettingsDraft(){const a={gridMode:'off',gridSpacing:.05,gridColor:'#69bed2',streamFps:8.3,gridOpacity:.35,gridThickness:1,gridDotSize:2,keyboardNudgePx:5,snap:false,roiAppearance:{labelFontSize:12,labelFontWeight:'700',outlineThickness:2,handleSize:10,showShapeType:false}};syncSettingsFormControls(a);const qualityInput=$('roi_setting_jpeg_quality');if(qualityInput)qualityInput.value=String(STREAM_CONTROL_ALLOWED?85:streamJpegQuality);streamQualityDraftDirty=!!STREAM_CONTROL_ALLOWED;const qualityValue=$('roi_setting_jpeg_quality_value');if(qualityValue)qualityValue.textContent=(qualityInput?qualityInput.value:streamJpegQuality)+' / 100';applyEditorSettings(a);}
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&$('roi_settings_dialog').classList.contains('is-open')){e.preventDefault();e.stopImmediatePropagation();closeEditorSettings(true);}});

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
  event.preventDefault();event.stopPropagation();event.stopImmediatePropagation();const p=pointFromEvent(event);if(!p)return;
  extCrosshairPoint=p;crosshairPinned=true;const coordinateText=p.space==='image'?p.u.toFixed(3)+', '+p.v.toFixed(3):Math.round(p.canvasX)+', '+Math.round(p.canvasY);
  updateActiveToolBanner();drawPrecisionOverlay();persistCrosshairWorkspaceNow();
  copyCoordinateText(coordinateText).then(()=>{const text=p.space==='image'?'Captured image U,V: '+coordinateText+'.':'Captured canvas X,Y px: '+coordinateText+'. Z is not real depth.';updateEditorStatus(text);showToast('Copied coordinates: '+coordinateText);}).catch(()=>{updateEditorStatus('Captured point: '+coordinateText+'. Clipboard unavailable.');showToast('Point: '+coordinateText);});
  return;
 }
 if(!['annotate','ruler'].includes(editorTool)||event.button!==0)return;
 const p=pointFromEvent(event);if(!p)return;event.preventDefault();event.stopPropagation();event.stopImmediatePropagation();
 if(editorTool==='annotate'){
  let label=window.prompt('Annotation label (optional):','');if(label===null)return;label=String(label).trim().slice(0,80);
  extAnnotations.push({kind:label?'note':'marker',space:p.space,u:p.space==='image'?p.u:p.canvasU,v:p.space==='image'?p.v:p.canvasV,label:label,color:'#fbbf24'});
  if(extAnnotations.length>250)extAnnotations.shift();refreshAnnotationList();syncLayerControls();drawPrecisionOverlay();scheduleWorkspaceSave();updateEditorStatus('Marker placed in '+p.space+' coordinate space.');
 }else if(!rulerStart){
  // Ruler start marked. Move the pointer to preview distance; click the second point to finish.
  rulerStart=snapshotRulerPoint(p);rulerHoverPoint=snapshotRulerPoint(p);updateEditorStatus('Ruler start set. Click again to finish; points may be inside or outside the image.');updateActiveToolBanner();drawPrecisionOverlay();}
 else{
  const a=rulerStart,same=a.space==='image'&&p.space==='image';rulerStart=null;const space=same?'image':'canvas',u=same?a.u:a.canvasU,v=same?a.v:a.canvasV,u2=same?p.u:p.canvasU,v2=same?p.v:p.canvasV,dist=rulerDistance(a,p);
  extAnnotations.push({kind:'ruler',space:space,u:u,v:v,u2:u2,v2:v2,distancePx:dist,color:'#22d3ee'});rulerHoverPoint=null;updateEditorStatus('Ruler saved: '+formatRulerDistance(dist,space)+'.');updateActiveToolBanner();syncLayerControls();
  if(extAnnotations.length>250)extAnnotations.shift();refreshAnnotationList();drawPrecisionOverlay();scheduleWorkspaceSave();
 }
}
