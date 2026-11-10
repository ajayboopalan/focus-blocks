"""Default settings. New keys added here are written into the user's config.json on next load."""

from __future__ import annotations

from typing import Any

CONFIG_VERSION = 3

DEFAULT_CONFIG: dict[str, Any] = {
    "block_minutes": 25,
    "break_minutes": 5,
    "more_break_minutes": 5,       # "N more min" when a break ends
    "daily_goal": 9,
    "break_mode": "notify",        # "notify" or "overlay" (full screen, skippable)
    "pause_resume": "manual",      # "manual" or "auto" (resumes when you're back on work)
    "work_desktops": ["Work"],     # virtual desktop names
    "work_apps": [],               # process names, e.g. "Code.exe", "ms-teams.exe"
    "tag_hotkey": "ctrl+alt+w",    # tag/untag the focused window (any tab in it counts)
    "count_meetings": True,        # mic or camera in use counts as work
    "idle_seconds": 180,           # no input this long mid-block -> the block pauses until you're back
    "abandon_minutes": 15,
    "nudge_minutes": 3,
    "lunch_time": "",              # "12:30": reminder to start lunch then ("" = no reminder)
    "lunch_minutes": 45,           # the reminder only shows inside lunch_time .. lunch_time + this
    "lunch_away_minutes": 2,       # PC untouched this long during lunch, then input -> "welcome back?"
    "lunch_snooze_minutes": 10,
    "desktop_previews": True,      # screenshot each desktop now and then for the settings picker
}

# Checked on load; a value that breaks a rule falls back to its default (see config.store.validate).
# Numbers in POSITIVE_KEYS must be > 0; other numbers just can't be < 0.
POSITIVE_KEYS = frozenset({"block_minutes", "break_minutes", "more_break_minutes", "daily_goal", "lunch_minutes",
                           "lunch_away_minutes"})
CHOICES: dict[str, tuple[str, ...]] = {
    "break_mode": ("notify", "overlay"),
    "pause_resume": ("manual", "auto"),
}

# Starting values for the separate test-mode config: everything happens in seconds, not minutes.
TEST_OVERRIDES: dict[str, Any] = {
    "block_minutes": 1, "break_minutes": 0.5, "more_break_minutes": 0.5, "idle_seconds": 15,
    "abandon_minutes": 2, "nudge_minutes": 0.5, "lunch_away_minutes": 0.25, "lunch_snooze_minutes": 1,
}

# Copied from the real config into a new test config so tests behave like your day.
TEST_INHERITED_KEYS = ("work_desktops", "work_apps", "break_mode", "pause_resume", "daily_goal",
                       "lunch_time", "lunch_minutes")
