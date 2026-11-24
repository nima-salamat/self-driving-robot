# Simulator Modes: CARLA and AVIS Engine

## Supported modes

The mode registry exposes three simulator modes. They reuse the selected City/Race perception profile through a separate simulator runtime; they do not start the physical camera or Arduino serial controller.

| Mode | Adapter | Perception profile | Native measurements |
|---|---|---|---|
| `carla` | CARLA | City | RGB camera, optional ray-cast LiDAR, simulator speed/location |
| `avis` | AVIS Engine | City | Camera and native distance readings |
| `avis-race` | AVIS Engine | Race | Camera and native distance readings |

The registry is in `python/modes/registry.py`; the normalized interface is in `python/modes/simulation/base_adapter.py`; the common loop is in `python/modes/simulation/runtime.py`.

## Install and launch

Install the base dependencies and optional simulator extras from the repository root:

```bash
python -m pip install -r requirements.txt
python -m pip install -r requirements-simulators.txt
```

Start the CARLA server or AVIS Engine separately, then launch the matching client mode:

```bash
python python/main.py --mode carla --stream --stream-control
python python/main.py --mode avis --stream --stream-control
python python/main.py --mode avis-race --stream --stream-control
```

Default endpoints are CARLA `127.0.0.1:2000` and AVIS Engine `127.0.0.1:25001`. Use `--simulator-host` and `--simulator-port` to override the endpoint; use `--simulator-timeout` for the backend's connection/request timeout. Check `python python/main.py --help` for the full set of simulator options.

CARLA's optional Python wheel is pinned in `requirements-simulators.txt` for common x86-64 CPython 3.10–3.12 environments. If the current operating system or Python version is outside that marker, install a compatible wheel from the matching CARLA distribution. AVIS support uses the bundled `python/avisengine.py` and `python/avisengine_utils.py` client; it is not an independently published pip package in this project.

## Adapter and control contract

Every adapter normalizes its backend into a `SensorFrame` containing an image, capture timestamp and sequence, optional speed, range dictionary, and optional backend-specific location/yaw/LiDAR data. The runtime passes perception output to `VirtualVehicleController`, which creates a `VehicleCommand` with normalized steering, throttle and brake values.

The virtual controller maps the configured servo minimum/center/maximum into a normalized steering range. It applies the configured inversion and speed/throttle policy. By default, an unavailable lane estimate can trigger simulator braking; verify `SIMULATOR_STOP_ON_LOST_LANE` and the selected profile before a run.

CARLA is **disarmed on every launch**. The vehicle is commanded to brake after connection and does not receive autonomous throttle until the user presses **Start Run** in the simulator Stream. **Stop / Brake** disarms it immediately. Opening the camera placement studio or changing the CARLA scene also disarms the run; closing an editor does not re-enable motion. Press Start Run again when the scene and camera are ready. This explicit run gate applies to CARLA; AVIS retains its existing run behavior.

CARLA's conservative starting values are 5 km/h target speed, 0.12 throttle, 0.28 steering authority, 0.8 normalized steering units/second, and 0.12 throttle rise/second. These are starting values, not permanent UI caps. The editor/API allow target speed 0–200 km/h, throttle 0–1, steering authority 0.05–1, steering rate 0.1–10, and throttle rise 0.01–1. The controller and adapter both enforce those normalized physical ranges while preserving the configured values. Older profiles are migrated once: legacy values above the former tuning envelope are reduced to conservative defaults and the profile is marked version 2; new saves are not clamped again on later restarts. Raise motion values gradually and verify steering direction and vehicle response at low speed.

Simulator commands and virtual encoder pulses are simulation state/telemetry, not physical Arduino commands or physical encoder measurements.

## CARLA-specific behavior

Implementation: `python/modes/simulation/carla_adapter.py`.

The CARLA adapter manages the client connection, vehicle actor and sensor lifecycle. Its supported editor operations include selecting a map, vehicle blueprint and spawn point, resetting the vehicle to the selected spawn, and editing/previewing the camera mount. CARLA mode can publish an RGB image and, when enabled, a ray-cast LiDAR point cloud. The Stream editor provides a bounded point-cloud view and range summaries. Camera mount X/Y/Z and pitch/yaw/roll values are vehicle-local offsets and rotations. Converting a free-fly world view into a vehicle mount, and composing that mount back into world space, uses full 4×4 rigid-transform matrix multiplication/inversion; component-wise Euler-angle addition/subtraction is not valid for general 3D rotations. CARLA requires the `spawn_actor(..., attach_to=vehicle)` transform to be parent-relative. The editor therefore moves only its independent free-fly preview while tuning; on Save mount, the main RGB sensor is recreated with the selected local transform and reattached to the vehicle. It deliberately never calls `set_transform(world_pose)` on the attached Stream sensor, which would move it in world coordinates rather than update the parent-relative mount. Saving/restoring the mount updates the live Stream sensor without restarting the server. The editor separately reports the actual RGB sensor's world transform (the source of the main Stream frames) and the independent free-fly preview camera's world transform; these map/world coordinates are expected to differ from the vehicle-local mount values when the vehicle is not at the world origin. Slider previews are serialized so an older in-flight update cannot overwrite a newer mount selection.

The editor's vehicle/map/spawn/camera values are simulator settings. Saving them requires Stream control to be enabled; use `--stream-read-only` when you want a read-only dashboard.

Map changes use a dedicated 120-second CARLA RPC timeout, then restore the normal simulator request timeout. While the world is being replaced, the adapter destroys and respawns its vehicle/sensors under a scene-transition lock. The runtime commands braking and waits while the CARLA vehicle actor is temporarily unavailable instead of treating that expected transition as a fatal actuator error. If a map request times out after the server has already switched worlds, the adapter re-queries the active world and attempts to respawn there before reporting the failed selection.

For the City vision profile, the simulator Stream renders the same structured lane/crosswalk diagnostics as the physical City Stream. The camera preview includes RL (right lane), LL (left lane), and CW (crosswalk) ROI overlays, including the active rectangle/trapezoid masks and BEV processing frame. With Stream control enabled, select an ROI, drag inside it to move it, or drag a corner to resize it. ROI changes auto-save after a drag ends or a numeric coordinate has been edited; Save now is also available. Coordinates are normalized fractions from 0 to 1 (0.1 means 10% of the image), and decimals are not restricted to a 0.01 step. When RL or LL is selected, its own Mirror option flips only that cropped lane image before detection; the two mirror flags are saved independently. These settings are written only to the active simulator's `.sim.json`.

The simulator City editor includes lane and crosswalk pixel thresholds, Hough segment/vote parameters, blur/morphological preprocessing, minimum crosswalk line counts, rectangle/trapezoid modes, top-width factors, optional resizable lane ROIs, servo center/limits/direction, camera pitch/height and expected lane width, and all eight BEV source-corner coordinates. They are isolated from the physical `city.json`; simulator defaults begin with BEV disabled and raw RGB camera processing. Turn BEV on after the camera image and camera mount are verified. Existing saved simulator settings override defaults, so older `carla.sim.json` files may still have an earlier target speed or BEV selection until edited.

The normal camera preview always prefers the raw CARLA RGB camera image. The BEV processing image is used only when BEV is enabled and its frame contains image content; a blank warp cannot replace a valid raw camera frame. When enabled LiDAR is stale, the vehicle still brakes, but the RGB frame continues to be published. The camera status badge reports dimensions, average intensity, and whether the displayed image is from the camera or BEV, helping distinguish a missing callback from a black image.

Per-frame virtual steering changes are kept in the Stream event console/state rather than written to the terminal. Only changes in actuator motion/safety state are retained as events, avoiding a terminal INFO line on every camera frame.

## AVIS Engine-specific behavior

Implementation: `python/modes/simulation/avis_adapter.py`, using the bundled AVIS client.

The adapter consumes AVIS camera frames and native left/front/right distance-sensor readings. These readings are exposed as ranges; the code does not fabricate a LiDAR point cloud from them. Sensor angle is configurable only where the current AVIS adapter and editor support it. AVIS requests are synchronous TCP operations, so the timeout should stay within the documented CLI range and be tuned to the simulator environment.

### AVIS City stop line and traffic lights

AVIS \`avis\` is the City profile, but it does **not** use the physical City crosswalk detector. The AVIS City behavior coordinator instead supports a separate solid stop-line detector with its own normalized ROI (\`SIMULATOR_STOP_LINE_*_ROI\`). It looks for a broad, near-horizontal bright marking inside the configured lower-camera ROI and requires multiple consecutive frames before latching a stop. Tune the threshold, minimum width/area and maximum angle from the simulator Stream settings; SL in the ROI overlay identifies this region.

The traffic-light detector reuses \`vision/traffic_light.py\` and has an independently editable TL ROI (\`TL_*_ROI\`). The editor exposes red/green hue ranges, saturation/value, contour area and brightness thresholds. A red observation latches braking. When stopped at the line, motion is released only after the newest observation is green and the configured number of distinct green frames has been observed (default 8 of 10). Unknown, conflicting or missing observations never release an active signal hold. If traffic-light gating is disabled while stop-line detection remains enabled, the line uses a short configured dwell instead. These features are City-only; \`avis-race\` and CARLA do not receive these AVIS-specific controls.

### Optional AVIS obstacle bypass

Both \`avis\` and \`avis-race\` expose an optional range-based obstacle bypass in the Stream editor. It uses only the actual AVIS left/front/right readings and a bounded \`CLEAR → SHIFT → PASS → REJOIN\` state machine. The default bypass is disabled. When enabled, it starts evaluating an obstacle at 100 cm, requires at least 75 cm on a selected side sensor, caps bypass throttle at 0.12, uses short steering offsets, and expects the front range to clear beyond 125 cm before rejoining. The existing 35 cm forward emergency-brake threshold remains active; the bypass also keeps a separate minimum hard-stop envelope if that legacy threshold is set to zero. A pass that times out, missing forward range, invalid lane perception, or a selected-side sensor that loses its configured clearance results in braking. During bypass, lost lane perception latches the controller in a blocked state. After a stop line is passed, the detector waits for eight consecutive absent frames before arming for the next line.

These three directional range sensors are not a 2D occupancy grid and cannot prove that a full vehicle-width path is clear. This is a conservative simulator behavior prototype, not a general obstacle-navigation guarantee. Losing lane perception, losing the selected-side clearance, or disabling avoidance during an active bypass enters a braked blocked state; after re-enabling, the controller requires three clear front-range observations before recovering. Keep the emergency brake enabled, tune at very low speed, inspect the ROI/sensor console, and test each AVIS scene before increasing speed.

### Optional traffic-sign actions

Both AVIS profiles can optionally run the existing asynchronous YOLO/ONNX sign detector. It is used instead of the legacy SVM path because the ONNX detector supplies per-detection confidence for safety filtering. The model is initialized only when sign actions are enabled; changing the enable flag requires a runtime restart. Inference is sampled at a configurable frame interval and consumes only fresh worker results. Supported labels are STOP, PARK, STRAIGHT, TURN LEFT and TURN RIGHT. STOP applies a timed brake hold; PARK remains latched until a STRAIGHT sign clears it; TURN signs apply a brief low-throttle steering nudge. These actions are intentionally simple and do not infer route topology or guarantee a complete intersection turn. Confirm model accuracy, camera placement and steering direction in AVIS before enabling them for a run.

## Configuration isolation

Simulator profile files are:

- `python/carla.sim.json`
- `python/avis.sim.json`
- `python/avis-race.sim.json`

They are separate from `python/city.json` and `python/race.json`. CARLA-only options such as vehicle blueprint and LiDAR settings are rejected by other backends; AVIS sensor-angle options are AVIS-specific. Mode/profile restrictions are enforced in the configuration/editor APIs.

## Feature boundaries

Shared perception does not imply shared mode orchestration. The simulator runtime does not instantiate physical camera hardware, open Arduino serial, or deliver physical encoder readings. Do not assume simulator modes inherit every physical lane-change sequence, Race start/finish workflow or hardware obstacle-avoidance behavior. AVIS now has a separate, deliberately limited behavior coordinator for optional range-based bypass, traffic-sign actions and (City only) stop-line/traffic-light gating. This does not reuse the physical Arduino action sequences or odometry-based race avoidance. Verify each capability in the active adapter, simulator runtime and capability metadata before depending on it.

## Simulator test checklist

1. Confirm the correct server is running and the host/port is reachable.
2. Start with the Stream editor in read-only mode until the mode and sensor feeds are verified.
3. Confirm the expected map/world, vehicle and spawn point.
4. Check steering sign, range measurements, LiDAR presence (CARLA only), and lane-loss braking.
5. For AVIS City, calibrate SL/TL ROIs against the actual camera frame and verify red/green behavior before enabling stop-line gating.
6. For AVIS obstacle bypass, verify all three range readings and test both selected bypass directions at the lowest speed; confirm the emergency stop still wins.
7. Enable sign actions only after verifying the model's labels/confidence against the AVIS scene.
8. Tune target speed and throttle limit conservatively.
6. Verify reset-to-spawn and shutdown cleanup after restarting the scenario.
7. Run the simulator-mode unit tests before changing adapter/runtime contracts.

A simulator validates API wiring and virtual control behavior; it cannot establish physical wheel geometry, real sensor validity, braking distance or hardware watchdog behavior.
