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
  const hallUnsupported=(caps.vision_profile==="city"&&$("city-lane-detector")&&$("city-lane-detector").value==="blsf-beta")
    ||(caps.vision_profile==="race"&&$("ml-lane-enabled")&&$("ml-lane-enabled").checked)
    ||($("old-method")&&$("old-method").checked);
  if(hallUnsupported)values.HALL_LINE_TRACKING_ENABLED=false;
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
function syncHallTrackingAvailability(){
  const hall=$("hall-line-tracking");
  if(!hall)return;
  const cityDetector=$("city-lane-detector");
  const mlEnabled=$("ml-lane-enabled");
  const oldMethod=$("old-method");
  const unsupported=(caps.vision_profile==="city"&&cityDetector&&cityDetector.value==="blsf-beta")
    ||(caps.vision_profile==="race"&&mlEnabled&&mlEnabled.checked)
    ||(oldMethod&&oldMethod.checked);
  const note=$("hall-compatibility-note");
  if(unsupported){
    hall.checked=false;
    hall.disabled=true;
    if(note){
      if(caps.vision_profile==="city"&&cityDetector&&cityDetector.value==="blsf-beta"){
        note.textContent="Hall tracking is unavailable while the BLSF beta detector is selected. Choose the default Sobel + Hough City detector to enable it.";
      }else if(caps.vision_profile==="race"&&mlEnabled&&mlEnabled.checked){
        note.textContent="Hall tracking is unavailable while the Race ML lane-mask detector is enabled. Disable ML to use Sobel + Hough temporal lane tracking.";
      }else{
        note.textContent="Hall tracking requires the Sobel + Hough detector. Disable the legacy Canny-based detector to enable it.";
      }
    }
  }else{
    hall.disabled=false;
    if(note)note.textContent="Uses joint left/right lane geometry and Hall matching. When a side is lost, Sobel + Hough searches a gradually expanding region around the predicted boundary and requires consistent multi-frame reacquisition. If both sides are lost, the last lane centre and learned width guide the search.";
  }
}
if($("city-lane-detector"))$("city-lane-detector").addEventListener("change",syncHallTrackingAvailability);
if($("ml-lane-enabled"))$("ml-lane-enabled").addEventListener("change",syncHallTrackingAvailability);
if($("old-method"))$("old-method").addEventListener("change",syncHallTrackingAvailability);
function populate(s){
  const fields = {
    "sim-host":"SIMULATOR_HOST","sim-port":"SIMULATOR_PORT","sim-timeout":"SIMULATOR_TIMEOUT_S",
    "vehicle-filter":"SIMULATOR_VEHICLE_FILTER","lidar-range":"SIMULATOR_LIDAR_RANGE_M",
    "lidar-channels":"SIMULATOR_LIDAR_CHANNELS","lidar-pps":"SIMULATOR_LIDAR_POINTS_PER_SECOND",
    "lidar-rotation":"SIMULATOR_LIDAR_ROTATION_FREQUENCY","camera-fov":"SIMULATOR_CAMERA_FOV",
    "avis-angle":"SIMULATOR_AVIS_SENSOR_ANGLE","obstacle-stop-distance":"SIMULATOR_OBSTACLE_STOP_DISTANCE_CM",
    "ml-lane-model":"ML_LANE_MODEL",
    "target-speed":"SIMULATOR_TARGET_SPEED",
    "throttle-limit":"SIMULATOR_THROTTLE_LIMIT","pulse-distance":"ENCODER_PULSE_DISTANCE_CM",
    "steering-authority":"SIMULATOR_STEERING_LIMIT","steering-rate":"SIMULATOR_STEERING_RATE",
    "throttle-rise-rate":"SIMULATOR_THROTTLE_RISE_RATE",
    "city-lane-detector":"CITY_LANE_DETECTOR",
    "lane-threshold":"LANE_THRESHOLD","hough-threshold":"HOUGH_THRESHOLD",
    "hough-min-line":"HOUGH_MIN_LINE_LENGTH","hough-max-gap":"HOUGH_MAX_LINE_GAP",
    "hough-blur":"HOUGH_BLUR_KERNEL","hall-line-max-missed":"HALL_LINE_TRACKING_MAX_MISSED",
    "hall-line-reacquire-margin":"HALL_LINE_TRACKING_REACQUIRE_MARGIN","crosswalk-threshold":"CROSSWALK_THRESHOLD",
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
    "cw-top":"CW_TOP_ROI","cw-bottom":"CW_BOTTOM_ROI","cw-left":"CW_LEFT_ROI","cw-right":"CW_RIGHT_ROI"
  };
  Object.keys(fields).forEach(function(id){ if($(id)&&s[fields[id]]!==undefined) $(id).value=s[fields[id]]; });
  ["lidar-enabled","stop-lost-lane","stop-crosswalk","steering-inverted","use-bev","debug-overlay","ml-lane-enabled",
   "hough-morph-close","cw-trapezoid","old-method","cw-old-method","roi-resizable","hall-line-tracking",
   "pid-enabled","pid-auto-kp"].forEach(function(id){
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
  syncHallTrackingAvailability();
}
