"""In-memory stand-ins for every engine port, so the state machine runs without Windows."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from focusblocks.config import DEFAULT_CONFIG
from focusblocks.core.commands import Command
from focusblocks.core.engine import Engine, EngineServices
from focusblocks.core.events import Event, EventBus
from focusblocks.core.models import Config, ForegroundWindow, Mode

START = dt.datetime(2026, 3, 2, 9, 0, 0)   # a Monday morning


class FakeClock:
    def __init__(self, start: dt.datetime = START):
        self.current = start

    def time(self) -> float:
        return self.current.timestamp()

    def now(self) -> dt.datetime:
        return self.current

    def today(self) -> dt.date:
        return self.current.date()

    def advance(self, seconds: float) -> None:
        self.current += dt.timedelta(seconds=seconds)


class FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def notify(self, title: str, msg: str) -> None:
        self.sent.append((title, msg))

    @property
    def titles(self) -> list[str]:
        return [t for t, _ in self.sent]


@dataclass
class FakeRepo:
    blocks: list[tuple[dt.datetime, dt.datetime, float, bool]] = field(default_factory=list)
    events: list[tuple[dt.datetime, str, float]] = field(default_factory=list)
    closed: bool = False

    def log_block(self, started: dt.datetime, ended: dt.datetime, minutes: float, completed: bool) -> None:
        self.blocks.append((started, ended, round(minutes, 1), completed))

    def log_event(self, at: dt.datetime, kind: str, minutes: float = 0.0) -> None:
        self.events.append((at, str(kind), round(minutes, 1)))

    def close(self) -> None:
        self.closed = True

    def day_counts(self, day: dt.date) -> tuple[int, int]:
        same_day = [b for b in self.blocks if b[1].date() == day]   # filed under the day it ended
        return sum(1 for b in same_day if b[3]), sum(1 for b in same_day if not b[3])

    def blocks_by_day(self) -> dict[str, tuple[int, float]]:
        out: dict[str, tuple[int, float]] = {}
        for _, ended, minutes, completed in self.blocks:
            c, m = out.get(ended.date().isoformat(), (0, 0.0))
            out[ended.date().isoformat()] = (c + int(completed), m + minutes)
        return out


class FakeConfigSource:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.broken = False   # True: the file has a syntax error

    def load(self) -> Config:
        return dict(self.cfg)

    def reload(self) -> Config | None:
        return None if self.broken else dict(self.cfg)


class FakeSystem:
    """Input, windows, desktops, devices and snapshots in one controllable object."""

    def __init__(self) -> None:
        self.idle = 0.0
        self.fg: ForegroundWindow | None = ForegroundWindow(100, 4242, "Code.exe", "main.py - Code")
        self.alive: set[int] = {100, 200, 300}
        self.desktop: str | None = "Work"
        self.mic = self.cam = False
        self.snapshots: list[str] = []

    def idle_seconds(self) -> float:
        return self.idle

    def foreground(self) -> ForegroundWindow | None:
        return self.fg

    def window_alive(self, hwnd: int) -> bool:
        return hwnd in self.alive

    def current_desktop(self) -> str | None:
        return self.desktop

    def device_in_use(self, kind: str) -> bool:
        return self.mic if kind == "microphone" else self.cam

    def snapshot(self, desktop: str) -> bool:
        self.snapshots.append(desktop)
        return True

    def focus(self, exe: str, hwnd: int = 100, title: str = "") -> None:
        self.fg = ForegroundWindow(hwnd, 4242, exe, title or exe)
        self.alive.add(hwnd)


@dataclass
class Harness:
    engine: Engine
    clock: FakeClock
    notifier: FakeNotifier
    repo: FakeRepo
    system: FakeSystem
    config: FakeConfigSource
    published: list[Event]
    take_breaks: bool = True

    def tick(self, seconds: int = 1) -> None:
        """Advance time one second at a time, like the real loop.

        With take_breaks, "Take a break" is clicked as soon as a block ends, for tests about what follows.
        """
        for _ in range(seconds):
            self.clock.advance(1)
            self.engine.step(self.clock.time(), 1.0)
            if self.take_breaks and self.engine.mode == Mode.BLOCK_DONE:
                self.engine.handle(Command.TAKE_BREAK)

    def send(self, *cmd: object) -> None:
        self.engine.handle(*cmd)  # type: ignore[arg-type]


def make_harness(started: bool = True, take_breaks: bool = True, **overrides: object) -> Harness:
    """An engine on fakes. started=True clicks Start, so tests begin with tracking on."""
    cfg: Config = dict(DEFAULT_CONFIG, **overrides)
    clock, notifier, repo, system = FakeClock(), FakeNotifier(), FakeRepo(), FakeSystem()
    config = FakeConfigSource(cfg)
    services = EngineServices(clock=clock, notifier=notifier, repo=repo, config=config, input=system,
                              windows=system, desktops=system, devices=system, snapshots=system)
    bus = EventBus()
    published: list[Event] = []
    bus.subscribe(Event, published.append)
    engine = Engine(dict(cfg), services, bus)
    engine.refresh_counts()
    if started:
        engine.handle(Command.START)
        notifier.sent.clear()
        published.clear()
    return Harness(engine, clock, notifier, repo, system, config, published, take_breaks)
