from __future__ import annotations

import datetime as dt
import time


class SystemClock:
    def time(self) -> float:
        return time.time()

    def now(self) -> dt.datetime:
        return dt.datetime.now()

    def today(self) -> dt.date:
        return dt.date.today()
