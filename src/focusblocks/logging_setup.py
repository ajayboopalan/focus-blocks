"""Logging to a file in the data folder, plus the console when there is one (under pythonw sys.stderr is None)."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_MAX_BYTES = 1_000_000
LOG_BACKUPS = 2


def configure_logging(level: int = logging.INFO, log_file: Path | None = None) -> None:
    root = logging.getLogger("focusblocks")
    if root.handlers:
        return
    root.setLevel(level)
    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            handler: logging.Handler = RotatingFileHandler(log_file, maxBytes=LOG_MAX_BYTES,
                                                           backupCount=LOG_BACKUPS, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
            root.addHandler(handler)
        except OSError:
            pass                           # read-only or locked folder: fall back to console only
    if sys.stderr is not None:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S"))
        root.addHandler(handler)
    if not root.handlers:
        root.addHandler(logging.NullHandler())


def close_file_logs() -> None:
    """Close and detach the log file, e.g. before deleting the folder it lives in."""
    root = logging.getLogger("focusblocks")
    for handler in [h for h in root.handlers if isinstance(h, logging.FileHandler)]:
        root.removeHandler(handler)
        handler.close()
