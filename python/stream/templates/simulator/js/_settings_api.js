async function loadSettings(){
  simulatorSettingsReady=false;
  const saveButton=$("save-settings"),reloadButton=$("reload-settings");
  if(saveButton)saveButton.disabled=true;
  if(reloadButton)reloadButton.disabled=true;
  try{
    const response=await fetch("/api/simulation/settings",{cache:"no-store"});
    const data=await response.json();
    if(!response.ok||!data.success) throw new Error(data.message||"Could not load simulator settings");
  simRoiControlsEnabled=!!data.controls_enabled;
  simRoiGeometry=Object.assign(simRoiGeometry,data.roi_geometry||{});
  const roiHint=document.querySelector("#sim-roi-editor .sim-roi-hint");
  if(roiHint)roiHint.textContent="Select a region, drag inside to move it, or drag a corner handle to resize. Changes auto-save after you finish dragging or edit a numeric coordinate. "+(caps.supports_bev?"The BEV source quadrilateral is drawn over the camera frame; drag its corners to tune the perspective transform. ":"")+ "Coordinates are normalized fractions from 0 to 1 (0.1 = 10% of the frame); City lane mask: "+simRoiGeometry.lane_roi_mode+"; crosswalk mask: "+(simRoiGeometry.cw_trapezoid_mode?"trapezoid":"rectangle")+".";
  populate(data.settings||{});
  if($("carla-run-start"))$("carla-run-start").disabled=!data.controls_enabled;
  if($("carla-run-stop"))$("carla-run-stop").disabled=!data.controls_enabled;
  const roiSaveButton=$("sim-roi-save");
  if(roiSaveButton)roiSaveButton.disabled=!simRoiControlsEnabled;
  if(!simRoiControlsEnabled)setText("sim-roi-status","Read-only: enable STREAM_ALLOW_CONTROL to save ROI changes.");
  else setText("sim-roi-status","Loaded saved ROI settings · changes auto-save");
  const roiMirrorInput=$("sim-roi-mirror-selected");if(roiMirrorInput)roiMirrorInput.disabled=!simRoiControlsEnabled;
  simRoiDefs.forEach(function(def){Object.values(def.fields).forEach(function(id){const input=$(id);if(input)input.disabled=!simRoiControlsEnabled;});});
  if(caps.supports_bev){
    ["bev-tl-x","bev-tl-y","bev-tr-x","bev-tr-y","bev-br-x","bev-br-y","bev-bl-x","bev-bl-y"].forEach(function(id){
      const input=$(id);if(input)input.disabled=!simRoiControlsEnabled;
    });
  }
  $("save-settings").disabled=!data.controls_enabled;
  if($("open-camera-editor"))$("open-camera-editor").disabled=!data.controls_enabled;
  $("save-settings").title=data.controls_enabled?"Save this simulator mode's settings":"Dashboard is read-only; enable stream control to edit settings";
  if(data.option_groups){
    const parent=$("option-groups");
    // This optional panel is not part of the AVIS view.
    if(parent){
      parent.replaceChildren();
      data.option_groups.forEach(function(group){
        const card=document.createElement("div"); card.className="option-group";
        const h=document.createElement("h4"); h.textContent=group.title;
        const p=document.createElement("p"); p.textContent=group.description;
        card.append(h,p); parent.append(card);
      });
    }
  }
  simulatorSettingsReady=true;
  }catch(error){
    simulatorSettingsReady=false;
    throw error;
  }finally{
    if(reloadButton)reloadButton.disabled=false;
  }
}
