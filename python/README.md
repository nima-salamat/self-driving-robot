# Python Runtime

This directory contains the runtime, configuration system, Arduino transport, vision pipeline, and operational tools for the self-driving robot.

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

Run:

~~~bash
cd python
python main.py --help
~~~

The exact line wrapping can vary by Python/terminal width. The command exposes the following interface:

~~~text
usage: main.py [-h] [--mode {city,race}] [--debug] [--stream]
               [--stream-host STREAM_HOST] [--stream-control]
               [--without-arduino] [--fps] [--performance] [--preflight]
               [--read-arduino-output] [--arduino-config PATH]
               [--arduino-contract-timeout SECONDS]
               [--camera-mode {picam,webcam,opencv}]
               [--camera-index INDEX]
               [--ml-lane-model {unet_depthwise_nano,unet_depthwise_small}]

Self-driving robot runtime.

options:
  -h, --help
                        show this help message and exit
  --mode {city,race}   Run mode. Default: city
  --debug              Enable debug output
  --stream             Enable the web stream
  --stream-host STREAM_HOST
                        Stream bind address
  --stream-control     Allow the web dashboard to change runtime settings
  --without-arduino    Run without opening the Arduino serial connection
  --fps                Show the runtime FPS counter
  --performance        Enable runtime performance diagnostics
  --preflight          Run startup diagnostics and exit without entering
                        the control loop
  --read-arduino-output
                        Print telemetry lines received from Arduino
  --arduino-config PATH
                        Enable the strict Arduino hardware contract using PATH
  --arduino-contract-timeout SECONDS
                        Timeout for each Arduino hardware-contract exchange
  --camera-mode {picam,webcam,opencv}
                        Select the camera backend. 'webcam' and 'opencv' use
                        OpenCV VideoCapture
  --camera-index INDEX
                        OpenCV camera index when using webcam/opencv
  --ml-lane-model {unet_depthwise_nano,unet_depthwise_small}
                        Enable ML lane detection with the selected model
~~~

## Configuration precedence

Configuration is loaded in this order:

~~~text
1. Mode defaults from config_city.py or config_race.py
2. python/city.json or python/race.json
3. Explicit command-line flags
~~~

A value supplied by an explicit CLI flag always has priority over the value loaded from JSON.

An omitted flag does not overwrite the JSON value.

For example, when \`race.json\` contains:

~~~json
{
  "STREAM": true,
  "CAMERA_MODE": "picam",
  "USBCAM_ADDR": 0
}
~~~

this command preserves those JSON values:

~~~bash
python main.py --mode race
~~~

while this command overrides only the camera mode:

~~~bash
python main.py --mode race --camera-mode webcam
~~~

The same rule applies to the existing boolean flags such as \`--stream\`, \`--debug\`, \`--fps\`, and \`--performance\`: they override JSON only when the user explicitly supplies the flag.

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

The strict hardware contract is opt-in.

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

Open the Raspberry Pi address in a browser. The page exposes live chessboard detection, raw-frame capture, calibration execution, measured FPS, and a configurable requested camera FPS.

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

### Performance diagnostics

~~~bash
python main.py --mode race --performance
~~~

### Print Arduino telemetry

~~~bash
python main.py --mode race --read-arduino-output
~~~

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

### Camera FPS semantics

The runtime distinguishes requested camera FPS from measured camera delivery FPS. The control/vision loop FPS remains a separate runtime metric, and the HTTP stream consumes the newest published frame instead of acting as the camera producer. For Picamera2, requested frame rate is expressed through `FrameDurationLimits` for the configured camera mode; unsupported ranges are rejected rather than reported as achieved.

### Calibration network exposure

`python -m calibration.stream --host 0.0.0.0` exposes operational endpoints that can capture images, clear images, change camera FPS, and start calibration. The calibration stream has no built-in authentication, so use it only on a trusted network.

