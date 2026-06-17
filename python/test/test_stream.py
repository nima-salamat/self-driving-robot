import sys
import os
prev_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(prev_dir)


import base_config
import modes.city.config_city as config_city 
base_config.MODE="city"
base_config.CONFIG_MODULE = config_city
from vision import camera, city_vision_processing
from stream import start_stream
import threading

config_city.DEBUG = True


flask_thread = threading.Thread(target=start_stream, daemon=False)
flask_thread.start()

camera = camera.Camera()
v = city_vision_processing.VisionProcessor()

while True:
    try:
        frame = camera.capture_frame()
        frame = v.detect(frame)["debug"]["combined"]
        config_city.debug_frame_buffer = frame
    except KeyboardInterrupt:
        break
    except Exception as e:
        print(e)

try:
    import requests
    requests.post("http://127.0.0.1:5000/shutdown")
except Exception:
    pass

if flask_thread.is_alive():
    flask_thread.join()
