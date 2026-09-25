from pathlib import Path


class CalibrationImageStore:
    """Manage captured chessboard images without owning camera state."""

    def __init__(self, image_dir):
        self.image_dir = Path(image_dir)
        self.image_dir.mkdir(parents=True, exist_ok=True)

    def next_path(self):
        indices = []
        for path in self.image_dir.glob("calib_*.jpg"):
            suffix = path.stem[6:]
            try:
                indices.append(int(suffix))
            except ValueError:
                continue

        next_index = max(indices, default=0) + 1
        return self.image_dir / f"calib_{next_index:03d}.jpg"

    def count(self):
        return len(list(self.image_dir.glob("calib_*.jpg")))

    def clear(self):
        removed = 0
        for path in self.image_dir.glob("calib_*.jpg"):
            try:
                path.unlink()
                removed += 1
            except OSError:
                continue
        return removed
