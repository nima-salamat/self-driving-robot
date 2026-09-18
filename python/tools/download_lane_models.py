#!/usr/bin/env python3
import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve()
PYTHON_ROOT = HERE.parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from vision.ml_lane.registry import get_model_spec, list_models, resolve_model_path


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(spec):
    destination = resolve_model_path(spec.name)
    destination.parent.mkdir(parents=True, exist_ok=True)

    if destination.exists() and sha256(destination) == spec.sha256:
        print(f"[ok] {spec.name}: already installed")
        return

    temporary = destination.with_suffix(destination.suffix + ".part")
    print(f"[download] {spec.name} ONNX")
    urllib.request.urlretrieve(spec.model_url, temporary)

    actual = sha256(temporary)
    if actual != spec.sha256:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(
            f"SHA256 mismatch for {spec.name}: expected {spec.sha256}, got {actual}"
        )

    temporary.replace(destination)
    print(f"[ok] {destination} ({destination.stat().st_size / 1024:.1f} KiB)")

    for asset_url, relative_path in (
        (spec.ncnn_param_url, spec.ncnn_param_path),
        (spec.ncnn_bin_url, spec.ncnn_bin_path),
    ):
        asset = Path(relative_path)
        asset_path = Path(__file__).resolve().parents[1] / "models" / "lane" / asset.relative_to(Path("weights"))
        asset_path.parent.mkdir(parents=True, exist_ok=True)
        if asset_path.exists() and asset_path.stat().st_size > 0:
            print(f"[ok] {asset_path} already installed")
            continue
        asset_tmp = asset_path.with_suffix(asset_path.suffix + ".part")
        print(f"[download] {spec.name} {asset_path.name}")
        urllib.request.urlretrieve(asset_url, asset_tmp)
        if asset_tmp.stat().st_size == 0:
            asset_tmp.unlink(missing_ok=True)
            raise RuntimeError(f"Downloaded empty NCNN asset: {asset_path.name}")
        asset_tmp.replace(asset_path)
        print(f"[ok] {asset_path} ({asset_path.stat().st_size / 1024:.1f} KiB)")


def main():
    parser = argparse.ArgumentParser(description="Download verified ML lane models.")
    parser.add_argument(
        "--model",
        choices=[spec.name for spec in list_models()] + ["all"],
        default="all",
    )
    args = parser.parse_args()

    specs = list_models() if args.model == "all" else [get_model_spec(args.model)]
    failures = 0
    for spec in specs:
        try:
            download(spec)
        except Exception as exc:
            failures += 1
            print(f"[error] {spec.name}: {exc}", file=sys.stderr)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
