"""Pure formatting and animation helpers (no Tk), so they're unit-testable."""

from __future__ import annotations

import math


def mmss(sec: float) -> str:
    sec = max(0, int(sec))
    return f"{sec // 60}:{sec % 60:02d}"


def hmm(sec: float) -> str:
    m = max(0, int(sec)) // 60
    return f"{m // 60}:{m % 60:02d}"


def mix(a: str, b: str, t: float) -> str:
    """Blend two #rrggbb colours; t=0 gives a, t=1 gives b."""
    ca, cb = [int(a[i:i + 2], 16) for i in (1, 3, 5)], [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb, strict=True))


def hop_offset(t: float) -> float:
    """Two soft hops, then rest, every 4.2 s (in px, negative = up)."""
    p = (t % 4.2) / 4.2
    if p < 0.2:
        return -9 * math.sin(math.pi * p / 0.2)
    if p < 0.34:
        return -4 * math.sin(math.pi * (p - 0.2) / 0.14)
    return 0.0


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def duration(sec: float) -> str:
    """Short spoken length for UI copy: '30 seconds', 'a minute', '10 min'."""
    if sec < 60:
        return plural(int(sec), "second")
    if sec == 60:
        return "a minute"
    return f"{sec / 60:g} min"


def more_label(minutes: float) -> str:
    """Button text for a little more break: '5 more min', '30 more sec'."""
    return f"{minutes:g} more min" if minutes >= 1 else f"{round(minutes * 60)} more sec"
