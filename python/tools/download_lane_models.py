#!/usr/bin/env python3
import argparse
import fnmatch
import hashlib
import io
import os
import sys
import tarfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve()
PYTHON_ROOT = HERE.parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from vision.ml_lane.registry import MODEL_ROOT, list_models


def _download(url, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp = destination.with_suffix(destination.suffix + ".part")
    print(f"Downloading {url}")
    urllib.request.urlretrieve(url, tmp)
    tmp.replace(destination)


def _safe_extract_select(archive_path, destination, pattern, preferred_name):
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as archive:
        members = [
            member for member in archive.getmembers()
            if member.isfile() and fnmatch.fnmatch(member.name.lower(), pattern.lower())
        ]
        if not members:
            raise RuntimeError(f"No archive member matched {pattern!r}")
        members.sort(key=lambda m: (preferred_name.lower() not in m.name.lower(), len(m.name)))
        member = members[0]

        target = destination / Path(member.name).name
        source = archive.extractfile(member)
        if source is None:
            raise RuntimeError(f"Could not read archive member {member.name}")
        with source, target.open("wb") as output:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
        return target


def _file_hash(path):
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def install_model(spec):
    if spec.model_url:
        destination = MODEL_ROOT / spec.model_path
        if destination.exists():
            print(f"[skip] {spec.name}: {destination}")
            return destination

        print(f"[install] {spec.name}")
        _download(spec.model_url, destination)
        print(f"[ok] {destination} ({destination.stat().st_size / 1024:.1f} KiB)")
        return destination

    if spec.archive_url:
        archive_dir = MODEL_ROOT / "_downloads"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_name = spec.name + ".tar.gz"
        archive_path = archive_dir / archive_name
        if not archive_path.exists():
            _download(spec.archive_url, archive_path)

        destination_dir = MODEL_ROOT / spec.name
        destination = _safe_extract_select(
            archive_path,
            destination_dir,
            spec.archive_glob or "*.onnx",
            "culane",
        )
        print(f"[ok] {destination} ({destination.stat().st_size / 1024 / 1024:.2f} MiB)")
        return destination

    raise RuntimeError(f"No download source configured for {spec.name}")


def main():
    parser = argparse.ArgumentParser(description="Download lane-detection model candidates.")
    parser.add_argument("--model", choices=[m.name for m in list_models()] + ["all"], default="all")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    selected = list_models() if args.model == "all" else [next(m for m in list_models() if m.name == args.model)]
    failures = 0
    for spec in selected:
        try:
            path = (
                MODEL_ROOT / spec.model_path
                if spec.model_path
                else next(MODEL_ROOT.glob(f"{spec.name}/**/*.onnx"), MODEL_ROOT / spec.name / f"{spec.name}.onnx")
            )
            if args.verify_only:
                if not path.exists():
                    raise FileNotFoundError(path)
                print(f"[ok] {spec.name}: {path} sha256={_file_hash(path)}")
            else:
                install_model(spec)
        except Exception as exc:
            failures += 1
            print(f"[error] {spec.name}: {exc}", file=sys.stderr)

    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
