# Dataset Collection, Model Training and Calibration

## Keep datasets separate

The project intentionally separates the canonical sign training dataset, newly collected sign samples and the standalone image connector's files.

| Data | Location |
|---|---|
| Canonical sign dataset | `python/train_sign_detector/dataset/` |
| New sign collection output | `python/train_sign_detector/collected_dataset/` |
| Dataset Connector capture storage | `python/assets/dataset_connector/` |
| Exported Connector archive | `dataset.zip` downloaded through the Connector UI |
| Camera calibration artifact | Configured by the active profile's `CAMERA_CALIBRATION_FILE` |

Do not let a collector or experiment overwrite the canonical training data. Back up a dataset before changing labels, directory organization or training splits.

## Traffic-sign collection

Use the collector at its current path:

```bash
python python/train_sign_detector/dataset_collector.py --mode race
```

New samples are saved to `python/train_sign_detector/collected_dataset/` by default. The canonical numeric class mapping is:

| ID | Class |
|---:|---|
| 0 | ERROR |
| 1 | STOP |
| 2 | TURN RIGHT |
| 3 | TURN LEFT |
| 4 | STRAIGHT |
| 5 | PARK |

The shared mapping is defined in `python/train_sign_detector/labels.py`. Keep the collector, training pipeline, runtime decoder and tests in sync if this contract changes.

## Train or evaluate from a collected dataset

Pass the dataset explicitly when training from new captures:

```bash
python python/train_sign_detector/main.py --train --dataset python/train_sign_detector/collected_dataset --file_name video.mp4
```

Check the training script's `--help` for available training and evaluation arguments. Confirm the produced model is the same architecture, label order and preprocessing expected by the runtime detector before deployment.

## Dataset Connector web workspace

Launch from the repository's `python/` directory:

```bash
cd python
python -m dataset_connector --host 0.0.0.0 --port 5051 --camera-mode picam --fps 30
```

The Connector provides a live camera view, responsive image gallery, capture/preview/delete/clear operations and a downloadable ZIP. A validated `camera_calibration.npz` file can be used for calibrated preview, but applying calibration to the preview does not overwrite the captured source images.

The default bind host `0.0.0.0` exposes the service on all network interfaces. Use it only on a trusted network and restrict access with a firewall. Keep captured images and exported archives private when they include people or identifying environments.

## Camera calibration

The calibration package lives under `python/calibration/`. It includes image capture, solving and an optional camera-calibration web service. The calibration artifact's exact path is a configurable value; check the selected mode's `CAMERA_CALIBRATION_FILE` rather than assuming every checkout uses the same asset location.

The calibration Stream can be launched from the `python/` directory:

```bash
cd python
python -m calibration.stream --host 127.0.0.1
```

The service can capture/clear images, change camera FPS and start calibration. It has no built-in authentication. Keep it bound to loopback when using the same machine, or on a trusted isolated network only when remote access is required.

Calibration workflow:

1. Capture checkerboard images covering the expected operating field of view, distance and tilt.
2. Run the calibration solver and inspect its reported result.
3. Save the artifact at a controlled location and update the active mode config if necessary.
4. Enable the calibration option and check the live undistorted frame.
5. Validate lane ROIs/BEV against the calibrated image; calibration can change apparent geometry and may require retuning.
6. Keep the original captures and artifact so changes can be reproduced.

## Offline lane tuning

Use the Tkinter lane tuning tool with saved PNGs; it does not open the camera or connect to Arduino:

```bash
cd python
python tools/lane_tuning_gui.py
```

The tool can inspect the original frame, raw Hough candidates, selected lane candidates and edge maps. It exposes threshold/Hough settings, blur/preprocessing, morphology, BEV transform, lane ROI geometry and trapezoid widths. **Save preset to mode JSON** merges values into `race.json` or `city.json` and creates a sibling `.bak` backup first.

The input PNG is resized to configured runtime dimensions by default. Turn that option off to inspect original dimensions. After saving a preset, inspect the diff and validate on more than one frame before a physical run.
