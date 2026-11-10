from __future__ import annotations

import datetime as dt
import logging
import webbrowser
from pathlib import Path
from typing import Protocol

from focusblocks.core.models import Config
from focusblocks.core.ports import BlockRepository

log = logging.getLogger(__name__)


class Report(Protocol):
    name: str      # also the output file name: <data dir>/<name>.html

    def render(self, cfg: Config, repo: BlockRepository, today: dt.date) -> str:
        """Return a complete HTML document."""
        ...


class ReportRegistry:
    def __init__(self) -> None:
        self._reports: dict[str, Report] = {}

    def register(self, report: Report) -> None:
        self._reports[report.name] = report

    def get(self, name: str) -> Report:
        try:
            return self._reports[name]
        except KeyError:
            raise KeyError(f"unknown report {name!r}; available: {', '.join(self.names())}") from None

    def names(self) -> list[str]:
        return sorted(self._reports)


def publish_html(html: str, out: Path) -> None:
    out.write_text(html, encoding="utf-8")
    log.info("Wrote %s", out)
    webbrowser.open(out.as_uri())
