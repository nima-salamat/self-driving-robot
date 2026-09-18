import hashlib
import logging
import urllib.request
from pathlib import Path

from .registry import MODEL_ROOT, get_model_spec, resolve_model_path


logger = logging.getLogger(__name__)


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_model_materialized(model_name):
    spec = get_model_spec(model_name)
    destination = resolve_model_path(model_name)

    if destination.exists() and destination.stat().st_size > 0:
        actual = _sha256(destination)
        if actual == spec.sha256:
            return destination
        logger.warning("Lane model hash mismatch; re-downloading %s", model_name)
        destination.unlink()

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    logger.info("Downloading lane model %s", model_name)

    try:
        urllib.request.urlretrieve(spec.model_url, temporary)
        actual = _sha256(temporary)
        if actual != spec.sha256:
            raise RuntimeError(
                f"SHA256 mismatch for {model_name}: expected {spec.sha256}, got {actual}"
            )
        temporary.replace(destination)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise

    return destination
