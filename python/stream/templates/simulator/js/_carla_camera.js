function setCameraStatus(message,bad){
  const el=$("camera-editor-status");if(!el)return;
  el.textContent=message||"";el.className="msg"+(bad?" bad":"");
}
const mountFields=[
  ["SIMULATOR_CAMERA_X","cam-x"],["SIMULATOR_CAMERA_Y","cam-y"],["SIMULATOR_CAMERA_Z","cam-z"],
  ["SIMULATOR_CAMERA_PITCH","cam-pitch"],["SIMULATOR_CAMERA_YAW","cam-yaw"],["SIMULATOR_CAMERA_ROLL","cam-roll"]
];
let cameraEditorOpen=false,cameraMoveTimer=null,cameraImageTimer=null,cameraStateTimer=null,cameraPreviewTimer=null;
let cameraPreviewChain=Promise.resolve(),cameraPreviewVersion=0;
let cameraHeldKeys=new Set(),cameraMovePending=false,cameraLookYaw=0,cameraLookPitch=0,cameraLastPointer=null;
let cameraControlMode="free";
function setCameraControlMode(mode){
  cameraControlMode=mode;
  const badge=$("camera-editor-mode");if(!badge)return;
  const modes={
    free:{label:"FREE-FLY · WORLD ROTATION",title:"Free camera mode: WASD/QE and mouse-look rotate or move the independent camera in CARLA world coordinates."},
    preview:{label:"MOUNT PREVIEW · VEHICLE-LOCAL",title:"Mount preview mode: slider values are vehicle-relative offsets and angles. The main Stream sensor has not changed until Save mount."},
    applied:{label:"STREAM MOUNT · APPLIED",title:"Applied mode: the main Stream RGB sensor has been recreated with the selected vehicle-relative camera mount."}
  };
  const selected=modes[mode]||modes.free;
  badge.textContent=selected.label;badge.title=selected.title;badge.dataset.mode=mode;
}
function updateCameraMountInputs(mount){
  if(!mount)return;
  mountFields.forEach(function(item){
    const key=item[0],id=item[1],el=$(id);if(!el||mount[key]===undefined)return;
    el.value=String(Number(mount[key]));
    const out=$(id+"-value");if(out)out.textContent=numeric(mount[key],2);
  });
}
function readCameraMount(){
  const out={};mountFields.forEach(function(item){out[item[0]]=Number($(item[1]).value);});return out;
}
function updateCameraMountOutputs(){
  mountFields.forEach(function(item){const el=$(item[1]),out=$(item[1]+"-value");if(el&&out)out.textContent=numeric(el.value,2);});
}
function renderCameraWorld(state){
  const mount=state&&state.mount;
  const stream=state&&state.stream_camera_transform;
  const world=state&&state.world_transform;
  if(mount)setText("camera-mount-readout","VEHICLE-RELATIVE MOUNT\nX "+numeric(mount.SIMULATOR_CAMERA_X,2)+" m · Y "+numeric(mount.SIMULATOR_CAMERA_Y,2)+" m · Z "+numeric(mount.SIMULATOR_CAMERA_Z,2)+" m\nPitch "+numeric(mount.SIMULATOR_CAMERA_PITCH,1)+"° · Yaw "+numeric(mount.SIMULATOR_CAMERA_YAW,1)+"° · Roll "+numeric(mount.SIMULATOR_CAMERA_ROLL,1)+"°");
  if(stream)setText("camera-stream-readout","STREAM RGB SENSOR · CARLA WORLD\nX "+numeric(stream.x,2)+" m · Y "+numeric(stream.y,2)+" m · Z "+numeric(stream.z,2)+" m\nPitch "+numeric(stream.pitch,1)+"° · Yaw "+numeric(stream.yaw,1)+"° · Roll "+numeric(stream.roll,1)+"°");
  if(world)setText("camera-world-readout","FREE PREVIEW · CARLA WORLD\nX "+numeric(world.x,2)+" m · Y "+numeric(world.y,2)+" m · Z "+numeric(world.z,2)+" m\nPitch "+numeric(world.pitch,1)+"° · Yaw "+numeric(world.yaw,1)+"° · Roll "+numeric(world.roll,1)+"°");
  // Keep the selected control mode stable while the state poll refreshes coordinates.
  setCameraControlMode(cameraControlMode);
}
async function cameraAction(action,payload,renderState){
  const response=await fetch("/api/simulation/carla-camera",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(Object.assign({action:action},payload||{})),cache:"no-store"});
  const data=await response.json().catch(function(){return {success:false,message:"Server returned an unreadable response"};});
  if(!response.ok||!data.success)throw new Error(data.message||"Camera editor operation failed");
  if(data.state&&renderState!==false)renderCameraWorld(data.state);
  return data.state||null;
}
async function pollCameraEditorState(){
  try{const response=await fetch("/api/simulation/carla-camera",{cache:"no-store"});const data=await response.json();if(!response.ok||!data.success)throw new Error(data.message||"Camera state unavailable");renderCameraWorld(data.state);}
  catch(error){setCameraStatus(error.message,true);}
}
function queueCameraMountPreview(){
  updateCameraMountOutputs();setCameraControlMode("preview");if(!cameraEditorOpen)return;
  const version=++cameraPreviewVersion;
  const transform=readCameraMount();
  clearTimeout(cameraPreviewTimer);
  cameraPreviewTimer=setTimeout(function(){
    cameraPreviewTimer=null;
    cameraPreviewChain=cameraPreviewChain.catch(function(){}).then(async function(){
      if(!cameraEditorOpen||version!==cameraPreviewVersion)return;
      try{
        const state=await cameraAction("preview_mount",{transform:transform,follow_mount:true},false);
        if(cameraEditorOpen&&version===cameraPreviewVersion){
          renderCameraWorld(state);
          setCameraStatus("Mount preview updated. The main Stream sensor is unchanged until you click Save mount.",false);
        }
      }catch(error){if(cameraEditorOpen&&version===cameraPreviewVersion)setCameraStatus(error.message,true);}
    });
  },110);
}
async function settleCameraMountPreviews(){
  cameraPreviewVersion++;
  clearTimeout(cameraPreviewTimer);cameraPreviewTimer=null;
  try{await cameraPreviewChain;}catch(error){/* preview errors are shown by the queued request */}
}
async function openCameraEditor(){
  if(!$("camera-editor-modal")||$("open-camera-editor").disabled)return;
  try{
    await settleCameraMountPreviews();
    const state=await cameraAction("open");
    cameraEditorOpen=true;$("camera-editor-modal").setAttribute("aria-hidden","false");
    if(state&&state.mount)updateCameraMountInputs(state.mount);
    setCameraControlMode("free");
    setCameraStatus("FREE-FLY mode: move and rotate the independent world camera. Use the mount sliders to switch to vehicle-local preview.",false);
    const refreshImage=function(){if(cameraEditorOpen)$("camera-editor-preview").src="/api/simulation/carla-camera/frame.jpg?t="+Date.now();};
    refreshImage();cameraImageTimer=setInterval(refreshImage,180);
    cameraStateTimer=setInterval(pollCameraEditorState,350);
    cameraHeldKeys.clear();cameraMovePending=false;cameraLookYaw=0;cameraLookPitch=0;
    cameraMoveTimer=setInterval(async function(){
      if(!cameraEditorOpen||cameraMovePending)return;
      let forward=(cameraHeldKeys.has("w")?1:0)-(cameraHeldKeys.has("s")?1:0);
      let right=(cameraHeldKeys.has("d")?1:0)-(cameraHeldKeys.has("a")?1:0);
      let up=(cameraHeldKeys.has("e")?1:0)-(cameraHeldKeys.has("q")?1:0);
      let yaw=(cameraHeldKeys.has("arrowright")?1:0)-(cameraHeldKeys.has("arrowleft")?1:0);
      let pitch=(cameraHeldKeys.has("arrowup")?1:0)-(cameraHeldKeys.has("arrowdown")?1:0);
      const speed=Number($("camera-move-speed").value)||.18;
      const factor=cameraHeldKeys.has("shift")?3:1;
      forward*=speed*factor;right*=speed*factor;up*=speed*factor;yaw*=1.4*factor;pitch*=1.2*factor;
      const lookYaw=Math.max(-8,Math.min(8,cameraLookYaw)),lookPitch=Math.max(-8,Math.min(8,cameraLookPitch));
      cameraLookYaw-=lookYaw;cameraLookPitch-=lookPitch;yaw+=lookYaw;pitch+=lookPitch;
      if(!forward&&!right&&!up&&!yaw&&!pitch)return;
      setCameraControlMode("free");
      cameraMovePending=true;
      try{await cameraAction("move",{forward:forward,right:right,up:up,yaw:yaw,pitch:pitch});}
      catch(error){setCameraStatus(error.message,true);}
      finally{cameraMovePending=false;}
    },70);
  }catch(error){setCameraStatus(error.message,true);status(error.message,false);}
}
async function closeCameraEditor(discard){
  if(!cameraEditorOpen)return;
  cameraEditorOpen=false;cameraHeldKeys.clear();cameraLastPointer=null;
  if(cameraMoveTimer)clearInterval(cameraMoveTimer);
  if(cameraImageTimer)clearInterval(cameraImageTimer);
  if(cameraStateTimer)clearInterval(cameraStateTimer);
  clearTimeout(cameraPreviewTimer);
  cameraMoveTimer=cameraImageTimer=cameraStateTimer=cameraPreviewTimer=null;
  $("camera-editor-modal").setAttribute("aria-hidden","true");
  $("camera-editor-preview").removeAttribute("src");
  await settleCameraMountPreviews();
  try{await cameraAction(discard?"discard":"close");setCameraStatus("Saved mount restored. CARLA remains STOPPED; press Start Run when the scene is ready.",false);}
  catch(error){status(error.message,false);}
}
function initCameraEditor(){
  if(!$("camera-editor-modal"))return;
  $("open-camera-editor").addEventListener("click",openCameraEditor);
  $("close-camera-editor").addEventListener("click",function(){closeCameraEditor(true);});
  $("camera-discard").addEventListener("click",function(){closeCameraEditor(true);});
  $("camera-editor-modal").addEventListener("click",function(event){if(event.target===$("camera-editor-modal"))closeCameraEditor(true);});
  $("camera-save-mount").addEventListener("click",async function(){
    try{await settleCameraMountPreviews();const state=await cameraAction("save_mount",{transform:readCameraMount()});if(state&&state.mount)updateCameraMountInputs(state.mount);setCameraControlMode("applied");setCameraStatus("Applied: the main Stream RGB sensor now uses this vehicle-local mount.",false);}
    catch(error){setCameraStatus(error.message,true);}
  });
  mountFields.forEach(function(item){$(item[1]).addEventListener("input",queueCameraMountPreview);});
  $("camera-snap-mount").addEventListener("click",async function(){try{const state=await cameraAction("snap_to_mount");setCameraControlMode("free");renderCameraWorld(state);setCameraStatus("FREE-FLY mode: the world camera is snapped to the current Stream camera position.",false);}catch(e){setCameraStatus(e.message,true);}});
  $("camera-use-view").addEventListener("click",async function(){try{const state=await cameraAction("use_view_as_mount");if(state&&state.mount)updateCameraMountInputs(state.mount);setCameraControlMode("preview");setCameraStatus("MOUNT PREVIEW mode: the free world-camera pose is now converted to vehicle-local offsets. Save mount to apply it to Stream.",false);}catch(e){setCameraStatus(e.message,true);}});
  $("camera-level-view").addEventListener("click",async function(){try{await cameraAction("level_view");setCameraControlMode("free");setCameraStatus("FREE-FLY mode: free camera horizon levelled.",false);}catch(e){setCameraStatus(e.message,true);}});
  $("camera-level-mount").addEventListener("click",function(){$("cam-pitch").value="0";$("cam-roll").value="0";queueCameraMountPreview();setCameraStatus("Mount pitch and roll set to zero. Save mount to persist.",false);});
  $("camera-reset-mount").addEventListener("click",function(){updateCameraMountInputs({"SIMULATOR_CAMERA_X":1.45,"SIMULATOR_CAMERA_Y":0,"SIMULATOR_CAMERA_Z":1.8,"SIMULATOR_CAMERA_PITCH":-8,"SIMULATOR_CAMERA_YAW":0,"SIMULATOR_CAMERA_ROLL":0});queueCameraMountPreview();});
  $("camera-restore-saved").addEventListener("click",async function(){try{await settleCameraMountPreviews();const state=await cameraAction("restore_mount");if(state&&state.mount)updateCameraMountInputs(state.mount);setCameraControlMode("applied");setCameraStatus("STREAM MOUNT · APPLIED: saved mount restored to the live Stream sensor.",false);}catch(e){setCameraStatus(e.message,true);}});
  $("camera-editor-preview").addEventListener("error",function(){if(cameraEditorOpen)setCameraStatus("Waiting for the CARLA fly-camera frame. Confirm that the simulator is ticking.",true);});
  const viewport=$("camera-editor-viewport");
  viewport.addEventListener("pointerdown",function(event){if(!cameraEditorOpen)return;setCameraControlMode("free");cameraLastPointer={x:event.clientX,y:event.clientY};viewport.classList.add("dragging");viewport.setPointerCapture(event.pointerId);event.preventDefault();});
  viewport.addEventListener("pointermove",function(event){if(!cameraLastPointer)return;setCameraControlMode("free");const dx=event.clientX-cameraLastPointer.x,dy=event.clientY-cameraLastPointer.y;cameraLastPointer={x:event.clientX,y:event.clientY};cameraLookYaw=Math.max(-30,Math.min(30,cameraLookYaw+dx*.24));cameraLookPitch=Math.max(-30,Math.min(30,cameraLookPitch-dy*.24));});
  function endLook(){cameraLastPointer=null;viewport.classList.remove("dragging");}
  viewport.addEventListener("pointerup",endLook);viewport.addEventListener("pointercancel",endLook);viewport.addEventListener("lostpointercapture",endLook);
  window.addEventListener("keydown",function(event){
    if(!cameraEditorOpen)return;
    if(event.key==="Escape"){event.preventDefault();closeCameraEditor(true);return;}
    if(["INPUT","SELECT","TEXTAREA"].includes((event.target&&event.target.tagName)||""))return;
    const key=event.key.toLowerCase();
    if(["w","a","s","d","q","e","shift","arrowleft","arrowright","arrowup","arrowdown"].includes(key)){cameraHeldKeys.add(key);event.preventDefault();}
  });
  window.addEventListener("keyup",function(event){cameraHeldKeys.delete(event.key.toLowerCase());});
  window.addEventListener("blur",function(){cameraHeldKeys.clear();});
}
