"""SQLite storage for blocks and events.

The connection opens lazily on first use, on the thread that uses it: SQLite connections
can't be shared across threads, so the engine thread and the report thread each get their own repository.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS blocks(
        id INTEGER PRIMARY KEY, day TEXT, started TEXT, ended TEXT,
        minutes REAL, completed INTEGER)""",
    """CREATE TABLE IF NOT EXISTS events(
        id INTEGER PRIMARY KEY, day TEXT, at TEXT, kind TEXT, minutes REAL)""",
)


class SqliteBlockRepository:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._con: sqlite3.Connection | None = None

    @property
    def con(self) -> sqlite3.Connection:
        if self._con is None:
            self.db_path.parent.mkdir(exist_ok=True)
            con = sqlite3.connect(self.db_path)
            for stmt in SCHEMA:
                con.execute(stmt)
            self._con = con
        return self._con

    def close(self) -> None:
        if self._con is not None:
            self._con.close()
            self._con = None

    def log_block(self, started: dt.datetime, ended: dt.datetime, minutes: float, completed: bool) -> None:
        """Filed under the day the block ended, so a block finished after midnight counts for the new day."""
        self.con.execute(
            "INSERT INTO blocks(day, started, ended, minutes, completed) VALUES (?,?,?,?,?)",
            (ended.date().isoformat(), started.isoformat(timespec="seconds"),
             ended.isoformat(timespec="seconds"), round(minutes, 1), int(completed)))
        self.con.commit()

    def log_event(self, at: dt.datetime, kind: str, minutes: float = 0.0) -> None:
        """kind: pause | skip_break | reset | lunch"""
        self.con.execute("INSERT INTO events(day, at, kind, minutes) VALUES (?,?,?,?)",
                         (at.date().isoformat(), at.isoformat(timespec="seconds"), str(kind), round(minutes, 1)))
        self.con.commit()

    def day_counts(self, day: dt.date) -> tuple[int, int]:
        row = self.con.execute(
            "SELECT SUM(completed=1), SUM(completed=0) FROM blocks WHERE day=?", (day.isoformat(),)).fetchone()
        return int(row[0] or 0), int(row[1] or 0)

    def blocks_by_day(self) -> dict[str, tuple[int, float]]:
        rows = self.con.execute("SELECT day, SUM(completed), SUM(minutes) FROM blocks GROUP BY day").fetchall()
        return {d: (int(c or 0), float(m or 0)) for d, c, m in rows}
