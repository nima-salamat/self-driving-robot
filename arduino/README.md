# Arduino Firmware

This directory contains multiple independent firmware generations. Existing firmware files are kept intact unless explicitly documented otherwise.

## Firmware matrix

| Firmware | Hardware configuration | Python contract | Main purpose |
|---|---|---|---|
| \`main.ino\` | Hard-coded in firmware | No | Legacy firmware |
| \`main_Blocking.ino\` | Hard-coded in firmware | No | Blocking legacy implementation |
| \`main_nonBlocking.ino\` | Hard-coded in firmware | No | Original non-blocking implementation |
| \`main_nonBlocking_v2.ino\` | Hard-coded in firmware | No | Hardened fixed-pin non-blocking implementation |
| \`main_configurable_v1.ino\` | Supplied by Python at startup | Yes | Configurable firmware with strict hardware validation |

## Recommended development model

\`main_configurable_v1.ino\` separates two concerns:

1. The firmware implements hardware capabilities and safety logic.
2. Python supplies the physical hardware layout for a specific robot.

Changing the wiring therefore does not require creating another firmware build, as long as the new layout is supported by the firmware.

## Supported modules

The firmware currently supports these module types:

~~~text
motor       maximum 4
servo       maximum 4
ultrasonic  maximum 8
encoder     maximum 4
tm1638      maximum 1
~~~

The implementation targets the Arduino Mega 2560.

### Motor

Each motor has an independent PWM and direction pin:

~~~json
{
  "type": "motor",
  "id": 0,
  "pwm": 10,
  "dir": 12
}
~~~

Motor IDs must be contiguous starting at zero.

### Servo

Each servo defines its pin and safe angular range:

~~~json
{
  "type": "servo",
  "id": 0,
  "pin": 9,
  "min": 30,
  "max": 150,
  "center": 90
}
~~~

### Ultrasonic

Ultrasonic sensors use a logical name plus TRIG/ECHO pins:

~~~json
{
  "type": "ultrasonic",
  "name": "right",
  "trig": 6,
  "echo": 7
}
~~~

For compatibility with the current Python controller, the front sensors should be named:

~~~text
left
right
~~~

An additional sensor can use:

~~~text
side
~~~

Names are configurable; Python compatibility currently depends on the standard \`left\` and \`right\` names for obstacle logic.

### Encoder

Encoders use an interrupt-capable Arduino pin:

~~~json
{
  "type": "encoder",
  "id": 0,
  "pin": 2
}
~~~

### TM1638

TM1638 is optional:

~~~json
{
  "type": "tm1638",
  "stb": 26,
  "clk": 28,
  "dio": 30,
  "force_stop_button": 0,
  "resume_button": 7
}
~~~

If TM1638 is omitted, the firmware simply disables that feature.

## Hardware validation

The Arduino validates the proposed configuration before enabling normal runtime control.

Validation includes:

- Module count limits.
- Contiguous motor, servo, and encoder IDs.
- Pin conflicts.
- PWM requirements for motor pins.
- Interrupt capability for encoder pins.
- Servo range validity.
- TRIG/ECHO conflicts.
- Duplicate ultrasonic names.
- Supported safety-option ranges.
- Configuration fingerprint equality.

A rejected configuration produces an error such as:

~~~text
ERR CFG PIN_CONFLICT_10
~~~

The hardware configuration is not activated after a validation failure.

## Python handshake

The configurable firmware starts by identifying itself:

~~~text
HELLO main_configurable_v1 1 mega2560
~~~

Python then sends the selected profile:

~~~text
cfg begin mega2560_default
cfg motor 0 10 12
cfg motor 1 11 13
cfg servo 0 9 30 150 90
cfg encoder 0 2
cfg ultrasonic left 4 5
cfg ultrasonic right 6 7
cfg ultrasonic side 8 24
cfg tm1638 26 28 30 0 7
cfg option stop_distance_cm 35
cfg option pulse_stop_distance_cm 10
...
cfg end mega2560_default <FNV32>
~~~

The Arduino validates the entire configuration and echoes accepted values:

~~~text
CFG ECHO mega2560_default motor 0 10 12
CFG ECHO mega2560_default servo 0 9 30 150 90
...
CFG READY mega2560_default <FNV32>
~~~

Python considers the contract valid only when all of these match:

- Firmware ID.
- Protocol version.
- Board ID.
- Every accepted module.
- Every accepted option.
- Final FNV-1a fingerprint.

## Runtime commands

After the contract succeeds, the current controller-compatible commands are:

~~~text
motor 200
motor -200
motor 0

servo 90
servo 0 90

stop
resume
heartbeat

left
right

set left <pulse sequence>
set right <pulse sequence>
save left
save right
load

status
u
lane auto
lane manual
lane stop
~~~

The `left` and `right` commands are directional signal events. They do not start a lane-change maneuver. Automatic lane changes are controlled by the lane state machine.
  
Pulse groups use:

~~~text
f <speed> <pulses> <angle>
b <speed> <pulses> <angle>
~~~

Multiple pulse groups can be sent in a single line.

## Lane automation

When lane automation is enabled:

1. A front obstacle detected by ultrasonic sensors named `left` or `right` can trigger the configured left-lane sequence.
2. While the robot is in the left lane, an ultrasonic sensor named `side` can trigger the configured return-to-right sequence.
3. A return sequence completes based on encoder pulses instead of a fixed wall-clock duration.
4. `lane manual` disables automatic lane changes and leaves obstacle handling to the explicit stop/resume path.

Control commands:

~~~text
lane auto
lane manual
lane stop
~~~

The feature requires at least one configured encoder because lane sequences are pulse-based.

## Safety features

The configurable firmware includes:

- Host heartbeat timeout.
- Front obstacle stop.
- Pulse pause/resume when a configured front sensor is too close.
- Encoder stall timeout.
- Direction dead-time.
- Fixed-size serial input buffering.
- AVR watchdog support.
- Optional TM1638 force-stop and resume controls.
- Configurable lane-change and side-return thresholds.

## Example profile

The repository contains a working profile for the current Mega 2560-style wiring:

~~~text
python/arduino_configs/mega2560_default.json
~~~

Start Python with strict validation:

~~~bash
python python/main.py --mode race --arduino-config python/arduino_configs/mega2560_default.json
~~~

See the Python README for the complete command-line workflow.

## Important compatibility notes

\`main_nonBlocking.ino\` and \`main_nonBlocking_v2.ino\` remain separate firmware generations.

The configurable firmware has its own protocol contract and should be paired with its matching Python profile.

Do not assume that a profile for \`main_configurable_v1.ino\` can be used with another firmware generation.
