"""Rules that decide whether the focused window counts as work.

Rules are checked in order; the first one that returns a description wins. To add a new
kind of work source (a browser URL, a Git repo, a calendar...) write a class with a
``match(ctx)`` method and register it through a plugin (see ``focusblocks.plugins``).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

from focusblocks.core.models import Config, ForegroundWindow, app_display_name
from focusblocks.core.ports import DesktopMonitor

log = logging.getLogger(__name__)

# Rule classes already logged as failing, so a broken plugin doesn't flood the log every tick.
_reported: set[type] = set()


@dataclass(frozen=True)
class WorkContext:
    cfg: Config
    fg: ForegroundWindow | None
    tags: Mapping[int, str]
    desktops: DesktopMonitor

    @property
    def work_desktops(self) -> list[str]:
        return [d.lower() for d in self.cfg["work_desktops"]]

    @property
    def work_apps(self) -> list[str]:
        return [a.lower() for a in self.cfg["work_apps"]]


class WorkSourceRule(Protocol):
    def match(self, ctx: WorkContext) -> str | None:
        """Why the current window counts as work, or None if this rule doesn't apply."""
        ...


class NothingConfigured:
    """With no sources picked, every window counts."""

    def match(self, ctx: WorkContext) -> str | None:
        if not ctx.work_desktops and not ctx.work_apps and not ctx.tags:
            return "any window"
        return None


class TaggedWindow:
    def match(self, ctx: WorkContext) -> str | None:
        if ctx.fg and ctx.fg.hwnd in ctx.tags:
            return "a tagged window"
        return None


class WorkApp:
    def match(self, ctx: WorkContext) -> str | None:
        if ctx.fg and ctx.fg.exe and ctx.fg.exe.lower() in ctx.work_apps:
            return app_display_name(ctx.fg.exe)
        return None


class WorkDesktop:
    def match(self, ctx: WorkContext) -> str | None:
        desktops = ctx.work_desktops
        if not desktops:
            return None
        d = ctx.desktops.current_desktop()
        if d is None:
            return "any window (desktop check unavailable)"
        if d.lower() in desktops:
            return f"the {d} desktop"
        return None


def default_rules() -> list[WorkSourceRule]:
    return [NothingConfigured(), TaggedWindow(), WorkApp(), WorkDesktop()]


def find_work_source(ctx: WorkContext, rules: Iterable[WorkSourceRule]) -> str | None:
    for rule in rules:
        try:
            source = rule.match(ctx)
        except Exception:
            if type(rule) not in _reported:
                _reported.add(type(rule))
                log.exception("Work rule %s failed; skipping it", type(rule).__name__)
            continue
        if source:
            return source
    return None
