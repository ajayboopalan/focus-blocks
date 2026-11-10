import datetime as dt

from focusblocks.storage import SqliteBlockRepository

DAY = dt.datetime(2026, 3, 2, 9, 0)


def test_counts_and_history(tmp_path):
    repo = SqliteBlockRepository(tmp_path / "focus.db")
    repo.log_block(DAY, DAY + dt.timedelta(minutes=25), 25.04, True)
    repo.log_block(DAY, DAY + dt.timedelta(minutes=5), 4.96, False)
    next_day = DAY + dt.timedelta(days=1)
    repo.log_block(next_day, next_day + dt.timedelta(minutes=25), 25, True)
    assert repo.day_counts(DAY.date()) == (1, 1)
    assert repo.day_counts(DAY.date() - dt.timedelta(days=1)) == (0, 0)
    assert repo.blocks_by_day()["2026-03-02"] == (1, 30.0)
    repo.close()


def test_log_event_row(tmp_path):
    repo = SqliteBlockRepository(tmp_path / "focus.db")
    repo.log_event(DAY, "pause", 3.333)
    assert repo.con.execute("SELECT day, at, kind, minutes FROM events").fetchone() == (
        "2026-03-02", "2026-03-02T09:00:00", "pause", 3.3)
    repo.close()


def test_block_across_midnight_counts_on_the_day_it_ends(tmp_path):
    repo = SqliteBlockRepository(tmp_path / "focus.db")
    late = dt.datetime(2026, 3, 2, 23, 50)
    repo.log_block(late, late + dt.timedelta(minutes=25), 25, True)
    assert repo.day_counts(dt.date(2026, 3, 3)) == (1, 0)
    assert repo.day_counts(dt.date(2026, 3, 2)) == (0, 0)
    repo.close()
