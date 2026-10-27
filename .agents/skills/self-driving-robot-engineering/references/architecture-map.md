# Architecture Map and Contracts

This map is a navigation aid, not a substitute for reading the checked-out source. Verify every path, symbol, and behavior against the active commit before relying on it.

## Runtime entry and configuration

- `python/main.py`: application bootstrap, CLI parsing, config loading, diagnostics, and dispatch to the selected mode.
- `python/utils/parser.py`: runtime arguments, including mode, stream, camera, preflight, optional lane-model, and optional Arduino contract controls.
- `python/utils/json_config.py`: JSON configuration parsing and validation.
- `python/modes/city/config_city.py` and `python/modes/race/config_race.py`: mode-specific defaults and tuning.
- Mode JSON files supply runtime values in addition to Python defaults.

The documented precedence is:

~~~text
mode defaults → mode JSON config → explicit CLI overrides
~~~

An omitted optional CLI flag should not accidentally erase a value loaded from JSON. Confirm exact merge behavior in the current loader before changing it.

## Mode control loops

- `python/modes/city/city.py`: City startup, runtime loop, perception/control integration, and cleanup.
- `python/modes/race/race.py`: Race startup, runtime loop, perception/control integration, and cleanup.
- `python/controller/`: shared motion, steering, speed, and PID-related logic; follow imports to identify the actual class/helper in use.

When modifying shared code, test the City and Race callers. A branch-specific fix may be safer than assuming the modes have identical requirements.

## Camera and image flow

- `python/vision/camera.py`: camera backend and frame acquisition.
- `python/vision/city_vision_processing.py`: City perception pipeline.
- `python/vision/race_vision_processing.py`: Race perception pipeline, with its own lane/ROI/BEV state.
- `python/stream/__init__.py` and `python/stream/template.py`: HTTP stream/API and browser-side display/control behavior.
- `python/stream/capabilities.py`: mode/feature capability descriptions used by the stream layer.
- `python/calibration/`: camera calibration capture, solve, runtime loading, and calibration UI.

Debug frame problems along both directions: camera capture → publication of the newest frame → route/endpoint serialization → browser refresh/rendering. Check frame shape, channel order, JPEG encoding, request errors, and whether the displayed frame is stale. The HTTP stream should not compete with the runtime for ownership of the camera; verify the current implementation before altering that architecture.

Camera/calibration and runtime dashboards may bind to different hosts and ports. Read the relevant CLI help and startup logs instead of assuming the runtime dashboard's address applies to every service. A bind address of 0.0.0.0 is not a browser destination address.

## Perception and dataset tooling

- `python/vision/ml_lane/` and related detector modules: optional learned lane detector paths. Check the model-selection arguments, runtime provider, tensor shapes, preprocessing, and output decoding together.
- `python/vision/blsf_lane/`: experimental classical BLSF-style lane pipeline.
- `python/traffic_sign_detector/`: runtime sign-detection service, including asynchronous inference.
- `python/train_sign_detector/`: dataset collection, labels, training, and model-related tools.
- `python/vision/` AprilTag modules and config: marker detection; verify the actual implementation and any OpenCV feature requirements.

Mode and detector boundaries matter:

- BLSF beta is documented as City-only and opt-in via the City lane-detector option.
- ML lane detection is opt-in and selected with the supported model option; verify which mode supports it in current capability code.
- Sign and AprilTag options use several similarly named flags across modes. Do not rename or merge them by inspection alone.
- Numeric sign class IDs and label strings are shared contracts between collector, trainer, and runtime. Locate the authoritative mapping before changing a class.

## Arduino and controller boundary

- `python/arduino/arduino_connection.py`: serial transport, command writes, telemetry buffering/draining, heartbeat, reconnection, and lifecycle.
- `python/arduino/hardware_contract.py`: optional hardware-contract handshake and profile validation.
- `arduino/main_nonBlocking_v2.ino`: fixed-pin non-blocking firmware generation.
- `arduino/main_configurable_v1.ino`: separate configurable firmware generation documented as using the explicit Python hardware contract.
- `arduino/README.md`: firmware-generation and command-contract distinctions.

The runtime protocol is documented as line-based text at 115200 baud. Existing commands include motor/servo, stop, turns, pulse sequences, status, and heartbeat; exact grammar and behavior must be read from the firmware and Python writer before modifying anything.

The active fixed-pin v2 firmware is documented as using a 500 ms host-heartbeat watchdog that stops motion and centers steering when host liveness expires during motion/pulse activity. Confirm the checked-out firmware before relying on that exact timing.

**Hardware-contract safety boundary:** do not enable handshake/config sync implicitly. The explicit `--arduino-config` path is for firmware that implements the contract protocol. Do not assume `main_nonBlocking_v2.ino` supports that protocol; preserve normal operation without the opt-in argument. A profile, handshake, pin map, or firmware identity must not be inferred and pushed automatically.

## Dashboard, health, and performance

- `python/utils/health.py`: health evaluation.
- `python/utils/runtime_metrics.py`: timing and runtime counters.
- `python/traffic_sign_detector/async_detector.py`: worker/queue status when present in the checked-out tree.
- `python/stream/`: health/performance presentation and runtime control endpoints.

Review API mutation paths for full-payload validation before applying changes. If one field fails validation, the expected behavior should be explicit and tested; do not leave a partially updated config after returning an error. Inspect the dashboard's bind host, control defaults, authentication, origin/CSRF defenses, and firewall assumptions before changing exposure.

## Tests and automated checks

- `python/test/`: unit and hardware-free regression tests.
- `.github/workflows/python-tests.yml`: current Python compile and hardware-free test workflow.
- `python/replay.py` and `python/tools/`: offline recorded-video/replay and benchmarking utilities.

Use the test fixtures and workflow as the current contract. Do not treat the older `python -m pytest test/` suggestion in the root README as the canonical CI command without checking whether pytest is configured and whether that path is correct.

## Current documentation

The maintained engineering guides live under `docs/`; start at `docs/README.md`. Historical review findings are not a statement of current behavior unless verified against the checked-out branch and covered by a focused regression test.
