"""Fonts and canvas drawing helpers shared by the pill, overlay and settings window."""

from __future__ import annotations

from typing import Any

from focusblocks.ui.theme import BTN, BTN_HOT, BTN_OFF, COL, INK, OFF_TEXT, SUB, TEXT, TRACK, W_INK, W_LINE

Button = dict[str, Any]   # hit-test record: x1, y1, x2, y2, action, enabled, id, plus extras


class Kit:
    def __init__(self, root: Any):
        from tkinter import font as tkfont
        self.S = S = root.winfo_fpixels("1i") / 96
        fams = set(tkfont.families(root))

        def pick(*names: str) -> str:
            return next((n for n in names if n in fams), names[-1])

        self.num = pick("Bahnschrift", "Segoe UI")
        self.num_sb = pick("Bahnschrift SemiBold", self.num)
        self.num_light = pick("Bahnschrift Light", self.num)
        self.ui = pick("Segoe UI Variable Text", "Segoe UI")
        self.ui_sb = pick("Segoe UI Variable Text Semibold", "Segoe UI Semibold", self.ui)
        cache: dict[tuple[str, float, bool], Any] = {}

        def F(fam: str, px: float, bold: bool = False) -> Any:
            key = (fam, px, bold)
            if key not in cache:
                cache[key] = tkfont.Font(root, family=fam, size=-max(1, round(px * S)),
                                         weight="bold" if bold else "normal")
            return cache[key]

        self.F = F

    def num_bold(self, px: float) -> Any:
        return self.F(self.num_sb, px, self.num_sb == self.num)

    def ui_bold(self, px: float) -> Any:
        return self.F(self.ui_sb, px, self.ui_sb == self.ui)

    _n = 0

    @classmethod
    def rrect(cls, cv, x1, y1, x2, y2, r, fill="", outline="", width=1):
        """Rounded rectangle with true circular corners (r = half the height gives a pill).
        Built from ovals and rectangles, so the ends are real semicircles.
        Returns a tag covering all its parts (usable with tag_lower / delete)."""
        cls._n += 1
        tag = f"rr{cls._n}"
        r = max(0.0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
        if fill and outline:
            cls._solid(cv, x1, y1, x2, y2, r, outline, tag)
            cls._solid(cv, x1 + width, y1 + width, x2 - width, y2 - width, max(0.0, r - width), fill, tag)
        elif fill:
            cls._solid(cv, x1, y1, x2, y2, r, fill, tag)
        elif outline:
            cls._ring(cv, x1, y1, x2, y2, r, outline, width, tag)
        return tag

    @staticmethod
    def _solid(cv, x1, y1, x2, y2, r, color, tag):
        if r < 1:
            cv.create_rectangle(x1, y1, x2, y2, fill=color, outline="", tags=tag)
            return
        d = 2 * r
        for ox, oy in ((x1, y1), (x2 - d, y1), (x1, y2 - d), (x2 - d, y2 - d)):
            cv.create_oval(ox, oy, ox + d, oy + d, fill=color, outline="", tags=tag)
        cv.create_rectangle(x1 + r, y1, x2 - r, y2, fill=color, outline="", tags=tag)
        cv.create_rectangle(x1, y1 + r, x2, y2 - r, fill=color, outline="", tags=tag)

    @staticmethod
    def _ring(cv, x1, y1, x2, y2, r, color, width, tag):
        d = 2 * r
        for bx, by, start in ((x1, y1, 90), (x2 - d, y1, 0), (x2 - d, y2 - d, 270), (x1, y2 - d, 180)):
            cv.create_arc(bx, by, bx + d, by + d, start=start, extent=90, style="arc",
                          outline=color, width=width, tags=tag)
        for a in ((x1 + r, y1, x2 - r, y1), (x2, y1 + r, x2, y2 - r),
                  (x1 + r, y2, x2 - r, y2), (x1, y1 + r, x1, y2 - r)):
            cv.create_line(*a, fill=color, width=width, tags=tag)

    @staticmethod
    def fit(text, font, width):
        if font.measure(text) <= width:
            return text
        while text and font.measure(text + "...") > width:
            text = text[:-1]
        return text + "..."

    @staticmethod
    def ring(cv, cx, cy, r, width, frac, color):
        cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline=TRACK, width=width)
        if frac >= 0.999:
            cv.create_oval(cx - r, cy - r, cx + r, cy + r, outline=color, width=width)
        elif frac > 0.005:
            cv.create_arc(cx - r, cy - r, cx + r, cy + r, start=90, extent=-360 * frac,
                          style="arc", outline=color, width=width)

    @staticmethod
    def hit(buttons, x, y):
        for b in reversed(buttons):
            if b["x1"] <= x <= b["x2"] and b["y1"] <= y <= b["y2"]:
                return b
        return None

    def button(self, cv, store, x, y, w, h, label, action, enabled=True, kind="normal",
               hot=None, font=None, radius=9, **extra):
        """kinds: normal | primary (light) | accent (lunch) | dark (settings save) | outline | icon"""
        S = self.S
        is_hot = enabled and hot is not None and hot.get("id") == (label, action)
        fills = {"normal": (BTN, BTN_HOT, TEXT), "primary": ("#e9eaec", "#ffffff", INK),
                 "accent": (COL["lunch"], "#f0ab7a", "#1d140d"), "dark": (W_INK, "#343a44", "#ffffff"),
                 "outline": ("#ffffff", "#f3f4f6", W_INK), "icon": (BTN, BTN_HOT, TEXT)}
        base, hov, fg = fills[kind]
        fill = hov if is_hot else base
        if not enabled:
            fill, fg = BTN_OFF, OFF_TEXT
        self.rrect(cv, x, y, x + w, y + h, radius * S, fill=fill,
                   outline=W_LINE if kind == "outline" else "", width=1)
        if kind == "icon":
            for dx in (-6, 0, 6):
                cv.create_oval(x + w / 2 + (dx - 1.8) * S, y + h / 2 - 1.8 * S,
                               x + w / 2 + (dx + 1.8) * S, y + h / 2 + 1.8 * S, fill=SUB, outline="")
        else:
            bold = kind in ("primary", "accent", "dark")
            f = font or (self.ui_bold(12.5) if bold else self.F(self.ui, 12.5))
            cv.create_text(x + w / 2, y + h / 2, text=label, font=f, fill=fg)
        b = dict(x1=x, y1=y, x2=x + w, y2=y + h, action=action, enabled=enabled, id=(label, action))
        b.update(extra)
        store.append(b)
        return b
