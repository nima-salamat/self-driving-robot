/* ---------- Advanced & BEV Settings logic ---------- */
const shapeInputs = {
    lane_mode: document.getElementById('lane_roi_mode'),
    rl_factor: document.getElementById('rl_factor'),
    ll_factor: document.getElementById('ll_factor'),
    cw_trap_mode: document.getElementById('cw_trap_mode'),
    cw_factor: document.getElementById('cw_factor'),
    st_trap_mode: document.getElementById('st_trap_mode'),
    st_factor: document.getElementById('st_factor'),
    obj_trap_mode: document.getElementById('obj_trap_mode'),
    obj_factor: document.getElementById('obj_factor'),
    rl_val: document.getElementById('rl_factor_val'),
    ll_val: document.getElementById('ll_factor_val'),
    cw_val: document.getElementById('cw_factor_val'),
    st_val: document.getElementById('st_factor_val'),
    obj_val: document.getElementById('obj_factor_val'),
    use_bev: document.getElementById('use_bev_toggle'),
    bev_tl_x: document.getElementById('BEV_SRC_TL_X'),
    bev_tl_y: document.getElementById('BEV_SRC_TL_Y'),
    bev_tr_x: document.getElementById('BEV_SRC_TR_X'),
    bev_tr_y: document.getElementById('BEV_SRC_TR_Y'),
    bev_br_x: document.getElementById('BEV_SRC_BR_X'),
    bev_br_y: document.getElementById('BEV_SRC_BR_Y'),
    bev_bl_x: document.getElementById('BEV_SRC_BL_X'),
    bev_bl_y: document.getElementById('BEV_SRC_BL_Y')
};

function updateShapeUIFromData() {
    shapeInputs.lane_mode.value = advanced.LANE_ROI_MODE || 'rectangle';
    shapeInputs.rl_factor.value = advanced.RL_TOP_WIDTH_FACTOR;
    shapeInputs.ll_factor.value = advanced.LL_TOP_WIDTH_FACTOR;
    shapeInputs.cw_trap_mode.checked = advanced.CW_TRAPEZOID_MODE;
    shapeInputs.cw_factor.value = advanced.CW_TOP_WIDTH_FACTOR;
    shapeInputs.st_trap_mode.checked = advanced.ST_TRAPEZOID_MODE;
    shapeInputs.st_factor.value = advanced.ST_TOP_WIDTH_FACTOR;
    shapeInputs.obj_trap_mode.checked = advanced.OBJ_TRAPEZOID_MODE;
    shapeInputs.obj_factor.value = advanced.OBJ_TOP_WIDTH_FACTOR;
    
    shapeInputs.rl_val.textContent = parseFloat(advanced.RL_TOP_WIDTH_FACTOR).toFixed(2);
    shapeInputs.ll_val.textContent = parseFloat(advanced.LL_TOP_WIDTH_FACTOR).toFixed(2);
    shapeInputs.cw_val.textContent = parseFloat(advanced.CW_TOP_WIDTH_FACTOR).toFixed(2);
    shapeInputs.st_val.textContent = parseFloat(advanced.ST_TOP_WIDTH_FACTOR).toFixed(2);
    shapeInputs.obj_val.textContent = parseFloat(advanced.OBJ_TOP_WIDTH_FACTOR).toFixed(2);
    
    shapeInputs.use_bev.checked = advanced.USE_BEV;
    shapeInputs.bev_tl_x.value = advanced.BEV_SRC_TL_X.toFixed(3);
    shapeInputs.bev_tl_y.value = advanced.BEV_SRC_TL_Y.toFixed(3);
    shapeInputs.bev_tr_x.value = advanced.BEV_SRC_TR_X.toFixed(3);
    shapeInputs.bev_tr_y.value = advanced.BEV_SRC_TR_Y.toFixed(3);
    shapeInputs.bev_br_x.value = advanced.BEV_SRC_BR_X.toFixed(3);
    shapeInputs.bev_br_y.value = advanced.BEV_SRC_BR_Y.toFixed(3);
    shapeInputs.bev_bl_x.value = advanced.BEV_SRC_BL_X.toFixed(3);
    shapeInputs.bev_bl_y.value = advanced.BEV_SRC_BL_Y.toFixed(3);

    drawOverlays();
}

function handleShapeSlider() {
    advanced.LANE_ROI_MODE = shapeInputs.lane_mode.value;
    advanced.RL_TOP_WIDTH_FACTOR = parseFloat(shapeInputs.rl_factor.value);
    advanced.LL_TOP_WIDTH_FACTOR = parseFloat(shapeInputs.ll_factor.value);
    advanced.CW_TRAPEZOID_MODE = shapeInputs.cw_trap_mode.checked;
    advanced.CW_TOP_WIDTH_FACTOR = parseFloat(shapeInputs.cw_factor.value);
    advanced.ST_TRAPEZOID_MODE = shapeInputs.st_trap_mode.checked;
    advanced.ST_TOP_WIDTH_FACTOR = parseFloat(shapeInputs.st_factor.value);
    advanced.OBJ_TRAPEZOID_MODE = shapeInputs.obj_trap_mode.checked;
    advanced.OBJ_TOP_WIDTH_FACTOR = parseFloat(shapeInputs.obj_factor.value);
    
    shapeInputs.rl_val.textContent = advanced.RL_TOP_WIDTH_FACTOR.toFixed(2);
    shapeInputs.ll_val.textContent = advanced.LL_TOP_WIDTH_FACTOR.toFixed(2);
    shapeInputs.cw_val.textContent = advanced.CW_TOP_WIDTH_FACTOR.toFixed(2);
    shapeInputs.st_val.textContent = advanced.ST_TOP_WIDTH_FACTOR.toFixed(2);
    shapeInputs.obj_val.textContent = advanced.OBJ_TOP_WIDTH_FACTOR.toFixed(2);
    drawOverlays();
}

['input', 'change'].forEach(evt => {
    shapeInputs.lane_mode.addEventListener(evt, handleShapeSlider);
    shapeInputs.rl_factor.addEventListener(evt, handleShapeSlider);
    shapeInputs.ll_factor.addEventListener(evt, handleShapeSlider);
    shapeInputs.cw_trap_mode.addEventListener(evt, handleShapeSlider);
    shapeInputs.cw_factor.addEventListener(evt, handleShapeSlider);
    shapeInputs.st_trap_mode.addEventListener(evt, handleShapeSlider);
    shapeInputs.st_factor.addEventListener(evt, handleShapeSlider);
    shapeInputs.obj_trap_mode.addEventListener(evt, handleShapeSlider);
    shapeInputs.obj_factor.addEventListener(evt, handleShapeSlider);
});

shapeInputs.use_bev.addEventListener('change', (e) => {
    sendAdvanced({ USE_BEV: e.target.checked });
});

document.getElementById('confirm_bev_inputs').addEventListener('click', () => {
    sendAdvanced({
        BEV_SRC_TL_X: parseFloat(shapeInputs.bev_tl_x.value) || 0,
        BEV_SRC_TL_Y: parseFloat(shapeInputs.bev_tl_y.value) || 0,
        BEV_SRC_TR_X: parseFloat(shapeInputs.bev_tr_x.value) || 0,
        BEV_SRC_TR_Y: parseFloat(shapeInputs.bev_tr_y.value) || 0,
        BEV_SRC_BR_X: parseFloat(shapeInputs.bev_br_x.value) || 0,
        BEV_SRC_BR_Y: parseFloat(shapeInputs.bev_br_y.value) || 0,
        BEV_SRC_BL_X: parseFloat(shapeInputs.bev_bl_x.value) || 0,
        BEV_SRC_BL_Y: parseFloat(shapeInputs.bev_bl_y.value) || 0
    });
});

document.getElementById('confirm_shape').addEventListener('click', ()=>{
    sendAdvanced({
        LANE_ROI_MODE: advanced.LANE_ROI_MODE,
        RL_TOP_WIDTH_FACTOR: advanced.RL_TOP_WIDTH_FACTOR,
        LL_TOP_WIDTH_FACTOR: advanced.LL_TOP_WIDTH_FACTOR,
        CW_TRAPEZOID_MODE: advanced.CW_TRAPEZOID_MODE,
        CW_TOP_WIDTH_FACTOR: advanced.CW_TOP_WIDTH_FACTOR,
        ST_TRAPEZOID_MODE: advanced.ST_TRAPEZOID_MODE,
        ST_TOP_WIDTH_FACTOR: advanced.ST_TOP_WIDTH_FACTOR,
        OBJ_TRAPEZOID_MODE: advanced.OBJ_TRAPEZOID_MODE,
        OBJ_TOP_WIDTH_FACTOR: advanced.OBJ_TOP_WIDTH_FACTOR
    });
});

/* ---------- Manual Box inputs ---------- */
function updateInputsFromValues(){
    inputsContainer.querySelectorAll('input').forEach(input=>{
        const name = input.name;
        if(values[name]!==undefined && !roiDirtyFields.has(name) && document.activeElement!==input) input.value = round01(values[name]).toFixed(2);
    });
}
document.querySelectorAll('.btn-inc').forEach(btn=>{
    btn.addEventListener('click', ()=>{
        if(!syncActive) return showToast('Requests are stopped!');
        const v = btn.dataset.var;
        const d = parseFloat(btn.dataset.delta);
        const input = inputsContainer.querySelector(`input[name="${v}"]`);
        let val = parseFloat(input.value)||0;
        val = clamp01(round01(val + d));
        input.value = val.toFixed(2);
        debounceSendSingle(v, val);
    });
});
function debounceSendSingle(name, val){
    if(debounceTimers[name]) clearTimeout(debounceTimers[name]);
    debounceTimers[name] = setTimeout(()=>{ sendUpdate({[name]:val}); }, 250);
}
inputsContainer.querySelectorAll('input').forEach(input=>{
    input.addEventListener('input', e=>{
        if(!syncActive) return;
        const name = e.target.name;
        let v = parseFloat(e.target.value);
        if(isNaN(v)) return;
        roiDirtyFields.add(name);
        roiEditVersions[name] = (roiEditVersions[name] || 0) + 1;
        v = clamp01(round01(v));
        values[name]=v;
        debounceSendSingle(name, v);
        drawOverlays();
    });
});
function sendUpdate(data){
    if(!syncActive) return;
    const editVersions = Object.create(null);
    Object.keys(data).forEach(name => { editVersions[name] = roiEditVersions[name] || 0; });
    recordApiEvent('info','Saving ROI/config fields: '+Object.keys(data).join(', '));
    fetch('/update_conf',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})
        .then(async r => {
            const result = await r.json().catch(() => ({}));
            if(!r.ok) throw new Error(result.message || 'HTTP ' + r.status);
            return result;
        })
        .then(j=>{
            if(j && j.values){
                Object.keys(data).forEach(name => {
                    if((roiEditVersions[name] || 0) === editVersions[name]) roiDirtyFields.delete(name);
                });
                values = j.values;
                updateInputsFromValues(); drawOverlays();
                if(window.syncPropertiesSelection)window.syncPropertiesSelection(document.getElementById('prop_target').value);
                showToast('Base Updated');
            } else {
                showToast((j && j.message) || 'Could not update base settings');
            }
        })
        .catch(err => {
            recordApiEvent('error', 'Failed to update base settings: ' + err.message);
            console.error('Failed to update base settings:', err);
            showToast('Settings update failed: ' + err.message);
        });
}

/* ---------- Stream API Actions ---------- */
document.getElementById('refresh_vals').addEventListener('click', ()=>{
    if(!syncActive) return showToast('Requests are stopped!');
    fetchDashboardJson('/get_values').then(j=>{ if(j && j.values){ values=j.values; updateInputsFromValues(); drawOverlays(); }});
    loadAdvanced();
});
document.getElementById('clear_selection').addEventListener('click',()=>{select.value='NONE';selectedVar='NONE';markerHighlight=null;document.getElementById('prop_target').value='NONE';if(window.syncPropertiesSelection)window.syncPropertiesSelection('NONE');renderWorkspaceCanvas();});

/* ---------- Pause Dashboard Requests Logic (robot RUN_LVL is unchanged) ---------- */
const stopAllBtn = document.getElementById('stop_all_btn');
stopAllBtn.addEventListener('click', () => {
    syncActive = !syncActive;
    if(!syncActive) {
        stopAllBtn.textContent = 'Resume Dashboard Requests';
        stopAllBtn.style.background = '#22c55e'; // Green when resuming
        clearInterval(fetchFrameTimer);
        fetchFrameTimer = null;
        clearInterval(valUpdateTimer);
        valUpdateTimer = null;
        clearInterval(healthUpdateTimer);
        healthUpdateTimer = null;
        clearInterval(arduinoUpdateTimer);
        arduinoUpdateTimer = null;
        if(typeof window.setStreamExtensionPollingEnabled==='function')window.setStreamExtensionPollingEnabled(false);
        updateFrameModeText();
        showToast('Dashboard polling paused; robot motion is unchanged');
    } else {
        stopAllBtn.textContent = 'Pause Dashboard Requests';
        stopAllBtn.style.background = '#ef4444'; // Red for pause
        if(typeof window.setStreamExtensionPollingEnabled==='function')window.setStreamExtensionPollingEnabled(true);
        startFrameLoop();
        if(!valUpdateTimer) valUpdateTimer = setInterval(fetchValuesLoop, 8000);
        if(!healthUpdateTimer) healthUpdateTimer = setInterval(updateHealth, 2000);
        if(!arduinoUpdateTimer) arduinoUpdateTimer = setInterval(updateArduinoOutput, 3000);
        fetchValuesLoop();
        updateHealth();
        updateArduinoOutput();
        updateFrameModeText();
        showToast('Dashboard polling resumed; robot run state is unchanged');
    }
});

/* ---------- Advanced API Sync ---------- */
const advInputs = {
    lane_threshold: document.getElementById('lane_threshold'),
    cross_thresh: document.getElementById('cross_thresh'),
    cross_sleep: document.getElementById('crosswalk_sleep'),
    cross_thresh_spend: document.getElementById('crosswalk_thresh_spend'),
    read_sign_thresh: document.getElementById('read_sign_threshold'),
    turn_right: document.getElementById('turn_right'),
    turn_left: document.getElementById('turn_left'),
    straight: document.getElementById('straight'),
    stop_lvl: document.getElementById('stop_lvl'),
    with_sign: document.getElementById('with_sign'),
    with_apriltag: document.getElementById('with_apriltag')
};

function loadAdvanced(){
    if(!syncActive) return;
    fetchDashboardJson('/get_advanced').then(j=>{
        if(j && j.advanced){
            advanced = j.advanced;
            advInputs.lane_threshold.value = advanced.LANE_THRESHOLD;
            advInputs.cross_thresh.value = advanced.CROSSWALK_THRESHOLD;
            advInputs.cross_sleep.value = advanced.CROSSWALK_SLEEP;
            advInputs.cross_thresh_spend.value = advanced.CROSSWALK_THRESH_SPEND;
            advInputs.read_sign_thresh.value = advanced.READ_SIGN_THRESHOLD;
            advInputs.turn_right.value = advanced.TURN_RIGHT;
            advInputs.turn_left.value = advanced.TURN_LEFT;
            advInputs.straight.value = advanced.STRAIGHT;
            advInputs.stop_lvl.value = advanced.STOP;
            advInputs.with_sign.checked = advanced.WITH_SIGN;
            advInputs.with_apriltag.checked = advanced.WITH_APRILTAG;
            updateShapeUIFromData();
        }
    });
}

document.getElementById('confirm_advanced').addEventListener('click', ()=>{
    sendAdvanced({
        LANE_THRESHOLD: parseInt(advInputs.lane_threshold.value)||0,
        CROSSWALK_THRESHOLD: parseInt(advInputs.cross_thresh.value)||0,
        CROSSWALK_SLEEP: parseFloat(advInputs.cross_sleep.value)||0,
        CROSSWALK_THRESH_SPEND: parseFloat(advInputs.cross_thresh_spend.value)||0,
        READ_SIGN_THRESHOLD: parseInt(advInputs.read_sign_thresh.value)||0,
        TURN_RIGHT: parseInt(advInputs.turn_right.value)||0,
        TURN_LEFT: parseInt(advInputs.turn_left.value)||0,
        STRAIGHT: parseInt(advInputs.straight.value)||0,
        STOP: parseInt(advInputs.stop_lvl.value)||0,
        WITH_SIGN: advInputs.with_sign.checked,
        WITH_APRILTAG: advInputs.with_apriltag.checked
    });
});

/* ---------- Color & Vis Listeners ---------- */
['vis_rl','vis_ll','vis_cw','vis_st','vis_obj','vis_ml','vis_mr','vis_bev'].forEach(id => {
    document.getElementById(id).addEventListener('change', (e) => {
        let key = id.replace('vis_', '').toUpperCase();
        ui.visible[key] = e.target.checked;
        if(syncActive) {
            fetch('/set_ui',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({visible: ui.visible})});
        }
        drawOverlays();
    });
});
['color_rl','color_ll','color_cw','color_st','color_obj','color_ml','color_mr','color_bev'].forEach(id => {
    document.getElementById(id).addEventListener('change', (e) => {
        let key = id.replace('color_', '').toUpperCase();
        ui.colors[key] = e.target.value;
        if(syncActive) {
            fetch('/set_ui',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({colors: ui.colors})});
        }
        drawOverlays();
    });
});

/* ---------- Buttons setup ---------- */
document.getElementById('freeze_btn').addEventListener('click', ()=> {
    if(!syncActive) return showToast('Requests are stopped!');
    fetch('/freeze_frame', {method:'POST'}).then(()=> {isFrozen=true; updateFrameModeText(); updateZoomStatus(); showToast('Frame frozen'); noteWorkspaceEvent('info','Camera frame frozen');})
});
document.getElementById('unfreeze_btn').addEventListener('click', ()=> {
    if(!syncActive) return showToast('Requests are stopped!');
    fetch('/unfreeze_frame', {method:'POST'}).then(()=> {isFrozen=false; updateFrameModeText(); updateZoomStatus(); showToast('Back to live'); noteWorkspaceEvent('info','Live camera resumed');})
});

document.getElementById('take_picture_btn').addEventListener('click', () => {
    if(!syncActive) return showToast('Requests are stopped!');
    fetch('/take_picture', {method: 'POST'}).then(r => r.json()).then(j => { if (j && j.success) showToast('Picture Taken!'); });
});

document.getElementById('toggle_record_btn').addEventListener('click', () => {
    if(!syncActive) return showToast('Requests are stopped!');
    fetch('/toggle_record', {method: 'POST'}).then(r => r.json()).then(j => {
        if (j && j.success) {
            isRecording = j.recording;
            const statusDiv = document.getElementById('record_status');
            const btn = document.getElementById('toggle_record_btn');
            statusDiv.textContent = 'Recording: ' + (isRecording ? 'Yes' : 'No');
            statusDiv.style.color = isRecording ? '#ef4444' : 'var(--accent)';
            btn.textContent = isRecording ? 'Stop Recording' : 'Start Recording';
            showToast(isRecording ? 'Recording Started' : 'Recording Stopped');
            noteWorkspaceEvent('info',isRecording?'Video recording started':'Video recording stopped');
        }
    });
});

