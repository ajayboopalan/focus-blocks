"""Interfaces the engine depends on (dependency inversion).

Each port is small and single-purpose so an adapter can be swapped or faked on its own:
Windows implementations live in ``focusblocks.platform.windows``, test fakes in ``tests/fakes.py``.
"""

from __future__ import annotations

import datetime as dt
from typing import Protocol

from focusblocks.core.models import Config, ForegroundWindow


class Clock(Protocol):
    def time(self) -> float: ...
    def now(self) -> dt.datetime: ...
    def today(self) -> dt.date: ...


class Notifier(Protocol):
    def notify(self, title: str, msg: str) -> None: ...


class InputMonitor(Protocol):
    def idle_seconds(self) -> float:
        """Seconds since the last keyboard or mouse input."""
        ...


class WindowMonitor(Protocol):
    def foreground(self) -> ForegroundWindow | None: ...
    def window_alive(self, hwnd: int) -> bool: ...


class DesktopMonitor(Protocol):
    def current_desktop(self) -> str | None:
        """Name of the current virtual desktop, or None if it can't be read."""
        ...


class DeviceMonitor(Protocol):
    def device_in_use(self, kind: str) -> bool:
        """True if any app is using the 'webcam' or 'microphone' right now."""
        ...


class DesktopSnapshotter(Protocol):
    def snapshot(self, desktop: str) -> bool: ...


class BlockRepository(Protocol):
    def log_block(self, started: dt.datetime, ended: dt.datetime, minutes: float, completed: bool) -> None: ...
    def log_event(self, at: dt.datetime, kind: str, minutes: float = 0.0) -> None: ...
    def day_counts(self, day: dt.date) -> tuple[int, int]:
        """(completed, partial) blocks on that day."""
        ...
    def blocks_by_day(self) -> dict[str, tuple[int, float]]:
        """{iso day: (completed blocks, minutes)}."""
        ...
    def close(self) -> None: ...


class ConfigSource(Protocol):
    def load(self) -> Config: ...

    def reload(self) -> Config | None:
        """Like load, but None when the file has an error, so the caller keeps what it has."""
        ...
