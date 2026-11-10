"""Full-screen, skippable break overlay (break_mode = "overlay")."""

from __future__ import annotations

import time
from typing import Any

from focusblocks.core.commands import Command
from focusblocks.core.engine import Engine
from focusblocks.core.models import Mode
from focusblocks.ui.context import UiPlatform
from focusblocks.ui.fmt import mmss
from focusblocks.ui.kit import Button, Kit
from focusblocks.ui.theme import COL, INK, MUTED, SUB, TEXT


class BreakOverlay:
    def __init__(self, root: Any, kit: Kit, engine: Engine, platform: UiPlatform):
        self.root, self.k, self.S, self.e, self.platform = root, kit, kit.S, engine, platform
        self.win: Any = None
        self.cv: Any = None
        self.buttons: list[Button] = []
        self.hot: Button | None = None

    def sync(self) -> None:
        """Show or hide to match the engine, then redraw. Called from the pill's UI loop."""
        import tkinter as tk
        e = self.e
        want = e.mode == Mode.BREAK and e.overlay
        if want and self.win is None:
            ov = self.win = tk.Toplevel(self.root)
            ov.overrideredirect(True)
            ov.attributes("-topmost", True)
            try:
                ov.attributes("-alpha", 0.95)
            except tk.TclError:
                pass
            ov.geometry(f"{self.root.winfo_screenwidth()}x{self.root.winfo_screenheight()}+0+0")
            self.cv = tk.Canvas(ov, bg=INK, highlightthickness=0, bd=0)
            self.cv.pack(fill="both", expand=True)
            self.cv.bind("<ButtonRelease-1>", self.on_click)
            self.cv.bind("<Motion>", lambda ev: setattr(self, "hot", self.k.hit(self.buttons, ev.x, ev.y)))
            ov.after(200, lambda: self.platform.pin_everywhere(ov))
            self.root.lift()
        elif not want and self.win is not None:
            self.win.destroy()
            self.win = None
        if self.win is not None:
            self.draw()

    def draw(self) -> None:
        cv, k, S, e = self.cv, self.k, self.S, self.e
        W, H = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        cx, cy = W / 2, H / 2
        cv.delete("all")
        self.buttons = []
        brk = max(1.0, e.break_len)
        left = e.break_end - time.time()
        k.ring(cv, cx, cy - 30 * S, 150 * S, 6 * S, max(0.0, min(1.0, left / brk)), COL["break"])
        cv.create_text(cx, cy - 92 * S, text="Break", font=k.ui_bold(22), fill=COL["break"])
        cv.create_text(cx, cy - 30 * S, text=mmss(left), font=k.F(k.num_light, 96), fill=TEXT)
        cv.create_text(cx, cy + 36 * S, text=f"Block {e.done} of {e.cfg['daily_goal']} done",
                       font=k.F(k.ui, 15), fill=MUTED)
        cv.create_text(cx, cy + 160 * S, text="Stand up, look away from the screen, stretch.",
                       font=k.F(k.ui, 17), fill=SUB)
        f = k.F(k.ui, 15)
        bw, bh, g = 150 * S, 44 * S, 12 * S
        x = cx - bw - g / 2
        for label, action in (("Skip break", Command.SKIP_BREAK), ("Start lunch", Command.LUNCH)):
            k.button(cv, self.buttons, x, cy + 200 * S, bw, bh, label, action, True, "normal",
                     self.hot, font=f, radius=11)
            x += bw + g

    def on_click(self, ev: Any) -> None:
        b = self.k.hit(self.buttons, ev.x, ev.y)
        if b:
            self.e.send(b["action"])
