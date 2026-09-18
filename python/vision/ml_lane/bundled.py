import hashlib
import logging
import urllib.request

from .registry import get_model_spec, resolve_model_path


logger = logging.getLogger(__name__)


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_nonempty(url, destination):
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        urllib.request.urlretrieve(url, temporary)
        if temporary.stat().st_size == 0:
            raise RuntimeError(f"Downloaded empty model asset: {destination.name}")
        temporary.replace(destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def ensure_model_materialized(model_name):
    spec = get_model_spec(model_name)

    onnx_path = resolve_model_path(model_name)
    if onnx_path.exists() and _sha256(onnx_path) != spec.sha256:
        logger.warning("Lane model hash mismatch; removing %s", onnx_path)
        onnx_path.unlink()

    onnx_path.parent.mkdir(parents=True, exist_ok=True)
    if not onnx_path.exists():
        logger.info("Downloading lane ONNX artifact %s", model_name)
        _download_nonempty(spec.model_url, onnx_path.with_suffix(onnx_path.suffix + ".download"))
        downloaded = onnx_path.with_suffix(onnx_path.suffix + ".download")
        if _sha256(downloaded) != spec.sha256:
            downloaded.unlink(missing_ok=True)
            raise RuntimeError(f"SHA256 mismatch for {model_name}")
        downloaded.replace(onnx_path)

    param_path = onnx_path.parent / spec.ncnn_param_path.rsplit("/", 1)[-1]
    bin_path = onnx_path.parent / spec.ncnn_bin_path.rsplit("/", 1)[-1]

    if not param_path.exists():
        logger.info("Downloading NCNN param %s", model_name)
        _download_nonempty(spec.ncnn_param_url, param_path)

    if not bin_path.exists():
        logger.info("Downloading NCNN bin %s", model_name)
        _download_nonempty(spec.ncnn_bin_url, bin_path)

    return param_path, bin_path
