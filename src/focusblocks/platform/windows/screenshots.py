from __future__ import annotations

from pathlib import Path

PREVIEW_SIZE = (480, 300)


class PillowDesktopSnapshotter:
    """Small screenshots used as desktop previews in settings. Saved locally only."""

    def __init__(self, snap_dir: Path):
        self.snap_dir = snap_dir

    def path_for(self, desktop: str) -> Path:
        slug = "".join(ch if ch.isalnum() else "_" for ch in desktop.lower()) or "desktop"
        return self.snap_dir / f"{slug}.png"

    def snapshot(self, desktop: str) -> bool:
        try:
            from PIL import ImageGrab, ImageOps
            self.snap_dir.mkdir(parents=True, exist_ok=True)
            img = ImageOps.fit(ImageGrab.grab(), PREVIEW_SIZE)
            img.save(self.path_for(desktop))
            return True
        except Exception:
            return False
