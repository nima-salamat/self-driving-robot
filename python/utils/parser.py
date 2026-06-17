import argparse

def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--mode",
        choices=["city", "race"],
        default="city",
        help="Run mode"
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Enable debug mode"
    )

    parser.add_argument(
        "--stream",
        default=True,
        action="store_true",
        help="Enable stream"
    )

    return parser.parse_args()