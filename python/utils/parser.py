import argparse


def parse_args():
    parser = argparse.ArgumentParser(
        description="Self-driving robot runtime.",
    )

    parser.add_argument(
        "--mode",
        choices=["city", "race"],
        default="city",
        help="Run mode (default: city).",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        default=None,
        help="Enable debug output; overrides the mode configuration.",
    )

    parser.add_argument(
        "--stream",
        action="store_true",
        default=None,
        help="Enable the web stream; overrides the mode configuration.",
    )

    parser.add_argument(
        "--stream-host",
        default=None,
        help="Stream bind address; overrides the mode configuration.",
    )

    parser.add_argument(
        "--stream-control",
        action="store_true",
        default=None,
        help="Allow the web dashboard to change runtime settings; overrides the mode configuration.",
    )

    parser.add_argument(
        "--without-arduino",
        action="store_true",
        default=None,
        help="Run without opening the Arduino serial connection; overrides the mode configuration.",
    )

    parser.add_argument(
        "--fps",
        action="store_true",
        default=None,
        help="Show the runtime FPS counter; overrides the mode configuration.",
    )

    parser.add_argument(
        "--performance",
        action="store_true",
        default=None,
        help="Enable runtime performance diagnostics; overrides the mode configuration.",
    )

    parser.add_argument(
        "--preflight",
        action="store_true",
        default=None,
        help="Run startup diagnostics and exit without entering the control loop.",
    )

    parser.add_argument(
        "--read-arduino-output",
        action="store_true",
        default=None,
        help="Print telemetry lines received from Arduino.",
    )

    parser.add_argument(
        "--arduino-config",
        default=None,
        metavar="PATH",
        help="Enable the strict Arduino hardware contract using PATH.",
    )

    parser.add_argument(
        "--arduino-contract-timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Timeout for each Arduino hardware-contract exchange (default: 3 seconds).",
    )

    parser.add_argument(
        "--camera-mode",
        choices=["picam", "webcam", "opencv"],
        default=None,
        help="Select the camera backend; overrides the mode configuration.",
    )

    parser.add_argument(
        "--camera-index",
        type=int,
        default=None,
        metavar="INDEX",
        help="OpenCV camera index when using webcam/opencv; overrides the mode configuration.",
    )

    parser.add_argument(
        "--ml-lane-model",
        choices=[
            "unet_depthwise_nano",
            "unet_depthwise_small",
        ],
        default=None,
        help="Enable ML lane detection with the selected model.",
    )

    parser.add_argument(
        "--city-lane-detector",
        choices=["default", "blsf-beta"],
        default=None,
        help=(
            "City mode lane detector. 'blsf-beta' enables the experimental "
            "classical BLSF pipeline; default keeps the existing detector."
        ),
    )

    return parser.parse_args()
