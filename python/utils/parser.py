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
        default=False,
        action="store_true",
        help="Enable stream"
    )

    parser.add_argument(
        "--without-arduino",
        default=False,
        action="store_true",
        help="Without sending to arduino"
    )

    return parser.parse_args()
