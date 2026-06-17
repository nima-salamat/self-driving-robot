# config_mode.py

import base_config

def set_city_mode():
    import modes.city.config_city as config_city

    base_config.MODE = "city"
    base_config.CONFIG_MODULE = config_city

def set_race_mode():
    import modes.race.config_race as config_race

    base_config.MODE = "race"
    base_config.CONFIG_MODULE = config_race