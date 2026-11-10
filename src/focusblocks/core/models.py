"""Value types shared by the engine, adapters and UI."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, NamedTuple

Config = dict[str, Any]


class Mode(StrEnum):
    STOPPED = "STOPPED"  # not started yet, or stopped: nothing is counted
    GOAL_MET = "GOAL_MET"  # daily goal reached: waiting for "keep going" or "stop", nothing is counted
    BLOCK_DONE = "BLOCK_DONE"  # a block ended: waiting for "take a break" or "skip break", nothing is counted
    LUNCH_TIME = "LUNCH_TIME"  # lunch_time reached: waiting for "start lunch" or "in 15 min", nothing is counted
    WORK = "WORK"
    BREAK = "BREAK"
    WAIT = "WAIT"        # break is over: waiting for "ready" or "more break", nothing is counted
    PAUSED = "PAUSED"
    LUNCH = "LUNCH"


class Status(StrEnum):
    """Fine-grained state shown on the pill (see ``ui.theme.STATUS``)."""

    STOPPED = "stopped"
    GOAL_MET = "goal_met"
    BLOCK_DONE = "block_done"
    LUNCH_TIME = "lunch_time"
    IDLE = "idle"
    WORKING = "working"
    MEETING = "meeting"
    AUTO_PAUSED = "auto_paused"
    PAUSED = "paused"
    BREAK = "break"
    WAIT = "wait"
    LUNCH = "lunch"


class EventKind(StrEnum):
    """Rows in the ``events`` table."""

    PAUSE = "pause"
    SKIP_BREAK = "skip_break"
    RESET = "reset"
    LUNCH = "lunch"


class ForegroundWindow(NamedTuple):
    hwnd: int
    pid: int
    exe: str
    title: str


def app_display_name(exe: str) -> str:
    """'Code.exe' -> 'Code'."""
    return exe[:-4] if exe.lower().endswith(".exe") else exe


def parse_clock(value: object) -> tuple[int, int] | None:
    """'12:30' -> (12, 30); None unless it's a valid 24-hour HH:MM."""
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        return None
    hh, mm = value[:2], value[3:]
    if not (hh.isdigit() and mm.isdigit()) or int(hh) > 23 or int(mm) > 59:
        return None
    return int(hh), int(mm)
