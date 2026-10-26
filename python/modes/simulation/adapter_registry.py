"""Extensible registry for simulator API implementations."""
from .avis_adapter import AvisAdapter
from .carla_adapter import CarlaAdapter

_ADAPTERS = {"carla": CarlaAdapter, "avis": AvisAdapter}


def register_adapter(name, factory, *, replace=False):
    key = str(name).strip().lower()
    if not key:
        raise ValueError("adapter name must be non-empty")
    if not callable(factory):
        raise TypeError("adapter factory must be callable")
    if key in _ADAPTERS and not replace:
        raise ValueError(f"adapter already registered: {key}")
    _ADAPTERS[key] = factory


def create_adapter(backend, config):
    key = str(backend).strip().lower()
    try:
        factory = _ADAPTERS[key]
    except KeyError as exc:
        raise ValueError(f"no simulator adapter registered for {key!r}") from exc
    return factory(config)


def adapter_names():
    return tuple(_ADAPTERS)
