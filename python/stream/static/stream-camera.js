/* ---------- Canvas frame loop ---------- */
function rectFromVars(topVar, bottomVar, leftVar, rightVar){
    const t = parseFloat(values[topVar]); const b = parseFloat(values[bottomVar]);
    const l = parseFloat(values[leftVar]); const r = parseFloat(values[rightVar]);
    if (isNaN(t)||isNaN(b)||isNaN(l)||isNaN(r)) return null;
    
    // Calculate physical canvas points using zoom
    const tl = toCanvas(l, t);
    const br = toCanvas(r, b);
    
    return {
        x: tl.x, y: tl.y, 
        w: Math.max(2, br.x - tl.x), h: Math.max(2, br.y - tl.y), 
        t, b, l, r
    };
}

function computeRects(){
    return {
        RL: rectFromVars('RL_TOP_ROI','RL_BOTTOM_ROI','RL_LEFT_ROI','RL_RIGHT_ROI'),
        LL: rectFromVars('LL_TOP_ROI','LL_BOTTOM_ROI','LL_LEFT_ROI','LL_RIGHT_ROI'),
        CW: rectFromVars('CW_TOP_ROI','CW_BOTTOM_ROI','CW_LEFT_ROI','CW_RIGHT_ROI'),
        ST: rectFromVars('ST_TOP_ROI','ST_BOTTOM_ROI','ST_LEFT_ROI','ST_RIGHT_ROI'),
        OBJ: rectFromVars('OBJ_TOP_ROI','OBJ_BOTTOM_ROI','OBJ_LEFT_ROI','OBJ_RIGHT_ROI')
    };
}

function getStreamDisplayFps(){return streamDisplayFps;}
function setStreamDisplayFps(value){
    const fps=Number(value);
    if(!Number.isFinite(fps)||fps<1||fps>30)throw new RangeError('Stream display FPS must be between 1 and 30.');
    streamDisplayFps=Math.round(fps*10)/10;
    if(fetchFrameTimer){
        clearInterval(fetchFrameTimer);
        fetchFrameTimer=setInterval(fetchFrameOnce,Math.max(33,Math.round(1000/streamDisplayFps)));
    }
    return streamDisplayFps;
}
window.getStreamDisplayFps=getStreamDisplayFps;
window.setStreamDisplayFps=setStreamDisplayFps;
function startFrameLoop(){
    if(fetchFrameTimer) clearInterval(fetchFrameTimer);
    fetchFrameTimer = setInterval(fetchFrameOnce, Math.max(33,Math.round(1000/streamDisplayFps)));
    fetchFrameOnce();
}

let frameRequestInFlight = false;
let hasRenderedFrame = false;
let frameRequestFailures = 0;
let frameRetryAt = 0;

function showCameraConnectionState(message){
    if(hasRenderedFrame) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.save();
    ctx.fillStyle = '#94a3b8';
    ctx.font = '16px Segoe UI, Arial, sans-serif';
    ctx.textBaseline = 'top';
    ctx.fillText(message, 16, 16);
    ctx.restore();
    drawOverlays();
}

const FRAME_REQUEST_TIMEOUT_MS = 8000;
function fetchFrameOnce(){
    // Camera refresh is independent from configuration/health API availability.
    if(!syncActive || frameRequestInFlight) return;
    if(Date.now() < frameRetryAt) return;

    frameRequestInFlight = true;
    let objectUrl = null;
    let img = null;
    let timeoutHandle = null;
    let completed = false;
    const controller = typeof AbortController === 'function' ? new AbortController() : null;

    const finishFrameRequest = (error) => {
        if(completed) return;
        completed = true;
        if(timeoutHandle !== null) clearTimeout(timeoutHandle);
        if(img) {
            img.onload = null;
            img.onerror = null;
        }
        if(objectUrl) {
            URL.revokeObjectURL(objectUrl);
            objectUrl = null;
        }
        frameRequestInFlight = false;

        if(error) {
            frameRequestFailures += 1;
            frameRetryAt = Date.now() + Math.min(5000, 250 * Math.pow(2, Math.min(frameRequestFailures - 1, 5)));
            const detail = error && error.message ? error.message : 'Unknown frame request error';
            if(!hasRenderedFrame) {
                showCameraConnectionState(
                    frameRequestFailures > 3
                        ? 'Waiting for camera frames... ' + detail
                        : 'Connecting to camera... ' + detail
                );
            }
            if(frameRequestFailures === 1 || frameRequestFailures === 4) {
                noteWorkspaceEvent('warn', 'Camera frame refresh failed; retrying: ' + detail);
            }
            return;
        }

        const recovered = frameRequestFailures > 0;
        frameRequestFailures = 0;
        frameRetryAt = 0;
        if(recovered) noteWorkspaceEvent('info', 'Camera frame updates recovered');
    };

    timeoutHandle = setTimeout(() => {
        if(controller) controller.abort();
        finishFrameRequest(new Error(
            'Camera frame request timed out after ' + (FRAME_REQUEST_TIMEOUT_MS / 1000) + ' seconds.'
        ));
    }, FRAME_REQUEST_TIMEOUT_MS);

    const requestOptions = {cache:'no-store',headers:{'Accept':'image/jpeg'}};
    if(controller) requestOptions.signal = controller.signal;

    fetch('/video_feed_frame?t=' + Date.now(), requestOptions).then(response => {
        if(completed) return null;
        if(response.status === 204) throw new Error('The Stream server has not published a frame yet (HTTP 204).');
        if(!response.ok) throw new Error('Camera frame endpoint returned HTTP ' + response.status + '.');
        const contentType = String(response.headers.get('content-type') || '').toLowerCase();
        if(contentType && !contentType.startsWith('image/')) {
            throw new Error('Camera frame endpoint returned ' + contentType + ', not an image.');
        }
        return response.blob();
    }).then(blob => {
        if(completed || blob === null) return;
        if(!blob || blob.size === 0) throw new Error('Camera frame response was empty.');

        objectUrl = URL.createObjectURL(blob);
        img = new Image();
        img.decoding = 'async';
        img.onload = () => {
            if(completed) return;
            try {
                if(syncActive) {
                    const frameWidth = img.naturalWidth || img.width;
                    const frameHeight = img.naturalHeight || img.height;
                    if(frameWidth <= 0 || frameHeight <= 0) throw new Error('Decoded camera frame has invalid dimensions.');
                    frameSourceWidth = frameWidth;
                    frameSourceHeight = frameHeight;
                    lastFrameImage = img;
                    syncCameraCanvasSize();
                    const rect = canvas.getBoundingClientRect();
                    if(rect.width <= 0 || rect.height <= 0) throw new Error('Camera canvas has no visible size.');
                    renderWorkspaceCanvas();
                    hasRenderedFrame = true;
                }
                finishFrameRequest();
            } catch(error) {
                console.error('Failed to render camera frame:', error);
                finishFrameRequest(new Error(
                    'Camera frame received, but display failed: ' +
                    (error && error.message ? error.message : String(error))
                ));
            }
        };
        img.onerror = () => finishFrameRequest(new Error('The response could not be decoded as an image.'));
        img.src = objectUrl;
    }).catch(error => finishFrameRequest(error));
}

// Force an immediate retry after browser timer throttling or network recovery.
document.addEventListener('visibilitychange', () => {
    if(!document.hidden) {
        frameRetryAt = 0;
        fetchFrameOnce();
    }
});
window.addEventListener('online', () => {
    frameRetryAt = 0;
    fetchFrameOnce();
});

