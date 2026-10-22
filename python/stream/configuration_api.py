"""StreamConfiguration endpoints and state operations for the Stream dashboard."""
import sys as _sys

# These methods were moved from WebStreamer without changing their behavior.
from utils.json_config import validate_pulse_sequence, PULSE_SEQUENCE_KEYS

# Bind shared Stream globals at import time; BASE_DIR is deliberately resolved
# dynamically so existing tests/configuration patching of stream.BASE_DIR remains valid.
_stream_module = _sys.modules[__package__]
for _global_name, _global_value in vars(_stream_module).items():
    if not _global_name.startswith('__'):
        globals()[_global_name] = _global_value

class StreamConfigurationMixin:
    def _mode_slug(self):
        raw = str(getattr(self.config, "MODE", "mode")).lower()
        slug = "".join(ch for ch in raw if ch.isalnum() or ch in "-_")
        return slug[:32] or "mode"

    def _state_filename(self, suffix):
        return os.path.join(str(_stream_module.BASE_DIR), f"{self._mode_slug()}_{suffix}.json")

    @staticmethod
    def _write_json_atomic(filename, data):
        directory = os.path.dirname(filename) or "."
        os.makedirs(directory, exist_ok=True)
        lock = _state_file_lock(filename)
        with lock:
            # Separate temporary files avoid collisions, while the path lock
            # serializes writers targeting the same destination in this process.
            temporary = f"{filename}.{os.getpid()}.{threading.get_ident()}.tmp"
            try:
                with open(temporary, "w", encoding="utf-8") as handle:
                    json.dump(data, handle, indent=2, ensure_ascii=False, allow_nan=False)
                    handle.flush()
                    os.fsync(handle.fileno())

                # Windows scanners and short-lived readers can briefly deny
                # replacement of an existing file. Retry only this transient
                # operation; persistent permission errors still propagate.
                replace_attempts = 6
                for attempt in range(replace_attempts):
                    try:
                        os.replace(temporary, filename)
                        break
                    except PermissionError:
                        if attempt + 1 >= replace_attempts:
                            raise
                        time.sleep(min(0.05 * (2 ** attempt), 0.4))
            finally:
                try:
                    if os.path.exists(temporary):
                        os.remove(temporary)
                except OSError:
                    logger.warning("Could not remove temporary dashboard state file")

    @staticmethod
    def _read_json_file(filename, default):
        try:
            with open(filename, "r", encoding="utf-8") as handle:
                value = json.load(handle)
            return value if isinstance(value, dict) else default
        except FileNotFoundError:
            return default
        except (OSError, ValueError, TypeError):
            logger.exception("Unable to read dashboard state file")
            return default

    def _camera_settings_snapshot(self, camera):
        if camera is None:
            return {"available": False, "reason": "camera is not initialized"}
        if not bool(getattr(camera, "pi_mode", False)):
            return {"available": False, "supported": False, "reason": "runtime tuning currently supports Picamera2 only",
                    "requested_fps": getattr(camera, "requested_frame_rate", None),
                    "measured_fps": getattr(camera, "measured_frame_rate", None)}
        picam = getattr(camera, "picam", None)
        controls = getattr(picam, "camera_controls", {}) if picam is not None else {}
        saved = getattr(camera, "_dashboard_image_controls", {"ExposureTime": 10000, "AnalogueGain": 6.0, "AeEnable": False, "AwbEnable": False})
        allowed_controls = {"ExposureTime", "AnalogueGain", "AeEnable", "AwbEnable"}
        current = {key: value for key, value in saved.items() if key in controls and key in allowed_controls}
        control_ranges = {}
        for key in ("ExposureTime", "AnalogueGain"):
            if key not in controls:
                continue
            bounds = controls[key]
            try:
                lower = bounds[0] if isinstance(bounds, (tuple, list)) and len(bounds) >= 2 else getattr(bounds, "min", None)
                upper = bounds[1] if isinstance(bounds, (tuple, list)) and len(bounds) >= 2 else getattr(bounds, "max", None)
                entry = {}
                if lower is not None and math.isfinite(float(lower)):
                    entry["min"] = float(lower)
                if upper is not None and math.isfinite(float(upper)):
                    entry["max"] = float(upper)
                if entry:
                    control_ranges[key] = entry
            except (TypeError, ValueError):
                logger.debug("Camera control bounds unavailable for %s", key)
        return {"available": picam is not None, "supported": picam is not None, "mode": "picam",
                "requested_fps": getattr(camera, "requested_frame_rate", None),
                "measured_fps": getattr(camera, "measured_frame_rate", None),
                "hardware_limits": camera.get_frame_rate_limits() if hasattr(camera, "get_frame_rate_limits") else None,
                "control_names": sorted(str(key) for key in controls.keys()),
                "control_ranges": control_ranges,
                "controls": current}

    def _full_config_snapshot(self):
        rate = getattr(self.config, "processing_rate_controller", None)
        camera = getattr(self.config, "camera", None)
        return {
            "schema_version": 1,
            "mode": self._mode_slug(),
            "values": {var: self.get_base_var(var) for var in VARIABLES},
            "advanced": self.get_all_advanced(),
            "ui": json.loads(json.dumps(self.ui_settings)),
            "runtime": {
                "target_processing_fps": (
                    float(getattr(rate, "target_fps"))
                    if rate is not None and getattr(rate, "target_fps", None) is not None
                    else getattr(self.config, "TARGET_PROCESSING_FPS", None)
                ),
                "camera": self._camera_settings_snapshot(camera),
            },
        }

    def _history_file(self):
        return self._state_filename("config_history")

    def _record_config_history(self, label, snapshot=None):
        try:
            history_file = self._history_file()
            # Keep the read/compare/append/write transaction under one lock;
            # locking only os.replace would still allow concurrent updates to
            # overwrite one another's history entries.
            with _state_file_lock(history_file):
                data = self._read_json_file(history_file, {"items": []})
                items = data.get("items", [])
                if not isinstance(items, list):
                    items = []
                state = snapshot or self._full_config_snapshot()
                signature = json.dumps(state, sort_keys=True, separators=(",", ":"), allow_nan=False)
                if items:
                    previous = items[-1]
                    previous_state = previous.get("snapshot", {}) if isinstance(previous, dict) else {}
                    if json.dumps(previous_state, sort_keys=True, separators=(",", ":"), allow_nan=False) == signature:
                        return
                items.append({"id": int(time.time() * 1000), "timestamp": time.time(),
                              "label": str(label)[:100], "snapshot": state})
                self._write_json_atomic(history_file, {"version": 1, "items": items[-CONFIG_HISTORY_LIMIT:]})
        except Exception:
            logger.exception("Failed to record dashboard configuration history")

    def _normalize_full_config(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("configuration must be a JSON object")
        if payload.get("schema_version", 1) not in (1,):
            raise ValueError("unsupported configuration schema version")
        if str(payload.get("mode", "")).lower() != self._mode_slug():
            raise ValueError("configuration mode does not match the active robot mode")
        raw_values = payload.get("values", {})
        raw_advanced = payload.get("advanced", {})
        raw_ui = payload.get("ui", {})
        if not isinstance(raw_values, dict) or not isinstance(raw_advanced, dict) or not isinstance(raw_ui, dict):
            raise ValueError("values, advanced, and ui must be objects")
        unknown_values = sorted(set(raw_values) - set(VARIABLES))
        unknown_advanced = sorted(set(raw_advanced) - set(ADVANCED_VARS))
        city_only_in_race = (
            sorted(set(raw_advanced) & CITY_ONLY_ADVANCED_VARS)
            if self._mode_slug() != "city" else []
        )
        if unknown_values or unknown_advanced:
            raise ValueError("unknown configuration keys: " + ", ".join(unknown_values + unknown_advanced))
        if city_only_in_race:
            raise ValueError("City crosswalk settings are not available in Race mode: " + ", ".join(city_only_in_race))
        values = {}
        for key, value in raw_values.items():
            if isinstance(value, bool):
                raise ValueError(f"{key} must be numeric")
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"{key} must be numeric") from None
            if not math.isfinite(number) or not 0.0 <= number <= 1.0:
                raise ValueError(f"{key} must be finite and between 0 and 1")
            values[key] = number

        capabilities = mode_capabilities(self.config)
        if ("USE_BEV" in raw_advanced
                and not capabilities.get("supports_bev", False)
                and bool(raw_advanced["USE_BEV"]) != bool(getattr(self.config, "USE_BEV", False))):
            raise ValueError("USE_BEV cannot be changed by the active perception pipeline")
        crosswalk_keys = {"CROSSWALK_THRESHOLD", "CROSSWALK_SLEEP", "CROSSWALK_THRESH_SPEND", "CW_TRAPEZOID_MODE", "CW_TOP_WIDTH_FACTOR", "CROSSWALK_VERTICAL_MIN_LINES", "CROSSWALK_HORIZONTAL_MIN_LINES", "CITY_CROSSWALK_TURN_RIGHT_SEQUENCE", "CITY_CROSSWALK_TURN_LEFT_SEQUENCE", "CITY_CROSSWALK_STRAIGHT_SEQUENCE"}
        lane_shape_keys = {"LANE_ROI_MODE", "RL_TOP_WIDTH_FACTOR", "LL_TOP_WIDTH_FACTOR"}
        changed_crosswalk = any(
            key in raw_advanced and raw_advanced[key] != getattr(self.config, key, ADVANCED_VARS[key])
            for key in crosswalk_keys
        )
        changed_lane_shape = any(
            key in raw_advanced and raw_advanced[key] != getattr(self.config, key, ADVANCED_VARS[key])
            for key in lane_shape_keys
        )
        if changed_crosswalk and not capabilities.get("supports_crosswalk", False):
            raise ValueError("crosswalk settings cannot be changed by the active mode")
        if changed_lane_shape and not capabilities.get("supports_lane_roi", False):
            raise ValueError("lane ROI settings cannot be changed by the active lane detector")

        advanced = {}
        for key, value in raw_advanced.items():
            default = ADVANCED_VARS[key]
            if key == "OUTPUT_LIMITS":
                if not isinstance(value, (list, tuple)) or len(value) != 2:
                    raise ValueError("OUTPUT_LIMITS must contain two numeric values")
                if any(isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)) for item in value):
                    raise ValueError("OUTPUT_LIMITS must contain two finite numbers")
                normalized = [float(value[0]), float(value[1])]
                if not -255.0 <= normalized[0] < normalized[1] <= 255.0:
                    raise ValueError("OUTPUT_LIMITS must be ordered and within -255..255")
            elif key in PULSE_SEQUENCE_KEYS:
                normalized = validate_pulse_sequence(key, value)
            elif type(default) is bool:
                if not isinstance(value, bool):
                    raise ValueError(f"{key} must be boolean")
                normalized = value
            elif type(default) is int:
                if isinstance(value, bool):
                    raise ValueError(f"{key} must be an integer")
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    raise ValueError(f"{key} must be an integer") from None
                if not math.isfinite(number) or not number.is_integer():
                    raise ValueError(f"{key} must be a finite integer")
                normalized = int(number)
            elif type(default) is float:
                if isinstance(value, bool):
                    raise ValueError(f"{key} must be numeric")
                try:
                    normalized = float(value)
                except (TypeError, ValueError):
                    raise ValueError(f"{key} must be numeric") from None
                if not math.isfinite(normalized):
                    raise ValueError(f"{key} must be finite")
            else:
                normalized = str(value)
            if key in {"LANE_THRESHOLD", "CROSSWALK_THRESHOLD"} and not 0 <= normalized <= 255:
                raise ValueError(f"{key} must be between 0 and 255")
            numeric_ranges = {
                "KP": (-100.0, 100.0), "KI": (-100.0, 100.0),
                "KD": (-100.0, 100.0), "KT": (0.0, 10.0),
                "PID_MIN_DT": (0.0001, 1.0), "PID_MAX_DT": (0.001, 5.0),
                "PID_DERIVATIVE_FILTER": (0.0, 1.0),
            }
            if key in numeric_ranges and not numeric_ranges[key][0] <= normalized <= numeric_ranges[key][1]:
                raise ValueError(f"{key} must be between {numeric_ranges[key][0]} and {numeric_ranges[key][1]}")
            if key in {"CROSSWALK_VERTICAL_MIN_LINES", "CROSSWALK_HORIZONTAL_MIN_LINES"} and not 1 <= normalized <= 1000:
                raise ValueError(f"{key} must be between 1 and 1000")
            if key == "LANE_ROI_MODE" and normalized not in {"rectangle", "trapezoid"}:
                raise ValueError("LANE_ROI_MODE must be rectangle or trapezoid")
            if key == "RUN_LVL" and normalized not in {"MOVE", "STOP"}:
                raise ValueError("RUN_LVL must be MOVE or STOP")
            if key.endswith("_WIDTH_FACTOR") and not 0.0 <= normalized <= 1.0:
                raise ValueError(f"{key} must be between 0 and 1")
            if key.startswith("BEV_SRC_") and not -5.0 <= normalized <= 5.0:
                raise ValueError(f"{key} must be between -5 and 5")
            if key == "CAMERA_CALIBRATION_FILE":
                from calibration.asset_store import calibration_path_from_reference
                normalized = str(value).strip()
                calibration_path_from_reference(normalized, require_exists=True)
            advanced[key] = normalized

        calibration_fields = {"CAMERA_CALIBRATION_FILE", "APPLY_CAMERA_CALIBRATION"}
        calibration_changed = any(
            key in advanced and advanced[key] != getattr(self.config, key, ADVANCED_VARS[key])
            for key in calibration_fields
        )
        if calibration_changed and str(getattr(self.config, "RUN_LVL", "MOVE")).upper() != "STOP":
            raise ValueError(
                "Camera calibration can only be changed while RUN_LVL=STOP. "
                "Stop the robot first, then apply the profile."
            )

        if "SERVO_CENTER" in advanced:
            center = int(advanced["SERVO_CENTER"])
            servo_min = float(getattr(self.config, "MIN_SERVO_ANGLE", 55))
            servo_max = float(getattr(self.config, "MAX_SERVO_ANGLE", 125))
            if not servo_min < center < servo_max:
                raise ValueError(
                    f"SERVO_CENTER must be strictly between MIN_SERVO_ANGLE ({servo_min:g}) "
                    f"and MAX_SERVO_ANGLE ({servo_max:g})"
                )
            current_center = int(getattr(self.config, "SERVO_CENTER", 95))
            if center != current_center and str(getattr(self.config, "RUN_LVL", "MOVE")).upper() != "STOP":
                raise ValueError(
                    "SERVO_CENTER can only be changed while RUN_LVL=STOP. "
                    "Stop the robot first, then apply the new servo center."
                )

        if (str(getattr(self.config, "RUN_LVL", "MOVE")) == "STOP"
                and advanced.get("RUN_LVL", "STOP") == "MOVE"):
            # Undo/redo may target a snapshot from before the operator stopped
            # the robot. Restore unrelated settings, but never let a full
            # configuration restore implicitly resume motion.
            advanced["RUN_LVL"] = "STOP"
        pid_min_dt = float(advanced.get("PID_MIN_DT", getattr(self.config, "PID_MIN_DT", 0.001)))
        pid_max_dt = float(advanced.get("PID_MAX_DT", getattr(self.config, "PID_MAX_DT", 0.2)))
        if pid_max_dt < pid_min_dt:
            raise ValueError("PID_MAX_DT must be greater than or equal to PID_MIN_DT")
        if advanced.get("WITH_SIGN", getattr(self.config, "WITH_SIGN", False)) and advanced.get("WITH_APRILTAG", getattr(self.config, "WITH_APRILTAG", False)):
            raise ValueError("WITH_SIGN and WITH_APRILTAG cannot both be enabled")

        ui = json.loads(json.dumps(self.ui_settings))
        colors, visible, opacity = raw_ui.get("colors", {}), raw_ui.get("visible", {}), raw_ui.get("opacity", {})
        frame_overlay = raw_ui.get("frame_overlay", ui.get("frame_overlay", {}))
        if not all(isinstance(obj, dict) for obj in (colors, visible, opacity, frame_overlay)):
            raise ValueError("ui.colors, ui.visible, ui.opacity, and ui.frame_overlay must be objects")
        ui.setdefault("opacity", {key: 1.0 for key in ui["visible"]})
        for key, value in colors.items():
            if key not in ui["colors"] or not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                raise ValueError(f"invalid UI color for {key}")
            ui["colors"][key] = value.lower()
        for key, value in visible.items():
            if key not in ui["visible"] or not isinstance(value, bool):
                raise ValueError(f"invalid UI visibility for {key}")
            ui["visible"][key] = value
        overlay_defaults = ui.get("frame_overlay", {})
        for key, value in frame_overlay.items():
            if key not in overlay_defaults or not isinstance(value, bool):
                raise ValueError(f"invalid frame telemetry overlay value for {key}")
            overlay_defaults[key] = value
        ui["frame_overlay"] = overlay_defaults
        for key, value in opacity.items():
            if key not in ui["visible"] or isinstance(value, bool):
                raise ValueError(f"invalid layer opacity for {key}")
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"invalid layer opacity for {key}") from None
            if not math.isfinite(number) or not 0.0 <= number <= 1.0:
                raise ValueError(f"layer opacity for {key} must be between 0 and 1")
            ui["opacity"][key] = number

        runtime = payload.get("runtime", {})
        if runtime is not None and not isinstance(runtime, dict):
            raise ValueError("runtime must be an object")
        normalized_runtime = {}
        if isinstance(runtime, dict) and runtime.get("target_processing_fps") is not None:
            rate = getattr(self.config, "processing_rate_controller", None)
            try:
                fps = float(runtime["target_processing_fps"])
            except (TypeError, ValueError):
                raise ValueError("target_processing_fps must be numeric") from None
            if not math.isfinite(fps) or fps <= 0:
                raise ValueError("target_processing_fps must be a positive finite number")
            if 1.0 <= fps <= 60.0:
                if rate is None:
                    raise ValueError("live processing-rate control is unavailable in this runtime")
                normalized_runtime["target_processing_fps"] = fps
            else:
                # CLI startup accepts any positive finite target, while live
                # changes are deliberately limited to 1..60 FPS. Full-config
                # restore/Undo must still work for unrelated settings when the
                # active startup rate is outside that live-edit range. Preserve
                # that rate only as an exact no-op; never apply an out-of-range
                # value imported from another snapshot.
                active_rate = (
                    getattr(rate, "target_fps", None)
                    if rate is not None
                    else getattr(self.config, "TARGET_PROCESSING_FPS", None)
                )
                try:
                    same_active_rate = (
                        active_rate is not None
                        and math.isfinite(float(active_rate))
                        and math.isclose(float(active_rate), fps, rel_tol=0.0, abs_tol=1e-9)
                    )
                except (TypeError, ValueError, OverflowError):
                    same_active_rate = False
                if not same_active_rate:
                    raise ValueError(
                        "target_processing_fps must be between 1 and 60; "
                        "an out-of-range startup rate can only be preserved unchanged"
                    )
        if isinstance(runtime, dict):
            raw_camera = runtime.get("camera", {})
            raw_controls = raw_camera.get("controls", {}) if isinstance(raw_camera, dict) else {}
            if isinstance(raw_controls, dict) and raw_controls and raw_camera.get("supported"):
                camera = getattr(self.config, "camera", None)
                if camera is None or not getattr(camera, "pi_mode", False) or getattr(camera, "picam", None) is None:
                    raise ValueError("configuration includes Picamera2 controls but this runtime has no compatible camera")
                supported = getattr(camera.picam, "camera_controls", {})
                normalized_controls = {}
                for key, value in raw_controls.items():
                    if key not in {"ExposureTime", "AnalogueGain", "AeEnable", "AwbEnable"}:
                        continue
                    if key not in supported:
                        raise ValueError(f"camera does not support imported control {key}")
                    if key in {"AeEnable", "AwbEnable"}:
                        if not isinstance(value, bool):
                            raise ValueError(f"{key} must be boolean")
                        normalized_controls[key] = value
                    else:
                        number = float(value)
                        if not math.isfinite(number):
                            raise ValueError(f"{key} must be finite")
                        bounds = supported.get(key)
                        lower = float(bounds[0]) if isinstance(bounds, (tuple, list)) and len(bounds) >= 2 else getattr(bounds, "min", None)
                        upper = float(bounds[1]) if isinstance(bounds, (tuple, list)) and len(bounds) >= 2 else getattr(bounds, "max", None)
                        if lower is not None and upper is not None and not float(lower) <= number <= float(upper):
                            raise ValueError(f"{key} is outside this camera's supported range")
                        normalized_controls[key] = int(round(number)) if key == "ExposureTime" else number
                if normalized_controls.get("AeEnable") is True:
                    normalized_controls.pop("ExposureTime", None)
                    normalized_controls.pop("AnalogueGain", None)
                if normalized_controls:
                    normalized_runtime["camera_controls"] = normalized_controls
        return {"schema_version": 1, "mode": self._mode_slug(), "values": values,
                "advanced": advanced, "ui": ui, "runtime": normalized_runtime}

    def _sync_live_servo_center(self):
        """Propagate the active mode's calibrated center to live steering components."""
        center = int(getattr(self.config, "SERVO_CENTER", 95))
        controller = getattr(self.config, "robot_controller", None)
        if controller is not None:
            controller.servo_center = center
            connection = getattr(controller, "connection", None)
            if connection is not None:
                connection.servo_center = center

        vision = getattr(self.config, "vision_processor", None)
        if vision is not None:
            for detector in (vision, getattr(vision, "ml_lane_detector", None)):
                if detector is None:
                    continue
                if hasattr(detector, "servo_center"):
                    detector.servo_center = float(center)
                if hasattr(detector, "last_steering"):
                    detector.last_steering = float(center)
                if hasattr(detector, "_last_config_servo_center"):
                    detector._last_config_servo_center = float(center)

        odometry = getattr(self.config, "encoder_odometry", None)
        if odometry is not None and hasattr(odometry, "servo_center"):
            odometry.servo_center = float(center)

    def _sync_live_pid_settings(self):
        """Replace the PID object from validated active-mode settings."""
        controller = getattr(self.config, "robot_controller", None)
        if controller is None:
            return
        from controller.pid_controller import PIDController
        limits = getattr(self.config, "OUTPUT_LIMITS", (-80, 80))
        if not isinstance(limits, (tuple, list)) or len(limits) != 2:
            raise ValueError("OUTPUT_LIMITS must contain two values")
        controller.pid = PIDController(
            float(getattr(self.config, "KP", 0.35)),
            float(getattr(self.config, "KI", 0.0)),
            float(getattr(self.config, "KD", 0.01)),
            float(getattr(self.config, "KT", 0.01)),
            output_limits=(float(limits[0]), float(limits[1])),
            min_dt=float(getattr(self.config, "PID_MIN_DT", 0.001)),
            max_dt=float(getattr(self.config, "PID_MAX_DT", 0.2)),
            derivative_filter=float(getattr(self.config, "PID_DERIVATIVE_FILTER", 0.25)),
        )

    def _apply_full_config(self, payload, label="configuration restore"):
        normalized = self._normalize_full_config(payload)
        before = self._full_config_snapshot()
        pid_keys = {"USE_PID", "KP", "KI", "KD", "KT", "OUTPUT_LIMITS", "PID_MIN_DT", "PID_MAX_DT", "PID_DERIVATIVE_FILTER"}
        pid_changed = any(key in normalized["advanced"] and normalized["advanced"][key] != before.get("advanced", {}).get(key) for key in pid_keys)
        servo_center_changed = (
            "SERVO_CENTER" in normalized["advanced"]
            and normalized["advanced"]["SERVO_CENTER"] != before.get("advanced", {}).get("SERVO_CENTER")
        )
        calibration_fields = {"CAMERA_CALIBRATION_FILE", "APPLY_CAMERA_CALIBRATION"}
        calibration_changed = any(
            key in normalized["advanced"]
            and normalized["advanced"][key] != before.get("advanced", {}).get(key)
            for key in calibration_fields
        )
        camera = getattr(self.config, "camera", None)
        try:
            for key, value in normalized["values"].items():
                setattr(self.config, key, value)
            for key, value in normalized["advanced"].items():
                if key not in {"WITH_SIGN", "WITH_APRILTAG"}:
                    setattr(self.config, key, value)
            if "WITH_SIGN" in normalized["advanced"] or "WITH_APRILTAG" in normalized["advanced"]:
                sign = normalized["advanced"].get("WITH_SIGN", getattr(self.config, "WITH_SIGN", False))
                tag = normalized["advanced"].get("WITH_APRILTAG", getattr(self.config, "WITH_APRILTAG", False))
                set_marker_mode(self.config, "sign" if sign else "apriltag" if tag else "none")
            if pid_changed:
                self._sync_live_pid_settings()
            if servo_center_changed:
                self._sync_live_servo_center()
            if calibration_changed and camera is not None:
                switch = getattr(camera, "set_camera_calibration_file", None)
                if not callable(switch):
                    raise ValueError("active camera does not support live calibration switching")
                switch(
                    str(getattr(self.config, "CAMERA_CALIBRATION_FILE")),
                    enabled=bool(getattr(self.config, "APPLY_CAMERA_CALIBRATION", True)),
                )
            self.ui_settings = normalized["ui"]
            setattr(self.config, "stream_ui_settings", self.ui_settings)
            if not self.save_ui_settings():
                raise RuntimeError("failed to persist UI settings")
            if "target_processing_fps" in normalized["runtime"]:
                fps = normalized["runtime"]["target_processing_fps"]
                self.config.processing_rate_controller.set_target_fps(fps)
                setattr(self.config, "TARGET_PROCESSING_FPS", fps)
            if "camera_controls" in normalized["runtime"]:
                camera = self.config.camera
                camera.picam.set_controls(normalized["runtime"]["camera_controls"])
                current = dict(getattr(camera, "_dashboard_image_controls", {}))
                current.update(normalized["runtime"]["camera_controls"])
                setattr(camera, "_dashboard_image_controls", current)
            if not self.save_conf_to_json():
                raise RuntimeError("failed to persist runtime configuration")
            self._record_config_history("before " + label, before)
            self._record_config_history(label, self._full_config_snapshot())
            return self._full_config_snapshot()
        except Exception:
            for key, value in before.get("values", {}).items():
                setattr(self.config, key, value)
            for key, value in before.get("advanced", {}).items():
                if key not in {"WITH_SIGN", "WITH_APRILTAG"}:
                    setattr(self.config, key, value)
            self.ui_settings = before.get("ui", self.ui_settings)
            setattr(self.config, "stream_ui_settings", self.ui_settings)
            try:
                set_marker_mode(self.config, "sign" if before["advanced"].get("WITH_SIGN") else "apriltag" if before["advanced"].get("WITH_APRILTAG") else "none")
            except Exception:
                logger.exception("Could not roll back marker mode after failed import")
            if pid_changed:
                try:
                    self._sync_live_pid_settings()
                except Exception:
                    logger.exception("Could not roll back live PID state after failed import")
            if servo_center_changed:
                try:
                    self._sync_live_servo_center()
                except Exception:
                    logger.exception("Could not roll back live servo-center state after failed import")
            if calibration_changed and camera is not None:
                try:
                    camera.set_camera_calibration_file(
                        str(before.get("advanced", {}).get("CAMERA_CALIBRATION_FILE")),
                        enabled=bool(before.get("advanced", {}).get("APPLY_CAMERA_CALIBRATION", True)),
                    )
                except Exception:
                    logger.exception("Could not roll back live camera calibration after failed import")
            before_runtime = before.get("runtime", {})
            old_rate = before_runtime.get("target_processing_fps")
            rate = getattr(self.config, "processing_rate_controller", None)
            if rate is not None and old_rate is not None:
                try:
                    rate.set_target_fps(old_rate)
                    setattr(self.config, "TARGET_PROCESSING_FPS", old_rate)
                except Exception:
                    logger.exception("Could not roll back processing rate after failed import")
            old_camera = before_runtime.get("camera", {})
            old_controls = old_camera.get("controls", {}) if isinstance(old_camera, dict) else {}
            camera = getattr(self.config, "camera", None)
            if old_controls and camera is not None and getattr(camera, "picam", None) is not None:
                try:
                    camera.picam.set_controls(old_controls)
                    setattr(camera, "_dashboard_image_controls", dict(old_controls))
                except Exception:
                    logger.exception("Could not roll back camera controls after failed import")
            self.ui_settings = before["ui"]
            self.save_ui_settings()
            self.save_conf_to_json()
            raise

    def full_config(self):
        if request.method == "GET":
            snapshot = self._full_config_snapshot()
            snapshot["exported_at"] = time.time()
            snapshot["controls_enabled"] = self._control_allowed()
            return jsonify(snapshot)
        if not self._control_allowed():
            return self._control_denied()
        payload = request.get_json(silent=True)
        try:
            result = self._apply_full_config(payload, "imported configuration")
            return jsonify(success=True, config=result)
        except (TypeError, ValueError) as exc:
            return jsonify(success=False, message=str(exc)), 400
        except Exception:
            logger.exception("Failed to apply full dashboard configuration")
            return jsonify(success=False, message="configuration apply failed"), 500

    def config_history(self):
        data = self._read_json_file(self._history_file(), {"items": []})
        items = data.get("items", []) if isinstance(data.get("items", []), list) else []
        items = items[-CONFIG_HISTORY_LIMIT:]
        if request.method == "GET":
            summary = []
            for index, item in enumerate(items):
                snap = item.get("snapshot", {}) if isinstance(item, dict) else {}
                summary.append({"index": index, "id": item.get("id"), "timestamp": item.get("timestamp"),
                                "label": item.get("label", "Configuration"), "mode": snap.get("mode"),
                                "advanced_keys": len(snap.get("advanced", {})), "roi_keys": len(snap.get("values", {}))})
            return jsonify(items=summary, limit=CONFIG_HISTORY_LIMIT)
        if not self._control_allowed():
            return self._control_denied()
        body = request.get_json(silent=True) or {}
        if body.get("action") != "restore":
            return jsonify(success=False, message="action must be restore"), 400
        try:
            index = int(body.get("index"))
        except (TypeError, ValueError):
            return jsonify(success=False, message="index must be an integer"), 400
        if index < 0 or index >= len(items):
            return jsonify(success=False, message="history index not found"), 404
        try:
            result = self._apply_full_config(items[index].get("snapshot"), "restored history")
            return jsonify(success=True, config=result)
        except (TypeError, ValueError) as exc:
            return jsonify(success=False, message=str(exc)), 400
        except Exception:
            logger.exception("Failed to restore configuration history")
            return jsonify(success=False, message="history restore failed"), 500

    def config_presets(self):
        filename = self._state_filename("config_presets")
        data = self._read_json_file(filename, {"presets": {}})
        presets = data.get("presets", {}) if isinstance(data.get("presets", {}), dict) else {}
        if request.method == "GET":
            requested_name = str(request.args.get("name", "")).strip()
            if requested_name:
                preset = presets.get(requested_name)
                if not preset:
                    return jsonify(success=False, message="preset not found"), 404
                return jsonify(name=requested_name, mode=preset.get("mode"), saved_at=preset.get("saved_at"),
                               config=preset.get("config"))
            return jsonify(presets=[{"name": name, "mode": value.get("mode"), "saved_at": value.get("saved_at")}
                                    for name, value in sorted(presets.items())])
        if not self._control_allowed():
            return self._control_denied()
        body = request.get_json(silent=True) or {}
        action, name = str(body.get("action", "")), str(body.get("name", "")).strip()
        if not name or len(name) > 48 or not re.fullmatch(r"[A-Za-z0-9 _.-]+", name):
            return jsonify(success=False, message="preset name must be 1-48 safe characters"), 400
        if action == "save":
            presets[name] = {"mode": self._mode_slug(), "saved_at": time.time(), "config": self._full_config_snapshot()}
        elif action == "delete":
            if name not in presets:
                return jsonify(success=False, message="preset not found"), 404
            del presets[name]
        elif action == "apply":
            preset = presets.get(name)
            if not preset:
                return jsonify(success=False, message="preset not found"), 404
            try:
                result = self._apply_full_config(preset.get("config"), "applied preset " + name)
            except (TypeError, ValueError) as exc:
                return jsonify(success=False, message=str(exc)), 400
            except Exception:
                logger.exception("Failed to apply configuration preset")
                return jsonify(success=False, message="preset apply failed"), 500
            self._write_json_atomic(filename, {"version": 1, "presets": presets})
            return jsonify(success=True, config=result)
        else:
            return jsonify(success=False, message="action must be save, delete, or apply"), 400
        self._write_json_atomic(filename, {"version": 1, "presets": presets})
        return jsonify(success=True, presets=[{"name": key, "mode": value.get("mode"), "saved_at": value.get("saved_at")} for key, value in sorted(presets.items())])

    def _workspace_default(self):
        return {"version": 1, "workspace": {}, "profiles": {}}

    def _sanitize_workspace(self, workspace):
        if not isinstance(workspace, dict):
            raise ValueError("workspace must be a JSON object")
        if len(json.dumps(workspace, ensure_ascii=False)) > 250000:
            raise ValueError("workspace data exceeds 250 KB")
        clean = {}
        view = workspace.get("view", {})
        if not isinstance(view, dict):
            raise ValueError("view must be an object")
        clean_view = {}
        for key, minimum, maximum in (("zoom", 0.3, 4.0), ("panX", -100000.0, 100000.0), ("panY", -100000.0, 100000.0), ("rightPaneWidth", 250.0, 700.0)):
            if key in view:
                value = view[key]
                if isinstance(value, bool):
                    raise ValueError(f"view.{key} must be numeric")
                value = float(value)
                if not math.isfinite(value) or not minimum <= value <= maximum:
                    raise ValueError(f"view.{key} is out of range")
                clean_view[key] = value
        for key in ("grid", "snap", "crosshair", "showRuler", "overlays", "viewLocked"):
            if key in view:
                if not isinstance(view[key], bool):
                    raise ValueError(f"view.{key} must be boolean")
                clean_view[key] = view[key]
        if "crosshairPoint" in view:
            point = view["crosshairPoint"]
            if point is None:
                clean_view["crosshairPoint"] = None
            elif not isinstance(point, dict) or point.get("space") not in {"image", "canvas"}:
                raise ValueError("view.crosshairPoint must use image or canvas coordinates")
            else:
                space = point["space"]
                clean_point = {"space": space}
                minimum, maximum = (-1000000.0, 1000000.0) if space == "image" else (0.0, 1.0)
                for axis in ("u", "v"):
                    if isinstance(point.get(axis), bool):
                        raise ValueError(f"view.crosshairPoint.{axis} must be numeric")
                    try:
                        coordinate = float(point.get(axis))
                    except (TypeError, ValueError):
                        raise ValueError(f"view.crosshairPoint.{axis} must be numeric") from None
                    if not math.isfinite(coordinate) or not minimum <= coordinate <= maximum:
                        raise ValueError(f"view.crosshairPoint.{axis} is out of range for {space} coordinates")
                    clean_point[axis] = coordinate
                clean_view["crosshairPoint"] = clean_point
        if "gridMode" in view:
            if view["gridMode"] not in {"off", "grid", "dots"}:
                raise ValueError("view.gridMode must be off, grid, or dots")
            clean_view["gridMode"] = view["gridMode"]
        if "gridStyle" in view:
            if view["gridStyle"] not in {"grid", "dots"}:
                raise ValueError("view.gridStyle must be grid or dots")
            clean_view["gridStyle"] = view["gridStyle"]
        for key, minimum, maximum in (("gridSpacing", 0.025, 0.25), ("gridOpacity", 0.05, 1.0), ("gridThickness", 0.5, 3.0), ("gridDotSize", 1.0, 6.0), ("keyboardNudgePx", 1.0, 100.0), ("streamFps", 1.0, 30.0), ("mmPerSourcePixel", 0.0, 10000.0)):
            if key in view:
                if isinstance(view[key], bool):
                    raise ValueError(f"view.{key} must be numeric")
                value = float(view[key])
                if not math.isfinite(value) or not minimum <= value <= maximum:
                    raise ValueError(f"view.{key} is out of range")
                clean_view[key] = value
        if "gridColor" in view:
            color = view["gridColor"]
            if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                raise ValueError("view.gridColor must be a six-digit hex color")
            clean_view["gridColor"] = color.lower()
        if "tool" in view:
            tool = view["tool"]
            if tool in {"roi", "roi_rect", "roi_trapezoid"}:
                # Older workspaces persisted visual-only custom ROI drawing tools.
                clean_view["tool"] = "select"
            elif tool in {"select", "pan", "annotate", "ruler"}:
                clean_view["tool"] = tool
            else:
                raise ValueError("view.tool is invalid")
        clean["view"] = clean_view
        appearance = workspace.get("roiAppearance", {})
        if not isinstance(appearance, dict):
            raise ValueError("roiAppearance must be an object")
        clean_appearance = {}
        for key, minimum, maximum in (("labelFontSize", 6.0, 32.0), ("outlineThickness", 0.5, 6.0), ("handleSize", 4.0, 24.0)):
            if key in appearance:
                if isinstance(appearance[key], bool):
                    raise ValueError(f"roiAppearance.{key} must be numeric")
                value = float(appearance[key])
                if not math.isfinite(value) or not minimum <= value <= maximum:
                    raise ValueError(f"roiAppearance.{key} is out of range")
                clean_appearance[key] = value
        if "labelFontWeight" in appearance:
            weight = str(appearance["labelFontWeight"])
            if weight not in {"400", "500", "600", "700"}:
                raise ValueError("roiAppearance.labelFontWeight is invalid")
            clean_appearance["labelFontWeight"] = weight
        clean["roiAppearance"] = clean_appearance
        panels = workspace.get("panels", {})
        if not isinstance(panels, dict):
            raise ValueError("panels must be an object")
        clean["panels"] = {str(key)[:80]: value for key, value in panels.items() if isinstance(value, bool)}
        layers = workspace.get("layers", {})
        if not isinstance(layers, dict):
            raise ValueError("layers must be an object")
        clean_layers = {}
        for key, layer in layers.items():
            if key not in {"RL", "LL", "CW", "ST", "OBJ", "BEV", "ANNOTATIONS", "GRID"} or not isinstance(layer, dict):
                continue
            entry = {}
            if "visible" in layer:
                if not isinstance(layer["visible"], bool):
                    raise ValueError(f"layers.{key}.visible must be boolean")
                entry["visible"] = layer["visible"]
            if "opacity" in layer:
                val = float(layer["opacity"])
                if not math.isfinite(val) or not 0 <= val <= 1:
                    raise ValueError(f"layers.{key}.opacity must be between 0 and 1")
                entry["opacity"] = val
            clean_layers[key] = entry
        clean["layers"] = clean_layers
        annotations = workspace.get("annotations", [])
        if not isinstance(annotations, list) or len(annotations) > 250:
            raise ValueError("annotations must be a list of at most 250 items")
        clean_annotations = []
        for item in annotations:
            if isinstance(item, dict) and item.get("kind") in {"roi", "roi_rect", "roi_trapezoid"}:
                # Migrate old preview-only shapes out of saved workspaces.
                continue
            if not isinstance(item, dict) or item.get("kind") not in {"marker", "note", "ruler"}:
                raise ValueError("annotation has an unsupported kind")
            space = item.get("space", "image")
            if space not in {"image", "canvas"}:
                raise ValueError("annotation space must be image or canvas")
            entry = {"kind": item["kind"]}
            if "space" in item:
                entry["space"] = space
            minimum, maximum = (-1000000.0, 1000000.0) if space == "image" else (0.0, 1.0)
            for key in ("u", "v", "u2", "v2"):
                if key in item:
                    if isinstance(item[key], bool):
                        raise ValueError("annotation coordinates must be numeric")
                    val = float(item[key])
                    if not math.isfinite(val) or not minimum <= val <= maximum:
                        raise ValueError("annotation coordinates are out of range for " + space + " coordinates")
                    entry[key] = val
            if "distancePx" in item:
                if isinstance(item["distancePx"], bool):
                    raise ValueError("annotation distance must be numeric")
                distance = float(item["distancePx"])
                if not math.isfinite(distance) or not 0 <= distance <= 1000000000:
                    raise ValueError("annotation distance is out of range")
                entry["distancePx"] = distance
            if "label" in item:
                entry["label"] = str(item["label"])[:80]
            if "color" in item and isinstance(item["color"], str) and re.fullmatch(r"#[0-9a-fA-F]{6}", item["color"]):
                entry["color"] = item["color"].lower()
            clean_annotations.append(entry)
        clean["annotations"] = clean_annotations
        return clean

    def workspace_api(self):
        filename = self._state_filename("workspace")
        data = self._read_json_file(filename, self._workspace_default())
        if not isinstance(data.get("profiles"), dict):
            data["profiles"] = {}
        if request.method == "GET":
            return jsonify(version=1, workspace=data.get("workspace", {}), profiles=sorted(data["profiles"].keys()))
        body = request.get_json(silent=True) or {}
        action = str(body.get("action", "save_workspace"))
        try:
            if action == "save_workspace":
                data["workspace"] = self._sanitize_workspace(body.get("workspace", {}))
            elif action == "save_profile":
                name = str(body.get("name", "")).strip()
                if not name or len(name) > 48 or not re.fullmatch(r"[A-Za-z0-9 _.-]+", name):
                    raise ValueError("profile name must be 1-48 safe characters")
                data["profiles"][name] = self._sanitize_workspace(body.get("workspace", {}))
            elif action == "delete_profile":
                name = str(body.get("name", "")).strip()
                if name not in data["profiles"]:
                    return jsonify(success=False, message="profile not found"), 404
                del data["profiles"][name]
            elif action == "load_profile":
                name = str(body.get("name", "")).strip()
                if name not in data["profiles"]:
                    return jsonify(success=False, message="profile not found"), 404
                return jsonify(success=True, workspace=data["profiles"][name], name=name)
            else:
                return jsonify(success=False, message="unsupported workspace action"), 400
            self._write_json_atomic(filename, data)
            return jsonify(success=True, workspace=data.get("workspace", {}), profiles=sorted(data["profiles"].keys()))
        except (TypeError, ValueError) as exc:
            return jsonify(success=False, message=str(exc)), 400
        except Exception:
            logger.exception("Failed to persist dashboard workspace")
            return jsonify(success=False, message="workspace save failed"), 500


def register_configuration_routes(app, streamer):
    """Register stream configuration routes on the shared Flask app."""
    app.add_url_rule("/api/config/full", "full_config", streamer.full_config, methods=["GET","POST"])
    app.add_url_rule("/api/config/history", "config_history", streamer.config_history, methods=["GET","POST"])
    app.add_url_rule("/api/config/presets", "config_presets", streamer.config_presets, methods=["GET","POST"])
    app.add_url_rule("/api/workspace", "workspace_api", streamer.workspace_api, methods=["GET","POST"])
