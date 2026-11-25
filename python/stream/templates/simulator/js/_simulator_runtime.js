async function setCarlaRunMode(action){
  const start=$("carla-run-start"),stop=$("carla-run-stop"),message=$("carla-run-message");
  if(start)start.disabled=true;if(stop)stop.disabled=true;
  if(message){message.textContent=action==="start"?"Starting autonomous run…":"Applying brake and stopping…";message.className="sim-run-feedback";}
  try{
    const response=await fetch("/api/simulation/run-mode",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action:action})});
    const data=await response.json();
    if(!response.ok||!data.success)throw new Error(data.message||"Could not change simulator run mode");
    if(message){message.textContent=data.message||"Run mode updated.";message.className="sim-run-feedback good";}
    await poll();
  }catch(error){
    if(message){message.textContent=error.message||String(error);message.className="sim-run-feedback bad";}
    if(start)start.disabled=!simRoiControlsEnabled;if(stop)stop.disabled=!simRoiControlsEnabled;
  }
}
if($("carla-run-start"))$("carla-run-start").addEventListener("click",function(){setCarlaRunMode("start");});
if($("carla-run-stop"))$("carla-run-stop").addEventListener("click",function(){setCarlaRunMode("stop");});

async function poll(){
  try{
    const response=await fetch("/api/simulation/state",{cache:"no-store"});
    const d=await response.json();
    if(!response.ok) throw new Error(d.message||"Simulation runtime unavailable");
    $("connection-led").className="led"+(d.connected?" on":" error");
    setText("connection-label",d.connected?"Connected · "+d.backend.toUpperCase():"Waiting for simulator");
    setText("frame-age",d.frame_age_ms===null?"No frame":numeric(d.frame_age_ms,0)+" ms old");
    const imageInfo=d.image||{};
    const sensorInfo=d.camera_sensor||{};
    if(caps.simulator_backend==="avis"){
    }
    if($("camera-image-state")){
      const cameraText=imageInfo.width?((imageInfo.looks_black?"BLACK FRAME · ":"LIVE · ")+imageInfo.width+"×"+imageInfo.height+" · "+numeric(imageInfo.mean_intensity,1)+" avg · "+String(imageInfo.source||"camera").toUpperCase()):"Waiting for camera frame";
      setText("camera-image-state",cameraText);
      $("camera-image-state").className="pill"+(imageInfo.looks_black?" error":" live");
    }
    const cameraDiagnostic=$("camera-diagnostic");
    const processing=d.processing||{};
    if(cameraDiagnostic){
      let detail="";
      let diagnosticError=false;
      if(caps.simulator_backend==="avis"){
        const responseInfo=sensorInfo.response||{};
        const frameCount=Number(sensorInfo.frame_count||0);
        const frameAge=Number(sensorInfo.last_frame_age_ms);
        const ageKnown=sensorInfo.last_frame_age_ms!==null&&sensorInfo.last_frame_age_ms!==undefined&&Number.isFinite(frameAge);
        if(!sensorInfo.connected){
          detail="AVIS LINK OFFLINE · reconnecting · autonomous motion disarmed";
          diagnosticError=true;
        }else if(responseInfo.image_decoded===true&&!imageInfo.looks_black){
          detail="CAMERA LIVE · "+frameCount.toLocaleString()+" frames · "+(ageKnown?numeric(frameAge,0)+" ms ago":"frame received");
        }else if(imageInfo.looks_black){
          detail="CAMERA IMAGE IS BLACK · check the simulator camera output";
          diagnosticError=true;
        }else if(frameCount>0){
          detail="WAITING FOR A VALID FRAME · last good frame "+(ageKnown?numeric(frameAge,0)+" ms ago":"age unknown");
          diagnosticError=ageKnown&&frameAge>1500;
        }else{
          detail="CONNECTED · waiting for the first decodable camera frame";
          diagnosticError=true;
        }
        if(sensorInfo.reconnect_attempts&&!sensorInfo.connected)detail+=" · reconnect attempts "+sensorInfo.reconnect_attempts;
      }else{
        detail="CARLA camera waiting for frames";
        if(sensorInfo.rendering_error){detail="RENDERER ERROR · "+sensorInfo.rendering_error;diagnosticError=true;}
        else if(sensorInfo.no_rendering_mode===true){detail="NO-RENDERING MODE · RGB camera output is disabled";diagnosticError=true;}
        else if(sensorInfo.decode_error){detail="CAMERA DECODE ERROR · "+sensorInfo.decode_error;diagnosticError=true;}
        else if(Number(sensorInfo.callback_count||0)>0){
          detail="RGB CAMERA LIVE · "+String(sensorInfo.callback_count)+" callbacks · "+numeric(sensorInfo.last_frame_age_ms,0)+" ms ago";
        }else if(Number(sensorInfo.callback_count||0)===0&&sensorInfo.sensor_spawned){
          detail="CAMERA ACTOR READY · waiting for the first RGB callback";
          diagnosticError=true;
        }
      }
      cameraDiagnostic.textContent=detail;
      cameraDiagnostic.className="status-message camera-diagnostic"+(diagnosticError?" error":"");
    }
    const performance=$("camera-performance");
    if(performance){
      const perf=[];
      if(Number.isFinite(Number(processing.lane_fps)))perf.push("LOOP "+numeric(processing.lane_fps,1)+"/"+numeric(processing.target_fps,0)+" FPS");
      if(Number.isFinite(Number(processing.detection_ms)))perf.push("DETECT "+numeric(processing.detection_ms,1)+" ms");
      if(Number.isFinite(Number(processing.debug_render_ms)))perf.push("DRAW "+numeric(processing.debug_render_ms,1)+" ms");
      if(Number(processing.camera_frames_skipped||0)>0)perf.push("SKIPPED "+String(processing.camera_frames_skipped));
      performance.textContent=perf.length?perf.join("   ·   "):"Loop — FPS   ·   Detect — ms   ·   Draw — ms";
    }
    if($("carla-run-state")){
      const enabled=!!d.run_enabled;
      setText("carla-run-state",enabled?"AUTONOMOUS RUNNING":"STOPPED · MANUAL START REQUIRED");
      $("carla-run-state").className="pill carla-run-state "+(enabled?"running":"stopped");
      if($("carla-run-start"))$("carla-run-start").disabled=!simRoiControlsEnabled||!d.connected||enabled;
      if($("carla-run-stop"))$("carla-run-stop").disabled=!simRoiControlsEnabled||!enabled;
    }
    setText("lane-value",d.lane_type||"none");
    setText("lane-valid",d.perception_valid?"Perception valid":"Invalid lane estimate · safety policy applies");
    const tracking=d.line_tracking||{};
    const trackingState=$("line-tracking-state");
    const trackingDetail=$("line-tracking-detail");
    if(trackingState){
      const state=String(tracking.state||"DISABLED").toUpperCase();
      trackingState.textContent=state;
      trackingState.classList.toggle("tracking-degraded",state!=="TRACKING");
      trackingState.classList.toggle("tracking-lost",state==="LOST"||state==="ACQUIRING_PAIR");
    }
    if(trackingDetail){
      if(tracking.enabled){
        const sideLabel=side=>{
          if(!side)return "—";
          const status=String(side.status||"UNKNOWN").replace("LOST · INFERRED","INFERRED");
          const id=side.track_id===null||side.track_id===undefined?"":" #"+side.track_id;
          const pending=Number(side.pending_hits||0);
          const confirm=pending>0?" "+pending+"/"+Number(side.pending_required||3):"";
          const missed=status==="INFERRED"||status==="COASTING"?" "+Number(side.missed_frames||0)+"f":"";
          return status+id+confirm+missed;
        };
        const width=Number.isFinite(Number(tracking.lane_width_px))?
          " · width "+numeric(tracking.lane_width_px,0)+" px":"";
        trackingDetail.textContent="L "+sideLabel(tracking.left)+" · R "+sideLabel(tracking.right)+width;
      }else if(String(tracking.state||"").startsWith("UNSUPPORTED")){
        trackingDetail.textContent=tracking.reason||"Tracking is unsupported by the active detector.";
      }else{
        trackingDetail.textContent="Temporal lane tracking is disabled";
      }
    }
    if($("avis-behavior-value")){
      const behavior=d.simulation_behavior||{}, obstacle=behavior.obstacle||{};
      const state=String(obstacle.state||"CLEAR").toUpperCase();
      setText("avis-behavior-value",state.replace(/_/g," "));
      const details=[];
      if(caps.supports_obstacle_avoidance){
        details.push("Lane change "+(!obstacle.enabled?"off":state.toLowerCase()+(obstacle.direction?" · "+obstacle.direction:"")));
        const ranges=obstacle.ranges_cm||{};
        const rangeText=value=>value==null?"—":numeric(value,0);
        details.push("Ranges L/F/R "+rangeText(ranges.left)+"/"+rangeText(ranges.front)+"/"+rangeText(ranges.right)+" cm");
        const rangeSafety=(d.sensors||{}).range_safety||{};
        if(caps.simulator_backend==="avis"&&rangeSafety.status){
          const frontState=rangeSafety.status==="clear"
            ? "CLEAR"
            : "BRAKE · "+(rangeSafety.reason||rangeSafety.status)
              +(rangeSafety.stop_latched?" · run disarmed":"");
          details.push("Independent front guard "+frontState);
        }
        if(obstacle.minimum_pass_distance_cm!=null){
          details.push("Pass "+numeric(obstacle.distance_since_shift_cm,0)+"/"+numeric(obstacle.minimum_pass_distance_cm,0)+" cm");
        }
        details.push("Vision lane geometry "+(obstacle.lane_geometry_active?"active":"fallback profile"));
        if(obstacle.lane_geometry_active&&obstacle.lane_width_px!=null){
          details.push("Lane error "+numeric(obstacle.lane_error_px,0)+" / width "+numeric(obstacle.lane_width_px,0)+" px");
        }
        if(obstacle.reason)details.push(obstacle.reason);
      }
      if(caps.supports_stop_line){
        details.push("Stop line "+(!behavior.stop_line_enabled?"off":behavior.stop_line_waiting?"HOLD":behavior.stop_line_armed?"armed":"passed"));
      }
      if(caps.supports_traffic_lights){
        details.push("Light "+(!behavior.traffic_light_enabled?"off":behavior.traffic_light||"unknown"));
      }
      if(caps.supports_sign_actions){
        details.push("Sign "+(behavior.sign_label||"none")+(behavior.park_latched?" · PARK":""));
      }
      if(behavior.sign_detector_error)details.push("Detector error");
      setText("avis-behavior-detail",details.join(" · ")||"No active AVIS behavior");
    }
    setText("speed-value",numeric(d.speed_kmh,1)+" km/h");
    setText("steer-value",caps.simulator_backend==="avis"
      ? numeric(d.steering_normalized*100,0)+"% ("+numeric(d.steering_angle,1)+"° vision)"
      : numeric(d.steering_angle,1)+"° / "+numeric(d.steering_normalized,2));
    setText("motion-value",numeric(d.command.throttle,2)+" / "+numeric(d.command.brake,2));
    setText("motion-reason",d.command.reason||"");
    setText("encoder-count",String(d.virtual_io.pulses||0));
    setText("encoder-distance",numeric(d.virtual_io.distance_cm,1)+" cm");
    const err=$("runtime-error");
    if(err){
      err.textContent=d.error||"";
      err.classList.toggle("visible",!!d.error);
    }
    if(caps.supports_lidar){
      setText("lidar-count",numeric(d.sensors.lidar_point_count,0)+" points");
      setText("lidar-note",d.sensors.lidar_available?"Ray-cast LiDAR active · nearest point "+(d.sensors.lidar_nearest_m===null?"—":numeric(d.sensors.lidar_nearest_m,1)+" m"):"LiDAR has not delivered a packet or is disabled.");
      drawLidar(d.sensors.lidar_points_xy||[]);
    }
    if(caps.supports_range_sensors) renderRanges(d.sensors.ranges_cm||{},d.frame_age_ms);
    renderEvents(d.events||[]);
  }catch(error){
    $("connection-led").className="led error";setText("connection-label","Disconnected / waiting");
    const box=$("runtime-error");box.textContent=error.message;box.classList.add("visible");
  }
}
$("settings-form").addEventListener("submit",async function(event){
  event.preventDefault();
  if(!simulatorSettingsReady){status("Settings have not finished loading. Saving is disabled until the saved values are ready.",false);return;}
  status("Validating active settings…");
  try{
    const s=collectSimulatorSettings();
    status("Saving settings…");
    const response=await fetch("/api/simulation/settings",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({settings:s})});
    const data=await response.json();
    if(!response.ok||!data.success)throw new Error(data.message||"Save failed");
    status(data.message+(data.restart_required&&data.restart_required.length?" Restart required for: "+data.restart_required.join(", "):""),true);
    await loadSettings();
  }catch(error){status(error.message,false);}
});
$("reload-settings").addEventListener("click",function(){loadSettings().then(function(){status("Loaded saved settings.",true);}).catch(function(e){status(e.message,false);});});
$("refresh").addEventListener("click",function(){poll();});
const clearEventsButton=$("clear-events");
if(clearEventsButton)clearEventsButton.addEventListener("click",function(){
 const consoleEl=$("event-console");if(consoleEl)consoleEl.replaceChildren();
 eventKeys=[];seenEvents.clear();
});
camera.addEventListener("error",function(){
  camera.alt="The latest simulator camera JPEG could not be decoded.";
  if(caps.simulator_backend==="avis"&&simRoiCanvas){
    simRoiCanvas.style.visibility="hidden";
    simRoiCanvas.style.pointerEvents="none";
  }
});
camera.addEventListener("load",fitSimulatorCameraFrame);
window.addEventListener("resize",fitSimulatorCameraFrame);
// The camera stage height also changes when the bottom workbench dock is resized.
// Observe the stage itself so the decoded image and ROI overlay are refitted together.
let cameraStageResizeObserver=null;
const cameraStageForResize=$("camera-stage");
if(typeof ResizeObserver!=="undefined"&&cameraStageForResize){
  cameraStageResizeObserver=new ResizeObserver(function(){fitSimulatorCameraFrame();});
  cameraStageResizeObserver.observe(cameraStageForResize);
}
fitSimulatorCameraFrame();

