import os
import sys
import threading
import time

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import modes.city.config_city as config_city
from stream import start_stream, stop_stream
from vision.camera import Camera
from vision.city_vision_processing import VisionProcessor


def main():
    config_city.DEBUG = True
    config_city.STREAM = True

    flask_thread = threading.Thread(
        target=start_stream,
        args=(config_city,),
        daemon=True,
    )
    flask_thread.start()

    cam = Camera(config=config_city)
    vision = VisionProcessor()

    try:
        while True:
            frame, _ = cam.capture_frame(with_resize=False)
            if not cam.last_capture_valid or frame is None:
                time.sleep(0.1)
                continue

            result = vision.detect(frame, frame.copy())
            debug_frame = (result.get("debug") or {}).get("combined")
            if debug_frame is not None:
                config_city.debug_frames_list = [debug_frame]
                config_city.stream_frame_seq = (
                    getattr(config_city, "stream_frame_seq", 0) + 1
                )
    except KeyboardInterrupt:
        pass
    finally:
        cam.release()
        stop_stream(config_city)
        if flask_thread.is_alive():
            flask_thread.join(timeout=2.0)


if __name__ == "__main__":
    main()
