# Camera Intrinsic Calibration Assets

This directory contains camera intrinsic/distortion models used by the City and Race camera pipelines.

## Runtime file

- `camera_calibration.npz` is the default profile selected by both `city.json` and `race.json`.
- Each mode may select another validated `.npz` profile by changing `CAMERA_CALIBRATION_FILE` in Stream's **Camera & Processing Rate → Camera Calibration Profile** section.
- Uploads from Stream are validated and stored here. Uploading only adds a profile; it does not activate it.
- Selecting a profile, or toggling undistortion, requires `RUN_LVL=STOP`. When a live camera is available, the new model is applied to the camera capture path and persisted to the active mode's JSON file.

## Supported format

Profiles are NumPy `.npz` archives containing at least:

- `cameraMatrix`: finite 3×3 camera intrinsic matrix, with positive focal lengths.
- `distCoeffs`: finite OpenCV distortion coefficients (4, 5, 8, 12, or 14 values).

The calibration loader also supports optional image-size and metadata arrays written by the project's calibration tool. Use the built-in calibration workflow when generating a new profile, so image dimensions and quality metadata stay consistent.

## Servo display note

The frame overlay distinguishes **Applied** (the last angle applied to the servo/controller) from **Center** (the configured straight-ahead calibration value). Changing the center while software-stopped updates the control reference but intentionally does not send a new servo command; therefore, the last applied angle can remain different until normal steering resumes.
