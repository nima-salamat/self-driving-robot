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
  function persist(){try{if(storage&&key)storage.setItem(key,JSON.stringify(items.slice(-limit)));}catch(_){}}
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
  function clear(){items=[];index=0;draft='';persist();}
  return {remember,move,edit,resetAfterSend,clear,get length(){return items.length;},get index(){return index;},snapshot:()=>items.slice()};
}
function createCommandFavorites(options){
  options=options||{};
  const storage=options.storage||null,key=String(options.key||'');
  const limit=Math.max(1,Math.min(100,Math.floor(Number(options.limit)||25)));
  let items=[];
  function normalize(label,command){
    label=String(label==null?'':label).trim().slice(0,48);
    command=String(command==null?'':command).trim().slice(0,256);
    const labelSafe=label.split('').every(ch=>{const code=ch.charCodeAt(0);return code>=32&&code!==127;});
    const commandSafe=command.split('').every(ch=>{const code=ch.charCodeAt(0);return code>=32&&code<=126;});
    if(!label||!command||!labelSafe||!commandSafe)return null;
    return {label,command};
  }  try{
    const saved=storage&&key?JSON.parse(storage.getItem(key)||'[]'):[];
    if(Array.isArray(saved))saved.forEach(value=>{
      if(!value||typeof value!=='object')return;
      const item=normalize(value.label,value.command);if(!item)return;
      const existing=items.findIndex(entry=>entry.label.toLowerCase()===item.label.toLowerCase());
      if(existing>=0)items[existing]=item;else items.push(item);
    });
    if(items.length>limit)items=items.slice(-limit);
  }catch(_){items=[];}
  function persist(){try{if(storage&&key)storage.setItem(key,JSON.stringify(items));}catch(_){}}
  function add(label,command){
    const item=normalize(label,command);if(!item)return null;
    const existing=items.findIndex(entry=>entry.label.toLowerCase()===item.label.toLowerCase());
    if(existing>=0)items[existing]=item;else items.push(item);
    if(items.length>limit)items=items.slice(-limit);
    persist();return {...item};
  }
  function remove(label){
    const index=items.findIndex(item=>item.label.toLowerCase()===String(label==null?'':label).trim().toLowerCase());
    if(index<0)return false;
    items.splice(index,1);persist();return true;
  }
  function clear(){items=[];persist();}
  return {add,remove,clear,get length(){return items.length;},snapshot:()=>items.map(item=>({...item}))};
}
function normalizeEditorTool(value){return ['select','pan','annotate','ruler'].includes(value)?value:'select';}
function normalizeWorkspaceToolState(view){
  view=view&&typeof view==='object'?view:{};
  const crosshairEnabled=view.crosshair===true,saved=view.crosshairPoint;let point=null;
  const validSpace=saved&&['image','canvas'].includes(saved.space);
  const hasCoordinates=saved&&saved.u!==null&&saved.u!==''&&saved.v!==null&&saved.v!=='';
  const u=hasCoordinates?Number(saved.u):NaN,v=hasCoordinates?Number(saved.v):NaN;
  const rangeValid=validSpace&&Number.isFinite(u)&&Number.isFinite(v)&&
    (saved.space==='image'?(u>=-1000000&&u<=1000000&&v>=-1000000&&v<=1000000):(u>=0&&u<=1&&v>=0&&v<=1));
  if(crosshairEnabled&&rangeValid)point={space:saved.space,u:u,v:v};
  return {editorTool:normalizeEditorTool(view.tool),crosshairEnabled,crosshairPoint:point,crosshairPinned:!!point};
}
root.StreamState=Object.freeze({createCommandHistory,createCommandFavorites,normalizeEditorTool,normalizeWorkspaceToolState});
})(typeof window!=='undefined'?window:globalThis);
