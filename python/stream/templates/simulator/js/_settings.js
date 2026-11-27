let simulatorSettingsReady=false;

const AVIS_CROSSWALK_ROUTE_NAMES={left:"LEFT",straight:"STRAIGHT",right:"RIGHT"};
let avisCrosswalkRouteData={left:[],straight:[],right:[]};
let avisCrosswalkActiveRoute="left";
function avisCrosswalkDefaultStep(route){
  const angle=route==="left"?-20:route==="right"?20:0;
  return {direction:"forward",distance_m:0.25,speed_percent:12,steering_percent:angle};
}
function avisCrosswalkReadRoutes(){
  const field=$("crosswalk-route-chains");
  let value={left:[],straight:[],right:[]};
  if(field&&String(field.value||"").trim())value=JSON.parse(field.value);
  ["left","straight","right"].forEach(function(route){
    if(!Array.isArray(value[route]))value[route]=[];
    value[route]=value[route].slice(0,16).map(function(step){
      return {direction:step.direction==="reverse"?"reverse":"forward",
        distance_m:Number(step.distance_m),speed_percent:Number(step.speed_percent),
        steering_percent:Number(step.steering_percent)};
    });
  });
  return value;
}
function avisCrosswalkSerializeRoutes(){
  const result={left:[],straight:[],right:[]};
  ["left","straight","right"].forEach(function(route){
    const steps=avisCrosswalkRouteData[route]||[];
    if(steps.length>16)throw new Error(AVIS_CROSSWALK_ROUTE_NAMES[route]+" route cannot exceed 16 steps.");
    result[route]=steps.map(function(step,index){
      const distance=Number(step.distance_m),speed=Number(step.speed_percent),steering=Number(step.steering_percent);
      if(!["forward","reverse"].includes(step.direction))throw new Error("Step "+(index+1)+": choose forward or reverse.");
      if(!Number.isFinite(distance)||distance<0.05||distance>40)throw new Error("Step "+(index+1)+": distance must be 0.05–40 metres.");
      if(!Number.isInteger(speed)||speed<1||speed>100)throw new Error("Step "+(index+1)+": speed must be an integer from 1 to 100 percent.");
      if(!Number.isInteger(steering)||steering<-100||steering>100)throw new Error("Step "+(index+1)+": steering must be an integer from -100 to +100 percent.");
      return {direction:step.direction,distance_m:distance,speed_percent:speed,steering_percent:steering};
    });
  });
  return JSON.stringify(result);
}
function avisCrosswalkUpdatePreview(){
  const preview=$("avis-crosswalk-route-preview");if(!preview)return;
  const steps=avisCrosswalkRouteData[avisCrosswalkActiveRoute]||[];
  if(!steps.length){preview.textContent="No steps configured. The vehicle will remain stopped if this route is selected.";return;}
  preview.textContent=steps.map(function(step,index){
    return (index+1)+". "+(step.direction==="reverse"?"REVERSE":"FORWARD")+" "+
      Number(step.distance_m).toFixed(2)+"m · "+Number(step.speed_percent)+
      "% speed · "+Number(step.steering_percent)+"% steering";
  }).join("   →   ");
}
function avisCrosswalkRenderRoutes(){
  const host=$("avis-crosswalk-step-list"),heading=$("avis-crosswalk-route-heading");
  const count=$("avis-crosswalk-route-count"),add=$("avis-crosswalk-step-add");
  if(!host)return;
  host.replaceChildren();
  ["left","straight","right"].forEach(function(route){
    const button=document.querySelector('[data-avis-crosswalk-route="'+route+'"]');
    if(button){const active=route===avisCrosswalkActiveRoute;button.classList.toggle("active",active);button.setAttribute("aria-selected",active?"true":"false");}
  });
  const steps=avisCrosswalkRouteData[avisCrosswalkActiveRoute]||[];
  if(heading)heading.textContent=AVIS_CROSSWALK_ROUTE_NAMES[avisCrosswalkActiveRoute]+" route";
  if(count)count.textContent=steps.length+" / 16 steps";
  if(add)add.disabled=steps.length>=16;
  steps.forEach(function(step,index){
    const row=document.createElement("div");row.className="avis-crosswalk-step";
    const number=document.createElement("div");number.className="avis-crosswalk-step-number";number.textContent="STEP "+(index+1);row.appendChild(number);
    function addField(title,control){const label=document.createElement("label");label.appendChild(document.createTextNode(title));label.appendChild(control);row.appendChild(label);}
    const direction=document.createElement("select");
    [["forward","Forward"],["reverse","Reverse"]].forEach(function(option){
      const node=document.createElement("option");node.value=option[0];node.textContent=option[1];direction.appendChild(node);
    });
    direction.value=step.direction;direction.addEventListener("change",function(){step.direction=direction.value;avisCrosswalkUpdatePreview();});addField("Direction",direction);
    const distance=document.createElement("input");distance.type="number";distance.min="0.05";distance.max="40";distance.step="0.05";distance.value=Number(step.distance_m).toFixed(2);
    distance.addEventListener("input",function(){step.distance_m=Number(distance.value);avisCrosswalkUpdatePreview();});addField("Distance · metres",distance);
    const speed=document.createElement("input");speed.type="number";speed.min="1";speed.max="100";speed.step="1";speed.value=String(step.speed_percent);
    speed.addEventListener("input",function(){step.speed_percent=Number(speed.value);avisCrosswalkUpdatePreview();});addField("Speed · percent",speed);
    const steering=document.createElement("input");steering.type="number";steering.min="-100";steering.max="100";steering.step="1";steering.value=String(step.steering_percent);
    steering.addEventListener("input",function(){step.steering_percent=Number(steering.value);avisCrosswalkUpdatePreview();});addField("Steering · signed %",steering);
    const remove=document.createElement("button");remove.type="button";remove.className="ghost";remove.textContent="Remove";
    remove.addEventListener("click",function(){avisCrosswalkRouteData[avisCrosswalkActiveRoute].splice(index,1);avisCrosswalkRenderRoutes();});
    row.appendChild(remove);host.appendChild(row);
  });
  if(!steps.length){const empty=document.createElement("p");empty.className="note";empty.textContent="No commands configured. If this sign is detected at a crosswalk, AVIS will hold at zero speed until the route is configured.";host.appendChild(empty);}
  avisCrosswalkUpdatePreview();
}
function avisCrosswalkCloseRouteEditor(){
  const modal=$("avis-crosswalk-route-modal");if(modal){modal.classList.remove("is-open");modal.setAttribute("aria-hidden","true");}
}
function avisCrosswalkOpenRouteEditor(){
  const modal=$("avis-crosswalk-route-modal"),field=$("crosswalk-route-chains");
  if(!modal||!field)return;
  try{avisCrosswalkRouteData=avisCrosswalkReadRoutes();avisCrosswalkActiveRoute="left";avisCrosswalkRenderRoutes();
    modal.classList.add("is-open");modal.setAttribute("aria-hidden","false");
    const close=$("avis-crosswalk-route-close");if(close)close.focus();
  }catch(error){showToast("Could not load crosswalk routes: "+error.message);}
}
function bindAvisCrosswalkRouteEditor(){
  const open=$("avis-crosswalk-routes-open"),modal=$("avis-crosswalk-route-modal");
  if(!open||!modal||open.dataset.bound==="1")return;
  open.dataset.bound="1";open.addEventListener("click",avisCrosswalkOpenRouteEditor);
  const close=$("avis-crosswalk-route-close"),cancel=$("avis-crosswalk-route-cancel");
  if(close)close.addEventListener("click",avisCrosswalkCloseRouteEditor);
  if(cancel)cancel.addEventListener("click",avisCrosswalkCloseRouteEditor);
  modal.addEventListener("click",function(event){if(event.target===modal)avisCrosswalkCloseRouteEditor();});
  modal.querySelectorAll("[data-avis-crosswalk-route]").forEach(function(button){
    button.addEventListener("click",function(){avisCrosswalkActiveRoute=button.dataset.avisCrosswalkRoute;avisCrosswalkRenderRoutes();});
  });
  const add=$("avis-crosswalk-step-add");
  if(add)add.addEventListener("click",function(){
    const steps=avisCrosswalkRouteData[avisCrosswalkActiveRoute]||[];if(steps.length>=16)return;
    steps.push(avisCrosswalkDefaultStep(avisCrosswalkActiveRoute));avisCrosswalkRenderRoutes();
  });
  const save=$("avis-crosswalk-route-save");
  if(save)save.addEventListener("click",function(){
    try{$("crosswalk-route-chains").value=avisCrosswalkSerializeRoutes();avisCrosswalkCloseRouteEditor();
      showToast("Route edits applied. Press Save settings to persist them.");
    }catch(error){showToast("Route validation failed: "+error.message);}
  });
  window.addEventListener("keydown",function(event){if(event.key==="Escape"&&modal.classList.contains("is-open"))avisCrosswalkCloseRouteEditor();});
}

const AVIS_DEADLOCK_ROUTE_NAMES={left:"LEFT",right:"RIGHT"};
let avisDeadlockRouteData={left:[],right:[]};
let avisDeadlockActiveRoute="left";
function avisDeadlockDefaultStep(route){
  return {direction:"forward",distance_m:0.30,speed_percent:12,steering_percent:route==="left"?-30:30};
}
function avisDeadlockReadRoutes(){
  const field=$("deadlock-route-chains");
  let value={left:[],right:[]};
  if(field&&String(field.value||"").trim())value=JSON.parse(field.value);
  ["left","right"].forEach(function(route){
    if(!Array.isArray(value[route]))value[route]=[];
    value[route]=value[route].slice(0,16).map(function(step){
      return {
        direction:step.direction==="reverse"?"reverse":"forward",
        distance_m:Number(step.distance_m),
        speed_percent:Number(step.speed_percent),
        steering_percent:Number(step.steering_percent)
      };
    });
  });
  return value;
}
function avisDeadlockSerializeRoutes(){
  const result={left:[],right:[]};
  ["left","right"].forEach(function(route){
    const steps=avisDeadlockRouteData[route]||[];
    if(steps.length>16)throw new Error(AVIS_DEADLOCK_ROUTE_NAMES[route]+" route cannot exceed 16 steps.");
    result[route]=steps.map(function(step,index){
      const distance=Number(step.distance_m),speed=Number(step.speed_percent),steering=Number(step.steering_percent);
      if(!["forward","reverse"].includes(step.direction))throw new Error("Step "+(index+1)+": choose forward or reverse.");
      if(!Number.isFinite(distance)||distance<0.05||distance>40)throw new Error("Step "+(index+1)+": distance must be 0.05–40 metres.");
      if(!Number.isInteger(speed)||speed<1||speed>100)throw new Error("Step "+(index+1)+": speed must be an integer from 1 to 100 percent.");
      if(!Number.isInteger(steering)||steering<-100||steering>100)throw new Error("Step "+(index+1)+": steering must be an integer from -100 to +100 percent.");
      return {direction:step.direction,distance_m:distance,speed_percent:speed,steering_percent:steering};
    });
  });
  return JSON.stringify(result);
}
function avisDeadlockUpdatePreview(){
  const preview=$("avis-deadlock-route-preview");if(!preview)return;
  const steps=avisDeadlockRouteData[avisDeadlockActiveRoute]||[];
  if(!steps.length){
    preview.textContent="No steps configured. If this deadlock direction is confirmed, no escape hardcode will run and normal lane following will continue.";
    return;
  }
  preview.textContent=steps.map(function(step,index){
    return (index+1)+". "+(step.direction==="reverse"?"REVERSE":"FORWARD")+" "+
      Number(step.distance_m).toFixed(2)+"m · "+Number(step.speed_percent)+
      "% speed · "+Number(step.steering_percent)+"% steering";
  }).join("   →   ");
}
function avisDeadlockRenderRoutes(){
  const host=$("avis-deadlock-step-list");
  const heading=$("avis-deadlock-route-heading");
  const count=$("avis-deadlock-route-count");
  const add=$("avis-deadlock-step-add");
  if(!host)return;
  host.replaceChildren();
  ["left","right"].forEach(function(route){
    const button=document.querySelector('[data-avis-deadlock-route="'+route+'"]');
    if(button){
      const active=route===avisDeadlockActiveRoute;
      button.classList.toggle("active",active);
      button.setAttribute("aria-selected",active?"true":"false");
    }
  });
  const steps=avisDeadlockRouteData[avisDeadlockActiveRoute]||[];
  if(heading)heading.textContent=AVIS_DEADLOCK_ROUTE_NAMES[avisDeadlockActiveRoute]+" maneuver";
  if(count)count.textContent=steps.length+" / 16 steps";
  if(add)add.disabled=steps.length>=16;
  steps.forEach(function(step,index){
    const row=document.createElement("div");row.className="avis-crosswalk-step";
    const number=document.createElement("div");
    number.className="avis-crosswalk-step-number";
    number.textContent="STEP "+(index+1);
    row.appendChild(number);
    function addField(title,control){
      const label=document.createElement("label");
      label.appendChild(document.createTextNode(title));
      label.appendChild(control);
      row.appendChild(label);
    }
    const direction=document.createElement("select");
    [["forward","Forward"],["reverse","Reverse"]].forEach(function(option){
      const node=document.createElement("option");
      node.value=option[0];node.textContent=option[1];direction.appendChild(node);
    });
    direction.value=step.direction;
    direction.addEventListener("change",function(){
      step.direction=direction.value;avisDeadlockUpdatePreview();
    });
    addField("Direction",direction);

    const distance=document.createElement("input");
    distance.type="number";distance.min="0.05";distance.max="40";
    distance.step="0.05";distance.value=Number(step.distance_m).toFixed(2);
    distance.addEventListener("input",function(){
      step.distance_m=Number(distance.value);avisDeadlockUpdatePreview();
    });
    addField("Distance · metres",distance);

    const speed=document.createElement("input");
    speed.type="number";speed.min="1";speed.max="100";speed.step="1";
    speed.value=String(step.speed_percent);
    speed.addEventListener("input",function(){
      step.speed_percent=Number(speed.value);avisDeadlockUpdatePreview();
    });
    addField("Speed · percent",speed);

    const steering=document.createElement("input");
    steering.type="number";steering.min="-100";steering.max="100";steering.step="1";
    steering.value=String(step.steering_percent);
    steering.addEventListener("input",function(){
      step.steering_percent=Number(steering.value);avisDeadlockUpdatePreview();
    });
    addField("Steering · signed %",steering);

    const remove=document.createElement("button");
    remove.type="button";remove.className="ghost";remove.textContent="Remove";
    remove.addEventListener("click",function(){
      avisDeadlockRouteData[avisDeadlockActiveRoute].splice(index,1);
      avisDeadlockRenderRoutes();
    });
    row.appendChild(remove);host.appendChild(row);
  });
  if(!steps.length){
    const empty=document.createElement("p");
    empty.className="note";
    empty.textContent="No commands configured. This direction will not run an escape hardcode; normal lane following will continue.";
    host.appendChild(empty);
  }
  avisDeadlockUpdatePreview();
}
function avisDeadlockCloseRouteEditor(){
  const modal=$("avis-deadlock-route-modal");
  if(modal){modal.classList.remove("is-open");modal.setAttribute("aria-hidden","true");}
}
function avisDeadlockOpenRouteEditor(){
  const modal=$("avis-deadlock-route-modal");
  const field=$("deadlock-route-chains");
  if(!modal||!field)return;
  try{
    avisDeadlockRouteData=avisDeadlockReadRoutes();
    avisDeadlockActiveRoute="left";
    avisDeadlockRenderRoutes();
    modal.classList.add("is-open");modal.setAttribute("aria-hidden","false");
    const close=$("avis-deadlock-route-close");if(close)close.focus();
  }catch(error){
    showToast("Could not load deadlock routes: "+error.message);
  }
}
function bindAvisDeadlockRouteEditor(){
  const open=$("avis-deadlock-routes-open");
  const modal=$("avis-deadlock-route-modal");
  if(!open||!modal||open.dataset.bound==="1")return;
  open.dataset.bound="1";
  open.addEventListener("click",avisDeadlockOpenRouteEditor);
  const close=$("avis-deadlock-route-close");
  const cancel=$("avis-deadlock-route-cancel");
  if(close)close.addEventListener("click",avisDeadlockCloseRouteEditor);
  if(cancel)cancel.addEventListener("click",avisDeadlockCloseRouteEditor);
  modal.addEventListener("click",function(event){
    if(event.target===modal)avisDeadlockCloseRouteEditor();
  });
  modal.querySelectorAll("[data-avis-deadlock-route]").forEach(function(button){
    button.addEventListener("click",function(){
      avisDeadlockActiveRoute=button.dataset.avisDeadlockRoute;
      avisDeadlockRenderRoutes();
    });
  });
  const add=$("avis-deadlock-step-add");
  if(add)add.addEventListener("click",function(){
    const steps=avisDeadlockRouteData[avisDeadlockActiveRoute]||[];
    if(steps.length>=16)return;
    steps.push(avisDeadlockDefaultStep(avisDeadlockActiveRoute));
    avisDeadlockRenderRoutes();
  });
  const save=$("avis-deadlock-route-save");
  if(save)save.addEventListener("click",function(){
    try{
      $("deadlock-route-chains").value=avisDeadlockSerializeRoutes();
      avisDeadlockCloseRouteEditor();
      showToast("Deadlock routes applied. Press Save settings to persist them.");
    }catch(error){
      showToast("Deadlock route validation failed: "+error.message);
    }
  });
  window.addEventListener("keydown",function(event){
    if(event.key==="Escape"&&modal.classList.contains("is-open"))avisDeadlockCloseRouteEditor();
  });
}

function readSettingNumber(id){
  const input=$(id);
  if(!input)throw new Error("Setting control is unavailable: "+id);
  const raw=String(input.value??"").trim();
  if(raw==="")throw new Error((input.name||id)+" is empty. Reload saved defaults or enter a value before saving.");
  const value=Number(raw);
  if(!Number.isFinite(value))throw new Error((input.name||id)+" must be a finite number.");
  return value;
}
function collectSimulatorSettings(){
  const form=$("settings-form");
  if(!form)throw new Error("Simulator settings form is unavailable.");
  const values={};
  form.querySelectorAll("[name]").forEach(function(control){
    if(control.disabled||control.closest(".section-hide")||control.closest("[hidden]"))return;
    const name=control.name;if(!name)return;
    if(!control.checkValidity()){
      if(typeof control.reportValidity==="function")control.reportValidity();
      const label=control.labels&&control.labels[0]?control.labels[0].textContent.trim():name;
      throw new Error(label+" is outside its allowed range or step.");
    }
    if(control.type==="checkbox")values[name]=!!control.checked;
    else if(control.type==="number")values[name]=readSettingNumber(control.id);
    else values[name]=String(control.value??"").trim();
  });
  if(values.SIMULATOR_VEHICLE_FILTER!==undefined&&!values.SIMULATOR_VEHICLE_FILTER){
    values.SIMULATOR_VEHICLE_FILTER="vehicle.*";
  }
  if(caps.supports_lane_roi&&caps.vision_profile==="city"){
    values.RL_MIRRORED=!!simRoiMirrors.RL;
    values.LL_MIRRORED=!!simRoiMirrors.LL;
  }
  const pidLowInput=$("pid-output-min"),pidHighInput=$("pid-output-max");
  if(!pidLowInput.checkValidity()||!pidHighInput.checkValidity()){
    if(!pidLowInput.checkValidity())pidLowInput.reportValidity();
    else pidHighInput.reportValidity();
    throw new Error("PID output limits must be between -255 and 255.");
  }
  const pidLow=readSettingNumber("pid-output-min"),pidHigh=readSettingNumber("pid-output-max");
  if(pidLow>=pidHigh)throw new Error("Minimum PID correction must be smaller than maximum PID correction.");
  values.OUTPUT_LIMITS=[pidLow,pidHigh];
  if(!Object.keys(values).length)throw new Error("No active simulator settings are available to save.");
  return values;
}
function populate(s){
  const fields = {
    "sim-host":"SIMULATOR_HOST","sim-port":"SIMULATOR_PORT","sim-timeout":"SIMULATOR_TIMEOUT_S",
    "vehicle-filter":"SIMULATOR_VEHICLE_FILTER","lidar-range":"SIMULATOR_LIDAR_RANGE_M",
    "lidar-channels":"SIMULATOR_LIDAR_CHANNELS","lidar-pps":"SIMULATOR_LIDAR_POINTS_PER_SECOND",
    "lidar-rotation":"SIMULATOR_LIDAR_ROTATION_FREQUENCY","camera-fov":"SIMULATOR_CAMERA_FOV",
    "avis-angle":"SIMULATOR_AVIS_SENSOR_ANGLE","obstacle-stop-distance":"SIMULATOR_OBSTACLE_STOP_DISTANCE_CM",
    "obstacle-trigger-distance":"SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM",
    "obstacle-approach-speed":"SIMULATOR_OBSTACLE_APPROACH_SPEED_KMH",
    "obstacle-speed-limit-distance":"SIMULATOR_OBSTACLE_SPEED_LIMIT_DISTANCE_CM",
    "obstacle-clear-distance":"SIMULATOR_OBSTACLE_CLEAR_DISTANCE_CM",
    "obstacle-clear-confirm-frames":"SIMULATOR_OBSTACLE_CLEAR_CONFIRM_FRAMES",
    "avis-front-range-grace":"SIMULATOR_AVIS_FRONT_RANGE_INVALID_GRACE_SECONDS",
    "obstacle-side-clearance":"SIMULATOR_OBSTACLE_SIDE_CLEARANCE_CM",
    "obstacle-left-steering":"SIMULATOR_OBSTACLE_LEFT_STEERING_PERCENT",
    "obstacle-right-steering":"SIMULATOR_OBSTACLE_RIGHT_STEERING_PERCENT",
    "obstacle-roi-delay":"SIMULATOR_OBSTACLE_ROI_DELAY_SECONDS",
    "obstacle-steering-distance":"SIMULATOR_OBSTACLE_DIRECT_STEERING_DISTANCE_CM",
    "obstacle-distance-timeout":"SIMULATOR_OBSTACLE_PASS_TIMEOUT_SECONDS",
    "obstacle-lane-hold":"SIMULATOR_OBSTACLE_LANE_HOLD_SECONDS",
    "obstacle-roi-timeout":"SIMULATOR_OBSTACLE_ROI_SEARCH_TIMEOUT_SECONDS",
    "obstacle-roi-frames":"SIMULATOR_OBSTACLE_ROI_CONFIRM_FRAMES",
    "obstacle-return-steering-samples":"SIMULATOR_OBSTACLE_RETURN_STEERING_SAMPLE_COUNT",
    "obstacle-return-steering-max-wait":"SIMULATOR_OBSTACLE_RETURN_STEERING_MAX_WAIT_SECONDS",
    "obstacle-return-steering-min":"SIMULATOR_OBSTACLE_RETURN_STEERING_MIN_PERCENT",
    "obstacle-return-steering-max":"SIMULATOR_OBSTACLE_RETURN_STEERING_MAX_PERCENT",
    "obstacle-throttle-limit":"SIMULATOR_OBSTACLE_THROTTLE_LIMIT",
    "stop-line-threshold":"SIMULATOR_STOP_LINE_THRESHOLD",
    "stop-line-width":"SIMULATOR_STOP_LINE_MIN_WIDTH_RATIO",
    "stop-line-area":"SIMULATOR_STOP_LINE_MIN_AREA",
    "stop-line-angle":"SIMULATOR_STOP_LINE_MAX_ANGLE_DEG",
    "stop-line-frames":"SIMULATOR_STOP_LINE_CONFIRM_FRAMES",
    "stop-line-dwell":"SIMULATOR_STOP_LINE_DWELL_SECONDS",
    "crosswalk-confirm-frames":"SIMULATOR_CROSSWALK_CONFIRM_FRAMES",
    "crosswalk-dwell":"SIMULATOR_CROSSWALK_DWELL_SECONDS",
    "crosswalk-step-timeout":"SIMULATOR_CROSSWALK_STEP_TIMEOUT_SECONDS",
    "crosswalk-route-chains":"SIMULATOR_CROSSWALK_ROUTE_CHAINS",
    "deadlock-confirm-frames":"SIMULATOR_DEADLOCK_CONFIRM_FRAMES",
    "deadlock-step-timeout":"SIMULATOR_DEADLOCK_STEP_TIMEOUT_SECONDS",
    "deadlock-route-chains":"SIMULATOR_DEADLOCK_ROUTE_CHAINS",
    "sign-confidence":"SIMULATOR_SIGN_CONFIDENCE",
    "sign-scan-interval":"SIMULATOR_SIGN_SCAN_INTERVAL",
    "sign-stop-hold":"SIMULATOR_SIGN_STOP_HOLD_SECONDS",
    "sign-turn-hold":"SIMULATOR_SIGN_TURN_HOLD_SECONDS",
    "sign-steering-offset":"SIMULATOR_SIGN_STEERING_OFFSET",
    "tl-min-saturation":"TL_MIN_SATURATION","tl-min-value":"TL_MIN_VALUE",
    "tl-min-area":"TL_MIN_CONTOUR_AREA","tl-brightness":"TL_MIN_ACTIVE_BRIGHTNESS",
    "tl-red-hue-min":"TL_RED_HUE_MIN","tl-red-hue-max":"TL_RED_HUE_MAX",
    "tl-red-wrap-hue":"TL_RED_HUE_WRAP_MIN","tl-green-hue-min":"TL_GREEN_HUE_MIN",
    "tl-green-hue-max":"TL_GREEN_HUE_MAX","tl-window":"SIMULATOR_TL_CONFIRMATION_WINDOW",
    "tl-green-required":"SIMULATOR_TL_GREEN_REQUIRED",
    "st-top":"ST_TOP_ROI","st-bottom":"ST_BOTTOM_ROI",
    "st-left":"ST_LEFT_ROI","st-right":"ST_RIGHT_ROI",
    "sl-top":"SIMULATOR_STOP_LINE_TOP_ROI","sl-bottom":"SIMULATOR_STOP_LINE_BOTTOM_ROI",
    "sl-left":"SIMULATOR_STOP_LINE_LEFT_ROI","sl-right":"SIMULATOR_STOP_LINE_RIGHT_ROI",
    "tl-top":"TL_TOP_ROI","tl-bottom":"TL_BOTTOM_ROI","tl-left":"TL_LEFT_ROI","tl-right":"TL_RIGHT_ROI",
    "ml-lane-model":"ML_LANE_MODEL",
    "target-speed":"SIMULATOR_TARGET_SPEED",
    "throttle-limit":"SIMULATOR_THROTTLE_LIMIT","pulse-distance":"ENCODER_PULSE_DISTANCE_CM",
    "steering-authority":"SIMULATOR_STEERING_LIMIT","steering-rate":"SIMULATOR_STEERING_RATE",
    "throttle-rise-rate":"SIMULATOR_THROTTLE_RISE_RATE",
    "city-lane-detector":"CITY_LANE_DETECTOR",
    "lane-threshold":"LANE_THRESHOLD","hough-threshold":"HOUGH_THRESHOLD",
    "hough-min-line":"HOUGH_MIN_LINE_LENGTH","hough-max-gap":"HOUGH_MAX_LINE_GAP",
    "hough-blur":"HOUGH_BLUR_KERNEL","hall-line-max-missed":"HALL_LINE_TRACKING_MAX_MISSED","crosswalk-threshold":"CROSSWALK_THRESHOLD",
    "pid-kp":"KP","pid-ki":"KI","pid-kd":"KD","pid-kt":"KT",
    "pid-min-dt":"PID_MIN_DT","pid-max-dt":"PID_MAX_DT","pid-derivative-filter":"PID_DERIVATIVE_FILTER",
    "crosswalk-min-vertical":"CROSSWALK_VERTICAL_MIN_LINES",
    "crosswalk-min-horizontal":"CROSSWALK_HORIZONTAL_MIN_LINES",
    "crosswalk-canny-low":"CROSSWALK_CANNY_LOW_THRESHOLD",
    "crosswalk-canny-high":"CROSSWALK_CANNY_HIGH_THRESHOLD",
    "crosswalk-hough-threshold":"CROSSWALK_HOUGH_THRESHOLD",
    "crosswalk-hough-min-line":"CROSSWALK_HOUGH_MIN_LINE_LENGTH",
    "crosswalk-hough-max-gap":"CROSSWALK_HOUGH_MAX_LINE_GAP",
    "crosswalk-angle-tolerance":"CROSSWALK_LINE_ANGLE_TOLERANCE_DEG",
    "crosswalk-min-line-ratio":"CROSSWALK_MIN_LINE_LENGTH_RATIO",
    "crosswalk-min-line-px":"CROSSWALK_MIN_LINE_LENGTH_PX",
    "crosswalk-bottom-ratio":"CROSSWALK_MIN_BOTTOM_DISTANCE_RATIO",
    "lane-roi-mode":"LANE_ROI_MODE","rl-top-factor":"RL_TOP_WIDTH_FACTOR",
    "ll-top-factor":"LL_TOP_WIDTH_FACTOR","cw-top-factor":"CW_TOP_WIDTH_FACTOR",
    "camera-pitch-deg":"CAMERA_PITCH_DEG","camera-height":"CAMERA_HEIGHT","lane-width":"LANE_WIDTH",
    "min-servo":"MIN_SERVO_ANGLE","servo-center":"SERVO_CENTER","max-servo":"MAX_SERVO_ANGLE",
    "servo-direction":"SERVO_DIRECTION",
    "bev-tl-x":"BEV_SRC_TL_X","bev-tl-y":"BEV_SRC_TL_Y",
    "bev-tr-x":"BEV_SRC_TR_X","bev-tr-y":"BEV_SRC_TR_Y",
    "bev-br-x":"BEV_SRC_BR_X","bev-br-y":"BEV_SRC_BR_Y",
    "bev-bl-x":"BEV_SRC_BL_X","bev-bl-y":"BEV_SRC_BL_Y",
    "rl-top":"RL_TOP_ROI","rl-bottom":"RL_BOTTOM_ROI","rl-left":"RL_LEFT_ROI","rl-right":"RL_RIGHT_ROI",
    "ll-top":"LL_TOP_ROI","ll-bottom":"LL_BOTTOM_ROI","ll-left":"LL_LEFT_ROI","ll-right":"LL_RIGHT_ROI",
    "ml-top":"ML_TOP_ROI","ml-bottom":"ML_BOTTOM_ROI","ml-left":"ML_LEFT_ROI","ml-right":"ML_RIGHT_ROI",
    "mr-top":"MR_TOP_ROI","mr-bottom":"MR_BOTTOM_ROI","mr-left":"MR_LEFT_ROI","mr-right":"MR_RIGHT_ROI",
    "cw-top":"CW_TOP_ROI","cw-bottom":"CW_BOTTOM_ROI","cw-left":"CW_LEFT_ROI","cw-right":"CW_RIGHT_ROI"
  };
  Object.keys(fields).forEach(function(id){ if($(id)&&s[fields[id]]!==undefined) $(id).value=s[fields[id]]; });
  ["lidar-enabled","stop-lost-lane","stop-crosswalk","steering-inverted","use-bev","debug-overlay","ml-lane-enabled",
   "hough-morph-close","cw-trapezoid","old-method","cw-old-method","roi-resizable","hall-line-tracking",
   "pid-enabled","pid-auto-kp","obstacle-avoidance-enabled","obstacle-hall-handoff-enabled",
   "obstacle-speed-limit-left-sensor","obstacle-speed-limit-front-sensor","obstacle-speed-limit-right-sensor",
   "obstacle-speed-limit-brake","stop-line-enabled",
   "traffic-lights-enabled","sign-actions-enabled","obstacle-return-steering-gate-enabled",
   "obstacle-distance-mode","obstacle-roi-confirmation-enabled","crosswalk-hardcode-enabled",
   "deadlock-enabled"].forEach(function(id){
    if(!$(id)) return;
    const key=$(id).name;
    if(s[key]!==undefined) $(id).checked=!!s[key];
  });
  if(Array.isArray(s.OUTPUT_LIMITS)&&s.OUTPUT_LIMITS.length===2){
    $("pid-output-min").value=s.OUTPUT_LIMITS[0];
    $("pid-output-max").value=s.OUTPUT_LIMITS[1];
  }else{
    $("pid-output-min").value=-80;
    $("pid-output-max").value=80;
  }
  simRoiMirrors.RL=!!s.RL_MIRRORED;
  simRoiMirrors.LL=!!s.LL_MIRRORED;
  simRoiUpdateSelection();
  setText("target-speed-label", caps.simulator_backend==="avis" ? "AVIS motor speed (0–100%)" : "Target vehicle speed (km/h, editable up to 200)");
  if($("carla-run-start"))$("carla-run-start").disabled=!simRoiControlsEnabled;
  if($("carla-run-stop"))$("carla-run-stop").disabled=!simRoiControlsEnabled;
  drawSimRoiOverlay();
  bindAvisCrosswalkRouteEditor();
  bindAvisDeadlockRouteEditor();
}

function bindAvisRouteEditors(){
  bindAvisCrosswalkRouteEditor();
  bindAvisDeadlockRouteEditor();
}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",bindAvisRouteEditors,{once:true});
else bindAvisRouteEditors();
