# Multiprocessing Camera and Sign Inference Experiment

## Baseline and measured camera experiment

The initial architecture review used main commit `05970cb7c11211cb6b2fe6fa297a4daa5f4d46a8`. City and Race previously owned camera capture, lane perception and control in one loop; sign inference used a single worker thread with a one-item waiting queue.

On a Raspberry Pi 4, the operator compared these two short Race runs at the same 640x480 camera mode and `--target-fps 40`, both using `--without-arduino --performance`:

- Without multiprocessing: reported FPS was mostly about 19–24 (approximate mean of the steady samples: 21.2).
- With camera multiprocessing: reported FPS was mostly about 22–29 (approximate mean of the steady samples: 24.5).
- Mean loop duration decreased from about 47 ms to about 40 ms.

These are only short, user-supplied runs, not a controlled benchmark or proof of long-run stability. Importantly, this comparison predates the new sign-inference process: it measures the camera-process experiment only, so the combined camera-plus-sign mode still needs a fresh Pi benchmark. The earlier Ctrl+C output also showed the camera worker being interrupted inside OpenCV resize; the camera child now ignores SIGINT and relies on the parent shutdown event for cleanup. A hardware shutdown retest is still required.

## Opt-in architecture

Use `--multiprocess` or the backward-compatible `--multiprocess-camera` flag. Both options enable camera capture and sign inference process isolation together; the feature remains disabled by default.

### Camera process

A spawned child is the sole owner of the Picamera2/OpenCV camera and performs capture, calibration and resizing. It publishes raw and resized frame data into a fixed-size shared-memory slot guarded by a small lock. The parent reads the latest published sequence and skips obsolete sequences rather than accumulating a camera queue. Camera hardware controls and frame-rate changes are forwarded to the owner process.

All lane-based navigation, phase transitions, stop-hold rules, steering/speed decisions and serial communication remain in the parent City/Race runtime.

### Traffic-sign process

When sign inference is enabled, a spawned worker loads the configured YOLO or SVM detector once. The main loop submits each active loop frame instead of waiting for `READ_SIGN_THRESHOLD`. The worker permits one inference in flight plus at most one waiting ROI frame. A newer frame replaces the waiting frame, so a slow inference worker does not build an ever-older backlog.

Only the cropped sign ROI and inference options cross the process boundary; full debug frames and binary masks do not. Bounding-box overlays are drawn back onto the parent frame. The existing model confidence, Race STOP confidence, sign-area filtering, phase gates and StopSignHold logic remain in place. The opt-in changes how often work is submitted, not the detector's confidence threshold or what constitutes an accepted sign.

A process boundary is not guaranteed to improve FPS on every device: camera/ROI copying, process scheduling and CPU contention cost time. The newly expanded metrics are meant to show whether it helps under the actual camera/model workload.

## Performance diagnostics

Run with `--performance`. The headline reports cycle FPS, loop mean/p95/max, camera p95, combined perception p95, control p95, serial p95 and the target processing rate. Additional logs expose available timings for:

- Lane pipeline and confidence evaluation.
- Sign submission, inference latency and age of its input frame.
- Parent-side camera handoff/copy time and camera-frame age when using the shared-memory camera.
- Skipped camera sequences, measured camera FPS and sign-worker liveness/queue/counters.
- Processing-rate wait, debug/stream rendering, object detection, synchronous AprilTag detection, and the optional City traffic-light detector.

Counters and stage timers have a finite rolling window; this diagnostics option adds measurement/logging only. Use the p95 values together with frame age and the worker counters, not the target FPS alone, to identify the true bottleneck.

Example comparison commands (hardware-free with respect to motor/Arduino commands):

```bash
python python/main.py --mode race --without-arduino --performance --target-fps 40
python python/main.py --mode race --without-arduino --performance --target-fps 40 --multiprocess
```

Keep camera, model, resolution, lighting, target rate and debug/stream settings identical. Wait for warm-up, collect several runs of at least 30–60 seconds, and compare steady-state samples. Start and stop the process repeatedly to check for resource leaks. Do not consider the multiprocessing path validated for physical movement until it has been tested in a controlled setup.

## Validation status and limitations

- Hardware-free tests cover shared-memory reader behavior, CLI opt-in and the process sign worker handoff.
- Automated tests do not validate Picamera2 driver behavior, real-time sign recall, camera freshness under thermal load, or actual FPS on the Pi.
- The repository's historical baseline test suite has known pre-existing failures; a run must be compared with the same baseline rather than labelled green from compile success alone.
- Physical robot actuation is intentionally excluded from routine validation.
