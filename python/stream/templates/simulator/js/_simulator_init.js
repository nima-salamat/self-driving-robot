if (caps.simulator_backend === "carla") {
  initCameraEditor();
  initCarlaScene();
}
loadSettings().then(function () {
  if (caps.simulator_backend === "carla") {
    carlaSceneControlsEnabled = !!($("save-settings") && !$("save-settings").disabled);
    renderCarlaScene(carlaSceneState);
    return loadCarlaScene();
  }
}).catch(function (error) { status(error.message, false); });
poll();
setInterval(poll, 650);
refreshSimulatorCameraFrame();
setInterval(refreshSimulatorCameraFrame, 40);
function toggleSensorPanel(panelId,buttonId,expandedClass){
  const panel=$(panelId),button=$(buttonId);if(!panel||!button)return;
  const expanded=panel.classList.toggle(expandedClass);
  button.textContent=expanded?"Exit expanded view":"Expand view";
  if(expanded&&document.documentElement.requestFullscreen)document.documentElement.requestFullscreen().catch(function(){});
  else if(!expanded&&document.fullscreenElement&&document.exitFullscreen)document.exitFullscreen().catch(function(){});
}
if($("lidar-expand"))$("lidar-expand").addEventListener("click",function(){toggleSensorPanel("lidar-panel","lidar-expand","lidar-panel-expanded");});
if($("avis-sensor-expand"))$("avis-sensor-expand").addEventListener("click",function(){toggleSensorPanel("range-panel","avis-sensor-expand","sensor-panel-expanded");});
document.addEventListener("fullscreenchange",function(){
  if(document.fullscreenElement!==null)return;
  [["lidar-panel","lidar-expand","lidar-panel-expanded"],["range-panel","avis-sensor-expand","sensor-panel-expanded"]].forEach(function(item){
    const panel=$(item[0]),button=$(item[1]);if(panel&&panel.classList.contains(item[2]))panel.classList.remove(item[2]);
    if(button)button.textContent="Expand view";
  });
});
