function paletteNormalize(value){
  const raw=String(value==null?'':value);
  return (typeof raw.normalize==='function'?raw.normalize('NFKC'):raw).toLocaleLowerCase();
}
function palettePanelTrail(detail){
  const parts=[];let current=detail;
  while(current&&current.matches&&current.matches('details.dock-panel')){
    const summary=current.querySelector(':scope > summary');
    const name=summary?summary.textContent.replace(/\s+/g,' ').trim():'Panel';
    if(name)parts.push(name);
    current=current.parentElement?current.parentElement.closest('details.dock-panel'):null;
  }
  return parts.reverse().join(' › ')||'Settings';
}
function settingSearchEntries(){
  const entries=[],seen=new Set();
  function add(label,panelTitle,detail,target,focusTarget,modal,kind){
    const name=String(label||'').replace(/\s+/g,' ').trim();
    if(name.length<2)return;
    const node=target||detail||focusTarget;if(!node)return;
    const identity=(panelTitle+'|'+name+'|'+(node.id||node.tagName||'item')).toLocaleLowerCase();
    if(seen.has(identity))return;seen.add(identity);
    const extra=[node.id,node.title,node.getAttribute&&node.getAttribute('aria-label'),focusTarget&&focusTarget.id,focusTarget&&focusTarget.placeholder].filter(Boolean).join(' ');
    entries.push({label:name,panelTitle:panelTitle,detail:detail,target:node,focusTarget:focusTarget||node,modal:!!modal,kind:kind||'SETTING',
      searchable:paletteNormalize(name+' '+panelTitle+' '+extra+' '+(kind||'setting'))});
  }
  document.querySelectorAll('.right-panel details.dock-panel').forEach(function(detail){
    const summary=detail.querySelector(':scope > summary');
    const panelTitle=palettePanelTrail(detail);
    if(summary)add('Open panel: '+summary.textContent,panelTitle,detail,summary,summary,false,'PANEL');
    detail.querySelectorAll('.dock-content label,.dock-content .section-title,.dock-content h3,.dock-content button,.dock-content .small-muted,.dock-content .settings-note').forEach(function(node){
      if(node.closest('details.dock-panel')!==detail)return;
      let focus=node.control||null;
      if(node.tagName==='LABEL'){
        if(!focus&&node.htmlFor)focus=document.getElementById(node.htmlFor);
        if(!focus)focus=node.querySelector('input,select,textarea,button');
      }
      const kind=node.matches('button')?'ACTION':node.matches('label')?'SETTING':'SECTION';
      add(node.textContent,panelTitle,detail,node,focus||node,false,kind);
    });
    detail.querySelectorAll('.dock-content input,.dock-content select,.dock-content textarea').forEach(function(control){
      if(control.closest('details.dock-panel')!==detail)return;
      const labels=control.labels?Array.from(control.labels):[];
      const label=labels.map(function(x){return x.textContent;}).join(' ').trim()||control.getAttribute('aria-label')||control.title||control.placeholder||control.name||control.id;
      if(!label)return;
      if(labels.length)return;
      add(label,panelTitle,detail,control,control,false,'SETTING');
    });
    detail.querySelectorAll('.dock-content select').forEach(function(control){
      if(control.closest('details.dock-panel')!==detail)return;
      Array.from(control.options||[]).forEach(function(option){
        if(!option.textContent.trim())return;
        const label=(control.labels&&control.labels.length?Array.from(control.labels).map(function(x){return x.textContent;}).join(' '):control.getAttribute('aria-label')||control.id)+' · '+option.textContent.trim();
        add(label,panelTitle,detail,control,control,false,'OPTION');
      });
    });
  });
  const editorSettings=document.getElementById('roi_settings_dialog');
  if(editorSettings){
    editorSettings.querySelectorAll('.settings-section h3').forEach(function(node){
      add(node.textContent,'Editor Settings',null,node,node,true,'SECTION');
    });
    editorSettings.querySelectorAll('.settings-section label').forEach(function(node){
      const focus=node.control||(node.htmlFor?document.getElementById(node.htmlFor):node.querySelector('input,select,textarea'));
      add(node.textContent,'Editor Settings',null,node,focus||node,true,'SETTING');
    });
    editorSettings.querySelectorAll('.settings-section select').forEach(function(control){
      Array.from(control.options||[]).forEach(function(option){
        add((control.labels&&control.labels.length?Array.from(control.labels).map(function(x){return x.textContent;}).join(' '):'Editor setting')+' · '+option.textContent,'Editor Settings',null,control,control,true,'OPTION');
      });
    });
    editorSettings.querySelectorAll('.settings-note').forEach(function(node){
      add(node.textContent,'Editor Settings',null,node,node,true,'HELP');
    });
  }
  return entries;
}
function navigateToPaletteSetting(entry){
  closeCommandPalette();
  function revealAndFocus(){
    if(entry.modal){
      const modal=$('roi_settings_dialog');
      if(modal&&!modal.classList.contains('is-open'))$('roi_settings_open').click();
    }else if(typeof window.ensureStreamDockVisible==='function'){
      window.ensureStreamDockVisible();
    }
    if(entry.detail){
      const ancestors=[];let detail=entry.detail;
      while(detail&&detail.matches&&detail.matches('details.dock-panel')){
        ancestors.push(detail);
        detail=detail.parentElement?detail.parentElement.closest('details.dock-panel'):null;
      }
      ancestors.reverse().forEach(function(panel){panel.open=true;});
    }
    window.requestAnimationFrame(function(){
      window.requestAnimationFrame(function(){
        const target=entry.target;
        if(!target||!target.isConnected)return;
        target.scrollIntoView({behavior:'smooth',block:'center',inline:'nearest'});
        const focus=entry.focusTarget;
        if(focus&&typeof focus.focus==='function'&&!focus.disabled){
          try{focus.focus({preventScroll:true});}catch(_){focus.focus();}
        }
        if(target.__paletteHighlightTimer)clearTimeout(target.__paletteHighlightTimer);
        target.classList.remove('palette-setting-highlight');
        void target.offsetWidth;
        target.classList.add('palette-setting-highlight');
        target.__paletteHighlightTimer=setTimeout(function(){
          target.classList.remove('palette-setting-highlight');
          target.__paletteHighlightTimer=null;
        },2100);
      });
    });
  }
  revealAndFocus();
}
function isPaletteCommandActive(name){
  if(name==='view-lock')return typeof window.isWorkspaceViewLocked==='function'&&window.isWorkspaceViewLocked();
  if(name==='select')return editorTool==='select';
  if(name==='pan')return editorTool==='pan';
  if(name==='annotate')return editorTool==='annotate';
  if(name==='ruler')return editorTool==='ruler';
  if(name==='grid')return !!($('ext_grid')&&$('ext_grid').checked);
  if(name==='crosshair')return !!($('ext_crosshair')&&$('ext_crosshair').checked);
  if(name==='overlays')return !!($('ext_overlays')&&$('ext_overlays').checked);
  if(name==='profile')return !!($('ext_editor_panel')&&$('ext_editor_panel').open&&document.activeElement===$('ext_profile_name'));
  if(name==='preset')return !!($('ext_config_panel')&&$('ext_config_panel').open&&document.activeElement===$('ext_preset_name'));
  return false;
}
function isEditableKeyboardTarget(target){
  return !!(target&&(
    target.isContentEditable||
    ['INPUT','TEXTAREA','SELECT'].includes(target.tagName)||
    target.closest&&target.closest('[contenteditable="true"]')
  ));
}
function toggleSettingsPanels(){
  const button=$('toggle_dock_btn');
  if(button)button.click();
}
function focusPanelNavigation(){
  const container=document.querySelector('.container');
  if(typeof window.ensureStreamDockVisible==='function')window.ensureStreamDockVisible();
  else if(container&&(container.classList.contains('dock-hidden')||(window.matchMedia('(max-width: 720px)').matches&&!container.classList.contains('show-dock'))))toggleSettingsPanels();
  window.requestAnimationFrame(function(){
    const first=document.querySelector('.right-panel details.dock-panel > summary');
    if(first)first.focus();
    else showToast('Settings panel navigation is unavailable.');
  });
}
function adjustSettingsPanelWidth(direction){
  if(window.innerWidth<721)return;
  const container=document.querySelector('.container');
  const panel=document.querySelector('.right-panel');
  if(!container||!panel||container.classList.contains('dock-hidden'))return;
  const current=parseFloat(getComputedStyle(container).getPropertyValue('--right-pane-width'))||panel.getBoundingClientRect().width||315;
  const minimum=250,maximum=Math.max(minimum,Math.min(700,window.innerWidth-360));
  const width=Math.round(Math.max(minimum,Math.min(maximum,current+(direction>0?24:-24))));
  container.style.setProperty('--right-pane-width',width+'px');
  const handle=$('panel_resize_handle');
  if(handle){
    handle.setAttribute('aria-valuenow',String(width));
    handle.setAttribute('aria-valuetext',width+' pixels wide');
  }
  if(typeof scheduleWorkspaceSave==='function')scheduleWorkspaceSave();
}
function consoleResizeLimits(){
  const mobile=window.matchMedia('(max-width: 720px)').matches;
  const shortLandscape=window.matchMedia('(max-width: 900px) and (orientation: landscape) and (max-height: 520px)').matches;
  const minimum=mobile?84:96;
  const maximum=Math.max(minimum,Math.min(shortLandscape?200:(mobile?360:520),window.innerHeight*(shortLandscape?0.42:(mobile?0.55:0.62)),window.innerHeight-(mobile?80:120)));
  return {minimum:minimum,maximum:maximum};
}
function changeConsoleHeight(direction){
  const dock=$('bottom_console'),toggle=$('console_toggle_btn'),handle=$('console_resize_handle');
  if(!dock||!toggle)return;
  const bounds=consoleResizeLimits(),isOpen=dock.classList.contains('console-open');
  let current=parseFloat(dock.style.getPropertyValue('--console-resize-height'));
  if(!Number.isFinite(current))current=isOpen?(dock.getBoundingClientRect().height||178):178;
  if(direction>0){
    if(!isOpen){
      const height=Math.max(bounds.minimum,Math.min(bounds.maximum,178));
      dock.style.setProperty('--console-resize-height',height+'px');
      toggle.click();
      if(handle){handle.setAttribute('aria-valuenow',String(height));handle.setAttribute('aria-valuetext',height+' pixels tall');}
    }else{
      const height=Math.max(bounds.minimum,Math.min(bounds.maximum,current+24));
      dock.style.setProperty('--console-resize-height',height+'px');
      if(handle){handle.setAttribute('aria-valuenow',String(height));handle.setAttribute('aria-valuetext',height+' pixels tall');}
    }
  }else if(isOpen){
    if(current<=bounds.minimum+24){
      toggle.click();
      if(handle)handle.setAttribute('aria-valuetext','Closed. Drag upward to open and downward to close.');
    }else{
      const height=Math.max(bounds.minimum,current-24);
      dock.style.setProperty('--console-resize-height',height+'px');
      if(handle){handle.setAttribute('aria-valuenow',String(height));handle.setAttribute('aria-valuetext',height+' pixels tall');}
    }
  }
  if(typeof scheduleWorkspaceSave==='function')scheduleWorkspaceSave();
}
function openTopMenu(menuId){
  const menu=document.querySelector('.app-menubar .menu-group[data-menu-id="'+menuId+'"]');
  if(!menu)return;
  document.querySelectorAll('.app-menubar .menu-group').forEach(function(item){item.open=item===menu;});
  const first=menu.querySelector('.menu-dropdown button:not(:disabled)');
  const summary=menu.querySelector(':scope > summary');
  if(first)first.focus();else if(summary)summary.focus();
}
function installWorkspaceKeyboardShortcuts(){
  const menuKeyMap={KeyF:'file',KeyE:'edit',KeyV:'view',KeyT:'tools',KeyH:'help'};
  function isAltGraph(event){return !!(event.getModifierState&&event.getModifierState('AltGraph'));}
  function syncMnemonicHints(event){
    const bar=document.querySelector('.app-menubar');
    if(bar)bar.classList.toggle('shortcuts-visible',!!(event&&event.ctrlKey&&event.altKey&&!event.metaKey&&!isAltGraph(event)));
  }
  document.addEventListener('keydown',function(event){
    syncMnemonicHints(event);
    const target=event.target;
    const menuItem=target&&target.closest?target.closest('.menu-dropdown button'):null;
    if(menuItem&&menuItem.closest('.menu-group[open]')){
      const menu=menuItem.closest('.menu-group[open]');
      const items=Array.from(menu.querySelectorAll('.menu-dropdown button:not(:disabled)'));
      const index=items.indexOf(menuItem);
      if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){
        event.preventDefault();
        let next=index;
        if(event.key==='ArrowDown')next=(index+1)%items.length;
        else if(event.key==='ArrowUp')next=(index-1+items.length)%items.length;
        else if(event.key==='Home')next=0;
        else next=items.length-1;
        if(items[next])items[next].focus();
        return;
      }
      if(event.key==='Escape'){
        event.preventDefault();event.stopPropagation();menu.open=false;
        const summary=menu.querySelector(':scope > summary');if(summary)summary.focus();
        return;
      }
    }
    if(target&&target.matches&&target.matches('.right-panel .dock-panel > summary')){
      const summaries=Array.from(document.querySelectorAll('.right-panel .dock-panel > summary'));
      const index=summaries.indexOf(target);
      if(event.key==='ArrowDown'||event.key==='ArrowUp'){
        event.preventDefault();
        const delta=event.key==='ArrowDown'?1:-1;
        const next=(index+delta+summaries.length)%summaries.length;
        if(summaries[next])summaries[next].focus();
        return;
      }
      if(event.key==='Home'||event.key==='End'){
        event.preventDefault();
        const next=event.key==='Home'?summaries[0]:summaries[summaries.length-1];
        if(next)next.focus();
        return;
      }
      // Space and Enter keep native <summary> toggle behaviour.
    }
    const palette=$('ext_command_palette');
    if(palette&&palette.style.display==='flex')return;
    if(!(event.ctrlKey&&event.altKey&&!event.metaKey)||isAltGraph(event))return;
    const menuId=menuKeyMap[event.code];
    if(event.repeat&&(menuId||['KeyP','KeyC','KeyR'].includes(event.code)))return;
    if(menuId){
      if(isEditableKeyboardTarget(target))return;
      event.preventDefault();event.stopPropagation();
      openTopMenu(menuId);
      return;
    }
    if(isEditableKeyboardTarget(target))return;
    switch(event.code){
      case 'KeyP':
        event.preventDefault();event.stopPropagation();
        if(event.shiftKey)focusPanelNavigation();
        else toggleSettingsPanels();
        return;
      case 'KeyC':
        event.preventDefault();event.stopPropagation();
        if($('console_toggle_btn'))$('console_toggle_btn').click();
        return;
      case 'KeyW':
        event.preventDefault();event.stopPropagation();changeConsoleHeight(1);return;
      case 'KeyS':
        event.preventDefault();event.stopPropagation();changeConsoleHeight(-1);return;
      case 'KeyA':
        event.preventDefault();event.stopPropagation();adjustSettingsPanelWidth(1);return;
      case 'KeyD':
        event.preventDefault();event.stopPropagation();adjustSettingsPanelWidth(-1);return;
      case 'KeyR':
        event.preventDefault();event.stopPropagation();
        if($('refresh_vals'))$('refresh_vals').click();
        else showToast('Configuration refresh control is unavailable.');
        return;
    }
  },true);
  document.addEventListener('keyup',syncMnemonicHints,true);
  window.addEventListener('blur',function(){
    const bar=document.querySelector('.app-menubar');if(bar)bar.classList.remove('shortcuts-visible');
  });
  document.addEventListener('visibilitychange',function(){
    if(document.hidden){const bar=document.querySelector('.app-menubar');if(bar)bar.classList.remove('shortcuts-visible');}
  });
}

function buildCommandPalette(){
  const commands=[
    ['Toggle settings panels','toggle-panels','Ctrl+Alt+P','show hide sidebar panel'],
    ['Focus settings panel navigation','focus-panels','Ctrl+Alt+Shift+P','navigate panel menus with arrows space enter'],
    ['Toggle Event Console','toggle-console','Ctrl+Alt+C / Ctrl+Backtick','open close events log console'],
    ['Increase Event Console height','console-grow','Ctrl+Alt+W','grow taller resize up'],
    ['Decrease Event Console height / close at minimum','console-shrink','Ctrl+Alt+S','shrink shorter resize down'],
    ['Widen settings panel','panel-widen','Ctrl+Alt+A','move divider left wider'],
    ['Narrow settings panel','panel-narrow','Ctrl+Alt+D','move divider right narrower'],
    ['Refresh configuration values and advanced settings','refresh-config','Ctrl+Alt+R','refresh config values feed advanced settings'],
    ['Open File menu','menu-file','Ctrl+Alt+F','file menu export import refresh capture exit'],
    ['Open Edit menu','menu-edit','Ctrl+Alt+E','edit menu properties selection'],
    ['Open View menu','menu-view','Ctrl+Alt+V','view menu zoom full screen overlay console panels'],
    ['Open Tools menu','menu-tools','Ctrl+Alt+T','tools select pan freeze live frame'],
    ['Open Help menu','menu-help','Ctrl+Alt+H','help shortcuts guide'],
    ['Select / Edit operational ROI','select','V'],['Pan camera view','pan','H'],['Toggle view lock','view-lock',''],
    ['Keyboard shortcuts','shortcuts','F1'],['Export full configuration','export','Ctrl+Shift+E','download configuration JSON'],
    ['Import full configuration','import','','load configuration JSON'],['Save workspace layout','workspace','Ctrl+S'],
    ['Undo','undo','Ctrl+Z'],['Redo','redo','Ctrl+Y / Ctrl+Shift+Z'],
    ['Fit camera frame','fit','0'],['Zoom in','zoom-in','+'],['Zoom out','zoom-out','−'],
    ['Toggle camera fullscreen','fullscreen','F'],['Toggle ROI overlays','overlays','O'],['Toggle grid','grid','G'],
    ['Toggle crosshair','crosshair','X'],['Use annotation tool','annotate','N'],['Use pixel ruler','ruler','R'],
    ['Show or hide Properties section','properties','','properties inspector'],
    ['Clear selection','clear-selection','','deselect clear current roi'],
    ['Take camera picture','take-picture','','capture still image photograph'],
    ['Exit Stream server','exit-stream','','stop server exit dashboard'],
    ['Freeze camera frame','freeze','','pause live frame'],['Return to live camera','unfreeze','','resume live frame'],
    ['Save workspace profile','profile',''],['Save configuration preset','preset',''],
    ['Capture frame snapshot','snapshot',''],['Refresh runtime diagnostics','health',''],['Refresh server logs','logs',''],
    ['Open encoder map','encoder',''],['Open camera controls','camera',''],
    ['Toggle Robot Motion (RUN_LVL)','toggle-motion','Ctrl+Shift+Space'],
    ['Force Stop (RUN_LVL → STOP)','stop',''],['Resume motion (confirmation)','resume','']
  ];
  const commandList=$('ext_command_list'),settingsList=$('ext_settings_results'),search=$('ext_command_search');
  function renderResults(){
    const query=paletteNormalize(search.value.trim());
    commandList.replaceChildren();settingsList.replaceChildren();
    const matchedCommands=commands.filter(function(entry){return !query||paletteNormalize(entry[0]+' '+entry[2]+' '+(entry[3]||'')).includes(query);});
    matchedCommands.forEach(function(entry){
      const button=document.createElement('button');button.type='button';button.className='palette-command-result';
      const badge=document.createElement('span');badge.className='palette-kind-badge command-kind';badge.textContent='COMMAND';
      const label=document.createElement('span');label.className='palette-result-label';label.textContent=entry[0];
      const shortcut=document.createElement('span');shortcut.className='palette-result-shortcut';shortcut.textContent=entry[2]||'Run';
      const active=document.createElement('span');active.className='palette-active-indicator';active.textContent=isPaletteCommandActive(entry[1])?'✓':'';active.hidden=!isPaletteCommandActive(entry[1]);active.setAttribute('aria-label',active.hidden?'':'Currently active');
      button.append(badge,label,shortcut,active);button.onclick=function(){closeCommandPalette();executeCommand(entry[1]);};commandList.appendChild(button);
    });
    $('ext_command_count').textContent=String(matchedCommands.length);
    if(!query){
      const empty=document.createElement('div');empty.className='palette-empty';empty.textContent='Type a keyword to search setting names, values, and panel options.';settingsList.appendChild(empty);
      $('ext_settings_count').textContent='Search';return;
    }
    const matchedSettings=settingSearchEntries().filter(function(entry){return entry.searchable.includes(query);});
    matchedSettings.sort(function(a,b){
      const aExact=paletteNormalize(a.label).startsWith(query)?0:1,bExact=paletteNormalize(b.label).startsWith(query)?0:1;
      return aExact-bExact||a.label.localeCompare(b.label);
    });
    matchedSettings.slice(0,60).forEach(function(entry){
      const button=document.createElement('button');button.type='button';button.className='palette-setting-result';
      const badge=document.createElement('span');badge.className='palette-kind-badge '+(entry.kind==='PANEL'?'panel-kind':entry.kind==='OPTION'?'option-kind':'setting-kind');badge.textContent=entry.kind;
      const textBox=document.createElement('span');textBox.className='palette-setting-copy';
      const label=document.createElement('span');label.className='palette-result-label';label.textContent=entry.label;
      const crumb=document.createElement('span');crumb.className='palette-setting-crumb';crumb.textContent=entry.panelTitle;
      textBox.append(label,crumb);button.append(badge,textBox);
      button.onclick=function(){navigateToPaletteSetting(entry);};settingsList.appendChild(button);
    });
    if(!matchedSettings.length){
      const empty=document.createElement('div');empty.className='palette-empty';empty.textContent='No matching settings or panel options.';settingsList.appendChild(empty);
    }
    $('ext_settings_count').textContent=String(matchedSettings.length);
  }
  search.oninput=renderResults;window.refreshStreamCommandPalette=renderResults;renderResults();
}
function openCommandPalette(){
  const modal=$('ext_command_palette');modal.style.display='flex';modal.setAttribute('aria-hidden','false');
  $('ext_command_search').value='';$('ext_command_search').focus();$('ext_command_search').dispatchEvent(new Event('input'));
}
function closeCommandPalette(){
  const modal=$('ext_command_palette');modal.style.display='none';modal.setAttribute('aria-hidden','true');
}
function executeCommand(name){
  const actions={
    'toggle-panels':toggleSettingsPanels,'focus-panels':focusPanelNavigation,
    'toggle-console':function(){if($('console_toggle_btn'))$('console_toggle_btn').click();},
    'console-grow':function(){changeConsoleHeight(1);},'console-shrink':function(){changeConsoleHeight(-1);},
    'panel-widen':function(){adjustSettingsPanelWidth(1);},'panel-narrow':function(){adjustSettingsPanelWidth(-1);},
    'refresh-config':function(){if($('refresh_vals'))$('refresh_vals').click();},
    'menu-file':function(){openTopMenu('file');},'menu-edit':function(){openTopMenu('edit');},'menu-view':function(){openTopMenu('view');},'menu-tools':function(){openTopMenu('tools');},'menu-help':function(){openTopMenu('help');},
    'zoom-in':function(){const b=document.querySelector('[data-action="zoom-in"]');if(b)b.click();},
    'zoom-out':function(){const b=document.querySelector('[data-action="zoom-out"]');if(b)b.click();},
    fullscreen:function(){const b=document.querySelector('[data-action="toggle-fullscreen"]');if(b)b.click();},
    properties:function(){const b=document.querySelector('[data-action="properties"]');if(b)b.click();},
    'clear-selection':function(){if($('clear_selection'))$('clear_selection').click();},
    'take-picture':function(){if($('take_picture_btn'))$('take_picture_btn').click();},
    'exit-stream':function(){if(window.openStreamExitDialog)window.openStreamExitDialog();else showToast('Stream exit dialog is unavailable.');},
    freeze:function(){const b=$('freeze_btn');if(b)b.click();},unfreeze:function(){const b=$('unfreeze_btn');if(b)b.click();},
    shortcuts:function(){if(window.openStreamShortcuts)window.openStreamShortcuts();},
    export:exportFullConfig,import:function(){const input=$('ext_config_file');if(input)input.click();else showToast('Full configuration import is unavailable.');},undo:doUndo,redo:doRedo,
    fit:function(){fitWorkspaceView();},overlays:function(){$('ext_overlays').click();},grid:function(){$('ext_grid').click();},crosshair:function(){$('ext_crosshair').click();},
    'view-lock':function(){if(typeof window.setWorkspaceViewLocked==='function')window.setWorkspaceViewLocked(!window.isWorkspaceViewLocked());},
    select:function(){setEditorTool('select');},pan:function(){setEditorTool(editorTool==='pan'?'select':'pan');},
    annotate:function(){setEditorTool(editorTool==='annotate'?'select':'annotate');},ruler:function(){setEditorTool(editorTool==='ruler'?'select':'ruler');},
    snapshot:addFrameSnapshot,workspace:function(){saveWorkspace().then(function(){showToast('Workspace saved');}).catch(function(e){showToast(e.message);});},
    profile:function(){$('ext_editor_panel').open=true;$('ext_profile_name').focus();},
    preset:function(){$('ext_config_panel').open=true;$('ext_preset_name').focus();},
    health:function(){refreshRuntime().then(function(){showToast('Runtime diagnostics refreshed');});},
    logs:refreshServerLogs,
    camera:function(){$('ext_camera_panel').open=true;$('ext_camera_panel').scrollIntoView({behavior:'smooth',block:'nearest'});},
    encoder:function(){if($('ext_encoder_embed').hidden)showToast('Encoder map requires --encoder-map and compatible firmware restart.');else $('ext_encoder_frame').scrollIntoView({behavior:'smooth'});},
    'toggle-motion':toggleMotionSafetyFromKeyboard,
    stop:function(){safetyAction('stop',{skipConfirm:true,source:'command-palette'}).catch(function(e){showToast(e.message);});},
    resume:function(){safetyAction('resume').catch(function(e){showToast(e.message);});}
  };
  if(actions[name])Promise.resolve(actions[name]()).catch(function(err){showToast(err.message||String(err));});
}
function enableReadOnlyState(){
  if(STREAM_CONTROL_ALLOWED)return;
  ['ext_apply_servo_center','ext_export_config','ext_import_config','ext_undo','ext_redo','ext_preset_save','ext_preset_apply','ext_preset_delete','ext_history_restore','ext_profile_save','ext_profile_delete','ext_apply_fps','ext_apply_camera','ext_sign_requests_pause','ext_sign_requests_resume','ext_software_stop','ext_software_resume','ext_save_workspace'].forEach(function(id){if($(id))$(id).disabled=true;});
}
