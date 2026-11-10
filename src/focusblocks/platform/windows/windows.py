"""Top-level windows: which one is focused, and which apps have windows open."""

from __future__ import annotations

import ctypes
import os

from focusblocks.core.models import ForegroundWindow

# Shell and system processes that show up as "apps" but are never useful work sources.
HIDDEN_APPS = ("TextInputHost.exe", "SystemSettings.exe", "ShellExperienceHost.exe")


def exe_of_pid(pid: int) -> str:
    try:
        import psutil
        return str(psutil.Process(pid).name())
    except Exception:
        return ""


def window_pid(hwnd: int) -> int:
    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def window_title(hwnd: int) -> str:
    u = ctypes.windll.user32
    n = u.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    u.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


class Win32WindowMonitor:
    def foreground(self) -> ForegroundWindow | None:
        """The focused top-level window, or None."""
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = window_pid(hwnd)
        return ForegroundWindow(hwnd, pid, exe_of_pid(pid), window_title(hwnd))

    def window_alive(self, hwnd: int) -> bool:
        return bool(ctypes.windll.user32.IsWindow(hwnd))


def running_apps() -> dict[str, str]:
    """{exe: a window title} for apps with visible windows right now."""
    from ctypes import wintypes
    u, found, me = ctypes.windll.user32, {}, os.getpid()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if u.IsWindowVisible(hwnd) and u.GetWindowTextLengthW(hwnd) > 0:
            pid = window_pid(hwnd)
            if pid != me:
                exe = exe_of_pid(pid)
                if exe and exe not in found:
                    found[exe] = window_title(hwnd)
        return True

    try:
        u.EnumWindows(cb, 0)
    except Exception:
        pass
    for skip in HIDDEN_APPS:
        found.pop(skip, None)
    return found
