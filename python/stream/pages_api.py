"""StreamPages endpoints and state operations for the Stream dashboard."""
import sys as _sys

# These methods were moved from WebStreamer without changing their behavior.
# Bind shared Stream globals at import time; BASE_DIR is deliberately resolved
# dynamically so existing tests/configuration patching of stream.BASE_DIR remains valid.
_stream_module = _sys.modules[__package__]
for _global_name, _global_value in vars(_stream_module).items():
    if not _global_name.startswith('__'):
        globals()[_global_name] = _global_value

class StreamPagesMixin:
    def index(self):
        values = {var: self.get_base_var(var) for var in VARIABLES}
        advanced_current = self.get_all_advanced()
        response = Response(
            render_template(
                "stream.html",
                variables=VARIABLES,
                values=values,
                ui=self.ui_settings,
                advanced=advanced_current,
                mode=getattr(self.config, "MODE", "mode"),
                stream_control=bool(
                    getattr(self.config, "STREAM_ALLOW_CONTROL", False)
                ),
                capabilities=mode_capabilities(self.config),
                encoder_map_enabled=bool(getattr(self.config, "ENCODER_MAP_ENABLED", False)),
                auth_enabled=bool(self.auth_enabled),
            ),
            mimetype="text/html",
        )
        # The dashboard contains inline JavaScript. Do not let a browser reuse
        # an old broken script after the local robot runtime has been updated.
        response.headers.update({
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        })
        return response

    def encoder_map_page(self):
        if not bool(getattr(self.config, "ENCODER_MAP_ENABLED", False)):
            return Response("Not Found", status=404)
        return Response(_stream_module.ENCODER_MAP_TEMPLATE, mimetype="text/html")

    def encoder_map_api(self):
        if not bool(getattr(self.config, "ENCODER_MAP_ENABLED", False)):
            return jsonify(error="encoder map is disabled"), 404
        odometry = getattr(self.config, "encoder_odometry", None)
        if odometry is None:
            return jsonify(error="encoder odometry is not initialized"), 503
        return jsonify(odometry.snapshot())

    def encoder_map_reset_origin(self):
        if not bool(getattr(self.config, "ENCODER_MAP_ENABLED", False)):
            return jsonify(error="encoder map is disabled"), 404
        if not self._control_allowed():
            return self._control_denied()
        odometry = getattr(self.config, "encoder_odometry", None)
        if odometry is None:
            return jsonify(error="encoder odometry is not initialized"), 503
        odometry.reset_display_origin()
        return jsonify(success=True, message="display origin reset; hardware unchanged")


def register_page_routes(app, streamer):
    """Register stream pages routes on the shared Flask app."""
    app.add_url_rule("/", "index", streamer.index)
    app.add_url_rule("/encoder-map", "encoder_map_page", streamer.encoder_map_page)
    app.add_url_rule("/api/encoder-map", "encoder_map_api", streamer.encoder_map_api)
    app.add_url_rule("/api/encoder-map/reset-origin", "encoder_map_reset_origin", streamer.encoder_map_reset_origin, methods=["POST"])
