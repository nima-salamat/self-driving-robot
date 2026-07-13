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
└── libraries/               # Custom libraries
    ├── UltrasonicSensor/    # Distance measurement
    ├── PulseQueue/          # Command queue
    └── Encoder/             # Speed measurement
```

### Arduino Communication Protocol

Commands are sent as single-character strings:
- `F` - Forward
- `B` - Backward
- `L` - Turn left (servo)
- `R` - Turn right (servo)
- `S` - Stop
- `+` - Increase speed
- `-` - Decrease speed
- `U` - Update sensor data (returns JSON)

**Response Format**:
```json
{
  "motorSpeed": 200,
  "servo": 90,
  "ultraLeft": 45,
  "ultraRight": 42,
  "ultraSide": 35,
  "encoder": 1250
}
```

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

1. Open `arduino/main_nonBlocking.ino` in Arduino IDE
2. Install required libraries (if not pre-installed):
   - UltrasonicSensor (custom)
   - PulseQueue (custom)
   - Encoder (custom)
   - Servo (built-in)
3. Upload to your Arduino board
4. Note the COM port (e.g., `COM3` on Windows, `/dev/ttyUSB0` on Linux)

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

### Serial Connection Details

| Parameter | Value |
|-----------|-------|
| Baud Rate | 9600 |
| Timeout | 2 seconds |
| Handshake | CTS/RTS |

### Command Flow

```
Python App
    ↓
[Vision Processing + Control Logic]
    ↓
[Generate Motor/Servo Commands]
    ↓
Arduino Serial Handler
    ↓
Arduino Board
    ↓
[Sensor Reading + Motor Control]
    ↓
JSON Response
    ↓
Python App
```

### Sensor Data Update

To get current sensor readings:

```python
# Python side (via arduino_connection.py)
sensor_data = arduino.read_sensors()  # Sends 'U' command
# Returns dict: {motorSpeed, servo, ultraLeft, ultraRight, ultraSide, encoder}
```

---

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
