"""The tracking state machine.

Runs on a background thread. The UI reads its public attributes and sends commands through
``send()``; it never changes the engine's state directly. All OS access goes through the
ports in ``EngineServices``, so the engine can be driven tick by tick in tests.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import queue
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from focusblocks import APP_NAME
from focusblocks.core import events as ev
from focusblocks.core.commands import Command
from focusblocks.core.models import (
    Config,
    EventKind,
    ForegroundWindow,
    Mode,
    Status,
    app_display_name,
    parse_clock,
)
from focusblocks.core.ports import (
    BlockRepository,
    Clock,
    ConfigSource,
    DesktopMonitor,
    DesktopSnapshotter,
    DeviceMonitor,
    InputMonitor,
    Notifier,
    WindowMonitor,
)
from focusblocks.core.work_sources import WorkContext, WorkSourceRule, default_rules, find_work_source

log = logging.getLogger(__name__)

TICK_SECONDS = 1.0
MAX_TICK_SECONDS = 5.0                 # cap after sleep/hibernate
MIN_PARTIAL_BLOCK_SECONDS = 60         # shorter abandoned blocks aren't stored
SNAPSHOT_EVERY_SECONDS = 300
SNAPSHOT_SETTLE_SECONDS = 3            # wait after a desktop switch before taking a preview
SNAPSHOT_MAX_IDLE_SECONDS = 30
LUNCH_BACK_IDLE_SECONDS = 2            # input this recent after being away during lunch = "you're back"
LUNCH_LATER_MINUTES = 15               # "in 15 min" on the lunch-time reminder
LUNCH_DETAIL = "Tracking off until you end lunch"
WELCOME_BACK_DETAIL = "Welcome back. Continue with your blocks?"
BREAK_DETAIL = "Stand up, look away, stretch"
READY_DETAIL = "Starts when you use a work window"
STOPPED_DETAIL = "Click Start when you're ready. Change lengths in Settings first if you like."
WHILE_STOPPED = frozenset({Command.START, Command.TAG_TOGGLE, Command.UNTAG_ALL, Command.RELOAD})
NOT_ANSWERS = frozenset({Command.TOGGLE_PAUSE, Command.SKIP_BREAK, Command.RESET, Command.TEST_FINISH_BLOCK,
                         Command.TAKE_BREAK, Command.KEEP_GOING, Command.READY, Command.MORE_BREAK})
# While the pill asks a question, only its answers (and stop, lunch, tagging, reload) do anything.
NOT_WHILE_ASKING = {
    Mode.GOAL_MET: NOT_ANSWERS - {Command.KEEP_GOING},
    Mode.BLOCK_DONE: NOT_ANSWERS - {Command.TAKE_BREAK, Command.SKIP_BREAK},
    Mode.LUNCH_TIME: NOT_ANSWERS,
    Mode.WAIT: NOT_ANSWERS - {Command.READY, Command.MORE_BREAK},
}
GOAL_MET_DETAIL = "Keep going adds a break and one more block. Or stop for today."
BLOCK_DONE_DETAIL = "Take a break, or skip it and go straight into the next block?"
BREAK_OVER_DETAIL = "Break's over. Ready for the next block?"


@dataclass
class EngineServices:
    clock: Clock
    notifier: Notifier
    repo: BlockRepository
    config: ConfigSource
    input: InputMonitor
    windows: WindowMonitor
    desktops: DesktopMonitor
    devices: DeviceMonitor
    snapshots: DesktopSnapshotter


class Engine:
    def __init__(self, cfg: Config, services: EngineServices, events: ev.EventBus | None = None,
                 rules: Iterable[WorkSourceRule] | None = None):
        self.cfg = cfg
        self.services = services
        self.events = events or ev.EventBus()
        self.rules: list[WorkSourceRule] = list(rules) if rules is not None else default_rules()
        self.q: queue.Queue[tuple[Any, ...]] = queue.Queue()
        self._stop = threading.Event()

        self.mode = Mode.STOPPED
        self.status, self.detail = Status.STOPPED, STOPPED_DETAIL
        self.worked = 0.0             # seconds counted in the current block
        self.away = 0.0
        self.block_start: Any = None  # datetime when the current block started
        self.break_end = 0.0
        self.break_len = 0.0          # seconds: length of the break in progress (a regular or a "more" break)
        self.overlay = False          # show the full-screen break overlay
        self.last_nudge = 0.0
        self.paused_from, self.pause_at, self.pause_left = Mode.WORK, 0.0, False
        self.lunch_at = 0.0
        self.done = self.partial = 0
        self.day: str | None = None
        self.goal_sent_for: Any = None
        self.bonus_left = 0                    # bonus blocks allowed past the goal: "keep going" adds one
        self.asked_after_block = False         # the current question came right after a block ended
        self.done_in_meeting = False           # that block ended in a meeting: never cover the screen
        self.held_since: float | None = None   # when the current block got auto-paused
        self.lunch_away = False                # PC was untouched for lunch_away_minutes during this lunch
        self.lunch_nudge = False               # "welcome back?" prompt is showing
        self.lunch_snooze_until = 0.0          # after "not yet": ask again from then on, even without leaving
        self.lunch_taken_for: Any = None       # day lunch was taken: no lunch-time reminder after that
        self.lunch_remind_after = 0.0          # after "in 15 min"
        self.lunch_ask_return = Mode.WORK      # where "in 15 min" goes back to
        self.last_snap: dict[str, float] = {}
        self.snap_desk: str | None = None
        self.desk_changed_at = 0.0
        self.fg: ForegroundWindow | None = None  # last focused window that isn't ours
        self.tags: dict[int, str] = {}           # hwnd -> title of windows tagged as work

        self._handlers: dict[str, Callable[..., None]] = {
            Command.START: self._cmd_start,
            Command.STOP: self._cmd_stop,
            Command.KEEP_GOING: self._cmd_keep_going,
            Command.TAKE_BREAK: self._cmd_take_break,
            Command.READY: self._cmd_ready,
            Command.MORE_BREAK: self._cmd_more_break,
            Command.TOGGLE_PAUSE: self._cmd_toggle_pause,
            Command.SKIP_BREAK: self._cmd_skip_break,
            Command.RESET: self._cmd_reset,
            Command.LUNCH: self._cmd_lunch,
            Command.LUNCH_SNOOZE: self._cmd_lunch_snooze,
            Command.LUNCH_LATER: self._cmd_lunch_later,
            Command.TAG_TOGGLE: self._cmd_tag_toggle,
            Command.UNTAG_ALL: self._cmd_untag_all,
            Command.RELOAD: self._cmd_reload,
            Command.TEST_FINISH_BLOCK: self._cmd_test_finish_block,
            Command.TEST_END_BREAK: self._cmd_test_end_break,
            Command.TEST_LUNCH_NUDGE: self._cmd_test_lunch_nudge,
        }

    # shortcuts
    def _notify(self, title: str, msg: str) -> None:
        self.services.notifier.notify(title, msg)

    def _now(self) -> float:
        return self.services.clock.time()

    def _idle(self) -> float:
        return self.services.input.idle_seconds()

    def send(self, *cmd: Any) -> None:
        self.q.put(cmd)

    def stop(self) -> None:
        self._stop.set()

    # ----- main loop -----
    def run(self) -> None:
        self.start_tracking()
        try:
            self._loop()
        finally:
            self.shutdown()

    def start_tracking(self) -> None:
        """Read today's counts and announce the start. A database error here is reported, not fatal."""
        try:
            self.refresh_counts()
        except Exception:
            log.exception("could not read today's blocks")
            self._notify("Couldn't read today's blocks", "Counting from 0 for now. Details in focusblocks.log.")
        if self.done >= self.cfg["daily_goal"]:        # already announced before a restart
            self.goal_sent_for = self.services.clock.today()
        self._notify(APP_NAME, "Ready. Click Start on the pill to begin tracking.")

    def shutdown(self) -> None:
        """On quit: keep the block in progress as a partial one, then close the database."""
        self._save_partial_block()
        try:
            self.services.repo.close()
        except Exception:
            log.exception("could not close the database")

    def _save_partial_block(self) -> None:
        """Keep the block in progress as a partial one (if it's long enough to count), then clear it."""
        if self.block_start is not None and self.worked >= MIN_PARTIAL_BLOCK_SECONDS:
            try:
                self.services.repo.log_block(self.block_start, self.services.clock.now(), self.worked / 60, False)
            except Exception:
                log.exception("could not save the block in progress")
        self.reset_block()

    def _loop(self) -> None:
        last = next_tick = self._now()
        while not self._stop.is_set():
            try:
                cmd = self.q.get(timeout=max(0.0, next_tick - self._now()))
                try:
                    self.handle(*cmd)
                except Exception:
                    log.exception("command failed: %s", cmd)
                continue
            except queue.Empty:
                pass
            now = self._now()
            tick = min(now - last, MAX_TICK_SECONDS)
            last, next_tick = now, now + TICK_SECONDS
            try:
                self.step(now, tick)
            except Exception:
                log.exception("step failed")

    def refresh_counts(self) -> None:
        today = self.services.clock.today()
        self.day = today.isoformat()
        self.done, self.partial = self.services.repo.day_counts(today)

    def reset_block(self) -> None:
        self.worked, self.away, self.block_start, self.held_since = 0.0, 0.0, None, None

    # ----- what counts as work -----
    def update_foreground(self) -> None:
        win = self.services.windows
        fg = win.foreground()
        if fg and fg.pid != os.getpid():
            self.fg = fg
        for h in [h for h in self.tags if not win.window_alive(h)]:
            del self.tags[h]

    def work_source(self) -> str | None:
        """Why the current window counts as work, or None."""
        ctx = WorkContext(cfg=self.cfg, fg=self.fg, tags=self.tags, desktops=self.services.desktops)
        return find_work_source(ctx, self.rules)

    def in_meeting(self) -> bool:
        devices = self.services.devices
        return bool(self.cfg["count_meetings"] and
                    (devices.device_in_use("microphone") or devices.device_in_use("webcam")))

    def is_working(self) -> bool:
        if self.in_meeting():
            self.status, self.detail = Status.MEETING, "Mic or camera in use, counting"
            return True
        source = self.work_source()
        if not source:
            name = app_display_name((self.fg.exe if self.fg else "") or "This window")
            if self.block_start is None:
                self.status, self.detail = Status.IDLE, f"{name} isn't a work source. Open one to start."
            else:
                self.status, self.detail = Status.AUTO_PAUSED, f"{name} isn't a work source. Resumes on a work window."
            return False
        if self._idle() < self.cfg["idle_seconds"]:
            self.status, self.detail = Status.WORKING, f"Counting {source}"
            return True
        if self.block_start is None:
            self.status, self.detail = Status.IDLE, READY_DETAIL
        else:
            self.status, self.detail = Status.AUTO_PAUSED, "No activity. Resumes when you're back."
        return False

    def maybe_snapshot(self, now: float) -> None:
        """Keep a fresh preview of each desktop for the settings picker."""
        if not self.cfg["desktop_previews"] or self.mode in (Mode.LUNCH, Mode.BREAK):
            return
        desk = self.services.desktops.current_desktop()
        if not desk:
            return
        if desk != self.snap_desk:
            self.snap_desk, self.desk_changed_at = desk, now
            return
        if now - self.desk_changed_at < SNAPSHOT_SETTLE_SECONDS or self._idle() > SNAPSHOT_MAX_IDLE_SECONDS:
            return
        if now - self.last_snap.get(desk, 0) >= SNAPSHOT_EVERY_SECONDS and self.services.snapshots.snapshot(desk):
            self.last_snap[desk] = now

    # ----- one tick -----
    def step(self, now: float, tick: float) -> None:
        if self.day != self.services.clock.today().isoformat():
            self.refresh_counts()
            self.bonus_left = 0                       # a new day starts from its own goal
        self.update_foreground()
        if self.mode == Mode.STOPPED:
            self.status, self.detail = Status.STOPPED, STOPPED_DETAIL
            return
        self.maybe_snapshot(now)
        {
            Mode.LUNCH: self._step_lunch,
            Mode.PAUSED: self._step_paused,
            Mode.BREAK: self._step_break,
            Mode.GOAL_MET: self._step_goal_met,
            Mode.BLOCK_DONE: self._step_block_done,
            Mode.LUNCH_TIME: self._step_lunch_time,
            Mode.WAIT: self._step_wait,
        }.get(self.mode, self._step_active)(now, tick)

    def _step_lunch(self, now: float, tick: float) -> None:
        """Ask "welcome back?" on the first input after the PC was left alone (or once "not yet" runs out)."""
        self.status = Status.LUNCH
        idle = self._idle()
        if idle >= self.cfg["lunch_away_minutes"] * 60:
            self.lunch_away = True
        snooze_over = bool(self.lunch_snooze_until) and now >= self.lunch_snooze_until
        if not self.lunch_nudge and idle < LUNCH_BACK_IDLE_SECONDS and (self.lunch_away or snooze_over):
            self.lunch_nudge, self.lunch_away, self.lunch_snooze_until = True, False, 0.0
            self._notify("Welcome back", "Continue with your blocks? Choose on the pill.")
        self.detail = WELCOME_BACK_DETAIL if self.lunch_nudge else LUNCH_DETAIL

    # ----- lunch-time reminder -----
    def _lunch_reminder_due(self) -> bool:
        """Inside today's lunch window, lunch not taken yet, and not put off with "in 15 min"."""
        clock = parse_clock(self.cfg["lunch_time"])
        if clock is None or self.lunch_taken_for == self.services.clock.today():
            return False
        now_dt = self.services.clock.now()
        start = now_dt.replace(hour=clock[0], minute=clock[1], second=0, microsecond=0)
        in_window = start <= now_dt < start + dt.timedelta(minutes=self.cfg["lunch_minutes"])
        return in_window and self._now() >= self.lunch_remind_after

    def _ask_lunch_time(self, return_to: Mode) -> None:
        self.lunch_ask_return = return_to
        self.mode, self.overlay = Mode.LUNCH_TIME, False
        self.status, self.detail = Status.LUNCH_TIME, self._lunch_time_detail()
        self._notify("Lunch time", f"{self._lunch_time_detail()} Choose on the pill.")

    def _lunch_time_detail(self) -> str:
        return f"Lunch at {self.cfg['lunch_time']} for {self.cfg['lunch_minutes']:g} min. Start it now?"

    def _step_lunch_time(self, now: float, tick: float) -> None:
        if parse_clock(self.cfg["lunch_time"]) is None:   # reminder turned off while asking
            self._cmd_lunch_later(now)
            return
        self.status, self.detail = Status.LUNCH_TIME, self._lunch_time_detail()

    def _step_paused(self, now: float, tick: float) -> None:
        if self.cfg["pause_resume"] == "auto":
            working = self.is_working()
            if not working:
                self.pause_left = True
            elif self.pause_left:
                self.resume(now)
                self._notify("Resumed", "You're back on work.")
                return
            self.detail = "Resumes when you're back on work"
        else:
            self.detail = "Click Resume to continue"
        self.status = Status.PAUSED

    def _step_break(self, now: float, tick: float) -> None:
        self.status, self.detail = Status.BREAK, BREAK_DETAIL
        if now >= self.break_end:
            self.overlay = False
            self.events.publish(ev.BreakEnded())
            if self._goal_choice_due():
                self._ask_goal_met()
                return
            self._ask_ready(now)

    # ----- break over: ready for the next block? -----
    def _ask_ready(self, now: float, notify: bool = True) -> None:
        self.mode, self.overlay, self.last_nudge = Mode.WAIT, False, now
        self.status, self.detail = Status.WAIT, BREAK_OVER_DETAIL
        if notify:
            self._notify("Break's over", "Ready for the next block? Choose on the pill.")

    def _step_wait(self, now: float, tick: float) -> None:
        """Nothing counts until "Ready". Nudge now and then if nobody answers."""
        if self._goal_choice_due():                # goal lowered to what's done while asking
            self._ask_goal_met()
            return
        if self._lunch_reminder_due():
            self._ask_lunch_time(Mode.WAIT)
            return
        self.status, self.detail = Status.WAIT, BREAK_OVER_DETAIL
        if now - self.last_nudge >= self.cfg["nudge_minutes"] * 60:
            self.last_nudge = now
            self._notify("Still on break?", "Click Ready on the pill when you're back.")

    # ----- daily goal reached -----
    def _goal_choice_due(self) -> bool:
        """Goal reached and no bonus block is left from a "keep going"."""
        return self.done >= self.cfg["daily_goal"] and self.bonus_left == 0

    def _ask_goal_met(self, after_block: bool = False, notify: bool = True) -> None:
        self.mode, self.overlay, self.asked_after_block = Mode.GOAL_MET, False, after_block
        self.status, self.detail = Status.GOAL_MET, GOAL_MET_DETAIL
        if notify:
            self._notify("Daily goal reached", f"{self.done} of {self.cfg['daily_goal']} done. Keep going or stop?")

    def _step_goal_met(self, now: float, tick: float) -> None:
        if not self._goal_choice_due():           # goal raised, or a new day
            if self.asked_after_block:
                self._ask_block_done(notify=False)
            else:
                self.mode, self.status, self.detail = Mode.WORK, Status.IDLE, READY_DETAIL
                self._step_active(now, tick)
            return
        self.status, self.detail = Status.GOAL_MET, GOAL_MET_DETAIL

    # ----- block ended: break or skip -----
    def _ask_block_done(self, notify: bool = True) -> None:
        self.mode, self.overlay = Mode.BLOCK_DONE, False
        self.status, self.detail = Status.BLOCK_DONE, BLOCK_DONE_DETAIL
        if notify:
            self._notify(f"Block {self.done} of {self.cfg['daily_goal']} done",
                         "Take a break or skip it? Choose on the pill.")

    def _step_block_done(self, now: float, tick: float) -> None:
        if self._goal_choice_due():               # goal lowered to what's done while asking
            self._ask_goal_met(after_block=True, notify=False)
            return
        self.status, self.detail = Status.BLOCK_DONE, BLOCK_DONE_DETAIL

    def _start_break(self, now: float, minutes: float | None = None) -> None:
        cfg = self.cfg
        minutes = cfg["break_minutes"] if minutes is None else minutes
        self.break_len = minutes * 60
        self.mode, self.break_end = Mode.BREAK, now + self.break_len
        self.status, self.detail = Status.BREAK, BREAK_DETAIL
        self.overlay = cfg["break_mode"] == "overlay" and not self.done_in_meeting
        self.events.publish(ev.BreakStarted(minutes, self.overlay))

    def _announce_goal_if_reached(self) -> bool:
        n, goal, today = self.done, self.cfg["daily_goal"], self.services.clock.today()
        if n < goal or self.goal_sent_for == today:
            return False
        self.goal_sent_for = today
        self._notify("Daily goal hit", f"{n} of {goal} blocks done today. Keep going or stop?")
        self.events.publish(ev.DailyGoalReached(n, goal))
        return True

    def _step_active(self, now: float, tick: float) -> None:
        """WORK: count time on work sources, start/abandon/complete blocks."""
        cfg = self.cfg
        if self.block_start is None and self._goal_choice_due():
            self._ask_goal_met()
            return
        if self.block_start is None and self._lunch_reminder_due():
            self._ask_lunch_time(self.mode)
            return
        working = self.is_working()

        if working:
            if self.block_start is None:
                self.block_start = self.services.clock.now()
                self.events.publish(ev.BlockStarted(self.block_start))
            self.worked += tick
            self.away, self.held_since = 0.0, None
        elif self.block_start is not None:
            self.held_since = self.held_since or now
            self.away += tick
            if self.away >= cfg["abandon_minutes"] * 60:
                self._abandon_block()

        if self.worked >= cfg["block_minutes"] * 60:
            self.complete_block(now)

    def _abandon_block(self) -> None:
        started, minutes = self.block_start, self.worked / 60
        logged = self.worked >= MIN_PARTIAL_BLOCK_SECONDS
        if logged:
            self.services.repo.log_block(started, self.services.clock.now(), minutes, False)
        self.reset_block()
        self.refresh_counts()
        self.events.publish(ev.BlockAbandoned(started, minutes, logged))

    def complete_block(self, now: float) -> None:
        """Log the block, then ask: break or skip, or (goal reached) keep going or stop. Nothing counts meanwhile."""
        self.done_in_meeting = self.status == Status.MEETING
        started, minutes = self.block_start, self.worked / 60
        self.services.repo.log_block(started, self.services.clock.now(), minutes, True)
        self.reset_block()
        self.refresh_counts()
        n, goal = self.done, self.cfg["daily_goal"]
        self.events.publish(ev.BlockCompleted(started, minutes, n, goal))
        if n >= goal:
            self.bonus_left = 0                       # the goal block, or the one bonus block, is used up
            announced = self._announce_goal_if_reached()
            self._ask_goal_met(after_block=True, notify=not announced)
        elif self._lunch_reminder_due():
            self._ask_lunch_time(Mode.BLOCK_DONE)      # "take a break?" comes back after "in 15 min"
        else:
            self._ask_block_done()

    # ----- commands from the UI / hotkey -----
    def resume(self, now: float) -> None:
        if self.mode != Mode.PAUSED:
            return
        paused_minutes = (now - self.pause_at) / 60
        self._log_event(EventKind.PAUSE, paused_minutes)
        if self.paused_from == Mode.BREAK:
            self.break_end += now - self.pause_at      # keep the remaining break
        self.mode = self.paused_from
        self.events.publish(ev.Resumed(paused_minutes))

    def handle(self, cmd: str, *args: Any) -> None:
        handler = self._handlers.get(cmd)
        if handler is None:
            log.debug("unknown command ignored: %s", cmd)
            return
        if self.mode == Mode.STOPPED and cmd not in WHILE_STOPPED:
            log.debug("ignored while stopped: %s", cmd)
            return
        if cmd in NOT_WHILE_ASKING.get(self.mode, ()):
            log.debug("ignored while asking: %s", cmd)
            return
        handler(self._now(), *args)

    def _log_event(self, kind: str, minutes: float = 0.0) -> None:
        self.services.repo.log_event(self.services.clock.now(), kind, minutes)

    def _cmd_start(self, now: float) -> None:
        if self.mode != Mode.STOPPED:
            return
        self.mode, self.status, self.detail = Mode.WORK, Status.IDLE, READY_DETAIL
        self.last_nudge = now
        goal = self.cfg["daily_goal"]
        self._notify(APP_NAME, f"Tracking started - {self.done}/{goal} blocks today.")
        self.events.publish(ev.TrackingStarted(self.done, goal))

    def _cmd_stop(self, now: float) -> None:
        if self.mode == Mode.STOPPED:
            return
        self._save_partial_block()
        self.refresh_counts()
        self.bonus_left = 0                           # an unused "keep going" doesn't outlive a stop
        self.mode, self.overlay, self.lunch_nudge = Mode.STOPPED, False, False
        self.status, self.detail = Status.STOPPED, STOPPED_DETAIL
        self._notify("Tracking stopped", "Click Start when you're ready.")
        self.events.publish(ev.TrackingStopped())

    def _cmd_keep_going(self, now: float) -> None:
        if self.mode != Mode.GOAL_MET:
            return
        self.bonus_left = 1
        if self.asked_after_block:
            self._start_break(now)
        else:
            self.mode, self.status, self.detail = Mode.WORK, Status.IDLE, READY_DETAIL

    def _cmd_take_break(self, now: float) -> None:
        if self.mode == Mode.BLOCK_DONE:
            self._start_break(now)

    def _cmd_ready(self, now: float) -> None:
        """Break's over and you're back: the next block starts on a work window."""
        if self.mode == Mode.WAIT:
            self.mode, self.status, self.detail = Mode.WORK, Status.IDLE, READY_DETAIL

    def _cmd_more_break(self, now: float) -> None:
        """Break's over but you want a few more minutes."""
        if self.mode == Mode.WAIT:
            self._start_break(now, self.cfg["more_break_minutes"])

    def _cmd_toggle_pause(self, now: float) -> None:
        if self.mode == Mode.PAUSED:
            self.resume(now)
        elif self.mode != Mode.LUNCH:
            self.paused_from, self.pause_at, self.pause_left = self.mode, now, False
            self.mode, self.status = Mode.PAUSED, Status.PAUSED
            self.detail = ("Resumes when you're back on work"
                           if self.cfg["pause_resume"] == "auto" else "Click Resume to continue")
            self.events.publish(ev.Paused(self.paused_from))

    def _cmd_skip_break(self, now: float) -> None:
        if self.mode in (Mode.BLOCK_DONE, Mode.BREAK):
            left = (float(self.cfg["break_minutes"]) if self.mode == Mode.BLOCK_DONE    # skipped the whole break
                    else max(0.0, self.break_end - now) / 60)
            self._log_event(EventKind.SKIP_BREAK, left)
            self.mode, self.overlay, self.status = Mode.WORK, False, Status.IDLE
            self.detail = READY_DETAIL
            self.events.publish(ev.BreakSkipped(left))

    def _cmd_reset(self, now: float) -> None:
        if self.worked > 0 and self.mode in (Mode.WORK, Mode.PAUSED):
            minutes = self.worked / 60
            self._log_event(EventKind.RESET, minutes)
            self.reset_block()
            self.events.publish(ev.BlockReset(minutes))

    def _cmd_lunch(self, now: float) -> None:
        if self.mode == Mode.LUNCH:
            minutes = (now - self.lunch_at) / 60
            self._log_event(EventKind.LUNCH, minutes)
            self.mode, self.status = Mode.WORK, Status.IDLE
            self.lunch_nudge = False
            self.detail = READY_DETAIL
            self._notify("Lunch over", f"{self.done} of {self.cfg['daily_goal']} blocks so far.")
            self.events.publish(ev.LunchEnded(minutes))
        else:
            self.lunch_at, self.mode, self.overlay, self.away = now, Mode.LUNCH, False, 0.0
            self.lunch_away, self.lunch_nudge, self.lunch_snooze_until, self.held_since = False, False, 0.0, None
            self.lunch_taken_for = self.services.clock.today()
            self.status, self.detail = Status.LUNCH, LUNCH_DETAIL
            self.events.publish(ev.LunchStarted())

    def _cmd_lunch_snooze(self, now: float) -> None:
        self.lunch_nudge, self.lunch_away = False, False
        self.lunch_snooze_until = now + self.cfg["lunch_snooze_minutes"] * 60

    def _cmd_lunch_later(self, now: float) -> None:
        if self.mode != Mode.LUNCH_TIME:
            return
        self.lunch_remind_after = now + LUNCH_LATER_MINUTES * 60
        if self.lunch_ask_return == Mode.BLOCK_DONE:
            self._ask_block_done(notify=False)
        elif self.lunch_ask_return == Mode.WAIT:
            self._ask_ready(now, notify=False)
        else:
            self.mode, self.last_nudge = self.lunch_ask_return, now
            self.status, self.detail = Status.IDLE, READY_DETAIL

    def _cmd_tag_toggle(self, now: float, hwnd: int, title: str) -> None:
        if hwnd in self.tags:
            del self.tags[hwnd]
            self._notify("Window untagged", title[:80])
            self.events.publish(ev.WindowUntagged(hwnd, title))
        else:
            self.tags[hwnd] = title
            self._notify("Window tagged as work", title[:80])
            self.events.publish(ev.WindowTagged(hwnd, title))

    def _cmd_untag_all(self, now: float) -> None:
        self.tags.clear()

    def _cmd_reload(self, now: float) -> None:
        cfg = self.services.config.reload()
        if cfg is None:                 # file has an error; the store already said so
            return
        old_break = self.cfg["break_minutes"]
        self.cfg.update(cfg)
        on_break = self.mode == Mode.BREAK or (self.mode == Mode.PAUSED and self.paused_from == Mode.BREAK)
        if on_break and self.break_len == old_break * 60:      # a regular break, not "more minutes"
            delta = (self.cfg["break_minutes"] - old_break) * 60
            self.break_end += delta
            self.break_len += delta
        if self.done < self.cfg["daily_goal"]:
            self.goal_sent_for = None                # a raised goal gets announced when it's reached
        elif self.mode != Mode.STOPPED:
            self._announce_goal_if_reached()         # lowered to what's already done
        self._notify("Settings reloaded", "")
        self.events.publish(ev.ConfigReloaded())

    def _cmd_test_finish_block(self, now: float) -> None:
        """Jump to the end of the current block."""
        if self.mode == Mode.WORK:
            self.block_start = self.block_start or self.services.clock.now()
            self.worked = self.cfg["block_minutes"] * 60

    def _cmd_test_end_break(self, now: float) -> None:
        if self.mode == Mode.BREAK:
            self.break_end = now

    def _cmd_test_lunch_nudge(self, now: float) -> None:
        """Show "welcome back" now, as if you'd just come back."""
        if self.mode == Mode.LUNCH and not self.lunch_nudge:
            self.lunch_nudge, self.lunch_away, self.lunch_snooze_until = True, False, 0.0
            self.detail = WELCOME_BACK_DETAIL
            self._notify("Welcome back", "Continue with your blocks? Choose on the pill.")
