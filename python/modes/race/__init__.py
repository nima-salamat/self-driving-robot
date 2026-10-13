"""Race mode package.

Keep importing configuration and perception helpers side-effect free. The
runtime is loaded only when callers actually invoke start().
"""


def start(*args, **kwargs):
    from .race import start as run_race

    return run_race(*args, **kwargs)
