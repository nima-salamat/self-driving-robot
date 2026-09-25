"""Interactive traffic-sign dataset collector."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import cv2

from train_sign_detector.labels import KEY_TO_LABEL, SIGN_LABELS, label_name
from utils import json_config
from utils.config_mode import set_city_mode, set_race_mode
from vision.camera import Camera

PACKAGE_DIR = Path(__file__).resolve().parent
COLLECTED_DATASET = PACKAGE_DIR / "collected_dataset"
WINDOW_NAME = "Traffic Sign Dataset Collector"


def dataset_path() -> Path:
    return COLLECTED_DATASET


def ensure_dataset_dirs(base: Path = COLLECTED_DATASET) -> None:
    base.mkdir(parents=True, exist_ok=True)
    for label in SIGN_LABELS:
        (base / str(label)).mkdir(parents=True, exist_ok=True)


def next_filename(directory: Path) -> Path:
    numbers = []
    for path in directory.glob("*.png"):
        stem = path.stem.split("_", 1)[0]
        if stem.isdigit():
            numbers.append(int(stem))
    return directory / f"{max(numbers, default=0) + 1:06d}.png"


def save_sample(frame, label: int, base: Path = COLLECTED_DATASET) -> Path:
    label = int(label)
    if label not in SIGN_LABELS:
        raise ValueError(f"unsupported sign label: {label}")
    if frame is None or getattr(frame, "size", 0) == 0:
        raise ValueError("cannot save an empty frame")
    directory = base / str(label)
    directory.mkdir(parents=True, exist_ok=True)
    path = next_filename(directory)
    temp = path.with_suffix(".tmp.png")
    if not cv2.imwrite(str(temp), frame):
        raise IOError(f"failed to write {temp}")
    temp.replace(path)
    return path


def build_config(args):
    if args.mode == "city":
        set_city_mode()
        from modes.city import config_city
        config = config_city
    else:
        set_race_mode()
        from modes.race import config_race
        config = config_race
    json_config.load()
    if args.camera_mode is not None:
        config.CAMERA_MODE = args.camera_mode
    if args.camera_index is not None:
        config.USBCAM_ADDR = args.camera_index
    if args.width is not None:
        config.CAM_WIDTH = args.width
    if args.height is not None:
        config.CAM_HEIGHT = args.height
    if args.camera_fps is not None:
        config.CAMERA_FPS = args.camera_fps
    if args.raw:
        config.APPLY_CAMERA_CALIBRATION = False
    config.STREAM = False
    config.DEBUG = False
    return config


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Collect traffic-sign training images."
    )
    parser.add_argument("--mode", choices=("city", "race"), default="city")
    parser.add_argument("--camera-mode", choices=("picam", "webcam", "opencv"))
    parser.add_argument("--camera-index", type=int)
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--camera-fps", type=float)
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Disable runtime undistortion for captured frames.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=COLLECTED_DATASET,
    )
    args = parser.parse_args(argv)

    canonical_dataset = (PACKAGE_DIR / "dataset").resolve()
    output_path = args.output.resolve()
    if output_path == canonical_dataset:
        parser.error(
            "--output may not be the canonical train_sign_detector/dataset; "
            "use collected_dataset or another explicit staging directory"
        )

    if args.camera_index is not None and args.camera_index < 0:
        parser.error("--camera-index must be non-negative")

    base = output_path
    ensure_dataset_dirs(base)
    config = build_config(args)
    camera = Camera(config=config)
    current_label = None
    saved_count = {
        label: len(list((base / str(label)).glob("*.png")))
        for label in SIGN_LABELS
    }

    print("Traffic-sign collector")
    print(
        "Keys: 0=ERROR 1=STOP 2=TURN RIGHT 3=TURN LEFT "
        "4=STRAIGHT 5=PARK, q=quit"
    )
    print(f"Output: {base}")
    print("Select a class, then press SPACE to save the current frame.")

    try:
        while True:
            frame, _ = camera.capture_frame(with_resize=False)
            if not camera.last_capture_valid or frame is None:
                print("camera frame unavailable")
                time.sleep(0.05)
                continue
            display = frame.copy()
            label_text = (
                "NONE"
                if current_label is None
                else f"{current_label} = {label_name(current_label)}"
            )
            cv2.putText(
                display,
                f"Label: {label_text}",
                (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (0, 255, 255),
                2,
            )
            cv2.putText(
                display,
                "SPACE: save   Q: quit",
                (10, 50),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 255, 255),
                1,
            )
            cv2.imshow(WINDOW_NAME, display)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            key_text = chr(key)
            if key_text in KEY_TO_LABEL:
                current_label = KEY_TO_LABEL[key_text]
                try:
                    saved = save_sample(frame, current_label, base)
                except Exception as exc:
                    print(f"save failed: {exc}")
                    continue
                saved_count[current_label] += 1
                print(
                    f"Saved {saved.name} -> {current_label} "
                    f"({label_name(current_label)}) "
                    f"count={saved_count[current_label]}"
                )
            elif key == ord(" "):
                if current_label is None:
                    print("Select a label first")
                    continue
                try:
                    saved = save_sample(frame, current_label, base)
                except Exception as exc:
                    print(f"save failed: {exc}")
                    continue
                saved_count[current_label] += 1
                print(
                    f"Saved {saved.name} -> {current_label} "
                    f"({label_name(current_label)}) "
                    f"count={saved_count[current_label]}"
                )
    finally:
        camera.release()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
