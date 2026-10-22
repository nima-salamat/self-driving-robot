import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from stream import WebStreamer, publish_camera_frame_fallback, publish_debug_frame
from calibration.asset_store import CALIBRATION_ASSET_RELATIVE_DIR


class StreamApiTests(unittest.TestCase):
    def setUp(self):
        import stream

        self._stream_test_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._stream_test_directory.cleanup)
        base_dir_patch = patch.object(stream, "BASE_DIR", self._stream_test_directory.name)
        base_dir_patch.start()
        self.addCleanup(base_dir_patch.stop)
        env_patch = patch.dict(os.environ, {"STREAM_USERNAME": "", "STREAM_PASSWORD": ""})
        env_patch.start()
        self.addCleanup(env_patch.stop)

    def make_config(self):
        return types.SimpleNamespace(
            MODE="city",
            STREAM=True,
            STREAM_ALLOW_CONTROL=False,
            RECORD_VIDEO=False,
            USE_BEV=False,
            USE_ML_LANE_DETECTOR=False,
            CITY_LANE_DETECTOR="blsf-beta",
            debug_frames_list=[np.zeros((32, 48, 3), dtype=np.uint8)],
            stream_frame_seq=1,
            OUTPUT_DIR="output",
        )

    def test_stream_api_handlers_are_split_into_modules_without_changing_routes(self):
        streamer = WebStreamer(self.make_config())

        self.assertEqual(WebStreamer.update_conf.__module__, "stream.controls_api")
        self.assertEqual(WebStreamer.full_config.__module__, "stream.configuration_api")
        self.assertEqual(WebStreamer.mode.__module__, "stream.runtime_api")
        self.assertEqual(WebStreamer.index.__module__, "stream.pages_api")
        self.assertEqual(WebStreamer.video_feed.__module__, "stream.media_api")

        registered = {(rule.rule, rule.endpoint) for rule in streamer.app.url_map.iter_rules()}
        expected = {
            ("/", "index"),
            ("/update_conf", "update_conf"),
            ("/get_values", "get_values"),
            ("/get_advanced", "get_advanced"),
            ("/set_advanced", "set_advanced"),
            ("/get_ui", "get_ui"),
            ("/set_ui", "set_ui"),
            ("/video_feed_frame", "video_feed_frame"),
            ("/video_feed", "video_feed"),
            ("/api/stream/quality", "stream_quality_api"),
            ("/api/mode", "mode"),
            ("/api/arduino-output", "arduino_output"),
            ("/api/health", "health"),
            ("/api/config/full", "full_config"),
            ("/api/config/history", "config_history"),
            ("/api/config/presets", "config_presets"),
            ("/api/workspace", "workspace_api"),
            ("/api/logs", "server_logs"),
            ("/api/traffic-lights", "traffic_lights_api"),
            ("/api/race", "race_status_api"),
            ("/api/camera/settings", "camera_settings_api"),
            ("/api/camera/calibrations", "camera_calibrations_api"),
            ("/api/processing-rate", "processing_rate_api"),
            ("/api/safety", "safety_api"),
            ("/api/sign-requests", "sign_requests_api"),
            ("/api/stream-control/stop", "stop_stream_api"),
            ("/api/features", "features_api"),
            ("/encoder-map", "encoder_map_page"),
            ("/api/encoder-map", "encoder_map_api"),
            ("/api/encoder-map/reset-origin", "encoder_map_reset_origin"),
            ("/take_picture", "take_picture"),
            ("/toggle_record", "toggle_record"),
            ("/freeze_frame", "freeze_frame"),
            ("/unfreeze_frame", "unfreeze_frame"),
        }
        self.assertTrue(expected.issubset(registered))

        config = self.make_config()
        config.ENCODER_MAP_ENABLED = True
        response = WebStreamer(config).app.test_client().get("/encoder-map")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Estimated Odometry", response.get_data(as_text=True))

    def test_stream_exit_stops_only_stream_server_and_requires_controls(self):
        import threading

        config = self.make_config()
        config.RUN_LVL = "MOVE"
        client = WebStreamer(config).app.test_client()

        denied = client.post("/api/stream-control/stop", json={"action": "stop"})
        self.assertEqual(denied.status_code, 403)
        self.assertTrue(config.STREAM)
        self.assertEqual(config.RUN_LVL, "MOVE")

        class FakeServer:
            def __init__(self):
                self.shutdown_called = threading.Event()

            def shutdown(self):
                self.shutdown_called.set()

        config.STREAM_ALLOW_CONTROL = True
        server = FakeServer()
        config.stream_server = server
        response = client.post("/api/stream-control/stop", json={"action": "stop"})
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertTrue(payload["shutdown_started"])
        self.assertTrue(payload["robot_runtime_continues"])
        self.assertFalse(config.STREAM)
        self.assertTrue(config.stream_shutdown_requested)
        self.assertEqual(config.RUN_LVL, "MOVE")
        response.close()
        self.assertTrue(server.shutdown_called.wait(timeout=1.0))

    def test_exit_stream_has_a_custom_confirmation_dialog_and_endpoint_binding(self):
        stream_dir = PYTHON_ROOT / "stream"
        core = (stream_dir / "static" / "stream-core.js").read_text(encoding="utf-8")
        extensions = (stream_dir / "static" / "stream-extensions.js").read_text(encoding="utf-8")
        template = (stream_dir / "templates" / "stream.html").read_text(encoding="utf-8")
        css = (stream_dir / "static" / "stream.css").read_text(encoding="utf-8")

        self.assertIn('data-action="exit-stream"', template)
        self.assertIn('id="ext_stream_exit_dialog"', template)
        self.assertIn('id="ext_stream_exit_confirm"', template)
        self.assertIn("The robot’s main City/Race loop", template)
        self.assertIn("case 'exit-stream'", core)
        self.assertIn("window.openStreamExitDialog=openStreamExitDialog", extensions)
        self.assertIn("nativeFetch('/api/stream-control/stop'", extensions)
        self.assertIn("STREAM is now false in this running process", extensions)
        self.assertIn(".menu-dropdown button.menu-danger", css)
        self.assertIn("window.location.replace('about:blank')", extensions)

        # Check the page as Flask actually renders it, not just source templates.
        live_config = self.make_config()
        live_config.STREAM_ALLOW_CONTROL = True
        rendered = WebStreamer(live_config).app.test_client().get("/")
        self.assertEqual(rendered.status_code, 200)
        rendered_html = rendered.get_data(as_text=True)
        self.assertIn('data-action="exit-stream"', rendered_html)
        self.assertIn("Exit · Stop Stream Server…", rendered_html)

    def test_fullscreen_exit_uses_a_complete_minimize_icon(self):
        stream_dir = PYTHON_ROOT / "stream"
        template = (stream_dir / "templates" / "stream.html").read_text(encoding="utf-8")
        core = (stream_dir / "static" / "stream-core.js").read_text(encoding="utf-8")

        self.assertIn(
            'd="M8 3v5H3M21 8h-5V3M3 16h5v5M16 21v-5h5"',
            template,
        )
        self.assertIn("collapseIcon.style.display=active?'':'none'", core)

    def test_event_console_supports_bounded_pointer_and_keyboard_resize(self):
        stream_dir = PYTHON_ROOT / "stream"
        extensions = (stream_dir / "static" / "stream-extensions.js").read_text(encoding="utf-8")
        template = (stream_dir / "templates" / "stream.html").read_text(encoding="utf-8")
        css = (stream_dir / "static" / "stream.css").read_text(encoding="utf-8")

        self.assertIn('id="console_resize_handle"', template)
        self.assertIn('role="separator" aria-orientation="horizontal"', template)
        self.assertIn('function initializeConsoleResize()', extensions)
        self.assertIn("handle.addEventListener('pointerdown'", extensions)
        self.assertIn("handle.addEventListener('pointermove'", extensions)
        self.assertIn("event.key==='ArrowUp'", extensions)
        self.assertIn("event.key==='ArrowDown'", extensions)
        self.assertIn("event.key==='Home'", extensions)
        self.assertIn("event.key==='End'", extensions)
        self.assertIn("function closedHeight(bounds)", extensions)
        self.assertIn("const requested=startHeight-(event.clientY-startY)", extensions)
        self.assertIn("if(requested<=closed)", extensions)
        self.assertIn("toggleOpen(false)", extensions)
        self.assertIn("toggleOpen(true)", extensions)
        self.assertIn("Drag upward to open and downward to close.", template)
        self.assertIn("repeating-linear-gradient(to right, #607d98 0 5px, transparent 5px 9px)", css)
        self.assertNotIn(".bottom-console:not(.console-open) .console-resize-handle span {", css)
        self.assertIn("shortLandscape?200:(mobile?360:520)", extensions)
        self.assertIn(".bottom-console:not(.console-open) {\n  height: 42px;", css)
        self.assertNotIn(".bottom-console:not(.console-open) .console-resize-handle { display: none; }", css)
        self.assertIn("initializeConsoleResize();", extensions)
        self.assertIn(".bottom-console.console-resizing", css)
        self.assertIn("max-height: min(62dvh, 520px)", css)
        self.assertIn("max-height: min(55dvh, 360px)", css)
        self.assertIn("max-height: min(42dvh, 200px)", css)

    def test_workspace_keyboard_shortcuts_and_command_search_are_complete(self):
        stream_dir = PYTHON_ROOT / "stream"
        extensions = (stream_dir / "static" / "stream-extensions.js").read_text(encoding="utf-8")
        template = (stream_dir / "templates" / "stream.html").read_text(encoding="utf-8")
        css = (stream_dir / "static" / "stream.css").read_text(encoding="utf-8")

        for menu_id, mnemonic in (("file", "F"), ("edit", "E"), ("view", "V"), ("tools", "T"), ("help", "H")):
            self.assertIn('data-menu-id="' + menu_id + '"', template)
            self.assertIn('<span class="menu-mnemonic">' + mnemonic + '</span>', template)

        for code in ("KeyP", "KeyC", "KeyW", "KeyS", "KeyA", "KeyD", "KeyR"):
            self.assertIn("'" + code + "'", extensions)
        for code, menu_id in (("KeyF", "file"), ("KeyE", "edit"), ("KeyV", "view"), ("KeyT", "tools"), ("KeyH", "help")):
            self.assertIn(code + ":'" + menu_id + "'", extensions)
        self.assertIn("function installWorkspaceKeyboardShortcuts()", extensions)
        self.assertIn("event.preventDefault();event.stopPropagation();", extensions)
        self.assertIn("function focusPanelNavigation()", extensions)
        self.assertIn("function adjustSettingsPanelWidth(direction)", extensions)
        self.assertIn("function changeConsoleHeight(direction)", extensions)
        self.assertIn("refresh-config','Ctrl+Alt+R'", extensions)
        self.assertIn("matchedCommands=commands.filter(function(entry){return !query||paletteNormalize(entry[0]+' '+entry[2]+' '+(entry[3]||'')).includes(query);})", extensions)
        self.assertIn("app-menubar.shortcuts-visible .menu-mnemonic", css)
        self.assertIn("Focus panel navigation; use ↑/↓, Space or Enter", template)
        self.assertIn("Increase / decrease console height by one step", template)
        self.assertIn("Refresh configuration values &amp; advanced settings", template)

    def _valid_camera_calibration_bytes(self):
        payload = io.BytesIO()
        metadata = {
            "format_version": 3,
            "calibration_model": "pinhole",
            "image_width": 640,
            "image_height": 480,
            "quality_status": "pass",
            "acceptable_for_runtime": True,
        }
        np.savez(
            payload,
            cameraMatrix=np.asarray(
                [[500.0, 0.0, 320.0], [0.0, 500.0, 240.0], [0.0, 0.0, 1.0]],
                dtype=np.float64,
            ),
            distCoeffs=np.zeros((5, 1), dtype=np.float64),
            imageSize=np.asarray([640, 480], dtype=np.int32),
            metadata=json.dumps(metadata),
        )
        return payload.getvalue()

    def test_servo_center_update_reaches_live_controller_connection_and_vision(self):
        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        config.RUN_LVL = "STOP"
        config.SERVO_CENTER = 95
        config.MIN_SERVO_ANGLE = 55.0
        config.MAX_SERVO_ANGLE = 125.0
        config.SERVO_DIRECTION = "ltr"
        connection = types.SimpleNamespace(servo_center=95)
        controller = types.SimpleNamespace(servo_center=95, connection=connection)
        vision = types.SimpleNamespace(
            servo_center=95.0, last_steering=95.0, ml_lane_detector=None
        )
        config.robot_controller = controller
        config.vision_processor = vision

        client = WebStreamer(config).app.test_client()
        payload = client.get("/api/config/full").get_json()
        payload["advanced"]["SERVO_CENTER"] = 103
        response = client.post("/api/config/full", json=payload)

        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(config.SERVO_CENTER, 103)
        self.assertEqual(controller.servo_center, 103)
        self.assertEqual(connection.servo_center, 103)
        self.assertEqual(vision.servo_center, 103.0)
        self.assertEqual(vision.last_steering, 103.0)

    def test_servo_center_generic_advanced_api_requires_stop_and_syncs_on_success(self):
        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        config.RUN_LVL = "MOVE"
        config.SERVO_CENTER = 95
        config.MIN_SERVO_ANGLE = 55.0
        config.MAX_SERVO_ANGLE = 125.0
        config.SERVO_DIRECTION = "ltr"
        controller = types.SimpleNamespace(servo_center=95, connection=types.SimpleNamespace(servo_center=95))
        config.robot_controller = controller
        client = WebStreamer(config).app.test_client()

        rejected = client.post("/set_advanced", json={"SERVO_CENTER": 101})
        self.assertEqual(rejected.status_code, 409)
        self.assertEqual(config.SERVO_CENTER, 95)

        config.RUN_LVL = "STOP"
        applied = client.post("/set_advanced", json={"SERVO_CENTER": 101})
        self.assertEqual(applied.status_code, 200, applied.get_json())
        self.assertEqual(config.SERVO_CENTER, 101)
        self.assertEqual(controller.servo_center, 101)
        self.assertEqual(controller.connection.servo_center, 101)

    def test_camera_calibration_upload_validate_select_and_stop_gate(self):
        from calibration import asset_store

        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        config.RUN_LVL = "STOP"
        config.CAMERA_CALIBRATION_FILE = CALIBRATION_ASSET_RELATIVE_DIR + "/camera_calibration.npz"
        config.APPLY_CAMERA_CALIBRATION = True
        asset_dir = Path(self._stream_test_directory.name) / "camera_calibrations"
        asset_dir.mkdir()
        previous_file = asset_dir / "camera_calibration.npz"
        previous_file.write_bytes(self._valid_camera_calibration_bytes())

        class FakeCamera:
            pi_mode = False
            picam = None

            def __init__(self):
                self.selected = None

            def set_camera_calibration_file(self, reference, enabled=True):
                self.selected = (reference, enabled)
                return {"enabled": enabled, "filename": reference.rsplit("/", 1)[-1]}

        camera = FakeCamera()
        config.camera = camera
        client = WebStreamer(config).app.test_client()

        with patch.object(asset_store, "CALIBRATION_ASSET_DIR", asset_dir):
            listed = client.get("/api/camera/calibrations")
            self.assertEqual(listed.status_code, 200, listed.get_json())
            self.assertTrue(listed.get_json()["active_calibration"]["valid"])

            uploaded = client.post(
                "/api/camera/calibrations",
                data={"file": (io.BytesIO(self._valid_camera_calibration_bytes()), "alternate profile.npz")},
                content_type="multipart/form-data",
            )
            self.assertEqual(uploaded.status_code, 200, uploaded.get_json())
            upload_data = uploaded.get_json()
            self.assertFalse(upload_data["active_changed"])
            reference = upload_data["reference"]
            self.assertIn("alternate_profile", reference)

            applied = client.post(
                "/api/camera/calibrations",
                json={"action": "select", "reference": reference, "enabled": True},
            )
            self.assertEqual(applied.status_code, 200, applied.get_json())
            self.assertEqual(camera.selected, (reference, True))
            self.assertEqual(config.CAMERA_CALIBRATION_FILE, reference)
            self.assertTrue(config.APPLY_CAMERA_CALIBRATION)

            config.RUN_LVL = "MOVE"
            denied = client.post(
                "/api/camera/calibrations",
                json={"action": "select", "reference": reference, "enabled": False},
            )
            self.assertEqual(denied.status_code, 409)
            self.assertEqual(camera.selected, (reference, True))

    def test_frame_overlay_preferences_persist_and_update_runtime_config(self):
        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        client = WebStreamer(config).app.test_client()
        response = client.post(
            "/set_ui",
            json={"frame_overlay": {"fps": False, "status": True, "servo_center": True}},
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertFalse(config.stream_ui_settings["frame_overlay"]["fps"])
        self.assertTrue(config.stream_ui_settings["frame_overlay"]["servo_center"])
        saved = json.loads((Path(self._stream_test_directory.name) / "city_ui.json").read_text(encoding="utf-8"))
        self.assertFalse(saved["frame_overlay"]["fps"])
        self.assertTrue(saved["frame_overlay"]["servo_center"])

    def test_settings_panel_has_visible_bounded_keyboard_resizer(self):
        stream_dir = PYTHON_ROOT / "stream"
        extensions = (stream_dir / "static" / "stream-extensions.js").read_text(encoding="utf-8")
        template = (stream_dir / "templates" / "stream.html").read_text(encoding="utf-8")
        css = (stream_dir / "static" / "stream.css").read_text(encoding="utf-8")

        self.assertIn('id="panel_resize_handle"', template)
        self.assertIn('role="separator" aria-orientation="vertical"', template)
        self.assertIn('title="Drag to resize the settings panel.', template)
        self.assertIn("function initializeResize()", extensions)
        self.assertIn("handle.addEventListener('pointerdown'", extensions)
        self.assertIn("handle.addEventListener('pointermove'", extensions)
        self.assertIn("event.key==='ArrowLeft'", extensions)
        self.assertIn("event.key==='ArrowRight'", extensions)
        self.assertIn("event.key==='Home'", extensions)
        self.assertIn("event.key==='End'", extensions)
        self.assertIn("Math.min(700,window.innerWidth-360)", extensions)
        self.assertIn(".panel-resize-handle{display:none;align-items:center;justify-content:center", css)
        self.assertIn("grid-template-columns:minmax(0,1fr) 12px var(--right-pane-width)", css)
        self.assertIn(".container.dock-hidden > .panel-resize-handle { display:none !important; }", css)
        self.assertIn(".container:not(.dock-hidden) > .panel-resize-handle {\n    display: flex !important;", css)
        self.assertIn(".panel-resize-handle { display:none !important; }", css)

    def test_stream_editor_precision_and_layout_hooks_are_present(self):
        stream_dir = PYTHON_ROOT / "stream"
        core = (stream_dir / "static" / "stream-core.js").read_text(encoding="utf-8")
        extensions = (stream_dir / "static" / "stream-extensions.js").read_text(encoding="utf-8")
        template = (stream_dir / "templates" / "stream.html").read_text(encoding="utf-8")
        css = (stream_dir / "static" / "stream.css").read_text(encoding="utf-8")

        self.assertIn("if(!showRectsCheckbox.checked)return {type:'none'}", core)
        self.assertIn("let streamDisplayFps = 8.3", core)
        self.assertIn("function setStreamDisplayFps(value)", core)
        self.assertIn("Math.round(1000/streamDisplayFps)", core)
        self.assertIn("window.ensureStreamDockVisible=()=>setDock(true)", core)
        self.assertIn("window.setStreamWorkspaceTool=setTool", core)
        self.assertIn("function setWorkspaceViewLocked(locked,log=true,persist=true)", core)
        self.assertIn('id="workspace_zoom_percent" class="zoom-percent" type="text"', template)
        self.assertIn('aria-label="View zoom percentage"', template)
        # Zoom controls live in the camera footer, while View Lock is a camera-tool action.
        self.assertGreater(template.index('id="workspace_zoom_percent"'), template.index('class="workspace-statusbar"'))
        self.assertGreater(template.index('id="cad_selected_area"'), template.index('id="workspace_zoom_percent"'))
        tool_start = template.index('<aside class="left-toolbar"')
        tool_end = template.index('</aside>', tool_start)
        lock_pos = template.index('id="workspace_view_lock"')
        self.assertGreater(lock_pos, tool_start)
        self.assertLess(lock_pos, tool_end)
        self.assertLess(lock_pos, template.index('data-action="fit-view"', tool_start))
        self.assertEqual(template.count('id="workspace_view_lock"'), 1)
        self.assertEqual(template.count('id="workspace_lock_shackle"'), 1)
        self.assertIn('view-lock-icon', template)
        self.assertNotIn('side-view-controls', template)
        self.assertIn('Object: None', template)
        self.assertIn('viewport-fit=cover', template)
        self.assertIn('.app-menubar .command-launch-button', css)
        self.assertIn('.app-menubar .stream-auth-menu button', css)
        self.assertIn('Mobile workspace: keep every tool reachable', css)
        self.assertIn('Landscape phones have little vertical room', css)
        self.assertIn('.left-toolbar .view-lock-button', css)
        self.assertIn('overscroll-behavior: none', css)
        self.assertIn(r"raw.match(/^(?:([0-9]+(?:\.[0-9]*)?)|(\.[0-9]+))\s*%?$/)", core)
        self.assertIn("zoomPercentInput.addEventListener('focus',function(){this.select();})", core)
        self.assertIn("zoomPercentInput.addEventListener('blur',applyWorkspaceZoomPercent)", core)
        self.assertIn("if(event.key==='Enter'){event.preventDefault();if(applyWorkspaceZoomPercent())this.blur();}", core)
        self.assertIn("else if(event.key==='Escape')", core)
        self.assertIn("percent<30||percent>400", core)
        self.assertIn("if(zoomPercent)zoomPercent.disabled=workspaceViewLocked", core)
        self.assertIn("if(workspaceViewLocked)return false", core)
        self.assertIn("if(workspaceViewLocked){showToast('View is locked. Unlock it to zoom or pan.')", core)
        self.assertIn("function openStreamShortcuts()", core)
        self.assertIn("e.code==='F1'", core)
        self.assertIn("e.code==='KeyH'", core)
        self.assertIn("pixelStep/source.width", core)
        self.assertIn("function roundPixelNormalized(v)", core)
        self.assertIn("values[n.left]=roundPixelNormalized(nl)", core)
        self.assertIn("function getGridStepX()", core)
        self.assertIn("copyCoordinateText(coordinateText)", extensions)
        self.assertIn("function installCoordinatePairPaste()", extensions)
        self.assertIn("extCrosshair=false", extensions)
        self.assertIn("e.code==='KeyK'", extensions)
        self.assertIn("e.code==='KeyS'", extensions)
        self.assertIn("gridColor", extensions)
        self.assertIn("const baseStep=Math.max(.001,Math.max(.025,Math.min(.25,Number(gridSpacing)||.05))*b.ih)", extensions)
        self.assertIn("const minScreenPitch=gridMode==='dots'?8:10,stride=Math.max(1,Math.ceil(minScreenPitch/baseStep)),step=baseStep*stride", extensions)
        self.assertIn("svg.replaceChildren()", extensions)
        self.assertIn("const radius=Math.max(.6,Math.min(24,(Number(gridDotSize)||2)*z))", extensions)
        self.assertIn("window.drawPrecisionOverlay=drawPrecisionOverlay", extensions)
        self.assertIn("firstColumn=Math.floor((0-b.ix)/step)", extensions)
        self.assertIn("firstRow=Math.floor((0-b.iy)/step)", extensions)
        self.assertIn("'stroke-width':Math.max(.4,Number(gridThickness)||1)", extensions)
        self.assertIn("let lastVisibleGridMode='grid'", extensions)
        self.assertIn("gridStyle:lastVisibleGridMode", extensions)
        self.assertIn("if(pointerInsideImage&&extSnap)", extensions)
        self.assertIn("space:'image'", extensions)
        self.assertIn("svg.replaceChildren()", extensions)
        self.assertIn("readout.x.textContent='X: '+Math.round(u*source.width)+' px'", core)
        self.assertIn("outside=u<0||u>1||v<0||v>1", core)
        self.assertIn('minimum, maximum = (-1000000.0, 1000000.0) if space == "image" else (0.0, 1.0)', (PYTHON_ROOT / "stream" / "configuration_api.py").read_text(encoding="utf-8"))
        self.assertIn("annotation coordinates are out of range for ", (PYTHON_ROOT / "stream" / "configuration_api.py").read_text(encoding="utf-8"))
        self.assertIn("keyboardNudgePx", extensions)
        self.assertIn("streamFps:streamFps", extensions)
        self.assertIn("viewLocked:typeof window.isWorkspaceViewLocked", extensions)
        self.assertIn("window.onWorkspaceViewLockChanged=function()", extensions)
        self.assertIn("Toggle view lock", extensions)
        self.assertIn("function settingSearchEntries()", extensions)
        self.assertIn("function navigateToPaletteSetting(entry)", extensions)
        self.assertIn("function updateActiveToolBanner()", extensions)
        self.assertIn("function isPaletteCommandActive(name)", extensions)
        self.assertIn("Force Stop (RUN_LVL → STOP)", extensions)
        self.assertIn("function refreshSignRequests()", extensions)
        self.assertIn("function signRequestsAction(action)", extensions)
        self.assertIn("nativeFetch('/api/sign-requests'", extensions)
        self.assertIn("function refreshSafety()", extensions)
        self.assertIn("await Promise.all([refreshSafety(),refreshSignRequests()])", extensions)
        self.assertIn('id="ext_sign_requests_pause"', template)
        self.assertIn('id="ext_sign_requests_resume"', template)
        self.assertIn("This does not change RUN_LVL", template)
        self.assertIn('id="ext_safety_panel"', template)
        self.assertIn('id="ext_software_stop"', template)
        self.assertIn('id="ext_software_stop" aria-label="Force Stop robot motion"', template)
        self.assertIn('id="ext_software_resume" aria-label="Resume robot motion"', template)
        self.assertIn('class="editor-safety-controls"', template)
        self.assertNotIn('id="run_lvl"', template)
        self.assertIn("$('ext_software_stop').onclick=function(){safetyAction('stop')", extensions)
        self.assertIn("$('ext_software_resume').onclick=function(){safetyAction('resume')", extensions)
        self.assertIn("Ctrl+Shift+Space", extensions)
        self.assertIn("stop:function(){safetyAction('stop',{skipConfirm:true,source:'command-palette'})", extensions)
        self.assertIn("async function toggleMotionSafetyFromKeyboard()", extensions)
        self.assertIn("const action=String(state.run_level||'MOVE').trim().toUpperCase()==='STOP'?'resume':'stop';", extensions)
        self.assertIn("await safetyAction(action,{skipConfirm:action==='stop',source:'keyboard'});", extensions)
        self.assertIn("['Toggle Robot Motion (RUN_LVL)','toggle-motion','Ctrl+Shift+Space']", extensions)
        self.assertIn("'toggle-motion':toggleMotionSafetyFromKeyboard", extensions)
        self.assertIn("if(action==='resume'&&!confirm('Resume motion? Confirm the track is clear and the robot is safe to move.'))return;", extensions)
        self.assertIn("Ruler start marked. Move the pointer to preview distance", extensions)
        self.assertIn("function snapshotRulerPoint(point)", extensions)
        self.assertIn("Object.freeze({space:point.space", extensions)
        self.assertIn("function rulerPointCanvasXY(point,b)", extensions)
        self.assertIn("rulerStart=snapshotRulerPoint(p);rulerHoverPoint=snapshotRulerPoint(p)", extensions)
        self.assertIn("snapshotRulerPoint(point):null", extensions)
        self.assertIn("const a=rulerPointCanvasXY(rulerStart,b),c=rulerPointCanvasXY(rulerHoverPoint,b)", extensions)
        self.assertIn("window.onStreamWorkspaceToolChanged=function(tool)", extensions)
        self.assertIn("window.setStreamWorkspaceTool(editorTool==='pan'?'pan':'select')", extensions)
        self.assertIn("palette-active-indicator", extensions)
        self.assertNotIn("$('ext_roi_rect_tool').onclick", extensions)
        self.assertNotIn("$('ext_roi_trapezoid_tool').onclick", extensions)
        self.assertNotIn("$('ext_roi_top_factor').addEventListener", extensions)
        self.assertNotIn('id="ext_roi_rect_tool"', template)
        self.assertNotIn('id="ext_roi_trapezoid_tool"', template)
        self.assertNotIn('id="ext_roi_top_factor"', template)
        self.assertNotIn("Draw rectangle ROI preview", extensions)
        self.assertNotIn("Draw trapezoid ROI preview", extensions)
        self.assertIn('id="active_tool_banner"', template)
        self.assertIn('id="active_tool_cancel"', template)
        self.assertIn(".active-tool-banner[hidden]", css)
        self.assertIn(".palette-active-indicator{", css)
        self.assertIn("palette-setting-highlight", extensions)
        self.assertIn("window.setStreamDisplayFps(streamFps)", extensions)
        self.assertIn('id="ext_settings_results"', template)
        self.assertIn('id="ext_command_count"', template)
        self.assertIn('id="roi_setting_stream_fps"', template)
        self.assertIn('id="workspace_view_lock"', template)
        self.assertIn('id="workspace_lock_shackle"', template)
        self.assertIn(".view-lock-button.is-locked", css)
        self.assertGreater(template.index('id="workspace_view_lock"'), template.index('data-tool="pan"'))
        self.assertGreater(template.index('id="workspace_zoom_percent"'), template.index('class="workspace-statusbar"'))
        self.assertGreater(template.index('id="ext_open_palette"'), template.index('id="menu_live_status"'))
        self.assertIn("@keyframes paletteSettingFlash", css)
        self.assertIn('id="shortcut_dialog"', template)
        self.assertIn('id="roi_setting_grid_color"', template)
        self.assertIn('id="roi_setting_keyboard_nudge"', template)
        self.assertIn('id="refresh_vals"', template)
        self.assertNotIn('id="apply_all"', template)
        self.assertNotIn('id="download_json"', template)
        self.assertNotIn('class="workspace-actionbar"', template)
        self.assertIn("physical key positions", template)
        self.assertIn(".container.dock-hidden { grid-template-columns:minmax(0,1fr) !important; }", css)
        self.assertIn("#video_canvas.crosshair-active { cursor: crosshair !important; }", css)

    def test_frame_refresh_recovers_from_stalled_requests_and_unrelated_api_failures(self):
        core = (PYTHON_ROOT / "stream" / "static" / "stream-core.js").read_text(encoding="utf-8")
        self.assertIn("const FRAME_REQUEST_TIMEOUT_MS = 8000", core)
        self.assertIn("if(!syncActive || frameRequestInFlight) return;", core)
        self.assertNotIn("if(!syncActive || frameRequestInFlight || !dashboardApiOnline) return;", core)
        self.assertIn("controller.abort()", core)
        self.assertIn("finishFrameRequest(new Error(", core)
        self.assertIn("document.addEventListener('visibilitychange'", core)
        self.assertIn("window.addEventListener('online'", core)

    def test_cursor_readout_keeps_frame_relative_coordinates_outside_frame(self):
        core = (PYTHON_ROOT / "stream" / "static" / "stream-core.js").read_text(encoding="utf-8")
        self.assertIn("function clearCadReadout()", core)
        self.assertIn("canvas.addEventListener('mouseleave',clearCadReadout", core)
        self.assertIn("window.addEventListener('blur',clearCadReadout", core)
        self.assertIn("const u=(p.x-b.ix)/b.iw,v=(p.y-b.iy)/b.ih,outside=u<0||u>1||v<0||v>1", core)
        self.assertIn("readout.x.textContent='X: '+Math.round(u*source.width)+' px'", core)
        self.assertIn("readout.u.textContent='U: '+(u*100).toFixed(1)+' %'", core)
        # BEV control points deliberately keep a wider range than ordinary ROIs.
        self.assertIn("Math.max(-5.0, Math.min(5.0", core)

    def test_workspace_sanitizes_grid_color_and_pixel_nudge_settings(self):
        streamer = WebStreamer(self.make_config())

        clean = streamer._sanitize_workspace({
            "view": {
                "gridColor": "#A1B2C3",
                "keyboardNudgePx": 7,
                "streamFps": 15,
                "viewLocked": True,
            }
        })
        self.assertEqual(clean["view"]["gridColor"], "#a1b2c3")
        self.assertEqual(clean["view"]["keyboardNudgePx"], 7.0)
        self.assertEqual(clean["view"]["streamFps"], 15.0)
        self.assertIs(clean["view"]["viewLocked"], True)

        with self.assertRaises(ValueError):
            streamer._sanitize_workspace({"view": {"gridColor": "steelblue"}})
        with self.assertRaises(ValueError):
            streamer._sanitize_workspace({"view": {"keyboardNudgePx": 101}})
        with self.assertRaises(ValueError):
            streamer._sanitize_workspace({"view": {"streamFps": 31}})
        with self.assertRaises(ValueError):
            streamer._sanitize_workspace({"view": {"viewLocked": "true"}})

    def test_wildcard_bind_discovers_private_lan_address(self):
        from unittest.mock import patch
        import socket
        from stream import _stream_access_urls

        class RouteProbe:
            def connect(self, _target):
                pass

            def getsockname(self):
                return ("192.168.1.42", 49152)

            def close(self):
                pass

        with patch(
            "stream.socket.getaddrinfo",
            return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.42", 0))
            ],
        ), patch("stream.socket.gethostname", return_value="robot"), patch(
            "stream.socket.socket", return_value=RouteProbe()
        ):
            urls = _stream_access_urls("0.0.0.0", 5000)

        self.assertIn("http://127.0.0.1:5000", urls)
        self.assertIn("http://192.168.1.42:5000", urls)

    def test_read_only_cli_flag_disables_dashboard_controls(self):
        from unittest.mock import patch
        from utils.parser import parse_args

        with patch.object(sys, "argv", ["main.py", "--stream-read-only"]):
            args = parse_args()

        self.assertIs(args.stream_control, False)
        self.assertTrue(
            args.stream,
            "--stream-read-only must also start the read-only dashboard",
        )

    def test_stream_control_cli_flags_are_mutually_exclusive(self):
        from unittest.mock import patch
        from utils.parser import parse_args

        with patch.object(
            sys,
            "argv",
            ["main.py", "--stream-control", "--stream-read-only"],
        ), self.assertRaises(SystemExit):
            parse_args()

    def test_stream_control_cli_flag_also_starts_dashboard(self):
        from unittest.mock import patch
        from utils.parser import parse_args

        with patch.object(sys, "argv", ["main.py", "--stream-control"]):
            args = parse_args()

        self.assertTrue(args.stream)
        self.assertIs(args.stream_control, True)

    def test_controls_are_enabled_when_config_allows_updates(self):
        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        streamer = WebStreamer(config)
        client = streamer.app.test_client()

        with patch.object(streamer, "save_conf_to_json"):
            response = client.post(
                "/update_conf",
                json={"RL_TOP_ROI": 0.25},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])
        self.assertEqual(config.RL_TOP_ROI, 0.25)

    def test_read_only_mode_returns_clear_forbidden_message(self):
        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = False
        response = WebStreamer(config).app.test_client().post(
            "/update_conf",
            json={"RL_TOP_ROI": 0.25},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.get_json()["message"],
            "stream control is disabled",
        )

    def test_city_and_race_stream_defaults_are_disabled(self):
        from modes.city import config_city
        from modes.race import config_race

        for config in (config_city, config_race):
            with self.subTest(mode=config.MODE):
                self.assertFalse(config.STREAM)

    def test_city_and_race_defaults_allow_lan_dashboard_controls(self):
        from modes.city import config_city
        from modes.race import config_race

        for config in (config_city, config_race):
            with self.subTest(mode=config.MODE):
                self.assertEqual(config.STREAM_HOST, "0.0.0.0")
                self.assertTrue(config.STREAM_ALLOW_CONTROL)

    def test_mode_endpoint_reports_active_city_detector(self):
        streamer = WebStreamer(self.make_config())
        client = streamer.app.test_client()

        response = client.get("/api/mode")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["mode"], "city")
        self.assertEqual(data["features"]["lane_detector"], "blsf-beta")
        self.assertFalse(data["features"]["bev"])

    def test_mjpeg_endpoint_has_stream_content_type(self):
        config = self.make_config()
        streamer = WebStreamer(config)
        client = streamer.app.test_client()

        response = client.get(
            "/video_feed",
            buffered=False,
        )

        self.assertIn(
            "multipart/x-mixed-replace",
            response.content_type,
        )
        response.close()

    def test_index_page_keeps_javascript_newline_escape_valid(self):
        response = WebStreamer(self.make_config()).app.test_client().get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))
        html = response.get_data(as_text=True)
        self.assertIn("Pause Dashboard Requests", html)
        self.assertIn('id="roi_setting_jpeg_quality"', html)
        self.assertIn("This only changes JPEG encoding for dashboard frames", html)
        self.assertIn('/static/stream-core.js', html)
        self.assertIn('/static/stream-extensions.js', html)
        core = (PYTHON_ROOT / "stream" / "static" / "stream-core.js").read_text(encoding="utf-8")
        extensions = (PYTHON_ROOT / "stream" / "static" / "stream-extensions.js").read_text(encoding="utf-8")
        self.assertIn("refreshStreamJpegQualityFromServer()", extensions)
        self.assertIn("nativeFetch('/api/stream/quality'", extensions)

        # JavaScript was externalized from HTML; validate the served asset.
        self.assertIn(
            r"output.textContent = (j.lines || []).join('\\n');",
            core,
        )
        self.assertNotIn(
            "output.textContent = (j.lines || []).join('\n');",
            core,
        )

    def test_dashboard_polling_uses_backoff_when_server_is_unreachable(self):
        response = WebStreamer(self.make_config()).app.test_client().get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        core = (PYTHON_ROOT / "stream" / "static" / "stream-core.js").read_text(encoding="utf-8")

        self.assertIn('/static/stream-core.js', html)
        self.assertIn("async function fetchDashboardJson", core)
        self.assertIn("dashboardApiRetryAt", core)
        self.assertRegex(core, r"Math\.min\(\s*30000")
        self.assertIn("fetchDashboardJson('/api/health')", core)
        self.assertIn("fault.message", core)
        self.assertIn("details.join(' | ')", core)
        self.assertIn("fetchDashboardJson('/api/arduino-output')", core)
        self.assertIn("fetchDashboardJson('/get_values')", core)
        self.assertIn("let frameRetryAt = 0;", core)
        self.assertIn("if(!syncActive || frameRequestInFlight) return;", core)
        self.assertNotIn("if(!syncActive || frameRequestInFlight || !dashboardApiOnline) return;", core)

    def test_camera_canvas_preserves_source_frame_aspect_ratio(self):
        import re

        response = WebStreamer(self.make_config()).app.test_client().get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        css = (PYTHON_ROOT / "stream" / "static" / "stream.css").read_text(encoding="utf-8")
        core = (PYTHON_ROOT / "stream" / "static" / "stream-core.js").read_text(encoding="utf-8")

        self.assertIn('/static/stream.css', html)
        canvas_css = re.search(r"(?m)^canvas\s*\{([^}]*)\}", css)
        self.assertIsNotNone(canvas_css, "Expected a canvas CSS rule")
        self.assertIn("width: auto;", canvas_css.group(1))
        self.assertIn("height: auto;", canvas_css.group(1))
        self.assertNotIn("aspect-ratio: 3 / 2", canvas_css.group(1))

        # Drawing-buffer dimensions follow the decoded source frame, not the viewport.
        self.assertIn("const frameWidth = img.naturalWidth || img.width;", core)
        self.assertIn("const frameHeight = img.naturalHeight || img.height;", core)
        self.assertNotIn("canvas.width !== dispW", core)
        self.assertNotIn("canvas.height !== dispH", core)

    def test_rendered_inline_javascript_passes_node_syntax_check(self):
        import re
        import shutil
        import subprocess
        import tempfile

        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is not installed; JavaScript syntax check skipped")

        response = WebStreamer(self.make_config()).app.test_client().get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        scripts = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
        self.assertEqual(len(scripts), 1, "Only the JSON bootstrap should remain inline")
        self.assertIn("window.STREAM_BOOTSTRAP", scripts[0])
        self.assertIn('/static/stream-core.js', html)
        self.assertIn('/static/stream-extensions.js', html)
        scripts.extend(
            (PYTHON_ROOT / "stream" / "static" / filename).read_text(encoding="utf-8")
            for filename in ("stream-core.js", "stream-extensions.js")
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            for index, script in enumerate(scripts):
                with self.subTest(javascript_source=index):
                    script_path = Path(tmp_dir) / f"stream-dashboard-{index}.js"
                    script_path.write_text(script, encoding="utf-8")
                    result = subprocess.run(
                        [node, "--check", str(script_path)],
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_full_config_export_contains_all_ui_sections_and_current_mode(self):
        client = WebStreamer(self.make_config()).app.test_client()
        response = client.get("/api/config/full")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["mode"], "city")
        self.assertIn("RL_TOP_ROI", data["values"])
        self.assertIn("LANE_THRESHOLD", data["advanced"])
        self.assertIn("colors", data["ui"])
        self.assertIn("visible", data["ui"])
        self.assertIn("opacity", data["ui"])
        self.assertIn("runtime", data)

    def test_full_config_import_is_read_only_until_controls_are_enabled(self):
        config = self.make_config()
        client = WebStreamer(config).app.test_client()
        payload = {
            "schema_version": 1,
            "mode": "city",
            "values": {"RL_TOP_ROI": 0.25},
            "advanced": {},
            "ui": {},
        }

        response = client.post("/api/config/full", json=payload)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(config.RL_TOP_ROI if hasattr(config, "RL_TOP_ROI") else 0.0, 0.0)

    def test_saving_dashboard_settings_preserves_unrelated_mode_config(self):
        import json
        import tempfile

        config = self.make_config()
        streamer = WebStreamer(config)
        with tempfile.TemporaryDirectory() as tmp_dir, patch("stream.BASE_DIR", tmp_dir):
            filename = Path(tmp_dir) / "city.json"
            original = {
                "SPEED": 220,
                "SIGN_AREA_MIN_PX2": 1234,
                "WITH_SIGN": True,
                "CUSTOM_MODE_SETTING": {"enabled": True},
                "RL_TOP_ROI": 0.2,
            }
            filename.write_text(json.dumps(original), encoding="utf-8")
            config.RL_TOP_ROI = 0.35

            self.assertTrue(streamer.save_conf_to_json())
            saved = json.loads(filename.read_text(encoding="utf-8"))

        self.assertEqual(saved["SPEED"], 220)
        self.assertEqual(saved["SIGN_AREA_MIN_PX2"], 1234)
        self.assertEqual(saved["CUSTOM_MODE_SETTING"], {"enabled": True})
        self.assertEqual(saved["RL_TOP_ROI"], 0.35)

    def test_full_config_round_trip_and_history_are_persisted_atomically(self):
        import tempfile

        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        streamer = WebStreamer(config)
        client = streamer.app.test_client()

        with tempfile.TemporaryDirectory() as tmp_dir, patch("stream.BASE_DIR", tmp_dir):
            exported = client.get("/api/config/full")
            self.assertEqual(exported.status_code, 200)
            payload = exported.get_json()
            payload["values"]["RL_TOP_ROI"] = 0.25

            applied = client.post("/api/config/full", json=payload)
            self.assertEqual(applied.status_code, 200, applied.get_data(as_text=True))
            self.assertTrue(applied.get_json()["success"])
            self.assertEqual(config.RL_TOP_ROI, 0.25)

            history = client.get("/api/config/history")
            self.assertEqual(history.status_code, 200)
            self.assertGreaterEqual(len(history.get_json()["items"]), 1)

    def test_full_config_restore_preserves_active_cli_fps_above_live_edit_limit(self):
        import copy
        import tempfile
        from unittest.mock import Mock

        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        rate = types.SimpleNamespace(
            target_fps=100.0,
            set_target_fps=Mock(),
        )
        config.processing_rate_controller = rate
        config.TARGET_PROCESSING_FPS = 100.0
        client = WebStreamer(config).app.test_client()

        with tempfile.TemporaryDirectory() as tmp_dir, patch("stream.BASE_DIR", tmp_dir):
            original = client.get("/api/config/full").get_json()
            changed = copy.deepcopy(original)
            changed["values"]["RL_TOP_ROI"] = 0.25

            applied = client.post("/api/config/full", json=changed)
            self.assertEqual(applied.status_code, 200, applied.get_data(as_text=True))
            self.assertEqual(config.RL_TOP_ROI, 0.25)

            # This simulates Undo: the previous full snapshot includes the
            # startup target FPS, even though Stream only allows live edits
            # from 1..60. Restoring an unrelated ROI must not try to reset FPS.
            restored = client.post("/api/config/full", json=original)
            self.assertEqual(restored.status_code, 200, restored.get_data(as_text=True))
            self.assertEqual(config.RL_TOP_ROI, original["values"].get("RL_TOP_ROI", 0.0))
            self.assertEqual(rate.target_fps, 100.0)
            rate.set_target_fps.assert_not_called()

    def test_full_config_rejects_out_of_range_fps_import_when_it_would_change_runtime(self):
        import copy
        from unittest.mock import Mock

        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        rate = types.SimpleNamespace(
            target_fps=30.0,
            set_target_fps=Mock(),
        )
        config.processing_rate_controller = rate
        config.TARGET_PROCESSING_FPS = 30.0
        client = WebStreamer(config).app.test_client()

        payload = client.get("/api/config/full").get_json()
        foreign = copy.deepcopy(payload)
        foreign["runtime"]["target_processing_fps"] = 100.0

        response = client.post("/api/config/full", json=foreign)
        self.assertEqual(response.status_code, 400)
        self.assertIn("only be preserved unchanged", response.get_json()["message"])
        rate.set_target_fps.assert_not_called()

    def test_full_config_undo_restores_settings_without_resuming_software_stop(self):
        import copy
        import tempfile

        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        config.RUN_LVL = "MOVE"
        client = WebStreamer(config).app.test_client()

        with tempfile.TemporaryDirectory() as tmp_dir, patch("stream.BASE_DIR", tmp_dir):
            before_stop = client.get("/api/config/full").get_json()
            changed = copy.deepcopy(before_stop)
            changed["values"]["RL_TOP_ROI"] = 0.25
            applied = client.post("/api/config/full", json=changed)
            self.assertEqual(applied.status_code, 200, applied.get_data(as_text=True))

            # Simulate the operator pressing Force Stop after the edit. Undo
            # must restore the ROI but may not clear the safety stop.
            config.RUN_LVL = "STOP"
            restored = client.post("/api/config/full", json=before_stop)
            self.assertEqual(restored.status_code, 200, restored.get_data(as_text=True))
            result = restored.get_json()["config"]
            self.assertEqual(result["values"]["RL_TOP_ROI"], before_stop["values"].get("RL_TOP_ROI", 0.0))
            self.assertEqual(result["advanced"]["RUN_LVL"], "STOP")
            self.assertEqual(config.RUN_LVL, "STOP")

    def test_full_config_rejects_wrong_mode_and_non_finite_roi(self):
        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        client = WebStreamer(config).app.test_client()
        base = {
            "schema_version": 1,
            "mode": "city",
            "values": {},
            "advanced": {},
            "ui": {},
        }

        wrong_mode = dict(base, mode="race")
        response = client.post("/api/config/full", json=wrong_mode)
        self.assertEqual(response.status_code, 400)

        bad_roi = dict(base, values={"RL_TOP_ROI": float("nan")})
        response = client.post("/api/config/full", json=bad_roi)
        self.assertEqual(response.status_code, 400)

    def test_workspace_rejects_out_of_range_annotations_and_saves_profiles(self):
        import tempfile

        client = WebStreamer(self.make_config()).app.test_client()
        with tempfile.TemporaryDirectory() as tmp_dir, patch("stream.BASE_DIR", tmp_dir):
            bad = client.post(
                "/api/workspace",
                json={"action": "save_workspace", "workspace": {
                    "annotations": [{"kind": "marker", "u": 1.5, "v": 0.2}]
                }},
            )
            self.assertEqual(bad.status_code, 400)

            saved = client.post(
                "/api/workspace",
                json={"action": "save_profile", "name": "Night layout",
                      "workspace": {"view": {"zoom": 1.5, "grid": True}}},
            )
            self.assertEqual(saved.status_code, 200, saved.get_data(as_text=True))
            loaded = client.post(
                "/api/workspace",
                json={"action": "load_profile", "name": "Night layout"},
            )
            self.assertEqual(loaded.status_code, 200)
            self.assertEqual(loaded.get_json()["workspace"]["view"]["zoom"], 1.5)

    def test_software_stop_endpoint_is_gated_and_clearly_not_hardware_emergency_stop(self):
        import tempfile

        config = self.make_config()
        client = WebStreamer(config).app.test_client()
        denied = client.post("/api/safety", json={"action": "stop"})
        self.assertEqual(denied.status_code, 403)

        config.STREAM_ALLOW_CONTROL = True
        with tempfile.TemporaryDirectory() as tmp_dir, patch("stream.BASE_DIR", tmp_dir):
            stopped = client.post("/api/safety", json={"action": "stop"})
            self.assertEqual(stopped.status_code, 200)
            self.assertEqual(config.RUN_LVL, "STOP")
            self.assertFalse(stopped.get_json()["hardware_emergency_stop"])

            resumed = client.post("/api/safety", json={"action": "resume"})
            self.assertEqual(resumed.status_code, 200)
            self.assertEqual(config.RUN_LVL, "MOVE")

    def test_sign_request_pause_is_independent_from_run_level_stop(self):
        import tempfile

        class FakeSignWorker:
            def __init__(self):
                self.requests_enabled = True

            def pause_requests(self):
                self.requests_enabled = False

            def resume_requests(self):
                self.requests_enabled = True

            def status(self):
                return {
                    "requests_enabled": self.requests_enabled,
                    "worker_alive": True,
                    "queue_depth": 0,
                    "inference_in_flight": False,
                }

        config = self.make_config()
        worker = FakeSignWorker()
        config.runtime_robot = types.SimpleNamespace(sign_detector=worker)
        client = WebStreamer(config).app.test_client()

        denied = client.post("/api/sign-requests", json={"action": "pause"})
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(getattr(config, "RUN_LVL", "MOVE"), "MOVE")
        self.assertTrue(worker.requests_enabled)

        config.STREAM_ALLOW_CONTROL = True
        with tempfile.TemporaryDirectory() as tmp_dir, patch("stream.BASE_DIR", tmp_dir):
            paused = client.post("/api/sign-requests", json={"action": "pause"})
            self.assertEqual(paused.status_code, 200, paused.get_data(as_text=True))
            self.assertFalse(worker.requests_enabled)
            self.assertEqual(paused.get_json()["run_level"], "MOVE")
            self.assertFalse(paused.get_json()["motion_state_changed"])
            self.assertEqual(getattr(config, "RUN_LVL", "MOVE"), "MOVE")

            stopped = client.post("/api/safety", json={"action": "stop"})
            self.assertEqual(stopped.status_code, 200, stopped.get_data(as_text=True))
            self.assertEqual(config.RUN_LVL, "STOP")
            self.assertFalse(worker.requests_enabled)

            resumed_requests = client.post(
                "/api/sign-requests", json={"action": "resume"}
            )
            self.assertEqual(resumed_requests.status_code, 200)
            self.assertTrue(worker.requests_enabled)
            self.assertEqual(config.RUN_LVL, "STOP")

            resumed_motion = client.post("/api/safety", json={"action": "resume"})
            self.assertEqual(resumed_motion.status_code, 200)
            self.assertEqual(config.RUN_LVL, "MOVE")
            self.assertTrue(worker.requests_enabled)

    def test_server_log_endpoint_redacts_bearer_credentials(self):
        import logging

        config = self.make_config()
        client = WebStreamer(config).app.test_client()
        secret = "super-secret-token-123"
        logging.getLogger("stream.redaction_test").warning(
            "Authorization: Bearer %s", secret
        )

        response = client.get("/api/logs?level=WARNING&q=authorization&limit=10")

        self.assertEqual(response.status_code, 200)
        serialized = response.get_data(as_text=True)
        self.assertNotIn(secret, serialized)
        self.assertIn("[REDACTED]", serialized)

    def test_config_restore_preserves_software_stop_but_advanced_edit_cannot_resume(self):
        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        config.RUN_LVL = "STOP"
        client = WebStreamer(config).app.test_client()

        payload = client.get("/api/config/full").get_json()
        payload["advanced"]["RUN_LVL"] = "MOVE"
        imported = client.post("/api/config/full", json=payload)
        self.assertEqual(imported.status_code, 200, imported.get_data(as_text=True))
        self.assertEqual(imported.get_json()["config"]["advanced"]["RUN_LVL"], "STOP")
        self.assertEqual(config.RUN_LVL, "STOP")

        edited = client.post("/set_advanced", json={"RUN_LVL": "MOVE"})
        self.assertEqual(edited.status_code, 409)
        self.assertEqual(config.RUN_LVL, "STOP")

        # Only the dedicated software-safety action may explicitly resume motion.
        resumed = client.post("/api/safety", json={"action": "resume"})
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(config.RUN_LVL, "MOVE")

    def test_roi_batch_validation_does_not_apply_a_partial_update(self):
        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        config.RL_TOP_ROI = 0.15
        config.RL_BOTTOM_ROI = 0.85
        response = WebStreamer(config).app.test_client().post(
            "/update_conf",
            json={"RL_TOP_ROI": 0.25, "RL_BOTTOM_ROI": "not-a-number"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(config.RL_TOP_ROI, 0.15)
        self.assertEqual(config.RL_BOTTOM_ROI, 0.85)

    def test_advanced_batch_rolls_back_when_a_later_value_is_invalid(self):
        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        config.LANE_THRESHOLD = 125
        config.WITH_SIGN = False
        config.WITH_APRILTAG = False
        response = WebStreamer(config).app.test_client().post(
            "/set_advanced",
            json={"LANE_THRESHOLD": 160, "WITH_SIGN": True, "WITH_APRILTAG": True},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(config.LANE_THRESHOLD, 125)
        self.assertFalse(config.WITH_SIGN)
        self.assertFalse(config.WITH_APRILTAG)

    def test_live_feature_rolls_back_when_config_persistence_fails(self):
        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        streamer = WebStreamer(config)
        client = streamer.app.test_client()

        with patch.object(streamer, "save_conf_to_json", return_value=False):
            response = client.post(
                "/api/features",
                json={"feature": "DETECT_OBJECT", "value": True},
            )

        self.assertEqual(response.status_code, 500)
        self.assertFalse(getattr(config, "DETECT_OBJECT", False))

    def test_layer_settings_roll_back_when_atomic_persistence_fails(self):
        import json

        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        streamer = WebStreamer(config)
        client = streamer.app.test_client()
        before = json.loads(json.dumps(streamer.ui_settings))

        with patch.object(streamer, "save_ui_settings", return_value=False):
            response = client.post("/set_ui", json={"visible": {"RL": False}})

        self.assertEqual(response.status_code, 500)
        self.assertEqual(streamer.ui_settings, before)

    def test_software_stop_is_retained_when_persistence_fails(self):
        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        streamer = WebStreamer(config)
        client = streamer.app.test_client()

        with patch.object(streamer, "save_conf_to_json", return_value=False):
            stopped = client.post("/api/safety", json={"action": "stop"})
            self.assertEqual(stopped.status_code, 500)
            self.assertEqual(config.RUN_LVL, "STOP")
            self.assertTrue(stopped.get_json()["software_stop_active"])

            resumed = client.post("/api/safety", json={"action": "resume"})
            self.assertEqual(resumed.status_code, 500)
            self.assertEqual(config.RUN_LVL, "STOP")
            self.assertTrue(resumed.get_json()["software_stop_active"])

    def test_camera_api_exposes_sensor_ranges_and_rejects_out_of_range_controls(self):
        import tempfile

        class FakePicam:
            camera_controls = {
                "ExposureTime": (100, 100000, 10000),
                "AnalogueGain": (1.0, 16.0, 6.0),
                "AeEnable": (False, True, False),
                "AwbEnable": (False, True, False),
            }

            def __init__(self):
                self.applied = []

            def set_controls(self, controls):
                self.applied.append(dict(controls))

        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        picam = FakePicam()
        config.camera = types.SimpleNamespace(
            pi_mode=True,
            picam=picam,
            _dashboard_image_controls={
                "ExposureTime": 10000,
                "AnalogueGain": 6.0,
                "AeEnable": False,
                "AwbEnable": False,
            },
            requested_frame_rate=30,
            measured_frame_rate=29,
        )
        streamer = WebStreamer(config)
        client = streamer.app.test_client()

        with tempfile.TemporaryDirectory() as tmp_dir, patch("stream.BASE_DIR", tmp_dir):
            status = client.get("/api/camera/settings")
            self.assertEqual(status.status_code, 200)
            camera = status.get_json()["camera"]
            self.assertEqual(camera["control_ranges"]["ExposureTime"], {"min": 100.0, "max": 100000.0})
            self.assertEqual(camera["control_ranges"]["AnalogueGain"], {"min": 1.0, "max": 16.0})

            invalid = client.post("/api/camera/settings", json={"ExposureTime": 100001})
            self.assertEqual(invalid.status_code, 400)
            self.assertEqual(picam.applied, [])

            valid = client.post("/api/camera/settings", json={"ExposureTime": 20000})
            self.assertEqual(valid.status_code, 200)
            self.assertEqual(picam.applied, [{"ExposureTime": 20000}])

    def test_camera_and_processing_rate_report_unavailable_capabilities_cleanly(self):
        streamer = WebStreamer(self.make_config())
        client = streamer.app.test_client()

        camera = client.get("/api/camera/settings")
        self.assertEqual(camera.status_code, 200)
        self.assertFalse(camera.get_json()["camera"]["available"])

        rate = client.get("/api/processing-rate")
        self.assertEqual(rate.status_code, 200)
        self.assertFalse(rate.get_json()["available"])

        config = streamer.config
        config.STREAM_ALLOW_CONTROL = True
        denied = client.post("/api/processing-rate", json={"target_fps": 25})
        self.assertEqual(denied.status_code, 409)

    def test_config_preset_can_be_queried_for_comparison(self):
        import tempfile

        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        client = WebStreamer(config).app.test_client()
        with tempfile.TemporaryDirectory() as tmp_dir, patch("stream.BASE_DIR", tmp_dir):
            saved = client.post("/api/config/presets", json={"action": "save", "name": "Stable"})
            self.assertEqual(saved.status_code, 200, saved.get_data(as_text=True))
            queried = client.get("/api/config/presets?name=Stable")
            self.assertEqual(queried.status_code, 200)
            self.assertIn("config", queried.get_json())

    def test_workspace_migrates_legacy_visual_custom_roi_annotations(self):
        import tempfile

        client = WebStreamer(self.make_config()).app.test_client()
        with tempfile.TemporaryDirectory() as tmp_dir, patch("stream.BASE_DIR", tmp_dir):
            migrated = client.post(
                "/api/workspace",
                json={"action": "save_workspace", "workspace": {
                    "view": {"tool": "roi_trapezoid", "rightPaneWidth": 380},
                    "annotations": [
                        {
                            "kind": "roi_trapezoid", "x": 0.1, "y": 0.2,
                            "w": 0.5, "h": 0.4, "topFactor": 0.45,
                            "label": "Legacy preview-only region"
                        },
                        {"kind": "marker", "u": 0.25, "v": 0.35, "label": "Keep this note"},
                    ],
                }},
            )
            self.assertEqual(migrated.status_code, 200, migrated.get_data(as_text=True))
            workspace = migrated.get_json()["workspace"]
            self.assertEqual(workspace["view"]["tool"], "select")
            self.assertEqual(workspace["view"]["rightPaneWidth"], 380.0)
            self.assertEqual(workspace["annotations"], [
                {"kind": "marker", "u": 0.25, "v": 0.35, "label": "Keep this note"}
            ])

            unsupported = client.post(
                "/api/workspace",
                json={"action": "save_workspace", "workspace": {
                    "annotations": [{"kind": "unknown-tool", "u": 0.1, "v": 0.2}],
                }},
            )
            self.assertEqual(unsupported.status_code, 400)

    def test_live_feature_controls_are_gated_and_persisted(self):
        import tempfile

        config = self.make_config()
        config.apply_marker_mode = lambda mode: (
            setattr(config, "WITH_SIGN", mode == "sign"),
            setattr(config, "WITH_APRILTAG", mode == "apriltag"),
            setattr(config, "USE_SIGN", mode == "sign"),
        )
        client = WebStreamer(config).app.test_client()

        before = client.get("/api/features")
        self.assertEqual(before.status_code, 200)
        self.assertFalse(before.get_json()["controls_enabled"])

        config.STREAM_ALLOW_CONTROL = True
        with tempfile.TemporaryDirectory() as tmp_dir, patch("stream.BASE_DIR", tmp_dir):
            enabled = client.post(
                "/api/features",
                json={"feature": "DETECT_OBJECT", "value": True},
            )
            self.assertEqual(enabled.status_code, 200, enabled.get_data(as_text=True))
            self.assertTrue(config.DETECT_OBJECT)
            exported = client.get("/api/config/full").get_json()
            self.assertTrue(exported["advanced"]["DETECT_OBJECT"])

            marker = client.post(
                "/api/features",
                json={"feature": "marker_mode", "value": "apriltag"},
            )
            self.assertEqual(marker.status_code, 200, marker.get_data(as_text=True))
            self.assertTrue(config.WITH_APRILTAG)
            self.assertFalse(config.WITH_SIGN)

            startup_only = client.post(
                "/api/features",
                json={"feature": "TRAFFIC_LIGHTS_ENABLED", "value": True},
            )
            self.assertEqual(startup_only.status_code, 400)

    def test_atomic_state_write_retries_transient_windows_permission_error(self):
        import json
        import os
        import tempfile

        from stream import WebStreamer

        original_replace = os.replace
        replace_attempts = []

        def fail_once(source, destination):
            replace_attempts.append((source, destination))
            if len(replace_attempts) == 1:
                raise PermissionError(5, "Access is denied", destination)
            return original_replace(source, destination)

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = str(Path(tmp_dir) / "race_config_history.json")
            with patch("stream.os.replace", side_effect=fail_once), patch(
                "stream.time.sleep"
            ) as sleep:
                WebStreamer._write_json_atomic(path, {"version": 1, "items": []})

            self.assertEqual(len(replace_attempts), 2)
            sleep.assert_called_once()
            with open(path, "r", encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), {"version": 1, "items": []})

    def test_concurrent_history_records_do_not_overwrite_each_other(self):
        import json
        import tempfile
        from concurrent.futures import ThreadPoolExecutor

        config = self.make_config()
        streamer = WebStreamer(config)

        with tempfile.TemporaryDirectory() as tmp_dir, patch("stream.BASE_DIR", tmp_dir):
            labels = [f"parallel-{index}" for index in range(24)]

            def record(index):
                streamer._record_config_history(labels[index], {"sequence": index})

            with ThreadPoolExecutor(max_workers=8) as executor:
                list(executor.map(record, range(len(labels))))

            history_path = Path(tmp_dir) / "city_config_history.json"
            with history_path.open("r", encoding="utf-8") as handle:
                history = json.load(handle)

        stored_labels = {item["label"] for item in history["items"]}
        self.assertEqual(stored_labels, set(labels))

    def test_video_frame_endpoint_does_not_cache_live_frames(self):
        config = self.make_config()
        config.debug_frames_list = []
        config.stream_frame_seq = 0
        streamer = WebStreamer(config)
        client = streamer.app.test_client()

        publish_debug_frame(
            config,
            np.zeros((32, 48, 3), dtype=np.uint8),
        )
        first = client.get("/video_feed_frame")

        publish_debug_frame(
            config,
            np.full((32, 48, 3), 255, dtype=np.uint8),
        )
        second = client.get("/video_feed_frame")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(first.data, second.data)
        self.assertEqual(second.headers["X-Stream-Frame-Sequence"], "2")
        self.assertIn("no-store", second.headers["Cache-Control"])

    def test_missing_video_frame_is_retryable_and_not_cacheable(self):
        config = self.make_config()
        config.debug_frames_list = []
        config.stream_frame_seq = 0
        response = WebStreamer(config).app.test_client().get(
            "/video_feed_frame"
        )

        self.assertEqual(response.status_code, 204)
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_camera_fallback_publishes_a_preview_before_debug_overlay_exists(self):
        import cv2

        config = self.make_config()
        config.debug_frames_list = []
        config.stream_frame_seq = 0
        config.stream_frame_timestamps = []
        camera_frame = np.empty((24, 36, 3), dtype=np.uint8)
        camera_frame[:] = (17, 73, 129)

        # A fresh annotated frame is preferred, but the first valid camera
        # frame must be visible even before debug overlay generation finishes.
        self.assertTrue(publish_camera_frame_fallback(config, camera_frame))
        self.assertEqual(config.stream_frame_seq, 1)

        response = WebStreamer(config).app.test_client().get("/video_feed_frame")
        self.assertEqual(response.status_code, 200)
        decoded = cv2.imdecode(
            np.frombuffer(response.data, dtype=np.uint8), cv2.IMREAD_COLOR
        )
        self.assertIsNotNone(decoded)
        self.assertLessEqual(
            int(np.max(np.abs(decoded[0, 0].astype(np.int16) - np.array([17, 73, 129])))),
            2,
        )

    def test_camera_fallback_does_not_replace_a_fresh_debug_frame(self):
        config = self.make_config()
        config.debug_frames_list = []
        config.stream_frame_seq = 0
        config.stream_frame_timestamps = []
        debug_frame = np.full((20, 30, 3), 211, dtype=np.uint8)
        publish_debug_frame(config, debug_frame)
        original_sequence = config.stream_frame_seq

        camera_frame = np.zeros((20, 30, 3), dtype=np.uint8)
        self.assertFalse(publish_camera_frame_fallback(config, camera_frame))
        self.assertEqual(config.stream_frame_seq, original_sequence)
        np.testing.assert_array_equal(config.debug_frames_list[-1][0, 0], [211, 211, 211])

    def test_frozen_frame_reuses_jpeg_cache_while_live_stream_advances(self):
        import cv2

        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        config.debug_frames_list = [np.zeros((32, 48, 3), dtype=np.uint8)]
        config.stream_frame_seq = 1
        streamer = WebStreamer(config)
        client = streamer.app.test_client()

        with patch("stream.media_api.cv2.imencode", wraps=cv2.imencode) as encode:
            frozen = client.post("/freeze_frame")
            self.assertEqual(frozen.status_code, 200)
            first = client.get("/video_feed_frame")
            self.assertEqual(first.status_code, 200)
            self.assertTrue(first.headers["X-Stream-Frame-Sequence"].startswith("frozen-"))

            # Advancing live sequence numbers must not invalidate the frozen image.
            publish_debug_frame(config, np.full((32, 48, 3), 255, dtype=np.uint8))
            second = client.get("/video_feed_frame")
            self.assertEqual(second.status_code, 200)
            self.assertEqual(first.data, second.data)
            self.assertEqual(encode.call_count, 1)

            resumed = client.post("/unfreeze_frame")
            self.assertEqual(resumed.status_code, 200)
            live = client.get("/video_feed_frame")
            self.assertEqual(live.status_code, 200)
            self.assertNotEqual(first.data, live.data)
            self.assertEqual(encode.call_count, 2)

    def test_stream_jpeg_quality_api_updates_cached_and_live_encoders(self):
        import cv2

        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = True
        streamer = WebStreamer(config)
        client = streamer.app.test_client()

        initial = client.get("/api/stream/quality")
        self.assertEqual(initial.status_code, 200)
        self.assertEqual(initial.get_json()["quality"], 85)
        self.assertTrue(initial.get_json()["runtime_only"])

        with patch("stream.media_api.cv2.imencode", wraps=cv2.imencode) as encode:
            first = client.get("/video_feed_frame")
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first.headers["X-Stream-JPEG-Quality"], "85")

            changed = client.post("/api/stream/quality", json={"quality": 60})
            self.assertEqual(changed.status_code, 200)
            self.assertEqual(changed.get_json()["quality"], 60)
            self.assertEqual(config.STREAM_JPEG_QUALITY, 60)

            # Same source frame ID: changing quality must invalidate cached JPEG.
            second = client.get("/video_feed_frame")
            self.assertEqual(second.status_code, 200)
            self.assertEqual(second.headers["X-Stream-JPEG-Quality"], "60")
            self.assertEqual(encode.call_count, 2)
            self.assertEqual(
                encode.call_args_list[0].args[2],
                [cv2.IMWRITE_JPEG_QUALITY, 85],
            )
            self.assertEqual(
                encode.call_args_list[1].args[2],
                [cv2.IMWRITE_JPEG_QUALITY, 60],
            )

        self.assertEqual(client.get("/api/stream/quality").get_json()["quality"], 60)
        invalid = client.post("/api/stream/quality", json={"quality": 101})
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(config.STREAM_JPEG_QUALITY, 60)

    def test_stream_jpeg_quality_mutation_respects_read_only_mode(self):
        config = self.make_config()
        config.STREAM_ALLOW_CONTROL = False
        client = WebStreamer(config).app.test_client()

        self.assertEqual(client.get("/api/stream/quality").status_code, 200)
        denied = client.post("/api/stream/quality", json={"quality": 50})
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(getattr(config, "STREAM_JPEG_QUALITY", 85), 85)

    def test_mjpeg_encoder_uses_active_jpeg_quality(self):
        import cv2

        config = self.make_config()
        config.STREAM_JPEG_QUALITY = 45
        streamer = WebStreamer(config)
        client = streamer.app.test_client()

        with patch("stream.media_api.cv2.imencode", wraps=cv2.imencode) as encode:
            response = client.get("/video_feed", buffered=False)
            try:
                next(iter(response.response))
            finally:
                response.close()

        self.assertGreaterEqual(encode.call_count, 1)
        self.assertEqual(
            encode.call_args_list[0].args[2],
            [cv2.IMWRITE_JPEG_QUALITY, 45],
        )

    def test_dashboard_request_pause_is_distinct_from_robot_stop(self):
        stream_dir = PYTHON_ROOT / "stream"
        core = (stream_dir / "static" / "stream-core.js").read_text(encoding="utf-8")
        template = (stream_dir / "templates" / "stream.html").read_text(encoding="utf-8")
        self.assertIn("Pause Dashboard Requests", template)
        self.assertIn("Resume Dashboard Requests", core)
        self.assertIn("clearInterval(fetchFrameTimer)", core)
        self.assertIn("Dashboard polling paused; robot motion is unchanged", core)
        self.assertIn("window.setStreamExtensionPollingEnabled(false)", core)
        self.assertIn("window.setStreamExtensionPollingEnabled(true)", core)
        extensions = (stream_dir / "static" / "stream-extensions.js").read_text(encoding="utf-8")
        self.assertIn("clearInterval(extHealthTimer)", extensions)
        self.assertIn("clearInterval(extSettingsTimer)", extensions)
        self.assertIn("extSettingsTimer=setInterval", extensions)
        self.assertIn("if(extensionPollingEnabled){", extensions)
        # The polling button must never send a RUN_LVL/safety mutation.
        stop_handler = core.split("Pause Dashboard Requests Logic", 1)[1].split(
            "Advanced API Sync", 1
        )[0]
        self.assertNotIn("/api/safety", stop_handler)
        self.assertIn("RUN_LVL", template)
        self.assertIn("does not stop the robot or change RUN_LVL", template)


    def test_manual_controller_angle_limit_accepts_numeric_entry(self):
        manual_ui = (PYTHON_ROOT / "test" / "test_manual_control.py").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            'id="angle_limit_number" class="angle-limit-number" type="number" min="10" max="90"',
            manual_ui,
        )
        self.assertIn("angleLimitSlider.value=String(value)", manual_ui)
        self.assertIn(
            "angleLimitNumber.addEventListener('change',()=>syncAngleLimitNumber(true))",
            manual_ui,
        )
        self.assertIn(
            "socket.emit('set_setting',{key:'angle_limit_deg',value:value})",
            manual_ui,
        )
        self.assertIn(
            "document.activeElement.id !== 'angle_limit_number'",
            manual_ui,
        )



    def test_python_log_console_uses_runtime_logs_and_has_a_dedicated_tab(self):
        import stream
        import time

        entry = {
            "timestamp": time.time(),
            "level": "ERROR",
            "logger": "modes.race.race",
            "message": "unit-python-log-console-regression",
        }
        with stream._STREAM_LOG_LOCK:
            stream._STREAM_LOGS.append(entry)
        try:
            response = WebStreamer(self.make_config()).app.test_client().get(
                "/api/logs?limit=20&q=unit-python-log-console-regression"
            )
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(any(
                item.get("message") == entry["message"]
                for item in payload.get("items", [])
            ))
        finally:
            with stream._STREAM_LOG_LOCK:
                try:
                    stream._STREAM_LOGS.remove(entry)
                except ValueError:
                    pass

        stream_dir = PYTHON_ROOT / "stream"
        template = (stream_dir / "templates" / "stream.html").read_text(encoding="utf-8")
        core = (stream_dir / "static" / "stream-core.js").read_text(encoding="utf-8")
        css = (stream_dir / "static" / "stream.css").read_text(encoding="utf-8")
        self.assertIn('data-console-tab="python"', template)
        self.assertIn('id="console_python"', template)
        self.assertIn("fetch('/api/logs?limit=200'", core)
        self.assertIn("workspacePythonLogs", core)
        self.assertIn("console_python').hidden=consoleTab!=='python'", core)
        self.assertIn('id="settings_drawer_backdrop"', template)
        self.assertIn("left: max(4px, env(safe-area-inset-left, 0px))", css)
        self.assertIn("Mobile polish: a true left-side settings drawer", css)
        extensions = (stream_dir / "static" / "stream-extensions.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("['events','api','python'].forEach(renderWorkspaceEventLog)", extensions)
        self.assertIn("python_logs:workspacePythonLogs", extensions)

    def test_ctrl_c_interrupted_shared_camera_wait_is_not_marked_as_runtime_fault(self):
        race_source = (
            PYTHON_ROOT / "modes" / "race" / "race.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "isinstance(e, InterruptedError) and self._shutdown_requested()",
            race_source,
        )
        self.assertIn(
            "exiting Race loop cleanly",
            race_source,
        )
        city_source = (
            PYTHON_ROOT / "modes" / "city" / "city.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "isinstance(e, InterruptedError) and self._shutdown_requested()",
            city_source,
        )
        self.assertIn(
            "exiting City loop cleanly",
            city_source,
        )
        stream_source = (PYTHON_ROOT / "stream" / "__init__.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "Stream dashboard closed; HTTP server socket released",
            stream_source,
        )


    def test_toolbar_active_state_tooltips_and_view_permissions_stay_in_sync(self):
        stream_dir = PYTHON_ROOT / "stream"
        core = (stream_dir / "static" / "stream-core.js").read_text(encoding="utf-8")
        extensions = (stream_dir / "static" / "stream-extensions.js").read_text(encoding="utf-8")
        template = (stream_dir / "templates" / "stream.html").read_text(encoding="utf-8")
        css = (stream_dir / "static" / "stream.css").read_text(encoding="utf-8")

        # The same toolbar pressed-state styling is used by Pan/Select and Console.
        self.assertIn("toolButton.setAttribute('aria-pressed',String(visible))", core)
        self.assertIn('.tool-button[aria-pressed="true"]', css)
        self.assertIn("button.removeAttribute('title')", core)
        self.assertIn("button.querySelector('.tool-tip')", core)
        self.assertIn("window.syncStreamOverlayControlUI=syncOverlayControlUI", core)
        self.assertIn("window.syncStreamOverlayControlUI()", extensions)
        self.assertIn("view.viewLocked===true", extensions)
        self.assertNotIn("lane_center_guide", core)

        # No "Live" banner is left below the canvas; frozen/paused states remain.
        self.assertNotIn("Camera frame: Live", core)
        self.assertIn("frameModeDisplay.hidden = !paused && !isFrozen", core)
        self.assertIn("Frozen frame · precise tuning", core)

        # Login and write permission are separate: readonly mode disables writes
        # immediately while keeping visual inspection controls available.
        self.assertIn("syncStreamPermissionUI();", core)
        self.assertIn("document.documentElement.dataset.streamControlPermission=permission", core)
        self.assertIn("'show_rects'", core)
        self.assertIn("'ext_overlays'", core)
        self.assertIn("Read-only dashboard: runtime/configuration changes are disabled", core)
        toolbar = template.split('<aside class="left-toolbar"', 1)[1].split("</aside>", 1)[0]
        self.assertNotIn("title=", toolbar)
        self.assertIn('aria-label="Show ROI overlays"', toolbar)
        self.assertIn('aria-label="Open Event Console" aria-pressed="false"', toolbar)
        self.assertIn('id="frame_mode" class="small status-line" hidden></div>', template)


    def test_header_controls_stay_left_while_panel_toggle_is_pinned_right(self):
        stream_dir = PYTHON_ROOT / "stream"
        template = (stream_dir / "templates" / "stream.html").read_text(
            encoding="utf-8"
        )
        css = (stream_dir / "static" / "stream.css").read_text(
            encoding="utf-8"
        )

        header_start = template.index('<div class="controls editor-controls"')
        header_end = template.index('<div class="workspace-main">', header_start)
        header = template[header_start:header_end]
        left_group = header.index('class="editor-controls-left"')
        right_group = header.index('class="editor-controls-right"')
        self.assertLess(left_group, right_group)
        self.assertLess(
            header.index('id="variable_select"'),
            header.index('id="toggle_dock_btn"'),
        )
        self.assertIn('class="editor-control-group editor-selection-group"', header)
        self.assertIn('class="editor-control-group editor-view-group"', header)
        self.assertIn('class="editor-control-group editor-settings-group"', header)
        self.assertEqual(header.count('class="editor-control-divider"'), 2)
        self.assertIn('role="separator" aria-orientation="vertical"', header)
        self.assertIn(".editor-controls > .editor-controls-left", css)
        self.assertIn(".editor-controls > .editor-controls-right", css)
        self.assertIn("border-left: 1px solid #344457", css)
        self.assertIn("@media (max-width: 720px)", css)
        self.assertIn("flex: 1 1 0 !important;", css)

if __name__ == "__main__":
    unittest.main()
