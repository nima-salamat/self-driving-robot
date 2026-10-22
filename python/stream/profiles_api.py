"""Unified Stream profiles containing mode config, vision settings and workspace layout."""
import logging
import re
import time
from flask import jsonify,request

logger=logging.getLogger(__name__)


class StreamProfilesMixin:
    def _profiles_file(self):
        return self._state_filename("profiles")

    @staticmethod
    def _valid_profile_name(name):
        return isinstance(name,str) and 1<=len(name.strip())<=48 and re.fullmatch(r"[A-Za-z0-9 _.-]+",name.strip()) is not None

    def _profiles_store(self):
        data=self._read_json_file(self._profiles_file(),{"version":1,"profiles":{},"active_profile":None})
        if not isinstance(data.get("profiles"),dict):data["profiles"]={}
        return data

    @staticmethod
    def _profile_summaries(profiles):
        return [{"name":name,"mode":item.get("mode"),"saved_at":item.get("saved_at"),"description":item.get("description","")} for name,item in sorted(profiles.items())]

    def profiles_api(self):
        data=self._profiles_store();profiles=data["profiles"]
        if request.method=="GET":
            name=str(request.args.get("name","")).strip()
            if name:
                profile=profiles.get(name)
                if profile is None:return jsonify(success=False,message="profile not found"),404
                return jsonify(success=True,profile=profile)
            return jsonify(version=1,mode=self._mode_slug(),active_profile=data.get("active_profile"),profiles=self._profile_summaries(profiles))
        if not self._control_allowed():return self._control_denied()
        body=request.get_json(silent=True) or {};action=str(body.get("action","")).strip().lower();name=str(body.get("name","")).strip()
        if action in {"save","delete","load","import","export"} and not self._valid_profile_name(name):
            return jsonify(success=False,message="profile name must be 1-48 safe characters"),400
        try:
            if action=="save":
                workspace=body.get("workspace")
                if workspace is None:
                    saved=self._read_json_file(self._state_filename("workspace"),self._workspace_default())
                    workspace=saved.get("workspace",{})
                profile={"schema_version":1,"name":name,"mode":self._mode_slug(),"saved_at":time.time(),
                    "description":str(body.get("description",""))[:160],"config":self._full_config_snapshot(),
                    "vision":self._vision_tuning_snapshot(),"workspace":self._sanitize_workspace(workspace)}
                profiles[name]=profile;data["version"]=1;self._write_json_atomic(self._profiles_file(),data)
                return jsonify(success=True,name=name,profiles=self._profile_summaries(profiles),active_profile=data.get("active_profile"))
            if action=="import":
                profile=body.get("profile")
                if not isinstance(profile,dict) or profile.get("schema_version")!=1:raise ValueError("unsupported or malformed profile file")
                if str(profile.get("mode","")).lower()!=self._mode_slug():return jsonify(success=False,message="profile mode does not match the active robot mode"),409
                if not isinstance(profile.get("vision"),dict):raise ValueError("profile is missing vision settings")
                self._normalize_full_config(profile.get("config"));self._normalize_vision_settings(profile["vision"])
                clean_workspace=self._sanitize_workspace(profile.get("workspace",{}));profile=dict(profile)
                profile.update({"schema_version":1,"name":name,"mode":self._mode_slug(),"saved_at":time.time(),"workspace":clean_workspace})
                profiles[name]=profile;self._write_json_atomic(self._profiles_file(),data)
                return jsonify(success=True,name=name,profiles=self._profile_summaries(profiles))
            if action=="delete":
                if name not in profiles:return jsonify(success=False,message="profile not found"),404
                del profiles[name]
                if data.get("active_profile")==name:data["active_profile"]=None
                self._write_json_atomic(self._profiles_file(),data)
                return jsonify(success=True,profiles=self._profile_summaries(profiles),active_profile=data.get("active_profile"))
            if action=="export":
                if name not in profiles:return jsonify(success=False,message="profile not found"),404
                return jsonify(success=True,profile=profiles[name])
            if action=="load":
                profile=profiles.get(name)
                if profile is None:return jsonify(success=False,message="profile not found"),404
                if str(profile.get("mode","")).lower()!=self._mode_slug():return jsonify(success=False,message="profile mode does not match the active robot mode"),409
                if str(getattr(self.config,"RUN_LVL","MOVE")).upper()!="STOP":return jsonify(success=False,message="Set RUN_LVL=STOP before loading a complete profile."),409
                config=profile.get("config");vision=self._normalize_vision_settings(profile.get("vision",{}));workspace=self._sanitize_workspace(profile.get("workspace",{}))
                self._normalize_full_config(config)
                before_config=self._full_config_snapshot();before_vision=self._vision_tuning_snapshot()
                workspace_file=self._state_filename("workspace");before_workspace=self._read_json_file(workspace_file,self._workspace_default())
                try:
                    self._apply_full_config(config,"loaded profile "+name);vision_apply=self._apply_vision_settings(vision,persist=True)
                    workspace_state=dict(before_workspace);workspace_state["workspace"]=workspace
                    self._write_json_atomic(workspace_file,workspace_state)
                    data["active_profile"]=name;self._write_json_atomic(self._profiles_file(),data)
                except Exception:
                    try:
                        self._apply_full_config(before_config,"rollback failed profile load")
                        self._apply_vision_settings(before_vision,persist=True);self._write_json_atomic(workspace_file,before_workspace)
                    except Exception:logger.exception("Profile rollback was incomplete")
                    raise
                return jsonify(success=True,name=name,config=self._full_config_snapshot(),vision=self._vision_tuning_snapshot(),restart_required=vision_apply.get("restart_required",[]),workspace=workspace,active_profile=name)
            return jsonify(success=False,message="action must be save, load, delete, import, or export"),400
        except (TypeError,ValueError) as exc:return jsonify(success=False,message=str(exc)),400
        except Exception:
            logger.exception("Profile operation failed")
            return jsonify(success=False,message="profile operation failed"),500


def register_profile_routes(app,streamer):
    app.add_url_rule("/api/profiles","profiles_api",streamer.profiles_api,methods=["GET","POST"])
