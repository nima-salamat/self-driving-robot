# Perception Pipeline

## Overview

Perception begins with camera frames and produces estimates used by a selected mode's control loop. The runtime can also request traffic-sign inference, AprilTag detection, crosswalk/traffic-light processing, and optional object-related diagnostics. Availability and timing differ by mode and configuration; enabling a detector does not mean every mode consumes its output in the same way.

## Camera lifecycle

Implementation: `python/vision/camera.py`.

Supported backends are:

- `picam`: Raspberry Pi camera through Picamera2.
- `webcam`: OpenCV `VideoCapture`.
- `opencv`: an alias for the OpenCV backend.

The camera path initializes the selected backend, applies calibration when enabled and available, publishes a raw frame and a processing-sized frame, and releases its resources during shutdown. Runtime camera controls depend on the selected backend. OpenCV camera indexes apply to `webcam`/`opencv`, not Picamera2.

Camera frame rate and the vision-loop rate are different measurements. Picamera2 frame-rate requests are limited by the selected camera mode. Use the measured camera rate and frame age rather than assuming a requested value was achieved; see [Performance](PERFORMANCE.md).

## Lane detection

The physical City and Race paths use separate processors:

- `python/vision/city_vision_processing.py`
- `python/vision/race_vision_processing.py`

These modules consume mode-specific ROI, preprocessing, line-selection, and optional bird's-eye-view (BEV/IPM) settings. The selected implementation and geometry settings must remain consistent: a detector can return syntactically valid coordinates even when ROI or BEV calibration is wrong.

### Default lane processors

The default processor estimates left/right lane evidence from configured regions and candidate line segments, then emits lane information used by the mode/controller. City and Race processors are similar in broad purpose but have their own configuration and state; do not replace one with the other without testing both callers.

When tuning, change one family of values at a time and validate against representative recorded frames before testing a moving robot. Use the offline lane tuning tool described in [Dataset and Calibration](DATASET_AND_CALIBRATION.md).

### Experimental BLSF lane detector

The experimental classical detector is under `python/vision/blsf_lane/` and is selected only for City mode:

```bash
python python/main.py --mode city --city-lane-detector blsf-beta
```

Its documented pipeline combines BEV/IPM, weighted grayscale, median-local thresholding, line-segment detection/filtering, column projection, sliding windows and quadratic RANSAC fitting. It reuses City BEV settings and has its own `BLSF_*` tuning values. The default City detector remains the default; treat BLSF as experimental until validated on the target camera and course.

### Learned lane detection

The optional ML lane detector is enabled by selecting a supported model, for example:

```bash
python python/main.py --mode race --ml-lane-model unet_depthwise_nano
```

Supported names exposed by the current CLI are `unet_depthwise_nano` and `unet_depthwise_small`. The runtime validates that the NCNN Python module can be loaded when this feature is selected. Model files, input dimensions, preprocessing and output decoding must agree; a successful import alone does not prove the selected model is correct. Check the current mode capability and preflight output before assuming a model is supported in every mode.

## Traffic-sign recognition

Runtime sign-detection code lives under `python/traffic_sign_detector/`; data collection, labels and training live under `python/train_sign_detector/`.

The shared numeric label mapping is:

| ID | Label |
|---:|---|
| 0 | ERROR |
| 1 | STOP |
| 2 | TURN RIGHT |
| 3 | TURN LEFT |
| 4 | STRAIGHT |
| 5 | PARK |

Treat these values as a contract between dataset collection, training and runtime decoding. Update all three sides and their tests together if a label is changed.

Sign inference can run through the normal detector/worker path or the opt-in process-isolated path. The asynchronous wrapper exposes the latest completed result and filters by result age; the process detector uses bounded request/result handoff. In multiprocessing mode stale waiting requests are replaced/skipped, while lane perception and mode control remain in the owning runtime process.

The detector's confidence, area filters, freshness checks and the mode's stop/phase logic are separate safety layers. A faster result path must not silently lower these thresholds.

## AprilTags, crosswalks and traffic lights

- AprilTag detection is implemented by the vision marker-detection code and is controlled by mode configuration/CLI options. Check the selected mode before expecting tag-triggered behavior.
- Crosswalk detection uses configured image regions and thresholds; City also has configured turn-right, turn-left and straight pulse sequences for supported route triggers.
- The City traffic-light crosswalk gate is explicitly opt-in via `--traffic-lights`; JSON alone cannot enable it. When enabled, crossing requires 8 GREEN observations among the latest 10 distinct fresh frames, and the newest observation must also be GREEN. RED, UNKNOWN, invalid frames or detector errors must keep the gate closed. `--traffic-light-wait-before-check` delays the first observation; it does not bypass confirmation.
- Object detection is optional and must not be assumed to be part of the default lane-control path.

## Debugging perception

1. Confirm the runtime selected the expected mode and camera backend.
2. Confirm the camera is publishing new frames; inspect camera FPS and frame age.
3. Check frame dimensions, color channel order, calibration artifact path and calibration toggle.
4. Inspect the active mode's ROI/BEV values and debug visualizations.
5. Check detector freshness and status before interpreting an old sign result as a current observation.
6. Compare default and optional lane detectors on the same saved frames.
7. Validate steering direction at very low speed before relying on perception changes.

A processed frame or a positive detection is not proof that the geometry, class label or steering decision is physically correct.
