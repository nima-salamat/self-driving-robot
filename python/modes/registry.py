"""Declarative mode registry shared by runtime dispatch, CLI and editor metadata.
Simulator modes reuse City/Race perception without importing physical mode loops.
"""
from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class ModeSpec:
    name: str
    config_profile: str
    vision_profile: str
    runtime_kind: str = "hardware"
    simulator_backend: str = ""
    editor_profile: str = "standard"
    supports_lidar: bool = False
    supports_range_sensors: bool = False


_MODE_SPECS: Dict[str, ModeSpec] = {
    "city": ModeSpec("city", "city", "city"),
    "race": ModeSpec("race", "race", "race"),
    "carla": ModeSpec("carla", "city", "city", runtime_kind="simulation",
                      simulator_backend="carla", editor_profile="simulator", supports_lidar=True),
    "avis": ModeSpec("avis", "city", "city", runtime_kind="simulation",
                     simulator_backend="avis", editor_profile="simulator", supports_range_sensors=True),
    "avis-race": ModeSpec("avis-race", "race", "race", runtime_kind="simulation",
                          simulator_backend="avis", editor_profile="simulator", supports_range_sensors=True),
}


def register_mode(spec: ModeSpec, *, replace: bool = False) -> None:
    """Register a mode without coupling it to CLI or stream implementation."""
    if not isinstance(spec, ModeSpec):
        raise TypeError("spec must be a ModeSpec")
    if not spec.name or spec.name.strip() != spec.name:
        raise ValueError("mode names must be non-empty and trimmed")
    if spec.config_profile not in {"city", "race"}:
        raise ValueError("config_profile must be 'city' or 'race'")
    if spec.vision_profile not in {"city", "race"}:
        raise ValueError("vision_profile must be 'city' or 'race'")
    if spec.runtime_kind not in {"hardware", "simulation"}:
        raise ValueError("runtime_kind must be 'hardware' or 'simulation'")
    if spec.runtime_kind == "simulation" and not spec.simulator_backend:
        raise ValueError("simulation modes require a simulator_backend")
    if spec.name in _MODE_SPECS and not replace:
        raise ValueError(f"mode already registered: {spec.name}")
    _MODE_SPECS[spec.name] = spec
    _refresh_mode_sets()


def get_mode_spec(name: str) -> ModeSpec:
    try:
        return _MODE_SPECS[str(name).strip().lower()]
    except KeyError as exc:
        raise ValueError(
            f"unknown mode {name!r}; available modes: {', '.join(MODE_NAMES)}"
        ) from exc


def list_modes():
    return tuple(_MODE_SPECS.values())


def get_mode_names():
    return tuple(_MODE_SPECS)


def _refresh_mode_sets():
    global MODE_NAMES, SIMULATOR_MODES, CITY_VISION_MODES, RACE_VISION_MODES
    MODE_NAMES = tuple(_MODE_SPECS)
    SIMULATOR_MODES = frozenset(
        name for name, spec in _MODE_SPECS.items() if spec.runtime_kind == "simulation"
    )
    CITY_VISION_MODES = frozenset(
        name for name, spec in _MODE_SPECS.items() if spec.vision_profile == "city"
    )
    RACE_VISION_MODES = frozenset(
        name for name, spec in _MODE_SPECS.items() if spec.vision_profile == "race"
    )


def is_simulation_mode(name: str) -> bool:
    spec = _MODE_SPECS.get(str(name).strip().lower())
    return bool(spec and spec.runtime_kind == "simulation")


_refresh_mode_sets()
