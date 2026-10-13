# Verification Checklist

## Establish state before testing

From the repository root:

~~~bash
git status --short
git branch --show-current
git rev-parse HEAD
git diff --check
~~~

Read existing changes before editing and distinguish them from your own modifications. Do not use reset/clean commands to manufacture a clean tree.

## Python compile check

~~~bash
python -m compileall -q python
~~~

A successful compile confirms syntax/bytecode compilation only. It does not validate imports in the target hardware environment, camera availability, model runtime compatibility, or physical behavior.

## Canonical hardware-free unit suite

The checked-in Python CI workflow documents this command:

~~~bash
PYTHONPATH=python python -m unittest discover -s python/test -p 'test_unit_*.py' -v
~~~

Run it from the repository root with the dependencies expected by the checked-out workflow. The workflow has documented Python 3.11 and installs dependencies including pyserial, NumPy, headless OpenCV, Flask, and ONNX Runtime; verify the active workflow before assuming those are still the exact requirements.

For focused tests, inspect the test names and fixtures first, then run the smallest relevant unittest module or test selection supported by that repository version. Do not invent test paths or assume a pytest command is canonical.

## Targeted regression coverage

Choose tests that match the change:

- Config/parser: defaults, JSON overlay, omitted CLI values, explicit overrides, invalid and contradictory values.
- Camera/stream: backend failure, no frame, fresh frame publication, encoding, endpoint status, browser-visible payload contract.
- City/Race: test affected mode and its sibling mode where shared code is touched.
- Lane/perception: expected frame dimensions, ROI/BEV geometry, valid detection, missing lane, malformed result, safe no-motion result.
- Sign/AprilTag: feature selection, label mapping, disabled options, worker exceptions, queue replacement, result freshness, cleanup.
- Arduino: disabled/no-hardware path, line endings, command grammar, serial exceptions, reconnect state transitions, heartbeat, close during reconnect, contract mismatch.
- Dashboard config: full payload validation, cross-field constraints, atomic failure (no partial mutation), read-only and network-control assumptions.
- Resource lifecycle: repeated close, exceptions during startup, worker termination, camera/serial/output release.

Prefer deterministic fakes and simulation. Avoid brittle sleeps; use events, bounded timeouts, and observable state where possible.

## Hardware-in-the-loop boundary

Do not run a command that can actuate motors, steering, pulse sequences, or firmware changes as a routine test. Such a test requires explicit user authorization and controlled physical setup.

Before an explicitly requested hardware test, review the exact command and active configuration, ensure the wheels/drive mechanism are safely restrained or lifted as appropriate, keep speed low, provide a reachable power cutoff, and make sure the area is clear. Verify firmware identity and protocol compatibility before enabling any hardware contract. Do not flash firmware or push new pin configuration merely to make a test pass unless specifically requested.

A replay test validates software against recorded input; it does not establish real-time camera quality, sensor correctness, or safe physical vehicle behavior.

## Diff and claims review

Before completion:

1. Inspect the full diff and confirm only requested files changed.
2. Run git diff --check.
3. Confirm new tests fail for the intended regression when practical, then pass after the fix.
4. Report exact commands and results. Separate passed checks, failed checks, skipped checks, and checks blocked by unavailable dependencies/hardware.
5. State whether any physical hardware, real camera, real serial port, or flashed firmware was actually exercised.
6. Do not say "fixed", "verified", "tested on hardware", or "CI green" beyond the evidence available.
