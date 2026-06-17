import os
import json
import modes.city.config_city as config_city
import base_config

def load():
    if base_config.MODE == "city":
        try:
            if config_city.CHANGE_WITH_JSON:
                if os.path.exists("city.json"):
                    with open("city.json", "r") as f:
                        configs = json.loads(f.read())
                        for conf_name, value in configs.items():
                            setattr(config_city, conf_name, value)
        except json.JSONDecodeError:
            pass