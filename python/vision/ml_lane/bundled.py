import base64
from pathlib import Path

from .registry import resolve_model_path


BUNDLE_ROOT = Path(__file__).resolve().parents[2] / "models" / "lane" / "bundled"


def _bundle_parts(model_name):
    stem = resolve_model_path(model_name).name
    return sorted(BUNDLE_ROOT.glob(f"{stem}.part*.b64"))


def ensure_model_materialized(model_name):
    destination = resolve_model_path(model_name)
    if destination.exists() and destination.stat().st_size > 0:
        return destination

    parts = _bundle_parts(model_name)
    if not parts:
        raise FileNotFoundError(
            f"No bundled weights found for {model_name}. Expected files under {BUNDLE_ROOT}."
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    with temporary.open("wb") as output:
        for part in parts:
            encoded = part.read_text(encoding="ascii").strip()
            output.write(base64.b64decode(encoded, validate=True))
    temporary.replace(destination)
    return destination
