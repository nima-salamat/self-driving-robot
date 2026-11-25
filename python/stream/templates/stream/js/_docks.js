function initializeResize(){
  const container=document.querySelector('.container'),panel=document.querySelector('.right-panel'),handle=$('panel_resize_handle');
  if(!container||!panel||!handle)return;
  let active=false,startX=0,startWidth=315;
  function limits(){
    const minimum=250;
    const maximum=Math.max(minimum,Math.min(700,window.innerWidth-360));
    return {minimum:minimum,maximum:maximum};
  }
  function announceWidth(width){
    const bounds=limits();
    handle.setAttribute('aria-valuemin',String(bounds.minimum));
    handle.setAttribute('aria-valuemax',String(bounds.maximum));
    handle.setAttribute('aria-valuenow',String(Math.round(width)));
    handle.setAttribute('aria-valuetext',Math.round(width)+' pixels wide');
  }
  function setWidth(requested){
    const bounds=limits();
    const width=Math.round(Math.min(bounds.maximum,Math.max(bounds.minimum,Number(requested)||315)));
    container.style.setProperty('--right-pane-width',width+'px');
    announceWidth(width);
  }
  function finishResize(){
    if(!active)return;
    active=false;
    container.classList.remove('panel-resizing');
    scheduleWorkspaceSave();
  }
  handle.addEventListener('pointerdown',function(event){
    if(window.innerWidth<721||(event.button!==0&&event.pointerType!=='touch'))return;
    active=true;
    startX=event.clientX;
    startWidth=parseFloat(getComputedStyle(container).getPropertyValue('--right-pane-width'))||panel.getBoundingClientRect().width;
    container.classList.add('panel-resizing');
    handle.setPointerCapture(event.pointerId);
    event.preventDefault();
  });
  handle.addEventListener('pointermove',function(event){
    if(!active)return;
    setWidth(startWidth-(event.clientX-startX));
  });
  handle.addEventListener('pointerup',finishResize);
  handle.addEventListener('pointercancel',finishResize);
  handle.addEventListener('keydown',function(event){
    if(window.innerWidth<721)return;
    const bounds=limits();
    const current=parseFloat(getComputedStyle(container).getPropertyValue('--right-pane-width'))||panel.getBoundingClientRect().width;
    if(event.key==='ArrowLeft'){event.preventDefault();setWidth(current+24);scheduleWorkspaceSave();}
    else if(event.key==='ArrowRight'){event.preventDefault();setWidth(current-24);scheduleWorkspaceSave();}
    else if(event.key==='Home'){event.preventDefault();setWidth(bounds.minimum);scheduleWorkspaceSave();}
    else if(event.key==='End'){event.preventDefault();setWidth(bounds.maximum);scheduleWorkspaceSave();}
  });
  window.addEventListener('resize',function(){
    if(window.innerWidth<721)return;
    const saved=parseFloat(getComputedStyle(container).getPropertyValue('--right-pane-width'));
    if(Number.isFinite(saved))setWidth(saved);
    else announceWidth(panel.getBoundingClientRect().width);
  });
  announceWidth(parseFloat(getComputedStyle(container).getPropertyValue('--right-pane-width'))||panel.getBoundingClientRect().width);
}
function initializeConsoleResize(){
  const consoleDock=$('bottom_console'),handle=$('console_resize_handle'),toggle=$('console_toggle_btn');
  if(!consoleDock||!handle||!toggle)return;
  let active=false,startY=0,startHeight=178,lastExpandedHeight=178;
  function limits(){
    const mobile=window.matchMedia('(max-width: 720px)').matches;
    const shortLandscape=window.matchMedia('(max-width: 900px) and (orientation: landscape) and (max-height: 520px)').matches;
    const minimum=mobile?84:96;
    const maximum=Math.max(minimum,Math.min(
      shortLandscape?200:(mobile?360:520),
      window.innerHeight*(shortLandscape?0.42:(mobile?0.55:0.62)),
      window.innerHeight-(mobile?80:120)
    ));
    return {minimum:minimum,maximum:maximum,mobile:mobile};
  }
  function closedHeight(bounds){return bounds.mobile?38:42;}
  function isOpen(){return consoleDock.classList.contains('console-open');}
  function toggleOpen(open){
    if(isOpen()!==open)toggle.click();
  }
  function announceSize(height){
    const bounds=limits(),closed=closedHeight(bounds),open=isOpen();
    handle.setAttribute('aria-valuemin',String(closed));
    handle.setAttribute('aria-valuemax',String(Math.round(bounds.maximum)));
    handle.setAttribute('aria-valuenow',String(Math.round(open?Math.max(closed,Math.min(bounds.maximum,height)):closed)));
    handle.setAttribute('aria-valuetext',open?Math.round(height)+' pixels tall':'Closed. Drag upward to open and downward to close.');
  }
  function setHeight(requested,allowCollapsedRange){
    const bounds=limits(),closed=closedHeight(bounds);
    const minimum=allowCollapsedRange?closed:bounds.minimum;
    const numeric=Number(requested);
    const finite=Number.isFinite(numeric)?numeric:bounds.minimum;
    const height=Math.round(Math.min(bounds.maximum,Math.max(minimum,finite)));
    consoleDock.style.setProperty('--console-resize-height',height+'px');
    if(height>=bounds.minimum)lastExpandedHeight=height;
    announceSize(height);
    return height;
  }
  function finishResize(){
    if(!active)return;
    const bounds=limits(),height=consoleDock.getBoundingClientRect().height;
    if(isOpen()&&height<bounds.minimum){
      /* Closing by drag shouldn't poison the remembered expanded height. */
      consoleDock.style.setProperty('--console-resize-height',Math.max(bounds.minimum,lastExpandedHeight)+'px');
      toggleOpen(false);
    }else if(isOpen()){
      setHeight(height,false);
    }else{
      consoleDock.style.setProperty('--console-resize-height',Math.max(bounds.minimum,lastExpandedHeight)+'px');
    }
    active=false;
    consoleDock.classList.remove('console-resizing');
    announceSize(consoleDock.getBoundingClientRect().height);
  }
  handle.addEventListener('pointerdown',function(event){
    if(event.button!==0&&event.pointerType!=='touch')return;
    const bounds=limits();
    active=true;
    startY=event.clientY;
    startHeight=consoleDock.getBoundingClientRect().height;
    lastExpandedHeight=isOpen()?Math.max(bounds.minimum,startHeight):Math.max(bounds.minimum,parseFloat(consoleDock.style.getPropertyValue('--console-resize-height'))||178);
    consoleDock.classList.add('console-resizing');
    try{handle.setPointerCapture(event.pointerId);}catch(_error){}
    event.preventDefault();
  });
  handle.addEventListener('pointermove',function(event){
    if(!active)return;
    const bounds=limits(),closed=closedHeight(bounds);
    const requested=startHeight-(event.clientY-startY);
    if(requested<=closed){
      /* Dragging down past the collapsed height closes the console. */
      consoleDock.style.setProperty('--console-resize-height',Math.max(bounds.minimum,lastExpandedHeight)+'px');
      toggleOpen(false);
      announceSize(closed);
      return;
    }
    /* The same grip expands upward and collapses downward, continuously. */
    const height=setHeight(requested,true);
    toggleOpen(true);
    if(height>=bounds.minimum)lastExpandedHeight=height;
    announceSize(height);
  });
  handle.addEventListener('pointerup',finishResize);
  handle.addEventListener('pointercancel',finishResize);
  handle.addEventListener('keydown',function(event){
    const bounds=limits(),closed=closedHeight(bounds),current=consoleDock.getBoundingClientRect().height;
    if(event.key==='ArrowUp'){
      event.preventDefault();
      if(!isOpen()){setHeight(bounds.minimum,false);toggleOpen(true);}
      else setHeight(current+24,false);
    }else if(event.key==='ArrowDown'){
      event.preventDefault();
      if(isOpen()&&current<=bounds.minimum+24){
        consoleDock.style.setProperty('--console-resize-height',Math.max(bounds.minimum,lastExpandedHeight)+'px');
        toggleOpen(false);
      }else if(isOpen())setHeight(current-24,false);
    }else if(event.key==='Home'){
      event.preventDefault();
      if(isOpen())setHeight(bounds.minimum,false);
      else announceSize(closed);
    }else if(event.key==='End'){
      event.preventDefault();
      setHeight(bounds.maximum,false);
      toggleOpen(true);
    }
  });
  window.addEventListener('resize',function(){
    const bounds=limits();
    if(!isOpen()){announceSize(closedHeight(bounds));return;}
    const saved=parseFloat(consoleDock.style.getPropertyValue('--console-resize-height'));
    if(Number.isFinite(saved))setHeight(saved,false);
    else announceSize(consoleDock.getBoundingClientRect().height);
  });
  const saved=parseFloat(consoleDock.style.getPropertyValue('--console-resize-height'));
  if(Number.isFinite(saved)&&saved>=limits().minimum)lastExpandedHeight=saved;
  announceSize(consoleDock.getBoundingClientRect().height);
}
function installCoordinatePairPaste(){
  ['prop_left','prop_top','prop_right','prop_bottom','prop_point_x','prop_point_y'].forEach(function(id){
    const field=$(id);if(!field)return;
    field.addEventListener('paste',function(event){
      const transfer=event.clipboardData||window.clipboardData;
      const text=transfer&&transfer.getData?transfer.getData('text'):'';
      const match=String(text||'').match(/^\s*(-?(?:\d+\.?\d*|\.\d+))\s*[,;\s]\s*(-?(?:\d+\.?\d*|\.\d+))\s*$/);
      if(!match)return;
      const a=Number(match[1]),b=Number(match[2]);if(!Number.isFinite(a)||!Number.isFinite(b))return;
      const target=$('prop_target')?$('prop_target').value:'NONE';
      let ids=[];
      if(['RL','LL','CW','ST','OBJ'].includes(target)){
        if(a<0||a>1||b<0||b>1){showToast('ROI coordinates must be between 0 and 1.');event.preventDefault();return;}
        if(['prop_left','prop_top'].includes(id))ids=['prop_left','prop_top'];
        else if(['prop_right','prop_bottom'].includes(id))ids=['prop_right','prop_bottom'];
        else return;
      }else if(target.startsWith('BEV_')&&['prop_point_x','prop_point_y'].includes(id)){
        if(a< -5||a>5||b< -5||b>5){showToast('BEV coordinates must be between -5 and 5.');event.preventDefault();return;}
        ids=['prop_point_x','prop_point_y'];
      }else return;
      event.preventDefault();
      $(ids[0]).value=a.toFixed(3);$(ids[1]).value=b.toFixed(3);
      const hint=$('prop_hint');if(hint)hint.textContent='Point pasted as U/X='+a.toFixed(3)+', V/Y='+b.toFixed(3)+'. Click Apply to save this ROI corner.';
      updateEditorStatus('Coordinate pair pasted into '+ids.join(' and ')+'. Click Apply to save.');
      showToast('Pasted coordinate pair into '+(ids[0]==='prop_left'?'ROI first corner':ids[0]==='prop_right'?'ROI second corner':'BEV point')+'. Click Apply.');
    });
  });
}

