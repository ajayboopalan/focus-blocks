"""Add-on support.

A plugin is a callable ``register(registry: PluginRegistry) -> None``. Installed packages expose it
through the ``focusblocks.plugins`` entry-point group::

    # in the add-on's pyproject.toml
    [project.entry-points."focusblocks.plugins"]
    slack = "focusblocks_slack:register"

From ``register`` a plugin can subscribe to engine events, add work-source rules and add reports.
A plugin that fails to load is logged and skipped; it never stops the tracker.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import TypeVar

from focusblocks.core.events import Event, EventBus
from focusblocks.core.work_sources import WorkSourceRule
from focusblocks.reports.base import Report, ReportRegistry

log = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "focusblocks.plugins"
E = TypeVar("E", bound=Event)


@dataclass
class PluginRegistry:
    events: EventBus
    work_rules: list[WorkSourceRule]
    reports: ReportRegistry

    def subscribe(self, event_type: type[E], handler: Callable[[E], None]) -> None:
        self.events.subscribe(event_type, handler)

    def add_work_rule(self, rule: WorkSourceRule, index: int | None = None) -> None:
        """Append a rule, or insert it at ``index`` to take priority over the built-in ones."""
        if index is None:
            self.work_rules.append(rule)
        else:
            self.work_rules.insert(index, rule)

    def add_report(self, report: Report) -> None:
        self.reports.register(report)


Plugin = Callable[[PluginRegistry], None]


def discover_plugins() -> list[tuple[str, Plugin]]:
    found = []
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            found.append((ep.name, ep.load()))
        except Exception:
            log.exception("could not import plugin %s", ep.name)
    return found


def load_plugins(registry: PluginRegistry, plugins: Iterable[tuple[str, Plugin]] | None = None) -> list[str]:
    """Run each plugin's register(); return the names that loaded."""
    loaded = []
    for name, register in discover_plugins() if plugins is None else plugins:
        try:
            register(registry)
            loaded.append(name)
            log.info("plugin loaded: %s", name)
        except Exception:
            log.exception("plugin %s failed to register", name)
    return loaded
