function initAvisBottomDock(){
 const dock=$("avis-bottom-dock"),handle=$("avis-dock-handle");if(!dock||!handle)return;
 const tabs=Array.from(dock.querySelectorAll("[data-dock-tab]")),panes=Array.from(dock.querySelectorAll("[data-dock-pane]"));
 const toggle=$("avis-dock-toggle");let drag=null;
 function maxHeight(){return Math.min(460,Math.max(220,Math.round(window.innerHeight*.62)));}
 function setHeight(value){
  const height=Math.max(76,Math.min(460,Math.min(maxHeight(),Math.round(value))));
  const expanded=height>110;
  dock.style.setProperty("--avis-dock-height",height+"px");dock.classList.toggle("is-expanded",expanded);
  handle.setAttribute("aria-valuenow",String(height));
  handle.setAttribute("aria-valuetext",expanded?"Expanded to "+height+" pixels. Drag to resize.":"Collapsed. Drag upward to expand.");
  if(toggle){toggle.textContent=expanded?"⌄":"⌃";toggle.setAttribute("aria-label",expanded?"Collapse bottom dock":"Expand bottom dock");toggle.setAttribute("aria-expanded",String(expanded));}
 }
 function expand(){setHeight(Math.min(310,maxHeight()));}
 function toggleDock(){if(dock.classList.contains("is-expanded"))setHeight(76);else expand();}
 function selectTab(name){
  tabs.forEach(function(tab){const active=tab.dataset.dockTab===name;tab.classList.toggle("active",active);tab.setAttribute("aria-selected",String(active));tab.setAttribute("tabindex",active?"0":"-1");});
  panes.forEach(function(pane){const active=pane.dataset.dockPane===name;pane.classList.toggle("active",active);pane.hidden=!active;});
  if(!dock.classList.contains("is-expanded"))expand();
 }
 tabs.forEach(function(tab){
  tab.addEventListener("click",function(){selectTab(tab.dataset.dockTab);});
  tab.addEventListener("keydown",function(event){
   if(event.key!=="ArrowRight"&&event.key!=="ArrowLeft")return;
   event.preventDefault();const index=tabs.indexOf(tab),direction=event.key==="ArrowRight"?1:-1;
   const next=tabs[(index+direction+tabs.length)%tabs.length];next.focus();selectTab(next.dataset.dockTab);
  });
 });
 if(toggle)toggle.addEventListener("click",toggleDock);
 handle.addEventListener("pointerdown",function(event){
  if(event.target.closest("button"))return;
  drag={y:event.clientY,height:dock.getBoundingClientRect().height,moved:false};
  if(handle.setPointerCapture)handle.setPointerCapture(event.pointerId);
  event.preventDefault();
 });
 handle.addEventListener("pointermove",function(event){
  if(!drag)return;const delta=drag.y-event.clientY;if(Math.abs(delta)>4)drag.moved=true;
  if(drag.moved)setHeight(drag.height+delta);
 });
 function finish(){if(!drag)return;const moved=drag.moved;drag=null;if(!moved)toggleDock();}
 handle.addEventListener("pointerup",finish);handle.addEventListener("pointercancel",finish);
 handle.addEventListener("keydown",function(event){
  if(event.key==="ArrowUp"){event.preventDefault();setHeight(dock.getBoundingClientRect().height+28);}
  else if(event.key==="ArrowDown"){event.preventDefault();setHeight(dock.getBoundingClientRect().height-28);}
  else if(event.key==="Enter"||event.key===" "){event.preventDefault();toggleDock();}
 });
 selectTab("overview");setHeight(76);
}
initAvisBottomDock();
