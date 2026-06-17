import base_config
import modes.city.config_city as config_city 
import modes.race.config_race as config_race



def set_city_mode():
    base_config.MODE="city"
    base_config.CONFIG_MODULE = config_city

def set_race_mode():
    base_config.MODE="race"
    base_config.CONFIG_MODULE = config_race
