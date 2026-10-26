"""Simulation runtime entry point; adapters are loaded only when selected."""


def start():
    from .runtime import SimulationRuntime
    from base_config import CONFIG_MODULE

    if CONFIG_MODULE is None:
        raise RuntimeError("The active mode configuration was not selected")
    SimulationRuntime(CONFIG_MODULE).start()
