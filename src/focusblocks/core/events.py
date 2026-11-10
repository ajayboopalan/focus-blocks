"""Domain events and a small synchronous event bus.

The engine publishes an event whenever something meaningful happens. Add-ons subscribe to
react (post to Slack, play a sound, sync a calendar...) without touching the engine.
Handlers run on the engine thread, so they must be quick; a failing handler is logged and skipped.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Event:
    pass


@dataclass(frozen=True)
class TrackingStarted(Event):
    done: int
    goal: int


@dataclass(frozen=True)
class TrackingStopped(Event):
    pass


@dataclass(frozen=True)
class BlockStarted(Event):
    started: dt.datetime


@dataclass(frozen=True)
class BlockCompleted(Event):
    started: dt.datetime
    minutes: float
    done: int
    goal: int


@dataclass(frozen=True)
class BlockAbandoned(Event):
    started: dt.datetime
    minutes: float
    logged: bool        # partial blocks under a minute aren't stored


@dataclass(frozen=True)
class BlockReset(Event):
    minutes: float


@dataclass(frozen=True)
class DailyGoalReached(Event):
    done: int
    goal: int


@dataclass(frozen=True)
class BreakStarted(Event):
    minutes: float
    overlay: bool


@dataclass(frozen=True)
class BreakEnded(Event):
    pass


@dataclass(frozen=True)
class BreakSkipped(Event):
    minutes_left: float


@dataclass(frozen=True)
class Paused(Event):
    from_mode: str


@dataclass(frozen=True)
class Resumed(Event):
    paused_minutes: float


@dataclass(frozen=True)
class LunchStarted(Event):
    pass


@dataclass(frozen=True)
class LunchEnded(Event):
    minutes: float


@dataclass(frozen=True)
class WindowTagged(Event):
    hwnd: int
    title: str


@dataclass(frozen=True)
class WindowUntagged(Event):
    hwnd: int
    title: str


@dataclass(frozen=True)
class ConfigReloaded(Event):
    pass


E = TypeVar("E", bound=Event)
Handler = Callable[[Any], None]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type[Event], list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: type[E], handler: Callable[[E], None]) -> None:
        """Subscribe to one event type, or to ``Event`` for everything."""
        self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: type[E], handler: Callable[[E], None]) -> None:
        if handler in self._handlers.get(event_type, []):
            self._handlers[event_type].remove(handler)

    def publish(self, event: Event) -> None:
        for event_type in type(event).__mro__:
            for handler in list(self._handlers.get(event_type, ())):
                try:
                    handler(event)
                except Exception:
                    log.exception("event handler %r failed on %r", handler, event)
