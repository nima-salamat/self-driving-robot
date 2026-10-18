"""StreamMedia endpoints and state operations for the Stream dashboard."""
import sys as _sys

# These methods were moved from WebStreamer without changing their behavior.
# Bind shared Stream globals at import time; BASE_DIR is deliberately resolved
# dynamically so existing tests/configuration patching of stream.BASE_DIR remains valid.
_stream_module = _sys.modules[__package__]
for _global_name, _global_value in vars(_stream_module).items():
    if not _global_name.startswith('__'):
        globals()[_global_name] = _global_value

class StreamMediaMixin:
        def video_feed_frame(self):
            with self._frame_lock:
                frozen = getattr(self.config, "frozen_debug_frame", None)
                if frozen is not None:
                    frame = frozen.copy()
                else:
                    frames_list = getattr(self.config, "debug_frames_list", [])
                    frame = (
                        (
                            frames_list[-1].copy()
                            if hasattr(frames_list[-1], "copy")
                            else frames_list[-1]
                        )
                        if frames_list and frames_list[-1] is not None
                        else None
                    )
            
            cache_headers = {
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            }

            if frame is None:
                response = Response("", status=204)
                response.headers.update(cache_headers)
                return response

            frame_id = getattr(self.config, "stream_frame_seq", id(frame))
            with self._jpeg_cache_lock:
                if frame_id != self._jpeg_cache_frame_id or self._jpeg_cache is None:
                    try:
                        ret, buffer = cv2.imencode(".jpg", frame)
                        if not ret:
                            response = Response("", status=204)
                            response.headers.update(cache_headers)
                            return response
                        payload = buffer.tobytes()
                    except Exception:
                        logger.exception("Failed to encode stream frame")
                        response = Response("", status=503)
                        response.headers.update(cache_headers)
                        return response
                    self._jpeg_cache = payload
                    self._jpeg_cache_frame_id = frame_id
                payload = self._jpeg_cache

            response = Response(payload, mimetype="image/jpeg")
            response.headers.update(cache_headers)
            response.headers["X-Stream-Frame-Sequence"] = str(frame_id)
            for key, value in self._feature_diagnostics().items():
                if value is not None:
                    response.headers["X-Robot-" + key.replace("_", "-")] = json.dumps(value, separators=(",", ":"))
            return response

        def video_feed(self):
            def generate():
                last_frame_id = None
                while True:
                    with self._frame_lock:
                        frozen = getattr(self.config, "frozen_debug_frame", None)
                        if frozen is not None:
                            frame = frozen.copy()
                            frame_id = "frozen"
                        else:
                            frames_list = getattr(
                                self.config,
                                "debug_frames_list",
                                [],
                            )
                            frame = (
                                (
                                    frames_list[-1].copy()
                                    if hasattr(frames_list[-1], "copy")
                                    else frames_list[-1]
                                )
                                if frames_list and frames_list[-1] is not None
                                else None
                            )
                            frame_id = getattr(
                                self.config,
                                "stream_frame_seq",
                                id(frame) if frame is not None else None,
                            )

                    if frame is None:
                        time.sleep(0.05)
                        continue

                    try:
                        ret, buffer = cv2.imencode(
                            ".jpg",
                            frame,
                            [cv2.IMWRITE_JPEG_QUALITY, 85],
                        )
                    except Exception:
                        logger.exception("Failed to encode MJPEG stream frame")
                        time.sleep(0.05)
                        continue

                    if not ret:
                        time.sleep(0.05)
                        continue

                    last_frame_id = frame_id
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n"
                        + buffer.tobytes()
                        + b"\r\n"
                    )

            return Response(
                generate(),
                mimetype="multipart/x-mixed-replace; boundary=frame",
            )

        def take_picture(self):
            if not self._control_allowed():
                return self._control_denied()
            setattr(self.config, "TAKE_PICTURE", True)
            return jsonify(success=True)

        def toggle_record(self):
            if not self._control_allowed():
                return self._control_denied()
            current = getattr(self.config, "RECORD_VIDEO", False)
            new_val = not current
            setattr(self.config, "RECORD_VIDEO", new_val)
            if not self.save_conf_to_json():
                setattr(self.config, "RECORD_VIDEO", current)
                return jsonify(success=False, message="could not persist recording state; previous value restored"), 500
            return jsonify(success=True, recording=new_val)

        def freeze_frame(self):
            if not self._control_allowed():
                return self._control_denied()
            with self._frame_lock:
                frames_list = getattr(self.config, "debug_frames_list", [])
                if frames_list:
                    setattr(
                        self.config,
                        "frozen_debug_frame",
                        frames_list[-1].copy(),
                    )
                    return jsonify(success=True)
            return jsonify(success=False, message="No frame available")

        def unfreeze_frame(self):
            if not self._control_allowed():
                return self._control_denied()
            if hasattr(self.config, "frozen_debug_frame"):
                delattr(self.config, "frozen_debug_frame")
            return jsonify(success=True)


def register_media_routes(app, streamer):
    """Register stream media routes on the shared Flask app."""
    app.add_url_rule("/video_feed_frame", "video_feed_frame", streamer.video_feed_frame)
    app.add_url_rule("/video_feed", "video_feed", streamer.video_feed)
    app.add_url_rule("/take_picture", "take_picture", streamer.take_picture, methods=["POST"])
    app.add_url_rule("/toggle_record", "toggle_record", streamer.toggle_record, methods=["POST"])
    app.add_url_rule("/freeze_frame", "freeze_frame", streamer.freeze_frame, methods=["POST"])
    app.add_url_rule("/unfreeze_frame", "unfreeze_frame", streamer.unfreeze_frame, methods=["POST"])
