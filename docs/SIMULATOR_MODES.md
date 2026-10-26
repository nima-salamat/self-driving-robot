# Simulator modes: CARLA and AVIS Engine

## Architecture

The declarative `modes.registry` selects a configuration profile, a vision profile, a runtime type, and adapter capabilities. Physical `city` and `race` startup flows remain separate; simulator modes use a generic runtime with a registered API adapter.

| Mode | Runtime | Config + vision | Sensor backend |
|---|---|---|---|
| `city` | Hardware | City | Physical camera and controller |
| `race` | Hardware | Race | Physical camera and controller |
| `carla` | Simulation | City | RGB camera plus optional ray-cast LiDAR |
| `avis` | Simulation | City | Camera plus left/front/right distance sensors |
| `avis-race` | Simulation | Race | Camera plus left/front/right distance sensors |

The shared City processor performs line and crosswalk image processing. Race mode uses the Race lane processor. The simulator runtime deliberately does not imply that physical mode orchestration is ported: serial motor sequences, traffic-light gating, sign-triggered Race start/finish phases, and the hardware obstacle-avoidance planner are not part of this first simulator runtime.

## Install and launch

```bash
python -m pip install -r requirements.txt
python -m pip install -r requirements-simulators.txt
python python/main.py --mode carla --stream --stream-control
python python/main.py --mode avis --stream --stream-control
python python/main.py --mode avis-race --stream --stream-control
```

Start the matching simulator server before the client. Defaults: CARLA `127.0.0.1:2000`; AVIS Engine `127.0.0.1:25001`. Use `--simulator-host` and `--simulator-port` to override. CARLA's server, client API version and Python wheel must be compatible. The optional CARLA requirement is limited to common x86-64 CPython 3.10–3.12 targets because those are the official PyPI wheel tags; for other platforms use the matching simulator-distributed wheel manually. The AVIS API is bundled as `python/avisengine.py` because the upstream repository does not currently provide a pip-installable package; its required NumPy/OpenCV dependencies are in the base requirements.

Useful command-line settings include `--simulator-target-speed`, `--simulator-throttle-limit`, `--simulator-stop-on-lost-lane`, `--simulator-stop-on-crosswalk`, `--simulator-obstacle-stop-distance-cm`, `--simulator-steering-inverted`, `--simulator-avis-sensor-angle`, and CARLA-only `--simulator-lidar-range-m`, `--simulator-lidar-channels`, `--simulator-lidar-points-per-second`. Run `python python/main.py --help` for the complete mode-specific CLI.

## Adapter contract

`SimulatorAdapter` normalizes the image, sequence/timestamp, current speed, available range measurements and optional LiDAR point cloud. Each adapter owns its connection, simulator sensors and shutdown lifecycle. `adapter_registry.register_adapter()` allows a future backend to be added without copying the perception loop.

- **CARLA:** spawns a configured vehicle, RGB camera and ray-cast LiDAR. The dedicated editor provides a bounded top-down point-cloud preview and nearest/range summaries.
- **AVIS Engine:** uses `avisengine.Car` (`connect`, `getImage`, `getSensors`, `getSpeed`, `setSteering`, `setSpeed`, `stop`). AVIS native sensor readings are left/middle/front/right distances in centimeters and are not represented as a point cloud.
- **Virtual I/O:** the common controller translates the project's servo-angle convention into normalized CARLA controls or AVIS steering/speed commands. A virtual encoder estimates travel from CARLA vehicle displacement or AVIS reported speed. It is explicitly labelled as an estimate, never physical encoder telemetry.

## Editor settings and separation

Simulator modes render `simulator_editor.html` and use `/api/simulation/state` and `/api/simulation/settings` rather than the generic hardware editor. The page groups shared vision, active vision profile, backend-specific sensors and virtual I/O. Use `--stream-control` to enable settings writes; without it the dashboard is intentionally read-only. Host/port, model selection, encoder geometry and sensor-creation changes require a restart; supported controller and vision settings are saved immediately.

### CARLA camera placement studio

In CARLA mode, open **Open camera placement studio** from the CARLA sensor settings. The full-screenable modal creates a second, independent RGB camera in world space so it can fly around the map without changing the active vehicle camera. Use `W/A/S/D` to fly, `Q/E` to move vertically, arrow keys to rotate, hold Shift to move faster, or drag the viewport to look around. The world coordinates and angles are displayed over the preview.

The right-side sliders control the actual vehicle-mounted camera's local X/Y/Z offset (meters) and pitch/yaw/roll (degrees). The changes are applied live to the attached camera but are not persisted until **Save mount** is pressed. **Snap view to vehicle camera** is a convenient starting point; **Use current world view as mount** converts the free camera's world pose into the vehicle's local coordinates. **Level mount** zeros pitch and roll. Closing/discarding the studio restores the last saved mount.

Opening the studio puts the CARLA vehicle on the brake and suppresses autonomous throttle until the studio closes. The CARLA sensor camera uses the saved mount on the next launch. Camera FOV and sensor-creation parameters still require a restart. Live world navigation requires a running, compatible CARLA server and `--stream-control`.

The CARLA LiDAR card shows a live 360-degree bird's-eye point-cloud view with range rings and distance-based point colors; use **Expand view** for a larger viewport. AVIS has a separate top-down three-sensor distance diagram with live left/front/right range rays, centimeter labels, adjustable side-angle context, proximity colors, unknown-reading handling and an expanded viewport. That AVIS diagram visualizes the three actual reported ranges; it does not claim to locate objects or synthesize a LiDAR point cloud. Only the front/middle reading is used by the current forward-stop rule; side readings are shown for awareness and monitoring.

Each mode persists only its own whitelisted simulator overrides:

- `python/carla.sim.json`
- `python/avis.sim.json`
- `python/avis-race.sim.json`

Those settings never write to `city.json` or `race.json`. Unknown keys and invalid values are rejected by the settings layer.

## Preflight and safety

`--preflight` checks the selected simulator API, the TCP endpoint and stream port without trying to open a physical camera or serial port. Unit tests use fake adapters and do not require a running simulator server.

The simulation controller brakes by default when a fresh frame is unavailable, the active lane processor reports invalid perception, a City-profile crosswalk is detected, or a front range sensor reports a value at/below the configurable obstacle-stop threshold. The range check uses the forward LiDAR sector in CARLA and AVIS's middle/front range sensor; a missing range reading is treated as unknown, not as an obstacle. Verify steering direction and use a low target speed before longer runs.
