#!/usr/bin/env python3
import argparse
import time
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve()
PYTHON_ROOT = HERE.parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from vision.ml_lane.detector import MLLaneDetector
from vision.ml_lane.registry import list_models


def format_ms(value):
    return f"{value:.2f} ms"


def _open_source(source, camera_mode):
    if source != "camera":
        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            raise RuntimeError(f"Could not open input: {source}")
        return cap, None

    if camera_mode == "picam":
        from modes.race import config_race
        from vision.camera import Camera

        config_race.DEBUG = False
        config_race.STREAM = False
        camera = Camera(config=config_race)
        return None, camera

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        raise RuntimeError("Could not open OpenCV camera index 0")
    return cap, None


def _read_source(cap, camera):
    if camera is not None:
        frame, resized = camera.capture_frame(with_resize=True)
        if not camera.last_capture_valid or resized is None:
            return False, None
        return True, resized

    return cap.read()


def benchmark(detector, source, warmup, frames, display, output, camera_mode):
    cap, camera = _open_source(source, camera_mode)

    writer = None
    total_frames = 0
    valid_frames = 0
    infer_times = []
    model_times = []
    wall_start = time.monotonic()

    for _ in range(max(0, warmup)):
        ok, frame = _read_source(cap, camera)
        if not ok:
            break
        detector.detect(frame)

    start = time.monotonic()
    while total_frames < frames:
        ok, frame = _read_source(cap, camera)
        if not ok:
            break

        result = detector.detect(frame)
        total_frames += 1
        valid_frames += int(result["perception_valid"])
        infer_times.append(result["ml_latency_ms"])
        model_times.append(result["ml_inference_ms"])

        if display or output:
            vis = result["debug"]["combined"]
            if output and writer is None:
                h, w = vis.shape[:2]
                fps_guess = max(1.0, frames / max(1e-6, time.monotonic() - start))
                writer = cv2.VideoWriter(
                    output,
                    cv2.VideoWriter_fourcc(*"mp4v"),
                    fps_guess,
                    (w, h),
                )
                if not writer.isOpened():
                    writer.release()
                    writer = None
            if writer is not None:
                writer.write(vis)
            if display:
                cv2.imshow("lane model benchmark", vis)
                if cv2.waitKey(1) & 0xFF == 27:
                    break

    elapsed = time.monotonic() - start
    wall_elapsed = time.monotonic() - wall_start

    if writer is not None:
        writer.release()
    if cap is not None:
        cap.release()
    if camera is not None:
        camera.release()
    if display:
        cv2.destroyAllWindows()

    if total_frames == 0:
        raise RuntimeError("No frames were processed")

    infer_mean = float(np.mean(infer_times))
    infer_p50 = float(np.percentile(infer_times, 50))
    infer_p95 = float(np.percentile(infer_times, 95))
    model_mean = float(np.mean(model_times))
    wall_fps = total_frames / max(elapsed, 1e-9)

    print()
    print(f"Model:              {detector.spec.title}")
    print(f"Frames:             {total_frames}")
    print(f"Valid detections:   {valid_frames / total_frames * 100:.1f}%")
    print(f"Inference mean:     {format_ms(infer_mean)}")
    print(f"Inference p50:      {format_ms(infer_p50)}")
    print(f"Inference p95:      {format_ms(infer_p95)}")
    print(f"Pipeline FPS:       {1000.0 / infer_mean:.2f}")
    print(f"NCNN inference:     {format_ms(model_mean)}")
    print(f"NCNN FPS:           {1000.0 / model_mean:.2f}")
    print(f"Wall FPS:           {wall_fps:.2f}")
    print(f"Wall elapsed:       {wall_elapsed:.2f} s")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark lane models on a video or Pi camera."
    )
    parser.add_argument("--list", action="store_true", help="List available models")
    parser.add_argument("--model", choices=[m.name for m in list_models()])
    parser.add_argument("--input", help="Video/image sequence source path")
    parser.add_argument("--camera", action="store_true", help="Use the project camera")
    parser.add_argument(
        "--camera-mode",
        choices=["picam", "opencv"],
        default="picam",
        help="Camera backend when --camera is used",
    )
    parser.add_argument("--warmup", type=int, default=20)
    parser.add_argument("--frames", type=int, default=300)
    parser.add_argument("--display", action="store_true")
    parser.add_argument("--output", help="Optional output video")
    parser.add_argument("--threads", type=int, default=4)
    args = parser.parse_args()

    if args.list:
        for spec in list_models():
            print(
                f"{spec.name:28} | {spec.title:40} | "
                f"{spec.input_width}x{spec.input_height} | {spec.dataset:7} | {spec.params}"
            )
        return 0

    if not args.model:
        parser.error("--model is required unless --list is used")
    if bool(args.input) == bool(args.camera):
        parser.error("Choose exactly one of --input or --camera")

    detector = MLLaneDetector(args.model, cpu_threads=args.threads)
    return benchmark(
        detector,
        "camera" if args.camera else args.input,
        args.warmup,
        args.frames,
        args.display,
        args.output,
        args.camera_mode,
    )


if __name__ == "__main__":
    raise SystemExit(main())
