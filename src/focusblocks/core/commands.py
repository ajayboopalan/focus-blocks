"""Commands the UI and hotkey send to the engine through ``Engine.send``."""

from __future__ import annotations

from enum import StrEnum


class Command(StrEnum):
    START = "start"                 # begin tracking (the app opens stopped)
    STOP = "stop"                   # back to not started; the block in progress is kept as partial
    KEEP_GOING = "keep_going"       # daily goal reached: a break (if a block just ended), then one bonus block
    TAKE_BREAK = "take_break"       # a block just ended: start the break (SKIP_BREAK goes straight on)
    READY = "ready"                 # break's over: back for the next block
    MORE_BREAK = "more_break"       # break's over: a few more minutes of break first
    TOGGLE_PAUSE = "toggle_pause"
    SKIP_BREAK = "skip_break"
    RESET = "reset"
    LUNCH = "lunch"                 # start or end lunch
    LUNCH_SNOOZE = "lunch_snooze"   # "not yet" on the welcome-back question
    LUNCH_LATER = "lunch_later"     # "in 15 min" on the lunch-time reminder
    TAG_TOGGLE = "tag_toggle"       # args: hwnd, title
    UNTAG_ALL = "untag_all"
    RELOAD = "reload"
    # test mode: jump to any moment
    TEST_FINISH_BLOCK = "test_finish_block"
    TEST_END_BREAK = "test_end_break"
    TEST_LUNCH_NUDGE = "test_lunch_nudge"
