let simulatorSettingsReady=false;
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
   "obstacle-distance-mode","obstacle-roi-confirmation-enabled"].forEach(function(id){
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
}
