# Project Documentation

This directory contains the architecture and engineering guides for the current repository. The root README is the quick-start entry point; the Python and Arduino READMEs remain the detailed component-level references for their respective code trees.

## Start here

| Guide | Use it when |
|---|---|
| [Architecture](ARCHITECTURE.md) | You need the runtime lifecycle, data flow, mode boundaries, or extension points. |
| [Module Reference](MODULES.md) | You need to find the implementation responsible for a feature. |
| [Perception Pipeline](PERCEPTION.md) | You are working on camera frames, lanes, signs, traffic lights, crosswalks, or AprilTags. |
| [Configuration](CONFIGURATION.md) | You need to understand mode JSON files, CLI overrides, and simulator profiles. |
| [Arduino Integration](ARDUINO_INTEGRATION.md) | You are changing serial transport, firmware commands, telemetry, or hardware profiles. |
| [Stream Dashboard](STREAM_DASHBOARD.md) | You are working on the live dashboard, editor, APIs, logs, or runtime controls. |
| [Simulator Modes](SIMULATORS.md) | You are adding or troubleshooting CARLA or AVIS Engine support. |
| [Performance](PERFORMANCE.md) | You are profiling frame age, loop latency, camera capture, or asynchronous sign inference. |
| [Dataset and Calibration](DATASET_AND_CALIBRATION.md) | You are calibrating the camera, collecting sign images, training a detector, or tuning lanes offline. |
| [Testing and Development](TESTING.md) | You need the supported test commands and development checks. |
| [Safety and Troubleshooting](SAFETY_AND_TROUBLESHOOTING.md) | You need a preflight, hardware-test, or fault-isolation checklist. |

## Component references

- [Python runtime guide](../python/README.md)
- [Arduino firmware overview and protocol notes](../arduino/README.md)
- [Selected adaptive-PWM firmware notes](../arduino/README-adaptive-features.md)
- [Root quick start](../README.md)

## Documentation rules

- Treat source code on the checked-out branch as authoritative when a guide and implementation disagree.
- Run `python python/main.py --help` to confirm the exact CLI supported by that checkout.
- The physical City/Race modes and simulator modes share parts of the perception stack, but they do not have identical lifecycle, sensor, or safety behavior.
- A successful unit test or simulator run does not prove that real-world motion is safe. Physical validation must be performed separately and conservatively.
- Keep documentation in English and update the relevant guide whenever changing a CLI flag, module contract, data format, or mode capability.
