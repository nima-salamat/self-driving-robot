# Testing and Development

## Python checks

Run commands from the repository root unless a command explicitly changes into `python/`.

Compile the Python tree:

```bash
python -m compileall -q python
```

Run the hardware-free unit suite used by the repository's Python CI:

```bash
PYTHONPATH=python python -m unittest discover -s python/test -p 'test_unit_*.py' -v
```

Run a focused test module by its filename when isolating a regression. The test tree includes coverage for runtime behavior, Stream APIs, adversarial input handling and simulator mode contracts; check the current filenames under `python/test/` before assuming a particular module exists.

Start preflight diagnostics without entering the runtime control loop:

```bash
python python/main.py --mode race --preflight
```

Preflight enumerates the configured serial device without opening it, because
opening some Arduino boards resets the MCU. When `--arduino-config` is supplied,
it also validates the hardware profile locally. It deliberately does not run the
`hello/cfg` handshake or configure the board; the runtime performs that
contract check before normal control. A serial-port enumeration pass is not
proof that the device is writable or that the attached firmware matches.

For an initial vision/runtime test without serial actuation:

```bash
python python/main.py --mode race --without-arduino --performance
```

The hardware-free suite cannot validate a physical camera, serial adapter, firmware upload, sensor geometry or stopping distance.

## Arduino checks

The workflow `.github/workflows/arduino-configurable.yml` compiles `arduino/main_configurable_v1.ino` for an Arduino Mega 2560. Passing that check does not compile every firmware generation or prove compatibility with a different uploaded sketch.

When changing firmware protocol or pin validation, test the exact firmware/profile pair. Record the selected board and firmware generation because configurable, fixed-pin and EEPROM/set-based sketches implement different contracts.

## Stream UI checks

The Python CI workflow `.github/workflows/python-tests.yml` runs Python compilation and the hardware-free suite, installs Playwright/Chromium, and performs Stream UI smoke checks. API unit tests and a browser smoke test provide different coverage; neither alone guarantees the entire dashboard works across every mode and screen size.

For manual UI testing, run with `--without-arduino` unless a real connected robot is intentionally being tested. Use read-only Stream mode for visual checks where configuration mutations are not needed.

## Simulator checks

Start the simulator server separately, then run a mode selected through the current registry. The repository includes `python/test/test_unit_simulation_modes.py`; check the test directory for related adapter/runtime tests.

For each backend, validate connect, first frame, sensor ranges, steering polarity, lane-loss behavior, scene reset, and clean shutdown. Keep CARLA-only and AVIS-only settings behind the backend capability checks.

## Suggested regression matrix

| Change | Minimum checks |
|---|---|
| CLI/config loader | Argument validation tests, config precedence tests, `--preflight` |
| Camera/calibration | Camera-related unit tests and saved-frame validation; hardware smoke test on the target backend |
| Lane detector | Run relevant tests and compare saved frames for City/Race independently |
| Sign worker or multiprocessing | Worker lifecycle/freshness tests, repeated start/stop, performance comparison with the same settings |
| Serial protocol/controller | Protocol tests, exact firmware compile/compatibility check, controlled hardware test |
| Stream API/editor | API tests, UI smoke checks, read-only mode and mutation validation |
| Simulator adapter | Adapter tests plus a run against the matching simulator/server |

## Contribution practices

- Keep changes scoped to the responsible module and avoid changing City and Race behavior implicitly.
- Add a regression test for each fixed bug where a deterministic test is possible.
- Treat observed hardware and performance behavior as environment-specific; record backend, configuration and exact command when reporting it.
- Update documentation when a CLI flag, configuration field, telemetry schema, firmware contract or mode capability changes.
- Review the diff for generated files, captured datasets, calibration artifacts and credentials before committing.
