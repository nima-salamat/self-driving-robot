# Stream frontend source layout

The Stream UI is split by responsibility while preserving the runtime contracts used by the dashboard and simulator editor.

## Main Stream dashboard

- `templates/stream.html` is the document shell and includes the semantic HTML partials under `templates/stream/partials/`.
- `templates/stream/js/` contains the ordered JavaScript fragments for the Extensions IIFE. These files are Jinja partials, not standalone browser scripts: keep their include order and their single shared IIFE in `_scripts.html`.
- `static/stream.css` is the compatibility stylesheet manifest. It imports the ordered layers from `static/css/`.
- The global dashboard runtime is loaded in order: state helpers, core, camera loop, overlays, controls, and runtime. These are classic scripts and intentionally share the page's global lexical environment; do not add `async` or `type="module"` without migrating those contracts first.
- `stream-auth.js` centralizes the optional 401-to-login redirect. `stream-workbench.js` remains the final dashboard enhancement layer.

## Simulator workbench

- `templates/simulator_editor.html` is the shell. Its semantic HTML is in `templates/simulator/partials/`.
- Simulator JavaScript fragments live in `templates/simulator/js/` and are included inside one IIFE so AVIS and CARLA helpers retain their shared lexical state.
- Shared simulator styling is in `static/css/simulator-base.css`; backend-specific styling is loaded from `simulator-avis.css` or `simulator-carla.css`.
- CARLA scene and camera-placement JavaScript is included only for the CARLA backend. The document also exposes backend/profile classes (`simulator-editor--avis`, `simulator-editor--carla`, `simulator-profile--city`, `simulator-profile--race`) for future focused customization.

## Verification

Run the browser smoke test and state helper tests with:

```bash
node --test python/test/test_stream_state.test.js
node python/test/test_stream_browser.test.js
```

The Python test workflow also runs the hardware-free unit suite and checks all static JavaScript files.
