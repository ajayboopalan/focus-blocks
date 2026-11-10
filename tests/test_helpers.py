import pytest

from focusblocks.core.models import app_display_name
from focusblocks.platform.windows.hotkey import MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, parse_hotkey
from focusblocks.ui.fmt import duration, hmm, hop_offset, mix, mmss, plural


@pytest.mark.parametrize(("spec", "expected"), [
    ("ctrl+alt+w", (MOD_CONTROL | MOD_ALT, ord("W"))),
    ("Control + Shift + 5", (MOD_CONTROL | MOD_SHIFT, ord("5"))),
    ("win+f12", (MOD_WIN, 0x7B)),
    ("ctrl+alt", (MOD_CONTROL | MOD_ALT, 0)),
])
def test_parse_hotkey(spec, expected):
    assert parse_hotkey(spec) == expected


def test_time_formats():
    assert mmss(125.9) == "2:05"
    assert mmss(-3) == "0:00"
    assert hmm(3 * 3600 + 7 * 60) == "3:07"


def test_mix_endpoints():
    assert mix("#000000", "#ffffff", 0) == "#000000"
    assert mix("#000000", "#ffffff", 1) == "#ffffff"
    assert mix("#000000", "#ffffff", 0.5) == "#808080"


def test_hop_rests_after_two_hops():
    assert hop_offset(0) == 0
    assert hop_offset(0.42) < 0
    assert hop_offset(3.0) == 0


def test_text_helpers():
    assert app_display_name("Code.EXE") == "Code"
    assert app_display_name("bash") == "bash"
    assert plural(1, "app") == "1 app"
    assert plural(2, "app") == "2 apps"


@pytest.mark.parametrize(("sec", "text"), [
    (60, "a minute"), (10, "10 seconds"), (1, "1 second"), (600, "10 min"), (30, "30 seconds"), (90, "1.5 min"),
])
def test_duration(sec, text):
    assert duration(sec) == text
