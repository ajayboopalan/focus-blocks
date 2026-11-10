"""System-wide hotkey through RegisterHotKey."""

from __future__ import annotations

import ctypes
import threading
from collections.abc import Callable

from focusblocks.core.ports import Notifier

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
VK_F1 = 0x70
MODIFIERS = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT, "shift": MOD_SHIFT, "win": MOD_WIN}


def parse_hotkey(spec: str) -> tuple[int, int]:
    """'ctrl+alt+w' -> (modifier flags, virtual-key code). vk is 0 if no key was recognised."""
    mods, vk = 0, 0
    for part in spec.lower().replace(" ", "").split("+"):
        if part in MODIFIERS:
            mods |= MODIFIERS[part]
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
        elif part.startswith("f") and part[1:].isdigit():
            vk = VK_F1 - 1 + int(part[1:])
    return mods, vk


class HotkeyListener:
    """Blocks in a Windows message loop; run it on its own thread. stop() ends it from any thread."""

    def __init__(self, spec: str, on_press: Callable[[], None], notifier: Notifier):
        self.spec = spec
        self.on_press = on_press
        self._notifier = notifier
        self.ready = threading.Event()        # set once the hotkey is registered
        self._stopped = False
        self._thread_id = 0

    def run(self) -> None:
        from ctypes import wintypes
        mods, vk = parse_hotkey(self.spec)
        u = ctypes.windll.user32
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        if not vk or not u.RegisterHotKey(None, 1, mods | MOD_NOREPEAT, vk):
            self._notifier.notify("Hotkey unavailable", f"{self.spec} is taken. Change tag_hotkey in settings.")
            return
        try:
            if self._stopped:
                return
            self.ready.set()
            msg = wintypes.MSG()
            while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:   # 0 = WM_QUIT, -1 = error
                if msg.message == WM_HOTKEY:
                    self.on_press()
        finally:
            u.UnregisterHotKey(None, 1)

    def stop(self) -> None:
        self._stopped = True
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
