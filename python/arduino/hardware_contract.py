import json
import re
import time
from pathlib import Path


PROTOCOL_VERSION = 1
FIRMWARE_ID = "main_configurable_v1"

_MODULE_LIMITS = {
    "motor": 4,
    "servo": 4,
    "ultrasonic": 8,
    "encoder": 4,
    "tm1638": 1,
}

_ID_MODULES = {"motor", "servo", "encoder"}
_PIN_FIELDS = {
    "motor": ("pwm", "dir"),
    "servo": ("pin",),
    "ultrasonic": ("trig", "echo"),
    "encoder": ("pin",),
    "tm1638": ("stb", "clk", "dio"),
}
_OPTION_DEFAULTS = {
    "stop_distance_cm": 35,
    "pulse_stop_distance_cm": 10,
    "side_return_distance_cm": 20,
    "ultrasonic_interval_ms": 50,
    "host_heartbeat_timeout_ms": 500,
    "pulse_stall_timeout_ms": 900,
    "direction_deadtime_ms": 15,
}
_OPTION_LIMITS = {
    "stop_distance_cm": (1, 500),
    "pulse_stop_distance_cm": (1, 200),
    "side_return_distance_cm": (1, 500),
    "ultrasonic_interval_ms": (20, 2000),
    "host_heartbeat_timeout_ms": (100, 5000),
    "pulse_stall_timeout_ms": (100, 10000),
    "direction_deadtime_ms": (0, 250),
}
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,16}$")
_CONFIG_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")


class ArduinoHardwareConfigError(RuntimeError):
    pass


def _fail(message):
    raise ArduinoHardwareConfigError(message)


def _int(value, label, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(f"{label} must be an integer")
    if value < minimum or value > maximum:
        _fail(f"{label} must be in range {minimum}..{maximum}")
    return value


def _name(value, label):
    if not isinstance(value, str) or not _NAME_RE.fullmatch(value):
        _fail(f"{label} must match {_NAME_RE.pattern}")
    return value


def _fingerprint(text):
    value = 0x811C9DC5
    for byte in text.encode("ascii"):
        value ^= byte
        value = (value * 0x01000193) & 0xFFFFFFFF
    return f"{value:08X}"


def _module_echo(module):
    kind = module["type"]
    if kind == "motor":
        return f"motor {module['id']} {module['pwm']} {module['dir']}"
    if kind == "servo":
        return (
            f"servo {module['id']} {module['pin']} "
            f"{module['min']} {module['max']} {module['center']}"
        )
    if kind == "ultrasonic":
        return f"ultrasonic {module['name']} {module['trig']} {module['echo']}"
    if kind == "encoder":
        return f"encoder {module['id']} {module['pin']}"
    if kind == "tm1638":
        return (
            f"tm1638 {module['stb']} {module['clk']} {module['dio']} "
            f"{module['force_stop_button']} {module['resume_button']}"
        )
    _fail(f"Unsupported module type: {kind}")


def _normalize_module(raw, index):
    if not isinstance(raw, dict):
        _fail(f"modules[{index}] must be an object")

    kind = raw.get("type")
    if kind not in _MODULE_LIMITS:
        _fail(f"modules[{index}] has unsupported type: {kind!r}")

    result = {"type": kind}

    if kind in _ID_MODULES:
        result["id"] = _int(raw.get("id"), f"modules[{index}].id", 0, _MODULE_LIMITS[kind] - 1)

    if kind == "ultrasonic":
        result["name"] = _name(raw.get("name"), f"modules[{index}].name")

    for field in _PIN_FIELDS[kind]:
        result[field] = _int(raw.get(field), f"modules[{index}].{field}", 2, 53)

    if kind == "servo":
        result["min"] = _int(raw.get("min"), f"modules[{index}].min", 0, 180)
        result["max"] = _int(raw.get("max"), f"modules[{index}].max", result["min"], 180)
        result["center"] = _int(raw.get("center"), f"modules[{index}].center", result["min"], result["max"])

    if kind == "tm1638":
        result["force_stop_button"] = _int(
            raw.get("force_stop_button", 0),
            f"modules[{index}].force_stop_button",
            0,
            7,
        )
        result["resume_button"] = _int(
            raw.get("resume_button", 7),
            f"modules[{index}].resume_button",
            0,
            7,
        )

    return result


def _validate_and_normalize(raw):
    if not isinstance(raw, dict):
        _fail("Arduino config root must be an object")

    if raw.get("schema_version") != 1:
        _fail("schema_version must be 1")

    config_id = raw.get("config_id")
    if not isinstance(config_id, str) or not _CONFIG_ID_RE.fullmatch(config_id):
        _fail("config_id must contain only A-Z/a-z/0-9/._- and be at most 32 characters")

    firmware = raw.get("firmware")
    if not isinstance(firmware, dict):
        _fail("firmware must be an object")
    firmware_id = firmware.get("id")
    protocol = firmware.get("protocol")
    if firmware_id != FIRMWARE_ID:
        _fail(f"config expects firmware {FIRMWARE_ID!r}, got {firmware_id!r}")
    if protocol != PROTOCOL_VERSION:
        _fail(f"config expects protocol {PROTOCOL_VERSION}, got {protocol!r}")

    board = raw.get("board", "mega2560")
    if not isinstance(board, str) or not board:
        _fail("board must be a non-empty string")

    modules = raw.get("modules")
    if not isinstance(modules, list) or not modules:
        _fail("modules must be a non-empty list")

    normalized = []
    ids_seen = {kind: set() for kind in _ID_MODULES}
    names_seen = set()
    pins_seen = {}

    counts = {kind: 0 for kind in _MODULE_LIMITS}
    for index, raw_module in enumerate(modules):
        module = _normalize_module(raw_module, index)
        kind = module["type"]
        counts[kind] += 1

        if counts[kind] > _MODULE_LIMITS[kind]:
            _fail(f"too many {kind} modules; maximum is {_MODULE_LIMITS[kind]}")

        if kind in _ID_MODULES:
            if module["id"] in ids_seen[kind]:
                _fail(f"duplicate {kind} id {module['id']}")
            ids_seen[kind].add(module["id"])

        if kind == "ultrasonic":
            if module["name"] in names_seen:
                _fail(f"duplicate ultrasonic name {module['name']!r}")
            names_seen.add(module["name"])

        for field in _PIN_FIELDS[kind]:
            pin = module[field]
            if pin in pins_seen:
                _fail(f"pin {pin} is assigned to both {pins_seen[pin]} and {kind}.{field}")
            pins_seen[pin] = f"{kind}.{field}"

        normalized.append(module)

    for kind in _ID_MODULES:
        expected = set(range(counts[kind]))
        if ids_seen[kind] != expected:
            _fail(f"{kind} ids must be contiguous starting at 0; got {sorted(ids_seen[kind])}")

    if counts["tm1638"] > 1:
        _fail("only one tm1638 module is supported")

    options_raw = raw.get("options", {})
    if not isinstance(options_raw, dict):
        _fail("options must be an object")

    options = dict(_OPTION_DEFAULTS)
    for name, value in options_raw.items():
        if name not in _OPTION_DEFAULTS:
            _fail(f"unsupported option: {name}")
        minimum, maximum = _OPTION_LIMITS[name]
        options[name] = _int(value, f"options.{name}", minimum, maximum)

    return {
        "schema_version": 1,
        "config_id": config_id,
        "firmware": {"id": firmware_id, "protocol": protocol},
        "board": board,
        "modules": normalized,
        "options": options,
    }


def load_hardware_config(path):
    config_path = Path(path).expanduser()
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        _fail(f"Arduino config file not found: {config_path}")
    except json.JSONDecodeError as exc:
        _fail(f"invalid Arduino config JSON: {exc}")
    except OSError as exc:
        _fail(f"cannot read Arduino config {config_path}: {exc}")

    return _validate_and_normalize(raw)


def _canonical_lines(config):
    lines = []
    for module in config["modules"]:
        lines.append(_module_echo(module))

    for name in (
        "stop_distance_cm",
        "pulse_stop_distance_cm",
        "side_return_distance_cm",
        "ultrasonic_interval_ms",
        "host_heartbeat_timeout_ms",
        "pulse_stall_timeout_ms",
        "direction_deadtime_ms",
    ):
        lines.append(f"option {name} {config['options'][name]}")
    return lines


def config_fingerprint(config):
    return _fingerprint("\n".join(_canonical_lines(config)) + "\n")


def _snapshot_lines(connection):
    return connection.telemetry_snapshot(limit=200)


def _wait_for(connection, predicate, timeout, description):
    deadline = time.monotonic() + max(0.1, float(timeout))
    while time.monotonic() < deadline:
        for line in _snapshot_lines(connection):
            if predicate(line):
                return line
        time.sleep(0.01)
    _fail(f"Arduino contract timeout waiting for {description}")


def _send_and_wait(connection, command, predicate, timeout, description):
    if not connection.send_command(command + "\n"):
        _fail(f"failed to send Arduino contract command: {command}")
    return _wait_for(connection, predicate, timeout, description)


def perform_hardware_handshake(connection, path, timeout=3.0):
    config = load_hardware_config(path)
    config_id = config["config_id"]
    fingerprint = config_fingerprint(config)

    if not connection.connected:
        _fail("Arduino is not connected; strict hardware contract requires a live connection")

    hello = _send_and_wait(
        connection,
        "hello",
        lambda line: line.startswith("HELLO "),
        timeout,
        "HELLO",
    )
    hello_parts = hello.split()
    if len(hello_parts) != 4:
        _fail(f"malformed Arduino HELLO: {hello!r}")

    _, firmware_id, protocol_text, board = hello_parts
    try:
        protocol = int(protocol_text)
    except ValueError:
        _fail(f"malformed Arduino protocol version: {protocol_text!r}")

    expected_board = config["board"]
    if firmware_id != config["firmware"]["id"]:
        _fail(
            f"Arduino firmware mismatch: expected {config['firmware']['id']}, "
            f"device reported {firmware_id}"
        )
    if protocol != config["firmware"]["protocol"]:
        _fail(
            f"Arduino protocol mismatch: expected {config['firmware']['protocol']}, "
            f"device reported {protocol}"
        )
    if expected_board and board != expected_board:
        _fail(f"Arduino board mismatch: expected {expected_board}, device reported {board}")

    _send_and_wait(
        connection,
        f"cfg begin {config_id}",
        lambda line: line == f"CFG BEGIN OK {config_id}",
        timeout,
        "CFG BEGIN",
    )

    for module in config["modules"]:
        kind = module["type"]
        if kind == "motor":
            command = f"cfg motor {module['id']} {module['pwm']} {module['dir']}"
        elif kind == "servo":
            command = (
                f"cfg servo {module['id']} {module['pin']} "
                f"{module['min']} {module['max']} {module['center']}"
            )
        elif kind == "ultrasonic":
            command = f"cfg ultrasonic {module['name']} {module['trig']} {module['echo']}"
        elif kind == "encoder":
            command = f"cfg encoder {module['id']} {module['pin']}"
        else:
            command = (
                f"cfg tm1638 {module['stb']} {module['clk']} {module['dio']} "
                f"{module['force_stop_button']} {module['resume_button']}"
            )

        _send_and_wait(
            connection,
            command,
            lambda line, config_id=config_id: line.startswith(f"CFG ACCEPT {config_id} "),
            timeout,
            f"{kind} module",
        )

    for name, value in config["options"].items():
        command = f"cfg option {name} {value}"
        _send_and_wait(
            connection,
            command,
            lambda line, config_id=config_id: line.startswith(f"CFG ACCEPT {config_id} option "),
            timeout,
            f"option {name}",
        )

    ready = _send_and_wait(
        connection,
        f"cfg end {config_id} {fingerprint}",
        lambda line, config_id=config_id: line.startswith(f"CFG READY {config_id} "),
        timeout,
        "CFG READY",
    )

    parts = ready.split()
    if len(parts) != 4 or parts[2] != fingerprint:
        _fail(
            f"Arduino configuration fingerprint mismatch: "
            f"Python={fingerprint}, device={parts[2] if len(parts) > 2 else 'malformed'}"
        )

    expected_echo = [f"CFG ECHO {config_id} {line}" for line in _canonical_lines(config)]
    actual_echo = [
        line
        for line in _snapshot_lines(connection)
        if line.startswith(f"CFG ECHO {config_id} ")
    ]

    # Keep only the most recent occurrence of each expected echo. The contract
    # ID is stable, so a reconnect cannot silently change the accepted values.
    actual_set = set(actual_echo)
    missing = [line for line in expected_echo if line not in actual_set]
    if missing:
        _fail("Arduino accepted the config but did not echo all values: " + "; ".join(missing))

    return {
        "config_id": config_id,
        "firmware_id": firmware_id,
        "protocol": protocol,
        "board": board,
        "fingerprint": fingerprint,
        "module_counts": {
            "motors": sum(m["type"] == "motor" for m in config["modules"]),
            "servos": sum(m["type"] == "servo" for m in config["modules"]),
            "ultrasonics": sum(m["type"] == "ultrasonic" for m in config["modules"]),
            "encoders": sum(m["type"] == "encoder" for m in config["modules"]),
            "tm1638": sum(m["type"] == "tm1638" for m in config["modules"]),
        },
    }
