import argparse
import json
import time

import cv2

from utils.runtime_metrics import RuntimeMetrics


def parse_args():
    parser = argparse.ArgumentParser(description="Offline lane-vision replay")
    parser.add_argument("--mode", choices=("race", "city"), default="race")
    parser.add_argument("--input", required=True, help="Path to a recorded video")
    parser.add_argument("--output", help="Optional path for annotated replay video")
    parser.add_argument("--max-frames", type=int, default=0, help="0 means all frames")
    parser.add_argument("--display", action="store_true", help="Display replay windows")
    return parser.parse_args()


def main():
    args = parse_args()

    if args.mode == "race":
        import base_config
        from modes.race import config_race as config
        from modes.race.config_race import VisionProcessor
        from utils.config_mode import set_race_mode
    else:
        import base_config
        from modes.city import config_city as config
        from modes.city.config_city import VisionProcessor
        from utils.config_mode import set_city_mode

    if args.mode == "race":
        set_race_mode()
    else:
        set_city_mode()

    base_config.MODE = args.mode
    cap = cv2.VideoCapture(args.input)
    if not cap.isOpened():
        raise RuntimeError(f"Unable to open replay input: {args.input}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    writer = None
    if args.output:
        codec = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(args.output, codec, fps if fps > 0 else 20.0, (width, height))
        if not writer.isOpened():
            cap.release()
            raise RuntimeError(f"Unable to open replay output: {args.output}")

    vision = VisionProcessor()
    metrics = RuntimeMetrics()
    frames = 0
    valid = 0
    started = time.monotonic()

    try:
        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                break
            if args.max_frames > 0 and frames >= args.max_frames:
                break

            loop_started = time.monotonic()
            debug_frame = frame.copy()
            result = vision.detect(frame, debug_frame)
            metrics.record_perception(
                (time.monotonic() - loop_started) * 1000.0,
                bool(result.get("perception_valid", False)),
            )
            metrics.record_loop((time.monotonic() - loop_started) * 1000.0)

            frames += 1
            if result.get("perception_valid", False):
                valid += 1

            if writer is not None:
                writer.write(debug_frame if debug_frame is not None else frame)

            if args.display:
                cv2.imshow("Replay", debug_frame if debug_frame is not None else frame)
                if cv2.waitKey(1) & 0xFF == 27:
                    break
    finally:
        cap.release()
        if writer is not None:
            writer.release()
        if args.display:
            cv2.destroyAllWindows()

    elapsed = max(0.0, time.monotonic() - started)
    timing = metrics.snapshot()["timing"]
    report = {
        "mode": args.mode,
        "input": args.input,
        "frames": frames,
        "valid_perception_frames": valid,
        "perception_valid_ratio": valid / frames if frames else 0.0,
        "wall_fps": frames / elapsed if elapsed else 0.0,
        "loop": timing["loop"],
        "perception": timing["perception"],
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()