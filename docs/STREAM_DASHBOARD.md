# Stream Dashboard

## Start and access

Start the optional web workspace alongside a physical mode or simulator mode:

```bash
python python/main.py --mode city --stream
# Open the URL printed by the runtime, normally http://<robot-ip>:5000
```

The Stream server is opt-in. The bind host and port are configurable; the default bind address is `0.0.0.0`, which listens on all network interfaces. Use the printed local/LAN address from another device, not `0.0.0.0` as a browser destination.

The Stream server does not own the camera or replace the mode's control loop. It displays the latest published frame and exposes selected runtime state and controls through its API.

## Main implementation areas

| Path | Responsibility |
|---|---|
| `python/stream/__init__.py` | Flask application, server lifecycle, frame/telemetry access and main route registration. |
| `python/stream/template.py` | Main workspace HTML template. |
| `python/stream/templates/` | Dedicated editor and feature templates, including simulator editor views. |
| `python/stream/capabilities.py` | Mode-aware UI/API capabilities. |
| `python/stream/auth_api.py` | Optional login/logout routes, authentication checks and response headers. |
| `python/stream/` API modules | Feature-specific configuration, simulator, camera and runtime endpoints. |

Check the active route-registration code before adding a new endpoint or assuming that a UI control is available in every mode.

## Workspace capabilities

The current workspace includes a CAD-style operational canvas and property editors, mode-specific configuration JSON import/export, presets and configuration history, undo/redo, runtime health/performance details, Arduino telemetry, sign-worker status, confidence and obstacle diagnostics, optional encoder mapping, frame snapshots/comparison, console filtering/export, log search, workspace profiles and a command palette.

The feature set is mode-aware. CARLA provides simulator-specific scene, vehicle, spawn and camera controls; AVIS exposes native distance-sensor configuration and controls supported by its adapter. Use read-only mode when inspecting a run without allowing dashboard configuration mutations.

## Runtime controls versus browser controls

These operations are distinct:

- The workspace **STOP** action requests a software run-level stop through the active Python mode loop. It is not a hardware emergency stop.
- **Resume** is confirmation-gated in the UI.
- **Pause Dashboard Requests** pauses browser polling for frames, configuration, health, Arduino and extension status. It does not pause the control loop and does not change the robot's run level.
- **File → Exit · Stop Stream Server** shuts down the Stream HTTP server and serving thread. It does not stop the City/Race runtime loop or independently command the robot to stop.

Always use the appropriate robot/firmware stop path for a physical safety condition.

## Access control and network exposure

The default bind address can expose the dashboard to other devices on the reachable network. Use a trusted network, a restrictive firewall and the optional login support documented in the [Python runtime guide](../python/README.md). Do not expose a control-enabled dashboard directly to the public internet.

If you need monitoring without mutation endpoints, start the runtime with:

```bash
python python/main.py --mode race --stream --stream-read-only
```

To inspect HTTP request/access logs while troubleshooting browser polling, add `--stream-request-logs`. Those access logs are disabled by default to reduce console I/O; this does not suppress application errors or warnings.

The camera-calibration web service is a separate service from the runtime Stream server. Its capture, clear, FPS-control and calibration endpoints can change camera state and do not have built-in authentication; keep it on a trusted network as described in the Python README.

## Troubleshooting

**Black or stale camera view:** confirm camera initialization and the runtime camera FPS/frame age; check the browser's frame endpoint and server logs; verify dimensions and JPEG encoding; and ensure the mode loop has started publishing frames.

**Controls or editor fields unavailable:** inspect `python/stream/capabilities.py` and the active mode's capability metadata. A visible control may be disabled for a backend that does not implement it.

**Configuration rejected:** check the server response, field range and mode-specific restrictions. Simulator settings should be written to the simulator profile, not to `city.json` or `race.json`.

**Excessive console output:** enable request logs only for a debugging session, and use the normal `--log-level` setting to control application severity.
