# Arduino Integration

## Responsibility boundary

Python owns high-level perception and driving decisions. The Arduino firmware owns low-level motor outputs, steering-servo writes, sensor polling, encoder pulse counting and the safety mechanisms implemented by that particular sketch.

The main Python boundary consists of:

- `python/arduino/arduino_connection.py`: serial transport, connection state, background telemetry draining, heartbeat/reconnect lifecycle and command writes.
- `python/controller/controller.py`: high-level movement/steering methods and the controller's use of the serial transport.
- `python/arduino/hardware_contract.py`: optional strict firmware identity and hardware-profile negotiation.
- `python/arduino_configs/mega2560_default.json`: example profile for the configurable-firmware workflow.

The transport is asynchronous: the background reader drains telemetry, while the controller does not require a response after each ordinary command. Telemetry status and command-send success are not equivalent to physical actuator feedback.

## Firmware generations are not interchangeable

The repository contains several independent sketches. Read [the Arduino firmware overview](../arduino/README.md) and the selected sketch before uploading firmware or enabling a protocol option.

In particular:

- The EEPROM/set-based adaptive-PWM sketch named `arduino/new_main_adaptive_pwm_with_savingPulseInEEPROM` is the selected setup described by the root README for the project's pulse-sequence workflow. It is stored without a `.ino` suffix.
- `arduino/main_configurable_v1.ino` implements a separate strict hardware-contract handshake. It identifies its firmware, accepts a profile, validates the proposed pins/modules/options and reports a configuration fingerprint.
- Fixed-pin sketches such as `main_nonBlocking.ino` and `main_nonBlocking_v2.ino` are separate generations. Do not assume that they implement the configurable handshake or every telemetry/ACK extension.

Keep handshake/configuration synchronization disabled unless the uploaded sketch is known to implement the matching contract. The explicit `--arduino-config PATH` option is not a universal auto-detection mechanism.

## Serial transport

The default project serial rate is 115200 baud. The connection module manages reconnect state, buffered newline-delimited telemetry, heartbeat scheduling and connection shutdown. The reader and writer share synchronized serial access to avoid interleaving operations.

Useful diagnostics include:

- `--without-arduino` to run perception/control logic without opening the serial connection.
- `--preflight` to run startup checks and exit before entering the control loop.
- `--read-arduino-output` to print telemetry lines for diagnosis.
- `--log-level DEBUG` for detailed application logs.

The serial device path is platform-specific; check the active mode configuration and operating-system device list instead of assuming `/dev/ttyUSB0` is universal.

## Pulse sequences and motion commands

The pulse-sequence format used by the EEPROM/set-based workflow is a sequence of four-token groups:

```text
f <speed> <pulses> <servo-angle>
b <speed> <pulses> <servo-angle>
```

- `f` indicates forward motion; `b` indicates reverse motion.
- Speed is a PWM-style command.
- Pulses define the segment length used by the selected firmware's encoder logic.
- Servo angle is a requested steering command, not a measurement of the actual road-wheel angle.

Multiple groups may be placed in one configured sequence. JSON validation enforces the format and bounds before accepted configuration values are applied. Do not assume that similarly named commands have identical semantics in every firmware generation.

## Strict configurable-firmware contract

When using `main_configurable_v1.ino`, pass the corresponding JSON hardware profile explicitly:

```bash
python python/main.py --mode race --arduino-config python/arduino_configs/mega2560_default.json
```

The profile describes supported modules such as motors, servos, ultrasonic sensors, encoders and optional TM1638 controls. Firmware validates module limits, IDs, pin conflicts, PWM/interrupt capabilities, servo ranges and supported safety options before accepting the configuration.

The contract requires the reported firmware ID, protocol version, board ID, accepted module/option echoes and final fingerprint to match. A failed contract must not be treated as permission to continue normal motion.

## Telemetry and optional extensions

Telemetry fields and extensions vary by sketch. The adaptive-PWM firmware notes describe the legacy seven-field status line and the opt-in `ODOM1` encoder telemetry extension. The latter includes signed estimated pulses, sample sequence/age and validity fields; it is not equivalent to a direction-sensing encoder or verified physical odometry.

An `ACK RECEIVED` response, where supported, means the firmware consumed a command line; it does not prove the actuator reached a target or a maneuver completed. See [adaptive firmware notes](../arduino/README-adaptive-features.md) and verify extension support in the exact uploaded sketch.

## Hardware validation checklist

Before connecting a wheel-driven robot:

1. Confirm board type, uploaded sketch, serial port, baud rate and pin mapping.
2. Verify that the configured servo center and limits match the actual linkage.
3. Check each sensor's validity and orientation; missing/no-echo measurements must not be interpreted as free space.
4. Test stop, resume and reconnection behavior with the wheels raised or motion mechanically constrained.
5. Start at low speed and verify forward/reverse, steering direction and obstacle-stop response.
6. Do not rely on a software Stream stop or an ACK as a substitute for a physical emergency stop.
