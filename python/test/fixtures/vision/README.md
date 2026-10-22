# Vision regression fixtures

The vision unit tests generate a deterministic synthetic 320×240 frame containing two high-contrast lane boundaries. It exercises the actual Hough preview endpoint and verifies candidate/edge stages and the no-motion contract.

When adding captured robot frames, place only non-sensitive images needed for regression here and add a JSON sidecar with the mode/detector, BEV setting, image dimensions, approximate left/right boundary annotations, known failure mode, and acceptable metric tolerances. Prefer metrics/tolerances over brittle exact-pixel comparisons.

Use a stable holdout set for regression. Do not tune thresholds on holdout frames and do not treat the synthetic test as proof of performance on real asphalt, banners, motion blur, or the Raspberry Pi camera.
