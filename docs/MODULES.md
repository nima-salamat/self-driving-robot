# Module Reference

This is a navigation guide to the implementation. It groups files by responsibility; read the selected module and its callers before changing behavior.

## Runtime and mode dispatch

| Path | Responsibility |
|---|---|
| `python/main.py` | Parses arguments, selects the mode, loads configuration, validates options, configures logging/health/metrics, and starts the selected runtime. |
| `python/base_config.py` | Shared runtime/configuration state used by modules that consume the active mode profile. |
| `python/utils/parser.py` | CLI flags and argument-value validation. Run `python python/main.py --help` for the live interface. |
| `python/utils/config_mode.py` | Selects the active City or Race configuration module for shared code. |
| `python/utils/json_config.py` | Loads and validates JSON settings, including constrained values and pulse-sequence fields. |
| `python/utils/preflight.py` | Checks startup prerequisites such as dependencies, storage, model files, camera, Arduino or simulator endpoint. |
| `python/modes/registry.py` | Declarative mode metadata: configuration profile, vision profile, runtime kind, backend and editor capabilities. |
| `python/modes/city/` | City defaults and the City control/perception orchestration. |
| `python/modes/race/` | Race defaults and Race control/perception orchestration. |
| `python/modes/simulation/` | Adapter contract, CARLA/AVIS adapters, virtual actuator mapping and simulator runtime. |

## Camera and perception

| Path | Responsibility |
|---|---|
| `python/vision/camera.py` | Camera backend initialization, capture, calibration integration, frame resizing, frame-rate controls and cleanup. |
| `python/vision/vision_processing.py` | Shared/base lane-processing implementation used where selected by the runtime. |
| `python/vision/city_vision_processing.py` | City lane and image-region processing. |
| `python/vision/race_vision_processing.py` | Race lane and image-region processing. |
| `python/vision/blsf_lane/` | Experimental classical BLSF-style lane detector, selectable in City mode. |
| `python/vision/ml_lane/` | Optional learned lane detector implementations. |
| `python/vision/apriltag.py` and related AprilTag modules | Marker detection used by navigation workflows when enabled. |
| `python/vision/traffic_light.py` | Traffic-light color/region detection for the optional City crosswalk gate. |
| `python/vision/shared_memory_capture.py` | Optional process-isolated camera producer and shared-memory latest-frame transport. |
| `python/vision/` | Additional image transforms, lane helpers and visualization helpers; check imports to identify the active path. |

## Control and hardware integration

| Path | Responsibility |
|---|---|
| `python/controller/controller.py` | High-level steering, motor command and controller-to-transport integration. |
| `python/controller/pid_controller.py` | PID update/reset logic for steering correction. |
| `python/controller/odometry.py` and related controller helpers | Encoder-derived path estimates and motion/planning helpers when enabled. Confirm the exact helper selected by the mode before changing behavior. |
| `python/arduino/arduino_connection.py` | Thread-safe serial connection, background telemetry reading, heartbeat/reconnect lifecycle and command writes. |
| `python/arduino/hardware_contract.py` | Optional strict hardware identity/configuration handshake for matching firmware. |
| `python/arduino_configs/` | Example hardware profile(s), including the Mega 2560 configuration. |
| `arduino/` | Independent Arduino firmware generations. Each sketch has its own compatibility expectations; see the Arduino README. |

## Asynchronous work, health and output

| Path | Responsibility |
|---|---|
| `python/traffic_sign_detector/` | Runtime traffic-sign detector and its result filtering, asynchronous worker and process-worker implementations. |
| `python/utils/health.py` | Runtime lifecycle and fault snapshots. |
| `python/utils/runtime_metrics.py` | Bounded-window timing samples and summary statistics. |
| `python/utils/processing_rate.py` | Requested processing-cycle rate limiting. This does not set the physical camera sensor rate. |
| `python/utils/fps.py` | FPS-oriented utility support. |
| `python/manager/output_manager.py` | Image output and asynchronous video-recording queue/writer lifecycle. |
| `python/visualization/` | Diagnostic overlays and frame display helpers. |

## Web workspace and calibration

| Path | Responsibility |
|---|---|
| `python/stream/__init__.py` | Flask Stream server, runtime state access, endpoints and shutdown lifecycle. |
| `python/stream/template.py` and `python/stream/templates/` | Browser workspace and dedicated editor UI templates. |
| `python/stream/capabilities.py` | Mode-aware capabilities and marker-mode metadata used by the UI/API. |
| `python/stream/auth_api.py` | Optional Stream authentication, login throttling, request checks and response security headers. |
| `python/stream/` feature-specific API modules | Separated routes for configuration, telemetry, simulator editing and other dashboard features; follow registration/imports in the current checkout. |
| `python/calibration/` | Camera-calibration image capture, solving and optional calibration web UI. |
| `python/assets/camera_calibrations/` | Runtime calibration artifacts; verify the configured path because asset layouts may differ between deployments. |

## Dataset, training and offline tools

| Path | Responsibility |
|---|---|
| `python/train_sign_detector/dataset_collector.py` | Collects new traffic-sign samples into the collected-data area. |
| `python/train_sign_detector/labels.py` | Authoritative numeric traffic-sign labels shared by collection, training and runtime. |
| `python/train_sign_detector/classification.py` and `main.py` | Model/training and classification workflow. |
| `python/train_sign_detector/dataset/` | Canonical training dataset; do not treat this as the collector's output directory. |
| `python/train_sign_detector/collected_dataset/` | Default destination for newly collected sign samples. |
| `python/dataset_connector/` | Standalone web workspace to capture, inspect and export image datasets without overwriting the training dataset. |
| `python/tools/lane_tuning_gui.py` | Offline GUI to tune lane thresholds, Hough settings, ROIs and BEV-related settings against saved PNGs. |
| `python/replay.py` and `python/tools/` | Offline replay, diagnosis and benchmarking tools; check each tool's help before use. |

## Tests and automation

| Path | Responsibility |
|---|---|
| `python/test/` | Hardware-free unit tests for core behavior, API contracts and simulator logic. |
| `.github/workflows/python-tests.yml` | Python compilation, hardware-free test suite and Stream UI smoke checks in CI. |
| `.github/workflows/arduino-configurable.yml` | Compile check for the configurable Arduino firmware. |

## Change-impact guide

- **Changing CLI behavior:** update `python/utils/parser.py`, test argument validation, and update [Configuration](CONFIGURATION.md).
- **Changing lane output:** inspect the active mode processor and its consumers; update [Perception](PERCEPTION.md).
- **Changing a serial command:** verify both Python and the exact firmware generation; update [Arduino Integration](ARDUINO_INTEGRATION.md).
- **Changing a dashboard control:** inspect mode capabilities, API validation and template behavior; update [Stream Dashboard](STREAM_DASHBOARD.md).
- **Adding simulator support:** implement the adapter contract, register its factory and mode capabilities, add tests, and update [Simulator Modes](SIMULATORS.md).
