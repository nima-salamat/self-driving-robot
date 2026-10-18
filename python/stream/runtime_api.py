"""StreamRuntime endpoints and state operations for the Stream dashboard."""
import sys as _sys

# These methods were moved from WebStreamer without changing their behavior.
# Bind shared Stream globals at import time; BASE_DIR is deliberately resolved
# dynamically so existing tests/configuration patching of stream.BASE_DIR remains valid.
_stream_module = _sys.modules[__package__]
for _global_name, _global_value in vars(_stream_module).items():
    if not _global_name.startswith('__'):
        globals()[_global_name] = _global_value

class StreamRuntimeMixin:
    def _feature_diagnostics(self):
        payload = {}
        if getattr(self.config, "CONFIDENCE_AWARE_ENABLED", False):
            payload["perception_confidence"] = getattr(self.config, "perception_confidence", None)
            payload["speed_decision"] = getattr(self.config, "speed_decision", None)
        if getattr(self.config, "ADAPTIVE_OBSTACLE_AVOIDANCE_ENABLED", False):
            payload["obstacle_diagnostics"] = getattr(self.config, "obstacle_diagnostics", None)
        return payload

    def _control_allowed(self):
        return bool(getattr(self.config, "STREAM_ALLOW_CONTROL", False))

    def _control_denied(self):
        return jsonify(success=False, message="stream control is disabled"), 403

    def server_logs(self):
        try:
            limit = max(1, min(200, int(request.args.get("limit", "100"))))
        except (TypeError, ValueError):
            return jsonify(success=False, message="limit must be an integer"), 400
        query = str(request.args.get("q", "")).strip().lower()[:120]
        level = str(request.args.get("level", "ALL")).upper()
        levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
        if level != "ALL" and level not in levels:
            return jsonify(success=False, message="invalid log level"), 400
        with _STREAM_LOG_LOCK:
            entries = list(_STREAM_LOGS)
        selected = []
        for entry in reversed(entries):
            if level != "ALL" and levels.get(entry["level"], 0) < levels[level]:
                continue
            if query and query not in (entry["message"] + " " + entry["logger"]).lower():
                continue
            selected.append(dict(entry))
            if len(selected) >= limit:
                break
        return jsonify(items=selected, count=len(selected), buffer_limit=STREAM_LOG_LIMIT,
                       source="in-memory runtime log buffer")

    def traffic_lights_api(self):
        if self._mode_slug() != "city":
            return jsonify(enabled=False, available=False, reason="traffic-light status is city-only"), 409
        robot = getattr(self.config, "runtime_robot", None)
        enabled = bool(getattr(self.config, "TRAFFIC_LIGHTS_ENABLED", False))
        window = getattr(robot, "traffic_light_window", None) if robot is not None else None
        return jsonify(available=robot is not None, enabled=enabled,
                       wait_before_check=bool(getattr(self.config, "TRAFFIC_LIGHT_WAIT_BEFORE_CHECK", False)),
                       status=getattr(robot, "_traffic_light_status", getattr(self.config, "traffic_light_status", "UNKNOWN")) if robot is not None else "runtime object unavailable",
                       last_state=getattr(robot, "_traffic_light_last_state", None) if robot is not None else None,
                       confirmation_window=window.snapshot() if window is not None and callable(getattr(window, "snapshot", None)) else None,
                       restart_required=not enabled)

    def race_status_api(self):
        if self._mode_slug() != "race":
            return jsonify(available=False, reason="race lifecycle is race-only"), 409
        robot = getattr(self.config, "runtime_robot", None)
        if robot is None:
            return jsonify(available=False, reason="race runtime object unavailable")
        gate, finish, hold = (getattr(robot, "race_start_gate", None),
                              getattr(robot, "race_finish", None), getattr(robot, "stop_hold", None))
        return jsonify(available=True, start_gate_enabled=gate is not None,
                       start_gate_released=bool(getattr(gate, "released", True)) if gate is not None else True,
                       motion_released=bool(getattr(robot, "_race_start_gate_motion_released", True)),
                       timer_started=bool(getattr(robot, "_race_timer_started", False)),
                       finishing=bool(getattr(finish, "finishing", False)) if finish is not None else False,
                       finished=bool(getattr(finish, "finished", False)) if finish is not None else False,
                       stop_hold_active=bool(getattr(hold, "active", False)) if hold is not None else False,
                       sign_observation_fresh=bool(getattr(robot, "last_sign_observation_fresh", False)),
                       stop_detector=getattr(robot, "stop_hold_detector_kind", None),
                       run_level=str(getattr(self.config, "RUN_LVL", "MOVE")))

    def camera_settings_api(self):
        camera = getattr(self.config, "camera", None)
        if request.method == "GET":
            return jsonify(camera=self._camera_settings_snapshot(camera))
        if not self._control_allowed():
            return self._control_denied()
        if camera is None or not bool(getattr(camera, "pi_mode", False)) or getattr(camera, "picam", None) is None:
            return jsonify(success=False, message="runtime camera controls require an initialized Picamera2 camera"), 409
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return jsonify(success=False, message="request body must be an object"), 400
        allowed = {"ExposureTime", "AnalogueGain", "AeEnable", "AwbEnable"}
        if not body or set(body) - allowed:
            return jsonify(success=False, message="only ExposureTime, AnalogueGain, AeEnable, and AwbEnable are accepted"), 400
        supported = getattr(camera.picam, "camera_controls", {})
        controls = {}
        try:
            for key, value in body.items():
                if key not in supported:
                    return jsonify(success=False, message=f"camera does not support {key}"), 409
                if key in {"AeEnable", "AwbEnable"}:
                    if not isinstance(value, bool):
                        raise ValueError(f"{key} must be boolean")
                    controls[key] = value
                else:
                    if isinstance(value, bool):
                        raise ValueError(f"{key} must be numeric")
                    number = float(value)
                    if not math.isfinite(number):
                        raise ValueError(f"{key} must be finite")
                    bounds = supported.get(key)
                    lower = float(bounds[0]) if isinstance(bounds, (tuple, list)) and len(bounds) >= 2 else getattr(bounds, "min", None)
                    upper = float(bounds[1]) if isinstance(bounds, (tuple, list)) and len(bounds) >= 2 else getattr(bounds, "max", None)
                    if lower is not None and upper is not None and not float(lower) <= number <= float(upper):
                        raise ValueError(f"{key} must be between the camera-supported limits {float(lower):g} and {float(upper):g}")
                    controls[key] = int(round(number)) if key == "ExposureTime" else number
            before = self._full_config_snapshot()
            camera.picam.set_controls(controls)
            current = dict(getattr(camera, "_dashboard_image_controls", {}))
            current.update(controls)
            setattr(camera, "_dashboard_image_controls", current)
            self._record_config_history("before camera settings update", before)
            self._record_config_history("camera settings updated")
            logger.info("Dashboard applied camera controls: %s", ", ".join(sorted(controls)))
            return jsonify(success=True, camera=self._camera_settings_snapshot(camera))
        except (TypeError, ValueError) as exc:
            return jsonify(success=False, message=str(exc)), 400
        except Exception:
            logger.exception("Failed to apply runtime Picamera2 controls")
            return jsonify(success=False, message="camera rejected these controls"), 502

    def processing_rate_api(self):
        rate = getattr(self.config, "processing_rate_controller", None)
        if request.method == "GET":
            return jsonify(available=rate is not None, runtime_only=True,
                           target_fps=getattr(rate, "target_fps", getattr(self.config, "TARGET_PROCESSING_FPS", None)) if rate is not None else None,
                           diagnostics=rate.snapshot() if rate is not None and hasattr(rate, "snapshot") else None)
        if not self._control_allowed():
            return self._control_denied()
        if rate is None or not callable(getattr(rate, "set_target_fps", None)):
            return jsonify(success=False, message="the active runtime does not expose live processing-rate control"), 409
        body = request.get_json(silent=True) or {}
        try:
            fps = float(body.get("target_fps"))
            if not math.isfinite(fps) or not 1.0 <= fps <= 60.0:
                raise ValueError("target_fps must be between 1 and 60")
            before = self._full_config_snapshot()
            old_fps = float(rate.target_fps)
            rate.set_target_fps(fps)
            setattr(self.config, "TARGET_PROCESSING_FPS", fps)
            if not self.save_conf_to_json():
                rate.set_target_fps(old_fps)
                setattr(self.config, "TARGET_PROCESSING_FPS", old_fps)
                return jsonify(success=False, message="could not persist processing-rate change; previous rate restored"), 500
            self._record_config_history("before processing rate update", before)
            self._record_config_history("processing rate updated")
            return jsonify(success=True, persisted=True, target_fps=rate.target_fps, diagnostics=rate.snapshot())
        except (TypeError, ValueError) as exc:
            return jsonify(success=False, message=str(exc)), 400

    def safety_api(self):
        if request.method == "GET":
            level = str(getattr(self.config, "RUN_LVL", "MOVE"))
            return jsonify(controls_enabled=self._control_allowed(), run_level=level,
                           software_stop_active=level == "STOP",
                           disclaimer="RUN_LVL STOP is processed by the active Python control loop to stop robot motion; it is not a hardware emergency stop. Sign-inference request pausing is separate at /api/sign-requests.")
        if not self._control_allowed():
            return self._control_denied()
        body = request.get_json(silent=True) or {}
        action = body.get("action")
        if action not in {"stop", "resume"}:
            return jsonify(success=False, message="action must be stop or resume"), 400
        # The mode loop owns the MCU latch; do not send a guessed raw serial command.
        previous_level = str(getattr(self.config, "RUN_LVL", "MOVE"))
        requested_level = "STOP" if action == "stop" else "MOVE"
        setattr(self.config, "RUN_LVL", requested_level)
        if not self.save_conf_to_json():
            # Never undo a stop request because disk persistence failed. For a
            # resume request, retain the previous STOP state instead.
            if action == "resume" and previous_level == "STOP":
                setattr(self.config, "RUN_LVL", "STOP")
            active_level = str(getattr(self.config, "RUN_LVL", "STOP"))
            logger.error("Could not persist software %s request; RUN_LVL remains %s", action, active_level)
            return jsonify(success=False, action=action, run_level=active_level,
                           software_stop_active=active_level == "STOP", persisted=False,
                           message="could not persist runtime control state"), 500
        self._record_config_history("dashboard software " + action)
        logger.warning("Dashboard requested RUN_LVL %s (mode=%s)", requested_level, self._mode_slug())
        return jsonify(success=True, action=action, run_level=getattr(self.config, "RUN_LVL"),
                       software_stop_active=action == "stop", hardware_emergency_stop=False)

    def stop_stream_api(self):
        """Stop only the Stream HTTP server; leave the City/Race runtime alive."""
        if not self._control_allowed():
            return self._control_denied()

        server = getattr(self.config, "stream_server", None)
        if server is None:
            setattr(self.config, "STREAM", False)
            return jsonify(
                success=True,
                stream_enabled=False,
                already_stopped=True,
                shutdown_started=False,
                robot_runtime_continues=True,
                message="Stream server is already stopped.",
            )

        if bool(getattr(self.config, "stream_shutdown_requested", False)):
            return jsonify(
                success=True,
                stream_enabled=False,
                already_stopping=True,
                shutdown_started=True,
                robot_runtime_continues=True,
                message="Stream shutdown is already in progress.",
            )

        # Match running without --stream: disable Stream in the active config,
        # so City/Race stops generating dashboard-only frames as well.
        setattr(self.config, "STREAM", False)
        setattr(self.config, "stream_shutdown_requested", True)
        response = jsonify(
            success=True,
            stream_enabled=False,
            already_stopped=False,
            already_stopping=False,
            shutdown_started=True,
            robot_runtime_continues=True,
            message="Stream server shutdown has been scheduled.",
        )

        # Do not stop the serving socket until this acknowledgement has been
        # sent to the browser. The actual shutdown must run off the request
        # thread because BaseServer.shutdown() waits for serve_forever().
        def schedule_shutdown_after_response():
            try:
                threading.Thread(
                    target=stop_stream,
                    args=(self.config,),
                    daemon=True,
                    name="stream-http-shutdown",
                ).start()
            except Exception:
                logger.exception("Could not start Stream shutdown worker")

        response.call_on_close(schedule_shutdown_after_response)
        return response

    def sign_requests_api(self):
        """Pause/resume sign-inference submissions without changing robot motion state."""
        robot = getattr(self.config, "runtime_robot", None)
        detector = getattr(robot, "sign_detector", None) if robot is not None else None
        if detector is None:
            detector = getattr(self.config, "sign_detector", None)

        def snapshot():
            status_method = getattr(detector, "status", None)
            status = status_method() if callable(status_method) else {}
            return {
                "controls_enabled": self._control_allowed(),
                "available": detector is not None
                and callable(getattr(detector, "pause_requests", None))
                and callable(getattr(detector, "resume_requests", None)),
                "requests_enabled": bool(status.get("requests_enabled", True)),
                "phase_paused": bool(status.get("paused", False)),
                "worker_alive": bool(status.get("worker_alive", False)),
                "queue_depth": int(status.get("queue_depth", 0) or 0),
                "inference_in_flight": bool(status.get("inference_in_flight", False)),
                "run_level": str(getattr(self.config, "RUN_LVL", "MOVE")),
                "control": "sign_inference_requests_only",
            }

        if request.method == "GET":
            return jsonify(snapshot())
        if not self._control_allowed():
            return self._control_denied()

        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify(success=False, message="request body must be a JSON object"), 400
        action = body.get("action")
        if action not in {"pause", "resume"}:
            return jsonify(success=False, message="action must be pause or resume"), 400
        current = snapshot()
        if not current["available"]:
            return jsonify(success=False, message="the active runtime has no sign inference request worker"), 409

        try:
            if action == "pause":
                detector.pause_requests()
            else:
                detector.resume_requests()
            current = snapshot()
            logger.info(
                "Dashboard %s sign inference requests (RUN_LVL unchanged: %s)",
                action,
                current["run_level"],
            )
            return jsonify(
                success=True,
                action=action,
                requests_enabled=current["requests_enabled"],
                run_level=current["run_level"],
                worker=current,
                motion_state_changed=False,
            )
        except Exception:
            logger.exception("Could not %s sign inference requests", action)
            return jsonify(
                success=False,
                message="sign inference request control failed; robot motion state was not changed",
            ), 500

    def _feature_snapshot(self):
        capabilities = mode_capabilities(self.config)
        robot = getattr(self.config, "runtime_robot", None)
        traffic_detector_ready = bool(
            robot is not None
            and getattr(robot, "traffic_light_detector", None) is not None
            and getattr(robot, "traffic_light_window", None) is not None
        )
        return {
            "mode": self._mode_slug(),
            "controls_enabled": self._control_allowed(),
            "live": {
                "DETECT_OBJECT": {
                    "enabled": bool(getattr(self.config, "DETECT_OBJECT", False)),
                    "available": bool(capabilities.get("supports_object_detection", False)),
                    "description": "Object detection is checked each control cycle; the detector is constructed by the active mode.",
                },
                "RECORD_VIDEO": {
                    "enabled": bool(getattr(self.config, "RECORD_VIDEO", False)),
                    "available": bool(capabilities.get("supports_recording", False)),
                    "description": "Recording flag is consumed by the active mode's output manager.",
                },
                "USE_BEV": {
                    "enabled": bool(getattr(self.config, "USE_BEV", False)),
                    "available": bool(capabilities.get("supports_bev", False)),
                    "description": "Bird's-eye transform can be changed live only when supported by the active lane pipeline.",
                },
                "marker_mode": {
                    "value": marker_mode(self.config),
                    "available": bool(
                        capabilities.get("supports_sign", False)
                        and capabilities.get("supports_apriltag", False)
                        and capabilities.get("marker_runtime_control", False)
                    ),
                    "description": "Marker mode uses the mode's existing runtime apply_marker_mode callback.",
                },
            },
            "restart_required": {
                "TRAFFIC_LIGHTS_ENABLED": {
                    "enabled": bool(getattr(self.config, "TRAFFIC_LIGHTS_ENABLED", False)),
                    "available": traffic_detector_ready,
                    "restart_required_to_enable": not traffic_detector_ready,
                    "reason": "City-only opt-in constructed by --traffic-lights at startup; dashboard will not silently create or bypass its safety gate.",
                },
                "CONFIDENCE_AWARE_ENABLED": {
                    "enabled": bool(getattr(self.config, "CONFIDENCE_AWARE_ENABLED", False)),
                    "reason": "Estimator/limiter lifecycle is created during mode initialization; requires --confidence-aware and restart.",
                },
                "ADAPTIVE_OBSTACLE_AVOIDANCE_ENABLED": {
                    "enabled": bool(getattr(self.config, "ADAPTIVE_OBSTACLE_AVOIDANCE_ENABLED", False)),
                    "reason": "Planner and firmware lane-ownership negotiation are startup-time; requires --adaptive-obstacle-avoidance and compatible firmware.",
                },
                "ENCODER_MAP_ENABLED": {
                    "enabled": bool(getattr(self.config, "ENCODER_MAP_ENABLED", False)),
                    "reason": "Odometry and serial telemetry contract are initialized at startup; requires --encoder-map and compatible firmware.",
                },
            },
        }

    def features_api(self):
        if request.method == "GET":
            return jsonify(self._feature_snapshot())
        if not self._control_allowed():
            return self._control_denied()
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return jsonify(success=False, message="request body must be a JSON object"), 400
        feature = str(body.get("feature", ""))
        value = body.get("value")
        capabilities = mode_capabilities(self.config)
        before = self._full_config_snapshot()
        try:
            if feature == "DETECT_OBJECT":
                if not capabilities.get("supports_object_detection", False):
                    return jsonify(success=False, message="object detection is unsupported by the active mode"), 409
                if not isinstance(value, bool):
                    raise ValueError("DETECT_OBJECT value must be boolean")
                setattr(self.config, "DETECT_OBJECT", value)
            elif feature == "RECORD_VIDEO":
                if not capabilities.get("supports_recording", False):
                    return jsonify(success=False, message="recording is unsupported by the active mode"), 409
                if not isinstance(value, bool):
                    raise ValueError("RECORD_VIDEO value must be boolean")
                setattr(self.config, "RECORD_VIDEO", value)
            elif feature == "USE_BEV":
                if not capabilities.get("supports_bev", False):
                    return jsonify(success=False, message="BEV cannot be changed by the active lane pipeline"), 409
                if not isinstance(value, bool):
                    raise ValueError("USE_BEV value must be boolean")
                setattr(self.config, "USE_BEV", value)
            elif feature == "marker_mode":
                if not capabilities.get("marker_runtime_control", False):
                    return jsonify(success=False, message="active runtime has no marker-mode switch callback"), 409
                value = str(value).lower()
                if value not in {"none", "sign", "apriltag"}:
                    raise ValueError("marker_mode must be none, sign, or apriltag")
                if value == "sign" and not capabilities.get("supports_sign", False):
                    return jsonify(success=False, message="traffic sign detection is unsupported by this mode"), 409
                if value == "apriltag" and not capabilities.get("supports_apriltag", False):
                    return jsonify(success=False, message="AprilTag detection is unsupported by this mode"), 409
                set_marker_mode(self.config, value)
            else:
                return jsonify(success=False, message="feature is not runtime-controllable; check restart_required status"), 400
            if not self.save_conf_to_json():
                self._restore_advanced_values(before.get("advanced", {}))
                return jsonify(success=False, message="could not persist feature change; previous state restored"), 500
            self._record_config_history("before feature change " + feature, before)
            self._record_config_history("feature changed: " + feature)
            logger.info("Dashboard live feature change: %s=%s", feature, value)
            return jsonify(success=True, feature=feature, value=value, state=self._feature_snapshot())
        except (TypeError, ValueError) as exc:
            self._restore_advanced_values(before.get("advanced", {}))
            return jsonify(success=False, message=str(exc)), 400
        except Exception:
            logger.exception("Failed to apply live feature change")
            self._restore_advanced_values(before.get("advanced", {}))
            return jsonify(success=False, message="feature change failed; previous state restored"), 500

    def health(self):
        monitor = getattr(self.config, "health_monitor", None)
        metrics = getattr(self.config, "runtime_metrics", None)
        controller = getattr(self.config, "robot_controller", None)

        payload = {
            "health": (
                monitor.snapshot_runtime(self.config)
                if monitor is not None
                else {"state": "UNKNOWN", "lifecycle": "UNKNOWN", "faults": {}}
            ),
            "metrics": metrics.snapshot() if metrics is not None else {},
        }
        if getattr(self.config, "CONFIDENCE_AWARE_ENABLED", False):
            payload["perception_confidence"] = getattr(self.config, "perception_confidence", None)
            payload["speed_decision"] = getattr(self.config, "speed_decision", None)
        if getattr(self.config, "ADAPTIVE_OBSTACLE_AVOIDANCE_ENABLED", False):
            payload["obstacle_diagnostics"] = getattr(self.config, "obstacle_diagnostics", None)

        sign_detector = getattr(self.config, "sign_detector", None)
        output_manager = getattr(self.config, "output_manager", None)
        if sign_detector is not None:
            payload["sign_detector"] = sign_detector.status()
        if output_manager is not None:
            payload["recording"] = output_manager.stats()

        if controller is not None:
            command = controller.last_command
            payload["control"] = {
                "angle": controller.last_angle,
                "speed": controller.current_speed,
                "command": command,
                "command_age_ms": (
                    max(0.0, (time.monotonic() - command["transmitted_at"]) * 1000.0)
                    if command and command.get("transmitted_at") is not None
                    else None
                ),
            }

        payload["stream"] = {
            "frame_seq": getattr(self.config, "stream_frame_seq", 0),
            "buffered_frames": len(
                getattr(self.config, "debug_frames_list", [])
            ),
        }
        processing_rate = getattr(self.config, "processing_rate_controller", None)
        if processing_rate is not None:
            payload["processing_rate"] = processing_rate.snapshot()

        camera = getattr(self.config, "camera", None)
        if camera is not None:
            payload["camera"] = {
                "requested_fps": getattr(
                    camera, "requested_frame_rate", None
                ),
                "measured_fps": getattr(
                    camera, "measured_frame_rate", None
                ),
                "hardware_limits": (
                    camera.get_frame_rate_limits()
                    if hasattr(camera, "get_frame_rate_limits")
                    else None
                ),
            }
        return jsonify(payload)

    def arduino_output(self):
        connection = getattr(self.config, "arduino_connection", None)
        if connection is None:
            return jsonify(enabled=False, connected=False, state="DISCONNECTED", lines=[])
        status = connection.telemetry_status(limit=50)
        status["enabled"] = bool(getattr(self.config, "READ_ARDUINO_OUTPUT", False))
        return jsonify(status)

    def mode(self):
        mode = getattr(self.config, "MODE", "mode")
        capabilities = mode_capabilities(self.config)
        return jsonify(
            mode=mode,
            config_file=os.path.basename(self.config_filename()),
            features={
                "lane_detector": capabilities.get("lane_detector", "default"),
                "ml_lane_detector": capabilities.get("ml_lane_detector", False),
                "bev": bool(
                    capabilities.get("supports_bev", False)
                    and capabilities.get("bev", False)
                ),
                "stream": capabilities.get("stream_enabled", False),
                "encoder_map": capabilities.get("encoder_map_enabled", False),
                "confidence_aware": capabilities.get("confidence_aware_enabled", False),
                "adaptive_obstacle_avoidance": capabilities.get("adaptive_obstacle_avoidance_enabled", False),
                "recording": capabilities.get("recording_enabled", False),
                "sign": capabilities.get("sign_enabled", False),
                "apriltag": capabilities.get("apriltag_enabled", False),
                "object_detection": capabilities.get(
                    "object_detection_enabled", False
                ),
                "crosswalk": capabilities.get("supports_crosswalk", False),
                "marker_mode": marker_mode(self.config),
            },
            capabilities=capabilities,
            controlling_settings={
                "lane_detector": (
                    "CITY_LANE_DETECTOR"
                    if mode == "city"
                    else "USE_ML_LANE_DETECTOR"
                ),
                "marker_mode": ["WITH_SIGN", "WITH_APRILTAG"],
                "bev": "USE_BEV",
            },
        )


def register_runtime_routes(app, streamer):
    """Register stream runtime routes on the shared Flask app."""
    app.add_url_rule("/api/mode", "mode", streamer.mode)
    app.add_url_rule("/api/arduino-output", "arduino_output", streamer.arduino_output)
    app.add_url_rule("/api/health", "health", streamer.health)
    app.add_url_rule("/api/logs", "server_logs", streamer.server_logs)
    app.add_url_rule("/api/traffic-lights", "traffic_lights_api", streamer.traffic_lights_api)
    app.add_url_rule("/api/race", "race_status_api", streamer.race_status_api)
    app.add_url_rule("/api/camera/settings", "camera_settings_api", streamer.camera_settings_api, methods=["GET","POST"])
    app.add_url_rule("/api/processing-rate", "processing_rate_api", streamer.processing_rate_api, methods=["GET","POST"])
    app.add_url_rule("/api/safety", "safety_api", streamer.safety_api, methods=["GET","POST"])
    app.add_url_rule("/api/sign-requests", "sign_requests_api", streamer.sign_requests_api, methods=["GET","POST"])
    app.add_url_rule("/api/stream-control/stop", "stop_stream_api", streamer.stop_stream_api, methods=["POST"])
    app.add_url_rule("/api/features", "features_api", streamer.features_api, methods=["GET","POST"])
