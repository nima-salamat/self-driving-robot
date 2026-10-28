# Performance and Frame Freshness

## The rates are not the same

The runtime has several different rates and latencies:

- **Camera FPS:** measured frame delivery from the configured camera backend.
- **Target processing FPS:** desired rate of complete perception/control cycles; default is 30 FPS when no value is saved, and an explicit `--target-fps` overrides the active mode JSON.
- **Measured loop FPS:** what the full runtime actually achieves after perception, control, I/O and waiting.
- **Stream display/update rate:** browser/network presentation, separate from the camera sensor and control loop.
- **Frame/result age:** how old a camera frame or detector result is when consumed.

A target is a requested scheduling rate, not a guarantee. A camera may deliver fewer frames than requested, and the loop may be slower than the camera or target when a synchronous stage is expensive.

## Performance diagnostics

Start with hardware actuation disabled:

```bash
python python/main.py --mode race --without-arduino --performance --target-fps 40
```

The performance collector in `python/utils/runtime_metrics.py` records bounded-window timings and summary statistics. Depending on the selected mode and enabled features, output includes loop/camera/perception/control/serial timing, lane and confidence evaluation, sign submission/inference/input age, camera handoff and frame age, rate-limit wait, AprilTag work, and optional Stream/object/traffic-light stages.

Compare p50/p95 stage latency, measured camera FPS, loop FPS, dropped/skipped frames and input age. The slowest average is not always the most important stage: a large p95 or an old input frame can indicate occasional stalls or a stale-result problem.

## Optional multiprocessing pipeline

The feature is off by default. Enable camera and sign-worker process isolation with either CLI spelling:

```bash
python python/main.py --mode race --without-arduino --performance --target-fps 40 --multiprocess
# Alias retained for compatibility:
python python/main.py --mode race --without-arduino --performance --target-fps 40 --multiprocess-camera
```

The current process layout is:

- A camera child process owns camera capture, the configured calibration/resize path and publication.
- Raw/resized frame bytes are published in a fixed shared-memory latest-frame slot, protected by a short lock. Frame bytes do not travel through a normal multiprocessing queue.
- The parent runtime skips obsolete camera sequence numbers rather than creating an unbounded frame backlog.
- A separate sign-inference worker accepts ROI requests, runs inference and publishes results. There is at most one inference in flight and at most one waiting request; stale waiting work is replaced or skipped.
- The parent remains responsible for lane perception, mode decisions, STOP/phase handling, steering, speed decisions and Arduino I/O.

In multiprocessing mode, the sign-submission cadence gate may be bypassed to keep inference input fresh. Detector confidence thresholds, area filters and mode safety checks are separate and remain in force. The default ONNX intra-op thread budget for the process-isolated sign worker is two; tune with `--sign-intra-op-threads N` while monitoring CPU contention.

## Profiling workflow

1. Use the same mode, camera backend/resolution, lane detector, target FPS, model, debug settings and run duration for baseline and candidate.
2. Use `--without-arduino` during initial comparisons so a benchmark does not actuate the robot.
3. Record measured camera FPS, loop FPS, stage p95 and frame/result age. Repeat runs; one short sample is not a stable benchmark.
4. Compare the multiprocessing path both with and without optional expensive stages (for example, AprilTag or dashboard visualization), changing only one variable at a time.
5. Test thread budgets on the actual target hardware. More worker threads can lower rather than increase throughput when camera, OpenCV and ONNX compete for the same CPU cores.
6. Re-test shutdown and restart paths after changing worker lifecycle code.

## Common bottlenecks

- **Camera delivery lower than requested:** check the backend's supported sensor mode and the camera's measured delivery rate.
- **High lane-processing latency:** inspect frame size, ROI geometry, detector choice and debug visualization.
- **Old sign results:** inspect inference duration and `sign_input_age`; fewer stale jobs are more useful than a large backlog of queued images.
- **High CPU contention:** compare worker thread counts, OpenCV threads and enabled visualizations.
- **Dashboard overhead:** compare with `--stream` disabled; request access logs are off by default and should be enabled only while troubleshooting HTTP polling.
- **AprilTag latency:** the current AprilTag stage may run synchronously in the mode loop; measure it separately before assuming sign multiprocessing isolates all perception work.

Do not infer safety from FPS alone. Frame freshness, false detections, camera geometry, steering correctness and actual stopping behavior require separate validation.
