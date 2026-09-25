"""Authoritative traffic-sign class mapping."""

SIGN_LABELS = {
    0: "ERROR",
    1: "STOP",
    2: "TURN RIGHT",
    3: "TURN LEFT",
    4: "STRAIGHT",
    5: "PARK",
}
SIGN_NAMES = tuple(SIGN_LABELS[i] for i in sorted(SIGN_LABELS))
KEY_TO_LABEL = {str(label): label for label in SIGN_LABELS}


def label_name(label: int) -> str:
    return SIGN_LABELS.get(int(label), SIGN_LABELS[0])
