const simRoiDefs = [
  {id:"RL",label:"Right lane",color:"#48d7a4",fields:{top:"rl-top",bottom:"rl-bottom",left:"rl-left",right:"rl-right"}},
  {id:"LL",label:"Left lane",color:"#65a8ff",fields:{top:"ll-top",bottom:"ll-bottom",left:"ll-left",right:"ll-right"}},
  {id:"CW",label:"Crosswalk",color:"#f4bd63",fields:{top:"cw-top",bottom:"cw-bottom",left:"cw-left",right:"cw-right"}}
].filter(function(item){return item.id!=="CW"||caps.supports_crosswalk;});
let simRoiGeometry={lane_roi_mode:"rectangle",cw_trapezoid_mode:false,rl_top_width_factor:.85,ll_top_width_factor:.85,cw_top_width_factor:.9,use_bev:false};
let simRoiSelected="RL", simRoiDrag=null, simRoiControlsEnabled=false;
let simRoiMirrors={RL:false,LL:false};
let simRoiSaveTimer=null,simRoiSaveInFlight=false,simRoiSaveQueued=false;
const simRoiCanvas=$("sim-roi-canvas");
function simRoiBounds(id){
  const def=simRoiDefs.find(function(item){return item.id===id;});if(!def)return null;
  const b={};Object.keys(def.fields).forEach(function(key){const el=$(def.fields[key]);b[key]=el&&el.value!==""?Number(el.value):NaN;});
  if(!Object.values(b).every(Number.isFinite)||b.left<0||b.top<0||b.right>1||b.bottom>1||b.left>=b.right||b.top>=b.bottom)return null;
  return b;
}
function simRoiWriteBounds(id,b){
  const def=simRoiDefs.find(function(item){return item.id===id;});if(!def)return;
  Object.keys(def.fields).forEach(function(key){const el=$(def.fields[key]);if(el)el.value=Number(b[key]).toFixed(3);});
}
function simRoiPolygon(id,b){
  const width=b.right-b.left;
  if(id==="RL"&&simRoiGeometry.lane_roi_mode==="trapezoid"){
    return [[b.left,b.top],[b.left+width*simRoiGeometry.rl_top_width_factor,b.top],[b.right,b.bottom],[b.left,b.bottom]];
  }
  if(id==="LL"&&simRoiGeometry.lane_roi_mode==="trapezoid"){
    return [[b.right-width*simRoiGeometry.ll_top_width_factor,b.top],[b.right,b.top],[b.right,b.bottom],[b.left,b.bottom]];
  }
  if(id==="CW"&&simRoiGeometry.cw_trapezoid_mode){
    const inset=width*(1-simRoiGeometry.cw_top_width_factor)/2;
    return [[b.left+inset,b.top],[b.right-inset,b.top],[b.right,b.bottom],[b.left,b.bottom]];
  }
  return [[b.left,b.top],[b.right,b.top],[b.right,b.bottom],[b.left,b.bottom]];
}
function simRoiContains(x,y,polygon){
  let inside=false;
  for(let i=0,j=polygon.length-1;i<polygon.length;j=i++){
    const xi=polygon[i][0],yi=polygon[i][1],xj=polygon[j][0],yj=polygon[j][1];
    const intersects=((yi>y)!==(yj>y))&&(x<(xj-xi)*(y-yi)/(yj-yi+1e-12)+xi);
    if(intersects)inside=!inside;
  }
  return inside;
}
function simRoiUpdateSelection(){
  document.querySelectorAll("[data-sim-roi-select]").forEach(function(button){button.classList.toggle("active",button.dataset.simRoiSelect===simRoiSelected);});
  if(simRoiCanvas)simRoiCanvas.style.pointerEvents=$("sim-roi-overlay-toggle")&&$("sim-roi-overlay-toggle").checked?"auto":"none";
  const mirrorControl=$("sim-roi-mirror-control"),mirrorInput=$("sim-roi-mirror-selected"),mirrorLabel=$("sim-roi-mirror-label");
  const laneSelected=(simRoiSelected==="RL"||simRoiSelected==="LL")&&caps.vision_profile==="city";
  if(mirrorControl)mirrorControl.classList.toggle("section-hide",!laneSelected);
  if(mirrorInput&&laneSelected)mirrorInput.checked=!!simRoiMirrors[simRoiSelected];
  if(mirrorLabel&&laneSelected)mirrorLabel.lastChild.textContent=" Mirror "+(simRoiSelected==="RL"?"right":"left")+" lane ROI before detection";
}
function fitSimulatorCameraFrame(){
  const frame=$("sim-camera-frame"),wrap=frame&&frame.parentElement;
  if(!frame||!wrap)return;
  const isAvis=caps.simulator_backend==="avis";
  // AVIS used to stretch the overlay canvas across the whole camera stage while
  // the image itself was letterboxed by object-fit:contain. That made normalized
  // ROI coordinates refer to a different rectangle than the visible image.
  if(!camera.naturalWidth||!camera.naturalHeight){
    if(isAvis&&simRoiCanvas){
      simRoiCanvas.style.visibility="hidden";
      simRoiCanvas.style.pointerEvents="none";
    }
    return;
  }
  const ratio=camera.naturalWidth/camera.naturalHeight;
  if(!Number.isFinite(ratio)||ratio<=0)return;
  const maxWidth=Math.max(1,wrap.clientWidth);
  const maxHeight=isAvis
    ? Math.max(1,wrap.clientHeight)
    : Math.max(180,window.innerHeight*0.68);
  let width=maxWidth,height=width/ratio;
  if(height>maxHeight){height=maxHeight;width=height*ratio;}
  if(isAvis){
    // Size the image frame itself to the decoded camera aspect ratio. The image
    // and ROI canvas now share exactly the same content rectangle (no letterbox
    // offset), so drawing and pointer hit-testing use identical coordinates.
    frame.style.position="absolute";
    frame.style.left="50%";
    frame.style.top="50%";
    frame.style.right="auto";
    frame.style.bottom="auto";
    frame.style.transform="translate(-50%, -50%)";
  }
  frame.style.width=width+"px";
  frame.style.height=height+"px";
  if(isAvis&&simRoiCanvas){
    simRoiCanvas.style.visibility="visible";
    simRoiUpdateSelection();
  }
  drawSimRoiOverlay();
}
function setCameraFeedStatus(message,kind){
  const el=$("camera-feed-status");if(!el)return;
  el.textContent=message||"";el.className="msg camera-feed-status"+(kind==="bad"?" bad":kind==="good"?" good":"");
}
async function refreshSimulatorCameraFrame(){
  if(cameraFramePollActive)return;
  cameraFramePollActive=true;
  try{
    const since=lastCameraFrameSequence===null?"":"&since="+encodeURIComponent(lastCameraFrameSequence);
    const response=await fetch("/video_feed_frame?t="+Date.now()+since,{cache:"no-store",headers:{"Accept":"image/jpeg"}});
    if(response.status===204){
      if(!camera.naturalWidth)setCameraFeedStatus("Waiting for the {{ caps.simulator_backend|upper }} camera adapter to publish its first frame (HTTP 204).");
      return;
    }
    if(!response.ok)throw new Error("Camera frame endpoint returned HTTP "+response.status+".");
    const contentType=response.headers.get("content-type")||"";
    if(!contentType.toLowerCase().startsWith("image/"))throw new Error("Camera endpoint returned "+(contentType||"an unknown content type")+", not an image.");
    const sequence=response.headers.get("X-Stream-Frame-Sequence");
    if(sequence!==null&&sequence===lastCameraFrameSequence)return;
    const blob=await response.blob();
    if(!blob.size)throw new Error("Camera endpoint returned an empty image.");
    const previous=cameraObjectUrl;
    cameraObjectUrl=URL.createObjectURL(blob);
    camera.src=cameraObjectUrl;
    if(previous)URL.revokeObjectURL(previous);
    lastCameraFrameSequence=sequence;
    setCameraFeedStatus("LIVE · frame "+(sequence!==null?sequence:"updated"),"good");
  }catch(error){
    setCameraFeedStatus("Camera feed request failed: "+(error.message||String(error)),"bad");
  }finally{cameraFramePollActive=false;}
}
function drawSimRoiOverlay(){
  if(!simRoiCanvas||!caps.supports_lane_roi)return;
  const frame=$("sim-camera-frame"),rect=frame&&frame.getBoundingClientRect();
  if(!rect||rect.width<2||rect.height<2)return;
  const dpr=Math.max(1,window.devicePixelRatio||1),w=rect.width,h=rect.height;
  const pixelW=Math.max(1,Math.round(w*dpr)),pixelH=Math.max(1,Math.round(h*dpr));
  if(simRoiCanvas.width!==pixelW||simRoiCanvas.height!==pixelH){simRoiCanvas.width=pixelW;simRoiCanvas.height=pixelH;}
  const ctx=simRoiCanvas.getContext("2d");ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);
  const master=$("sim-roi-overlay-toggle");if(master&&!master.checked)return;
  simRoiDefs.forEach(function(def){
    const visible=document.querySelector('[data-sim-roi-visible="'+def.id+'"]');if(visible&&!visible.checked)return;
    const b=simRoiBounds(def.id);if(!b)return;
    const polygon=simRoiPolygon(def.id,b),selected=def.id===simRoiSelected;
    const points=polygon.map(function(point){return [point[0]*w,point[1]*h];});
    ctx.save();ctx.fillStyle=def.color+"20";ctx.strokeStyle=def.color;ctx.lineWidth=selected?3:2;ctx.setLineDash(selected?[]:[7,4]);
    ctx.beginPath();ctx.moveTo(points[0][0],points[0][1]);points.slice(1).forEach(function(point){ctx.lineTo(point[0],point[1]);});ctx.closePath();ctx.fill();ctx.stroke();ctx.setLineDash([]);
    ctx.font="700 12px system-ui";const label=def.id+" · "+def.label;const labelW=ctx.measureText(label).width+12;
    const labelX=Math.min(w-labelW,Math.max(0,points[0][0]));
    ctx.fillStyle=def.color;ctx.fillRect(labelX,Math.max(0,points[0][1]-22),labelW,20);ctx.fillStyle="#07111a";ctx.fillText(label,labelX+6,Math.max(14,points[0][1]-8));
    if(selected){
      points.forEach(function(point){ctx.fillStyle="#f4f8fc";ctx.fillRect(point[0]-5,point[1]-5,10,10);ctx.strokeStyle=def.color;ctx.lineWidth=2;ctx.strokeRect(point[0]-5,point[1]-5,10,10);});
    }
    ctx.restore();
  });
}
function simRoiPoint(event){const r=simRoiCanvas.getBoundingClientRect();return{x:(event.clientX-r.left)/r.width,y:(event.clientY-r.top)/r.height,px:event.clientX-r.left,py:event.clientY-r.top,width:r.width,height:r.height};}
function simRoiClamp(value,min,max){return Math.max(min,Math.min(max,value));}
function simRoiPointerDown(event){
  if(!simRoiControlsEnabled||!$("sim-roi-overlay-toggle").checked)return;
  const p=simRoiPoint(event);let hit=null,corner=null,bounds=null;
  const ordered=[simRoiDefs.find(function(def){return def.id===simRoiSelected;})].concat(simRoiDefs.filter(function(def){return def.id!==simRoiSelected;})).filter(Boolean);
  for(let i=0;i<ordered.length;i++){
    const def=ordered[i],show=document.querySelector('[data-sim-roi-visible="'+def.id+'"]');if(show&&!show.checked)continue;
    const b=simRoiBounds(def.id);if(!b)continue;
    const polygon=simRoiPolygon(def.id,b);
    const handles={nw:polygon[0],ne:polygon[1],se:polygon[2],sw:polygon[3]};
    const key=Object.keys(handles).find(function(name){const point=handles[name];return Math.hypot(point[0]*p.width-p.px,point[1]*p.height-p.py)<=12;});
    const inside=simRoiContains(p.x,p.y,polygon);
    if(key||inside){hit=def.id;corner=key||null;bounds=b;break;}
  }
  if(!hit)return;
  simRoiSelected=hit;simRoiDrag={id:hit,mode:corner?"resize":"move",corner:corner,start:p,initial:Object.assign({},bounds)};
  simRoiCanvas.setPointerCapture(event.pointerId);simRoiUpdateSelection();drawSimRoiOverlay();event.preventDefault();
}
function simRoiPointerMove(event){
  if(!simRoiDrag)return;
  const p=simRoiPoint(event),drag=simRoiDrag,b=Object.assign({},drag.initial),dx=p.x-drag.start.x,dy=p.y-drag.start.y,minSize=.001;
  if(drag.mode==="move"){const width=b.right-b.left,height=b.bottom-b.top;b.left=simRoiClamp(b.left+dx,0,1-width);b.right=b.left+width;b.top=simRoiClamp(b.top+dy,0,1-height);b.bottom=b.top+height;}
  else{
    if(drag.corner==="nw"||drag.corner==="sw")b.left=simRoiClamp(b.left+dx,0,b.right-minSize);
    if(drag.corner==="ne"||drag.corner==="se")b.right=simRoiClamp(b.right+dx,b.left+minSize,1);
    if(drag.corner==="nw"||drag.corner==="ne")b.top=simRoiClamp(b.top+dy,0,b.bottom-minSize);
    if(drag.corner==="sw"||drag.corner==="se")b.bottom=simRoiClamp(b.bottom+dy,b.top+minSize,1);
  }
  simRoiWriteBounds(drag.id,b);drawSimRoiOverlay();setText("sim-roi-status","Unsaved ROI changes");
}
function simRoiPointerUp(){
  if(simRoiDrag){simRoiDrag=null;drawSimRoiOverlay();scheduleSimRoiSave(180);}
}
function simRoiCollectSettings(){
  const settings={};
  for(const def of simRoiDefs){
    const b=simRoiBounds(def.id);
    if(!b){
      const values={};
      Object.keys(def.fields).forEach(function(key){const el=$(def.fields[key]);values[key]=el&&el.value!==""?Number(el.value):NaN;});
      if(!Object.values(values).every(Number.isFinite)||Object.values(values).some(function(value){return value<0||value>1;})){
        return {error:def.label+" ROI coordinates must be finite numbers from 0 to 1 (for example, 0.1 means 10% of the image)."};
      }
      if(values.top>=values.bottom)return {error:def.label+" ROI top must be smaller than bottom."};
      if(values.left>=values.right)return {error:def.label+" ROI left must be smaller than right."};
      return {error:"Invalid "+def.label+" ROI bounds."};
    }
    const prefix=def.id+"_";
    Object.keys(def.fields).forEach(function(key){settings[prefix+({top:"TOP_ROI",bottom:"BOTTOM_ROI",left:"LEFT_ROI",right:"RIGHT_ROI"})[key]]=b[key];});
  }
  // Race/AVIS-Race exposes lane ROI geometry but not City-only mirror
  // controls. Sending these keys anyway makes the API reject the entire
  // otherwise-valid ROI patch for non-City profiles.
  if(caps.vision_profile==="city"){
    settings.RL_MIRRORED=!!simRoiMirrors.RL;
    settings.LL_MIRRORED=!!simRoiMirrors.LL;
  }
  return {settings:settings};
}
function scheduleSimRoiSave(delay){
  if(!simRoiControlsEnabled)return;
  if(simRoiSaveTimer!==null)clearTimeout(simRoiSaveTimer);
  setText("sim-roi-status","ROI changes pending · auto-save");
  simRoiSaveTimer=setTimeout(function(){simRoiSaveTimer=null;saveSimRoiSettings();},Math.max(0,Number(delay)||0));
}
async function saveSimRoiSettings(){
  if(!simRoiControlsEnabled){
    setText("sim-roi-status","Cannot save: Stream control is disabled. Enable STREAM_ALLOW_CONTROL and reload Workbench.");
    return false;
  }
  if(simRoiSaveInFlight){simRoiSaveQueued=true;return false;}
  const collected=simRoiCollectSettings();
  if(collected.error){setText("sim-roi-status","Not saved: "+collected.error);return false;}
  const button=$("sim-roi-save"),originalLabel=button?button.textContent:"Save now";
  simRoiSaveInFlight=true;
  if(button){button.disabled=true;button.textContent="Saving…";}
  setText("sim-roi-status","Saving ROI settings to "+mode+".sim.json…");
  try{
    const response=await fetch("/api/simulation/settings",{
      method:"POST",cache:"no-store",credentials:"same-origin",
      headers:{"Content-Type":"application/json","Accept":"application/json"},
      body:JSON.stringify({settings:collected.settings})
    });
    const raw=await response.text();
    let data={};
    try{data=raw?JSON.parse(raw):{};}catch(_){throw new Error("Server returned a non-JSON response (HTTP "+response.status+").");}
    if(!response.ok||!data.success)throw new Error(data.message||("HTTP "+response.status));

    // Read back the persisted profile after the POST. A 200 response alone
    // is not enough feedback for an editor: verify every submitted ROI value.
    const verifyResponse=await fetch("/api/simulation/settings",{cache:"no-store",credentials:"same-origin",headers:{"Accept":"application/json"}});
    const verifyRaw=await verifyResponse.text();
    let verify={};
    try{verify=verifyRaw?JSON.parse(verifyRaw):{};}catch(_){throw new Error("Save request succeeded, but the verification response was invalid.");}
    if(!verifyResponse.ok||!verify.success)throw new Error(verify.message||"Could not verify saved ROI settings.");
    const current=verify.settings||{};
    const mismatches=Object.keys(collected.settings).filter(function(key){
      const expected=collected.settings[key],actual=current[key];
      if(typeof expected==="number")return !Number.isFinite(Number(actual))||Math.abs(Number(actual)-expected)>0.00001;
      return actual!==expected;
    });
    if(mismatches.length)throw new Error("Server did not retain: "+mismatches.join(", "));
    setText("sim-roi-status","Saved and verified · "+mode+".sim.json");
    if(typeof window.showToast==="function")window.showToast("ROI settings saved and verified.");
    return true;
  }catch(error){
    setText("sim-roi-status","Save failed: "+(error.message||String(error)));
    return false;
  }finally{
    simRoiSaveInFlight=false;
    if(button){button.disabled=!simRoiControlsEnabled;button.textContent=originalLabel;}
    if(simRoiSaveQueued){simRoiSaveQueued=false;scheduleSimRoiSave(0);}
  }
}
function bindSimRoiEditor(){
  if(!caps.supports_lane_roi)return;
  // Saving must not depend on the optional canvas overlay being available.
  // The previous early return silently left the Save button without a handler
  // whenever the canvas could not be initialized.
  const saveButton=$("sim-roi-save");
  if(saveButton)saveButton.addEventListener("click",async function(event){
    event.preventDefault();
    if(simRoiSaveTimer!==null){clearTimeout(simRoiSaveTimer);simRoiSaveTimer=null;}
    await saveSimRoiSettings();
  });
  simRoiDefs.forEach(function(def){Object.values(def.fields).forEach(function(id){
    const el=$(id);if(!el)return;
    const changed=function(){drawSimRoiOverlay();scheduleSimRoiSave(700);};
    el.addEventListener("input",changed);
    el.addEventListener("change",changed);
    el.addEventListener("blur",function(){if(simRoiSaveTimer!==null)scheduleSimRoiSave(0);});
  });});
  if(!simRoiCanvas){setText("sim-roi-status","ROI numeric controls are active; overlay canvas is unavailable.");return;}
  document.querySelectorAll("[data-sim-roi-select]").forEach(function(button){button.addEventListener("click",function(){simRoiSelected=button.dataset.simRoiSelect;simRoiUpdateSelection();drawSimRoiOverlay();});});
  document.querySelectorAll("[data-sim-roi-visible]").forEach(function(input){input.addEventListener("change",drawSimRoiOverlay);});
  $("sim-roi-overlay-toggle").addEventListener("change",function(){simRoiUpdateSelection();drawSimRoiOverlay();});
  $("sim-roi-mirror-selected").addEventListener("change",function(){
    if(simRoiSelected!=="RL"&&simRoiSelected!=="LL")return;
    simRoiMirrors[simRoiSelected]=this.checked;scheduleSimRoiSave(100);
  });
  simRoiCanvas.addEventListener("pointerdown",simRoiPointerDown);simRoiCanvas.addEventListener("pointermove",simRoiPointerMove);
  simRoiCanvas.addEventListener("pointerup",simRoiPointerUp);simRoiCanvas.addEventListener("pointercancel",simRoiPointerUp);
  window.addEventListener("resize",drawSimRoiOverlay);camera.addEventListener("load",drawSimRoiOverlay);
  simRoiUpdateSelection();drawSimRoiOverlay();
}
bindSimRoiEditor();
