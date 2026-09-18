import argparse

def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--mode",
        choices=["city", "race"],
        default="city",
        help="Run mode."
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Enable debug mode"
    )

    parser.add_argument(
        "--stream",
        action="store_true",
        default=False,
        help="Enable stream"
    )

    parser.add_argument(
        "--stream-host",
        default=None,
        help="Stream bind address (default comes from mode config)"
    )

    parser.add_argument(
        "--stream-control",
        action="store_true",
        default=False,
        help="Allow the web dashboard to change runtime settings"
    )

    parser.add_argument(
        "--without-arduino",
        default=False,
        action="store_true",
        help="Without sending to arduino"
    )

    parser.add_argument(
        "--fps",
        default=False,
        action="store_true",
        help="Avg fps"
    )

    parser.add_argument(
        "--performance",
        action="store_true",
        default=False,
        help="Enable runtime performance diagnostics"
    )

    parser.add_argument(
        "--preflight",
        action="store_true",
        default=False,
        help="Run startup diagnostics and exit without starting the robot"
    )

    parser.add_argument(
        "--read-arduino-output",
        default=False,
        action="store_true",
        help="Display Arduino telemetry collected by the background serial reader"
    )

    parser.add_argument(
        "--ml-lane-model",
        choices=[
            "unet_depthwise_nano",
            "unet_depthwise_small",
            "ufld_culane_resnet18",
        ],
        default=None,
        help="Enable ML lane detection with the selected model. Omit to keep the existing detector."
    )

    return parser.parse_args()
