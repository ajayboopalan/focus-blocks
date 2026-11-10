"""The floating pill: a compact timer that expands into a control panel on hover."""

from __future__ import annotations

import json
import logging
import math
import time
from typing import Any

from focusblocks import APP_NAME
from focusblocks.core.commands import Command
from focusblocks.core.engine import Engine
from focusblocks.core.models import Mode, Status
from focusblocks.ui.context import UiContext
from focusblocks.ui.fmt import duration, hmm, hop_offset, mix, mmss, more_label
from focusblocks.ui.kit import Button, Kit
from focusblocks.ui.overlay import BreakOverlay
from focusblocks.ui.theme import COL, INK, KEY, LINE, MUTED, STATUS, SUB, TEXT, TRACK

log = logging.getLogger(__name__)

FRAME_MS, FAST_FRAME_MS = 200, 50    # fast frames only while the lunch nudge animates
COLLAPSE_DELAY = 0.6                   # seconds after the pointer leaves before collapsing
ANIM_RECHECK_MS = 60_000
ASKING = (Mode.BLOCK_DONE, Mode.GOAL_MET, Mode.LUNCH_TIME, Mode.WAIT)   # the pill opens and hops until answered
BORDER_PX = 2.5                              # coloured outline, so the pill is easy to find on any background
ASK_HOP_PX = 0.7                            # of hop_offset's 9 px: about 6 px, two soft hops then rest


class Pill:
    M = 9                     # transparent margin around the pill, room for the lunch glow

    def __init__(self, engine: Engine, ctx: UiContext):
        import tkinter as tk
        ctx.platform.set_dpi_aware()
        self.tk, self.e, self.ctx = tk, engine, ctx
        self.clear_requested = False   # "Clear test data and quit" was picked
        self.root = root = tk.Tk()
        root.title(APP_NAME)
        self.k = Kit(root)
        self.S = S = self.k.S
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=KEY)
        try:
            root.attributes("-transparentcolor", KEY)
        except tk.TclError:
            pass
        self.cv = tk.Canvas(root, bg=KEY, highlightthickness=0, bd=0)
        self.cv.pack(fill="both", expand=True)
        try:
            self.right, self.top = json.loads(ctx.paths.pill_position.read_text())
        except Exception:
            self.right, self.top = root.winfo_screenwidth() - int(16 * S), int(16 * S)
        self.expanded, self.leave_at, self.menu_open = False, None, False
        self.buttons: list[Button] = []
        self.hot: Button | None = None
        self.geom = ""
        self.press: tuple[float, float, float, float] | None = None
        self.dragging = False
        self.overlay = BreakOverlay(root, self.k, engine, ctx.platform)
        self.settings: Any = None
        self.anim = ctx.platform.animations_enabled()

        cv = self.cv
        cv.bind("<ButtonPress-1>", self.on_press)
        cv.bind("<B1-Motion>", self.on_drag)
        cv.bind("<ButtonRelease-1>", self.on_release)
        cv.bind("<Motion>", lambda ev: setattr(self, "hot", self.k.hit(self.buttons, ev.x, ev.y)))
        cv.bind("<Button-3>", lambda ev: self.show_menu(ev.x_root, ev.y_root))
        self.menu = tk.Menu(root, tearoff=0)
        root.after(300, lambda: ctx.platform.pin_everywhere(root))
        root.after(ANIM_RECHECK_MS, self.refresh_anim_setting)
        self.loop()

    def mainloop(self) -> None:
        self.root.mainloop()

    def refresh_anim_setting(self):
        self.anim = self.ctx.platform.animations_enabled()
        self.root.after(ANIM_RECHECK_MS, self.refresh_anim_setting)

    def place(self, w, h):
        top = self.top + self.ask_hop()
        geom = f"{int(w)}x{int(h)}+{int(self.right - w)}+{int(top)}"
        if geom != self.geom:
            self.root.geometry(geom)
            self.geom = geom

    def asking(self) -> bool:
        """The pill is waiting for one of its buttons: block done, goal met, lunch time, or welcome back."""
        e = self.e
        return e.mode in ASKING or (e.mode == Mode.LUNCH and e.lunch_nudge)

    def ask_hop(self) -> float:
        """Vertical offset (px) of the whole pill while it waits for an answer; 0 otherwise."""
        if not self.anim or self.dragging or not self.asking():
            return 0.0
        return hop_offset(time.time()) * ASK_HOP_PX * self.S

    # ----- what to show -----
    def view(self) -> dict[str, Any]:
        e, cfg, now = self.e, self.e.cfg, time.time()
        goal, blk, brk = cfg["daily_goal"], cfg["block_minutes"] * 60, max(1.0, e.break_len)
        current = e.done + 1
        bonus = current - goal                 # past the daily goal after "keep going": 1, 2, ...
        block = f"bonus block {bonus}" if bonus > 0 else f"block {current}"
        label, ck = STATUS.get(e.status, (e.status, "paused"))
        v: dict[str, Any] = dict(label=label, color=COL[ck], clock_color=TEXT, paused_icon=False,
                                 count=f"{e.done}/{goal}",
                                 ring_text=f"+{bonus}" if bonus > 0 else f"{current}/{goal}")
        mode = e.paused_from if e.mode == Mode.PAUSED else e.mode
        if mode == Mode.STOPPED:
            v.update(clock="Not started", frac=0.0, ring_text=f"{e.done}/{goal}",
                     sub=f"{cfg['block_minutes']:g}-min blocks, {cfg['break_minutes']:g}-min breaks")
        elif mode == Mode.BLOCK_DONE:
            v.update(clock="Block done", frac=1.0, ring_text=f"{e.done}/{goal}",
                     sub=f"{cfg['break_minutes']:g}-min break next, if you want it")
        elif mode == Mode.LUNCH_TIME:
            v.update(clock="Lunch time", frac=1.0, ring_text=f"{e.done}/{goal}",
                     sub=f"{cfg['lunch_time']} for {cfg['lunch_minutes']:g} min")
        elif mode == Mode.GOAL_MET:
            v.update(clock="Goal met", frac=1.0, ring_text=f"{e.done}/{goal}",
                     sub=f"{e.done} of {goal} blocks done today")
        elif mode == Mode.BREAK:
            left = e.break_end - (e.pause_at if e.mode == Mode.PAUSED else now)
            v.update(clock=mmss(left), sub=f"of a {brk / 60:g}-min break", frac=left / brk,
                     ring_text=f"{e.done}/{goal}")
        elif e.mode == Mode.LUNCH:
            v.update(clock=hmm(now - e.lunch_at), sub="on lunch, tracking off", frac=e.worked / blk)
        elif mode == Mode.WAIT:
            v.update(clock="Ready?", sub=f"{block[:1].upper()}{block[1:]} starts when you click Ready", frac=1.0)
        else:
            v.update(clock=mmss(blk - e.worked), frac=e.worked / blk)
            if e.status == Status.AUTO_PAUSED and e.held_since:
                v.update(clock_color=COL["paused"], paused_icon=True,
                         sub=f"held for {int((now - e.held_since) // 60)} min")
            elif e.block_start is None:
                v["sub"] = f"{block} starts on a work window"
            else:
                v["sub"] = f"left in {block}"
        if e.mode == Mode.PAUSED:
            v.update(label="Paused", color=COL["paused"], clock_color=COL["paused"], paused_icon=True,
                     sub="resumes on a work window" if cfg["pause_resume"] == "auto" else "paused by you")
        v["frac"] = max(0.0, min(1.0, v["frac"]))
        return v

    # ----- loop -----
    def loop(self):
        try:
            self.update_hover()
            self.render()
            self.overlay.sync()
        except Exception:
            log.exception("ui error")
        fast = self.anim and self.asking()
        self.root.after(FAST_FRAME_MS if fast else FRAME_MS, self.loop)

    def update_hover(self):
        if self.dragging or self.menu_open:
            return
        if self.asking():                          # stay open until a button is clicked
            self.expanded, self.leave_at = True, None
            return
        px, py = self.root.winfo_pointerxy()
        M = self.M * self.S
        x, y = self.root.winfo_rootx() + M, self.root.winfo_rooty() + M
        w, h = self.root.winfo_width() - 2 * M, self.root.winfo_height() - 2 * M
        if x <= px < x + w and y <= py < y + h:
            self.expanded, self.leave_at = True, None
        elif self.expanded:
            self.leave_at = self.leave_at or time.time()
            if time.time() - self.leave_at > COLLAPSE_DELAY:
                self.expanded, self.hot = False, None

    def render(self):
        self.cv.delete("all")
        self.buttons = []
        e = self.e
        if not self.expanded:
            self.draw_collapsed()
        elif e.mode == Mode.LUNCH and e.lunch_nudge:
            self.draw_nudge()
        else:
            self.draw_panel()

    def draw_collapsed(self):
        cv, k, S, e = self.cv, self.k, self.S, self.e
        v = self.view()
        M = self.M * S
        pw, ph = 148 * S, 38 * S
        self.place(pw + 2 * M, ph + 2 * M)
        nudging = e.mode == Mode.LUNCH and e.lunch_nudge
        t = time.time()
        if nudging and self.anim:                                   # soft breathing glow
            p = (1 - math.cos(2 * math.pi * t / 4.2)) / 2
            g = (2 + 5 * p) * S
            k.rrect(cv, M - g, M - g, M + pw + g, M + ph + g, ph / 2 + g,
                    fill=mix(INK, COL["lunch"], 0.2 + 0.4 * p))
        k.rrect(cv, M, M, M + pw, M + ph, ph / 2, fill=INK, outline=v["color"], width=BORDER_PX * S)
        k.ring(cv, M + 21 * S, M + ph / 2, 8 * S, 2.6 * S, v["frac"], v["color"])
        clock_font = k.num_bold(18) if v["clock"][0].isdigit() else k.ui_bold(14)
        cv.create_text(M + 40 * S, M + ph / 2, text=v["clock"], anchor="w", font=clock_font,
                       fill=v["clock_color"])
        if nudging:
            dy = hop_offset(t) * S if self.anim else 0
            cx, cy, r = M + pw - 18 * S, M + ph / 2 + dy, 4.5 * S
            cv.create_oval(cx - r, cy - r, cx + r, cy + r, fill=COL["lunch"], outline="")
        elif e.mode != Mode.STOPPED:                                # "Not started" needs the room
            test = self.ctx.test_mode
            cv.create_text(M + pw - 14 * S, M + ph / 2, text="TEST" if test else v["count"], anchor="e",
                           font=k.ui_bold(11) if test else k.F(k.num, 14),
                           fill=COL["test"] if test else MUTED)

    def draw_panel(self):
        cv, k, S, e, cfg = self.cv, self.k, self.S, self.e, self.e.cfg
        v = self.view()
        M, pad, pw = self.M * S, 18 * S, 330 * S
        x0, y0, inner = M, M, 330 * S - 36 * S
        # header: ring + status, big clock, sub line
        top = y0 + pad
        cx, cy = x0 + pad + 26 * S, top + 35 * S
        k.ring(cv, cx, cy, 22 * S, 4 * S, v["frac"], v["color"])
        if v["paused_icon"]:
            for dx in (-6, 2):
                k.rrect(cv, cx + dx * S, cy - 7 * S, cx + (dx + 4) * S, cy + 7 * S, 1.5 * S, fill=SUB)
        else:
            cv.create_text(cx, cy, text=v["ring_text"], font=k.num_bold(15), fill=TEXT)
        tx = x0 + pad + 66 * S
        cv.create_text(tx, top, text=v["label"], anchor="nw", font=k.ui_bold(13), fill=v["color"])
        big = k.F(k.num, 32) if v["clock"][0].isdigit() else k.ui_bold(26)
        cv.create_text(tx, top + 17 * S, text=v["clock"], anchor="nw", font=big, fill=v["clock_color"])
        cv.create_text(tx, top + 55 * S, text=k.fit(v["sub"], k.F(k.ui, 12), pw - 66 * S - 2 * pad),
                       anchor="nw", font=k.F(k.ui, 12), fill=MUTED)
        y = top + 84 * S
        d = cv.create_text(x0 + pad, y, text=e.detail, anchor="nw", width=inner,
                           font=k.F(k.ui, 12.5), fill=SUB)
        y = cv.bbox(d)[3] + 14 * S
        # today
        cv.create_line(x0 + pad, y, x0 + pw - pad, y, fill=LINE)
        y += 14 * S
        goal = max(1, cfg["daily_goal"])
        gap = 6 * S
        seg = min(22 * S, (inner - gap * (goal - 1)) / goal)
        for i in range(goal):
            if i < e.done:
                c = COL["focus"]
            elif i == e.done and e.mode in (Mode.WORK, Mode.PAUSED) and e.worked > 0:
                c = mix(TRACK, COL["focus"], 0.3)
            else:
                c = TRACK
            sx = x0 + pad + i * (seg + gap)
            k.rrect(cv, sx, y, sx + seg, y + 8 * S, 4 * S, fill=c)
        y += 20 * S
        sx = x0 + pad
        for n, word in ((e.done, "done"), (e.partial, "partial"), (max(0, goal - e.done), "breaks left")):
            f_n, f_w = k.ui_bold(12), k.F(k.ui, 12)
            cv.create_text(sx, y, text=str(n), anchor="nw", font=f_n, fill=TEXT)
            sx += f_n.measure(str(n)) + 4 * S
            cv.create_text(sx, y, text=word, anchor="nw", font=f_w, fill=MUTED)
            sx += f_w.measure(word) + 18 * S
        y += 30 * S
        # buttons
        paused, lunch = e.mode == Mode.PAUSED, e.mode == Mode.LUNCH
        if e.mode == Mode.STOPPED:
            specs = [("Start", Command.START, True, "primary", 1.0)]
        elif e.mode == Mode.BLOCK_DONE:
            specs = [("Take a break", Command.TAKE_BREAK, True, "primary", 1.0),
                     ("Skip break", Command.SKIP_BREAK, True, "normal", 1.0)]
        elif e.mode == Mode.LUNCH_TIME:
            specs = [("Start lunch", Command.LUNCH, True, "accent", 1.0),
                     ("In 15 min", Command.LUNCH_LATER, True, "normal", 1.0)]
        elif e.mode == Mode.GOAL_MET:
            specs = [("Keep going", Command.KEEP_GOING, True, "primary", 1.0),
                     ("Stop", Command.STOP, True, "normal", 1.0)]
        elif e.mode == Mode.WAIT:
            specs = [("Ready", Command.READY, True, "primary", 1.0),
                     (more_label(cfg["more_break_minutes"]), Command.MORE_BREAK, True, "normal", 1.0)]
        else:
            specs = [("Resume" if paused else "Pause", Command.TOGGLE_PAUSE, not lunch,
                      "primary" if paused else "normal", 1.0),
                     ("Skip break", Command.SKIP_BREAK, e.mode == Mode.BREAK, "normal", 1.3),
                     ("Reset", Command.RESET, e.worked > 0 and e.mode in (Mode.WORK, Mode.PAUSED), "normal", 1.0),
                     ("End lunch" if lunch else "Lunch", Command.LUNCH, True, "accent" if lunch else "normal", 1.0)]
        bh, icon_w = 34 * S, 34 * S
        unit = (inner - icon_w - gap * len(specs)) / sum(s[4] for s in specs)
        bx = x0 + pad
        for label, action, enabled, kind, wgt in specs:
            k.button(cv, self.buttons, bx, y, unit * wgt, bh, label, action, enabled, kind, self.hot)
            bx += unit * wgt + gap
        k.button(cv, self.buttons, bx, y, icon_w, bh, "more", "menu", True, "icon", self.hot)
        y += bh + pad
        bg = k.rrect(cv, x0, y0, x0 + pw, y, 16 * S, fill=INK, outline=v["color"], width=BORDER_PX * S)
        cv.tag_lower(bg)
        self.place(pw + 2 * M, y + M)

    def draw_nudge(self):
        cv, k, S, e = self.cv, self.k, self.S, self.e
        M, pad, pw = self.M * S, 18 * S, 300 * S
        x0, y0, inner = M, M, pw - 36 * S
        y = y0 + pad
        dy = hop_offset(time.time()) * 0.6 * S if self.anim else 0
        r = 5 * S
        cv.create_oval(x0 + pad, y + 5 * S - r + dy, x0 + pad + 2 * r, y + 5 * S + r + dy,
                       fill=COL["lunch"], outline="")
        cv.create_text(x0 + pad + 2 * r + 12 * S, y + 5 * S, text="Welcome back", anchor="w",
                       font=k.ui_bold(15), fill=TEXT)
        y += 26 * S
        msg = (f"Continue with your blocks? Lunch has run {int((time.time() - e.lunch_at) // 60)} min"
               + (", and your block picks up where it left off." if e.block_start else "."))
        d = cv.create_text(x0 + pad, y, text=msg, anchor="nw", width=inner, font=k.F(k.ui, 13), fill=SUB)
        y = cv.bbox(d)[3] + 14 * S
        bw = (inner - 8 * S) / 2
        k.button(cv, self.buttons, x0 + pad, y, bw, 36 * S, "Continue", Command.LUNCH, True, "accent", self.hot,
                 font=k.ui_bold(13))
        k.button(cv, self.buttons, x0 + pad + bw + 8 * S, y, bw, 36 * S, "Not yet", Command.LUNCH_SNOOZE, True,
                 "normal", self.hot, font=k.F(k.ui, 13))
        y += 36 * S + 12 * S
        snooze = duration(e.cfg["lunch_snooze_minutes"] * 60)
        cv.create_text(x0 + pad, y, text=f"Not yet asks again when you're back, or in {snooze}.", anchor="nw",
                       font=k.F(k.ui, 11.5), fill=MUTED)
        y += 16 * S + pad
        bg = k.rrect(cv, x0, y0, x0 + pw, y, 16 * S, fill=INK, outline=COL["lunch"], width=BORDER_PX * S)
        cv.tag_lower(bg)
        self.place(pw + 2 * M, y + M)

    # ----- mouse -----
    def on_press(self, ev):
        self.press = (ev.x_root, ev.y_root, self.right, self.top)
        self.dragging = False

    def on_drag(self, ev):
        if not self.press:
            return
        x0, y0, r0, t0 = self.press
        if abs(ev.x_root - x0) + abs(ev.y_root - y0) > 4 * self.S:
            self.dragging = True
        if self.dragging:
            self.right, self.top = r0 + ev.x_root - x0, t0 + ev.y_root - y0
            self.geom = ""
            self.render()

    def on_release(self, ev):
        if self.dragging:
            self.dragging = False
            try:
                self.ctx.paths.pill_position.write_text(json.dumps([int(self.right), int(self.top)]))
            except Exception:
                pass
        else:
            b = self.k.hit(self.buttons, ev.x, ev.y)
            if b and b["enabled"]:
                if b["action"] == "menu":
                    self.show_menu(ev.x_root, ev.y_root)
                else:
                    self.e.send(b["action"])
        self.press = None

    def show_menu(self, x, y):
        m, e, ctx = self.menu, self.e, self.ctx
        m.delete(0, "end")
        if e.mode == Mode.STOPPED:
            m.add_command(label="Start tracking", command=lambda: e.send(Command.START))
        else:
            m.add_command(label="Stop tracking", command=lambda: e.send(Command.STOP))
        m.add_command(label="Settings...", command=self.open_settings)
        fg = e.fg
        if fg:
            title = fg.title or fg.exe or "window"
            short = title if len(title) <= 40 else title[:39] + "..."
            verb = "Untag" if fg.hwnd in e.tags else "Tag as work"
            m.add_command(label=f"{verb}: {short}", command=lambda: e.send(Command.TAG_TOGGLE, fg.hwnd, title))
        m.add_separator()
        m.add_command(label="Heatmap...", command=lambda: self.open_settings("heatmap"))
        m.add_command(label="Open settings file", command=lambda: ctx.platform.open_file(ctx.paths.config))
        m.add_command(label="Reload settings", command=lambda: e.send(Command.RELOAD))
        if ctx.test_mode:
            tm = self.tk.Menu(m, tearoff=0)
            tm.add_command(label="Finish block now", command=lambda: e.send(Command.TEST_FINISH_BLOCK))
            tm.add_command(label="End break now", command=lambda: e.send(Command.TEST_END_BREAK))
            tm.add_command(label="Trigger lunch nudge (while on lunch)",
                           command=lambda: e.send(Command.TEST_LUNCH_NUDGE))
            tm.add_command(label="Clear test data and quit", command=self.clear_test_data)
            m.add_cascade(label="Test", menu=tm)
        m.add_separator()
        m.add_command(label="Quit", command=self.root.destroy)
        self.menu_open = True
        try:
            m.tk_popup(int(x), int(y))
        finally:
            m.grab_release()
            self.menu_open = False

    def clear_test_data(self):
        """Quit; the app deletes the test folder once the engine has closed the database."""
        self.clear_requested = True
        self.root.destroy()

    def open_settings(self, page: str | None = None):
        from focusblocks.ui.settings import Settings
        if self.settings and self.settings.alive:
            if page:
                self.settings.show_page(page)
            self.settings.top.deiconify()
            self.settings.top.lift()
            self.settings.top.focus_force()
        else:
            self.settings = Settings(self, page or "sources")
