import json
import time
from pathlib import Path

import cv2


class CalibrationImageStore:
    """Persist calibration frames together with the accepted detector result."""

    METADATA_SUFFIX = ".json"

    def __init__(self, image_dir):
        self.image_dir = Path(image_dir)
        self.image_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

    def count(self):
        return len(
            list(
                self.image_dir.glob(
                    "calib_*.jpg"
                )
            )
        )

    def next_path(self):
        indices = []
        for path in self.image_dir.glob(
            "calib_*.jpg"
        ):
            suffix = path.stem[6:]
            try:
                indices.append(
                    int(suffix)
                )
            except ValueError:
                continue

        next_index = (
            max(indices, default=0) + 1
        )
        return self.image_dir / (
            f"calib_{next_index:03d}.jpg"
        )

    def metadata_path(self, image_path):
        return Path(image_path).with_suffix(
            self.METADATA_SUFFIX
        )

    def save(self, image, metadata=None):
        if image is None or getattr(
            image,
            "size",
            0,
        ) == 0:
            raise ValueError(
                "Cannot save an empty calibration frame."
            )

        path = self.next_path()
        if not cv2.imwrite(
            str(path),
            image,
        ):
            raise IOError(
                f"Failed to save calibration image: {path}"
            )

        if metadata is not None:
            metadata_path = self.metadata_path(path)
            temp_path = metadata_path.with_name(
                f".{metadata_path.name}.{time.time_ns()}.tmp"
            )
            try:
                serialized = json.dumps(
                    metadata,
                    ensure_ascii=False,
                    allow_nan=False,
                    separators=(",", ":"),
                )
                temp_path.write_text(
                    serialized,
                    encoding="utf-8",
                )
                temp_path.replace(
                    metadata_path
                )
            except Exception:
                try:
                    path.unlink()
                except OSError:
                    pass
                try:
                    temp_path.unlink()
                except OSError:
                    pass
                raise

        return path

    def load_metadata(self, image_path):
        metadata_path = self.metadata_path(
            image_path
        )
        if not metadata_path.exists():
            return None
        try:
            metadata = json.loads(
                metadata_path.read_text(
                    encoding="utf-8"
                )
            )
        except (
            OSError,
            ValueError,
            TypeError,
        ):
            return None
        return (
            metadata
            if isinstance(metadata, dict)
            else None
        )

    def paths(self):
        return sorted(
            self.image_dir.glob(
                "calib_*.jpg"
            )
        )

    def clear(self):
        removed = 0

        for path in self.image_dir.glob(
            "calib_*.jpg"
        ):
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue

        for path in self.image_dir.glob(
            "calib_*.json"
        ):
            try:
                path.unlink()
            except OSError:
                continue

        return removed
