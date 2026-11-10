"""Settings window: pick work sources, set block and break lengths, the daily goal and lunch; see the heatmap."""

from __future__ import annotations

import datetime as dt
import logging
from typing import TYPE_CHECKING, Any

from focusblocks.core.commands import Command
from focusblocks.core.models import app_display_name
from focusblocks.reports.heatmap import heatmap_grid
from focusblocks.ui.fmt import plural
from focusblocks.ui.kit import Button
from focusblocks.ui.steppers import (
    DEFAULT_LUNCH_MINUTES_OF_DAY,
    LUNCH_FIELDS,
    TIME_FIELDS,
    clock_minutes,
    clock_text,
    stepped,
)
from focusblocks.ui.theme import (
    BADGES,
    HEAT,
    W_BG,
    W_CHECK_OFF,
    W_FAINT,
    W_GREEN,
    W_INK,
    W_LINE,
    W_NAV,
    W_SEL_ROW,
    W_SUB,
)

if TYPE_CHECKING:
    from focusblocks.ui.pill import Pill

log = logging.getLogger(__name__)


class Settings:
    W, H, NAV = 1000, 700, 210
    PAGES = (("sources", "Work sources"), ("blocks", "Blocks and breaks"), ("lunch", "Lunch and pause"),
             ("heatmap", "Heatmap"))

    def __init__(self, pill: Pill, page: str = "sources"):
        tk = pill.tk
        self.p, self.e, self.k, self.S, self.ctx = pill, pill.e, pill.k, pill.S, pill.ctx
        S = self.S
        self.top = top = tk.Toplevel(pill.root)
        top.title("Focus Blocks settings")
        top.geometry(f"{int(self.W * S)}x{int(self.H * S)}")
        top.resizable(False, False)
        top.configure(bg=W_BG)
        top.protocol("WM_DELETE_WINDOW", self.close)
        self.cv = tk.Canvas(top, bg=W_BG, highlightthickness=0, bd=0)
        self.cv.pack(fill="both", expand=True)
        self.alive, self.page, self.tab = True, page, "desktops"
        self.history: dict[str, tuple[int, float]] = {}
        self.buttons: list[Button] = []
        self.hot: Button | None = None
        self.scroll, self.content_h = 0.0, 0.0
        cfg = self.e.cfg
        self.sel_desks = {d.lower() for d in cfg["work_desktops"]}
        self.sel_apps = {a.lower() for a in cfg["work_apps"]}
        self.times = {f.key: cfg[f.key] for f in TIME_FIELDS}   # edited on the "Blocks and breaks" page
        self.lunch_on = bool(cfg["lunch_time"])                 # edited on the "Lunch and pause" page
        self.lunch = self.saved_lunch()
        cw = (self.W - self.NAV - 64) * S
        self.card_w = (cw - 2 * 18 * S) / 3
        self.thumb = (int(self.card_w - 20 * S), int((self.card_w - 20 * S) * 10 / 16))
        self.load()
        self.cv.bind("<ButtonRelease-1>", self.on_click)
        self.cv.bind("<Motion>", self.on_motion)
        self.cv.bind("<MouseWheel>", self.on_wheel)
        self.show_page(page)

    def load(self):
        platform = self.ctx.platform
        self.desktops = platform.list_desktops()
        have = {d["name"].lower() for d in self.desktops}
        for n in self.e.cfg["work_desktops"]:
            if n.lower() not in have:
                self.desktops.append(dict(name=n, number=None, apps=[], current=False, missing=True))
        running = platform.running_apps()
        self.apps = [dict(exe=x, title=t, running=True) for x, t in sorted(running.items(), key=lambda i: i[0].lower())]
        have = {a["exe"].lower() for a in self.apps}
        self.apps += [dict(exe=a, title="", running=False) for a in self.e.cfg["work_apps"] if a.lower() not in have]
        self.images: dict[str, Any] = {}
        try:
            from PIL import Image, ImageOps, ImageTk
            for d in self.desktops:
                p = platform.snapshot_path(d["name"])
                if p.exists():
                    img = ImageOps.fit(Image.open(p), self.thumb)
                    self.images[d["name"]] = ImageTk.PhotoImage(img, master=self.top)
                    d["snap"] = dt.datetime.fromtimestamp(p.stat().st_mtime)
        except Exception as ex:
            log.warning("previews unavailable: %s", ex)

    def saved_lunch(self) -> dict[str, float]:
        """The lunch fields as running now; lunch_time as minutes after midnight (12:30 if none is set)."""
        cfg = self.e.cfg
        return {"lunch_time": clock_minutes(cfg["lunch_time"]) or DEFAULT_LUNCH_MINUTES_OF_DAY,
                "lunch_minutes": cfg["lunch_minutes"]}

    def show_page(self, page: str) -> None:
        self.page, self.scroll = page, 0.0
        if page == "heatmap":
            try:
                self.history = self.ctx.load_history()
            except Exception:
                log.exception("could not read the block history")
                self.history = {}
        self.render()

    def close(self):
        self.alive = False
        self.top.destroy()

    def save(self):
        store = self.ctx.config_store
        cfg = store.load()
        cfg["work_desktops"] = [d["name"] for d in self.desktops if d["name"].lower() in self.sel_desks]
        cfg["work_apps"] = [a["exe"] for a in self.apps if a["exe"].lower() in self.sel_apps]
        cfg.update(self.times)
        cfg["lunch_time"] = clock_text(self.lunch["lunch_time"]) if self.lunch_on else ""
        cfg["lunch_minutes"] = self.lunch["lunch_minutes"]
        store.save(cfg)
        self.e.send(Command.RELOAD)
        self.close()

    # ----- events -----
    def visible(self, b, x, y):
        """Content buttons scroll under the header/footer; only the visible part is clickable."""
        in_content = x > self.NAV * self.S and 150 * self.S <= y <= (self.H - 68) * self.S
        return b.get("content", False) == in_content

    def on_motion(self, ev):
        b = self.k.hit([b for b in self.buttons if self.visible(b, ev.x, ev.y)], ev.x, ev.y)
        if (b and b["id"]) != (self.hot and self.hot["id"]):
            self.hot = b
            self.render()

    def on_wheel(self, ev):
        view = (self.H - 68 - 150) * self.S
        self.scroll = max(0.0, min(self.scroll - ev.delta / 120 * 50 * self.S, max(0.0, self.content_h - view)))
        self.render()

    def on_click(self, ev):
        b = self.k.hit([b for b in self.buttons if self.visible(b, ev.x, ev.y)], ev.x, ev.y)
        if not b or not b["enabled"]:
            return
        a = b["action"]
        if a == "page":
            self.show_page(b["page"])
            return
        elif a == "tab":
            self.tab, self.scroll = b["tab"], 0.0
        elif a == "desk":
            self.sel_desks ^= {b["key"]}
        elif a == "app":
            self.sel_apps ^= {b["key"]}
        elif isinstance(a, tuple) and a[0] == "step":   # ("step", key, direction): unique per button for hover
            f = b["field"]
            values = self.times if f.key in self.times else self.lunch
            values[f.key] = stepped(f, values[f.key], b["direction"])
        elif a == "lunch_on":
            self.lunch_on = not self.lunch_on
        elif a == "untag":
            self.e.send(Command.TAG_TOGGLE, b["key"], self.e.tags.get(b["key"], ""))
            self.top.after(300, self.render)
        elif a == "cancel":
            self.close()
            return
        elif a == "save":
            self.save()
            return
        self.render()

    # ----- drawing -----
    def checkbox(self, cv, x, y, on):
        S, k = self.S, self.k
        if on:
            k.rrect(cv, x, y, x + 22 * S, y + 22 * S, 6 * S, fill=W_GREEN)
            cv.create_line(x + 6 * S, y + 11.5 * S, x + 9.5 * S, y + 15 * S, x + 16.5 * S, y + 7.5 * S,
                           fill="#ffffff", width=2.6 * S, capstyle="round", joinstyle="round")
        else:
            k.rrect(cv, x, y, x + 22 * S, y + 22 * S, 6 * S, fill="#ffffff", outline=W_CHECK_OFF, width=1.5 * S)

    def render(self):
        if not self.alive:
            return
        cv, S = self.cv, self.S
        cv.delete("all")
        self.buttons = []
        W, H, NAV = self.W * S, self.H * S, self.NAV * S
        x0, cw = NAV + 32 * S, W - NAV - 64 * S
        head_h, foot_y = 150 * S, H - 68 * S
        start = head_h + 22 * S
        y = start - self.scroll
        if self.page == "sources":
            draw_tab = {"desktops": self.draw_desktops, "apps": self.draw_apps, "windows": self.draw_windows}[self.tab]
            y = draw_tab(x0, y, cw)
        elif self.page == "blocks":
            y = self.draw_times(x0, y, cw)
        elif self.page == "lunch":
            y = self.draw_lunch(x0, y, cw)
        elif self.page == "heatmap":
            y = self.draw_heatmap(x0, y, cw)
        self.content_h = y + self.scroll - start + 22 * S

        # header (covers scrolled content)
        cv.create_rectangle(NAV, 0, W, head_h, fill=W_BG, outline="")
        if self.page == "sources":
            self.draw_sources_header(x0)
        elif self.page == "blocks":
            self.draw_times_header(x0)
        elif self.page == "lunch":
            self.draw_lunch_header(x0)
        elif self.page == "heatmap":
            self.draw_heatmap_header(x0)
        self.draw_footer(x0, W, H, NAV, foot_y)
        self.draw_nav(H, NAV)

    def draw_sources_header(self, x0):
        cv, k, S = self.cv, self.k, self.S
        cv.create_text(x0, 30 * S, text="What counts as work", anchor="nw", font=k.ui_bold(22), fill=W_INK)
        cv.create_text(x0, 64 * S, text="Pick any mix. Time counts while one of these is in front of you.",
                       anchor="nw", font=k.F(k.ui, 13.5), fill=W_SUB)
        counts = {"desktops": len(self.sel_desks & {d["name"].lower() for d in self.desktops}),
                  "apps": len(self.sel_apps & {a["exe"].lower() for a in self.apps}),
                  "windows": len(self.e.tags)}
        tabs = (("desktops", "Desktops"), ("apps", "Apps"), ("windows", "Windows"))
        f_on, f_off, f_n = k.ui_bold(13), k.F(k.ui, 13), k.F(k.num, 13)
        widths = [f_on.measure(lbl) + f_n.measure(str(counts[t])) + 34 * S for t, lbl in tabs]
        ty = 100 * S
        k.rrect(cv, x0, ty, x0 + sum(widths) + 8 * S + 4 * S * (len(tabs) - 1), ty + 40 * S, 10 * S, fill="#eceef1")
        tx = x0 + 4 * S
        for (t, lbl), w in zip(tabs, widths, strict=True):
            on = self.tab == t
            if on:
                k.rrect(cv, tx, ty + 4 * S, tx + w, ty + 36 * S, 7 * S, fill="#ffffff", outline="#e3e6ea")
            f = f_on if on else f_off
            cv.create_text(tx + 14 * S, ty + 20 * S, text=lbl, anchor="w", font=f, fill=W_INK if on else "#3b434d")
            cv.create_text(tx + 14 * S + f.measure(lbl) + 6 * S, ty + 20 * S, text=str(counts[t]), anchor="w",
                           font=f_n, fill="#5d6670")
            self.buttons.append(dict(x1=tx, y1=ty + 4 * S, x2=tx + w, y2=ty + 36 * S, action="tab", tab=t,
                                     enabled=True, id=("tab", t)))
            tx += w + 4 * S

    def draw_times_header(self, x0):
        cv, k, S = self.cv, self.k, self.S
        cv.create_text(x0, 30 * S, text="Blocks and breaks", anchor="nw", font=k.ui_bold(22), fill=W_INK)
        cv.create_text(x0, 64 * S, text="Set how long you focus, how long you rest, and how many blocks make a day.",
                       anchor="nw", font=k.F(k.ui, 13.5), fill=W_SUB)

    def draw_step_rows(self, x0, y, cw, fields, values, saved, enabled=True):
        """One row per setting: label, range hint, then - value +. Rows that differ from what's running are tinted."""
        cv, k, S = self.cv, self.k, self.S
        f_label, f_value, f_unit, f_btn = k.ui_bold(14), k.F(k.num, 20), k.F(k.ui, 13), k.ui_bold(16)
        row_h, btn, value_w = 64 * S, 38 * S, 72 * S
        for f in fields:
            value = values[f.key]
            changed = enabled and value != saved[f.key]
            k.rrect(cv, x0, y, x0 + cw, y + row_h, 12 * S, fill=W_SEL_ROW if changed else "#ffffff",
                    outline=W_LINE)
            cy = y + row_h / 2
            ink = W_INK if enabled else W_FAINT
            cv.create_text(x0 + 20 * S, cy, text=f.label, anchor="w", font=f_label, fill=ink)
            hint = f"{f.show(f.lo)}-{f.show(f.hi)} {f.unit}".rstrip() + (f", was {f.show(saved[f.key])}"
                                                                          if changed else "")
            cv.create_text(x0 + 200 * S, cy, text=hint, anchor="w", font=k.F(k.ui, 12), fill=W_FAINT)
            bx = x0 + cw - 20 * S - btn - value_w - btn - 60 * S
            k.button(cv, self.buttons, bx, cy - btn / 2, btn, btn, "−", ("step", f.key, -1),
                     enabled and value > f.lo, "outline", self.hot, font=f_btn, content=True, field=f, direction=-1)
            cv.create_text(bx + btn + value_w / 2, cy, text=f.show(value), font=f_value, fill=ink)
            k.button(cv, self.buttons, bx + btn + value_w, cy - btn / 2, btn, btn, "+", ("step", f.key, +1),
                     enabled and value < f.hi, "outline", self.hot, font=f_btn, content=True, field=f, direction=+1)
            cv.create_text(bx + 2 * btn + value_w + 12 * S, cy, text=f.unit, anchor="w", font=f_unit, fill=W_SUB)
            y += row_h + 12 * S
        return y

    def draw_times(self, x0, y, cw):
        cv, k, S = self.cv, self.k, self.S
        cfg = self.e.cfg
        y = self.draw_step_rows(x0, y, cw, TIME_FIELDS, self.times, cfg)
        note = f"Break style: {cfg['break_mode']}. Other settings are in the settings file."
        cv.create_text(x0, y + 6 * S, text=note, anchor="nw", font=k.F(k.ui, 12.5), fill=W_SUB)
        return y + 30 * S

    def draw_lunch_header(self, x0):
        cv, k, S = self.cv, self.k, self.S
        cv.create_text(x0, 30 * S, text="Lunch and pause", anchor="nw", font=k.ui_bold(22), fill=W_INK)
        cv.create_text(x0, 64 * S, text="Get a reminder at lunch time. Lunch on the pill works any time, set or not.",
                       anchor="nw", font=k.F(k.ui, 13.5), fill=W_SUB)

    def draw_lunch(self, x0, y, cw):
        cv, k, S = self.cv, self.k, self.S
        cfg = self.e.cfg
        row_h = 64 * S
        changed = self.lunch_on != bool(cfg["lunch_time"])
        k.rrect(cv, x0, y, x0 + cw, y + row_h, 12 * S, fill=W_SEL_ROW if changed else "#ffffff", outline=W_LINE)
        self.checkbox(cv, x0 + 20 * S, y + row_h / 2 - 11 * S, self.lunch_on)
        cv.create_text(x0 + 56 * S, y + row_h / 2, text="Remind me at lunch time", anchor="w", font=k.ui_bold(14),
                       fill=W_INK)
        cv.create_text(x0 + 300 * S, y + row_h / 2, text="If a block is running, it asks when the block ends.",
                       anchor="w", font=k.F(k.ui, 12), fill=W_FAINT)
        self.buttons.append(dict(x1=x0, y1=y, x2=x0 + cw, y2=y + row_h, action="lunch_on", enabled=True,
                                 id=("lunch_on",), content=True))
        y += row_h + 12 * S
        y = self.draw_step_rows(x0, y, cw, LUNCH_FIELDS, self.lunch, self.saved_lunch(), enabled=self.lunch_on)
        notes = [f"Back from lunch: the first mouse or key after {cfg['lunch_away_minutes']:g} min away asks "
                 "\"Welcome back\". Continue picks up the block you were in.",
                 f"Pause resumes: {cfg['pause_resume']}. Unfinished block resets after {cfg['abandon_minutes']:g} min "
                 "away. These are in the settings file."]
        for note in notes:
            d = cv.create_text(x0, y + 6 * S, text=note, anchor="nw", width=cw, font=k.F(k.ui, 12.5), fill=W_SUB)
            y = cv.bbox(d)[3] + 4 * S
        return y + 30 * S

    def draw_heatmap_header(self, x0):
        cv, k, S = self.cv, self.k, self.S
        cfg = self.e.cfg
        cv.create_text(x0, 30 * S, text="Heatmap", anchor="nw", font=k.ui_bold(22), fill=W_INK)
        cv.create_text(x0, 64 * S, anchor="nw", font=k.F(k.ui, 13.5), fill=W_SUB,
                       text=f"Your focus blocks over the last year. Daily goal: {cfg['daily_goal']} blocks.")

    def draw_heatmap(self, x0, y, cw):
        """Stats, then a year of days as week columns (Sunday on top). Hover a day for its numbers."""
        cv, k, S = self.cv, self.k, self.S
        goal = self.e.cfg["daily_goal"]
        g = heatmap_grid(self.history, goal, dt.date.today())
        f_big, f_small = k.ui_bold(26), k.F(k.ui, 12.5)
        sx = x0
        for big, small in ((f"{g.today}/{goal}", "today"), (str(g.streaks.current), "day streak"),
                           (str(g.streaks.best), "best streak"), (str(g.total), "blocks total")):
            cv.create_text(sx, y, text=big, anchor="nw", font=f_big, fill=W_INK)
            cv.create_text(sx, y + 36 * S, text=small, anchor="nw", font=f_small, fill=W_FAINT)
            sx += max(f_big.measure(big), f_small.measure(small)) + 48 * S
        y += 78 * S

        card_top, pad, label_w, gap = y, 16 * S, 32 * S, 2 * S
        cell = min(14 * S, (cw - 2 * pad - label_w - gap * (g.weeks - 1)) / g.weeks)
        step = cell + gap
        gx, gy = x0 + pad + label_w, card_top + pad + 20 * S
        f_axis = k.F(k.ui, 11)
        for col, name in g.months:
            cv.create_text(gx + col * step, card_top + pad, text=name, anchor="nw", font=f_axis, fill=W_FAINT)
        for row, name in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
            cv.create_text(x0 + pad, gy + row * step + cell / 2, text=name, anchor="w", font=f_axis, fill=W_FAINT)
        hot = self.hot["id"][1] if self.hot and self.hot["id"][0] == "cell" else None
        tip = "Hover a day to see its blocks."
        for c in g.cells:
            cx, cy, iso = gx + c.col * step, gy + c.row * step, c.day.isoformat()
            if iso == hot:
                tip = c.tip
            cv.create_rectangle(cx, cy, cx + cell, cy + cell, fill=HEAT[c.level],
                                outline=W_INK if iso == hot else "", width=1.5 * S)
            self.buttons.append(dict(x1=cx, y1=cy, x2=cx + step, y2=cy + step, action="cell", enabled=False,
                                     content=True, id=("cell", iso)))
        y = gy + 7 * step + 12 * S

        # hovered day on the left, legend on the right
        cv.create_text(x0 + pad, y, text=tip, anchor="nw", font=k.F(k.ui, 12.5), fill=W_INK if hot else W_FAINT)
        lx = x0 + cw - pad - f_axis.measure("Goal met")
        cv.create_text(lx, y + 1 * S, text="Goal met", anchor="nw", font=f_axis, fill=W_FAINT)
        lx -= 6 * S
        for color in reversed(HEAT):
            lx -= 12 * S
            cv.create_rectangle(lx, y + 2 * S, lx + 12 * S, y + 14 * S, fill=color, outline="")
            lx -= 3 * S
        cv.create_text(lx - 3 * S, y + 1 * S, text="Less", anchor="ne", font=f_axis, fill=W_FAINT)
        y += 24 * S + pad
        card = k.rrect(cv, x0, card_top, x0 + cw, y, 12 * S, fill="#ffffff", outline=W_LINE)
        cv.tag_lower(card)
        return y + 10 * S

    def draw_footer(self, x0, W, H, NAV, foot_y):
        cv, k, S = self.cv, self.k, self.S
        cv.create_rectangle(NAV, foot_y, W, H, fill=W_BG, outline="")
        cv.create_line(NAV, foot_y, W, foot_y, fill=W_LINE)
        nd = len(self.sel_desks & {d["name"].lower() for d in self.desktops})
        na = len(self.sel_apps & {a["exe"].lower() for a in self.apps})
        nt = len(self.e.tags)
        if self.page == "blocks":
            summary = "Saved changes apply right away, including to the block or break in progress."
        elif self.page == "lunch":
            summary = "Saved changes apply right away."
        elif self.page == "heatmap":
            summary = "Your history is stored only on this PC."
        elif nd + na + nt == 0:
            summary = "Counting any window (nothing picked)"
        else:
            summary = f"Counting {plural(nd, 'desktop')}, {plural(na, 'app')} and {plural(nt, 'tagged window')}"
        cv.create_text(x0, foot_y + 34 * S, text=summary, anchor="w", font=k.F(k.ui, 13), fill="#3b434d")
        fb, fbb = k.F(k.ui, 13), k.ui_bold(13)
        sw, cw_ = fbb.measure("Save") + 40 * S, fb.measure("Cancel") + 36 * S
        k.button(cv, self.buttons, W - 32 * S - sw, foot_y + 16 * S, sw, 36 * S, "Save", "save", True, "dark",
                 self.hot, font=fbb)
        k.button(cv, self.buttons, W - 32 * S - sw - 10 * S - cw_, foot_y + 16 * S, cw_, 36 * S, "Cancel", "cancel",
                 True, "outline", self.hot, font=fb)

    def draw_nav(self, H, NAV):
        cv, k, S = self.cv, self.k, self.S
        cv.create_rectangle(0, 0, NAV, H, fill=W_NAV, outline="")
        cv.create_line(NAV, 0, NAV, H, fill=W_LINE)
        rcx, rcy = 22 * S + 10 * S, 34 * S
        cv.create_oval(rcx - 8 * S, rcy - 8 * S, rcx + 8 * S, rcy + 8 * S, outline="#d5d9de", width=2.6 * S)
        cv.create_arc(rcx - 8 * S, rcy - 8 * S, rcx + 8 * S, rcy + 8 * S, start=90, extent=-216, style="arc",
                      outline=W_GREEN, width=2.6 * S)
        cv.create_text(rcx + 18 * S, rcy, text="Focus Blocks", anchor="w", font=k.ui_bold(14), fill=W_INK)
        ny = 70 * S
        for key, label in self.PAGES:
            on = self.page == key
            hot = self.hot and self.hot["id"] == ("page", key)
            if on or hot:
                k.rrect(cv, 12 * S, ny, NAV - 12 * S, ny + 36 * S, 8 * S, fill="#e2e5e9" if on else "#e8eaed")
            cv.create_text(24 * S, ny + 18 * S, text=label, anchor="w",
                           font=k.ui_bold(13.5) if on else k.F(k.ui, 13.5), fill=W_INK if on else "#3b434d")
            self.buttons.append(dict(x1=12 * S, y1=ny, x2=NAV - 12 * S, y2=ny + 36 * S, action="page", page=key,
                                     enabled=True, id=("page", key)))
            ny += 38 * S

    def draw_desktops(self, x0, y, cw):
        cv, k, S = self.cv, self.k, self.S
        if not self.desktops:
            cv.create_text(x0, y, text="Couldn't read your virtual desktops. Is pyvda installed?", anchor="nw",
                           font=k.F(k.ui, 13.5), fill=W_SUB)
            return y + 30 * S
        tw, th = self.thumb
        card_w, card_h, gap = self.card_w, th + 92 * S, 18 * S
        f_name, f_sub, f_small = k.ui_bold(14), k.F(k.ui, 12), k.F(k.ui, 11.5)
        today = dt.date.today()
        for i, d in enumerate(self.desktops):
            col, row = i % 3, i // 3
            cx, cy = x0 + col * (card_w + gap), y + row * (card_h + gap)
            key = d["name"].lower()
            on = key in self.sel_desks
            hot = self.hot and self.hot["id"] == ("desk", key)
            k.rrect(cv, cx, cy, cx + card_w, cy + card_h, 12 * S, fill="#ffffff",
                    outline=W_GREEN if on else ("#c9ced4" if hot else W_LINE), width=2 * S)
            ix, iy = cx + 10 * S, cy + 10 * S
            if d["name"] in self.images:
                cv.create_image(ix, iy, image=self.images[d["name"]], anchor="nw")
            else:
                k.rrect(cv, ix, iy, ix + tw, iy + th, 8 * S, fill="#2c3540")
                cv.create_text(ix + tw / 2, iy + th / 2, text="Visit this desktop once\nto see a preview",
                               justify="center", font=f_sub, fill="#c4cad1")
            ty = iy + th + 12 * S
            cv.create_text(cx + 12 * S, ty, text=k.fit(d["name"], f_name, card_w - 60 * S), anchor="nw",
                           font=f_name, fill=W_INK)
            apps = ", ".join(app_display_name(a) for a in d["apps"][:4]) or "No windows"
            cv.create_text(cx + 12 * S, ty + 22 * S, text=k.fit(apps, f_sub, card_w - 24 * S), anchor="nw",
                           font=f_sub, fill="#5d6670")
            if d.get("missing"):
                seen = "Not found. Renamed or removed?"
            elif d["current"]:
                seen = "You are here"
            elif d.get("snap"):
                sd = d["snap"]
                seen = (f"Snapshot {sd:%H:%M}" if sd.date() == today else
                        "Snapshot yesterday" if sd.date() == today - dt.timedelta(days=1) else f"Snapshot {sd:%b %d}")
            else:
                seen = "No snapshot yet"
            cv.create_text(cx + 12 * S, ty + 42 * S, text=seen, anchor="nw", font=f_small, fill=W_FAINT)
            self.checkbox(cv, cx + card_w - 34 * S, ty, on)
            self.buttons.append(dict(x1=cx, y1=cy, x2=cx + card_w, y2=cy + card_h, action="desk", key=key,
                                     enabled=True, content=True, id=("desk", key)))
        rows = (len(self.desktops) + 2) // 3
        y += rows * (card_h + gap)
        cv.create_text(x0, y, anchor="nw", width=cw, font=k.F(k.ui, 12.5), fill="#5d6670",
                       text="Previews are snapshots from the last time you used each desktop, saved only on this PC. "
                            "Rename desktops in Task View (Win + Tab).")
        return y + 40 * S

    def draw_apps(self, x0, y, cw):
        cv, k, S = self.cv, self.k, self.S
        cv.create_text(x0, y, text="Apps with windows open now. Pick one and every window of it counts.",
                       anchor="nw", font=k.F(k.ui, 13), fill=W_SUB)
        y += 30 * S
        top = y
        f_name, f_sub = k.ui_bold(13.5), k.F(k.ui, 12)
        rh = 56 * S
        for a in self.apps:
            key = a["exe"].lower()
            on = key in self.sel_apps
            hot = self.hot and self.hot["id"] == ("app", key)
            row_fill = W_SEL_ROW if on else ("#f7f8f9" if hot else "#ffffff")
            cv.create_rectangle(x0 + 1, y, x0 + cw - 1, y + rh, fill=row_fill, outline="")
            cv.create_line(x0, y + rh, x0 + cw, y + rh, fill="#eceef1")
            name = app_display_name(a["exe"])
            color = BADGES[sum(map(ord, key)) % len(BADGES)]
            k.rrect(cv, x0 + 16 * S, y + 13 * S, x0 + 46 * S, y + 43 * S, 8 * S, fill=color)
            cv.create_text(x0 + 31 * S, y + 28 * S, text=name[:1].upper(), font=k.ui_bold(13), fill="#ffffff")
            cv.create_text(x0 + 60 * S, y + 10 * S, text=name, anchor="nw", font=f_name, fill=W_INK)
            sub = f"{a['exe']}   {a['title']}" if a["running"] else f"{a['exe']}   not running"
            cv.create_text(x0 + 60 * S, y + 30 * S, text=k.fit(sub, f_sub, cw - 120 * S), anchor="nw",
                           font=f_sub, fill="#5d6670")
            self.checkbox(cv, x0 + cw - 38 * S, y + 17 * S, on)
            self.buttons.append(dict(x1=x0, y1=y, x2=x0 + cw, y2=y + rh, action="app", key=key, enabled=True,
                                     content=True, id=("app", key)))
            y += rh
        k.rrect(cv, x0, top, x0 + cw, y, 10 * S, fill="", outline=W_LINE)
        return y + 20 * S

    def draw_windows(self, x0, y, cw):
        cv, k, S = self.cv, self.k, self.S
        hotkey = self.e.cfg["tag_hotkey"].replace("+", " + ").title()
        cv.create_text(x0, y, anchor="nw", width=cw, font=k.F(k.ui, 13), fill=W_SUB,
                       text=f"Tagged windows count with every tab inside them. "
                            f"Press {hotkey} on any window to tag or untag it.")
        y += 40 * S
        if not self.e.tags:
            cv.create_text(x0, y, text="No tagged windows yet.", anchor="nw", font=k.F(k.ui, 13.5), fill=W_INK)
            return y + 30 * S
        f_name, f_sub, fb = k.ui_bold(13.5), k.F(k.ui, 12), k.F(k.ui, 12.5)
        for hwnd, title in list(self.e.tags.items()):
            k.rrect(cv, x0, y, x0 + cw, y + 60 * S, 10 * S, fill="#ffffff", outline=W_LINE)
            cv.create_text(x0 + 16 * S, y + 12 * S, text=k.fit(title, f_name, cw - 140 * S), anchor="nw",
                           font=f_name, fill=W_INK)
            cv.create_text(x0 + 16 * S, y + 33 * S, text="Clears when the window closes.", anchor="nw",
                           font=f_sub, fill="#5d6670")
            bw = fb.measure("Untag") + 28 * S
            k.button(cv, self.buttons, x0 + cw - 16 * S - bw, y + 14 * S, bw, 32 * S, "Untag", "untag", True,
                     "outline", self.hot, font=fb, radius=8, key=hwnd, content=True)
            y += 70 * S
        return y + 10 * S
