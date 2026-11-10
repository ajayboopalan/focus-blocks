"""Everything the UI needs from the rest of the app, passed in rather than imported."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from focusblocks.config import ConfigStore
from focusblocks.paths import AppPaths


class UiPlatform(Protocol):
    def set_dpi_aware(self) -> None: ...
    def animations_enabled(self) -> bool: ...
    def pin_everywhere(self, win: Any) -> None: ...
    def list_desktops(self) -> list[dict[str, Any]]: ...
    def running_apps(self) -> dict[str, str]: ...
    def snapshot_path(self, desktop: str) -> Path: ...
    def open_file(self, path: Path) -> None: ...


@dataclass
class UiContext:
    paths: AppPaths
    config_store: ConfigStore
    platform: UiPlatform
    load_history: Callable[[], dict[str, tuple[int, float]]]   # {iso day: (completed blocks, minutes)}
    test_mode: bool = False
