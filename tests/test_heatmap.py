import datetime as dt

from focusblocks.reports import HeatmapReport, default_reports
from focusblocks.reports.heatmap import build_heatmap_html, calendar_start, heatmap_grid, level, streaks

from fakes import FakeRepo

TODAY = dt.date(2026, 3, 4)   # a Wednesday


def test_level_scale():
    assert [level(c, 9) for c in (0, 1, 3, 6, 8, 9, 20)] == [0, 1, 2, 3, 3, 4, 4]


def test_calendar_starts_on_sunday_a_year_back():
    start = calendar_start(TODAY)
    assert start.weekday() == 6
    assert 364 <= (TODAY - start).days < 371


def test_streaks():
    data = {(TODAY - dt.timedelta(days=i)).isoformat(): (3, 75.0) for i in (1, 2, 3, 10, 11, 12, 13)}
    s = streaks(data, 3, calendar_start(TODAY), TODAY)
    assert (s.current, s.best) == (3, 4)


def test_today_counts_toward_streak_once_goal_met():
    data = {TODAY.isoformat(): (3, 75.0), (TODAY - dt.timedelta(days=1)).isoformat(): (3, 75.0)}
    assert streaks(data, 3, calendar_start(TODAY), TODAY).current == 2


def test_html_contains_stats_and_a_cell_per_day():
    html = build_heatmap_html({TODAY.isoformat(): (2, 50.0)}, 9, 25, TODAY)
    assert "<b>2/9</b>" in html
    assert "25-minute blocks" in html
    assert html.count('class="c l') == (TODAY - calendar_start(TODAY)).days + 1 + 5   # +5 legend cells
    assert "Wed Mar 04: 2 blocks, 50 min focused" in html


def test_report_registry_has_heatmap():
    report = default_reports().get("heatmap")
    assert isinstance(report, HeatmapReport)
    assert report.render({"daily_goal": 9, "block_minutes": 25}, FakeRepo(), TODAY).startswith("<!doctype html>")


def test_streaks_with_zero_goal_stop_at_calendar_start():
    start = calendar_start(TODAY)
    days = (TODAY - start).days + 1
    assert streaks({}, 0, start, TODAY) == streaks({}, 0, start, TODAY).__class__(days, days)


def test_grid_has_a_cell_per_day_in_week_columns():
    g = heatmap_grid({TODAY.isoformat(): (9, 225.0)}, 9, TODAY)
    assert len(g.cells) == (TODAY - calendar_start(TODAY)).days + 1
    assert (g.cells[0].col, g.cells[0].row) == (0, 0)             # a Sunday, top left
    last = g.cells[-1]
    assert last.day == TODAY and last.row == 3 and last.col == g.weeks - 1   # Wednesday
    assert last.level == 4 and last.tip == "Wed Mar 04: 9 blocks, 225 min focused"
    assert (g.today, g.total) == (9, 9)


def test_grid_month_labels_start_at_their_first_week():
    g = heatmap_grid({}, 9, TODAY)
    assert g.months[-1] == (g.cells[-1].col, "Mar")             # Sun Mar 1 starts the last week
    assert all(0 <= col < g.weeks for col, _ in g.months)
