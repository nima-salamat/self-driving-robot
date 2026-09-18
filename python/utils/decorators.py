import os
import functools
import base_config


def if_is_not_windows(fn):
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        config = getattr(self, "config", None) or base_config.CONFIG_MODULE
        if os.name == "nt" or (
            config is not None and getattr(config, "WITHOUT_ARDUINO", False)
        ):
            return
        return fn(self, *args, **kwargs)
    return wrapper
