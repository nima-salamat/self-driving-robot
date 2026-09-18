# Python & Arduino Integration - Self Driving Robot

This document covers the Python and Arduino components of the Self Driving Robot project. These components work together to enable autonomous navigation through computer vision, sensor processing, and motor control.


## 📋 Table of Contents
- [Demo](#demo)
- [Architecture Overview](#architecture-overview)
- [Arduino Component](#arduino-component)
- [Python Component](#python-component)
- [Setup & Installation](#setup--installation)
- [Usage](#usage)
- [Communication Protocol](#communication-protocol)
- [Troubleshooting](#troubleshooting)

---
## Demo

https://github.com/user-attachments/assets/ad7efa66-dcdb-4234-98d1-214cd702bc16

---

## 🏗️ Architecture Overview

The system is built on a two-tier architecture:

```
┌─────────────────────────────────────────────┐
│         PYTHON (Main Controller)            │
│  - Vision Processing (Camera)               │
│  - Traffic Sign Detection                   │
│  - PID Control Logic                        │
│  - Mode Management (City/Race)              │
│  - Serial Communication Handler             │
└──────────────┬──────────────────────────────┘
               │ Serial Communication (USB)
               │
┌──────────────▼──────────────────────────────┐
│      ARDUINO (Motor & Sensor Controller)    │
│  - Motor Control (PWM)                      │
│  - Servo Control (Steering)                 │
│  - Ultrasonic Distance Sensors              │
│  - Encoder (Speed Measurement)              │
│  - Non-blocking Command Processing          │
└─────────────────────────────────────────────┘
```

---

## 🤖 Arduino Component

### Overview
The Arduino handles real-time motor control, sensor monitoring, and obstacle detection. It operates independently with non-blocking I/O to ensure responsive command handling.

### Hardware Components

| Component | Pin(s) | Purpose |
|-----------|--------|---------|
| **Motor 1** | IN1(10), M1(12) | Forward direction & speed control |
| **Motor 2** | IN2(11), M2(13) | Forward direction & speed control |
| **Servo** | Pin 9 | Steering control (10-170°) |
| **Encoder** | Pin 2 (REED) | Wheel speed measurement |
| **Ultrasonic Left** | Trig(4), Echo(5) | Front-left distance sensor |
| **Ultrasonic Right** | Trig(6), Echo(7) | Front-right distance sensor |
| **Ultrasonic Side** | Trig(8), Echo(24) | Side distance sensor |

### Key Features

- **Non-blocking Motor Control**: Asynchronous command processing prevents blocking operations
- **Multiple Sensor Input**: Handles 3 ultrasonic sensors + encoder simultaneously
- **Servo Steering**: Smooth servo control with configurable range (10-170°)
- **Safety Limits**: Automatic obstacle detection with configurable stop distances
- **Encoder Support**: Dual modes - HALL sensor (5000µs debounce) or laser sensor (0µs debounce)

### File Structure

```
arduino/
├── main.ino                 # Primary firmware
├── main_Blocking.ino        # Blocking (legacy) version
├── main_nonBlocking.ino     # Non-blocking version (recommended)
├── main_nonBlocking_v2.ino  # Hardened fixed-pin version
├── main_configurable_v1.ino # Configurable firmware with Python hardware-contract handshake
└── libraries/               # Custom libraries
    ├── UltrasonicSensor/    # Distance measurement
    ├── PulseQueue/          # Command queue
    └── Encoder/             # Speed measurement
```

### Arduino Communication Protocol

The current Python runtime uses 115200 baud and line-based commands with the non-blocking firmware family.

Typical current commands:

~~~text
motor 200
servo 90
stop
resume
left
right
set left <pulse sequence>
set right <pulse sequence>
save left
save right
status
heartbeat
~~~

Current telemetry is a six-field line:

~~~text
<lane> <motion> <right_distance_cm> <left_distance_cm> <loop_hz> <pulse_active>
~~~

The legacy single-character/JSON protocol belongs to older Arduino firmware and is not the current Python contract. See [arduino/README.md](arduino/README.md) for firmware differences.

---

## 🐍 Python Component

### Overview
The Python application handles high-level decision making, computer vision processing, and autonomous mode management. It communicates with Arduino via serial connection and implements two operational modes: City and Race.

### Project Structure

```
python/
├── main.py                          # Entry point with argument parsing
├── base_config.py                   # Base configuration
├── requirements.txt                 # Dependencies
│
├── modes/                           # Operational modes
│   ├── city/
│   │   ├── config_city.py          # City mode configuration
│   │   └── city.py                 # City mode logic
│   └── race/
│       ├── config_race.py          # Race mode configuration
│       └── race.py                 # Race mode logic
│
├── vision/                          # Computer vision processing
│   ├── camera.py                   # Camera capture & initialization
│   ├── vision_processing.py        # Base vision processor
│   ├── city_vision_processing.py   # City-specific vision (lane detection)
│   ├── race_vision_processing.py   # Race-specific vision
│   ├── traffic_light.py            # Traffic light detection
│   └── apriltag.py                 # AprilTag marker detection
│
├── controller/                      # Motion control
│   ├── controller.py               # Main controller
│   └── pid_controller.py           # PID controller implementation
│
├── arduino/                         # Serial communication
│   └── arduino_connection.py       # Arduino serial handler
│
├── manager/                         # Output management
│   └── output_manager.py           # Video stream & display manager
│
├── stream/                          # Web streaming (optional)
│   ├── template.py                 # Flask templates
│   └── __init__.py                 # Flask app
│
├── traffic_sign_detector/           # Traffic sign recognition
│   └── detector.py                 # Sign detection model
│
├── train_sign_detector/             # Model training
│   ├── main.py                     # Training entry point
│   └── classification.py           # Classification logic
│
├── utils/                           # Utility modules
│   ├── parser.py                   # Command-line argument parser
│   ├── config_mode.py              # Configuration utilities
│   ├── json_config.py              # JSON config handling
│   ├── fps.py                      # FPS counter
│   ├── decorators.py               # Utility decorators
│   └── camera_calibration.py       # Camera calibration
│
├── calibration/                     # Camera calibration
│   ├── capture_calibration_images.py  # Collect calibration frames
│   └── calibrate_camera.py         # Run calibration
│
└── test/                            # Unit tests
    ├── test_traffic_light.py       # Traffic light tests
    ├── test_stream.py              # Stream tests
    ├── test_manual_control.py      # Manual control tests
    └── test_apriltag.py            # AprilTag tests
```

### Key Features

#### Vision Processing
- **Lane Detection**: Identifies road lanes for autonomous navigation (City mode)
- **Traffic Light Detection**: Detects and responds to traffic signals
- **AprilTag Recognition**: Locates and interprets marker-based navigation points
- **Traffic Sign Detection**: ML-based sign recognition and classification
- **Camera Calibration**: Distortion correction using checkerboard calibration

#### Control System
- **PID Controller**: Proportional-Integral-Derivative control for smooth steering
- **Speed Management**: Adaptive speed control based on obstacles and mode
- **Servo Control**: Steering angle management

#### Operational Modes

**City Mode**:
- Lane-following behavior
- Traffic light compliance
- Obstacle avoidance using ultrasonic sensors
- Traffic sign recognition

**Race Mode**:
- High-speed autonomous navigation
- Optimized steering response
- Minimal processing overhead
- AprilTag-based waypoint detection

#### Dependencies

```
requests          # HTTP requests (API communication)
flask             # Web streaming interface
opencv-python     # Computer vision & image processing
serial            # Serial communication with Arduino
```

---

## 🔧 Setup & Installation

### Requirements

- **Python**: 3.8+
- **Arduino**: Compatible board (Uno, Mega, etc.)
- **USB Connection**: Serial port for Arduino communication

### Step 1: Arduino Setup

1. Choose the firmware documented in [arduino/README.md](arduino/README.md).
2. For `main_configurable_v1.ino`, the hardware layout is supplied by Python at startup; the firmware uses the Arduino core plus Servo and EEPROM.
3. Upload the selected firmware to your Arduino board.
4. Note the serial port (for example `COM3` on Windows or `/dev/ttyUSB0` on Linux).

### Step 2: Python Environment

```bash
# Navigate to python directory
cd python

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r ../requirements.txt
```

### Step 3: Camera Calibration (Recommended)

```bash
# Capture calibration images
python capture_calibration_images.py

# Run calibration
python calibrate_camera.py
```

---

## 🚀 Usage

### Basic Launch

```bash
cd python

# City mode (lane-following)
python main.py --mode city

# Race mode
python main.py --mode race
```

### Command-Line Arguments

```bash
python main.py [OPTIONS]

Options:
  --mode {city, race}      Operating mode (default: city)
  --debug                  Enable debug output
  --stream                 Enable web video stream
  --fps                    Show FPS counter
  --without-arduino        Run without Arduino connection (simulation)
  --arduino-config PATH    Enable strict Arduino hardware-contract handshake
  --arduino-contract-timeout SECONDS
                           Timeout for each contract exchange (default: 3)
```

### Examples

```bash
# Run city mode with debug output
python main.py --mode city --debug

# Run race mode with FPS display and streaming
python main.py --mode race --fps --stream

# Test without Arduino (vision only)
python main.py --mode city --without-arduino --debug
```

### Manual Control Testing

```bash
python test/test_manual_control.py
```

### Traffic Light Detection Test

```bash
python test/test_traffic_light.py
```

---

## 📡 Communication Protocol

The current Python runtime communicates with the Arduino at **115200 baud** using line-based commands.

### Host commands

The active controller uses commands such as:

```
motor 200
servo 90
stop
left
right
set left <pulse sequence>
set right <pulse sequence>
save left
save right
status
heartbeat
```

A pulse group has the form:

```
f <speed> <pulses> <angle>
b <speed> <pulses> <angle>
```

Multiple pulse groups can be sent in one line.

### Telemetry

The current firmware reports six fields:

```
<lane> <motion> <right_distance_cm> <left_distance_cm> <loop_hz> <pulse_active>
```

Example:

```
R F 25 30 1000 0
```

Python drains telemetry asynchronously through `ArduinoConnection`; it does not wait for a reply after every control command.

### Host heartbeat / fail-safe

Python sends a `heartbeat` line periodically while the serial connection is active.

The active `main_nonBlocking_v2.ino` firmware uses a 500 ms host-heartbeat watchdog. When host liveness expires while motion or a pulse sequence is active, the firmware clears the pending motion, stops the motors, and centers the steering.

This watchdog is intentionally implemented on the Arduino side because a Python process crash cannot send a final `stop` command.

### Motion history

Python now keeps a bounded in-memory trace of the last **200 commanded individual pulse units** plus a separate semantic event history.

Pulse records include:

- direction
- speed
- steering angle
- pulse index inside the operation
- event name
- source
- timestamp
- metadata

Semantic events can describe boundaries such as:

```
hardcode_lane_change_configured
crosswalk_stop_started
crosswalk_maneuver_started
crosswalk_turn_left
crosswalk_turn_right
crosswalk_straight
lane_lost
```

The history is intentionally passive. It does not make recovery decisions.

The future route-recovery coordinator should be implemented in:

```
python/controller/motion_recovery.py
```

It should use the history to identify a verified safe boundary and replay only a bounded portion of the trace. It must not blindly replay all 200 pulses.

The current history represents **Python-issued commanded pulses**, not guaranteed physical encoder-completed pulses. A future protocol revision can add pulse lifecycle telemetry so Python can distinguish commanded, executing, completed, and aborted motion.

## 🛠️ Troubleshooting

### Arduino Connection Issues

**Problem**: "Serial port not found"
```bash
# List available ports (Windows)
python -m serial.tools.list_ports

# Or manually check:
# Windows: Device Manager → COM ports
# Linux: ls /dev/ttyUSB*
```

**Solution**: Update the port in configuration or pass via `--port` argument

### Camera Issues

**Problem**: "No camera detected"
```bash
# Check camera availability
python -c "import cv2; print(cv2.getBuildInformation())"
```

**Problem**: "Distorted video feed"
- Run camera calibration (see [Setup & Installation](#step-3-camera-calibration-recommended))

### Motor/Servo Not Responding

1. Verify Arduino is receiving commands:
   - Enable `--debug` mode in Python
   - Check serial output in Arduino IDE Serial Monitor

2. Test motor pins directly in Arduino:
   ```cpp
   pinMode(M1, OUTPUT);
   digitalWrite(M1, HIGH);
   delay(1000);
   digitalWrite(M1, LOW);
   ```

3. Check power supply to motors and servo

### Vision Processing Lag

- Reduce frame resolution in `camera.py`
- Disable debug visualization (`--debug` mode)
- Disable web streaming (`--stream` option)

---

## 📚 Additional Resources

- **Arduino Reference**: https://www.arduino.cc/reference/
- **OpenCV Documentation**: https://docs.opencv.org/
- **PID Control Theory**: https://en.wikipedia.org/wiki/Proportional%E2%80%93integral%E2%80%93derivative_controller

---

## 📝 Contributing

When modifying the code:

1. Test changes in both City and Race modes
2. Verify Arduino communication works
3. Update this README if adding new features
4. Run test suite: `python -m pytest test/`

---

## 📄 License

See LICENSE file in the project root.

---

## 🤝 Support

For issues or questions:
1. Check the [Troubleshooting](#troubleshooting) section
2. Review existing test files for usage examples
3. Enable debug mode for detailed diagnostics


## ML Lane Model Benchmarks

The default lane detector is unchanged. ML lane detection is opt-in and disabled unless `--ml-lane-model` is supplied.

List candidates:

```bash
python python/tools/benchmark_lane_models.py --list
```

The two candidate ONNX weights are bundled in the repository and materialized automatically on first use.

Benchmark one candidate on a recorded drive:

```bash
python python/tools/benchmark_lane_models.py \
  --model unet_depthwise_nano \
  --input output/videos/video_1.mp4 \
  --display \
  --frames 300
```

Benchmark directly from camera:

```bash
python python/tools/benchmark_lane_models.py \
  --model unet_depthwise_nano \
  --camera \
  --display
```

To run Race mode with an ML lane model:

```bash
python python/main.py --mode race --ml-lane-model unet_depthwise_nano
```

Available names are:

- `unet_depthwise_nano`
- `unet_depthwise_small`

ML lane detection is not used in the normal runtime unless explicitly enabled. The Arduino firmware and protocol are unchanged.

## Configurable Arduino Hardware Contract

The new opt-in hardware contract is documented separately:

- [arduino/README.md](arduino/README.md)
- [python/README.md](python/README.md)
- Sample profile: [python/arduino_configs/mega2560_default.json](python/arduino_configs/mega2560_default.json)

Start with the contract enabled:

~~~bash
python python/main.py \
  --mode race \
  --arduino-config python/arduino_configs/mega2560_default.json
~~~

The Python side verifies the Arduino firmware ID, protocol version, board, echoed module configuration, and a shared FNV-1a fingerprint before Race/City startup.

## Operational Diagnostics

The Python runtime includes startup pre-flight checks, rotating logs, runtime health metrics, hardware-free tests, and an offline vision replay tool.

### Pre-flight

Run diagnostics without entering the control loop:

```bash
python python/main.py --mode race --preflight
python python/main.py --mode city --preflight
```

The check covers core Python dependencies, configured sign-model requirements, output storage, camera initialization and frame shape, the configured serial port, the monotonic clock, and the configured stream port.

### Performance and health

Enable periodic performance diagnostics:

```bash
python python/main.py --mode race --performance
```

When streaming is enabled, the dashboard exposes runtime health and performance information, including loop timing, camera/perception/serial timing, hardware state, asynchronous sign-worker status, and recording queue statistics.

The stream binds to `127.0.0.1:5000` by default. Dashboard controls that modify runtime settings are disabled unless `--stream-control` is explicitly supplied.

### Hardware-free tests

```bash
PYTHONPATH=python python -m unittest discover -s python/test -p 'test_unit_*.py' -v
```

The suite covers the PID controller, configuration validation, runtime metrics, health evaluation, disabled serial transport behavior, and sign-worker failure recovery. GitHub Actions runs compilation and this hardware-free suite.

### Offline vision replay

Replay recorded video without constructing the robot controller or opening Arduino serial:

```bash
python python/replay.py --mode race --input output/videos/video_1.mp4
python python/replay.py --mode city --input output/videos/video_1.mp4 --output replay.mp4
```

The replay reports frame count, perception-valid ratio, processing rate, and loop/perception timing statistics.