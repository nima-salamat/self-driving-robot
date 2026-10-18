import argparse
import math

from utils.processing_rate import DEFAULT_TARGET_FPS


def _positive_finite_fps(value):
    try:
        fps = float(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("must be a positive finite number")
    if not math.isfinite(fps) or fps <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return fps


def _finite_nonnegative(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("must be a finite non-negative number")
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError("must be a finite non-negative number")
    return number


def _confidence(value):
    number = _finite_nonnegative(value)
    if number > 1:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return number


def parse_args(argv=None):
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
        "--target-fps",
        type=_positive_finite_fps,
        default=DEFAULT_TARGET_FPS,
        metavar="N",
        help=(
            "Maximum desired rate of complete vision-processing cycles per "
            f"second, including frame acquisition, perception, and applicable "
            f"inference (default: {DEFAULT_TARGET_FPS:g}); does not set camera FPS."
        ),
    )

    parser.add_argument("--race-start-on-stop-sign", action="store_true", default=False,
                        help="Race mode waits for STOP, then 1 second of fresh STOP absence.")
    parser.add_argument("--race-stop-absence-seconds", type=_finite_nonnegative, default=None,
                        metavar="SECONDS", help="Continuous fresh STOP absence required to start (default: 1.0).")
    parser.add_argument("--race-stop-confidence-threshold", type=_confidence, default=None,
                        metavar="0..1", help="Minimum YOLO sign confidence for Race start/finish STOP (default: 0.2).")
    parser.add_argument("--race-finish-after-seconds", type=_finite_nonnegative, default=None,
                        metavar="SECONDS", help="Enter Race finishing phase and enable STOP monitoring this many seconds after race start.")
    parser.add_argument("--race-finish-speed", type=int, default=None, metavar="SPEED",
                        help="Target speed in the Race finishing phase (valid controller range: -255..255).")

    parser.add_argument("--traffic-lights", action="store_true", default=False,
                        help="Enable safety-gated traffic-light crossing in City mode only.")
    parser.add_argument("--traffic-light-wait-before-check", action="store_true", default=False,
                        help="With --traffic-lights, wait CROSSWALK_SLEEP before first observation.")

    parser.add_argument(
        "--debug",
        action="store_true",
        default=None,
        help="Enable diagnostic visualizations; independent of --log-level.",
    )

    parser.add_argument(
        "--log-level",
        type=str.upper,
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        default="INFO",
        metavar="LEVEL",
        help="Minimum severity for console and output/robot.log (default: INFO).",
    )

    parser.add_argument(
        "--stream",
        action="store_true",
        default=False,
        help="Enable the web stream; disabled unless this flag is supplied.",
    )

    parser.add_argument(
        "--stream-request-logs",
        action="store_true",
        default=False,
        help="Show HTTP request/access logs from the stream server (off by default).",
    )

    parser.add_argument("--encoder-map", action="store_true", default=False,
                        help="Enable opt-in encoder odometry and the /encoder-map page (requires --stream).")
    parser.add_argument("--encoder-pulse-distance-cm", type=float, default=None, metavar="FLOAT",
                        help="Measured travel in cm per FALLING encoder pulse; overrides active mode config.")
    parser.add_argument("--encoder-wheelbase-cm", type=float, default=None, metavar="FLOAT",
                        help="Measured wheelbase in cm; overrides active mode config for calibrated odometry.")
    parser.add_argument("--encoder-road-wheel-angle-at-servo-min-deg", type=float, default=None, metavar="FLOAT",
                        help="Measured signed road-wheel angle at configured minimum servo command; overrides active mode config.")
    parser.add_argument("--encoder-road-wheel-angle-at-servo-max-deg", type=float, default=None, metavar="FLOAT",
                        help="Measured signed road-wheel angle at configured maximum servo command; overrides active mode config.")

    parser.add_argument("--confidence-aware", action="store_true", default=False,
                        help="Enable heuristic confidence-aware speed limiting.")
    parser.add_argument("--confidence-slow-threshold", type=float, default=0.65, metavar="FLOAT",
                        help="Confidence score below which speed is limited (default: 0.65).")
    parser.add_argument("--confidence-stop-threshold", type=float, default=0.30, metavar="FLOAT",
                        help="Confidence score at/below which speed is stopped (default: 0.30).")

    parser.add_argument("--adaptive-obstacle-avoidance", action="store_true", default=False,
                        help="Explicitly request host-adaptive obstacle handling (Race only).")
    parser.add_argument("--obstacle-trigger-distance-cm", type=float, default=35.0, metavar="FLOAT",
                        help="Begin obstacle assessment at this front range (default: 35 cm).")
    parser.add_argument("--obstacle-stop-distance-cm", type=float, default=4.0, metavar="FLOAT",
                        help="Firmware emergency stop threshold (default: 4 cm; not a proven safe stopping distance).")
    parser.add_argument("--obstacle-lane-width-cm", type=float, default=None, metavar="FLOAT",
                        help="Measured traversable lane width in cm.")
    parser.add_argument("--obstacle-robot-width-cm", type=float, default=None, metavar="FLOAT",
                        help="Measured robot width in cm.")
    parser.add_argument("--obstacle-clearance-cm", type=float, default=None, metavar="FLOAT",
                        help="Required measured side clearance in cm.")

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
        help="Enable dashboard controls and start the stream (enabled by default).",
    )
    stream_control_group.add_argument(
        "--stream-read-only",
        dest="stream_control",
        action="store_false",
        default=None,
        help="Start the stream in read-only mode; implies --stream and disables dashboard mutation endpoints.",
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

    args = parser.parse_args(argv)
    # A dashboard access-mode flag is an explicit request to run the dashboard.
    # Without this implication, --stream-read-only alone silently disables the
    # server because --stream defaults to False.
    if args.stream_control is not None:
        args.stream = True
    return args
