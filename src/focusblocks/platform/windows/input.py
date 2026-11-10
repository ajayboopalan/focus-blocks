from __future__ import annotations

import ctypes


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


class Win32InputMonitor:
    def idle_seconds(self) -> float:
        lii = _LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(lii)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
        k32 = ctypes.windll.kernel32
        k32.GetTickCount.restype = ctypes.c_uint
        return ((k32.GetTickCount() - lii.dwTime) & 0xFFFFFFFF) / 1000
