# Cross-Module Debugging Playbook

Use this as a checklist for investigation. Avoid assuming the symptom originates in the subsystem named by the user.

## General sequence

1. Capture the exact symptom, expected behavior, actual behavior, environment, invocation/CLI arguments, and relevant logs.
2. Inspect Git status/HEAD and recent relevant changes.
3. Identify the runtime entry point and effective config values. Include CLI/JSON precedence.
4. Follow the data or command through producer, transformation, consumer, and cleanup.
5. Inspect failure paths, early returns, exceptions, thread/event lifecycle, and stale state.
6. Reproduce with a focused hardware-free test or deterministic fixture if possible.
7. Implement a minimal fix, add a regression test, then run relevant checks and inspect the diff.

Never stop at a function name match. Read the callers, callees, configuration, data shape, and tests that establish its contract.

## Camera opens but the stream has no frames

Trace:

1. Actual launch path and camera CLI/config values.
2. Whether the selected backend opens successfully and returns valid frames.
3. Whether the runtime publishes a new frame, and whether publication is conditional on mode/debug settings.
4. The route that retrieves/encodes the most recent frame.
5. Browser polling, response status/MIME type, image decode, and UI element update.
6. Shutdown/error behavior if frame acquisition fails.

Useful distinctions:

- Camera requested FPS, camera-delivered FPS, perception/control-loop FPS, and browser stream refresh rate are different measurements.
- A dashboard should consume the latest published frame rather than becoming a second camera producer, unless source proves otherwise.
- If binding to 0.0.0.0, print usable local/LAN URLs separately; 0.0.0.0 itself is only a bind target.
- Verify Windows/no-Arduino launch separately from Linux/Raspberry Pi behavior when the bug concerns platform-specific startup.
- Check whether a frame is raw BGR/RGB, already encoded, or otherwise wrapped before changing encoding code.

## City or Race behaves differently from configuration

Trace:

1. Selected mode argument and parser defaults.
2. Mode defaults and relevant mode JSON file.
3. Explicit CLI override detection and merge order.
4. Mode-specific init and loop.
5. Shared helper branches selected by config/capability.
6. The runtime UI/API mutation path if changes occur after startup.

Do not infer effective config from Python constants alone. Write a regression test for omitted CLI values as well as explicit true/false overrides when precedence is the subject.

## Lane detector, BEV, ROI, or steering regression

Trace the complete path:

frame size → crop/ROI selection → optional undistortion → perspective/BEV transform → preprocessing → candidate extraction/model inference → geometric validation → lane/perception result → PID/controller output → stop or motion command.

Check each transform's coordinate system and the shape of its input/output. Confirm whether BEV/ROI setup is reached on every branch; look closely for early returns that skip state refresh or debug overlays. Validate ROI ordering and finite numeric configuration before applying it. Compare City and Race separately because their processors and optional algorithms are not identical.

For detector changes, test at least: valid detection, no lane, malformed/empty result, wrong image shape, and relevant option disabled. A perception-invalid result must not turn into an unverified motion command.

## Sign/AprilTag detector or worker appears stuck

Trace configuration flags to actual detector selection, queue submission, worker execution, result timestamp/ID, consumption by the mode loop, and health reporting. Inspect dropped/replaced queue entries, exceptions, stop/shutdown, and whether counters can remain inconsistent after a job is discarded.

Do not conflate USE_SIGN, WITH_SIGN, and WITH_APRILTAG. Determine which values are canonical in that specific mode and how the parser/config/capability layer maps them. Confirm numeric class labels and their shared mapping across collection, training, and inference before changing labels.

## Arduino commands are not applied or connection does not recover

Trace:

mode startup → controller construction → ArduinoConnection enabled/disabled state → serial open and safe initialization → command writer → newline/flush behavior → MCU parser → firmware state machine → telemetry reader/status → heartbeat/watchdog → close/reconnect.

Check the actual firmware flashed to the board, not only which file appears in Git. A Python-side change does not prove the device has been reflashed.

For reconnect issues, inspect event set/clear order, worker loop conditions, retry/backoff timing, exception branches, connection state transitions, serial object lifetime, and shutdown races. Test with a fake serial port where feasible.

For a hardware-contract error, verify both firmware identity/protocol support and the explicit config/profile argument. Do not "fix" the error by silently enabling or bypassing handshake, accepting a mismatched fingerprint, or synchronizing fixed pins from a profile.

## Dashboard configuration updates are inconsistent

Trace request parsing → type conversion → per-field validation → cross-field constraints → config mutation → persistence → runtime reader. Build the prospective state separately and validate the entire payload before changing live config. Ensure an error response leaves the pre-request state unchanged. Test invalid final fields after valid earlier fields, not only a payload where the first field fails.

Also inspect control exposure: bind host, port, authentication, origin/CSRF behavior, read-only mode, and network trust assumptions.

## Intermittent stalls or unexplained latency

Look for thread ownership, locks held during I/O, unbounded loops, queue eviction, work performed in the control loop, repeated camera open/close, timestamp monotonicity, and incorrect "busy" counters. Separate camera capture timing, perception timing, serial timing, and stream consumer timing. Prefer recorded replay and synthetic workloads over uncontrolled physical runs.

## Cleanup and exception behavior

For every new resource or worker, check both normal and exceptional exits: camera release, serial close, worker stop/join, output writer finalization, dashboard/server shutdown, and pending queue handling. Cleanup must be idempotent where callers may invoke it more than once.

## Required investigation note

Before a significant fix, record:

- Symptom and exact reproduction command.
- Verified execution path and effective config.
- Root-cause evidence.
- Why the proposed change is minimal and safe.
- Regression tests and any untestable hardware assumptions.
