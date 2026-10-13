---
name: self-driving-robot-engineering
description: Use when understanding, debugging, testing, reviewing, or modifying the self-driving-robot repository, especially Python runtime startup, City/Race control loops, camera and frame streaming, lane/sign/AprilTag perception, configuration, Arduino serial communication, hardware contracts, calibration, or runtime diagnostics.
---

# Self-Driving Robot Engineering

## Mission

Work from the repository's actual implementation and preserve its safety-related behavior. Trace a reported symptom through the complete execution path rather than patching the first suspicious line. Make the smallest justified change and demonstrate it with appropriate tests.

## Read the project map first

For non-trivial work, read these references before editing:

- [Architecture and contracts](references/architecture-map.md)
- [Cross-module debugging playbook](references/debugging-playbook.md)
- [Verification checklist](references/verification-checklist.md)

For a narrow question, read only the sections relevant to the requested subsystem. If a referenced path has changed or is missing, inspect the current tree and update your assumptions; do not invent a replacement path.

## Mandatory workflow

### 1. Establish the actual baseline

From the repository root, inspect:

- Current branch and commit.
- Working-tree status and existing diff.
- The requested behavior, relevant issue context, and any recent changes.
- The current implementation, callers, callees, configs, tests, and CI workflow.

Do not overwrite unrelated changes or assume a previous audit still describes HEAD. Do not create a branch, commit, or push unless the user asked for it or the active task clearly requires it.

### 2. Trace the full behavior path

Start from the real entry point and follow data and control through modules. For runtime issues, the usual top-level path is:

CLI and mode selection → configuration overlays → selected City/Race startup → camera/frame source → perception → control decision → Arduino command/heartbeat → telemetry/health/dashboard → cleanup.

The actual path varies by feature; verify it in the source. Check both the producer and consumer when data appears missing. Inspect error and cleanup paths as well as the happy path.

### 3. Form and test a root-cause hypothesis

Before editing, state the suspected cause and the evidence supporting it. Distinguish:

- Confirmed facts from source or executed tests.
- Hypotheses needing a reproduction.
- Unknowns requiring hardware, camera, or runtime access.

Prefer a small regression test that fails before the fix and passes after it. If a failure is environmental or caused by an incomplete test fixture, prove that from the call path before changing production code.

### 4. Implement a narrow, compatible change

- Preserve existing behavior unless the request explicitly changes it.
- Check City and Race independently whenever code or shared helpers can affect both.
- Preserve configuration precedence and defaults.
- Keep optional features opt-in.
- Preserve safe stop behavior when perception or hardware state is invalid.
- Avoid duplicated sources of truth, broad refactors, unrelated renames, and unrequested dependency changes.
- Treat the Python/Arduino serial format and timing as a protocol contract. Check both sides before modifying it.
- Avoid long blocking work in the control loop; preserve asynchronous ownership and bounded queues.
- Do not remove fallback paths or Windows/no-Arduino support without explicit evidence and a scoped requirement.

### 5. Validate, inspect, and report

Run the most specific relevant tests first, then the repository's hardware-free suite and compile check when feasible. Inspect the final diff and check for unintended changes. Use the exact commands in [Verification checklist](references/verification-checklist.md).

Never say a test passed unless it actually ran and passed. If the available environment cannot run a command, say so and identify the closest verification performed. Do not present static inspection as a runtime or physical-robot test.

## Non-negotiable hardware and configuration rules

1. **Do not move the physical robot as part of routine validation.** Prefer unit tests, fakes, replay, preflight, and read-only diagnostics. Real hardware tests require an explicit user request and a controlled setup.
2. **Do not silently enable Arduino hardware configuration synchronization or handshake.** The hardware-contract flow is opt-in via its explicit CLI/profile path and is intended for firmware implementing that protocol. The fixed-pin `main_nonBlocking_v2.ino` path must not be assumed to support it. Never add automatic handshake attempts to ordinary City/Race startup unless the user explicitly requests that behavior and the firmware compatibility is verified.
3. **Keep safety behavior intact.** If lane perception is invalid or the control path cannot justify movement, do not weaken the stop/fail-safe behavior merely to keep the robot moving.
4. **Do not treat a host-side stop command as the only watchdog.** Understand the firmware heartbeat watchdog and its limits before changing communications or shutdown behavior.
5. **Do not expose unauthenticated control dashboards to untrusted networks.** Existing bind defaults and endpoint behavior must be inspected for the checked-out version before proposing deployment changes.

## Project-specific reasoning rules

- Mode defaults, JSON configuration, and explicit CLI overrides interact. Follow the current precedence in source and test; do not infer runtime configuration from a module's constants alone.
- City and Race share concepts but not every detector, flag, or capability. Similar names such as USE_SIGN, WITH_SIGN, and WITH_APRILTAG are not automatically interchangeable.
- The stream is a consumer of the newest published frame in the current architecture; do not add a second camera owner or turn the HTTP stream into a competing frame producer without proving that is necessary.
- Detector labels, numeric sign class IDs, calibration coordinate conventions, image dimensions, ROI geometry, and Arduino commands are contracts. Search usages and tests before changing them.
- For intermittent problems, inspect thread ownership, queue drops, timeouts, event reset/set paths, shutdown, and resource lifetime.
- For performance problems, measure camera delivery FPS, perception latency, control-loop timing, and stream consumption separately. Do not optimize using a single aggregate FPS number.
- Update docs only after behavior and CLI contracts are confirmed. Keep historical audit findings clearly dated.

## Done means

A task is complete only when the change addresses the evidenced cause, relevant regressions are covered, checks and limitations are reported accurately, and the final diff contains no unrelated edits. Physical behavior remains unverified until tested on hardware under controlled conditions.
