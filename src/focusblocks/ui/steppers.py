"""The - / + fields on the settings pages (no Tk, so they're unit-testable)."""

from __future__ import annotations

import math
from dataclasses import dataclass

from focusblocks.core.models import parse_clock


@dataclass(frozen=True)
class StepField:
    key: str          # config.json key
    label: str
    unit: str
    step: int
    lo: int
    hi: int
    clock: bool = False   # value is minutes after midnight, shown as HH:MM

    def show(self, value: float) -> str:
        return clock_text(int(value)) if self.clock else f"{value:g}"


TIME_FIELDS = (
    StepField("block_minutes", "Block length", "min", 5, 5, 120),
    StepField("break_minutes", "Break length", "min", 1, 1, 30),
    StepField("daily_goal", "Daily goal", "blocks", 1, 1, 20),
)

LUNCH_FIELDS = (
    StepField("lunch_time", "Lunch time", "", 15, 10 * 60, 16 * 60, clock=True),
    StepField("lunch_minutes", "Lunch length", "min", 5, 15, 120),
)
DEFAULT_LUNCH_MINUTES_OF_DAY = 12 * 60 + 30   # shown when the reminder is first switched on


def clock_text(minutes_of_day: int) -> str:
    return f"{minutes_of_day // 60:02d}:{minutes_of_day % 60:02d}"


def clock_minutes(value: str) -> int | None:
    """'12:30' -> 750; None for "" or anything that isn't HH:MM."""
    hm = parse_clock(value)
    return None if hm is None else hm[0] * 60 + hm[1]


def stepped(f: StepField, value: float, direction: int) -> int:
    """One press of - (direction -1) or + (+1): move to the next multiple of the step, kept in range.

    A value from the file that is off the step (27) or out of range (a 1-minute test block) snaps into place.
    """
    steps = math.floor(value / f.step) + 1 if direction > 0 else math.ceil(value / f.step) - 1
    return max(f.lo, min(f.hi, steps * f.step))
