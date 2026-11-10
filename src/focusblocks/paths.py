"""Where Focus Blocks keeps its files. Test mode uses a separate folder so tests never touch real stats."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    data_dir: Path

    @classmethod
    def default(cls) -> AppPaths:
        return cls(Path.home() / ".focusblocks")

    @classmethod
    def test(cls) -> AppPaths:
        return cls(Path.home() / ".focusblocks-test")

    @property
    def db(self) -> Path:
        return self.data_dir / "focus.db"

    @property
    def config(self) -> Path:
        return self.data_dir / "config.json"

    @property
    def pill_position(self) -> Path:
        return self.data_dir / "pill.json"

    @property
    def log(self) -> Path:
        return self.data_dir / "focusblocks.log"

    @property
    def snaps(self) -> Path:
        return self.data_dir / "snaps"

    def report(self, name: str) -> Path:
        return self.data_dir / f"{name}.html"
