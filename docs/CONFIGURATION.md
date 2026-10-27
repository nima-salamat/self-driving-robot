# Configuration

## Configuration sources and precedence

The general resolution order is:

1. Defaults in the selected profile module: `python/modes/city/config_city.py` or `python/modes/race/config_race.py`.
2. The matching JSON file: `python/city.json` or `python/race.json`.
3. Explicit CLI overrides.

A concrete CLI value takes priority over the corresponding JSON value. Not every CLI flag behaves like a normal nullable override: several features are deliberate command-line opt-ins and remain disabled unless the documented flag is supplied.

Run `python python/main.py --help` on the current checkout for the authoritative list of flags and accepted values.

## Mode and profile mapping

| CLI mode | Base profile | Main JSON |
|---|---|---|
| `city` | City | `python/city.json` |
| `race` | Race | `python/race.json` |
| `carla` | City | `python/carla.sim.json` |
| `avis` | City | `python/avis.sim.json` |
| `avis-race` | Race | `python/avis-race.sim.json` |

The simulator profiles are intentionally separate from physical City/Race files. Editing simulator steering, throttle or sensor settings must not overwrite physical robot configuration.

## Important opt-in behavior

- **Stream dashboard:** `--stream` is required. The server remains off when the flag is omitted, even if a stale JSON value says otherwise.
- **Multiprocessing:** `--multiprocess` (alias `--multiprocess-camera`) opts into process-isolated camera capture and sign inference. Do not enable it by putting a default in JSON.
- **City traffic-light gate:** `--traffic-lights` is required; the gate is City-only. The optional `--traffic-light-wait-before-check` flag delays the first observation but does not reduce the GREEN-confirmation requirement.
- **Stream HTTP access logs:** `--stream-request-logs` opts into per-request log output; access logging is quiet by default.
- **Strict Arduino hardware contract:** `--arduino-config PATH` is for matching configurable firmware. It is not a generic switch for every Arduino sketch.
- **Experimental lane detectors:** BLSF is selected with `--city-lane-detector blsf-beta`; ML lane detection is selected with `--ml-lane-model` and a supported model name.

## Camera FPS versus processing FPS

These settings describe different parts of the pipeline:

- `CAMERA_FPS` is a requested camera capture rate. The actual rate depends on the camera backend and the selected sensor mode.
- `--target-fps N` sets the desired rate of complete processing/control cycles. The default is 30 FPS.
- The Stream JPEG/display rate is separate from both and affects dashboard presentation/network use, not the camera sensor's delivery rate.

Use measured values from the performance output to reason about the effective rate. A requested target is not a guarantee.

## Configuration domains

Common groups of settings include:

- **Camera and calibration:** backend, device index, capture dimensions, resized processing dimensions, camera frame rate, calibration toggle and calibration file.
- **Lane geometry:** ROI edges, ROI shape, BEV/IPM source points, lane threshold and Hough parameters.
- **Steering:** servo min/max/center, PID gains, derivative filtering and controller timing limits.
- **Signs and traffic lights:** model/detector selection, confidence or area filters, result freshness and traffic-light HSV/contour/temporal confirmation settings.
- **Motion and sensors:** speed settings, serial timeouts, telemetry buffer sizing, obstacle thresholds and pulse-sequence strings.
- **Stream:** host/port, mutation/read-only behavior, logging, recording, dashboard presentation and optional encoder map.
- **Simulation:** host/port/timeout, vehicle/map/spawn parameters, native sensor settings, target speed, throttle limit and lost-lane policy.

Use the JSON validator in `python/utils/json_config.py` and CLI validation in `python/main.py` as the constraints when changing a field. Pulse-sequence fields are command strings with a strict group format; do not put shell-like syntax or arbitrary text into them.

## Recommended workflow for a configuration change

1. Identify the active mode and the profile file it loads.
2. Check the setting's default, accepted range and any coupled settings in code.
3. Make the smallest change possible and use `--preflight` when relevant.
4. Start without physical actuation (for example, `--without-arduino`) if the change can be evaluated without the robot moving.
5. Inspect logs, perception output and performance metrics before physical tests.
6. If the Stream editor persists the setting, check which profile it writes to and export a copy before a larger edit.

Avoid copying physical tuning values into simulator profiles or treating a simulator value as a measured property of the real robot. Keep credentials and other secrets out of JSON files and commits.
