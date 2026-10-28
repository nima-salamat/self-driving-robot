"""StreamControls endpoints and state operations for the Stream dashboard."""
import sys as _sys

# These methods were moved from WebStreamer without changing their behavior.
# Bind shared Stream globals at import time; BASE_DIR is deliberately resolved
# dynamically so existing tests/configuration patching of stream.BASE_DIR remains valid.
_stream_module = _sys.modules[__package__]
for _global_name, _global_value in vars(_stream_module).items():
    if not _global_name.startswith('__'):
        globals()[_global_name] = _global_value

class StreamControlsMixin:
    def get_base_var(self, var):
        default = 1.0 if ("BOTTOM" in var or "RIGHT" in var) else 0.0
        return float(getattr(self.config, var, default))

    def get_all_advanced(self):
        res = {}
        active_mode = str(getattr(self.config, "MODE", "mode")).lower()
        for k, default_v in ADVANCED_VARS.items():
            if active_mode != "city" and k in CITY_ONLY_ADVANCED_VARS:
                continue
            val = getattr(self.config, k, default_v)
            if k == "OUTPUT_LIMITS":
                if not isinstance(val, (tuple, list)) or len(val) != 2:
                    val = default_v
                res[k] = [float(val[0]), float(val[1])]
            elif type(default_v) == bool: res[k] = bool(val)
            elif type(default_v) == int: res[k] = int(val)
            elif type(default_v) == float: res[k] = float(val)
            else: res[k] = str(val)
        return res

    def _restore_advanced_values(self, snapshot):
        """Roll back an in-memory dashboard mutation to a known-good snapshot."""
        if not isinstance(snapshot, dict):
            return
        for key, value in snapshot.items():
            if key not in {"WITH_SIGN", "WITH_APRILTAG"}:
                setattr(self.config, key, value)
        connection = getattr(self.config, "arduino_connection", None)
        policy_setter = getattr(connection, "set_automatic_commands_enabled", None)
        if callable(policy_setter) and "SEND_AUTOMATIC_ARDUINO_COMMANDS" in snapshot:
            policy_setter(bool(snapshot["SEND_AUTOMATIC_ARDUINO_COMMANDS"]))
        if "SERVO_CENTER" in snapshot:
            try:
                self._sync_live_servo_center()
            except Exception:
                logger.exception("Could not restore live servo-center state")
        try:
            set_marker_mode(
                self.config,
                "sign" if snapshot.get("WITH_SIGN", False)
                else "apriltag" if snapshot.get("WITH_APRILTAG", False)
                else "none",
            )
        except Exception:
            logger.exception("Could not restore the prior marker-detector mode")

    def ui_filename(self):
        mode = getattr(self.config, "MODE", "mode")
        return os.path.join(str(_stream_module.BASE_DIR), f"{mode}_ui.json")

    def load_ui_settings(self):
        fname = self.ui_filename()
        default_ui = {
            "colors": {"RL":"#ff7b7b", "LL":"#7bffb8", "CW":"#ffd27b", "BEV":"#d946ef", "ST":"#bf7bff", "OBJ":"#ff5757"},
            "visible": {"RL":True, "LL":True, "CW":True, "BEV":True, "ST":True, "OBJ":True},
            "opacity": {"RL":1.0, "LL":1.0, "CW":1.0, "BEV":0.8, "ST":1.0, "OBJ":1.0},
            "frame_overlay": {
            "fps": True, "realfps": False, "status": True,
            "applied_angle": True, "vision_angle": True, "servo_center": True,
            "crosswalk": False, "sign": False, "last_tag": False,
            "error": False, "lane_type": False, "speed": False,
            "confidence": False, "obstacle": False,
                "servo_guide": True, "candidate_labels": True,
        }
        }
        if os.path.exists(fname):
            try:
                with open(fname, "r") as f:
                    data = json.load(f)
                    ui = {
                        "colors": data.get("colors", default_ui["colors"]),
                        "visible": data.get("visible", default_ui["visible"]),
                        "opacity": data.get("opacity", default_ui["opacity"]),
                        "frame_overlay": data.get("frame_overlay", default_ui["frame_overlay"]),
                    }
                    if not isinstance(ui["frame_overlay"], dict):
                        ui["frame_overlay"] = dict(default_ui["frame_overlay"])
                    else:
                        ui["frame_overlay"] = {
                            key: ui["frame_overlay"].get(key, default)
                            if isinstance(ui["frame_overlay"].get(key, default), bool)
                            else default
                            for key, default in default_ui["frame_overlay"].items()
                        }
                    for key in default_ui["colors"]:
                        if key not in ui["colors"]: ui["colors"][key] = default_ui["colors"][key]
                    for key in default_ui["visible"]:
                        if key not in ui["visible"]: ui["visible"][key] = default_ui["visible"][key]
                        if key not in ui["opacity"]: ui["opacity"][key] = default_ui["opacity"][key]
                    return ui
            except Exception:
                logger.exception("Failed load UI settings")
        return default_ui

    def save_ui_settings(self):
        try:
            self._write_json_atomic(self.ui_filename(), self.ui_settings)
            return True
        except Exception:
            logger.exception("Failed writing UI settings")
            return False

    def config_filename(self):
        mode = getattr(self.config, "MODE", "mode")
        return os.path.join(str(_stream_module.BASE_DIR), f"{mode}.json")

    def save_conf_to_json(self):
        filename = self.config_filename()
        try:
            # Preserve every mode-specific setting not editable in this
            # dashboard. Replacing the JSON with just the ROI/advanced subset
            # would silently discard speeds, sign thresholds, hardware
            # contracts and other controls owned by the mode config.
            data = {}
            if os.path.exists(filename):
                with open(filename, "r", encoding="utf-8") as handle:
                    existing = json.load(handle)
                if not isinstance(existing, dict):
                    raise ValueError("mode configuration file must contain a JSON object")
                data.update(existing)

            data.update({var: self.get_base_var(var) for var in VARIABLES})
            data.update(self.get_all_advanced())
            target_rate = getattr(self.config, "processing_rate_controller", None)
            if target_rate is not None:
                data["TARGET_PROCESSING_FPS"] = float(target_rate.target_fps)
            self._write_json_atomic(filename, data)
            return True
        except Exception:
            logger.exception("Failed writing config JSON without dropping unrelated mode settings")
            return False

    def update_conf(self):
        if not self._control_allowed():
            return self._control_denied()
        try:
            data = request.get_json(silent=True)
            if data is None:
                data = request.form.to_dict()
            if not isinstance(data, dict):
                return jsonify(success=False, message="request body must be an object"), 400

            # Validate the entire request before changing any runtime value.
            updated = {}
            for var in VARIABLES:
                if var not in data:
                    continue
                try:
                    val = float(data[var])
                except (TypeError, ValueError):
                    return jsonify(success=False, message=f"{var} must be numeric"), 400
                if not math.isfinite(val) or not 0.0 <= val <= 1.0:
                    return jsonify(success=False, message=f"{var} must be finite and between 0 and 1"), 400
                updated[var] = val

            if updated:
                try:
                    self._validate_roi_geometry(updated)
                except ValueError as exc:
                    return jsonify(success=False, message=str(exc)), 400

                before = self._full_config_snapshot()
                for var, val in updated.items():
                    setattr(self.config, var, val)
                if not self.save_conf_to_json():
                    for var, val in before.get("values", {}).items():
                        setattr(self.config, var, val)
                    return jsonify(success=False, message="could not persist ROI settings; previous values restored"), 500
                self._record_config_history("before ROI update", before)
                self._record_config_history("ROI settings updated")
            return jsonify(
                success=True,
                values={var: self.get_base_var(var) for var in VARIABLES},
            )
        except Exception:
            logger.exception("Failed to update stream configuration")
            return jsonify(
                success=False,
                message="Failed to update stream configuration",
            ), 500

    def get_values(self):
        return jsonify(values={var: self.get_base_var(var) for var in VARIABLES})

    def get_advanced(self):
        return jsonify(advanced=self.get_all_advanced())

    def set_advanced(self):
        if not self._control_allowed():
            return self._control_denied()
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(
                success=False,
                message="request body must be a JSON object",
            ), 400

        capabilities = mode_capabilities(self.config)
        unsupported = []
        if "USE_BEV" in data and not capabilities.get("supports_bev", False):
            unsupported.append("USE_BEV")
        crosswalk_keys = {
            "CROSSWALK_THRESHOLD",
            "CROSSWALK_SLEEP",
            "CROSSWALK_THRESH_SPEND",
            "CW_TRAPEZOID_MODE",
            "CW_TOP_WIDTH_FACTOR",
            "CROSSWALK_VERTICAL_MIN_LINES",
            "CROSSWALK_HORIZONTAL_MIN_LINES",
            "CITY_CROSSWALK_TURN_RIGHT_SEQUENCE",
            "CITY_CROSSWALK_TURN_LEFT_SEQUENCE",
            "CITY_CROSSWALK_STRAIGHT_SEQUENCE",
        }
        if (
            any(key in data for key in crosswalk_keys)
            and not capabilities.get("supports_crosswalk", False)
        ):
            unsupported.extend(sorted(key for key in crosswalk_keys if key in data))
        lane_shape_keys = {
            "LANE_ROI_MODE",
            "RL_TOP_WIDTH_FACTOR",
            "LL_TOP_WIDTH_FACTOR",
        }
        if (
            any(key in data for key in lane_shape_keys)
            and not capabilities.get("supports_lane_roi", False)
        ):
            unsupported.extend(sorted(key for key in lane_shape_keys if key in data))
        if unsupported:
            return jsonify(
                success=False,
                message="unsupported controls for active mode",
                unsupported=unsupported,
            ), 409

        # These changes have dedicated, guarded workflows. Keep them out of
        # the generic settings endpoint so they cannot bypass the safety gates.
        if any(key in data for key in ("CAMERA_CALIBRATION_FILE", "APPLY_CAMERA_CALIBRATION")):
            return jsonify(
                success=False,
                message="Use the Camera Calibration Profile controls to validate and apply calibration files.",
            ), 409
        if (
            str(getattr(self.config, "RUN_LVL", "MOVE")).upper() == "STOP"
            and data.get("RUN_LVL", "STOP") != "STOP"
        ):
            return jsonify(
                success=False,
                message="motion is software-stopped; use the explicit /api/safety resume action",
            ), 409
        if "SERVO_CENTER" in data:
            raw_center = data["SERVO_CENTER"]
            if isinstance(raw_center, bool):
                return jsonify(success=False, message="SERVO_CENTER must be an integer"), 400
            try:
                center = int(raw_center)
                if float(raw_center) != center:
                    raise ValueError
            except (TypeError, ValueError, OverflowError):
                return jsonify(success=False, message="SERVO_CENTER must be an integer"), 400
            minimum = float(getattr(self.config, "MIN_SERVO_ANGLE", 55))
            maximum = float(getattr(self.config, "MAX_SERVO_ANGLE", 125))
            if not minimum < center < maximum:
                return jsonify(
                    success=False,
                    message=f"SERVO_CENTER must be strictly between {minimum:g} and {maximum:g}",
                ), 400
            if (
                center != int(getattr(self.config, "SERVO_CENTER", 95))
                and str(getattr(self.config, "RUN_LVL", "MOVE")).upper() != "STOP"
            ):
                return jsonify(
                    success=False,
                    message="Set RUN_LVL=STOP before changing SERVO_CENTER.",
                ), 409

        # Validate through the same schema used by full-config imports before
        # mutating runtime state or writing a file. This also rejects unknown
        # keys, non-finite numbers, invalid pulse sequences and cross-field
        # constraints such as PID_MIN_DT > PID_MAX_DT.
        payload = {
            "schema_version": 1,
            "mode": self._mode_slug(),
            "values": {},
            "advanced": data,
            "ui": {},
            "runtime": {},
        }
        try:
            self._apply_full_config(payload, "advanced settings update")
        except (TypeError, ValueError) as exc:
            return jsonify(success=False, message=str(exc)), 400
        except Exception:
            logger.exception("Failed to apply advanced settings")
            return jsonify(
                success=False,
                message="Failed to apply advanced settings; previous settings were restored where possible.",
            ), 500
        return jsonify(success=True, advanced=self.get_all_advanced())

    def get_ui(self):
        return jsonify(ui=self.ui_settings)

    def set_ui(self):
        if not self._control_allowed():
            return self._control_denied()
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify(success=False, message="request body must be a JSON object"), 400
        for group in ("colors", "visible", "opacity", "frame_overlay"):
            if group in data and not isinstance(data[group], dict):
                return jsonify(success=False, message=f"{group} must be a JSON object"), 400
        before = self._full_config_snapshot()
        previous_ui = json.loads(json.dumps(self.ui_settings))
        try:
            for key, value in data.get("colors", {}).items():
                if key not in self.ui_settings["colors"] or not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                    raise ValueError("colors must be six-digit hex colors for known layers")
            for key, value in data.get("visible", {}).items():
                if key not in self.ui_settings["visible"] or not isinstance(value, bool):
                    raise ValueError("visible must contain boolean values for known layers")
            for key, value in data.get("frame_overlay", {}).items():
                if key not in self.ui_settings["frame_overlay"] or not isinstance(value, bool):
                    raise ValueError("frame_overlay must contain boolean values for known telemetry fields")
            for key, value in data.get("opacity", {}).items():
                if key not in self.ui_settings["visible"] or isinstance(value, bool):
                    raise ValueError("opacity must contain numeric values for known layers")
                number = float(value)
                if not math.isfinite(number) or not 0 <= number <= 1:
                    raise ValueError("opacity must be between 0 and 1")
            self.ui_settings["colors"].update({k:v.lower() for k,v in data.get("colors", {}).items()})
            self.ui_settings["visible"].update(data.get("visible", {}))
            self.ui_settings.setdefault("opacity", {}).update({k:float(v) for k,v in data.get("opacity", {}).items()})
            self.ui_settings.setdefault("frame_overlay", {}).update(data.get("frame_overlay", {}))
            setattr(self.config, "stream_ui_settings", self.ui_settings)
            if not self.save_ui_settings():
                self.ui_settings = previous_ui
                setattr(self.config, "stream_ui_settings", self.ui_settings)
                return jsonify(success=False, message="failed to persist UI settings; values were rolled back"), 500
            self._record_config_history("before layer update", before)
            self._record_config_history("layer visibility/color/opacity update")
            return jsonify(success=True, ui=self.ui_settings)
        except (TypeError, ValueError) as exc:
            self.ui_settings = previous_ui
            setattr(self.config, "stream_ui_settings", self.ui_settings)
            return jsonify(success=False, message=str(exc)), 400
        except Exception:
            self.ui_settings = previous_ui
            setattr(self.config, "stream_ui_settings", self.ui_settings)
            self.save_ui_settings()
            logger.exception("Failed to persist dashboard layer settings")
            return jsonify(success=False, message="failed to persist layer settings; values were rolled back"), 500


def register_control_routes(app, streamer):
    """Register stream controls routes on the shared Flask app."""
    app.add_url_rule("/update_conf", "update_conf", streamer.update_conf, methods=["POST"])
    app.add_url_rule("/get_values", "get_values", streamer.get_values)
    app.add_url_rule("/get_advanced", "get_advanced", streamer.get_advanced)
    app.add_url_rule("/set_advanced", "set_advanced", streamer.set_advanced, methods=["POST"])
    app.add_url_rule("/get_ui", "get_ui", streamer.get_ui)
    app.add_url_rule("/set_ui", "set_ui", streamer.set_ui, methods=["POST"])
