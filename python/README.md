# Python Runtime

This directory contains the runtime, configuration system, Arduino transport, vision pipeline, and operational tools for the self-driving robot.

See the [project documentation index](../docs/README.md) for architecture, module responsibilities, configuration, simulator, Stream, performance, testing, and safety guides.

## Quick start

From the repository root:

~~~bash
python python/main.py --mode race
~~~

Or from the \`python/\` directory:

~~~bash
cd python
python main.py --mode race
~~~

The default mode is \`city\`.

## Command-line help

The exact command-line interface is generated from the checked-out code. Run:

```bash
python python/main.py --help
```

The current mode registry includes physical modes `city` and `race`, plus simulator modes `carla`, `avis`, and `avis-race`. Each mode selects a configuration profile and a runtime path; simulator capabilities are not identical to physical hardware capabilities.

CLI options are grouped around:

- mode selection, logging, FPS display and performance diagnostics;
- camera backend/index and the desired processing-cycle rate;
- optional Stream hosting and read-only/control behavior;
- Arduino enablement, telemetry output and the opt-in strict hardware contract;
- experimental multiprocessing camera/sign inference and optional lane models;
- simulator endpoint, vehicle, sensor and control settings;
- optional diagnostics and mode-specific safety/behavior features.

Do not copy an old help transcript as the authoritative interface: flags and accepted values evolve with the mode registry. The [Configuration guide](../docs/CONFIGURATION.md) explains configuration precedence and opt-in behavior, while [Simulator Modes](../docs/SIMULATORS.md) describes the simulator-specific switches.

## Multiprocess camera and traffic-sign inference

The experimental process-isolated path remains off unless explicitly requested. `--multiprocess` and `--multiprocess-camera` are aliases. They run camera capture in a shared-memory latest-frame producer and sign inference in a separate process, while the main process still owns lane perception, STOP/phase handling, steering, speed decisions and Arduino I/O.

The sign worker keeps one inference in flight and at most one waiting ROI descriptor. ROI pixels are handed off through a shared-memory latest-frame slot; only sequence/shape metadata and inference options cross the process queue. The worker snapshots the shared slot under a short lock and performs inference after releasing it. In this mode every active main-loop frame may be submitted; `READ_SIGN_THRESHOLD` is bypassed only as a frame-submission cadence limit. Detector confidence thresholds, Race STOP confidence checks, area filters and control safety rules are unchanged. Stale waiting descriptors are replaced or skipped rather than forming a backlog.

Example (do not actuate Arduino during an initial performance comparison):

```bash
python main.py --mode race --without-arduino --performance --target-fps 40 --multiprocess
```

Compare against the same command without `--multiprocess`. The multiprocessing YOLO worker defaults to two ONNX intra-op CPU threads to limit contention with capture and lane processing; test `--sign-intra-op-threads 1`, `2` and `3` on the Pi to find the best trade-off. This setting does not affect the legacy threaded detector. Performance output includes the loop/camera/perception/control/serial timings, lane and confidence time, sign submission/inference/input age, camera handoff and frame age, skipped camera frames, rate wait, synchronous AprilTag detection, and applicable stream/object/traffic-light stages. FPS is not guaranteed to reach `--target-fps`; use measured stage p95 and input-frame age to determine the current bottleneck.

See [Performance and frame freshness](../docs/PERFORMANCE.md) for the process layout, measurement workflow and current limitations.

## Stream request logging

The stream's HTTP access lines are disabled by default to avoid console-I/O
overhead when the dashboard polls frames and telemetry. Enable them only while
debugging browser/network requests:

~~~bash
# Stream runs without per-request access-log spam (default)
python main.py --mode race --stream

# Explicitly show stream HTTP request/access lines
python main.py --mode race --stream --stream-request-logs
~~~

This flag gates access-log lines for the robot dashboard server only. It does
not suppress Flask application errors or Werkzeug warnings/errors. The global
`--log-level` still controls which severities are displayed.

## Stream dashboard workspace

Start the workspace with:

~~~bash
python main.py --mode city --stream
# Open the URL printed by the runtime, normally http://<robot-ip>:5000
~~~

The CAD-style workspace includes:
- Fixed operational ROI / BEV point editing, layer visibility/color/opacity, zoom/pan, grid, snap, and crosshair. On phones, the tool dock becomes a horizontally scrollable touch toolbar; View Lock sits beside Select/Pan/Zoom, while zoom percentage and the selected-object label stay in the footer below the camera frame.
- Note/marker annotations and a live-preview pixel ruler. Operational ROI regions (RL/LL/CW/ST/OBJ) are edited directly through Properties; custom preview-only ROI drawing is intentionally not offered because it does not affect perception or steering.
- Full mode-specific configuration JSON import/export, preset save/apply/compare, configuration history, and undo/redo.
- Runtime-health charts/details, Arduino telemetry, sign-worker status, confidence/obstacle diagnostics, City traffic-light or Race lifecycle status, and an embedded encoder map when `--encoder-map` is enabled.
- Picamera2-supported exposure/gain/auto-control settings, live processing-cycle FPS limiting, session-only frame snapshots/comparison, console filters/export, runtime log search, workspace profiles, and a command palette (`Ctrl+K`).
- Runtime Stream JPEG quality (30–100) for smaller or clearer dashboard images; it is separate from browser display FPS, camera sensor FPS, and robot perception/processing.
- `File → Exit · Stop Stream Server…` opens a custom confirmation dialog and then shuts down only the Stream HTTP server and its serving thread; it does not stop the City/Race runtime loop or robot motion.
- The robot software STOP and Resume controls stay in the workspace toolbar, independently of the settings dock. STOP requests `RUN_LVL=STOP` through the active Python mode loop; it is not a hardware emergency stop. Resume remains confirmation-gated.
- `Pause Dashboard Requests` pauses browser-side frame, configuration, health, Arduino and extension status polling. It never changes `RUN_LVL` or pauses the City/Race control loop. Runtime status charts share the core health response instead of polling `/api/health` independently.

After confirmation, the active process sets `STREAM=False` so dashboard-only frame generation stops too. The current browser page disconnects; restarting the dashboard requires launching the program again with `--stream`. This runtime action is disabled when launched with `--stream-read-only`.

The JPEG quality control is available under `Settings → Stream Display Performance` and requires dashboard controls to be enabled. It changes only the JPEG encoding used by the two Stream frame endpoints; the default is 85 and values are kept for the current running process only. It does not resize the camera frame or alter vision inputs.

The dashboard control endpoints respect `STREAM_ALLOW_CONTROL` and the CLI's
`--stream-read-only` option. Either `--stream-read-only` or
`--stream-control` is also sufficient to start the dashboard; you do not have
to pass `--stream` separately:

~~~bash
# Start the dashboard with mutation endpoints disabled
python main.py --mode city --stream-read-only

# Start the dashboard with runtime controls enabled
python main.py --mode city --stream-control
~~~

For compatibility, `--stream --stream-read-only` is also valid. The two
control-mode flags are mutually exclusive.

**Network and safety:** the dashboard binds to `127.0.0.1` by default and is
available only from the same machine. Binding to a non-loopback address (including
`0.0.0.0`) is refused unless both `STREAM_USERNAME` and `STREAM_PASSWORD` are set
in `python/.env` or the process environment. For trusted LAN access, configure
unique credentials and explicitly pass `--stream-host 0.0.0.0`. The built-in server
uses HTTP, so login credentials and session cookies are not encrypted in transit
without an HTTPS reverse proxy. **Force Stop** sets the robot's
`RUN_LVL=STOP` through the active Python mode loop. `Ctrl+Shift+Space` toggles
motion: when the robot is moving it requests STOP; when already stopped it
requests MOVE after explicit confirmation that the track is clear. Neither is a
hardware emergency stop or a substitute for a physical power cutoff. This is
separate from **Pause Sign Requests** in the dashboard: that control blocks new frames
from being submitted to the asynchronous sign-inference worker and clears its
queued frame, reducing perception compute without changing `RUN_LVL`. An
inference already in progress may finish, and sign-based detection is unavailable
while requests are paused. Features that need startup construction or compatible
firmware are displayed as restart-required rather
than being enabled through an unsafe generic toggle. Runtime camera tuning is
available only when the active Picamera2 camera reports support for each control.

### Optional Stream login

The dashboard can optionally require a username and password. The Stream server reads
`python/.env` automatically when it starts; process environment variables take precedence.
No extra Python package is required.

~~~bash
cd python
cp .env.example .env
# Edit .env and replace both placeholder values with unique credentials.
chmod 600 .env
python main.py --mode race --stream --stream-host 0.0.0.0
~~~

The example explicitly enables LAN access; authentication is required for this non-loopback bind.

Set both variables in `python/.env` (or in the process environment):

~~~dotenv
STREAM_USERNAME=your-dashboard-username
STREAM_PASSWORD=use-a-long-unique-password
~~~

With both variables absent or empty, no-login access is allowed only when Stream
is bound to a loopback address (the default). A non-loopback bind fails closed
until both credentials are configured.
If only one is set, Stream startup reports a configuration error rather than silently
disabling authentication. Credentials are not committed: `.env` files are ignored by
Git, while `.env.example` is only a template. The login is rate-limited, uses a
server-side-verified signed session cookie, expires after 12 hours of inactivity, and rejects
cross-origin state-changing requests. Restarting the Stream process invalidates
existing sessions.

**Transport warning:** the built-in server uses HTTP, not HTTPS. Login credentials and
session cookies are therefore not encrypted on the network. Use it only on a trusted
network, or put it behind an HTTPS reverse proxy; for local-only access, bind to
`127.0.0.1`. An optional `STREAM_COOKIE_SECURE=1` environment setting marks the
session cookie Secure when HTTPS is available.

## Log verbosity

Logging defaults to `INFO`, so `DEBUG` records are hidden from both the terminal
and `output/robot.log`. Choose a level per run with `--log-level`:

~~~bash
# Normal operation: INFO and above
python main.py --mode race

# Troubleshoot lane detection with DEBUG records enabled
python main.py --mode race --log-level DEBUG

# Only warnings and errors
python main.py --mode race --log-level WARNING
~~~

The `--debug` flag is separate: it controls diagnostic image overlays and does
not set the logging threshold. Picamera2's high-frequency internal logs remain
limited to `WARNING` to avoid flooding the real-time control loop.

## Configuration precedence

Configuration is loaded in this order:

~~~text
1. Mode defaults from config_city.py or config_race.py
2. python/city.json or python/race.json
3. Explicit command-line flags
~~~

A value supplied by an explicit CLI flag always has priority over the value loaded from JSON.

For most optional flags, an omitted value does not overwrite the JSON value. **The stream is intentionally different:** it is opt-in and remains disabled unless `--stream` is supplied. This CLI rule overrides a stale `"STREAM": true` value in either mode JSON file.

For example, even if `race.json` contains:

~~~json
{
  "STREAM": true,
  "CAMERA_MODE": "picam",
  "USBCAM_ADDR": 0
}
~~~

this command keeps the dashboard stream disabled:

~~~bash
python main.py --mode race
~~~

Pass `--stream` to enable it:

~~~bash
python main.py --mode race --stream
~~~

Other optional settings, such as camera mode, continue to use the normal configuration precedence:

~~~bash
python main.py --mode race --camera-mode webcam
~~~

## Experimental multiprocessing camera capture

The optional --multiprocess-camera flag starts one child process that owns the camera,
performs the existing capture/calibration/resize path, and publishes the latest raw
and resized frame pair through multiprocessing.shared_memory. City/Race perception,
steering and stop decisions, Arduino communications, and the main control loop remain
in the existing process. The shared slot is protected by a short lock; stale frames
are skipped instead of building an unbounded queue. Small camera-setting commands use
a multiprocessing queue, but frame bytes never do. Picamera2 runtime controls are
forwarded to the camera-owning child process.

The feature is off by default. It is an experiment for reducing camera-I/O stalls,
not a guarantee that total perception FPS will increase. Compare the same mode,
resolution, target FPS, lane model, and debug/stream settings with and without it.
Start with Arduino communication disabled so no motor commands are sent:

```bash
python python/main.py --mode race --without-arduino --performance --target-fps 40
python python/main.py --mode race --without-arduino --performance --target-fps 40 --multiprocess-camera
```

Repeat each run for the same duration and compare measured camera FPS, complete-loop
FPS, and camera/perception p95 latency. Hardware-free tests cannot validate a physical
camera backend; test on the target Raspberry Pi before considering a merge.

## Camera configuration

Camera settings are available in both JSON configuration and CLI overrides.

### JSON

The active mode loads its JSON from:

~~~text
python/city.json
python/race.json
~~~

Relevant settings:

~~~json
{
  "CAMERA_MODE": "picam",
  "USBCAM_ADDR": 0,
  "CAM_WIDTH": 640,
  "CAM_HEIGHT": 480,
  "resize_width": 380,
  "resize_height": 230
}
~~~

Supported camera modes:

- \`picam\`: Raspberry Pi Camera through Picamera2.
- \`webcam\`: OpenCV \`VideoCapture\`.
- \`opencv\`: Alias for the OpenCV backend.

### CLI

Select the camera backend at runtime:

~~~bash
python main.py --mode race --camera-mode webcam
~~~

Select a specific USB camera index:

~~~bash
python main.py --mode race --camera-mode webcam --camera-index 1
~~~

The CLI camera options override the corresponding JSON values.

When \`CAMERA_MODE=picam\`, \`--camera-index\` has no effect.

## Arduino hardware contract

The strict hardware contract is opt-in and is enabled only by explicitly passing
`--arduino-config PATH` on the command line. Values left in `city.json` or
`race.json` cannot enable the handshake implicitly. The handshake requires
firmware implementing the `hello`/`cfg` protocol.

For EEPROM/set-based firmware such as
`arduino/new_main_adaptive_pwm_with_savingPulseInEEPROM`, omit
`--arduino-config`. City and Race send their hardcoded pulse sequences using
`set left` and `set right` at startup; Race persists both sequences with the
firmware's single `save` command. This path does not use a hardware-contract handshake.

Example:

~~~bash
python main.py \
  --mode race \
  --arduino-config arduino_configs/mega2560_default.json
~~~

This requires \`arduino/main_configurable_v1.ino\`.

Python verifies:

1. Arduino firmware ID.
2. Protocol version.
3. Board ID.
4. Module and pin acknowledgements.
5. Configuration fingerprint.

Any contract error stops startup before Race or City begins.

The timeout can be changed with:

~~~bash
python main.py \
  --mode race \
  --arduino-config arduino_configs/mega2560_default.json \
  --arduino-contract-timeout 5
~~~

The strict contract cannot be combined with \`--without-arduino\`.

## Common run examples

### City

~~~bash
python main.py --mode city
~~~

### City with BLSF beta lane detection

~~~bash
python main.py --mode city --city-lane-detector blsf-beta
~~~

### Camera calibration web stream

Start the raw camera calibration interface instead of the legacy local camera window:

~~~bash
python -m calibration.stream --host 0.0.0.0 --port 5050 --camera-mode picam --fps 30
~~~

Open the Raspberry Pi address in a browser. The page exposes live chessboard detection, raw-frame capture, calibration execution, measured FPS, and a configurable requested camera FPS. The web calibration UI includes board-size inputs, detector selection, quality-threshold controls, automatic capture, a captured-image gallery, and a live preview through the generated calibration model.

Run the offline calibration step directly when images are already captured:

~~~bash
python -m calibration.calibrate --image-dir assets/images --square-size 1.0
~~~

The `--square-size` value is the physical side length of one chessboard square in any consistent unit. Intrinsic calibration does not depend on that unit, but storing it keeps the calibration metadata physically meaningful.

### Race

~~~bash
python main.py --mode race
~~~

### Race with a USB webcam

~~~bash
python main.py --mode race --camera-mode webcam --camera-index 0
~~~

### Race with strict Arduino validation

~~~bash
python main.py \
  --mode race \
  --arduino-config arduino_configs/mega2560_default.json
~~~

### Race with strict Arduino validation and webcam

~~~bash
python main.py \
  --mode race \
  --arduino-config arduino_configs/mega2560_default.json \
  --camera-mode webcam \
  --camera-index 0
~~~

### Hardware-free run

~~~bash
python main.py --mode race --without-arduino
~~~

### Startup diagnostics

~~~bash
python main.py --mode race --preflight
~~~

Preflight enumerates the configured serial port without opening it, because opening some Arduino boards resets the MCU. If `--arduino-config` is selected, it validates that profile locally, but it does not verify the attached firmware identity or execute the live `hello/cfg` handshake. A successful preflight therefore does not certify hardware-contract compatibility. When Stream is enabled, preflight also checks that non-loopback binding has both login credentials configured.

### Performance diagnostics

~~~bash
python main.py --mode race --performance
~~~

### Print Arduino telemetry

~~~bash
python main.py --mode race --read-arduino-output
~~~

## Encoder map and odometry calibration

The separate `/encoder-map` page uses cumulative encoder telemetry from Arduino and the **final servo command** applied by the controller. When `USE_PID=True`, this is the command produced after the PID correction—not the unprocessed angle proposed by vision. The page reports a calibrated road-wheel-angle estimate and uses it to integrate a 2D path; Arduino does not provide physical servo-angle feedback, so this remains an estimate.

Calibration may be configured independently for each active mode in `modes/city/config_city.py` / `city.json` and `modes/race/config_race.py` / `race.json`:

- `ENCODER_PULSE_DISTANCE_CM`: measured travel per encoder pulse.
- `ENCODER_WHEELBASE_CM`: measured wheelbase.
- `ENCODER_ROAD_ANGLE_MIN_DEG` and `ENCODER_ROAD_ANGLE_MAX_DEG`: measured road-wheel angles at that mode's minimum and maximum servo commands.

The pulse-distance value is required. Wheelbase and both road-angle values are needed for 2D path estimation; without them, the map can still show pulse/distance telemetry but does not fabricate X/Y coordinates. No generic values are pre-filled because these measurements depend on the physical robot. Explicit `--encoder-*` CLI values override the active mode's JSON/config values.

Enable the map and Stream server with:

~~~bash
python main.py --mode race --stream --encoder-map
~~~

The selected mode's Arduino telemetry must support the explicit `encoder telemetry on` command. In this repository, `arduino/new_main_adaptive_pwm_with_savingPulseInEEPROM_FIX` already emits the `ODOM1` extension when requested.

## Classical BLSF lane detection — City beta

The repository includes an experimental classical lane detector following the BLSF-style pipeline: existing City BEV/IPM, weighted grayscale, median-local thresholding, LSD line segments, binary line-segment filtering, column projection, sliding windows, and quadratic RANSAC fitting.

City keeps the current vision detector by default. The beta detector is opt-in:

~~~bash
python main.py --mode city --city-lane-detector blsf-beta
~~~

`--city-lane-detector default` keeps the existing City detector. `blsf-beta` selects the experimental detector. The option is restricted to City mode and does not change Race mode or the existing ML lane detector.

The BLSF implementation reuses the existing `USE_BEV` and `BEV_SRC_*` configuration values from `modes/city/config_city.py`. BLSF-specific tuning values are grouped under the `BLSF_*` names in that same file.

**Beta note:** this implementation is for controlled evaluation and comparison first; it should not be treated as the production City detector until it has been validated on the robot's recorded runs.

## ML lane detection

ML lane detection is opt-in:

~~~bash
python main.py --mode race --ml-lane-model unet_depthwise_nano
~~~

Supported models:

~~~text
unet_depthwise_nano
unet_depthwise_small
~~~

## Tests

Run the hardware-free unit suite from the repository root:

~~~bash
PYTHONPATH=python python -m unittest discover -s python/test -p 'test_unit_*.py' -v
~~~

The configurable Arduino firmware also has a GitHub Actions compile workflow:

~~~text
.github/workflows/arduino-configurable.yml
~~~

The CI workflow compiles \`main_configurable_v1.ino\` for Arduino Mega 2560.

## Project structure

~~~text
python/
├── main.py
├── base_config.py
├── city.json
├── race.json
├── arduino/
│   ├── arduino_connection.py
│   └── hardware_contract.py
├── arduino_configs/
│   └── mega2560_default.json
├── controller/
├── modes/
├── vision/
├── utils/
└── test/
~~~

## Design notes

The current serial transport is asynchronous. Telemetry is drained by a background reader, and the controller does not wait for a response after every command.

The strict Arduino contract is intentionally separate from normal operation so existing deployments can continue using their current firmware. It can be enabled explicitly when a robot is known to use \`main_configurable_v1.ino\`.

## Traffic-sign dataset collection

The traffic-sign collector now lives under `python/train_sign_detector/`. The canonical training dataset and newly collected data are deliberately separate:

```text
python/train_sign_detector/
├── dataset/              # existing canonical training dataset
├── collected_dataset/    # newly captured samples
├── dataset_collector.py
├── classification.py
├── labels.py
└── main.py
```

The authoritative class mapping is numeric and shared by the collector, trainer, and runtime detector:

```text
0 ERROR
1 STOP
2 TURN RIGHT
3 TURN LEFT
4 STRAIGHT
5 PARK
```

Collect samples without depending on the shell working directory:

```bash
python python/train_sign_detector/dataset_collector.py --mode race
```

By default new data is saved under `python/train_sign_detector/collected_dataset/`. To train directly from a collected set, pass it explicitly:

```bash
python python/train_sign_detector/main.py --train --dataset python/train_sign_detector/collected_dataset --file_name video.mp4
```

The existing `dataset/` is not overwritten by the collector. The old root `python/dataset_collector.py` wrapper has been removed; use `python/train_sign_detector/dataset_collector.py` directly.

### Dataset Connector Web UI

The repository also includes a standalone web workspace for collecting camera images without modifying the canonical training dataset:

~~~bash
cd python
python -m dataset_connector --host 0.0.0.0 --port 5051 --camera-mode picam --fps 30
~~~

The connector:

- keeps captured source images under `python/assets/dataset_connector/`;
- provides a live camera view and responsive image gallery;
- captures, previews, deletes, clears, and downloads the captured images as `dataset.zip`;
- optionally accepts a validated `camera_calibration.npz` file for Raw/Calibrated preview;
- never overwrites captured source images when applying calibration;
- keeps connector storage separate from `train_sign_detector/dataset` and `train_sign_detector/collected_dataset`.

The default connector storage is runtime data and is ignored by Git.

### Camera FPS semantics

The runtime distinguishes requested camera FPS from measured camera delivery FPS. The control/vision loop FPS remains a separate runtime metric, and the HTTP stream consumes the newest published frame instead of acting as the camera producer. For Picamera2, requested frame rate is expressed through `FrameDurationLimits` for the configured camera mode. Requests above the mode's maximum are clamped to the supported maximum and logged as a warning; requests below the minimum are rejected. The reported requested rate reflects the rate actually applied, not an unsupported target.

### Calibration network exposure

`python -m calibration.stream --host 0.0.0.0` exposes operational endpoints that can capture images, clear images, change camera FPS, and start calibration. The calibration stream has no built-in authentication, so use it only on a trusted network.



## Optional City traffic-light crosswalk gate

Disabled by default and City-only. JSON cannot enable it; explicit `--traffic-lights` is required.

```bash
python main.py --mode city
python main.py --mode city --traffic-lights
python main.py --mode city --traffic-lights --traffic-light-wait-before-check
```

The delayed option waits `CROSSWALK_SLEEP` before the first observation; it does not bypass confirmation. Crossing requires 8 GREEN observations among the latest 10 distinct fresh frames, with the newest also GREEN. RED, UNKNOWN, invalid frames, and detector errors must hold indefinitely. The wait flag requires `--traffic-lights`.

Image thresholds are separate from temporal confirmation. Configure `TL_RED_HSV_RANGES`, `TL_GREEN_HSV_RANGES`, `TL_MIN_SATURATION`, `TL_MIN_VALUE`, `TL_MIN_CONTOUR_AREA`, and `TL_MIN_ACTIVE_BRIGHTNESS` in `modes/city/config_city.py`. The normalized ROI uses `TL_TOP_ROI`, `TL_BOTTOM_ROI`, `TL_LEFT_ROI`, `TL_RIGHT_ROI`, satisfying `0 <= top < bottom <= 1` and `0 <= left < right <= 1`. Temporal defaults are `TL_CONFIRMATION_WINDOW=10` and `TL_CONFIRMATION_GREEN_REQUIRED=8`. Thresholds are not camera-calibrated; validate with the real camera before physical operation.

## Offline PNG lane tuning GUI

Use the Tkinter tool to inspect saved camera PNGs and tune the actual Race or City Hough lane detector without starting a camera or connecting to an Arduino.

From the repository's `python/` directory:

```bash
python tools/lane_tuning_gui.py
```

Open a directory containing PNG images from **Open PNG folder**, choose `race` or `city`, select an image, tune the lane threshold, Hough vote threshold, minimum segment length, maximum segment gap, blur kernel, preprocessing method, morphology, BEV transform, lane ROI shape, each left/right ROI boundary, and trapezoid top-width factors, then press **Apply detection**.

Available views are the original frame, all raw Hough candidates, the best candidate selected for each lane ROI, and left/right edge maps. **Save displayed PNG** exports the current view. **Save preset to mode JSON** merges the detector settings into `race.json` or `city.json` after confirmation and creates a sibling `.bak` backup first.

The image is resized to the mode's configured runtime dimensions by default. Turn that option off to run the detector on the original image dimensions. Tuning is offline and does not start camera or Arduino hardware. Validate saved settings on representative recordings and at low speed before using them on the robot.
