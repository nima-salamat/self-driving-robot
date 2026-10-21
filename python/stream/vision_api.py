"""Safe Stream endpoints for vision tuning, stage previews and diagnostic export."""
import base64
import importlib
import io
import json
import logging
import math
import re
import sys as _sys
import time
import zipfile
from types import SimpleNamespace

import cv2
import numpy as np
from flask import jsonify, request, send_file

_stream_module = _sys.modules[__package__]
logger = logging.getLogger(__name__)

COMMON_DEFAULTS = {
    "LANE_THRESHOLD": 180, "HOUGH_THRESHOLD": 15, "HOUGH_MIN_LINE_LENGTH": 5,
    "HOUGH_MAX_LINE_GAP": 20, "HOUGH_BLUR_KERNEL": 3, "HOUGH_MORPH_CLOSE": True,
    "SIGN_AREA_FILTER_ENABLED": True, "SIGN_AREA_FILTER_TARGETS": ["STOP"], "SIGN_AREA_MIN_PX2": 900,
}
BLSF_DEFAULTS = {
    "BLSF_RANDOM_SEED": (42, 0, 1000000, int),
    "BLSF_MIN_SEGMENT_LENGTH": (17.0, 1.0, 500.0, float),
    "BLSF_ANGLE_LIMIT_DEG": (35.0, 1.0, 89.0, float),
    "BLSF_STRAIGHT_BAND_DEG": (5.0, 0.0, 30.0, float),
    "BLSF_MIN_ANGLE_VOTE": (20.0, 0.0, 100000.0, float),
    "BLSF_MEDIAN_KERNEL": (9, 3, 31, int),
    "BLSF_LOCAL_THRESHOLD": (15, 0, 255, int),
    "BLSF_NUM_WINDOWS": (9, 3, 40, int),
    "BLSF_WINDOW_WIDTH_FACTOR": (0.40, 0.05, 1.0, float),
    "BLSF_RANSAC_ITERATIONS": (80, 1, 1000, int),
    "BLSF_RANSAC_INLIER_THRESHOLD": (6.0, 0.1, 100.0, float),
    "BLSF_MIN_FIT_POINTS": (12, 3, 10000, int),
    "BLSF_DEFAULT_LANE_WIDTH": (0.40, 0.05, 1.0, float),
    "BLSF_FALLBACK_HALF_LANE_WIDTH": (0.20, 0.05, 0.5, float),
    "BLSF_STEERING_KP": (0.45, 0.0, 5.0, float),
    "BLSF_STEERING_SMOOTHING": (0.70, 0.0, 1.0, float),
    "BLSF_NO_LANE_STEERING": (150, 0, 180, int),
}
INTEGER_RANGES = {
    "LANE_THRESHOLD": (0, 255), "HOUGH_THRESHOLD": (1, 255),
    "HOUGH_MIN_LINE_LENGTH": (1, 500), "HOUGH_MAX_LINE_GAP": (0, 100),
    "HOUGH_BLUR_KERNEL": (1, 15),
}
RESTART_ONLY = {"CITY_LANE_DETECTOR", "USE_ML_LANE_DETECTOR"}


class StreamVisionMixin:
    def _vision_mode_module(self):
        name = "modes.city.config_city" if self._mode_slug() == "city" else "modes.race.config_race"
        try:
            return importlib.import_module(name)
        except Exception:
            return self.config

    def _vision_setting_names(self):
        names = list(COMMON_DEFAULTS)
        return names + (["CITY_LANE_DETECTOR"] + list(BLSF_DEFAULTS) if self._mode_slug() == "city" else ["USE_ML_LANE_DETECTOR"])

    def _vision_tuning_snapshot(self):
        module, result = self._vision_mode_module(), {}
        for name, default in COMMON_DEFAULTS.items():
            value = getattr(module, name, getattr(self.config, name, default))
            if name in {"HOUGH_MORPH_CLOSE", "SIGN_AREA_FILTER_ENABLED"}:
                result[name] = bool(value)
            elif name == "SIGN_AREA_FILTER_TARGETS":
                result[name] = list(value) if isinstance(value, (list, tuple)) else list(default)
            else:
                try:
                    number = float(value)
                    result[name] = int(number) if number.is_integer() else number
                except (TypeError, ValueError):
                    result[name] = default
        if self._mode_slug() == "city":
            name = getattr(module, "CITY_LANE_DETECTOR", getattr(self.config, "CITY_LANE_DETECTOR", "default"))
            result["CITY_LANE_DETECTOR"] = name if name in {"default", "blsf-beta"} else "default"
            for name, spec in BLSF_DEFAULTS.items():
                try:
                    number = float(getattr(module, name, getattr(self.config, name, spec[0])))
                    result[name] = int(number) if spec[3] is int else number
                except (TypeError, ValueError):
                    result[name] = spec[0]
        else:
            result["USE_ML_LANE_DETECTOR"] = bool(getattr(module, "USE_ML_LANE_DETECTOR", getattr(self.config, "USE_ML_LANE_DETECTOR", False)))
        return result

    def _normalize_vision_settings(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("vision settings must be a JSON object")
        unknown = sorted(set(payload) - set(self._vision_setting_names()))
        if unknown:
            raise ValueError("unknown vision setting(s): " + ", ".join(unknown))
        clean = {}
        for name, value in payload.items():
            if name in INTEGER_RANGES:
                if isinstance(value, bool):
                    raise ValueError(name + " must be an integer")
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    raise ValueError(name + " must be an integer") from None
                low, high = INTEGER_RANGES[name]
                if not math.isfinite(number) or not number.is_integer() or not low <= number <= high:
                    raise ValueError(f"{name} must be an integer between {low} and {high}")
                if name == "HOUGH_BLUR_KERNEL" and number != 1 and number % 2 == 0:
                    raise ValueError("HOUGH_BLUR_KERNEL must be 1 or an odd integer")
                clean[name] = int(number)
            elif name in {"HOUGH_MORPH_CLOSE", "SIGN_AREA_FILTER_ENABLED", "USE_ML_LANE_DETECTOR"}:
                if not isinstance(value, bool):
                    raise ValueError(name + " must be boolean")
                clean[name] = value
            elif name == "SIGN_AREA_FILTER_TARGETS":
                from traffic_sign_detector.area_filter import validate_sign_area_filter
                validate_sign_area_filter(name, value)
                clean[name] = list(value)
            elif name == "SIGN_AREA_MIN_PX2":
                if isinstance(value, bool):
                    raise ValueError(name + " must be numeric")
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    raise ValueError(name + " must be numeric") from None
                if not math.isfinite(number) or not 0 <= number <= 10000000:
                    raise ValueError(name + " must be between 0 and 10000000 px²")
                clean[name] = int(number) if number.is_integer() else number
            elif name == "CITY_LANE_DETECTOR":
                if self._mode_slug() != "city" or value not in {"default", "blsf-beta"}:
                    raise ValueError("City lane detector must be default or blsf-beta")
                clean[name] = value
            elif name in BLSF_DEFAULTS:
                default, low, high, converter = BLSF_DEFAULTS[name]
                if isinstance(value, bool):
                    raise ValueError(name + " must be numeric")
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    raise ValueError(name + " must be numeric") from None
                if not math.isfinite(number) or not low <= number <= high:
                    raise ValueError(f"{name} must be between {low} and {high}")
                if converter is int and not number.is_integer():
                    raise ValueError(name + " must be an integer")
                if name == "BLSF_MEDIAN_KERNEL" and (int(number) < 3 or int(number) % 2 == 0):
                    raise ValueError("BLSF_MEDIAN_KERNEL must be an odd integer of at least 3")
                clean[name] = converter(number)
        return clean

    def _apply_vision_settings(self, settings, persist=True):
        clean = self._normalize_vision_settings(settings)
        if str(getattr(self.config, "RUN_LVL", "MOVE")).upper() != "STOP":
            raise ValueError("Set RUN_LVL=STOP before applying perception settings.")
        module, filename = self._vision_mode_module(), self.config_filename()
        old = {key: getattr(module, key, getattr(self.config, key, None)) for key in clean}
        previous_file = None
        try:
            if persist:
                with open(filename, "r", encoding="utf-8") as handle:
                    previous_file = json.load(handle)
                if not isinstance(previous_file, dict):
                    raise ValueError("mode configuration must be a JSON object")
            for key, value in clean.items():
                setattr(module, key, value)
                if module is not self.config:
                    try:
                        setattr(self.config, key, value)
                    except Exception:
                        pass
            if persist:
                updated = dict(previous_file)
                updated.update(clean)
                self._write_json_atomic(filename, updated)
        except Exception:
            for key, value in old.items():
                try:
                    setattr(module, key, value)
                    setattr(self.config, key, value)
                except Exception:
                    logger.exception("Could not roll back vision setting %s", key)
            raise
        current = self._vision_tuning_snapshot()
        active = current.get("CITY_LANE_DETECTOR", "default") if self._mode_slug() == "city" else ("ml" if current.get("USE_ML_LANE_DETECTOR") else "default")
        changed = [key for key, value in clean.items() if old.get(key) != value]
        restart = [key for key in changed if key in RESTART_ONLY]
        if active == "blsf-beta":
            restart.extend(key for key in changed if key in BLSF_DEFAULTS)
        return {
            "settings": current, "changed": changed, "restart_required": sorted(set(restart)),
            "live_hough_settings": active == "default" and any(key in changed for key in ("LANE_THRESHOLD","HOUGH_THRESHOLD","HOUGH_MIN_LINE_LENGTH","HOUGH_MAX_LINE_GAP","HOUGH_BLUR_KERNEL","HOUGH_MORPH_CLOSE")),
            "run_level": str(getattr(self.config, "RUN_LVL", "UNKNOWN")),
        }

    def vision_tuning_api(self):
        if request.method == "GET":
            mode = self._mode_slug()
            return jsonify(mode=mode, settings=self._vision_tuning_snapshot(), controls_enabled=self._control_allowed(),
                run_level=str(getattr(self.config, "RUN_LVL", "UNKNOWN")),
                lane_detector_options=["default","blsf-beta"] if mode == "city" else ["default","ml"],
                setting_semantics={"BLSF":"BLSF caches constructor parameters; process restart required when active.",
                    "detector":"Detector selection is saved for startup; active motion pipeline is never hot-swapped.",
                    "HOUGH":"Classical Hough reads these settings while processing frames."})
        if not self._control_allowed():
            return self._control_denied()
        body = request.get_json(silent=True) or {}
        try:
            return jsonify(success=True, **self._apply_vision_settings(body.get("settings", body), persist=True))
        except (TypeError, ValueError) as exc:
            return jsonify(success=False, message=str(exc)), (409 if "RUN_LVL=STOP" in str(exc) else 400)
        except Exception:
            logger.exception("Failed to apply Stream vision settings")
            return jsonify(success=False, message="vision settings could not be persisted"), 500

    @staticmethod
    def _data_url_bytes(value, limit=6*1024*1024):
        if not isinstance(value, str) or len(value) > limit*2:
            raise ValueError("image payload is missing or too large")
        match = re.fullmatch(r"data:image/(?:jpeg|png);base64,([A-Za-z0-9+/=]+)", value)
        if not match:
            raise ValueError("image must be a JPEG or PNG data URL")
        try:
            decoded = base64.b64decode(match.group(1), validate=True)
        except (ValueError, base64.binascii.Error):
            raise ValueError("image payload is invalid") from None
        if not decoded or len(decoded) > limit:
            raise ValueError("image payload is empty or too large")
        return decoded

    @staticmethod
    def _stage_data_url(image, max_width=900):
        if image is None:
            return None
        if len(image.shape) == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        if image.shape[1] > max_width:
            scale = max_width / float(image.shape[1])
            image = cv2.resize(image, (max_width, max(1,int(round(image.shape[0]*scale))),), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY,72])
        return "data:image/jpeg;base64,"+base64.b64encode(encoded.tobytes()).decode("ascii") if ok else None

    def vision_preview_api(self):
        body = request.get_json(silent=True) or {}
        try:
            raw = cv2.imdecode(np.frombuffer(self._data_url_bytes(body.get("image")),dtype=np.uint8),cv2.IMREAD_COLOR)
            if raw is None or raw.size == 0:
                raise ValueError("frame could not be decoded")
            if raw.shape[1] > 1280:
                scale=1280.0/raw.shape[1]
                raw=cv2.resize(raw,(1280,max(1,int(round(raw.shape[0]*scale)))),interpolation=cv2.INTER_AREA)
            module=self._vision_mode_module()
            settings=self._vision_tuning_snapshot()
            if body.get("settings"):
                settings.update(self._normalize_vision_settings(body["settings"]))
            cfg=SimpleNamespace(**{**{k:v for k,v in vars(module).items() if k.isidentifier()},**settings})
            detector_name=settings.get("CITY_LANE_DETECTOR","default") if self._mode_slug()=="city" else ("ml" if settings.get("USE_ML_LANE_DETECTOR") else "default")
            stages={"input":raw}
            summary={"mode":self._mode_slug(),"pipeline":detector_name,"frame_width":int(raw.shape[1]),"frame_height":int(raw.shape[0]),"motion_commands_sent":False}
            if detector_name=="blsf-beta" and self._mode_slug()=="city":
                from vision.blsf_lane.detector import BLSFLaneDetector
                detector=BLSFLaneDetector(cfg)
                bev=detector._bev(raw.copy());weighted=detector._weighted_gray(bev)
                thresholded=detector._median_local_threshold(weighted);segments=detector._segments(thresholded)
                band,votes=detector._blsf_band(segments);binary=detector._blsf_binary(thresholded,segments,band)
                ls,rs,hist=detector._seeds(binary)
                lane_width=max(1.0,float(rs-ls)) if ls is not None and rs is not None else raw.shape[1]*float(settings.get("BLSF_DEFAULT_LANE_WIDTH",.4))
                ww=float(settings.get("BLSF_WINDOW_WIDTH_FACTOR",.4))*lane_width
                left_model=detector._ransac_parabola(detector._track(binary,ls,ww))
                right_model=detector._ransac_parabola(detector._track(binary,rs,ww))
                candidates=bev.copy();filtered=np.zeros_like(bev)
                for x1,y1,x2,y2,_length,angle in segments:
                    cv2.line(candidates,(int(x1),int(y1)),(int(x2),int(y2)),(60,220,90),1,cv2.LINE_AA)
                    if band is not None and band[0]<=angle<=band[1]:
                        cv2.line(filtered,(int(x1),int(y1)),(int(x2),int(y2)),(255,150,30),1,cv2.LINE_AA)
                selected=bev.copy();fit_count=0
                for model,color in ((left_model,(255,100,30)),(right_model,(30,180,255))):
                    if model is None: continue
                    fit_count+=1;points=[]
                    for y in range(0,bev.shape[0],4):
                        x=int(round(float(np.polyval(model,y))))
                        if 0<=x<bev.shape[1]:points.append((x,y))
                    for start,end in zip(points,points[1:]):cv2.line(selected,start,end,color,3,cv2.LINE_AA)
                stages.update({"bev":bev,"weighted_gray":weighted,"local_threshold":thresholded,"binary":binary,"candidates":candidates,"angle_filtered_segments":filtered,"selected_lane_fits":selected})
                summary.update({"candidate_segments":len(segments),"selected_angle_band":band,"angle_votes":[round(float(v),2) for v in votes],
                    "left_fit":left_model is not None,"right_fit":right_model is not None,"selected_lane_boundaries":fit_count,
                    "no_lane_reason":"No segments survived angle/length filters." if not segments else "No angle band met its vote threshold." if band is None else "No curve fit met RANSAC requirements." if not fit_count else None,
                    "preview_note":"BLSF stages run on this submitted frame only; no control function is called."})
            else:
                working=raw.copy()
                if bool(getattr(cfg,"USE_BEV",False)):
                    h,w=working.shape[:2]
                    src=np.float32([[w*float(getattr(cfg,"BEV_SRC_TL_X",.35)),h*float(getattr(cfg,"BEV_SRC_TL_Y",.6))],[w*float(getattr(cfg,"BEV_SRC_TR_X",.65)),h*float(getattr(cfg,"BEV_SRC_TR_Y",.6))],[w*float(getattr(cfg,"BEV_SRC_BR_X",1)),h*float(getattr(cfg,"BEV_SRC_BR_Y",1))],[w*float(getattr(cfg,"BEV_SRC_BL_X",0)),h*float(getattr(cfg,"BEV_SRC_BL_Y",1))]])
                    working=cv2.warpPerspective(working,cv2.getPerspectiveTransform(src,np.float32([[0,0],[w,0],[w,h],[0,h]])),(w,h))
                stages["bev"]=working
                height,width=working.shape[:2]
                candidates=working.copy();edge_views={};counts={};selected_side={}
                legacy=bool(getattr(cfg,"OLD_METHOD",False))
                threshold=int(settings.get("LANE_THRESHOLD",180));blur=int(settings.get("HOUGH_BLUR_KERNEL",3))
                votes=int(settings.get("HOUGH_THRESHOLD",15));min_len=int(settings.get("HOUGH_MIN_LINE_LENGTH",5))
                max_gap=int(settings.get("HOUGH_MAX_LINE_GAP",20));morph=bool(settings.get("HOUGH_MORPH_CLOSE",True))
                for side,tk,bk,lk,rk in (("left","LL_TOP_ROI","LL_BOTTOM_ROI","LL_LEFT_ROI","LL_RIGHT_ROI"),("right","RL_TOP_ROI","RL_BOTTOM_ROI","RL_LEFT_ROI","RL_RIGHT_ROI")):
                    top=max(0,min(height-1,int(float(getattr(cfg,tk,.4))*height)));bottom=max(top+1,min(height,int(float(getattr(cfg,bk,1))*height)))
                    left=max(0,min(width-1,int(float(getattr(cfg,lk,0))*width)));right=max(left+1,min(width,int(float(getattr(cfg,rk,1))*width)))
                    roi=working[top:bottom,left:right].copy();gray=cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY)
                    if legacy:
                        _,processed=cv2.threshold(gray,threshold,255,cv2.THRESH_BINARY);edges=cv2.Canny(processed,100,150)
                    else:
                        if blur>1:
                            blur=blur if blur%2 else blur+1
                            gray=cv2.GaussianBlur(gray,(blur,blur),0)
                        gx=cv2.Sobel(gray,cv2.CV_32F,1,0,ksize=3);gy=cv2.Sobel(gray,cv2.CV_32F,0,1,ksize=3)
                        magnitude=cv2.convertScaleAbs(cv2.magnitude(gx,gy));_,edges=cv2.threshold(magnitude,threshold,255,cv2.THRESH_BINARY)
                        if morph:edges=cv2.morphologyEx(edges,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8),iterations=1)
                    if str(getattr(cfg,"LANE_ROI_MODE","rectangle"))=="trapezoid":
                        rh,rw=edges.shape[:2];factor=float(getattr(cfg,"LL_TOP_WIDTH_FACTOR" if side=="left" else "RL_TOP_WIDTH_FACTOR",.5))
                        poly=np.array([[rw-int(rw*factor),0],[rw,0],[rw,rh],[0,rh]],np.int32) if side=="left" else np.array([[0,0],[int(rw*factor),0],[rw,rh],[0,rh]],np.int32)
                        mask=np.zeros_like(edges);cv2.fillPoly(mask,[poly],255);edges=cv2.bitwise_and(edges,edges,mask=mask)
                    lines=cv2.HoughLinesP(edges,1,np.pi/180,threshold=votes,minLineLength=max(1,min_len),maxLineGap=max(0,max_gap))
                    rows=[] if lines is None else [np.asarray(line).reshape(-1,4)[0] for line in lines]
                    counts[side]=len(rows);edge_views["left_edges" if side=="left" else "right_edges"]=edges
                    best=None;best_score=-1.0
                    for line in rows:
                        x1,y1,x2,y2=map(float,line);length=math.hypot(x2-x1,y2-y1)
                        xmid=(x1+x2)/2;ymid=(y1+y2)/2;angle=abs(math.degrees(math.atan((y2-y1)/(x2-x1+1e-9))))
                        diagonal=max(1,math.hypot(roi.shape[1],roi.shape[0]))
                        score=.25*min(length/diagonal,1)+.45*max(0,min(1,(1-xmid/max(1,roi.shape[1])) if side=="right" else xmid/max(1,roi.shape[1])))+.1*min(ymid/max(1,roi.shape[0]),1)+.2*math.exp(-((angle-90)**2)/(2*25**2))
                        cv2.line(candidates,(left+int(x1),top+int(y1)),(left+int(x2),top+int(y2)),(65,225,100),1,cv2.LINE_AA)
                        if score>best_score:best_score,best=score,line
                    if best is not None:
                        x1,y1,x2,y2=map(int,best);color=(255,100,30) if side=="left" else (30,165,255)
                        cv2.line(candidates,(left+x1,top+y1),(left+x2,top+y2),color,3,cv2.LINE_AA);selected_side[side]=True
                    else:selected_side[side]=False
                stages.update(edge_views);stages["candidates"]=candidates
                summary.update({"candidate_count_left":counts.get("left",0),"candidate_count_right":counts.get("right",0),
                    "selected_candidate_left":selected_side.get("left",False),"selected_candidate_right":selected_side.get("right",False),
                    "no_lane_reason":"No Hough segments passed the active preprocessing/ROI settings." if not any(counts.values()) else None,
                    "preview_note":"Green = Hough candidates; blue/amber = top-scoring candidate per ROI; preview only."})
                if detector_name=="ml":summary["preview_note"]="Reference Hough diagnostics only; the Race ML runtime is not invoked here."
            return jsonify(success=True,stages={name:self._stage_data_url(img) for name,img in stages.items() if img is not None},summary=summary)
        except (TypeError,ValueError) as exc:
            return jsonify(success=False,message=str(exc)),400
        except Exception:
            logger.exception("Vision preview failed")
            return jsonify(success=False,message="could not analyze this frame"),500

    def diagnostic_bundle_api(self):
        body=request.get_json(silent=True) or {}
        try:
            timestamp=time.time()
            snapshot={"created_at":timestamp,"mode":self._mode_slug(),"run_level":str(getattr(self.config,"RUN_LVL","UNKNOWN")),
                "config":self._full_config_snapshot(),"vision":self._vision_tuning_snapshot()}
            try:
                health=self.health()
                snapshot["health"]=health.get_json(silent=True) if hasattr(health,"get_json") else None
            except Exception:snapshot["health"]={"available":False}
            workspace=self._read_json_file(self._state_filename("workspace"),{"workspace":{},"profiles":{}})
            snapshot["workspace"]=workspace.get("workspace",{});snapshot["workspace_profiles"]=sorted((workspace.get("profiles") or {}).keys())
            snapshot["recent_logs"]=[{"timestamp":v.get("timestamp"),"level":v.get("level"),"logger":v.get("logger"),"message":_stream_module._redact_log_message(v.get("message",""))} for v in list(_stream_module._STREAM_LOGS)[-200:]]
            out=io.BytesIO()
            with zipfile.ZipFile(out,"w",compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("diagnostic.json",json.dumps(snapshot,ensure_ascii=False,indent=2,default=str))
                if body.get("frame"):archive.writestr("current_frame.jpg",self._data_url_bytes(body["frame"],limit=3*1024*1024))
                stages=body.get("stages",{})
                if isinstance(stages,dict):
                    for name,value in list(stages.items())[:12]:
                        if not re.fullmatch(r"[a-z0-9_-]{1,48}",str(name)):continue
                        try:archive.writestr("vision_stages/"+name+".jpg",self._data_url_bytes(value,limit=2*1024*1024))
                        except ValueError:pass
            out.seek(0)
            return send_file(out,mimetype="application/zip",as_attachment=True,download_name=f"stream-diagnostics-{self._mode_slug()}-{int(timestamp)}.zip")
        except Exception:
            logger.exception("Could not create Stream diagnostic bundle")
            return jsonify(success=False,message="diagnostic bundle creation failed"),500


def register_vision_routes(app,streamer):
    app.add_url_rule("/api/vision/tuning","vision_tuning_api",streamer.vision_tuning_api,methods=["GET","POST"])
    app.add_url_rule("/api/vision/preview","vision_preview_api",streamer.vision_preview_api,methods=["POST"])
    app.add_url_rule("/api/diagnostics/bundle","diagnostic_bundle_api",streamer.diagnostic_bundle_api,methods=["POST"])
