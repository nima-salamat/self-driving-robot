
(function(){
'use strict';
const $ = function(id){return document.getElementById(id)};
const jsonClone = function(value){return JSON.parse(JSON.stringify(value));};
const EXT_LAYERS = ['RL','LL','CW','ST','OBJ','BEV'];
let extGrid=false, extSnap=false, extCrosshair=false, extAnnotationsVisible=true, extCrosshairPoint=null;
window.__isEditorSnapEnabled=()=>extSnap;
let editorTool='select', rulerStart=null, extAnnotations=[], extFrameGallery=[], extRuntimeSample=[];
let undoStack=[], redoStack=[], currentConfig=null, internalConfigWrite=0, extSaveTimer=null, extHealthTimer=null;
let serverLogsVisible=[], workspaceProfileNames=[], presetNames=[], historyItems=[];
let frameCompareImage=null, cameraSupportedControlNames=[], cameraSettingsEditable=false;
const nativeFetch = window.fetch.bind(window);

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
    const step=Math.max(.025,Math.min(.25,Number(gridSpacing)||.05));
    const stroke='rgba(105,190,210,'+Math.max(.05,Math.min(1,Number(gridOpacity)||.35))+')';
    if(gridMode==='dots'){
      for(let u=step;u<1;u+=step)for(let v=step;v<1;v+=step)
        addSVG('circle',{cx:b.ix+b.iw*u,cy:b.iy+b.ih*v,r:Math.max(.6,Number(gridDotSize||2)*z),fill:stroke});
    }else{
      for(let u=step;u<1;u+=step){const x=b.ix+b.iw*u;addSVG('line',{x1:x,y1:b.iy,x2:x,y2:b.iy+b.ih,stroke:stroke,'stroke-width':Math.max(.4,gridThickness*z)});}
      for(let v=step;v<1;v+=step){const y=b.iy+b.ih*v;addSVG('line',{x1:b.ix,y1:y,x2:b.ix+b.iw,y2:y,stroke:stroke,'stroke-width':Math.max(.4,gridThickness*z)});}
    }
    addSVG('rect',{x:b.ix,y:b.iy,width:b.iw,height:b.ih,fill:'none',stroke:stroke,'stroke-width':Math.max(.5,gridThickness*z)});
  }
  if(extCrosshair&&extCrosshairPoint){
    addSVG('line',{x1:b.ix,y1:extCrosshairPoint.y,x2:b.ix+b.iw,y2:extCrosshairPoint.y,stroke:'#f8fafc','stroke-width':z,'stroke-dasharray':(6*z)+' '+(4*z)});
    addSVG('line',{x1:extCrosshairPoint.x,y1:b.iy,x2:extCrosshairPoint.x,y2:b.iy+b.ih,stroke:'#f8fafc','stroke-width':z,'stroke-dasharray':(6*z)+' '+(4*z)});
    const label=addSVG('text',{x:extCrosshairPoint.x+8*z,y:extCrosshairPoint.y-8*z,fill:'#fff','font-size':11*z,'paint-order':'stroke','stroke':'#07101a','stroke-width':3*z});
    label.textContent='U '+(((extCrosshairPoint.x-b.ix)/b.iw)*100).toFixed(1)+'% · V '+(((extCrosshairPoint.y-b.iy)/b.ih)*100).toFixed(1)+'%';
  }
  if(!extAnnotationsVisible)return;
  const baseOutline=Math.max(.5,Number(roiAppearance.outlineThickness)||2);
  const baseLabel=Math.max(6,Number(roiAppearance.labelFontSize)||12);
  const baseHandle=Math.max(4,Number(roiAppearance.handleSize)||10);
  const labelWeight=String(roiAppearance.labelFontWeight||'700');
  extAnnotations.forEach(function(item,index){
    const color=item.color||'#fbbf24';
    if(item.kind==='roi_rect'||item.kind==='roi_trapezoid'){
      const x=b.ix+Number(item.x||0)*b.iw,y=b.iy+Number(item.y||0)*b.ih,w=Number(item.w||0)*b.iw,h=Number(item.h||0)*b.ih;
      const strokeWidth=baseOutline*z;
      if(item.kind==='roi_rect'){
        addSVG('rect',{x:x,y:y,width:w,height:h,fill:'rgba(34,211,238,.10)',stroke:color,'stroke-width':strokeWidth,'stroke-dasharray':(5*z)+' '+(3*z)});
      }else{
        const top=Math.max(0,Math.min(1,Number(item.topFactor==null?0.5:item.topFactor))),inset=(w*(1-top))/2;
        addSVG('polygon',{points:(x+inset)+','+y+' '+(x+w-inset)+','+y+' '+(x+w)+','+(y+h)+' '+x+','+(y+h),fill:'rgba(34,211,238,.10)',stroke:color,'stroke-width':strokeWidth,'stroke-dasharray':(5*z)+' '+(3*z)});
      }
      const label=addSVG('text',{x:x+4*z,y:y+13*z,fill:color,'font-size':baseLabel*z,'font-weight':labelWeight,'paint-order':'stroke',stroke:'#07101a','stroke-width':1.5*baseOutline*z});
      label.textContent=item.label||('Preview ROI '+(index+1));
      return;
    }
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
function setEditorTool(tool){
  editorTool=tool;
  rulerStart=null;
  if($('ext_ruler'))$('ext_ruler').checked=tool==='ruler';
  ['ext_annotate_btn','ext_ruler','ext_roi_rect_tool','ext_roi_trapezoid_tool'].forEach(function(id){
    if($(id))$(id).classList.toggle('ext-tool-active',
      (id==='ext_ruler'&&tool==='ruler')||(id==='ext_annotate_btn'&&tool==='annotate')||
      (id==='ext_roi_rect_tool'&&tool==='roi_rect')||(id==='ext_roi_trapezoid_tool'&&tool==='roi_trapezoid'));
  });
  if(typeof setTool==='function')setTool(tool==='pan'?'pan':'select');
  if(canvas)canvas.style.cursor=tool==='pan'?'grab':(['annotate','ruler','roi_rect','roi_trapezoid'].includes(tool)?'crosshair':'default');
  const messages={ruler:'Ruler active: click two points inside the image.',annotate:'Annotation active: click in the image to add a note marker.',roi_rect:'Rectangle ROI preview: click two opposite corners.',roi_trapezoid:'Trapezoid ROI preview: click two opposite corners.'};
  updateEditorStatus(messages[tool]||('Tool: '+tool));
  scheduleWorkspaceSave();drawPrecisionOverlay();
}
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
  if(!extAnnotations.length){const empty=document.createElement('div');empty.className='small-muted';empty.textContent='No custom annotations.';root.appendChild(empty);return;}
  extAnnotations.forEach(function(item,index){
    const row=document.createElement('div');row.className='ext-list-row';
    const label=document.createElement('span');label.textContent=(index+1)+'. '+(item.kind||'marker')+(item.label?': '+item.label:'');row.appendChild(label);
    const remove=document.createElement('button');remove.type='button';remove.className='ghost';remove.textContent='Delete';remove.onclick=function(){extAnnotations.splice(index,1);refreshAnnotationList();drawPrecisionOverlay();scheduleWorkspaceSave();};row.appendChild(remove);root.appendChild(row);
  });
  syncLayerControls();
}
let settingsBeforeOpen=null,settingsReturnFocus=null;
function currentEditorSettings(){return{gridMode,gridSpacing,gridOpacity,gridThickness,gridDotSize,snap:extSnap,roiAppearance:{labelFontSize:roiAppearance.labelFontSize,labelFontWeight:String(roiAppearance.labelFontWeight),outlineThickness:roiAppearance.outlineThickness,handleSize:roiAppearance.handleSize}};}
function syncSettingsFormControls(a){$('roi_setting_grid_mode').value=a.gridMode;$('roi_setting_grid_spacing').value=String(a.gridSpacing);$('roi_setting_grid_spacing_value').textContent=Number((a.gridSpacing*100).toFixed(1))+'%';$('roi_setting_grid_opacity').value=String(a.gridOpacity);$('roi_setting_grid_thickness').value=String(a.gridThickness);$('roi_setting_grid_dot_size').value=String(a.gridDotSize);$('roi_setting_snap').checked=!!a.snap;$('roi_setting_label_size').value=String(a.roiAppearance.labelFontSize);$('roi_setting_label_size_value').textContent=a.roiAppearance.labelFontSize+' px at 100%';$('roi_setting_label_weight').value=String(a.roiAppearance.labelFontWeight);$('roi_setting_outline_thickness').value=String(a.roiAppearance.outlineThickness);$('roi_setting_handle_size').value=String(a.roiAppearance.handleSize);}
function applyEditorSettings(a,redraw=true){gridMode=['off','grid','dots'].includes(a.gridMode)?a.gridMode:'off';gridSpacing=Math.max(.025,Math.min(.25,Number(a.gridSpacing)||.05));gridOpacity=Math.max(.05,Math.min(1,Number(a.gridOpacity)||.35));gridThickness=Math.max(.5,Math.min(3,Number(a.gridThickness)||1));gridDotSize=Math.max(1,Math.min(6,Number(a.gridDotSize)||2));extGrid=gridMode!=='off';extSnap=!!a.snap;const r=a.roiAppearance||{};roiAppearance={labelFontSize:Math.max(6,Math.min(32,Number(r.labelFontSize)||12)),labelFontWeight:['400','500','600','700'].includes(String(r.labelFontWeight))?String(r.labelFontWeight):'700',outlineThickness:Math.max(.5,Math.min(6,Number(r.outlineThickness)||2)),handleSize:Math.max(4,Math.min(24,Number(r.handleSize)||10))};if($('ext_grid'))$('ext_grid').checked=extGrid;if($('ext_snap'))$('ext_snap').checked=extSnap;if(redraw){renderWorkspaceCanvas();drawPrecisionOverlay();}}
function readEditorSettingsForm(){return{gridMode:$('roi_setting_grid_mode').value,gridSpacing:Number($('roi_setting_grid_spacing').value),gridOpacity:Number($('roi_setting_grid_opacity').value),gridThickness:Number($('roi_setting_grid_thickness').value),gridDotSize:Number($('roi_setting_grid_dot_size').value),snap:$('roi_setting_snap').checked,roiAppearance:{labelFontSize:Number($('roi_setting_label_size').value),labelFontWeight:$('roi_setting_label_weight').value,outlineThickness:Number($('roi_setting_outline_thickness').value),handleSize:Number($('roi_setting_handle_size').value)}};}
function previewEditorSettings(){const a=readEditorSettingsForm();applyEditorSettings(a);syncSettingsFormControls(a);}
function openEditorSettings(){const m=$('roi_settings_dialog');settingsBeforeOpen=currentEditorSettings();settingsReturnFocus=document.activeElement;syncSettingsFormControls(settingsBeforeOpen);m.classList.add('is-open');m.setAttribute('aria-hidden','false');$('roi_setting_grid_mode').focus();}
function closeEditorSettings(restore){const m=$('roi_settings_dialog');if(restore&&settingsBeforeOpen)applyEditorSettings(settingsBeforeOpen);m.classList.remove('is-open');m.setAttribute('aria-hidden','true');if(settingsReturnFocus&&settingsReturnFocus.focus)settingsReturnFocus.focus();settingsBeforeOpen=null;}
function resetEditorSettingsDraft(){const a={gridMode:'off',gridSpacing:.05,gridOpacity:.35,gridThickness:1,gridDotSize:2,snap:false,roiAppearance:{labelFontSize:12,labelFontWeight:'700',outlineThickness:2,handleSize:10}};syncSettingsFormControls(a);applyEditorSettings(a);}
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
  if(!['annotate','ruler','roi_rect','roi_trapezoid'].includes(editorTool)||event.button!==0)return;
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
    rulerStart=point;updateEditorStatus(editorTool==='ruler'?'Ruler start marked. Click the second point.':'ROI first corner marked. Click the opposite corner.');drawPrecisionOverlay();
  }else{
    const start=rulerStart;rulerStart=null;
    if(editorTool==='ruler'){
      const distance=Math.hypot((point.u-start.u)*(frameSourceWidth||canvas.width),(point.v-start.v)*(frameSourceHeight||canvas.height));
      extAnnotations.push({kind:'ruler',u:start.u,v:start.v,u2:point.u,v2:point.v,label:distance.toFixed(1)+' px',color:'#22d3ee'});
      updateEditorStatus('Ruler saved: '+distance.toFixed(1)+' image pixels.');syncLayerControls();
    }else{
      const x=Math.min(start.u,point.u),y=Math.min(start.v,point.v),w=Math.abs(point.u-start.u),h=Math.abs(point.v-start.v);
      if(w<0.005||h<0.005){updateEditorStatus('Custom ROI is too small; draw it again with a larger area.');return;}
      const kind=editorTool;
      const generatedName='Preview ROI '+(extAnnotations.length+1);
      const typedLabel=window.prompt('Custom ROI label:',generatedName);
      if(typedLabel===null){drawPrecisionOverlay();return;}
      const item={kind:kind,x:x,y:y,w:w,h:h,label:String(typedLabel||generatedName).trim().slice(0,80),color:'#22d3ee'};
      if(kind==='roi_trapezoid')item.topFactor=Number($('ext_roi_top_factor').value)||0.5;
      extAnnotations.push(item);updateEditorStatus('Preview ROI added. This shape does not alter robot perception or control.');
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
  return {view:{zoom:workspaceZoom,panX:viewPanX,panY:viewPanY,grid:gridMode!=='off',gridMode:gridMode,gridSpacing:gridSpacing,gridOpacity:gridOpacity,gridThickness:gridThickness,gridDotSize:gridDotSize,snap:extSnap,crosshair:extCrosshair,showRuler:editorTool==='ruler',overlays:!!showRectsCheckbox.checked,tool:editorTool,rightPaneWidth:paneWidth},
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
  gridSpacing=Math.max(.025,Math.min(.25,Number(view.gridSpacing)||.05));gridOpacity=Math.max(.05,Math.min(1,Number(view.gridOpacity)||.35));
  gridThickness=Math.max(.5,Math.min(3,Number(view.gridThickness)||1));gridDotSize=Math.max(1,Math.min(6,Number(view.gridDotSize)||2));
  const a=workspace.roiAppearance&&typeof workspace.roiAppearance==='object'?workspace.roiAppearance:{};
  roiAppearance={labelFontSize:Math.max(6,Math.min(32,Number(a.labelFontSize)||12)),labelFontWeight:['400','500','600','700'].includes(String(a.labelFontWeight))?String(a.labelFontWeight):'700',outlineThickness:Math.max(.5,Math.min(6,Number(a.outlineThickness)||2)),handleSize:Math.max(4,Math.min(24,Number(a.handleSize)||10))};
  extGrid=gridMode!=='off';extSnap=!!view.snap;extCrosshair=!!view.crosshair;
  if($('ext_grid'))$('ext_grid').checked=extGrid;if($('ext_snap'))$('ext_snap').checked=extSnap;if($('ext_crosshair'))$('ext_crosshair').checked=extCrosshair;
  if($('ext_overlays'))$('ext_overlays').checked=view.overlays!==false;if(typeof view.overlays==='boolean')showRectsCheckbox.checked=view.overlays;
  editorTool=['select','pan','annotate','ruler','roi_rect','roi_trapezoid'].includes(view.tool)?view.tool:'select';
  const layers=workspace.layers||{};extAnnotationsVisible=!layers.ANNOTATIONS||layers.ANNOTATIONS.visible!==false;
  if(typeof view.rightPaneWidth==='number'&&view.rightPaneWidth>=250&&view.rightPaneWidth<=700)document.querySelector('.container').style.setProperty('--right-pane-width',view.rightPaneWidth+'px');
  Object.keys(workspace.panels||{}).forEach(id=>{const p=$(id);if(p&&p.tagName==='DETAILS')p.open=!!workspace.panels[id];});
  Object.keys(layers).forEach(key=>{const layer=layers[key];if(layer&&EXT_LAYERS.includes(key)){ui.visible[key]=layer.visible!==false;ui.opacity[key]=Number(layer.opacity==null?1:layer.opacity);}});
  if(layers.GRID&&layers.GRID.visible===false){gridMode='off';extGrid=false;}
  extAnnotations=Array.isArray(workspace.annotations)?jsonClone(workspace.annotations).slice(0,250):[];
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
  const annotationCheck=document.createElement('input');annotationCheck.type='checkbox';annotationCheck.checked=extAnnotationsVisible;annotationCheck.title='Show/hide user annotations and custom ROI previews';
  annotationCheck.onchange=function(){extAnnotationsVisible=annotationCheck.checked;drawPrecisionOverlay();scheduleWorkspaceSave();};
  annotationRow.appendChild(annotationCheck);
  const annotationLabel=document.createElement('span');annotationLabel.textContent='Annotations / custom ROI previews';annotationRow.appendChild(annotationLabel);
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
  if($('run_lvl'))$('run_lvl').value=advanced.RUN_LVL||'MOVE';if($('with_sign'))$('with_sign').checked=!!advanced.WITH_SIGN;if($('with_apriltag'))$('with_apriltag').checked=!!advanced.WITH_APRILTAG;
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
async function refreshRuntime(){
  try{
    const health=await nativeFetch('/api/health',{cache:'no-store'}).then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.json();});
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
    const controls=c.controls||{};if(controls.ExposureTime!=null)$('ext_exposure').value=String(controls.ExposureTime);if(controls.AnalogueGain!=null)$('ext_gain').value=String(controls.AnalogueGain);
    $('ext_auto_exposure').checked=!!controls.AeEnable;$('ext_auto_wb').checked=!!controls.AwbEnable;
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
    if(data.target_fps!=null)$('ext_target_fps').value=String(data.target_fps);
    $('ext_fps_status').textContent=data.available?'Live · '+Number(data.target_fps).toFixed(1)+' FPS':'Unavailable';
    $('ext_target_fps').disabled=!data.available||!STREAM_CONTROL_ALLOWED;$('ext_apply_fps').disabled=!data.available||!STREAM_CONTROL_ALLOWED;
  }catch(err){$('ext_fps_status').textContent=err.message;}
}
async function refreshSafety(){
  try{const data=await nativeFetch('/api/safety',{cache:'no-store'}).then(function(r){return r.json();});
    $('ext_safety_state').textContent='Software stop: '+(data.software_stop_active?'ACTIVE':'inactive')+' · RUN_LVL='+data.run_level;
    $('ext_software_stop').disabled=!data.controls_enabled;$('ext_software_resume').disabled=!data.controls_enabled;
  }catch(err){$('ext_safety_state').textContent='Safety status read failed: '+err.message;}
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
  showToast(action==='stop'?'Software stop requested':'Motion resume requested');noteWorkspaceEvent(action==='stop'?'warn':'info','Dashboard software '+action+' requested'+(settings.source==='keyboard'?' via Ctrl+Shift+Space':''));await refreshSafety();
}
async function applyProcessingRate(){
  const before=currentConfig?jsonClone(currentConfig):await readConfig();
  const fps=Number($('ext_target_fps').value);const data=await nativeFetch('/api/processing-rate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({target_fps:fps})}).then(async function(r){const j=await r.json();if(!r.ok)throw new Error(j.message||('HTTP '+r.status));return j;});
  $('ext_fps_status').textContent='Saved · '+Number(data.target_fps).toFixed(1)+' FPS';currentConfig=await readConfig().catch(function(){return currentConfig;});rememberUndo(before,currentConfig);showToast('Processing-rate limit applied and saved');
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
  const response=await nativeFetch('/api/camera/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  const data=await response.json().catch(function(){return {};});if(!response.ok)throw new Error(data.message||('HTTP '+response.status));await refreshCameraSettings();currentConfig=await readConfig().catch(function(){return currentConfig;});rememberUndo(before,currentConfig);showToast('Runtime camera controls applied');
}
function buildCommandPalette(){
  const commands=[
    ['Keyboard shortcuts','shortcuts','F1'],['Export full configuration','export','Ctrl+Shift+E'],['Import full configuration','import',''],['Save workspace layout','workspace','Ctrl+S'],['Undo','undo','Ctrl+Z'],['Redo','redo','Ctrl+Y / Ctrl+Shift+Z'],
    ['Fit camera frame','fit','0'],['Toggle ROI overlays','overlays','O'],['Toggle grid','grid','G'],['Toggle crosshair','crosshair','X'],
    ['Use annotation tool','annotate','N'],['Use pixel ruler','ruler','R'],['Draw rectangle ROI preview','roi_rect',''],['Draw trapezoid ROI preview','roi_trapezoid',''],
    ['Save workspace layout','workspace',''],['Save workspace profile','profile',''],['Save configuration preset','preset',''],
    ['Capture frame snapshot','snapshot',''],['Refresh runtime diagnostics','health',''],['Refresh server logs','logs',''],
    ['Open encoder map','encoder',''],['Open camera controls','camera',''],['Request software stop','stop',''],['Resume motion (confirmation)','resume','']
  ];
  const list=$('ext_command_list');list.replaceChildren();
  commands.forEach(function(entry){const b=document.createElement('button');b.type='button';b.dataset.command=entry[1];b.textContent=entry[0]+(entry[2]?' · '+entry[2]:'');b.onclick=function(){closeCommandPalette();executeCommand(entry[1]);};list.appendChild(b);});
  $('ext_command_search').addEventListener('input',function(){const q=this.value.toLowerCase();list.querySelectorAll('button').forEach(function(b){b.hidden=!b.textContent.toLowerCase().includes(q);});});
}
function openCommandPalette(){const m=$('ext_command_palette');m.style.display='flex';$('ext_command_search').value='';$('ext_command_search').focus();$('ext_command_search').dispatchEvent(new Event('input'));}
function closeCommandPalette(){$('ext_command_palette').style.display='none';}
function executeCommand(name){
  const actions={
    shortcuts:function(){if(window.openStreamShortcuts)window.openStreamShortcuts();},
    export:exportFullConfig,import:function(){$('ext_config_file').click();},undo:doUndo,redo:doRedo,
    fit:function(){fitWorkspaceView();},overlays:function(){$('ext_overlays').click();},grid:function(){$('ext_grid').click();},crosshair:function(){$('ext_crosshair').click();},
    annotate:function(){setEditorTool('annotate');},ruler:function(){$('ext_ruler').click();},
    roi_rect:function(){setEditorTool('roi_rect');},roi_trapezoid:function(){setEditorTool('roi_trapezoid');},
    snapshot:addFrameSnapshot,workspace:function(){saveWorkspace().then(function(){showToast('Workspace saved');}).catch(function(e){showToast(e.message);});},
    profile:function(){$('ext_editor_panel').open=true;$('ext_profile_name').focus();},
    preset:function(){$('ext_config_panel').open=true;$('ext_preset_name').focus();},
    health:function(){refreshRuntime().then(function(){showToast('Runtime diagnostics refreshed');});},
    logs:refreshServerLogs,
    camera:function(){$('ext_camera_panel').open=true;$('ext_camera_panel').scrollIntoView({behavior:'smooth',block:'nearest'});},
    encoder:function(){if($('ext_encoder_embed').hidden)showToast('Encoder map requires --encoder-map and compatible firmware restart.');else $('ext_encoder_frame').scrollIntoView({behavior:'smooth'});},
    stop:function(){safetyAction('stop').catch(function(e){showToast(e.message);});},
    resume:function(){safetyAction('resume').catch(function(e){showToast(e.message);});}
  };
  if(actions[name])Promise.resolve(actions[name]()).catch(function(err){showToast(err.message||String(err));});
}
function enableReadOnlyState(){
  if(STREAM_CONTROL_ALLOWED)return;
  ['ext_export_config','ext_import_config','ext_undo','ext_redo','ext_preset_save','ext_preset_apply','ext_preset_delete','ext_history_restore','ext_profile_save','ext_profile_delete','ext_apply_fps','ext_apply_camera','ext_software_stop','ext_software_resume','ext_save_workspace'].forEach(function(id){if($(id))$(id).disabled=true;});
}
function initializeResize(){
  const container=document.querySelector('.container'),panel=document.querySelector('.right-panel');if(!container||!panel)return;
  let active=false,startX=0,startWidth=315;
  panel.addEventListener('pointerdown',function(e){const bounds=panel.getBoundingClientRect();if(e.clientX-bounds.left>7||window.innerWidth<721)return;active=true;startX=e.clientX;startWidth=parseFloat(getComputedStyle(container).getPropertyValue('--right-pane-width'))||bounds.width;panel.setPointerCapture(e.pointerId);e.preventDefault();});
  panel.addEventListener('pointermove',function(e){if(!active)return;const delta=startX-e.clientX;const width=Math.max(250,Math.min(700,startWidth+delta));container.style.setProperty('--right-pane-width',width+'px');});
  panel.addEventListener('pointerup',function(){if(!active)return;active=false;scheduleWorkspaceSave();});
  panel.addEventListener('pointercancel',function(){active=false;});
}
function installCoordinatePairPaste(){
  ['prop_left','prop_top','prop_right','prop_bottom','prop_point_x','prop_point_y'].forEach(function(id){
    const field=$(id);if(!field)return;
    field.addEventListener('paste',function(event){
      const transfer=event.clipboardData||window.clipboardData;
      const text=transfer&&transfer.getData?transfer.getData('text'):'';
      const match=String(text||'').match(/^\\s*(-?(?:\\d+\\.?\\d*|\\.\\d+))\\s*[,;\\s]\\s*(-?(?:\\d+\\.?\\d*|\\.\\d+))\\s*$/);
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
function installExtension(){
  const stage=$('canvas_stage');if(stage&&canvas){
    let svg=$('ext_precision_overlay');if(!svg){svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.id='ext_precision_overlay';svg.setAttribute('aria-hidden','true');stage.appendChild(svg);}
    canvas.addEventListener('pointerdown',onCustomPointerDown,true);
    installCoordinatePairPaste();
    canvas.addEventListener('pointermove',function(e){const point=pointFromEvent(e);extCrosshairPoint=point?{x:point.x,y:point.y}:null;if(extCrosshair)drawPrecisionOverlay();});
  }
  if($('ext_export_annotations'))$('ext_export_annotations').onclick=function(){downloadText(JSON.stringify(extAnnotations,null,2),'roboy-annotations.json','application/json');};
  $('ext_grid').addEventListener('change',function(){gridMode=this.checked?(gridMode==='dots'?'dots':'grid'):'off';extGrid=gridMode!=='off';drawPrecisionOverlay();scheduleWorkspaceSave();});
  $('roi_settings_open').addEventListener('click',openEditorSettings);$('roi_settings_close').addEventListener('click',()=>closeEditorSettings(true));$('roi_settings_cancel').addEventListener('click',()=>closeEditorSettings(true));
  $('roi_settings_apply').addEventListener('click',()=>{previewEditorSettings();scheduleWorkspaceSave();closeEditorSettings(false);showToast('Editor settings applied');});$('roi_settings_reset').addEventListener('click',resetEditorSettingsDraft);
  const settingsModalElement=$('roi_settings_dialog');settingsModalElement.addEventListener('click',e=>{if(e.target===settingsModalElement)closeEditorSettings(true);});settingsModalElement.querySelectorAll('input,select').forEach(el=>['input','change'].forEach(evt=>el.addEventListener(evt,previewEditorSettings)));
  $('ext_snap').addEventListener('change',function(){extSnap=this.checked;scheduleWorkspaceSave();});
  $('ext_crosshair').addEventListener('change',function(){extCrosshair=this.checked;if(canvas)canvas.classList.toggle('crosshair-active',extCrosshair);drawPrecisionOverlay();scheduleWorkspaceSave();if(extCrosshair)updateEditorStatus('Crosshair active: click a point inside the camera image to copy normalized U, V coordinates.');});
  $('ext_overlays').addEventListener('change',function(){showRectsCheckbox.checked=this.checked;renderWorkspaceCanvas();scheduleWorkspaceSave();});
  showRectsCheckbox.addEventListener('change',function(){if($('ext_overlays'))$('ext_overlays').checked=this.checked;});
  $('ext_annotate_btn').onclick=function(){setEditorTool(editorTool==='annotate'?'select':'annotate');};
  $('ext_ruler').addEventListener('change',function(){setEditorTool(this.checked?'ruler':'select');});
  $('ext_roi_rect_tool').onclick=function(){setEditorTool(editorTool==='roi_rect'?'select':'roi_rect');};
  $('ext_roi_trapezoid_tool').onclick=function(){setEditorTool(editorTool==='roi_trapezoid'?'select':'roi_trapezoid');};
  $('ext_roi_top_factor').addEventListener('input',function(){$('ext_roi_top_factor_label').textContent=Math.round(Number(this.value)*100)+'%';});
  $('ext_clear_annotations').onclick=function(){if(!extAnnotations.length)return;if(confirm('Clear all custom annotations from the workspace?')){extAnnotations=[];refreshAnnotationList();syncLayerControls();drawPrecisionOverlay();scheduleWorkspaceSave();}};
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
  $('ext_software_stop').onclick=function(){safetyAction('stop').catch(function(e){showToast(e.message);});};$('ext_software_resume').onclick=function(){safetyAction('resume').catch(function(e){showToast(e.message);});};
  $('ext_auto_exposure').addEventListener('change',updateCameraControlsEnabled);
  $('ext_log_refresh').onclick=function(){refreshServerLogs();};$('ext_log_level').addEventListener('change',refreshServerLogs);$('ext_log_search').addEventListener('input',function(){clearTimeout(window.extLogDebounce);window.extLogDebounce=setTimeout(refreshServerLogs,250);});
  $('console_filter').addEventListener('input',function(){workspaceConsoleQuery=this.value;renderWorkspaceEventLog('events');renderWorkspaceEventLog('api');});
  $('console_level').addEventListener('change',function(){workspaceConsoleLevel=this.value;renderWorkspaceEventLog('events');renderWorkspaceEventLog('api');});
  $('console_pause').addEventListener('change',function(){workspaceConsolePaused=this.checked;if(!workspaceConsolePaused){renderWorkspaceEventLog('events');renderWorkspaceEventLog('api');}});
  $('console_autoscroll').addEventListener('change',function(){workspaceConsoleAutoScroll=this.checked;if(workspaceConsoleAutoScroll){renderWorkspaceEventLog('events');renderWorkspaceEventLog('api');}});
  $('console_export_btn').onclick=function(){downloadText(JSON.stringify({exported_at:new Date().toISOString(),events:workspaceEvents.map(function(e){return {time:e.time instanceof Date?e.time.toISOString():e.time,level:e.level,message:e.message};}),requests:workspaceApiEvents.map(function(e){return {time:e.time instanceof Date?e.time.toISOString():e.time,level:e.level,message:e.message};})},null,2),'roboy-workspace-console.json','application/json');};
  $('ext_log_export').onclick=function(){downloadText(JSON.stringify(serverLogsVisible,null,2),'roboy-runtime-logs.json','application/json');};
  $('ext_export_annotations').onclick=function(){downloadText(JSON.stringify(extAnnotations,null,2),'roboy-'+String(window.STREAM_BOOTSTRAP.mode || 'mode').toLowerCase()+'-annotations.json','application/json');};
  $('ext_open_palette').onclick=openCommandPalette;
  $('ext_encoder_reset').onclick=async function(){if(!confirm('Reset only the displayed odometry origin? Hardware counters will not be reset.'))return;const r=await nativeFetch('/api/encoder-map/reset-origin',{method:'POST'});const j=await r.json();if(!r.ok)throw new Error(j.error||('HTTP '+r.status));showToast('Displayed odometry origin reset');};
  $('ext_frame_compare_close').onclick=function(){$('ext_frame_compare').style.display='none';};
  $('ext_frame_compare').addEventListener('click',function(e){if(e.target===this)this.style.display='none';});
  $('ext_command_palette').addEventListener('click',function(e){if(e.target===this)closeCommandPalette();});buildCommandPalette();initializeResize();enableReadOnlyState();
  document.addEventListener('keydown',function(e){
    // Fast software-stop hotkey: Ctrl+Shift+Space, with no confirmation dialog.
    // It still uses /api/safety; the active Python mode loop owns RUN_LVL.
    if(e.ctrlKey&&e.shiftKey&&(e.code==='Space'||e.key===' ')){
      if(e.repeat)return;
      e.preventDefault();
      safetyAction('stop',{skipConfirm:true,source:'keyboard'}).catch(function(err){showToast('Software STOP failed: '+err.message);});
      return;
    }
    if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();openCommandPalette();return;}
    if((e.ctrlKey||e.metaKey)&&e.shiftKey&&e.key.toLowerCase()==='e'){e.preventDefault();exportFullConfig().catch(function(err){showToast('Export failed: '+err.message);});return;}
    if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();saveWorkspace().then(function(){showToast('Workspace saved');}).catch(function(err){showToast('Save failed: '+err.message);});return;}
    if($('ext_command_palette').style.display==='flex'&&e.key==='Escape'){closeCommandPalette();return;}
    if(e.target&&(['INPUT','SELECT','TEXTAREA'].includes(e.target.tagName)||e.target.isContentEditable))return;
    if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();doUndo();return;}
    if((e.ctrlKey||e.metaKey)&&(e.key.toLowerCase()==='y'||(e.shiftKey&&e.key.toLowerCase()==='z'))){e.preventDefault();doRedo();return;}
    if(!e.ctrlKey&&!e.metaKey&&!e.altKey){
      if(e.key.toLowerCase()==='g')$('ext_grid').click();
      else if(e.key.toLowerCase()==='x')$('ext_crosshair').click();
      else if(e.key.toLowerCase()==='n')setEditorTool('annotate');
      else if(e.key.toLowerCase()==='r'){$('ext_ruler').checked=!$('ext_ruler').checked;$('ext_ruler').dispatchEvent(new Event('change'));}
    }
  });
  document.querySelectorAll('.right-panel details.dock-panel').forEach(function(panel){panel.addEventListener('toggle',scheduleWorkspaceSave);});
  window.addEventListener('resize',drawPrecisionOverlay);
}
async function initializeExtension(){
  try{currentConfig=await readConfig();if(currentConfig.ui&&currentConfig.ui.opacity)ui.opacity=currentConfig.ui.opacity;}catch(err){if(typeof recordApiEvent==='function')recordApiEvent('warn','Extended config API unavailable: '+err.message);}
  syncLayerControls();syncLegacyLayerControls();installExtension();refreshAnnotationList();drawPrecisionOverlay();
  refreshWorkspaceProfiles().catch(function(err){if(typeof recordApiEvent==='function')recordApiEvent('warn','Workspace load failed: '+err.message);});
  refreshPresets().catch(function(err){if(typeof recordApiEvent==='function')recordApiEvent('warn','Preset list failed: '+err.message);});
  refreshHistory().catch(function(err){if(typeof recordApiEvent==='function')recordApiEvent('warn','History read failed: '+err.message);});
  refreshRuntime();refreshFeatureStatus();refreshTrafficAndRace();refreshCameraSettings();refreshProcessingRate();refreshSafety();refreshServerLogs();
  extHealthTimer=setInterval(function(){refreshRuntime();refreshTrafficAndRace();refreshSafety();},1800);
  setInterval(function(){refreshCameraSettings();refreshProcessingRate();},8000);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',initializeExtension,{once:true});else initializeExtension();
})();
