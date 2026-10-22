(function(root){
'use strict';
function createCommandHistory(options){
  options=options||{};const storage=options.storage||null,key=String(options.key||'');
  const limit=Math.max(1,Math.min(1000,Math.floor(Number(options.limit)||100)));
  let items=[],index=0,draft='';
  try{const saved=storage&&key?JSON.parse(storage.getItem(key)||'[]'):[];
    if(Array.isArray(saved))items=saved.filter(value=>typeof value==='string'&&value.trim()).map(value=>value.trim().slice(0,256)).slice(-limit);
  }catch(_){items=[];}
  index=items.length;
  function persist(){try{if(storage&&key)storage.setItem(key,JSON.stringify(items.slice(-limit));}catch(_){}}
  function remember(value){
    const command=String(value==null?'':value).trim().slice(0,256);if(!command)return '';
    if(items[items.length-1]!==command)items.push(command);
    if(items.length>limit)items=items.slice(-limit);
    index=items.length;draft='';persist();return command;
  }
  function move(direction,currentValue){
    if(!items.length)return {handled:false};
    if(Number(direction)<0){
      if(index===items.length)draft=String(currentValue==null?'':currentValue);
      if(index<=0)return {handled:false};
      index--;return {handled:true,value:items[index],index:index};
    }
    if(index>=items.length)return {handled:false};
    index++;return {handled:true,value:index===items.length?draft:items[index],index:index};
  }
  function edit(value){if(index<items.length)index=items.length;draft=String(value==null?'':value);}
  function resetAfterSend(){index=items.length;draft='';}
  return {remember,move,edit,resetAfterSend,get length(){return items.length;},get index(){return index;},snapshot:()=>items.slice()};
}
function normalizeEditorTool(value){return ['select','pan','annotate','ruler'].includes(value)?value:'select';}
function normalizeWorkspaceToolState(view){
  view=view&&typeof view==='object'?view:{};
  const crosshairEnabled=view.crosshair===true,saved=view.crosshairPoint;let point=null;
  if(crosshairEnabled&&saved&&['image','canvas'].includes(saved.space)&&Number.isFinite(Number(saved.u))&&Number.isFinite(Number(saved.v))){
    point={space:saved.space,u:Number(saved.u),v:Number(saved.v)};
  }
  return {editorTool:normalizeEditorTool(view.tool),crosshairEnabled,crosshairPoint:point,crosshairPinned:!!point};
}
root.StreamState=Object.freeze({createCommandHistory,normalizeEditorTool,normalizeWorkspaceToolState});
})(typeof window!=='undefined'?window:globalThis);
