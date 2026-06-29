from utils.parser import parse_args

if __name__ == '__main__':
    args = parse_args()

    if args.mode == "city":
        from modes.city import config_city as config
        from modes.city import start
    else:
        from modes.race import config_race as config
        from modes.race import start

    config.DEBUG = args.debug
    config.STREAM = args.stream
    config.SHOW_FPS = args.fps
    config.WITHOUT_ARDUINO = args.without_arduino
    start()
