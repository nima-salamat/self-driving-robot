# Multiprocessing Camera Capture Experiment

## Baseline reviewed

This experiment starts from the main branch at commit 05970cb7c11211cb6b2fe6fa297a4daa5f4d46a8. The runtime path was traced through:

- python/main.py: CLI options, mode/config setup, shutdown event and metrics.
- python/modes/city/city.py and python/modes/race/race.py: each owns the synchronous camera/perception/control cycle.
- python/vision/camera.py: Picamera2/OpenCV acquisition, calibration, resize and camera FPS.
- python/vision/city_vision_processing.py, python/vision/race_vision_processing.py and python/vision/ml_lane/detector.py: perception runs in the control process.
- python/traffic_sign_detector/async_detector.py: sign inference already uses a one-item queue in a thread and does not serialize frames between processes.
- python/utils/runtime_metrics.py: current camera, perception, control and whole-loop latency measurements.

## Experiment design

The first experiment isolates camera acquisition rather than moving stateful City/Race control logic into another process. A spawned child owns the camera and performs the existing capture, calibration and resize path. It publishes one raw frame and its resized counterpart into a fixed-size shared-memory slot. The parent copies the latest complete frame under a short lock and skips older sequence numbers rather than queuing stale frames. The control loop and its stop/steering/Arduino semantics remain in the existing process. Camera setting changes use a small control queue; frame bytes never pass through a queue.

The feature is opt-in through --multiprocess-camera, disabled by default, and does not change firmware or serial protocols. Shape mismatches, worker startup failures and invalid frames are treated as capture failures so the existing mode safe-stop path remains authoritative. Shared memory and the camera child are released through the existing Camera.release lifecycle. Picamera2 camera-control updates are forwarded to the process that owns the device.

## Why not move perception/control yet?

The existing vision processors hold per-mode state, and each mode currently consumes a frame and decides steering/speed in the same cycle. Moving inference to an asynchronous process before defining result freshness and deadline rules could increase stale-control latency. The first benchmark should establish whether camera I/O stalls are a meaningful bottleneck before adding more process boundaries.

## Validation

The updated Python CI workflow compiles the project and runs the hardware-free unittest suite. CLI coverage verifies that multiprocessing is strictly opt-in. CI cannot prove target-camera performance; on the Raspberry Pi, compare baseline and experimental runs with the same mode, camera, resolution, target FPS, model and debug/stream configuration. Record camera delivery FPS, complete-loop FPS, and camera/perception p95 durations from --performance. Run first with --without-arduino. Physical motion behavior is intentionally not part of automated tests.
