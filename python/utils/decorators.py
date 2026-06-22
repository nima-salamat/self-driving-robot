import os
import functools
import base_config


def if_is_not_windows(fn):
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        config = base_config.CONFIG_MODULE
        if os.name == "nt" or config.WITHOUT_ARDUINO:
            return
        else:
            return fn(self, *args, **kwargs)
    return wrapper
