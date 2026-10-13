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
        default=False,
        help="Enable the web stream; disabled unless this flag is supplied.",
    )

    parser.add_argument(
        "--stream-host",
        default=None,
        help=("Address to bind the dashboard to (default: 0.0.0.0, all interfaces). "
              "Use 127.0.0.1 for local-only access."),
    )

    stream_control_group = parser.add_mutually_exclusive_group()
    stream_control_group.add_argument(
        "--stream-control",
        dest="stream_control",
        action="store_true",
        default=None,
        help="Enable dashboard controls (enabled by default).",
    )
    stream_control_group.add_argument(
        "--stream-read-only",
        dest="stream_control",
        action="store_false",
        default=None,
        help="Disable dashboard mutation endpoints and make the stream read-only.",
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
        "--send-traffic-stop-command",
        action="store_true",
        default=None,
        help="Send the Arduino STOP command when a traffic STOP sign is detected.",
    )

    parser.add_argument(
        "--arduino-config",
        default=None,
        metavar="PATH",
        help=(
            "Opt in to the strict hello/cfg hardware handshake using PATH. "
            "Only use with firmware that implements the hardware-contract protocol; "
            "EEPROM/set-based firmware should omit this option."
        ),
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
