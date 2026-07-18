import os
import json



def load():
    import base_config

    import modes.city.config_city as config_city
    import modes.race.config_race as config_race
    print(base_config.MODE, "*******************")
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

    else:
        try:
            if config_race.CHANGE_WITH_JSON:
                if os.path.exists("race.json"):
                    with open("race.json", "r") as f:
                        configs = json.loads(f.read())
                        for conf_name, value in configs.items():
                            setattr(config_race, conf_name, value)
        except json.JSONDecodeError:
            pass