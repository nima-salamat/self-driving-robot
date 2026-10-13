"""City mode package.

Keep importing configuration and perception helpers side-effect free. The
runtime is loaded only when callers actually invoke start().
"""


def start(*args, **kwargs):
    from .city import start as run_city

    return run_city(*args, **kwargs)
