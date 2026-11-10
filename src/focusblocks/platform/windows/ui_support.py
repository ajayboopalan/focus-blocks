"""OS services the Tk UI needs, bundled as one ``ui.context.UiPlatform`` implementation."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
from typing import Any

from focusblocks.platform.windows.desktops import list_desktops, pin_everywhere
from focusblocks.platform.windows.screenshots import PillowDesktopSnapshotter
from focusblocks.platform.windows.windows import running_apps

SPI_GETCLIENTAREAANIMATION = 0x1042


class WindowsUiPlatform:
    def __init__(self, snapshots: PillowDesktopSnapshotter):
        self._snapshots = snapshots

    def set_dpi_aware(self) -> None:
        """Crisp text on high-DPI screens. Must run before the first Tk window."""
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    def animations_enabled(self) -> bool:
        """Respects Windows Settings > Accessibility > Visual effects > Animation effects."""
        try:
            val = ctypes.c_int(1)
            ctypes.windll.user32.SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(val), 0)
            return bool(val.value)
        except Exception:
            return True

    def pin_everywhere(self, win: Any) -> None:
        pin_everywhere(win)

    def list_desktops(self) -> list[dict[str, Any]]:
        return list_desktops()

    def running_apps(self) -> dict[str, str]:
        return running_apps()

    def snapshot_path(self, desktop: str) -> Path:
        return self._snapshots.path_for(desktop)

    def open_file(self, path: Path) -> None:
        os.startfile(path)
