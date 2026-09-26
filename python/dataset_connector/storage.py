from __future__ import annotations

import re
import time
from pathlib import Path

import cv2


class DatasetImageStore:
    """Safe filesystem storage for captured dataset images."""

    IMAGE_PATTERN = re.compile(r"^frame_(\d{6})\.jpg$")

    def __init__(self, dataset_dir):
        self.dataset_dir = Path(dataset_dir)
        self.dataset_dir.mkdir(parents=True, exist_ok=True)

    def paths(self):
        return sorted(
            path
            for path in self.dataset_dir.glob("frame_*.jpg")
            if path.is_file() and self.IMAGE_PATTERN.fullmatch(path.name)
        )

    def count(self):
        return len(self.paths())

    def resolve(self, filename):
        filename = Path(str(filename)).name
        if self.IMAGE_PATTERN.fullmatch(filename) is None:
            raise ValueError("Invalid dataset image filename.")
        root = self.dataset_dir.resolve()
        path = (self.dataset_dir / filename).resolve()
        if path.parent != root:
            raise ValueError("Invalid dataset image path.")
        return path

    def next_path(self):
        indices = []
        for path in self.paths():
            match = self.IMAGE_PATTERN.fullmatch(path.name)
            if match:
                indices.append(int(match.group(1)))
        return self.dataset_dir / f"frame_{max(indices, default=0) + 1:06d}.jpg"

    def save(self, image):
        if image is None or getattr(image, "size", 0) == 0:
            raise ValueError("Cannot save an empty dataset image.")

        path = self.next_path()
        temp_path = path.with_name(
            f".{path.name}.{time.time_ns()}.tmp.jpg"
        )
        try:
            if not cv2.imwrite(str(temp_path), image):
                raise OSError(f"Failed to write {path.name}.")
            temp_path.replace(path)
            return path
        finally:
            try:
                temp_path.unlink()
            except OSError:
                pass

    def delete(self, filename):
        path = self.resolve(filename)
        if not path.exists():
            return False
        path.unlink()
        return True

    def clear(self):
        removed = 0
        for path in self.paths():
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
        return removed
