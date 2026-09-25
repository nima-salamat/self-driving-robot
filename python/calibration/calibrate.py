import argparse
import logging
from pathlib import Path

from .calibrator import CameraCalibrator


DEFAULT_IMAGE_DIR = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "images"
)
DEFAULT_OUTPUT_FILE = (
    Path(__file__).resolve().parents[1]
    / "assets"
    / "camera_calibration.npz"
)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Calibrate camera intrinsics from chessboard images.",
    )
    parser.add_argument(
        "--image-dir",
        type=Path,
        default=DEFAULT_IMAGE_DIR,
        help="Directory containing calibration images.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_FILE,
        help="Output NPZ calibration file.",
    )
    parser.add_argument(
        "--checkerboard-cols",
        type=int,
        default=11,
        help="Number of inner chessboard corners across.",
    )
    parser.add_argument(
        "--checkerboard-rows",
        type=int,
        default=7,
        help="Number of inner chessboard corners down.",
    )
    parser.add_argument(
        "--square-size",
        type=float,
        default=1.0,
        help="Physical square size in your chosen unit.",
    )
    parser.add_argument(
        "--min-valid-images",
        type=int,
        default=10,
        help="Minimum number of valid images required.",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] %(message)s",
    )

    if not args.image_dir.exists():
        raise SystemExit(
            f"Calibration image directory does not exist: "
            f"{args.image_dir}"
        )

    calibrator = CameraCalibrator(
        checkerboard=(
            args.checkerboard_cols,
            args.checkerboard_rows,
        ),
        square_size=args.square_size,
        min_valid_images=args.min_valid_images,
    )

    try:
        result = calibrator.calibrate_from_directory(
            args.image_dir,
            args.output,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    logging.getLogger(__name__).info(
        "Valid images: %d",
        result["valid_images"],
    )
    logging.getLogger(__name__).info(
        "RMS error: %.6f",
        result["rms"],
    )
    logging.getLogger(__name__).info(
        "Mean reprojection error: %.6f",
        result["mean_reprojection_error"],
    )
    logging.getLogger(__name__).info(
        "Image size: %dx%d",
        result["image_size"][0],
        result["image_size"][1],
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
