(function(){
'use strict';
const $=id=>document.getElementById(id),nativeFetch=window.fetch.bind(window);
const mode=String(window.STREAM_BOOTSTRAP&&window.STREAM_BOOTSTRAP.mode||'city').toLowerCase();
const writable=!!(window.STREAM_BOOTSTRAP&&window.STREAM_BOOTSTRAP.streamControl);
const hough=[['LANE_THRESHOLD','wb_lane_threshold'],['HOUGH_THRESHOLD','wb_hough_threshold'],['HOUGH_MIN_LINE_LENGTH','wb_hough_min_len'],['HOUGH_MAX_LINE_GAP','wb_hough_gap'],['HOUGH_BLUR_KERNEL','wb_hough_blur']];
const blsf=[['BLSF_RANDOM_SEED','wb_blsf_seed'],['BLSF_MIN_SEGMENT_LENGTH','wb_blsf_min_segment'],['BLSF_ANGLE_LIMIT_DEG','wb_blsf_angle'],['BLSF_STRAIGHT_BAND_DEG','wb_blsf_straight'],['BLSF_MIN_ANGLE_VOTE','wb_blsf_vote'],['BLSF_MEDIAN_KERNEL','wb_blsf_median'],['BLSF_LOCAL_THRESHOLD','wb_blsf_local'],['BLSF_NUM_WINDOWS','wb_blsf_windows'],['BLSF_WINDOW_WIDTH_FACTOR','wb_blsf_width'],['BLSF_RANSAC_ITERATIONS','wb_blsf_iterations'],['BLSF_RANSAC_INLIER_THRESHOLD','wb_blsf_ransac'],['BLSF_MIN_FIT_POINTS','wb_blsf_fit_points'],['BLSF_DEFAULT_LANE_WIDTH','wb_blsf_lane_width'],['BLSF_FALLBACK_HALF_LANE_WIDTH','wb_blsf_half_width'],['BLSF_STEERING_KP','wb_blsf_kp'],['BLSF_STEERING_SMOOTHING','wb_blsf_smoothing'],['BLSF_NO_LANE_STEERING','wb_blsf_no_lane']];
let previewImages={};
async function api(url,options){const r=await nativeFetch(url,Object.assign({cache:'no-store'},options||{})),j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.message||j.reason||('HTTP '+r.status));return j;}
function msg(id,value,error){const node=$(id);if(node){node.textContent=value;node.dataset.tone=error?'error':'normal';}}
function fill(fields,data){fields.forEach(([key,id])=>{if($(id)&&data[key]!=null)$(id).value=String(data[key]);});}
async function refreshVision(){
 try{
  const d=await api('/api/vision/tuning'),s=d.settings||{};fill(hough,s);if(mode==='city')fill(blsf,s);
  $('wb_hough_morph').checked=!!s.HOUGH_MORPH_CLOSE;$('wb_sign_area_enabled').checked=!!s.SIGN_AREA_FILTER_ENABLED;
  $('wb_sign_min_area').value=String(s.SIGN_AREA_MIN_PX2);$('wb_sign_targets').value=(s.SIGN_AREA_FILTER_TARGETS||['STOP']).join(', ');
  $('wb_detector').value=mode==='city'?(s.CITY_LANE_DETECTOR||'default'):(s.USE_ML_LANE_DETECTOR?'ml':'default');
  $('wb_blsf_fields').hidden=mode!=='city'||$('wb_detector').value!=='blsf-beta';
  $('wb_detector_help').textContent=mode==='city'?'Detector selection and BLSF constructor settings require restart.':'Race ML selection is startup-only; the live pipeline is not swapped by Stream.';
  msg('wb_vision_status','Mode '+d.mode+' · RUN_LVL='+d.run_level+(d.controls_enabled?' · controls enabled':' · read-only'));
 }catch(e){msg('wb_vision_status','Vision settings failed: '+e.message,true);}
}
function readVision(){
 const s={};hough.forEach(([k,id])=>s[k]=Number($(id).value));
 s.HOUGH_MORPH_CLOSE=$('wb_hough_morph').checked;s.SIGN_AREA_FILTER_ENABLED=$('wb_sign_area_enabled').checked;
 s.SIGN_AREA_MIN_PX2=Number($('wb_sign_min_area').value);s.SIGN_AREA_FILTER_TARGETS=$('wb_sign_targets').value.split(',').map(v=>v.trim()).filter(Boolean);
 if(mode==='city'){blsf.forEach(([k,id])=>s[k]=Number($(id).value));s.CITY_LANE_DETECTOR=$('wb_detector').value;}
 else s.USE_ML_LANE_DETECTOR=$('wb_detector').value==='ml';
 return s;
}
async function applyVision(){
 if(!writable)throw new Error('Stream is read-only.');
 const settings=readVision();Object.keys(settings).forEach(k=>{if(typeof settings[k]==='number'&&!Number.isFinite(settings[k]))throw new Error(k+' must be finite.');});
 const d=await api('/api/vision/tuning',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({settings})});
 const restart=d.restart_required||[],message=restart.length?'Saved. Restart required for: '+restart.join(', ')+'.':(d.live_hough_settings?'Saved; classical Hough reads these values during processing.':'Saved; no running detector was hot-swapped.');
 msg('wb_vision_status',message);if(typeof window.showToast==='function')window.showToast(message);
}
function frameUrl(){
 if(typeof lastFrameImage==='undefined'||!lastFrameImage||!lastFrameImage.complete||!lastFrameImage.naturalWidth)throw new Error('No decoded camera frame is available.');
 const scale=Math.min(1,1280/lastFrameImage.naturalWidth),c=document.createElement('canvas');c.width=Math.max(1,Math.round(lastFrameImage.naturalWidth*scale));c.height=Math.max(1,Math.round(lastFrameImage.naturalHeight*scale));
 c.getContext('2d').drawImage(lastFrameImage,0,0,c.width,c.height);return c.toDataURL('image/jpeg',.84);
}
async function preview(){
 $('wb_preview_btn').disabled=true;msg('wb_preview_status','Analyzing one submitted frame. No motor commands are sent.');
 try{
  const d=await api('/api/vision/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image:frameUrl(),settings:readVision()})});
  previewImages=d.stages||{};const root=$('wb_stage_gallery');root.replaceChildren();
  const labels={input:'Input frame',bev:'BEV / working frame',weighted_gray:'Weighted grayscale',local_threshold:'Local threshold',binary:'Binary lane mask',left_edges:'Left ROI edge map',right_edges:'Right ROI edge map',candidates:'Hough candidates + top line',angle_filtered_segments:'BLSF angle-filtered segments',selected_lane_fits:'Selected BLSF fits'};
  Object.keys(previewImages).forEach(key=>{const card=document.createElement('div');card.className='wb-stage-card';const title=document.createElement('strong');title.textContent=labels[key]||key.replace(/_/g,' ');card.appendChild(title);const img=document.createElement('img');img.alt=title.textContent;img.loading='lazy';img.src=previewImages[key];card.appendChild(img);const btn=document.createElement('button');btn.type='button';btn.className='ghost';btn.textContent='Open image';btn.onclick=()=>window.open(previewImages[key],'_blank','noopener');card.appendChild(btn);root.appendChild(card);});
  msg('wb_preview_summary',JSON.stringify(d.summary,null,2));msg('wb_preview_status','Preview complete. Diagnostics correspond to this submitted frame, not a nonstop live detector stream.');
 }catch(e){msg('wb_preview_status','Preview failed: '+e.message,true);}
 finally{$('wb_preview_btn').disabled=false;}
}
async function refreshProfiles(){
 try{
  const d=await api('/api/profiles'),sel=$('wb_profile_select');sel.replaceChildren();
  if(!(d.profiles||[]).length){const o=document.createElement('option');o.value='';o.textContent='No complete profiles';sel.appendChild(o);}
  (d.profiles||[]).forEach(p=>{const o=document.createElement('option');o.value=p.name;o.textContent=p.name+' · '+new Date(p.saved_at*1000).toLocaleString();sel.appendChild(o);});
  if(d.active_profile)sel.value=d.active_profile;msg('wb_profile_status',(d.profiles||[]).length+' profile(s) · active: '+(d.active_profile||'none'));
 }catch(e){msg('wb_profile_status','Profile list failed: '+e.message,true);}
}
const profileName=()=>(String($('wb_profile_name').value||$('wb_profile_select').value||'').trim());
async function saveProfile(){
 if(!writable)throw new Error('Stream is read-only.');const name=profileName();if(!name)throw new Error('Enter a profile name.');
 const workspace=typeof window.collectStreamWorkspace==='function'?window.collectStreamWorkspace():{};
 await api('/api/profiles',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'save',name,workspace})});
 $('wb_profile_name').value=name;await refreshProfiles();msg('wb_profile_status','Saved "'+name+'": mode config + vision tuning + workspace and annotations.');
}
async function loadProfile(){
 if(!writable)throw new Error('Stream is read-only.');const name=$('wb_profile_select').value||$('wb_profile_name').value.trim();if(!name)throw new Error('Choose a profile.');
 if(!window.confirm('Load "'+name+'"? RUN_LVL must be STOP. Motion will not resume automatically.'))return;
 const d=await api('/api/profiles',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'load',name})});
 if(typeof window.applyStreamWorkspace==='function')window.applyStreamWorkspace(d.workspace||{});
 await refreshVision();await refreshProfiles();msg('wb_profile_status','Loaded "'+name+'". Robot motion remains stopped.');
 if(typeof window.showToast==='function')window.showToast('Profile loaded; motion remains STOP.');
}
async function deleteProfile(){
 if(!writable)throw new Error('Stream is read-only.');const name=$('wb_profile_select').value||$('wb_profile_name').value.trim();if(!name)throw new Error('Choose a profile.');
 if(!window.confirm('Delete profile "'+name+'"?'))return;
 await api('/api/profiles',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'delete',name})});await refreshProfiles();msg('wb_profile_status','Deleted "'+name+'".');
}
async function exportProfile(){
 const name=$('wb_profile_select').value;if(!name)throw new Error('Choose a profile.');const d=await api('/api/profiles?name='+encodeURIComponent(name));
 const blob=new Blob([JSON.stringify(d.profile,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='stream-profile-'+name.replace(/[^A-Za-z0-9_.-]+/g,'_')+'.json';document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url);
}
async function importProfile(file){
 if(!writable)throw new Error('Stream is read-only.');const profile=JSON.parse(await file.text()),suggested=String(profile.name||file.name.replace(/\.json$/i,'')).slice(0,48);
 const name=window.prompt('Name for imported profile:',suggested);if(!name)return;
 await api('/api/profiles',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'import',name,profile})});await refreshProfiles();$('wb_profile_select').value=name;msg('wb_profile_status','Imported "'+name+'". Load is a separate STOP-gated action.');
}
async function diagnostics(){
 $('wb_diagnostics_btn').disabled=true;msg('wb_diagnostics_status','Collecting config, health, logs, current frame and preview stages…');
 try{
  let frame=null;try{frame=frameUrl();}catch(_){}
  const r=await nativeFetch('/api/diagnostics/bundle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({frame,stages:previewImages})});
  if(!r.ok){const d=await r.json().catch(()=>({}));throw new Error(d.message||('HTTP '+r.status));}
  const blob=await r.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='stream-diagnostics.zip';document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url);
  msg('wb_diagnostics_status','ZIP exported. Inspect it before sharing; it may contain a camera frame and config metadata.');
 }catch(e){msg('wb_diagnostics_status','Export failed: '+e.message,true);}
 finally{$('wb_diagnostics_btn').disabled=!writable;}
}
function cursor(e){
 const c=$('video_canvas'),r=c.getBoundingClientRect();if(!r.width||!r.height)return;
 const x=(e.clientX-r.left)*c.width/r.width,y=(e.clientY-r.top)*c.height/r.height;let b=null;
 try{if(typeof getImgBounds==='function')b=getImgBounds();}catch(_){}
 const inside=!!b&&x>=b.ix&&x<=b.ix+b.iw&&y>=b.iy&&y<=b.iy+b.ih;
 if(inside){const u=(x-b.ix)/b.iw,v=(y-b.iy)/b.ih,w=Number(frameSourceWidth)||c.width,h=Number(frameSourceHeight)||c.height;
  $('cad_cursor_x').textContent='X: '+Math.round(u*w)+' px';$('cad_cursor_y').textContent='Y: '+Math.round(v*h)+' px';
  $('cad_cursor_u').textContent='U: '+(u*100).toFixed(2)+'%';$('cad_cursor_v').textContent='V: '+(v*100).toFixed(2)+'%';$('cad_cursor_z').textContent='Z: — (no camera depth data)';
 }else{$('cad_cursor_x').textContent='Canvas X: '+Math.round(x)+' px';$('cad_cursor_y').textContent='Canvas Y: '+Math.round(y)+' px';$('cad_cursor_u').textContent='U: n/a outside frame';$('cad_cursor_v').textContent='V: n/a outside frame';$('cad_cursor_z').textContent='Z: 0 (editor plane only)';}
}
function bind(id,fn,target){if($(id))$(id).addEventListener('click',()=>Promise.resolve().then(fn).catch(e=>msg(target||'wb_diagnostics_status',e.message,true)));}
document.addEventListener('DOMContentLoaded',function(){
 if($('wb_detector'))$('wb_detector').addEventListener('change',()=>$('wb_blsf_fields').hidden=mode!=='city'||$('wb_detector').value!=='blsf-beta');
 bind('wb_vision_apply',applyVision,'wb_vision_status');bind('wb_preview_btn',preview,'wb_preview_status');
 bind('wb_profile_save',saveProfile,'wb_profile_status');bind('wb_profile_load',loadProfile,'wb_profile_status');bind('wb_profile_delete',deleteProfile,'wb_profile_status');bind('wb_profile_export',exportProfile,'wb_profile_status');
 bind('wb_profile_import',()=>$('wb_profile_file').click(),'wb_profile_status');
 if($('wb_profile_file'))$('wb_profile_file').addEventListener('change',function(){const f=this.files&&this.files[0];if(f)importProfile(f).catch(e=>msg('wb_profile_status',e.message,true));this.value='';});
 bind('wb_diagnostics_btn',diagnostics,'wb_diagnostics_status');
 if(!writable)['wb_vision_apply','wb_profile_save','wb_profile_load','wb_profile_delete','wb_profile_import'].forEach(id=>{if($(id))$(id).disabled=true;});
 const c=$('video_canvas');if(c){c.addEventListener('pointermove',cursor);c.addEventListener('pointerleave',()=>{[['cad_cursor_x','X: —'],['cad_cursor_y','Y: —'],['cad_cursor_u','U: —'],['cad_cursor_v','V: —'],['cad_cursor_z','Z: —']].forEach(([id,value])=>{if($(id))$(id).textContent=value;});});}
 refreshVision();refreshProfiles();
});
})();