# Safety and Troubleshooting

## Safety boundary

This is a prototype robotics stack. Unit tests, camera previews and simulator runs do not establish safe physical behavior. Real steering geometry, braking distance, sensor placement, firmware watchdog behavior, traction, battery state and control latency depend on the hardware and environment.

Use a physical emergency stop or power isolation method appropriate to the robot. The Stream dashboard's STOP action is a software run-level request, not a hardware emergency stop. A serial ACK, successful write or virtual simulator command is not proof that an actuator reached its target.

## Before a physical run

1. Verify the uploaded Arduino sketch and its protocol compatibility with the selected Python command path.
2. Confirm servo center, direction and limits with the wheels raised; the configured center is not a sensor feedback value.
3. Check each ultrasonic/range sensor's orientation and validity. A no-echo/invalid reading must not be interpreted as clear space.
4. Check encoder pulses, sign/lane detector freshness and camera frame age.
5. Run Python preflight and hardware-free checks before enabling motion.
6. Test STOP, resume, power/reset, serial disconnect and reconnection in a controlled area.
7. Start at low speed and keep a person able to physically disable motor power.

Example startup diagnostics and vision-only run:

```bash
python python/main.py --mode race --preflight
python python/main.py --mode race --without-arduino --performance
```

## Common failures

### No camera or black/stale Stream image

- Confirm the selected backend: `picam`, `webcam` or `opencv`.
- For USB/OpenCV backends, check the camera index; `--camera-index` does not select a Picamera2 camera.
- Check camera initialization errors, measured camera FPS, frame sequence/age and JPEG/frame endpoint responses.
- Verify capture dimensions, channel order, resize path and calibration artifact location.
- Compare with the Stream disabled to isolate browser/network overhead from the processing loop.

### Arduino unavailable or reconnect loop

- Check board, cable, serial device path, baud rate and operating-system port permissions.
- Confirm the firmware generation before enabling `--arduino-config`; the strict hardware contract only applies to matching configurable firmware.
- Enable `--read-arduino-output` or DEBUG logs to inspect telemetry/connection state.
- Use `--without-arduino` only for diagnostics; it does not validate physical actuation.
- Do not assume a reconnect or a successful serial write means the robot is safely stopped. Test reconnection behavior on the actual firmware with motion constrained.

### Steering appears reversed or unstable

- Verify servo minimum/center/maximum, direction mapping and linkage with the wheels raised.
- Confirm the mode is loading the intended JSON profile.
- Inspect lane ROI/BEV geometry and debug overlays before changing PID gains.
- Change one variable at a time and validate City/Race separately.
- For odometry or adaptive obstacle avoidance, use measured pulse distance, wheelbase and road-wheel-angle calibration; generic estimates can be misleading.

### Lane detection is missing or noisy

- Inspect the original and resized frame, calibration state, ROI boundaries and camera mount.
- Compare the default detector on saved frames before switching to BLSF beta or ML lane detection.
- Confirm model files, runtime dependencies, preprocessing and output decoding.
- Avoid solving a performance problem by reducing confidence thresholds or bypassing freshness checks without a focused safety review.

### Sign inference is delayed or stale

- Inspect inference duration, result age and the async/process detector status.
- Compare one setting at a time: target processing rate, ONNX intra-op thread budget, resolution and optional synchronous stages.
- The multiprocessing path is experimental; ensure workers exit and restart cleanly.
- Do not equate the newest available inference result with a current frame unless its age is within the configured limit.

### Stream controls are unavailable or reject changes

- Confirm the Stream server was started with `--stream`.
- Check whether `--stream-read-only` disabled mutation endpoints.
- Check mode capabilities and backend-specific settings before assuming an editor field exists.
- Inspect validation errors and ensure a setting is being written to the active physical or simulator profile.

## Network security

The main Stream server binds to loopback by default. Any non-loopback bind requires both `STREAM_USERNAME` and `STREAM_PASSWORD`; plain HTTP still does not encrypt credentials in transit, so use a trusted LAN or an HTTPS reverse proxy. Do not expose a control-enabled dashboard or calibration service directly to the public internet. The separate calibration web service has no built-in authentication and can capture/clear images, adjust camera settings and start calibration; keep it on loopback or a trusted isolated network.

Use `--stream-read-only` for monitoring that does not require mutations. Keep credentials, private images, raw datasets and calibration artifacts out of public commits unless they are intentionally meant to be shared.

## Traffic-light gate

The City traffic-light crosswalk gate is disabled unless `--traffic-lights` is specified. With the gate enabled, it requires 8 GREEN observations among 10 distinct fresh frames and the latest result must also be GREEN. The wait-before-check option does not bypass this confirmation. Validate HSV thresholds, lighting, camera exposure and the full gating path using representative recordings and controlled tests before considering physical operation.
