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

Simulator commands and virtual encoder pulses are simulation state/telemetry, not physical Arduino commands or physical encoder measurements.

## CARLA-specific behavior

Implementation: `python/modes/simulation/carla_adapter.py`.

The CARLA adapter manages the client connection, vehicle actor and sensor lifecycle. Its supported editor operations include selecting a map, vehicle blueprint and spawn point, resetting the vehicle to the selected spawn, and editing/previewing the camera mount. CARLA mode can publish an RGB image and, when enabled, a ray-cast LiDAR point cloud. The Stream editor provides a bounded point-cloud view and range summaries.

The editor's vehicle/map/spawn/camera values are simulator settings. Saving them requires Stream control to be enabled; use `--stream-read-only` when you want a read-only dashboard.

## AVIS Engine-specific behavior

Implementation: `python/modes/simulation/avis_adapter.py`, using the bundled AVIS client.

The adapter consumes AVIS camera frames and native distance-sensor readings. These readings are exposed as ranges; the code does not fabricate a LiDAR point cloud from them. Sensor angle is configurable only where the current AVIS adapter and editor support it. AVIS requests are synchronous TCP operations, so the timeout should stay within the documented CLI range and be tuned to the simulator environment.

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
