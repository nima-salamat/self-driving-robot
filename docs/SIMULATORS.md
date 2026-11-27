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

CARLA and AVIS Engine use different startup interlocks. **CARLA is disarmed on every launch** and requires **Start Run** in the simulator Stream. **AVIS with `--stream` is also disarmed on launch** and requires the Stream's Start Run control. When AVIS is launched **without `--stream`**, there is no Stream control surface, so the runtime automatically arms the initial run after process startup; valid camera frames and normal sensor/perception safety checks are still required before motion. A confirmed AVIS safety stop, sustained camera outage, or link loss disarms autonomy; it does not silently re-arm when the connection returns. In headless AVIS mode, restart the process after correcting the fault to arm a new run. CARLA's Stop / Brake and scene/camera editor interlocks remain unchanged. This does not change the physical robot workflow.

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

The adapter consumes AVIS camera frames and native distance-sensor readings. These readings are exposed as ranges; the code does not fabricate a LiDAR point cloud from them. Sensor angle is configurable only where the current AVIS adapter and editor support it. AVIS requests are synchronous TCP operations, so the timeout should stay within the documented CLI range and be tuned to the simulator environment.

### AVIS City stop line and traffic lights

AVIS `avis` is the City profile and runs the shared City crosswalk image detector. Its CW ROI and detector parameters are available in the simulator Stream settings: grayscale threshold, minimum vertical/horizontal line counts, Canny thresholds, Hough vote/segment/gap settings, angle tolerance, minimum segment length, bottom-position ratio, ROI shape and legacy LSD/Hough selection. The camera overlay edits the CW crop and saves it into `avis.sim.json`. A positive crosswalk detection now sends a zero-throttle stop command immediately while the configured consecutive-frame confirmation runs. After confirmation, the controller waits for AVIS speed telemetry to remain at or below 0.5 km/h for three consecutive frames; only then does the configurable dwell (default 3 seconds) begin. If speed feedback is unavailable, it keeps the zero-throttle command active and fails closed. After the dwell, it freezes the latest accepted TURN LEFT / TURN RIGHT / STRAIGHT sign direction and runs the matching distance-based route chain. The official AVIS Python API exposes `setSpeed` as throttle control and does not expose a separate brake method, so this stop request is not a hardware-style active brake. Configure it in the AVIS City Settings panel or search for “crosswalk hardcode routes”. Each step defines forward/reverse, metres, signed speed percentage and signed steering percentage. Empty or invalid routes fail closed and remain stopped; saving a route does not move the vehicle. The generic `SIMULATOR_STOP_ON_CROSSWALK` flag remains separate and unavailable in AVIS so it cannot compete with the dedicated controller. The camera overlay uses a bounded rectangle and one unified diagnostics panel.

The AVIS City behavior coordinator independently detects a solid stop line using its normalized `SIMULATOR_STOP_LINE_*_ROI`. It looks for a broad, near-horizontal bright marking in the configured lower-camera ROI and requires multiple consecutive frames before latching a stop. Tune the threshold, minimum width/area and maximum angle in Stream settings; SL in the ROI overlay identifies this region.

The traffic-light detector uses an independent TL ROI (`TL_*_ROI`). The editor exposes red/green hue ranges, saturation/value, contour area and brightness thresholds. Detected red/green contours are circled in the live frame, while the debug text reports RED, GREEN or UNKNOWN. A red observation latches braking. When stopped at the line, motion is released only after the newest observation is green and the configured number of distinct green frames has been observed (default 8 of 10). Unknown, conflicting or missing observations never release an active signal hold. If traffic-light gating is disabled while stop-line detection remains enabled, the line uses a short configured dwell instead. These settings and controls are City-only; `avis-race` does not receive stop-line or traffic-light controls.

### AVIS obstacle bypass and forward safety guard

Both `avis` and `avis-race` expose a range-based obstacle bypass in the Stream editor. New profiles enable the staged `CLEAR → SHIFT → PASS → REJOIN` controller by default. Its initial profile starts a bypass at 120 cm, waits for the front range to clear beyond 150 cm before rejoining, requires at least 75 cm on the selected side sensor, and caps bypass throttle at 0.12. Existing AVIS settings files are migrated once from the old disabled 35/100/125 cm defaults; custom distances are retained unless they violate the safety ordering.

The `avis` City mode allows an emergency-stop threshold up to 1000 cm, a bypass trigger distance up to 1500 cm, a path-clear threshold up to 2000 cm, and a bypass throttle cap up to 1.0. The `avis-race` profile retains the previous 500 cm distance and 0.25 bypass-throttle limits. These are editable ceilings, not recommended operating targets: defaults remain conservative, and motion limits should be increased gradually under direct simulator supervision.

When Hall is enabled on the classical AVIS Hough path and the optional **Use Hall line identity when switching ROIs during obstacle bypass** setting is enabled, the bypass uses a single-boundary cross-handoff: the tracked left-boundary identity is transferred to an expanded right ROI for the passing-lane phase, then transferred back to an expanded left ROI for the original-lane phase. The transfer is bounded by the image width, preserves the lane-width model, and brakes if the handed-off boundary cannot be reacquired.

When Hall tracking is enabled but that optional identity-handoff setting is off, the maneuver ROI is acquired independently. The tracker discards ROI-specific line IDs when the maneuver ROI changes, retains only the calibrated lane-width model during the bypass, and uses the active ROI's observed boundary to infer the opposite boundary. It does not require a newly detected left/right pair to validate each maneuver ROI. Hall-backed AVIS bypasses force ROI confirmation even when the general ROI-confirmation checkbox is off. After the MR ROI confirms the original lane, the controller remains in REJOIN_LANE_FOLLOW and keeps MR active until the lane-hold and return-steering gates complete; only then are the normal left/right ROIs restored.

The steering-mean return gate is bounded as well. After the configured passing-lane hold, it waits for the configured steering sample window to enter its return band, but for no longer than the maximum wait setting (default 4 seconds). When that wait expires, the right-return attempt proceeds only if normal lane perception and right-side clearance remain valid; a failed safety check still brakes.

A separate forward safety guard always runs, whether lane-change bypass is enabled or not. Its default AVIS stop threshold is 60 cm and it enforces a minimum 20 cm threshold even if a legacy profile stores zero. Missing, invalid, negative, or non-finite front-range telemetry causes an explicit AVIS Engine `stop` command and disarms autonomous motion; an obstacle inside the emergency threshold does the same. The adapter reconnects in the background, but the operator must press Start again before motion can resume. Above the emergency threshold, the staged bypass can steer around the obstacle. The dashboard reports this guard independently from the lane-change state. During normal frame-by-frame control, the AVIS adapter sends steering and speed together in one packet, avoiding a brief resend of the previous speed.

These three directional range sensors are not a 2D occupancy grid and cannot prove that a full vehicle-width path is clear; they also do not provide a rearward view. AVIS exposes a speed command, not a separate physical brake channel, so the stop path commands motor speed zero. This is a conservative simulator prototype, not a safety-certified autonomous-driving system. Start at the lowest speed, keep direct supervision and a physical emergency stop, and verify sensor units and both bypass directions before increasing speed.

### Optional AVIS traffic-sign actions

Both AVIS profiles can optionally run the existing asynchronous YOLO/ONNX sign detector. It is used instead of the legacy SVM path because the ONNX detector supplies per-detection confidence for safety filtering. The model is initialized only when sign actions are enabled; changing the enable flag requires a runtime restart. Inference is sampled at a configurable frame interval and consumes only fresh worker results. Supported labels are STOP, PARK, STRAIGHT, TURN LEFT and TURN RIGHT. STOP applies a timed brake hold; PARK remains latched until a STRAIGHT sign clears it; TURN signs apply a brief low-throttle steering nudge. These actions do not infer route topology or guarantee a complete intersection turn. Confirm model accuracy, camera placement and steering direction in AVIS before enabling them.

### Hall-aware temporal lane tracking

The Hall feature preserves the identity of detected lane-boundary line segments across frames using bipartite maximum matching. It is opt-in through `HALL_LINE_TRACKING_ENABLED`; missed-frame and reacquisition thresholds are configurable in the simulator settings. It supports the classical Hough City/Race pipelines and BLSF City mode. Race ML lane-mask mode reports the feature as unsupported. Tracking state, line IDs, and degraded/lost/reacquiring status are exposed in Stream telemetry. It does not replace the lane-loss braking policy.

## Configuration isolation

Simulator profile files are:

- `python/carla.sim.json`
- `python/avis.sim.json`
- `python/avis-race.sim.json`

They are separate from `python/city.json` and `python/race.json`. CARLA-only options such as vehicle blueprint and LiDAR settings are rejected by other backends; AVIS sensor-angle options are AVIS-specific. Mode/profile restrictions are enforced in the configuration/editor APIs.

## Feature boundaries

Shared perception does not imply shared mode orchestration. The simulator runtime does not instantiate physical camera hardware, open Arduino serial, or deliver physical encoder readings. Do not assume it supports every physical lane-change sequence, traffic-light gate, Race start/finish workflow or hardware obstacle-avoidance behavior. Verify each capability in the active adapter, simulator runtime and capability metadata before depending on it.

## Simulator test checklist

1. Confirm the correct server is running and the host/port is reachable.
2. Start with the Stream editor in read-only mode until the mode and sensor feeds are verified.
3. Confirm the expected map/world, vehicle and spawn point.
4. Check steering sign, range measurements, LiDAR presence (CARLA only), and lane-loss braking.
5. Tune target speed and throttle limit conservatively.
6. Verify reset-to-spawn and shutdown cleanup after restarting the scenario.
7. Run the simulator-mode unit tests before changing adapter/runtime contracts.

A simulator validates API wiring and virtual control behavior; it cannot establish physical wheel geometry, real sensor validity, braking distance or hardware watchdog behavior.

## AVIS obstacle approach speed

The AVIS runtime reads the left, front and right range rays. The settings editor provides independent left-, front- and right-sensor selectors for approach-speed limiting. Only the front sensor is enabled by default because the side rays can detect lane boundaries or nearby scenery even when the forward path is clear. Users can enable either side sensor independently. When any enabled sensor reports an object strictly closer than `SIMULATOR_OBSTACLE_SPEED_LIMIT_DISTANCE_CM` (default 1500 cm), a closed-loop speed controller uses AVIS's measured vehicle speed from `car.getSpeed()` to limit speed to `SIMULATOR_OBSTACLE_APPROACH_SPEED_KMH` (default 10 km/h). The optional `SIMULATOR_OBSTACLE_SPEED_LIMIT_BRAKE_ENABLED` setting adds a latched brake request while measured speed is more than 0.5 km/h above the approach target; it releases when measured speed reaches the target, then normal closed-loop throttle control maintains that speed. It is disabled by default, preserving the existing throttle-only behavior. The setting is saved with the three sensor selections in the mode-specific `.sim.json` profile and restored on the next launch. Because the AVIS protocol has no independent mechanical-brake channel, its adapter maps this brake request to a zero motor-speed command; actual deceleration depends on AVIS Engine vehicle dynamics. Existing AVIS profiles are migrated once to the forward-only default; previously saved side-sensor selections can be re-enabled and saved again. Disabling the front selector affects only this approach-speed limiter; the independent forward emergency-stop guard remains active. This threshold is independent of `SIMULATOR_OBSTACLE_TRIGGER_DISTANCE_CM`, which is reserved for lane-change bypass. The actuator still receives AVIS's normalized/percentage speed command; the km/h target is not sent as a percentage. This behavior applies only to the virtual AVIS vehicle. The independent front emergency-stop guard remains in force and can stop the vehicle at its configured threshold.
