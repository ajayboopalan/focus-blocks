"""A year of focus blocks as a GitHub-style heatmap, with goal streaks."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from focusblocks.core.models import Config
from focusblocks.core.ports import BlockRepository

DayData = dict[str, tuple[int, float]]   # iso day -> (completed blocks, minutes)


def level(blocks: int, goal: int) -> int:
    """0 (none) .. 4 (goal met)."""
    if blocks == 0:
        return 0
    if blocks >= goal:
        return 4
    return 1 + min(2, (blocks * 3) // goal)


def calendar_start(today: dt.date) -> dt.date:
    """A year back, aligned to Sunday."""
    start = today - dt.timedelta(days=364)
    return start - dt.timedelta(days=(start.weekday() + 1) % 7)


@dataclass(frozen=True)
class Streaks:
    current: int
    best: int


def streaks(data: DayData, goal: int, start: dt.date, today: dt.date) -> Streaks:
    """Runs of days that met the goal. Today only counts toward the current streak once it's met."""
    def met(d: dt.date) -> bool:
        return data.get(d.isoformat(), (0,))[0] >= goal

    current = 0
    d = today if met(today) else today - dt.timedelta(days=1)
    while d >= start and met(d):               # with a goal of 0 every day is met: stop at the calendar
        current += 1
        d -= dt.timedelta(days=1)
    best = run_len = 0
    d = start
    while d <= today:
        run_len = run_len + 1 if met(d) else 0
        best = max(best, run_len)
        d += dt.timedelta(days=1)
    return Streaks(current, best)


@dataclass(frozen=True)
class HeatCell:
    day: dt.date
    col: int        # week, 0 = the oldest
    row: int        # 0 = Sunday .. 6 = Saturday
    level: int      # 0 .. 4, see level()
    blocks: int
    minutes: float

    @property
    def tip(self) -> str:
        blocks = f"{self.blocks} block{'s' if self.blocks != 1 else ''}"
        return f"{self.day:%a %b %d}: {blocks}, {self.minutes:.0f} min focused"


@dataclass(frozen=True)
class HeatmapGrid:
    cells: list[HeatCell]
    months: list[tuple[int, str]]   # (column, "Mar") where a month starts
    weeks: int
    today: int                      # completed blocks today
    streaks: Streaks
    total: int


def heatmap_grid(data: DayData, daily_goal: int, today: dt.date) -> HeatmapGrid:
    """Lay out a year of days in week columns, Sunday on top. Shared by the HTML report and the settings page."""
    start = calendar_start(today)
    cells: list[HeatCell] = []
    months: list[tuple[int, str]] = []
    d, col, last_month = start, -1, None
    while d <= today:
        if d.weekday() == 6:  # Sunday starts a new column
            col += 1
            if d.month != last_month and d.day <= 7:
                months.append((col, f"{d:%b}"))
            last_month = d.month
        c, m = data.get(d.isoformat(), (0, 0.0))
        cells.append(HeatCell(d, col, (d.weekday() + 1) % 7, level(c, daily_goal), c, m))
        d += dt.timedelta(days=1)
    return HeatmapGrid(cells, months, col + 1, data.get(today.isoformat(), (0, 0.0))[0],
                       streaks(data, daily_goal, start, today), sum(c for c, _ in data.values()))


def build_heatmap_html(data: DayData, daily_goal: int, block_minutes: float, today: dt.date) -> str:
    g = heatmap_grid(data, daily_goal, today)
    months = "".join(f'<span style="grid-column:{col + 1}">{name}</span>' for col, name in g.months)
    cells = "".join(f'<div class="c l{c.level}" style="grid-column:{c.col + 1};grid-row:{c.row + 1}" '
                    f'title="{c.tip}"></div>' for c in g.cells)
    return _PAGE.format(
        block_minutes=block_minutes, goal=daily_goal, months=months, cells=cells,
        today=g.today, streak=g.streaks.current, best=g.streaks.best, total=g.total)


class HeatmapReport:
    name = "heatmap"

    def render(self, cfg: Config, repo: BlockRepository, today: dt.date) -> str:
        return build_heatmap_html(repo.blocks_by_day(), cfg["daily_goal"], cfg["block_minutes"], today)


_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Focus blocks</title>
<style>
:root {{ --bg:#fbfaf9; --ink:#1d2229; --muted:#6b7480; --l0:#ebe8e5; --l1:#f6c7bd; --l2:#ec8f7c; --l3:#d8573f; --l4:#a8301c; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#16191d; --ink:#e9ecef; --muted:#8c96a1; --l0:#262b31; --l1:#5a2a22; --l2:#8a3a2b; --l3:#c4523b; --l4:#f07a5f; }} }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:16px/1.5 "Segoe UI Variable","Segoe UI",system-ui,sans-serif; }}
main {{ max-width:1000px; margin:48px auto; padding:0 24px; }}
h1 {{ font-size:28px; font-weight:600; margin:0 0 4px; }}
p.sub {{ color:var(--muted); margin:0 0 32px; }}
.wrap {{ overflow-x:auto; padding-bottom:8px; }}
.months, .grid {{ display:grid; grid-auto-flow:column; grid-auto-columns:14px; gap:3px; }}
.months {{ font-size:12px; color:var(--muted); height:18px; }}
.months span {{ white-space:nowrap; }}
.grid {{ grid-template-rows:repeat(7,14px); }}
.c {{ border-radius:3px; }}
.l0 {{ background:var(--l0); }} .l1 {{ background:var(--l1); }} .l2 {{ background:var(--l2); }}
.l3 {{ background:var(--l3); }} .l4 {{ background:var(--l4); }}
.stats {{ display:flex; flex-wrap:wrap; gap:40px; margin-top:32px; }}
.stats b {{ display:block; font-size:32px; font-weight:600; line-height:1.1; }}
.stats span {{ color:var(--muted); font-size:14px; }}
.legend {{ display:flex; align-items:center; gap:4px; font-size:12px; color:var(--muted); margin-top:12px; }}
.legend .c {{ width:12px; height:12px; }}
</style></head><body><main>
<h1>Focus blocks</h1>
<p class="sub">{block_minutes}-minute blocks over the last year. Daily goal: {goal}.</p>
<div class="wrap"><div class="months">{months}</div><div class="grid">{cells}</div></div>
<div class="legend">Less <div class="c l0"></div><div class="c l1"></div><div class="c l2"></div><div class="c l3"></div><div class="c l4"></div> Goal met</div>
<div class="stats">
<div><b>{today}/{goal}</b><span>today</span></div>
<div><b>{streak}</b><span>day streak</span></div>
<div><b>{best}</b><span>best streak</span></div>
<div><b>{total}</b><span>blocks total</span></div>
</div></main></body></html>"""  # noqa: E501
