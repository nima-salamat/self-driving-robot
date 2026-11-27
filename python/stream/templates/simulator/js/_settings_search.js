function bindSettingsSearch(){
 const modal=$("settings-search-modal"),input=$("settings-search"),results=$("settings-search-results");
 const count=$("settings-search-count"),launcher=$("settings-search-open"),closeButton=$("settings-search-close");
 if(!modal||!input||!results||!launcher||!closeButton)return;
 let entries=[],activeIndex=-1,returnFocus=null;
 function buildIndex(){
  entries=[];
  document.querySelectorAll("#settings-form > .setting-block").forEach(function(block){
   if(block.classList.contains("section-hide"))return;
   const heading=block.querySelector(".section-title"),section=heading?heading.textContent.trim():"Settings";
   block.querySelectorAll("input[name],select[name],textarea[name]").forEach(function(control){
    if(control.closest(".section-hide"))return;
    const labels=control.labels?Array.from(control.labels):[];
    const label=labels.map(function(node){return node.textContent.trim();}).filter(Boolean).join(" ");
    const field=control.closest(".field,.check-field")||control.parentElement;
    const context=field?field.textContent.trim().replace(/\s+/g," ").slice(0,150):"";
    const title=label||control.getAttribute("aria-label")||control.name||control.id||section;
    const detail=section+" · "+(control.name||control.id||"setting");
    entries.push({title:title,detail:detail,searchable:[title,detail,control.name,control.id,context].join(" ").toLowerCase(),target:control,kind:"field"});
   });
   block.querySelectorAll("button[data-settings-search]").forEach(function(control){
    const title=control.textContent.trim().replace(/\\s+/g," ");
    const searchable=[title,control.dataset.settingsSearch,section,block.textContent].join(" ").toLowerCase();
    entries.push({title:title,detail:section+" · Open editor",searchable:searchable,target:control,kind:"action"});
   });
   if(heading)entries.push({title:section,detail:"Open section",searchable:(section+" "+block.textContent).toLowerCase(),target:block,kind:"section"});
  });
 }
 function closeSearch(){
  modal.classList.remove("is-open");modal.setAttribute("aria-hidden","true");activeIndex=-1;
  if(returnFocus&&typeof returnFocus.focus==="function")returnFocus.focus({preventScroll:true});
 }
 function openSearch(){
  returnFocus=document.activeElement;input.value="";
  modal.classList.add("is-open");modal.setAttribute("aria-hidden","false");
  renderResults();window.setTimeout(function(){input.focus();},0);
 }
 function jumpTo(entry){
  closeSearch();
  const panel=$("sim-settings-panel");
  const target=entry.target,content=panel&&panel.querySelector(".panel-content");
  if(!target||!content||!panel)return;
  // On narrow screens Settings is below the camera. Bring the whole rail into
  // view first, then scroll its own content to the selected control.
  panel.scrollIntoView({behavior:"smooth",block:"start"});
  const top=content.scrollTop+target.getBoundingClientRect().top-content.getBoundingClientRect().top-24;
  content.scrollTo({top:Math.max(0,top),behavior:"smooth"});
  if(entry.kind==="action"){
   window.setTimeout(function(){target.click();},180);
   return;
  }
  if(entry.kind==="section")target.setAttribute("tabindex","-1");
  target.classList.add("setting-search-highlight");
  window.setTimeout(function(){target.focus({preventScroll:true});},180);
  window.setTimeout(function(){target.classList.remove("setting-search-highlight");},1500);
 }
 function renderResults(){
  const query=String(input.value||"").trim().toLowerCase();
  results.replaceChildren();activeIndex=-1;
  if(!query){
   const empty=document.createElement("div");empty.className="settings-search-empty";
   empty.textContent="Search settings or actions: crosswalk, hardcode routes, sensors, motion, vision, ROI, calibration or PID.";
   results.append(empty);count.textContent=entries.filter(function(item){return item.kind==="field"||item.kind==="action";}).length+" settings and actions indexed";return;
  }
  const matches=entries.map(function(item){
   const title=item.title.toLowerCase(),detail=item.detail.toLowerCase();let score=0;
   if(title===query)score=100;else if(title.startsWith(query))score=55;else if(detail.includes(query))score=35;else if(title.includes(query))score=25;else if(item.searchable.includes(query))score=10;
   return {item:item,score:score};
  }).filter(function(result){return result.score>0;}).sort(function(a,b){return b.score-a.score;}).slice(0,30);
  count.textContent=matches.length?matches.length+" matching results":"No matching settings";
  if(!matches.length){
   const empty=document.createElement("div");empty.className="settings-search-empty";
   empty.textContent="No results. Try crosswalk, hardcode, sign, KP, PID, ROI, threshold or speed.";
   results.append(empty);return;
  }
  matches.forEach(function(match,index){
   const item=match.item,button=document.createElement("button");
   button.type="button";button.className="settings-search-result";button.setAttribute("role","option");
   button.setAttribute("aria-selected","false");button.dataset.resultIndex=String(index);
   const wrap=document.createElement("span");wrap.className="settings-search-result-text";
   const title=document.createElement("strong");title.textContent=item.title;
   const detail=document.createElement("small");detail.textContent=item.detail;
   wrap.append(title,detail);
   const kind=document.createElement("span");kind.className="settings-search-result-kind";kind.textContent=item.kind==="section"?"SECTION":item.kind==="action"?"ACTION":"SETTING";
   button.append(wrap,kind);button.addEventListener("click",function(){jumpTo(item);});
   results.append(button);
  });
  setActive(0);
 }
 function setActive(next){
  const buttons=Array.from(results.querySelectorAll(".settings-search-result"));if(!buttons.length)return;
  activeIndex=(next+buttons.length)%buttons.length;
  buttons.forEach(function(button,index){
   const selected=index===activeIndex;button.classList.toggle("active",selected);button.setAttribute("aria-selected",String(selected));
  });
  buttons[activeIndex].scrollIntoView({block:"nearest"});
 }
 input.addEventListener("input",renderResults);
 input.addEventListener("keydown",function(event){
  if(event.key==="Escape"){event.preventDefault();closeSearch();}
  else if(event.key==="ArrowDown"){event.preventDefault();setActive(activeIndex+1);}
  else if(event.key==="ArrowUp"){event.preventDefault();setActive(activeIndex<0?0:activeIndex-1);}
  else if(event.key==="Enter"&&results.querySelector(".settings-search-result")){
   event.preventDefault();if(activeIndex<0)setActive(0);
   const selected=results.querySelector('[data-result-index="'+activeIndex+'"]');if(selected)selected.click();
  }
 });
 closeButton.addEventListener("click",closeSearch);
 modal.addEventListener("click",function(event){if(event.target===modal)closeSearch();});
 launcher.addEventListener("click",openSearch);
 window.addEventListener("keydown",function(event){
  if((event.ctrlKey||event.metaKey)&&!event.altKey&&(String(event.key||"").toLowerCase()==="k"||event.code==="KeyK")){
   event.preventDefault();event.stopPropagation();
   if(typeof event.stopImmediatePropagation==="function")event.stopImmediatePropagation();
   if(modal.classList.contains("is-open"))input.focus();else openSearch();
  }
  if(event.key==="Escape"&&modal.classList.contains("is-open")){event.preventDefault();closeSearch();}
 },true);
 buildIndex();renderResults();
}
bindSettingsSearch();

