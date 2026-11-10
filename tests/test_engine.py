import os

from focusblocks.core import events as ev
from focusblocks.core.commands import Command
from focusblocks.core.models import ForegroundWindow, Mode, Status

from fakes import START, Harness, make_harness


def test_starts_ready_and_counts_on_work_desktop(h: Harness):
    assert h.engine.block_start is None
    h.tick(10)
    assert h.engine.status == Status.WORKING
    assert h.engine.detail == "Counting the Work desktop"
    assert h.engine.worked == 10
    assert h.engine.block_start is not None


def test_non_work_window_does_not_start_a_block(h: Harness):
    h.system.desktop = "Personal"
    h.tick(5)
    assert h.engine.block_start is None
    assert h.engine.status == Status.IDLE
    assert h.engine.detail == "Code isn't a work source. Open one to start."


def test_full_block_logs_and_starts_break(h: Harness):
    h.tick(120)
    assert h.engine.mode == Mode.BREAK
    assert h.engine.done == 1
    assert len(h.repo.blocks) == 1 and h.repo.blocks[0][3] is True
    assert ("Block 1 of 3 done", "Take a break or skip it? Choose on the pill.") in h.notifier.sent
    assert any(isinstance(e, ev.BlockCompleted) for e in h.published)


def test_break_ends_then_asks_ready(h: Harness):
    h.tick(120)
    h.tick(60)
    assert h.engine.mode == Mode.WAIT and h.engine.status == Status.WAIT
    assert "Break's over" in h.notifier.titles
    h.tick(30)                                    # on a work window, but nothing counts until Ready
    assert h.engine.worked == 0 and h.engine.block_start is None
    h.tick(31)
    assert "Still on break?" in h.notifier.titles
    h.send(Command.READY)
    assert h.engine.mode == Mode.WORK
    h.tick(1)
    assert h.engine.worked == 1


def test_more_break_adds_minutes_then_asks_again(h: Harness):
    h.engine.cfg["more_break_minutes"] = 2
    h.tick(120 + 60)
    h.send(Command.MORE_BREAK)
    assert h.engine.mode == Mode.BREAK and h.engine.break_len == 120
    assert isinstance(h.published[-1], ev.BreakStarted) and h.published[-1].minutes == 2
    h.tick(119)
    assert h.engine.mode == Mode.BREAK
    h.tick(1)
    assert h.engine.mode == Mode.WAIT


def test_only_ready_and_more_break_answer_the_ready_question(h: Harness):
    h.tick(180)
    for cmd in (Command.TOGGLE_PAUSE, Command.SKIP_BREAK, Command.RESET, Command.TAKE_BREAK, Command.KEEP_GOING):
        h.send(cmd)
    assert h.engine.mode == Mode.WAIT
    h.send(Command.READY)
    h.send(Command.MORE_BREAK)                    # no longer asking: ignored
    assert h.engine.mode == Mode.WORK


def test_ready_and_more_break_do_nothing_outside_the_question(h: Harness):
    h.tick(10)
    h.send(Command.READY)
    h.send(Command.MORE_BREAK)
    assert h.engine.mode == Mode.WORK and h.engine.worked == 10


def test_overlay_break_skips_notification(h: Harness):
    h.engine.cfg["break_mode"] = "overlay"
    h.tick(120)
    assert h.engine.overlay is True
    assert not any(t.startswith("Take a") for t in h.notifier.titles)


def test_meeting_counts_and_never_shows_overlay(h: Harness):
    h.engine.cfg["break_mode"] = "overlay"
    h.system.desktop = "Personal"
    h.system.mic = True
    h.tick(120)
    assert h.engine.mode == Mode.BREAK
    assert h.engine.overlay is False


def test_daily_goal_notifies_once():
    h = make_harness(block_minutes=1, break_minutes=0.1, daily_goal=1)
    h.tick(60)
    assert h.notifier.titles.count("Daily goal hit") == 1
    h.engine.handle(Command.SKIP_BREAK)
    h.tick(60)
    assert h.notifier.titles.count("Daily goal hit") == 1
    assert sum(isinstance(e, ev.DailyGoalReached) for e in h.published) == 1


def test_abandoned_block_is_logged_as_partial(h: Harness):
    h.tick(90)
    h.system.desktop = "Personal"
    h.tick(1)
    assert h.engine.status == Status.AUTO_PAUSED
    assert h.engine.held_since is not None
    h.tick(59)
    assert h.engine.block_start is None
    assert h.repo.blocks[0][2:] == (1.5, False)
    assert h.engine.partial == 1


def test_short_abandoned_block_is_not_logged(h: Harness):
    h.tick(30)
    h.system.desktop = "Personal"
    h.tick(60)
    assert h.repo.blocks == []
    assert h.engine.block_start is None
    abandoned = [e for e in h.published if isinstance(e, ev.BlockAbandoned)]
    assert abandoned and abandoned[0].logged is False


def test_manual_pause_stops_counting_and_logs_duration(h: Harness):
    h.tick(10)
    h.send(Command.TOGGLE_PAUSE)
    assert h.engine.mode == Mode.PAUSED
    h.tick(120)
    assert h.engine.worked == 10
    assert h.engine.detail == "Click Resume to continue"
    h.send(Command.TOGGLE_PAUSE)
    assert h.engine.mode == Mode.WORK
    assert h.repo.events[-1][1:] == ("pause", 2.0)


def test_pause_during_break_keeps_remaining_break(h: Harness):
    h.tick(120)
    end = h.engine.break_end
    h.send(Command.TOGGLE_PAUSE)
    h.tick(30)
    h.send(Command.TOGGLE_PAUSE)
    assert h.engine.mode == Mode.BREAK
    assert h.engine.break_end == end + 30


def test_auto_resume_needs_you_to_leave_and_come_back():
    h = make_harness(pause_resume="auto")
    h.tick(5)
    h.send(Command.TOGGLE_PAUSE)
    h.tick(3)
    assert h.engine.mode == Mode.PAUSED          # still on work: not an absence yet
    h.system.desktop = "Personal"
    h.tick(1)
    assert h.engine.pause_left is True
    h.system.desktop = "Work"
    h.tick(1)
    assert h.engine.mode == Mode.WORK
    assert "Resumed" in h.notifier.titles


def test_lunch_is_ignored_by_pause(h: Harness):
    h.send(Command.LUNCH)
    h.send(Command.TOGGLE_PAUSE)
    assert h.engine.mode == Mode.LUNCH


def test_skip_break_logs_minutes_left(h: Harness):
    h.tick(120)
    h.tick(30)
    h.send(Command.SKIP_BREAK)
    assert h.engine.mode == Mode.WORK
    assert h.engine.status == Status.IDLE
    assert h.repo.events[-1][1:] == ("skip_break", 0.5)


def test_reset_discards_current_block(h: Harness):
    h.tick(30)
    h.send(Command.RESET)
    assert h.engine.worked == 0 and h.engine.block_start is None
    assert h.repo.events[-1][1:] == ("reset", 0.5)
    h.send(Command.RESET)                       # nothing to reset: no new event
    assert len(h.repo.events) == 1


def come_back_from_lunch(h: Harness) -> None:
    """Leave the PC untouched for over 2 minutes, then move the mouse."""
    h.system.idle = 130
    h.tick(1)
    h.system.idle = 0
    h.tick(1)


def test_welcome_back_after_being_away(h: Harness):
    h.send(Command.LUNCH)
    assert h.engine.mode == Mode.LUNCH
    h.system.idle = 130
    h.tick(1)
    assert not h.engine.lunch_nudge               # still away
    h.system.idle = 0
    h.tick(1)
    assert h.engine.lunch_nudge
    assert "Welcome back" in h.notifier.titles


def test_using_the_pc_without_leaving_does_not_ask(h: Harness):
    h.send(Command.LUNCH)
    h.tick(600)                                  # lunch at the desk
    assert not h.engine.lunch_nudge


def test_continue_resumes_the_block_from_before_lunch(h: Harness):
    h.tick(30)
    started = h.engine.block_start
    h.send(Command.LUNCH)
    come_back_from_lunch(h)
    h.send(Command.LUNCH)                         # Continue
    assert h.engine.mode == Mode.WORK
    assert h.repo.events[-1][1] == "lunch"
    assert "Lunch over" in h.notifier.titles
    h.tick(5)
    assert h.engine.worked == 35 and h.engine.block_start == started


def test_not_yet_asks_again_on_the_next_return(h: Harness):
    h.send(Command.LUNCH)
    come_back_from_lunch(h)
    h.send(Command.LUNCH_SNOOZE)
    assert not h.engine.lunch_nudge
    h.tick(30)
    assert not h.engine.lunch_nudge
    come_back_from_lunch(h)
    assert h.engine.lunch_nudge


def test_not_yet_asks_again_after_the_snooze_while_at_the_desk(h: Harness):
    h.send(Command.LUNCH)
    come_back_from_lunch(h)
    h.send(Command.LUNCH_SNOOZE)
    h.tick(10 * 60 - 5)
    assert not h.engine.lunch_nudge
    h.tick(5)
    assert h.engine.lunch_nudge


# ----- lunch time reminder -----
def lunch_at(time: str = "09:05") -> Harness:
    return make_harness(take_breaks=False, block_minutes=25, daily_goal=9, lunch_time=time, lunch_minutes=45)


def test_lunch_reminder_between_blocks():
    h = lunch_at()
    h.system.desktop = "Personal"                 # not working, so no block is running
    h.tick(4 * 60)
    assert h.engine.mode == Mode.WORK
    h.tick(60)                                    # 09:05
    assert h.engine.mode == Mode.LUNCH_TIME and h.engine.status == Status.LUNCH_TIME
    assert "Lunch time" in h.notifier.titles


def test_lunch_reminder_waits_for_the_running_block_to_end():
    h = lunch_at()
    h.tick(10 * 60)                               # 09:10, block in progress
    assert h.engine.mode == Mode.WORK and h.engine.block_start is not None
    h.tick(15 * 60)                               # block ends at 09:25
    assert h.engine.mode == Mode.LUNCH_TIME       # asked instead of "take a break?"
    assert h.engine.done == 1


def test_start_lunch_from_the_reminder():
    h = lunch_at()
    h.system.desktop = "Personal"
    h.tick(5 * 60)
    h.send(Command.LUNCH)
    assert h.engine.mode == Mode.LUNCH
    h.send(Command.LUNCH)                         # back already
    h.tick(10 * 60)
    assert h.engine.mode == Mode.WORK             # reminded once a day


def test_lunch_later_asks_again_in_15_minutes():
    h = lunch_at()
    h.system.desktop = "Personal"
    h.tick(5 * 60)
    h.send(Command.LUNCH_LATER)
    assert h.engine.mode == Mode.WORK
    h.tick(15 * 60 - 1)
    assert h.engine.mode == Mode.WORK
    h.tick(1)
    assert h.engine.mode == Mode.LUNCH_TIME


def test_lunch_later_after_a_block_goes_back_to_the_break_question():
    h = lunch_at()
    h.tick(25 * 60)
    assert h.engine.mode == Mode.LUNCH_TIME
    h.send(Command.LUNCH_LATER)
    assert h.engine.mode == Mode.BLOCK_DONE


def test_no_reminder_outside_the_lunch_window():
    h = lunch_at("08:00")                         # 08:00-08:45, the day starts at 09:00
    h.system.desktop = "Personal"
    h.tick(10 * 60)
    assert h.engine.mode == Mode.WORK


def test_manual_lunch_earlier_cancels_the_reminder():
    h = lunch_at()
    h.system.desktop = "Personal"
    h.tick(60)
    h.send(Command.LUNCH)
    h.send(Command.LUNCH)
    h.tick(10 * 60)
    assert h.engine.mode == Mode.WORK


def test_no_lunch_time_means_no_reminder():
    h = lunch_at("")
    h.system.desktop = "Personal"
    h.tick(10 * 60)
    assert h.engine.mode == Mode.WORK


def test_pause_does_nothing_while_asking_about_lunch():
    h = lunch_at()
    h.system.desktop = "Personal"
    h.tick(5 * 60)
    h.send(Command.TOGGLE_PAUSE)
    h.send(Command.TAKE_BREAK)
    assert h.engine.mode == Mode.LUNCH_TIME


def test_tagged_window_counts_and_clears_when_closed(h: Harness):
    h.system.desktop = "Personal"
    h.system.focus("chrome.exe", hwnd=200, title="Docs")
    h.send(Command.TAG_TOGGLE, 200, "Docs")
    h.tick(1)
    assert h.engine.detail == "Counting a tagged window"
    h.system.alive.discard(200)
    h.tick(1)
    assert h.engine.tags == {}


def test_tag_toggle_untags(h: Harness):
    h.send(Command.TAG_TOGGLE, 300, "x")
    h.send(Command.TAG_TOGGLE, 300, "x")
    assert h.engine.tags == {}
    assert h.notifier.titles[-2:] == ["Window tagged as work", "Window untagged"]


def test_short_idle_still_counts(h: Harness):
    h.tick(10)
    h.system.idle = h.engine.cfg["idle_seconds"] - 1    # reading, mouse untouched for a while
    h.tick(1)
    assert h.engine.status == Status.WORKING
    assert h.engine.worked == 11


def test_long_idle_pauses_the_block(h: Harness):
    h.tick(5)
    h.system.idle = h.engine.cfg["idle_seconds"]
    h.tick(1)
    assert h.engine.status == Status.AUTO_PAUSED
    assert h.engine.detail == "No activity. Resumes when you're back."
    assert h.engine.worked == 5
    h.system.idle = 0
    h.tick(1)
    assert h.engine.status == Status.WORKING and h.engine.worked == 6


def test_new_day_refreshes_counts(h: Harness):
    h.tick(120)
    assert h.engine.done == 1
    h.clock.current = START.replace(day=START.day + 1)
    h.tick(1)
    assert h.engine.done == 0
    assert h.engine.day == h.clock.today().isoformat()


def test_reload_merges_new_config(h: Harness):
    h.config.cfg["daily_goal"] = 12
    h.send(Command.RELOAD)
    assert h.engine.cfg["daily_goal"] == 12
    assert "Settings reloaded" in h.notifier.titles


def test_unknown_command_is_ignored(h: Harness):
    h.send("does_not_exist")
    assert h.engine.mode == Mode.WORK


def test_own_window_is_not_tracked(h: Harness):
    h.tick(1)
    before = h.engine.fg
    h.system.fg = ForegroundWindow(999, os.getpid(), "python.exe", "pill")
    h.tick(1)
    assert h.engine.fg == before


def test_snapshot_after_settling_on_a_desktop(h: Harness):
    h.tick(2)
    assert h.system.snapshots == []
    h.tick(3)
    assert h.system.snapshots == ["Work"]
    h.tick(60)
    assert h.system.snapshots == ["Work"]          # at most every 5 minutes


def test_test_commands_jump_ahead(h: Harness):
    h.send(Command.TEST_FINISH_BLOCK)
    h.tick(1)
    assert h.engine.mode == Mode.BREAK
    h.send(Command.TEST_END_BREAK)
    h.tick(1)
    assert h.engine.mode == Mode.WAIT


def test_lunch_later_from_the_ready_question_goes_back_to_it():
    h = make_harness(block_minutes=2, break_minutes=1, daily_goal=9, lunch_time="09:03", lunch_minutes=45)
    h.tick(120)                                   # 09:02, break until 09:03
    h.tick(60)
    assert h.engine.mode == Mode.WAIT
    h.tick(1)
    assert h.engine.mode == Mode.LUNCH_TIME
    h.send(Command.LUNCH_LATER)
    assert h.engine.mode == Mode.WAIT and h.engine.status == Status.WAIT


def test_failing_event_handler_does_not_break_engine(h: Harness):
    def boom(_):
        raise RuntimeError("plugin bug")

    h.engine.events.subscribe(ev.BlockCompleted, boom)
    h.tick(120)
    assert h.engine.mode == Mode.BREAK


def test_reload_of_broken_file_keeps_current_settings(h: Harness):
    h.engine.cfg["daily_goal"] = 12
    h.config.broken = True
    h.send(Command.RELOAD)
    assert h.engine.cfg["daily_goal"] == 12
    assert "Settings reloaded" not in h.notifier.titles


def test_desktop_previews_can_be_turned_off(h: Harness):
    h.engine.cfg["desktop_previews"] = False
    h.tick(600)
    assert h.system.snapshots == []


def test_shutdown_logs_the_block_in_progress(h: Harness):
    h.tick(90)
    h.engine.shutdown()
    assert [(b[2], b[3]) for b in h.repo.blocks] == [(1.5, False)]
    assert h.repo.closed


def test_shutdown_skips_a_very_short_block(h: Harness):
    h.tick(30)
    h.engine.shutdown()
    assert h.repo.blocks == []


def test_start_survives_an_unreadable_database(h: Harness):
    def broken(day):
        raise OSError("database is locked")

    h.repo.day_counts = broken  # type: ignore[method-assign]
    h.engine.start_tracking()
    assert "Couldn't read today's blocks" in h.notifier.titles
    h.tick(5)
    assert h.engine.status == Status.WORKING


def test_goal_met_before_a_restart_is_not_announced_again(h: Harness):
    for _ in range(3):                               # daily_goal is 3 in the fixture
        h.repo.log_block(START, START, 2, True)
    h.engine.start_tracking()
    h.tick(120)
    assert "Daily goal hit" not in h.notifier.titles
    assert not any(isinstance(e, ev.DailyGoalReached) for e in h.published)


# ----- Start / Stop -----
def stopped() -> Harness:
    return make_harness(started=False, block_minutes=2, break_minutes=1, daily_goal=3, abandon_minutes=1)


def test_new_engine_waits_for_start():
    h = stopped()
    h.tick(30)
    assert h.engine.mode == Mode.STOPPED
    assert h.engine.status == Status.STOPPED
    assert h.engine.worked == 0 and h.engine.block_start is None
    assert h.system.snapshots == []


def test_start_begins_tracking():
    h = stopped()
    h.send(Command.START)
    h.tick(10)
    assert h.engine.worked == 10
    assert h.engine.status == Status.WORKING
    assert any(isinstance(e, ev.TrackingStarted) for e in h.published)


def test_only_start_tag_and_reload_work_while_stopped():
    h = stopped()
    for cmd in (Command.TOGGLE_PAUSE, Command.LUNCH, Command.TEST_FINISH_BLOCK):
        h.send(cmd)
    assert h.engine.mode == Mode.STOPPED
    h.send(Command.TAG_TOGGLE, 100, "main.py")
    assert 100 in h.engine.tags


def test_stop_saves_block_in_progress_and_waits_again(h: Harness):
    h.tick(90)
    h.send(Command.STOP)
    assert [(b[2], b[3]) for b in h.repo.blocks] == [(1.5, False)]
    assert h.engine.mode == Mode.STOPPED
    assert any(isinstance(e, ev.TrackingStopped) for e in h.published)
    h.tick(30)
    assert h.engine.worked == 0


def test_stop_during_break_closes_overlay(h: Harness):
    h.engine.cfg["break_mode"] = "overlay"
    h.tick(120)
    assert h.engine.overlay
    h.send(Command.STOP)
    assert h.engine.mode == Mode.STOPPED and not h.engine.overlay


def test_stop_during_lunch(h: Harness):
    h.send(Command.LUNCH)
    h.send(Command.STOP)
    assert h.engine.mode == Mode.STOPPED


def test_start_again_after_stop(h: Harness):
    h.tick(10)
    h.send(Command.STOP)
    h.send(Command.START)
    h.tick(5)
    assert h.engine.worked == 5


# ----- editing times while running -----
def test_shorter_block_length_completes_the_current_block(h: Harness):
    h.tick(90)
    h.config.cfg["block_minutes"] = 1
    h.send(Command.RELOAD)
    h.tick(1)
    assert h.engine.mode == Mode.BREAK and h.engine.done == 1


def test_longer_block_length_extends_the_current_block(h: Harness):
    h.tick(90)
    h.config.cfg["block_minutes"] = 3
    h.send(Command.RELOAD)
    h.tick(60)
    assert h.engine.mode == Mode.WORK
    h.tick(30)
    assert h.engine.mode == Mode.BREAK


def test_break_length_change_applies_to_the_running_break(h: Harness):
    h.tick(120)                                   # block done, 1-min break starts
    h.tick(10)
    h.config.cfg["break_minutes"] = 3
    h.send(Command.RELOAD)
    h.tick(60)
    assert h.engine.mode == Mode.BREAK
    h.tick(110)
    assert h.engine.mode == Mode.WAIT


def test_break_length_change_leaves_a_more_break_alone(h: Harness):
    h.tick(180)
    h.send(Command.MORE_BREAK)                    # 5 min
    h.config.cfg["break_minutes"] = 3
    h.send(Command.RELOAD)
    assert h.engine.break_len == 300


def test_daily_goal_change_applies_right_away(h: Harness):
    h.config.cfg["daily_goal"] = 1
    h.send(Command.RELOAD)
    h.tick(120)
    assert "Daily goal hit" in h.notifier.titles


# ----- block ended: take a break or skip it -----
def asking(goal: int = 3, break_mode: str = "notify") -> Harness:
    """Nobody answers the questions unless the test does."""
    return make_harness(take_breaks=False, block_minutes=2, break_minutes=1, daily_goal=goal, abandon_minutes=1,
                        nudge_minutes=1, break_mode=break_mode)


def test_block_end_waits_for_a_decision():
    h = asking()
    h.tick(120)
    assert h.engine.mode == Mode.BLOCK_DONE and h.engine.status == Status.BLOCK_DONE
    assert h.notifier.titles.count("Block 1 of 3 done") == 1
    h.tick(600)                                    # walked away: still waiting, nothing counted
    assert h.engine.mode == Mode.BLOCK_DONE
    assert h.engine.worked == 0 and h.engine.block_start is None
    assert h.notifier.titles.count("Block 1 of 3 done") == 1


def test_take_a_break():
    h = asking()
    h.tick(120)
    h.send(Command.TAKE_BREAK)
    assert h.engine.mode == Mode.BREAK
    assert any(isinstance(e, ev.BreakStarted) for e in h.published)
    h.tick(60)
    assert h.engine.mode == Mode.WAIT


def test_skip_the_break_goes_straight_to_the_next_block():
    h = asking()
    h.tick(120)
    h.send(Command.SKIP_BREAK)
    assert h.repo.events[-1][1:] == ("skip_break", 1.0)
    h.tick(5)
    assert h.engine.mode == Mode.WORK and h.engine.worked == 5


def test_overlay_appears_only_after_choosing_the_break():
    h = asking(break_mode="overlay")
    h.tick(120)
    assert not h.engine.overlay
    h.send(Command.TAKE_BREAK)
    assert h.engine.overlay


def test_pause_does_nothing_while_asking_about_the_break():
    h = asking()
    h.tick(120)
    h.send(Command.TOGGLE_PAUSE)
    h.send(Command.KEEP_GOING)
    assert h.engine.mode == Mode.BLOCK_DONE


# ----- last block: keep going (break + one bonus block) or stop -----
def test_last_block_asks_keep_going_or_stop_without_a_break():
    h = asking(goal=1)
    h.tick(120)
    assert h.engine.mode == Mode.GOAL_MET and h.engine.status == Status.GOAL_MET
    assert "Daily goal hit" in h.notifier.titles
    assert not any(isinstance(e, ev.BreakStarted) for e in h.published)
    h.tick(600)
    assert h.engine.mode == Mode.GOAL_MET and h.engine.worked == 0


def test_stop_after_the_last_block_has_no_break():
    h = asking(goal=1)
    h.tick(120)
    h.send(Command.STOP)
    assert h.engine.mode == Mode.STOPPED
    assert not any(isinstance(e, ev.BreakStarted) for e in h.published)


def test_keep_going_is_a_break_then_exactly_one_bonus_block():
    h = asking(goal=1)
    h.tick(120)
    h.send(Command.KEEP_GOING)
    assert h.engine.mode == Mode.BREAK
    h.tick(60)
    assert h.engine.mode == Mode.WAIT
    h.send(Command.READY)
    h.tick(120)                                    # the bonus block
    assert h.engine.done == 2
    assert h.engine.mode == Mode.GOAL_MET          # asked again
    h.send(Command.KEEP_GOING)
    h.tick(60)
    h.send(Command.READY)
    h.tick(120)
    assert h.engine.done == 3 and h.engine.mode == Mode.GOAL_MET


def test_goal_notification_fires_once_a_day():
    h = asking(goal=1)
    h.tick(120)
    h.send(Command.KEEP_GOING)
    h.tick(60)
    h.send(Command.READY)
    h.tick(120)
    assert h.notifier.titles.count("Daily goal hit") == 1
    assert h.notifier.titles.count("Daily goal reached") == 1     # the bonus block asks again
    assert sum(isinstance(e, ev.DailyGoalReached) for e in h.published) == 1


def test_lowering_goal_during_break_announces_it_and_asks_after_break():
    h = asking(goal=2)                             # the reported bug
    h.tick(120)
    h.send(Command.TAKE_BREAK)
    h.tick(10)
    h.config.cfg["daily_goal"] = 1
    h.send(Command.RELOAD)
    assert "Daily goal hit" in h.notifier.titles
    assert any(isinstance(e, ev.DailyGoalReached) for e in h.published)
    h.tick(50)
    assert h.engine.mode == Mode.GOAL_MET
    h.send(Command.KEEP_GOING)                     # already had the break: straight into the bonus block
    h.tick(5)
    assert h.engine.mode == Mode.WORK and h.engine.worked == 5


def test_lowering_goal_while_waiting_for_work_asks_right_away():
    h = asking(goal=2)
    h.tick(120)
    h.send(Command.TAKE_BREAK)
    h.tick(60)
    assert h.engine.mode == Mode.WAIT
    h.config.cfg["daily_goal"] = 1
    h.send(Command.RELOAD)
    h.tick(1)
    assert h.engine.mode == Mode.GOAL_MET


def test_lowering_goal_while_asking_about_the_break_switches_question():
    h = asking(goal=2)
    h.tick(120)
    h.config.cfg["daily_goal"] = 1
    h.send(Command.RELOAD)
    h.tick(1)
    assert h.engine.mode == Mode.GOAL_MET
    h.send(Command.KEEP_GOING)
    assert h.engine.mode == Mode.BREAK


def test_raising_goal_after_the_last_block_offers_the_break_again():
    h = asking(goal=1)
    h.tick(120)
    h.config.cfg["daily_goal"] = 2
    h.send(Command.RELOAD)
    h.tick(1)
    assert h.engine.mode == Mode.BLOCK_DONE


def test_raising_goal_while_waiting_goes_back_to_normal():
    h = asking(goal=1)
    h.repo.log_block(START, START, 2, True)
    h.engine.refresh_counts()
    h.tick(1)
    assert h.engine.mode == Mode.GOAL_MET
    h.config.cfg["daily_goal"] = 2
    h.send(Command.RELOAD)
    h.tick(10)
    assert h.engine.worked == 10


def test_pause_and_reset_do_nothing_while_asking():
    h = asking(goal=1)
    h.tick(120)
    h.send(Command.TOGGLE_PAUSE)
    h.send(Command.RESET)
    h.send(Command.TAKE_BREAK)
    assert h.engine.mode == Mode.GOAL_MET


def test_goal_change_while_stopped_is_not_announced():
    h = make_harness(started=False, daily_goal=3)
    h.repo.log_block(START, START, 2, True)
    h.engine.refresh_counts()
    h.config.cfg["daily_goal"] = 1
    h.send(Command.RELOAD)
    assert "Daily goal hit" not in h.notifier.titles


def test_start_after_goal_already_met_asks():
    h = make_harness(started=False, daily_goal=1)
    h.repo.log_block(START, START, 2, True)
    h.engine.start_tracking()
    h.send(Command.START)
    h.tick(1)
    assert h.engine.mode == Mode.GOAL_MET


def test_stop_forgets_an_unused_keep_going():
    h = asking(goal=1)
    h.tick(120)
    h.send(Command.KEEP_GOING)                     # break, then a bonus block...
    h.send(Command.STOP)                           # ...but stopped during the break
    h.send(Command.START)
    h.tick(1)
    assert h.engine.mode == Mode.GOAL_MET          # asked again, no free bonus block


def test_a_new_day_forgets_an_unused_keep_going():
    h = asking(goal=1)
    h.tick(120)
    h.send(Command.KEEP_GOING)
    h.clock.current = START.replace(day=START.day + 1)
    h.tick(1)
    assert h.engine.bonus_left == 0


def test_test_menu_lunch_nudge_shows_welcome_back_at_once(h: Harness):
    h.send(Command.LUNCH)
    h.system.idle = 500                           # no real input needed
    h.send(Command.TEST_LUNCH_NUDGE)
    assert h.engine.lunch_nudge
