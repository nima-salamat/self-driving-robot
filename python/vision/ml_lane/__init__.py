def create_ml_lane_detector(config):
    from .detector import create_ml_lane_detector as factory
    return factory(config)


def list_models():
    from .registry import list_models as registry_list_models
    return registry_list_models()


__all__ = ["create_ml_lane_detector", "list_models"]
