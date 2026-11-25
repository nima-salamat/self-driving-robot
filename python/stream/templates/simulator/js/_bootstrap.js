const $ = function(id){ return document.getElementById(id); };
const camera = $("camera");
let cameraFramePollActive=false,cameraObjectUrl=null,lastCameraFrameSequence=null;
const seenEvents = new Set();
let eventKeys = [];
function setText(id, value){ const e=$(id); if(e) e.textContent = value; }
function numeric(value, places){ return Number.isFinite(Number(value)) ? Number(value).toFixed(places||0) : "—"; }
function status(message, good){ const e=$("save-message"); e.textContent=message||""; e.className="msg"+(good===true?" good":good===false?" bad":""); }
