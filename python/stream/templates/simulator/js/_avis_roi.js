const simRoiDefs = [
  {id:"RL",label:"Right lane",color:"#48d7a4",fields:{top:"rl-top",bottom:"rl-bottom",left:"rl-left",right:"rl-right"}},
  {id:"LL",label:"Left lane",color:"#65a8ff",fields:{top:"ll-top",bottom:"ll-bottom",left:"ll-left",right:"ll-right"}},
  ...(caps.supports_sign_actions?[
    {id:"ST",label:"Sign detector",color:"#f472b6",fields:{top:"st-top",bottom:"st-bottom",left:"st-left",right:"st-right"}}
  ]:[]),
  ...(caps.simulator_backend==="avis"?[
    {id:"ML",label:"Left maneuver",color:"#c084fc",fields:{top:"ml-top",bottom:"ml-bottom",left:"ml-left",right:"ml-right"}},
    {id:"MR",label:"Right maneuver",color:"#fb923c",fields:{top:"mr-top",bottom:"mr-bottom",left:"mr-left",right:"mr-right"}}
  ]:[]),
  {id:"CW",label:"Crosswalk",color:"#f4bd63",fields:{top:"cw-top",bottom:"cw-bottom",left:"cw-left",right:"cw-right"}},
  {id:"SL",label:"Stop line",color:"#ffb45d",fields:{top:"sl-top",bottom:"sl-bottom",left:"sl-left",right:"sl-right"}},
  {id:"TL",label:"Traffic light",color:"#ff6685",fields:{top:"tl-top",bottom:"tl-bottom",left:"tl-left",right:"tl-right"}}
].filter(function(item){
  return (item.id!=="CW"||caps.supports_crosswalk_roi||caps.supports_crosswalk)
    &&(item.id!=="SL"||caps.supports_stop_line)
    &&(item.id!=="TL"||caps.supports_traffic_lights);
});
let simRoiGeometry={lane_roi_mode:"rectangle",cw_trapezoid_mode:false,rl_top_width_factor:.85,ll_top_width_factor:.85,cw_top_width_factor:.9,use_bev:false};
let simRoiSelected="RL", simRoiDrag=null, simRoiControlsEnabled=false;
let simRoiZoom=100;
let simRoiMirrors={RL:false,LL:false};
let simRoiSaveTimer=null,simRoiSaveInFlight=false,simRoiSaveQueued=false;
const simRoiCanvas=$("sim-roi-canvas");
const simRoiCameraStage=$("camera-stage");
if(caps.simulator_backend==="avis"&&simRoiCanvas&&simRoiCameraStage&&simRoiCanvas.parentElement!==simRoiCameraStage){
  // Keep the overlay in stage coordinates, independent from the fitted image box.
  simRoiCameraStage.appendChild(simRoiCanvas);
}
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
function simBevCorners(){
  const keys=["TL","TR","BR","BL"],corners={};
  for(const key of keys){
    const xEl=$("bev-"+key.toLowerCase()+"-x"),yEl=$("bev-"+key.toLowerCase()+"-y");
    const x=xEl&&xEl.value!==""?Number(xEl.value):NaN;
    const y=yEl&&yEl.value!==""?Number(yEl.value):NaN;
    if(!Number.isFinite(x)||!Number.isFinite(y)||x< -0.15||x>1.15||y< -0.15||y>1.15)return null;
    corners[key]={x:x,y:y};
  }
  return corners;
}
function simBevWriteCorners(corners){
  ["TL","TR","BR","BL"].forEach(function(key){
    const point=corners[key];if(!point)return;
    const xEl=$("bev-"+key.toLowerCase()+"-x"),yEl=$("bev-"+key.toLowerCase()+"-y");
    if(xEl)xEl.value=Number(point.x).toFixed(3);
    if(yEl)yEl.value=Number(point.y).toFixed(3);
  });
}
function simBevPolygon(corners){
  return ["TL","TR","BR","BL"].map(function(key){return [corners[key].x,corners[key].y];});
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
function simRoiVisibilityStorageKey(){
  return "self-driving-robot:simulator-roi-visibility:"+String(mode||"simulation");
}
function persistSimRoiVisibility(){
  try{
    const state={};
    const master=$("sim-roi-overlay-toggle");
    if(master)state.all=!!master.checked;
    document.querySelectorAll("[data-sim-roi-visible]").forEach(function(input){
      state[input.dataset.simRoiVisible]=!!input.checked;
    });
    window.localStorage.setItem(simRoiVisibilityStorageKey(),JSON.stringify(state));
  }catch(_){
    // Visibility preferences are best-effort when browser storage is unavailable.
  }
}
function restoreSimRoiVisibility(){
  try{
    const raw=window.localStorage.getItem(simRoiVisibilityStorageKey());
    if(!raw)return;
    const state=JSON.parse(raw);
    if(!state||typeof state!=="object")return;
    const master=$("sim-roi-overlay-toggle");
    if(master&&typeof state.all==="boolean")master.checked=state.all;
    document.querySelectorAll("[data-sim-roi-visible]").forEach(function(input){
      const key=input.dataset.simRoiVisible;
      if(typeof state[key]==="boolean")input.checked=state[key];
    });
  }catch(_){
    // Ignore malformed or unavailable local preferences and keep template defaults.
  }
}
function fitSimulatorCameraFrame(){
  const frame=$("sim-camera-frame"),wrap=simRoiCameraStage||frame&&frame.parentElement;
  if(!frame||!wrap)return;
  const isAvis=caps.simulator_backend==="avis";
  const master=$("sim-roi-overlay-toggle");
  const bevVisible=document.querySelector('[data-sim-roi-visible="BEV"]');
  const bevCornersForFit=caps.supports_bev?simBevCorners():null;
  const bevExtendsBeyondImage=!!(
    bevCornersForFit&&Object.values(bevCornersForFit).some(function(point){
      return point.x<0||point.x>1||point.y<0||point.y>1;
    })
  );
  const reserveBevSpace=!!(
    isAvis&&caps.supports_bev
    &&(!master||master.checked)
    &&(!bevVisible||bevVisible.checked)
    &&(simRoiSelected==="BEV"||bevExtendsBeyondImage)
  );
  // Reserve a 17% margin on every side so BEV handles can sit outside the image
  // without being clipped by the camera stage.
  const margin=reserveBevSpace?0.17:0;
  if(!camera.naturalWidth||!camera.naturalHeight){
    if(isAvis&&simRoiCanvas){
      simRoiCanvas.style.visibility="hidden";
      simRoiCanvas.style.pointerEvents="none";
    }
    return;
  }
  const ratio=camera.naturalWidth/camera.naturalHeight;
  if(!Number.isFinite(ratio)||ratio<=0)return;
  const fitScale=1+margin*2;
  const availableWidth=Math.max(1,wrap.clientWidth);
  const availableHeight=isAvis
    ?Math.max(1,wrap.clientHeight)
    :Math.max(180,window.innerHeight*0.68);
  let width=availableWidth/fitScale;
  let height=width/ratio;
  if(height>availableHeight/fitScale){
    height=availableHeight/fitScale;
    width=height*ratio;
  }
  const zoom=Math.max(50,Math.min(100,Number(simRoiZoom)||100))/100;
  width*=zoom;
  height*=zoom;
  if(isAvis){
    frame.style.position="absolute";
    frame.style.left="50%";
    frame.style.top="50%";
    frame.style.right="auto";
    frame.style.bottom="auto";
    frame.style.transform="translate(-50%, -50%)";
    frame.style.margin="0";
    frame.style.maxWidth="none";
    frame.style.maxHeight="none";
    frame.style.overflow="visible";
  }
  frame.style.width=width+"px";
  frame.style.height=height+"px";
  if(isAvis&&simRoiCanvas){
    // The canvas spans the whole camera stage. All ROI coordinates are mapped
    // from the actual fitted image rectangle into this stable stage rectangle.
    simRoiCanvas.style.position="absolute";
    simRoiCanvas.style.inset="0";
    simRoiCanvas.style.left="0";
    simRoiCanvas.style.top="0";
    simRoiCanvas.style.right="0";
    simRoiCanvas.style.bottom="0";
    simRoiCanvas.style.width="100%";
    simRoiCanvas.style.height="100%";
    simRoiCanvas.style.zIndex="2";
    simRoiCanvas.style.visibility="visible";
    simRoiUpdateSelection();
  }
  const zoomValue=$("sim-roi-zoom-value");
  if(zoomValue)zoomValue.textContent=Math.round(zoom*100)+"%"+(zoom>=0.999?" · fit":" · zoomed out");
  const zoomInput=$("sim-roi-zoom");
  if(zoomInput&&Number(zoomInput.value)!==Math.round(zoom*100))zoomInput.value=String(Math.round(zoom*100));
  drawSimRoiOverlay();
}
function setCameraFeedStatus(message,kind){
  const el=$("camera-feed-status");if(!el)return;
  el.textContent=message||"";el.className="msg camera-feed-status"+(kind==="bad"?" bad":kind==="good"?" good":"");
}
async function refreshSimulatorCameraFrame(){
  if(document.hidden||cameraFramePollActive)return;
  cameraFramePollActive=true;
  try{
    const since=lastCameraFrameSequence===null?"":"?since="+encodeURIComponent(lastCameraFrameSequence);
    const response=await fetch("/video_feed_frame"+since,{cache:"no-store",headers:{"Accept":"image/jpeg"}});
    if(response.status===204){
      const unchangedSequence=response.headers.get("X-Stream-Frame-Sequence");
      if(unchangedSequence!==null)lastCameraFrameSequence=unchangedSequence;
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
  const frame=$("sim-camera-frame"),frameRect=frame&&frame.getBoundingClientRect();
  const canvasRect=simRoiCanvas.getBoundingClientRect();
  if(!frameRect||frameRect.width<2||frameRect.height<2||canvasRect.width<2||canvasRect.height<2)return;
  const dpr=Math.max(1,window.devicePixelRatio||1);
  const frameW=frameRect.width,frameH=frameRect.height;
  const canvasW=canvasRect.width,canvasH=canvasRect.height;
  const originX=frameRect.left-canvasRect.left,originY=frameRect.top-canvasRect.top;
  const pixelW=Math.max(1,Math.round(canvasW*dpr)),pixelH=Math.max(1,Math.round(canvasH*dpr));
  if(simRoiCanvas.width!==pixelW||simRoiCanvas.height!==pixelH){
    simRoiCanvas.width=pixelW;simRoiCanvas.height=pixelH;
  }
  const ctx=simRoiCanvas.getContext("2d");
  ctx.setTransform(dpr,0,0,dpr,0,0);
  ctx.clearRect(0,0,canvasW,canvasH);
  const master=$("sim-roi-overlay-toggle");
  if(master&&!master.checked)return;
  function mapPoint(point){
    return [originX+point[0]*frameW,originY+point[1]*frameH];
  }
  function drawLabel(point,label,color){
    ctx.font="700 12px system-ui";
    const labelW=ctx.measureText(label).width+12;
    const labelX=simRoiClamp(point[0]+originX,4,Math.max(4,canvasW-labelW-4));
    const labelY=simRoiClamp(point[1]+originY-22,2,Math.max(2,canvasH-22));
    ctx.fillStyle=color;ctx.fillRect(labelX,labelY,labelW,20);
    ctx.fillStyle="#07111a";ctx.fillText(label,labelX+6,labelY+14);
  }

  simRoiDefs.forEach(function(def){
    const visible=document.querySelector('[data-sim-roi-visible="'+def.id+'"]');
    if(visible&&!visible.checked)return;
    const b=simRoiBounds(def.id);if(!b)return;
    const polygon=simRoiPolygon(def.id,b),selected=def.id===simRoiSelected;
    const points=polygon.map(mapPoint);
    ctx.save();ctx.fillStyle=def.color+"20";ctx.strokeStyle=def.color;
    ctx.lineWidth=selected?3:2;ctx.setLineDash(selected?[]:[7,4]);
    ctx.beginPath();ctx.moveTo(points[0][0],points[0][1]);
    points.slice(1).forEach(function(point){ctx.lineTo(point[0],point[1]);});
    ctx.closePath();ctx.fill();ctx.stroke();ctx.setLineDash([]);
    drawLabel(polygon[0],def.id+" · "+def.label,def.color);
    if(selected){
      points.forEach(function(point){
        ctx.fillStyle="#f4f8fc";ctx.fillRect(point[0]-5,point[1]-5,10,10);
        ctx.strokeStyle=def.color;ctx.lineWidth=2;ctx.strokeRect(point[0]-5,point[1]-5,10,10);
      });
    }
    ctx.restore();
  });

  if(caps.supports_bev){
    const visible=document.querySelector('[data-sim-roi-visible="BEV"]');
    const corners=simBevCorners();
    if(corners&&(!visible||visible.checked)){
      const selected=simRoiSelected==="BEV";
      const polygon=simBevPolygon(corners),points=polygon.map(mapPoint);
      const bevColor="#c084fc";
      ctx.save();
      ctx.fillStyle=simRoiGeometry.use_bev?"#c084fc24":"#c084fc10";
      ctx.strokeStyle=bevColor;ctx.lineWidth=selected?3:2;
      ctx.setLineDash(selected?[]:(simRoiGeometry.use_bev?[]:[5,5]));
      ctx.beginPath();ctx.moveTo(points[0][0],points[0][1]);
      points.slice(1).forEach(function(point){ctx.lineTo(point[0],point[1]);});
      ctx.closePath();ctx.fill();ctx.stroke();ctx.setLineDash([]);
      drawLabel(polygon[0],"BEV source · "+(simRoiGeometry.use_bev?"ON":"OFF"),bevColor);
      if(selected){
        points.forEach(function(point){
          ctx.fillStyle="#f4f8fc";ctx.fillRect(point[0]-6,point[1]-6,12,12);
          ctx.strokeStyle=bevColor;ctx.lineWidth=2;ctx.strokeRect(point[0]-6,point[1]-6,12,12);
        });
      }
      ctx.restore();
    }
  }
}
function simRoiPoint(event){const frame=$("sim-camera-frame"),r=frame&&frame.getBoundingClientRect();if(!r||r.width<1||r.height<1)return{x:0,y:0,px:0,py:0,width:1,height:1};return{x:(event.clientX-r.left)/r.width,y:(event.clientY-r.top)/r.height,px:event.clientX-r.left,py:event.clientY-r.top,width:r.width,height:r.height};}
function simRoiClamp(value,min,max){return Math.max(min,Math.min(max,value));}
function simRoiPointerDown(event){
  if(!simRoiControlsEnabled||!$("sim-roi-overlay-toggle").checked)return;
  const p=simRoiPoint(event);let hit=null,corner=null,bounds=null;
  function tryHitBev(){
    if(!caps.supports_bev)return false;
    const visible=document.querySelector('[data-sim-roi-visible="BEV"]');
    if(visible&&!visible.checked)return false;
    const corners=simBevCorners();if(!corners)return false;
    const polygon=simBevPolygon(corners);
    const key=["TL","TR","BR","BL"].find(function(name){
      const point=corners[name];
      return Math.hypot(point.x*p.width-p.px,point.y*p.height-p.py)<=12;
    });
    if(key||simRoiContains(p.x,p.y,polygon)){
      hit="BEV";corner=key||null;bounds=corners;return true;
    }
    return false;
  }
  if(simRoiSelected==="BEV")tryHitBev();
  if(!hit){
    const ordered=[simRoiDefs.find(function(def){return def.id===simRoiSelected;})]
      .concat(simRoiDefs.filter(function(def){return def.id!==simRoiSelected;})).filter(Boolean);
    for(let i=0;i<ordered.length;i++){
      const def=ordered[i],show=document.querySelector('[data-sim-roi-visible="'+def.id+'"]');
      if(show&&!show.checked)continue;
      const b=simRoiBounds(def.id);if(!b)continue;
      const polygon=simRoiPolygon(def.id,b);
      const handles={nw:polygon[0],ne:polygon[1],se:polygon[2],sw:polygon[3]};
      const key=Object.keys(handles).find(function(name){
        const point=handles[name];
        return Math.hypot(point[0]*p.width-p.px,point[1]*p.height-p.py)<=12;
      });
      if(key||simRoiContains(p.x,p.y,polygon)){
        hit=def.id;corner=key||null;bounds=b;break;
      }
    }
  }
  if(!hit)tryHitBev();
  if(!hit)return;
  simRoiSelected=hit;
  simRoiDrag={id:hit,mode:corner?"resize":"move",corner:corner,start:p,initial:JSON.parse(JSON.stringify(bounds))};
  simRoiCanvas.setPointerCapture(event.pointerId);
  simRoiUpdateSelection();drawSimRoiOverlay();event.preventDefault();
}
function simRoiPointerMove(event){
  if(!simRoiDrag)return;
  const p=simRoiPoint(event),drag=simRoiDrag,dx=p.x-drag.start.x,dy=p.y-drag.start.y;
  if(drag.id==="BEV"){
    const corners=JSON.parse(JSON.stringify(drag.initial));
    if(drag.mode==="resize"){
      const point=corners[drag.corner];
      point.x=simRoiClamp(point.x+dx,-0.15,1.15);
      point.y=simRoiClamp(point.y+dy,-0.15,1.15);
    }else{
      const values=Object.values(corners);
      const minX=Math.min.apply(null,values.map(function(point){return point.x;}));
      const maxX=Math.max.apply(null,values.map(function(point){return point.x;}));
      const minY=Math.min.apply(null,values.map(function(point){return point.y;}));
      const maxY=Math.max.apply(null,values.map(function(point){return point.y;}));
      const shiftX=simRoiClamp(dx,-0.15-minX,1.15-maxX);
      const shiftY=simRoiClamp(dy,-0.15-minY,1.15-maxY);
      Object.keys(corners).forEach(function(key){
        corners[key].x+=shiftX;corners[key].y+=shiftY;
      });
    }
    simBevWriteCorners(corners);
  }else{
    const b=Object.assign({},drag.initial),minSize=.001;
    if(drag.mode==="move"){
      const width=b.right-b.left,height=b.bottom-b.top;
      b.left=simRoiClamp(b.left+dx,0,1-width);b.right=b.left+width;
      b.top=simRoiClamp(b.top+dy,0,1-height);b.bottom=b.top+height;
    }else{
      if(drag.corner==="nw"||drag.corner==="sw")b.left=simRoiClamp(b.left+dx,0,b.right-minSize);
      if(drag.corner==="ne"||drag.corner==="se")b.right=simRoiClamp(b.right+dx,b.left+minSize,1);
      if(drag.corner==="nw"||drag.corner==="ne")b.top=simRoiClamp(b.top+dy,0,b.bottom-minSize);
      if(drag.corner==="sw"||drag.corner==="se")b.bottom=simRoiClamp(b.bottom+dy,b.top+minSize,1);
    }
    simRoiWriteBounds(drag.id,b);
  }
  drawSimRoiOverlay();setText("sim-roi-status","Unsaved ROI changes");
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
    const prefix=def.id==="SL"?"SIMULATOR_STOP_LINE_":def.id+"_";
    Object.keys(def.fields).forEach(function(key){
      settings[prefix+({top:"TOP_ROI",bottom:"BOTTOM_ROI",left:"LEFT_ROI",right:"RIGHT_ROI"})[key]]=b[key];
    });
  }
  if(caps.supports_bev){
    const corners=simBevCorners();
    if(!corners)return {error:"BEV source corners must be finite coordinates from -0.15 to 1.15."};
    ["TL","TR","BR","BL"].forEach(function(key){
      settings["BEV_SRC_"+key+"_X"]=corners[key].x;
      settings["BEV_SRC_"+key+"_Y"]=corners[key].y;
    });
  }
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
  if(caps.supports_bev){
    ["bev-tl-x","bev-tl-y","bev-tr-x","bev-tr-y","bev-br-x","bev-br-y","bev-bl-x","bev-bl-y"].forEach(function(id){
      const input=$(id);if(!input)return;
      const changed=function(){drawSimRoiOverlay();scheduleSimRoiSave(700);};
      input.addEventListener("input",changed);
      input.addEventListener("change",changed);
      input.addEventListener("blur",function(){if(simRoiSaveTimer!==null)scheduleSimRoiSave(0);});
    });
    const useBev=$("use-bev");
    if(useBev)useBev.addEventListener("change",function(){
      simRoiGeometry.use_bev=!!this.checked;drawSimRoiOverlay();
    });
  }

  const zoomInput=$("sim-roi-zoom");
  if(zoomInput)zoomInput.addEventListener("input",function(){
    simRoiZoom=Math.max(50,Math.min(100,Number(this.value)||100));
    fitSimulatorCameraFrame();
  });
  const fitButton=$("sim-roi-fit");
  if(fitButton)fitButton.addEventListener("click",function(){
    simRoiZoom=100;
    if(zoomInput)zoomInput.value="100";
    fitSimulatorCameraFrame();
  });

  if(!simRoiCanvas){
    setText("sim-roi-status","ROI numeric controls are active; overlay canvas is unavailable.");
    return;
  }
  document.querySelectorAll("[data-sim-roi-select]").forEach(function(button){
    button.addEventListener("click",function(){
      simRoiSelected=button.dataset.simRoiSelect;
      fitSimulatorCameraFrame();
    });
  });
  restoreSimRoiVisibility();
  document.querySelectorAll("[data-sim-roi-visible]").forEach(function(input){input.addEventListener("change",function(){persistSimRoiVisibility();if(input.dataset.simRoiVisible==="BEV")fitSimulatorCameraFrame();else drawSimRoiOverlay();});});
  $("sim-roi-overlay-toggle").addEventListener("change",function(){persistSimRoiVisibility();simRoiUpdateSelection();fitSimulatorCameraFrame();});
  $("sim-roi-mirror-selected").addEventListener("change",function(){
    if(simRoiSelected!=="RL"&&simRoiSelected!=="LL")return;
    simRoiMirrors[simRoiSelected]=this.checked;scheduleSimRoiSave(100);
  });
  simRoiCanvas.addEventListener("pointerdown",simRoiPointerDown);
  simRoiCanvas.addEventListener("pointermove",simRoiPointerMove);
  simRoiCanvas.addEventListener("pointerup",simRoiPointerUp);
  simRoiCanvas.addEventListener("pointercancel",simRoiPointerUp);
  simRoiCanvas.addEventListener("lostpointercapture",simRoiPointerUp);
  window.addEventListener("resize",fitSimulatorCameraFrame);camera.addEventListener("load",fitSimulatorCameraFrame);
  document.addEventListener("visibilitychange",function(){
    if(document.hidden&&simRoiSaveTimer!==null){
      clearTimeout(simRoiSaveTimer);simRoiSaveTimer=null;
      saveSimRoiSettings();
    }
  });
  window.addEventListener("pagehide",function(){
    const pending=simRoiSaveTimer!==null||simRoiSaveQueued||simRoiSaveInFlight;
    if(simRoiSaveTimer!==null){clearTimeout(simRoiSaveTimer);simRoiSaveTimer=null;}
    if(!pending||!simRoiControlsEnabled)return;
    const collected=simRoiCollectSettings();
    if(collected.error)return;
    // Submit the last drag position even when navigation closes the editor
    // before the debounce timer or normal verification request can finish.
    fetch("/api/simulation/settings",{
      method:"POST",cache:"no-store",credentials:"same-origin",keepalive:true,
      headers:{"Content-Type":"application/json","Accept":"application/json"},
      body:JSON.stringify({settings:collected.settings})
    }).catch(function(){});
  });
  simRoiUpdateSelection();fitSimulatorCameraFrame();
}
bindSimRoiEditor();
