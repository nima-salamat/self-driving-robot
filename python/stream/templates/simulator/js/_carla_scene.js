let carlaSceneState=null;
let carlaSceneControlsEnabled=false;
let carlaSpawnMapPoints=[];
function carlaSceneMessage(message,kind){
  const el=$("carla-scene-message");if(!el)return;
  el.textContent=message||"";
  el.className="msg carla-scene-message"+(kind==="bad"?" bad":kind==="good"?" good":"");
}
function carlaVehicleIcon(category){
  if(category==="Motorcycle")return "🏍";
  if(category==="Commercial")return "🚚";
  if(category==="SUV / Off-road")return "🚙";
  return "🚗";
}
function renderCarlaVehicles(){
  const grid=$("carla-vehicle-grid");if(!grid||!carlaSceneState)return;
  const query=String(($("carla-vehicle-search")||{}).value||"").trim().toLowerCase();
  const all=carlaSceneState.vehicles||[];
  const vehicles=all.filter(function(v){return (v.name+" "+v.id+" "+v.category).toLowerCase().includes(query);});
  setText("carla-vehicle-count",vehicles.length+" / "+all.length+" vehicles");
  grid.replaceChildren();
  if(!vehicles.length){const empty=document.createElement("div");empty.className="status-message";empty.textContent="No vehicles match this search.";grid.append(empty);return;}
  vehicles.forEach(function(vehicle){
    const selected=vehicle.id===carlaSceneState.current_vehicle_id;
    const button=document.createElement("button");button.type="button";
    button.className="carla-vehicle-card"+(selected?" selected":"");
    button.dataset.blueprintId=vehicle.id;button.disabled=!carlaSceneControlsEnabled;
    const top=document.createElement("div");top.className="vehicle-card-top";
    const icon=document.createElement("span");icon.className="carla-vehicle-icon";icon.textContent=carlaVehicleIcon(vehicle.category);
    const check=document.createElement("span");check.className="carla-card-check";check.textContent=selected?"✓ ACTIVE":"";
    top.append(icon,check);
    const name=document.createElement("span");name.className="vehicle-name";name.textContent=vehicle.name;
    const category=document.createElement("span");category.className="vehicle-category";category.textContent=vehicle.category+(vehicle.wheels?" · "+vehicle.wheels+" wheels":"");
    const id=document.createElement("span");id.className="vehicle-id";id.textContent=vehicle.id;
    button.append(top,name,category,id);grid.append(button);
  });
}
function renderCarlaSpawnList(){
  const list=$("carla-spawn-list");if(!list||!carlaSceneState)return;
  const query=String(($("carla-spawn-search")||{}).value||"").trim().toLowerCase();
  const points=carlaSceneState.spawn_points||[];
  const filtered=points.filter(function(p){
    return ("spawn "+p.index+" "+p.x+" "+p.y+" "+p.z+" "+p.yaw).toLowerCase().includes(query);
  });
  list.replaceChildren();
  if(!filtered.length){const empty=document.createElement("div");empty.className="status-message";empty.textContent="No spawn locations match this search.";list.append(empty);return;}
  filtered.forEach(function(point){
    const selected=Number(point.index)===Number(carlaSceneState.selected_spawn_index);
    const button=document.createElement("button");button.type="button";
    button.className="carla-spawn-card"+(selected?" selected":"");
    button.dataset.spawnIndex=String(point.index);button.disabled=!carlaSceneControlsEnabled;
    const number=document.createElement("span");number.className="carla-spawn-number";number.textContent="#"+String(point.index).padStart(2,"0");
    const info=document.createElement("span");info.className="carla-spawn-info";
    const name=document.createElement("strong");name.textContent=selected?"ACTIVE RESET POINT":"Spawn point "+point.index;
    const coords=document.createElement("small");coords.textContent="X "+point.x.toFixed(1)+" · Y "+point.y.toFixed(1)+" · Z "+point.z.toFixed(1);
    const yaw=document.createElement("small");yaw.textContent="Heading "+point.yaw.toFixed(0)+"°";
    info.append(name,coords,yaw);button.append(number,info);list.append(button);
  });
}
function drawCarlaSpawnMap(){
  const canvas=$("carla-spawn-map");if(!canvas||!carlaSceneState)return;
  const ctx=canvas.getContext("2d"),w=canvas.width,h=canvas.height;
  ctx.clearRect(0,0,w,h);ctx.fillStyle="#09121b";ctx.fillRect(0,0,w,h);
  ctx.strokeStyle="#172a39";ctx.lineWidth=1;
  for(let x=20;x<w;x+=30){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,h);ctx.stroke();}
  for(let y=20;y<h;y+=30){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke();}
  const points=carlaSceneState.spawn_points||[];
  carlaSpawnMapPoints=[];
  if(!points.length){ctx.fillStyle="#8ea3b7";ctx.font="13px system-ui";ctx.fillText("No spawn points returned by this map",18,28);return;}
  const xs=points.map(function(p){return p.x;}),ys=points.map(function(p){return p.y;});
  const minX=Math.min.apply(null,xs),maxX=Math.max.apply(null,xs),minY=Math.min.apply(null,ys),maxY=Math.max.apply(null,ys);
  const pad=28,rangeX=Math.max(1,maxX-minX),rangeY=Math.max(1,maxY-minY);
  const scale=Math.min((w-pad*2)/rangeX,(h-pad*2)/rangeY);
  const usedW=rangeX*scale,usedH=rangeY*scale,offsetX=(w-usedW)/2,offsetY=(h-usedH)/2;
  ctx.fillStyle="#91a7ba";ctx.font="11px ui-monospace,Consolas,monospace";ctx.fillText(points.length+" spawn locations · click a point",12,17);
  points.forEach(function(p){
    const x=offsetX+(p.x-minX)*scale,y=h-(offsetY+(p.y-minY)*scale);
    const selected=Number(p.index)===Number(carlaSceneState.selected_spawn_index);
    carlaSpawnMapPoints.push({index:p.index,x:x,y:y});
    ctx.beginPath();ctx.arc(x,y,selected?7:3.2,0,Math.PI*2);
    ctx.fillStyle=selected?"#71d9a0":"#73c5ff";ctx.fill();
    if(selected){ctx.strokeStyle="#e0fff0";ctx.lineWidth=2;ctx.stroke();ctx.fillStyle="#b7f6d3";ctx.font="bold 11px ui-monospace,Consolas,monospace";ctx.fillText("#"+p.index,x+9,y-8);}
  });
  ctx.fillStyle="#7890a5";ctx.font="10px system-ui";ctx.fillText("World XY projection · not a road mesh",12,h-9);
}
function renderCarlaScene(state){
  if(!state)return;
  carlaSceneState=state;
  setText("carla-current-map",state.current_map||"Unknown world");
  setText("carla-current-vehicle",(state.current_vehicle_name||"No vehicle")+" · "+(state.current_vehicle_id||"not spawned"));
  setText("carla-scene-state",state.available?"Connected · "+(state.spawn_points||[]).length+" spawns":"Waiting for CARLA");
  const maps=state.maps||[],select=$("carla-map-select");
  if(select){
    const old=select.value;select.replaceChildren();
    maps.forEach(function(map){
      const option=document.createElement("option");option.value=map.id;option.textContent=map.name;select.append(option);
    });
    let active=maps.find(function(map){return map.id===state.current_map_id;});
    if(!active)active=maps.find(function(map){return map.name===state.current_map;});
    if(!active&&state.current_map_id){
      const option=document.createElement("option");option.value=state.current_map_id;option.textContent=state.current_map+" (current)";select.insertBefore(option,select.firstChild);active={id:state.current_map_id};
    }
    if(active)select.value=active.id;else if(maps.some(function(map){return map.id===old;}))select.value=old;
    select.disabled=!carlaSceneControlsEnabled||!maps.length;
  }
  const reset=$("carla-reset-spawn");if(reset)reset.disabled=!carlaSceneControlsEnabled||!state.vehicle_location;
  const load=$("carla-load-map");if(load)load.disabled=!carlaSceneControlsEnabled||!maps.length;
  const search=$("carla-vehicle-search");if(search)search.disabled=!state.vehicles||!state.vehicles.length;
  const spawnSearch=$("carla-spawn-search");if(spawnSearch)spawnSearch.disabled=!state.spawn_points||!state.spawn_points.length;
  renderCarlaVehicles();renderCarlaSpawnList();drawCarlaSpawnMap();
}
async function loadCarlaScene(){
  if(!$("carla-scene-panel"))return;
  try{
    const response=await fetch("/api/simulation/carla/scene",{cache:"no-store"});
    const data=await response.json();
    if(!response.ok||!data.success)throw new Error(data.message||"Could not load CARLA scene.");
    renderCarlaScene(data.state);carlaSceneMessage("World and spawn catalog loaded from the connected CARLA server.","good");
  }catch(error){
    setText("carla-scene-state","Unavailable");
    carlaSceneMessage(error.message+" Start CARLA and reconnect the simulator to load maps, vehicles and spawn points.","bad");
  }
}
async function carlaSceneAction(action,payload,confirmation){
  if(!carlaSceneControlsEnabled){carlaSceneMessage("Scene controls are read-only. Enable stream control to make changes.","bad");return;}
  if(confirmation&&!window.confirm(confirmation))return;
  const buttons=[$("carla-load-map"),$("carla-reset-spawn")].filter(Boolean);
  buttons.forEach(function(button){button.disabled=true;});
  carlaSceneMessage("Applying CARLA scene change…");
  try{
    const response=await fetch("/api/simulation/carla/scene",{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify(Object.assign({action:action},payload||{}))
    });
    const data=await response.json();
    if(!response.ok||!data.success)throw new Error(data.message||"CARLA scene operation failed.");
    renderCarlaScene(data.state);
    carlaSceneMessage(data.message||"CARLA scene updated.", "good");
  }catch(error){
    carlaSceneMessage(error.message,"bad");
  }finally{
    if(carlaSceneControlsEnabled){buttons.forEach(function(button){button.disabled=false;});renderCarlaScene(carlaSceneState);}
  }
}
function initCarlaScene(){
  if(!$("carla-scene-panel"))return;
  $("carla-load-map").addEventListener("click",function(){
    const id=$("carla-map-select").value;
    if(!id)return;
    const label=$("carla-map-select").selectedOptions[0].textContent;
    carlaSceneAction("select_map",{map_id:id},"Load "+label+"? CARLA will replace the active world and respawn the vehicle. Current world actors will be removed.");
  });
  $("carla-reset-spawn").addEventListener("click",function(){
    carlaSceneAction("reset_to_spawn",{},"Reset the vehicle to its currently selected spawn point?");
  });
  $("carla-vehicle-search").addEventListener("input",renderCarlaVehicles);
  $("carla-spawn-search").addEventListener("input",renderCarlaSpawnList);
  $("carla-vehicle-grid").addEventListener("click",function(event){
    const button=event.target.closest("button[data-blueprint-id]");if(!button||button.disabled)return;
    const id=button.dataset.blueprintId;if(id===carlaSceneState.current_vehicle_id)return;
    carlaSceneAction("select_vehicle",{blueprint_id:id},"Switch to "+button.querySelector(".vehicle-name").textContent+"? The current vehicle actor and attached sensors will be recreated at the selected spawn point.");
  });
  $("carla-spawn-list").addEventListener("click",function(event){
    const button=event.target.closest("button[data-spawn-index]");if(!button||button.disabled)return;
    const index=Number(button.dataset.spawnIndex);
    if(index===Number(carlaSceneState.selected_spawn_index))return;
    carlaSceneAction("select_spawn_point",{index:index},"Move the vehicle to spawn point #"+index+" and use it as the new Reset target?");
  });
  $("carla-spawn-map").addEventListener("click",function(event){
    const canvas=$("carla-spawn-map"),rect=canvas.getBoundingClientRect();
    const x=(event.clientX-rect.left)*canvas.width/rect.width,y=(event.clientY-rect.top)*canvas.height/rect.height;
    let nearest=null,distance=Infinity;
    carlaSpawnMapPoints.forEach(function(point){const d=Math.hypot(point.x-x,point.y-y);if(d<distance){distance=d;nearest=point;}});
    if(nearest&&distance<20&&nearest.index!==Number(carlaSceneState.selected_spawn_index)){
      carlaSceneAction("select_spawn_point",{index:nearest.index},"Move the vehicle to spawn point #"+nearest.index+" and use it as the new Reset target?");
    }
  });
}
