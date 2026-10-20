# Self-Driving Robot

A Python-and-Arduino autonomous robot project for camera-based navigation, lane detection, motion control, and optional traffic-sign/traffic-light behaviors.

[Watch the demo](https://github.com/user-attachments/assets/ad7efa66-dcdb-4234-98d1-214cd702bc16)

## How it works

- **Python runtime** (`python/main.py`) runs on the host computer/Raspberry Pi. It selects City or Race mode, processes camera frames, runs perception and steering logic, and sends motion commands over serial.
- **Arduino firmware** controls the motors, steering servo, encoder and ultrasonic sensors. The host and firmware communicate using line-based serial commands.
- **Tools** under `python/calibration/`, `python/train_sign_detector/`, `python/dataset_connector/` and `python/tools/` support camera calibration, sign-model data collection, and offline lane-detector tuning.

## Quick start

From the repository root, create an environment and install the project dependencies:

```bash
python -m venv .venv
# Linux / Raspberry Pi
source .venv/bin/activate
# Windows PowerShell instead:
# .venv\Scripts\Activate.ps1

python -m pip install -r requirements.txt
python python/main.py --help
```

Run a mode:

```bash
# City mode (the default)
python python/main.py --mode city

# Race mode
python python/main.py --mode race

# Run the processing loop at a lower target rate (default: 30 FPS)
python python/main.py --mode race --target-fps 20
```

Camera hardware, operating-system packages, and permissions vary by platform. Verify the selected camera and Arduino connection before testing motion.

## Modes and optional features

**City mode** supports lane following and configurable traffic-sign behavior. The traffic-light crosswalk gate is opt-in:

```bash
python python/main.py --mode city --traffic-lights
```

With this gate enabled, crossing requires 8 GREEN observations among the latest 10 distinct fresh frames, and the newest observation must also be GREEN. The optional `--traffic-light-wait-before-check` flag delays the first observation; it does not bypass confirmation.

**Race mode** provides a separate navigation/control path and configurable race phases. Sign-triggered start/finish behavior is controlled by its flags and configuration; see the Python runtime guide before enabling it.

Other useful options:

```bash
# Experimental classical lane detector in City mode
python python/main.py --mode city --city-lane-detector blsf-beta

# Web dashboard / video stream (opt-in)
python python/main.py --mode race --stream

# Show stream HTTP request logs while debugging
python python/main.py --mode race --stream --stream-request-logs

# Detailed application logs
python python/main.py --mode race --log-level DEBUG

# Startup diagnostics without entering the control loop
python python/main.py --mode race --preflight

# Vision/runtime testing without opening the Arduino serial connection
python python/main.py --mode city --without-arduino

# Experimental camera + sign-inference processes with latest-frame handoff
python python/main.py --mode race --without-arduino --performance --target-fps 40 --multiprocess
```

The BLSF detector and supported ML lane models are documented in [`python/README.md`](python/README.md). BLSF is experimental; validate detector changes on representative footage and at low speed before physical use.

## Configuration

Runtime configuration is resolved in this order:

1. Mode defaults in `python/modes/city/config_city.py` or `python/modes/race/config_race.py`.
2. The selected mode's JSON file: `python/city.json` or `python/race.json`.
3. Explicit command-line overrides.

An explicit CLI value takes precedence. The dashboard stream is intentionally opt-in and requires `--stream`.

### Multiprocess latest-frame pipeline

`--multiprocess` (alias: `--multiprocess-camera`) opts into process-isolated camera capture and traffic-sign inference. The YOLO process defaults to two ONNX intra-op CPU threads (`--sign-intra-op-threads N` lets you tune that budget); this is intended to reduce CPU contention with camera capture and lane processing, not to guarantee faster model inference. The camera shares only its latest raw/resized frame with the main process; the sign worker keeps only one pending ROI frame and replaces it with newer submissions. This avoids growing backlogs, while the main process continues to own lane perception, STOP/phase decisions, steering and speed control. Only the sign-submission cadence gate `READ_SIGN_THRESHOLD` is bypassed; model confidence and sign safety checks are preserved.

With `--performance`, the runtime reports stage percentiles for lane detection, confidence evaluation, sign submission/inference/input age, camera handoff and frame age, control, serial I/O, processing-rate wait, synchronous AprilTag inference and optional debug/object/traffic-light work. This is experimental: compare against a same-settings baseline and use `--without-arduino` before any physical test. A target FPS is a requested processing rate, not a guarantee.

See [the full multiprocessing experiment notes](docs/MULTIPROCESSING_EXPERIMENT.md).

### Processing FPS vs camera FPS

`--target-fps` limits the desired rate of complete vision-processing cycles; its default is **30**. It does **not** configure the camera's capture rate. Camera settings and the distinction between requested and measured camera FPS are covered in [`python/README.md`](python/README.md).

## Arduino firmware

For the EEPROM/set-based setup used by this project, the selected sketch is:

```text
arduino/new_main_adaptive_pwm_with_savingPulseInEEPROM
```

This file is stored without a `.ino` extension. With this firmware, leave `--arduino-config` out: City and Race send their configured pulse sequences through `set left` and `set right`, and Race uses the firmware's `save` command to persist them. The strict `hello`/`cfg` hardware-contract handshake is a separate path for `arduino/main_configurable_v1.ino` and must not be assumed to apply to the selected EEPROM/set-based firmware.

The selected sketch's adaptive-PWM and optional encoder-telemetry behavior, sensor validity details, and limitations are described in [`arduino/README-adaptive-features.md`](arduino/README-adaptive-features.md). Firmware variants and general protocol notes are in [`arduino/README.md`](arduino/README.md).

## Tests

Run the hardware-free unit tests from the repository root:

```bash
PYTHONPATH=python python -m unittest discover -s python/test -p 'test_unit_*.py' -v
```

Tests do not replace hardware validation. Before a real run, check steering direction, sensor readings, stop behavior, and the selected firmware with the wheels raised or at very low speed.

## Documentation map

- [Python runtime, CLI, camera, configuration, stream, and test guide](python/README.md)
- [Arduino firmware overview and protocol](arduino/README.md)
- [Selected adaptive-PWM firmware notes](arduino/README-adaptive-features.md)

## License

See [`LICENSE`](LICENSE) for the project license.
