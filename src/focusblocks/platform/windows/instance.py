from __future__ import annotations

import ctypes
import hashlib
from pathlib import Path

ERROR_ALREADY_EXISTS = 183


class SingleInstanceLock:
    """A named mutex per data folder, so two copies never track into the same database.

    Test mode has its own folder, so it can still run next to the real copy.
    """

    def __init__(self, data_dir: Path):
        digest = hashlib.sha1(str(data_dir.resolve()).lower().encode()).hexdigest()[:16]
        self.name = f"Local\\FocusBlocks-{digest}"
        self._handle: int | None = None

    def acquire(self) -> bool:
        k32 = ctypes.windll.kernel32
        k32.CreateMutexW.restype = ctypes.c_void_p
        handle = k32.CreateMutexW(None, False, self.name)
        if not handle:
            return True                    # can't tell: don't block startup over it
        if ctypes.GetLastError() == ERROR_ALREADY_EXISTS:
            k32.CloseHandle(ctypes.c_void_p(handle))
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        if self._handle:
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(self._handle))
            self._handle = None
