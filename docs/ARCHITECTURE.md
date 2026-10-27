# System Architecture

## Purpose

The project combines a Python perception and decision layer with Arduino firmware for physical actuation. It also provides simulator adapters and an optional web workspace. Mode registration and shared module contracts reduce duplication, but the hardware and simulator runtimes remain separate where their sensors and actuators differ.

## Runtime entry point

`python/main.py` is the application bootstrap. At startup it parses CLI arguments, resolves a registered mode, loads that mode's configuration profile, applies configuration and CLI overrides, validates selected optional features, optionally runs preflight diagnostics, and dispatches to the appropriate runtime.

The declarative registry in `python/modes/registry.py` describes each mode's configuration profile, perception profile, runtime kind, simulator backend, and editor capabilities.

| Mode | Runtime | Configuration / perception profile | Input and actuator path |
|---|---|---|---|
| `city` | Physical robot | City | Camera, Arduino serial controller, physical range sensors and encoder telemetry when supported |
| `race` | Physical robot | Race | Camera, Arduino serial controller, physical range sensors and encoder telemetry when supported |
| `carla` | Simulator | City | CARLA RGB camera and optional ray-cast LiDAR; virtual steering/throttle/brake |
| `avis` | Simulator | City | AVIS camera and native distance readings; virtual steering/throttle/brake |
| `avis-race` | Simulator | Race | AVIS camera and native distance readings; virtual steering/throttle/brake |

## Physical runtime flow

1. **Bootstrap and configuration** — `main.py`, `utils/parser.py`, `utils/json_config.py`, and `utils/preflight.py` prepare the selected run.
2. **Frame acquisition** — `vision/camera.py` opens the configured backend and exposes raw and processing-sized frames. Camera calibration is applied when configured.
3. **Perception** — the selected City or Race vision processor estimates lane geometry and returns perception data used by the mode loop. Optional sign, AprilTag, traffic-light, and object-related work is enabled through mode settings or explicit flags.
4. **Mode decisions** — `modes/city/city.py` and `modes/race/race.py` own their mode-specific lifecycle and decisions. Asynchronous sign workers can publish recent inference results to the loop.
5. **Control** — `controller/controller.py` maps steering error and speed decisions to controller commands; `controller/pid_controller.py` implements the reusable PID calculation.
6. **Hardware boundary** — `arduino/arduino_connection.py` handles serial transport and telemetry. Firmware owns low-level motor outputs, servo writes, sensor polling and the firmware-specific safety mechanisms.
7. **Output and observability** — output management records images/videos when enabled; runtime metrics and health snapshots are surfaced to logs and the optional Stream dashboard.

The Stream server is a consumer/control surface, not the owner of the physical camera or the City/Race control loop.

## Simulator runtime flow

Simulator modes use `modes/simulation/runtime.py`, `modes/simulation/controller.py`, and an adapter selected by `modes/simulation/adapter_registry.py`. Both adapters normalize simulator-specific data into `SensorFrame` and receive `VehicleCommand` objects through the `SimulatorAdapter` contract.

- `CarlaAdapter` owns the CARLA connection, actors, RGB camera and optional LiDAR, and exposes scene editing such as map, vehicle and spawn selection.
- `AvisAdapter` owns the AVIS client connection and maps native range measurements into the normalized sensor frame.
- `VirtualVehicleController` maps the servo-angle convention into normalized steering, throttle and brake values.
- Simulator state is saved in its own profile files; simulator settings do not overwrite the physical `city.json` or `race.json`.

Do not assume that the simulator runtime implements every physical-mode behavior. It does not create the physical camera, open the Arduino serial transport, or provide physical encoder measurements. Hardware-specific lane-change sequences, traffic-light gating and Race lifecycle behavior must be checked against the current simulator implementation before being described as supported.

## Important boundaries

### Shared code versus mode-specific code

- Shared configuration and utility code lives under `python/utils/`.
- City and Race defaults are separate modules: `python/modes/city/config_city.py` and `python/modes/race/config_race.py`.
- City and Race perception processors are distinct; a change to shared camera or controller code can still affect both.
- The Stream layer uses mode capability metadata instead of assuming every control or editor feature exists for every mode.
- Firmware generations implement different serial contracts. The strict configurable-firmware handshake is opt-in and must not be assumed for fixed-pin or EEPROM/set-based firmware.

### Concurrency

The normal runtime owns perception and control in its main mode process. Optional multiprocessing isolates camera capture and traffic-sign inference; it does not move steering, STOP/phase decisions, or Arduino I/O into the worker. Latest-frame handoff is designed to drop obsolete frames rather than build a backlog.

### Configuration ownership

Use this precedence as the general rule:

```text
Mode defaults → mode JSON → explicit CLI overrides
```

Some features are intentionally CLI opt-ins, including the web Stream and multiprocessing path. Consult [Configuration](CONFIGURATION.md) and the runtime's actual CLI help before relying on a general precedence rule for a specific flag.

## Extension checklist

When adding a feature or changing a module contract:

1. Identify whether the feature belongs to shared code, a physical mode, a simulator adapter, or the Stream presentation layer.
2. Keep simulator sensor readings distinct from hardware telemetry; do not fabricate a LiDAR cloud, encoder count, or servo feedback where the backend does not provide it.
3. Preserve existing firmware compatibility and make new handshakes or protocol extensions explicit.
4. Add hardware-free tests for deterministic logic and API contracts; use dedicated simulator or hardware validation for integration behavior.
5. Update the relevant page in this directory and the corresponding component README when CLI usage or an externally visible contract changes.
