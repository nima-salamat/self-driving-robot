from utils.parser import parse_args
from utils.config_mode import set_city_mode, set_race_mode
import base_config
if __name__ == '__main__':
    args = parse_args()

    if args.mode == "city":
        from modes.city import config_city as config
        from modes.city import start
        set_city_mode()
    else:
        from modes.race import config_race as config
        from modes.race import start
        set_race_mode()

    config.DEBUG = args.debug
    config.STREAM = args.stream
    config.SHOW_FPS = args.fps
    config.WITHOUT_ARDUINO = args.without_arduino
    config.MODE = args.mode
    base_config.MODE = args.mode
    
    start()
