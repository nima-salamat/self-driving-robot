/* ---------- Overlays (Shapes & Rects) ---------- */
function drawHandle(cx,cy,size,fill,stroke){
    const z=getOverlayScale();
    ctx.beginPath();ctx.fillStyle=fill;ctx.strokeStyle=stroke||'#000';
    ctx.lineWidth=Math.max(.5,(Number(roiAppearance.outlineThickness)||2)*z*.5);
    ctx.rect(cx-size/2,cy-size/2,size,size);ctx.fill();ctx.stroke();
}

function drawPolygon(points,color,isHighlight,fillAlpha=0.35){
    const z=getOverlayScale();
    ctx.beginPath();ctx.moveTo(points[0].x,points[0].y);for(let i=1;i<points.length;i++)ctx.lineTo(points[i].x,points[i].y);ctx.closePath();
    ctx.fillStyle=color;ctx.globalAlpha=fillAlpha;ctx.fill();ctx.globalAlpha=1;
    ctx.strokeStyle=isHighlight?'#fff':color;
    ctx.lineWidth=Math.max(.5,(Number(roiAppearance.outlineThickness)||2)*z+(isHighlight?z:0));
    ctx.setLineDash(isHighlight?[6*z,4*z]:[]);ctx.stroke();ctx.setLineDash([]);
}

// Keep text outside ROI geometry, with anchor alignment chosen by ROI type.
function drawExternalLabel(labelText,color,anchorX,shapeTop,alignment='left'){
    if(!labelText)return;
    const z=getOverlayScale();
    const fs=Math.max(4,Math.min(64,(Number(roiAppearance.labelFontSize)||12)*z));
    ctx.save();
    ctx.font=String(roiAppearance.labelFontWeight||'700')+' '+fs+'px Arial,sans-serif';
    const padX=4*z,padY=2*z;
    const width=Math.ceil(ctx.measureText(labelText).width+padX*2);
    const height=Math.ceil(fs+padY*2);
    const gap=3*z;
    let x=alignment==='right'?anchorX-width:alignment==='center'?anchorX-width/2:anchorX;
    let y=shapeTop-height-gap;
    x=Math.max(1,Math.min(Math.max(1,canvas.width-width-1),x));
    y=Math.max(1,y);
    ctx.fillStyle=color;ctx.fillRect(x,y,width,height);
    ctx.fillStyle='#fff';ctx.textBaseline='top';ctx.fillText(labelText,x+padX,y+padY);
    ctx.restore();
}
function formatRoiLabel(key,shapeType){
    return roiAppearance.showShapeType ? key+' ('+shapeType+')' : key;
}
function syncOverlayControlUI(){
    const button=document.getElementById('tool_overlays_btn');
    const visible=!!showRectsCheckbox.checked;
    if(button){
        button.setAttribute('aria-pressed',String(visible));
        button.setAttribute('aria-label',visible?'Hide ROI overlays':'Show ROI overlays');
        const tip=button.querySelector('.tool-tip');
        if(tip)tip.textContent=visible?'Hide ROI Overlays · O':'Show ROI Overlays · O';
    }
    const topToggle=document.querySelector('.editor-overlay-toggle');
    if(topToggle)topToggle.setAttribute('data-overlay-state',visible?'visible':'hidden');
}
window.syncStreamOverlayControlUI=syncOverlayControlUI;
syncOverlayControlUI();

function drawOverlays(){
    const showRects = showRectsCheckbox.checked;
    const rects = computeRects();
    ctx.save();
    
    if(showRects){
        const laneMode = advanced.LANE_ROI_MODE || 'rectangle';
        const cwMode = advanced.CW_TRAPEZOID_MODE !== false; 
        const stMode = advanced.ST_TRAPEZOID_MODE !== false; 
        const objMode = advanced.OBJ_TRAPEZOID_MODE !== false;
        
        // 1. Draw BEV
        if(ui.visible['BEV'] && advanced.USE_BEV !== false) {
            const bevColor = varColorByKey('BEV');
            const isBevHL = (markerHighlight === 'BEV');
            const pts = [
                toCanvas(advanced.BEV_SRC_TL_X, advanced.BEV_SRC_TL_Y),
                toCanvas(advanced.BEV_SRC_TR_X, advanced.BEV_SRC_TR_Y),
                toCanvas(advanced.BEV_SRC_BR_X, advanced.BEV_SRC_BR_Y),
                toCanvas(advanced.BEV_SRC_BL_X, advanced.BEV_SRC_BL_Y)
            ];
            
            drawPolygon(pts, bevColor, isBevHL, 0.15); 
            
            const z=getOverlayScale();
            const topY=Math.min(pts[0].y,pts[1].y);
            drawExternalLabel('BEV Region',bevColor,(pts[0].x+pts[1].x)/2,topY,'center');
            const size=Math.max(2,(Number(roiAppearance.handleSize)||10)*z);
            for(let p of pts) drawHandle(p.x, p.y, size, '#fff', bevColor);
        }

        // Draw the selected ROI last so overlapping regions cannot cover it.
        const roiOrder=['RL','LL','CW','ST','OBJ'];
        if(roiOrder.includes(markerHighlight)){
            const selectedIndex=roiOrder.indexOf(markerHighlight);
            roiOrder.push(roiOrder.splice(selectedIndex,1)[0]);
        }
        // 2. Draw ROIs
        for(const key of roiOrder){
            if(!ui.visible[key]) continue;
            const r = rects[key];
            if(!r) continue;
            
            const color = varColorByKey(key);
            const isHL = (markerHighlight === key);
            
            let shapeType='Rectangle';
            if(key === 'RL') {
                if(laneMode === 'trapezoid'){
                    shapeType='Trapezoid';
                    let factor = advanced.RL_TOP_WIDTH_FACTOR;
                    let pts = [{x:r.x, y:r.y}, {x:r.x+(r.w*factor), y:r.y}, {x:r.x+r.w, y:r.y+r.h}, {x:r.x, y:r.y+r.h}];
                    drawPolygon(pts,color,isHL);
                } else {
                    let pts = [{x:r.x,y:r.y}, {x:r.x+r.w,y:r.y}, {x:r.x+r.w,y:r.y+r.h}, {x:r.x,y:r.y+r.h}];
                    drawPolygon(pts,color,isHL);
                }
            }
            else if(key === 'LL') {
                if(laneMode === 'trapezoid'){
                    shapeType='Trapezoid';
                    let factor = advanced.LL_TOP_WIDTH_FACTOR;
                    let pts = [{x:(r.x+r.w)-(r.w*factor), y:r.y}, {x:r.x+r.w, y:r.y}, {x:r.x+r.w, y:r.y+r.h}, {x:r.x, y:r.y+r.h}];
                    drawPolygon(pts,color,isHL);
                } else {
                    let pts = [{x:r.x,y:r.y}, {x:r.x+r.w,y:r.y}, {x:r.x+r.w,y:r.y+r.h}, {x:r.x,y:r.y+r.h}];
                    drawPolygon(pts,color,isHL);
                }
            }
            else if(key === 'CW') {
                if(cwMode){
                    shapeType='Isosceles';
                    let factor = advanced.CW_TOP_WIDTH_FACTOR;
                    let pts = [{x:r.x+(r.w*(1-factor)/2), y:r.y}, {x:r.x+(r.w*(1+factor)/2), y:r.y}, {x:r.x+r.w, y:r.y+r.h}, {x:r.x, y:r.y+r.h}];
                    drawPolygon(pts,color,isHL);
                } else {
                    let pts = [{x:r.x,y:r.y}, {x:r.x+r.w,y:r.y}, {x:r.x+r.w,y:r.y+r.h}, {x:r.x,y:r.y+r.h}];
                    drawPolygon(pts,color,isHL);
                }
            }
            else if(key === 'ST') {
                if(stMode){
                    shapeType='Isosceles';
                    let factor = advanced.ST_TOP_WIDTH_FACTOR;
                    let pts = [{x:r.x+(r.w*(1-factor)/2), y:r.y}, {x:r.x+(r.w*(1+factor)/2), y:r.y}, {x:r.x+r.w, y:r.y+r.h}, {x:r.x, y:r.y+r.h}];
                    drawPolygon(pts,color,isHL);
                } else {
                    let pts = [{x:r.x,y:r.y}, {x:r.x+r.w,y:r.y}, {x:r.x+r.w,y:r.y+r.h}, {x:r.x,y:r.y+r.h}];
                    drawPolygon(pts,color,isHL);
                }
            }
            else if(key === 'OBJ') {
                if(objMode){
                    shapeType='Isosceles';
                    let factor = advanced.OBJ_TOP_WIDTH_FACTOR;
                    let pts = [{x:r.x+(r.w*(1-factor)/2), y:r.y}, {x:r.x+(r.w*(1+factor)/2), y:r.y}, {x:r.x+r.w, y:r.y+r.h}, {x:r.x, y:r.y+r.h}];
                    drawPolygon(pts,color,isHL);
                } else {
                    let pts = [{x:r.x,y:r.y}, {x:r.x+r.w,y:r.y}, {x:r.x+r.w,y:r.y+r.h}, {x:r.x,y:r.y+r.h}];
                    drawPolygon(pts,color,isHL);
                }
            }

            const labelAlignment=key==='RL'?'right':key==='CW'?'center':'left';
            const labelX=labelAlignment==='right'?r.x+r.w:labelAlignment==='center'?r.x+r.w/2:r.x;
            drawExternalLabel(formatRoiLabel(key,shapeType),color,labelX,r.y,labelAlignment);
            const z=getOverlayScale();ctx.globalAlpha=1;
            ctx.strokeStyle=isHL?'rgba(255,255,255,.95)':'rgba(255,255,255,.24)';
            ctx.lineWidth=Math.max(.5,(Number(roiAppearance.outlineThickness)||2)*.5*z);
            ctx.setLineDash(isHL?[6*z,4*z]:[]);ctx.strokeRect(r.x,r.y,r.w,r.h);ctx.setLineDash([]);
            const size=Math.max(2,(Number(roiAppearance.handleSize)||10)*z);
            drawHandle(r.x, r.y, size, '#fff', color);
            drawHandle(r.x + r.w, r.y, size, '#fff', color);
            drawHandle(r.x, r.y + r.h, size, '#fff', color);
            drawHandle(r.x + r.w, r.y + r.h, size, '#fff', color);
        }
    }
    ctx.restore();
}

/* ---------- Hit testing & Drag Bounding Box ---------- */
function hitTest(px, py){
    if(!showRectsCheckbox.checked)return {type:'none'};
    const scale=getOverlayScale();const size = Math.max(4,(Number(roiAppearance.handleSize)||10)*scale/2+3*scale);
    
    if(ui.visible['BEV'] && advanced.USE_BEV !== false) {
        const bevCorners = {
            TL: toCanvas(advanced.BEV_SRC_TL_X, advanced.BEV_SRC_TL_Y),
            TR: toCanvas(advanced.BEV_SRC_TR_X, advanced.BEV_SRC_TR_Y),
            BR: toCanvas(advanced.BEV_SRC_BR_X, advanced.BEV_SRC_BR_Y),
            BL: toCanvas(advanced.BEV_SRC_BL_X, advanced.BEV_SRC_BL_Y)
        };
        for(const c of Object.keys(bevCorners)){
            const {x:cx, y:cy} = bevCorners[c];
            if(px >= cx-size && px <= cx+size && py >= cy-size && py <= cy+size){
                return {type:'handle', group:'BEV', corner:c};
            }
        }
    }

    const rects = computeRects();
    for(const key of ['RL','LL','CW','ST','OBJ']){
        if(!ui.visible[key]) continue;
        const r = rects[key];
        if(!r) continue;
        
        const corners = {nw:{x:r.x,y:r.y}, ne:{x:r.x+r.w,y:r.y}, sw:{x:r.x,y:r.y+r.h}, se:{x:r.x+r.w,y:r.y+r.h}};
        for(const c of Object.keys(corners)){
            const {x:cx,y:cy} = corners[c];
            if(px >= cx-size && px <= cx+size && py >= cy-size && py <= cy+size){
                return {type:'handle', group:key, corner:c, rect:r};
            }
        }
        if(px >= r.x && px <= r.x+r.w && py >= r.y && py <= r.y+r.h){
            return {type:'inside', group:key, rect:r};
        }
    }
    return {type:'none'};
}

canvas.addEventListener('auxclick',e=>{if(e.button===1)e.preventDefault();});canvas.addEventListener('contextmenu',e=>e.preventDefault());
canvas.addEventListener('wheel',e=>{e.preventDefault();const p=canvasPointFromEvent(e);setWorkspaceZoom(workspaceZoom*(e.deltaY<0?1.12:1/1.12),p.x,p.y);},{passive:false});
canvas.addEventListener('mousedown',e=>{
    if(e.button===1||(e.button===0&&workspaceTool==='pan')){e.preventDefault();if(workspaceViewLocked){showToast('View is locked. Unlock it to zoom or pan.');return;}const p=canvasPointFromEvent(e);viewPanState={startX:p.x,startY:p.y,originalX:viewPanX,originalY:viewPanY,imageScale:Math.max(0.0001,getBaseImgBounds().scale||1)};dragState=null;canvas.style.cursor='grabbing';noteWorkspaceEvent('info','Pan started (middle mouse / hand tool)');return;}
    if(e.button!==0||!syncActive||workspaceTool!=='select')return;
    const p=canvasPointFromEvent(e),px=p.x,py=p.y;
    const hit = hitTest(px, py);
    
    if(hit.group === 'BEV') {
        dragState = {type:'resize', group:'BEV', corner:hit.corner, start:{x:px,y:py}, orig: {...advanced}};
        markerHighlight = 'BEV';selectedVar='BEV_'+hit.corner;select.value=selectedVar;document.getElementById('prop_target').value=selectedVar;
        window.syncPropertiesSelection(selectedVar);
    } 
    else if(hit.type==='handle'){
        dragState = {type:'resize', group:hit.group, corner:hit.corner, origRect:hit.rect, start:{x:px,y:py}};
        markerHighlight = hit.group;
        selectedVar = hit.group;
        select.value = hit.group;
        document.getElementById('prop_target').value = hit.group;
        window.syncPropertiesSelection(hit.group);
    } 
    else if(hit.type==='inside'){
        dragState = {type:'move', group:hit.group, origRect:hit.rect, start:{x:px,y:py}};
        markerHighlight = hit.group;
        selectedVar = hit.group;
        select.value = hit.group;
        document.getElementById('prop_target').value = hit.group;
        window.syncPropertiesSelection(hit.group);
    } 
    else {
        dragState=null;markerHighlight=null;selectedVar='NONE';select.value='NONE';document.getElementById('prop_target').value='NONE';
        if(window.syncPropertiesSelection)window.syncPropertiesSelection('NONE');renderWorkspaceCanvas();
    }
});

canvas.addEventListener('mousemove',e=>{
    const p=canvasPointFromEvent(e),px=p.x,py=p.y;
    if(viewPanState){const scale=Math.max(0.0001,viewPanState.imageScale||1);viewPanX=viewPanState.originalX+(px-viewPanState.startX)/scale;viewPanY=viewPanState.originalY+(py-viewPanState.startY)/scale;canvas.style.cursor='grabbing';renderWorkspaceCanvas();return;}
    const hover = hitTest(px, py);
    
    if(dragState){
        canvas.style.cursor = dragState.type==='move' ? 'grabbing' : 'nwse-resize';
    } else if(hover.type==='handle'){
        canvas.style.cursor = 'nwse-resize';
    } else if(hover.type==='inside'){
        canvas.style.cursor = 'move';
    } else {
        canvas.style.cursor = 'default';
    }
    
    if(!dragState || !syncActive) return;
    const dx = px - dragState.start.x;
    const dy = py - dragState.start.y;
    
    const b = getImgBounds();
    const dnx = dx / b.iw; // Scale delta accurately by workspace zoom
    const dny = dy / b.ih;
    
    if(dragState.group === 'BEV'){
        const c = dragState.corner; 
        
        // Removed 0-1 restriction. Allowing bounds from -5 to 5.
        let nx = Math.max(-5.0, Math.min(5.0, dragState.orig['BEV_SRC_'+c+'_X'] + dnx));
        let ny = Math.max(-5.0, Math.min(5.0, dragState.orig['BEV_SRC_'+c+'_Y'] + dny));
        
        advanced['BEV_SRC_'+c+'_X'] = round01(nx);
        advanced['BEV_SRC_'+c+'_Y'] = round01(ny);
        
        updateShapeUIFromData(); 
        drawOverlays();
        window.syncPropertiesSelection('BEV_' + c);
        
        if(debounceTimers['BEV']) clearTimeout(debounceTimers['BEV']);
        debounceTimers['BEV'] = setTimeout(()=>{
            sendAdvanced({
                ['BEV_SRC_'+c+'_X']: advanced['BEV_SRC_'+c+'_X'],
                ['BEV_SRC_'+c+'_Y']: advanced['BEV_SRC_'+c+'_Y']
            });
        }, 220);
        return; 
    }
    
    const group = dragState.group;
    let topVar, bottomVar, leftVar, rightVar;
    if(group==='RL'){ topVar='RL_TOP_ROI'; bottomVar='RL_BOTTOM_ROI'; leftVar='RL_LEFT_ROI'; rightVar='RL_RIGHT_ROI'; }
    else if(group==='LL'){ topVar='LL_TOP_ROI'; bottomVar='LL_BOTTOM_ROI'; leftVar='LL_LEFT_ROI'; rightVar='LL_RIGHT_ROI'; }
    else if(group==='CW'){ topVar='CW_TOP_ROI'; bottomVar='CW_BOTTOM_ROI'; leftVar='CW_LEFT_ROI'; rightVar='CW_RIGHT_ROI'; }
    else if(group==='ST'){ topVar='ST_TOP_ROI'; bottomVar='ST_BOTTOM_ROI'; leftVar='ST_LEFT_ROI'; rightVar='ST_RIGHT_ROI'; }
    else { topVar='OBJ_TOP_ROI'; bottomVar='OBJ_BOTTOM_ROI'; leftVar='OBJ_LEFT_ROI'; rightVar='OBJ_RIGHT_ROI'; }
    
    const orig = dragState.origRect;
    let nx_t = orig.t, nx_b = orig.b, nx_l = orig.l, nx_r = orig.r;
    
    if(dragState.type==='move'){
        const width=orig.r-orig.l,height=orig.b-orig.t;
        nx_l=Math.max(0,Math.min(1-width,orig.l+dnx));nx_r=nx_l+width;
        nx_t=Math.max(0,Math.min(1-height,orig.t+dny));nx_b=nx_t+height;
    } else {
        if(dragState.corner==='nw'){ nx_t = clamp01(orig.t + dny); nx_l = clamp01(orig.l + dnx); }
        if(dragState.corner==='ne'){ nx_t = clamp01(orig.t + dny); nx_r = clamp01(orig.r + dnx); }
        if(dragState.corner==='sw'){ nx_b = clamp01(orig.b + dny); nx_l = clamp01(orig.l + dnx); }
        if(dragState.corner==='se'){ nx_b = clamp01(orig.b + dny); nx_r = clamp01(orig.r + dnx); }
        if(nx_b <= nx_t) nx_b = nx_t + 0.01;
        if(nx_r <= nx_l) nx_r = nx_l + 0.01;
    }
    if(isEditorSnapEnabled()){
        const stepX=getGridStepX(),stepY=Math.max(.025,Math.min(.25,Number(gridSpacing)||.05));
        if(dragState.type==='move'){
            const w=nx_r-nx_l,h=nx_b-nx_t;nx_l=Math.max(0,Math.min(1-w,snapNormalized(nx_l,stepX)));nx_t=Math.max(0,Math.min(1-h,snapNormalized(nx_t,stepY)));nx_r=nx_l+w;nx_b=nx_t+h;
        }else{
            if(dragState.corner==='nw'||dragState.corner==='sw')nx_l=clamp01(snapNormalized(nx_l,stepX));
            if(dragState.corner==='ne'||dragState.corner==='se')nx_r=clamp01(snapNormalized(nx_r,stepX));
            if(dragState.corner==='nw'||dragState.corner==='ne')nx_t=clamp01(snapNormalized(nx_t,stepY));
            if(dragState.corner==='sw'||dragState.corner==='se')nx_b=clamp01(snapNormalized(nx_b,stepY));
            if(nx_r-nx_l<.01){if(dragState.corner==='nw'||dragState.corner==='sw')nx_l=Math.max(0,nx_r-.01);else nx_r=Math.min(1,nx_l+.01);}
            if(nx_b-nx_t<.01){if(dragState.corner==='nw'||dragState.corner==='ne')nx_t=Math.max(0,nx_b-.01);else nx_b=Math.min(1,nx_t+.01);}
        }
    }
    values[topVar] = round01(nx_t); values[bottomVar] = round01(nx_b);
    values[leftVar] = round01(nx_l); values[rightVar] = round01(nx_r);
    updateInputsFromValues(); 
    drawOverlays();
    window.syncPropertiesSelection(group);
    
    if(debounceTimers[group]) clearTimeout(debounceTimers[group]);
    debounceTimers[group] = setTimeout(()=>{
        sendUpdate({[topVar]:values[topVar], [bottomVar]:values[bottomVar], [leftVar]:values[leftVar], [rightVar]:values[rightVar]});
    }, 220);
});

window.addEventListener('mouseup',()=>{
    if(viewPanState){viewPanState=null;canvas.style.cursor=workspaceTool==='pan'?'grab':'default';noteWorkspaceEvent('info','Pan finished');return;}
    if(!dragState || !syncActive) {
        dragState = null;
        canvas.style.cursor = 'default';
        return;
    }
    
    if(dragState.group === 'BEV') {
        const c = dragState.corner;
        sendAdvanced({
            ['BEV_SRC_'+c+'_X']: advanced['BEV_SRC_'+c+'_X'],
            ['BEV_SRC_'+c+'_Y']: advanced['BEV_SRC_'+c+'_Y']
        });
    } else {
        const group = dragState.group;
        let topVar, bottomVar, leftVar, rightVar;
        if(group==='RL'){ topVar='RL_TOP_ROI'; bottomVar='RL_BOTTOM_ROI'; leftVar='RL_LEFT_ROI'; rightVar='RL_RIGHT_ROI'; }
        else if(group==='LL'){ topVar='LL_TOP_ROI'; bottomVar='LL_BOTTOM_ROI'; leftVar='LL_LEFT_ROI'; rightVar='LL_RIGHT_ROI'; }
        else if(group==='CW'){ topVar='CW_TOP_ROI'; bottomVar='CW_BOTTOM_ROI'; leftVar='CW_LEFT_ROI'; rightVar='CW_RIGHT_ROI'; }
        else if(group==='ST'){ topVar='ST_TOP_ROI'; bottomVar='ST_BOTTOM_ROI'; leftVar='ST_LEFT_ROI'; rightVar='ST_RIGHT_ROI'; }
        else { topVar='OBJ_TOP_ROI'; bottomVar='OBJ_BOTTOM_ROI'; leftVar='OBJ_LEFT_ROI'; rightVar='OBJ_RIGHT_ROI'; }
        sendUpdate({[topVar]:values[topVar], [bottomVar]:values[bottomVar], [leftVar]:values[leftVar], [rightVar]:values[rightVar]});
    }
    
    dragState = null;
    canvas.style.cursor = 'default';
});

