import pytest

from focusblocks.ui.steppers import TIME_FIELDS, stepped


def field(key):
    return next(f for f in TIME_FIELDS if f.key == key)


@pytest.mark.parametrize(("key", "value", "direction", "expected"), [
    ("block_minutes", 25, +1, 30),
    ("block_minutes", 25, -1, 20),
    ("block_minutes", 120, +1, 120),     # stays at the top of the range
    ("block_minutes", 5, -1, 5),         # and the bottom
    ("block_minutes", 1, +1, 5),         # a test-mode value below the range snaps into it
    ("block_minutes", 27, +1, 30),       # an odd value from the file snaps to the step
    ("block_minutes", 27, -1, 25),
    ("break_minutes", 5, +1, 6),
    ("break_minutes", 0.5, +1, 1),
    ("break_minutes", 30, +1, 30),
    ("daily_goal", 9, +1, 10),
    ("daily_goal", 1, -1, 1),
    ("daily_goal", 20, +1, 20),
])
def test_stepped(key, value, direction, expected):
    assert stepped(field(key), value, direction) == expected


def test_fields_cover_the_three_settings():
    assert [f.key for f in TIME_FIELDS] == ["block_minutes", "break_minutes", "daily_goal"]


def test_lunch_fields():
    from focusblocks.ui.steppers import LUNCH_FIELDS, clock_minutes, clock_text

    time_field = next(f for f in LUNCH_FIELDS if f.key == "lunch_time")
    assert clock_text(750) == "12:30"
    assert clock_minutes("12:30") == 750
    assert clock_minutes("") is None
    assert stepped(time_field, 750, +1) == 765           # 15-minute steps
    assert stepped(time_field, 960, +1) == 960           # 16:00 at the latest
    assert stepped(time_field, 600, -1) == 600           # 10:00 at the earliest
    assert time_field.show(750) == "12:30"
    assert field("block_minutes").show(25) == "25"
