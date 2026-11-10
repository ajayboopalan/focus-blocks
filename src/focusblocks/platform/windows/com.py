from __future__ import annotations

import ctypes
import threading

_com = threading.local()


def com_init() -> None:
    """pyvda talks to Windows through COM, which every thread must initialise once."""
    if not getattr(_com, "done", False):
        try:
            ctypes.windll.ole32.CoInitialize(None)
        except Exception:
            pass
        _com.done = True
