# Contributing to Focus Blocks

Thanks for wanting to help! Every kind of contribution counts: bug reports, feature ideas, docs, screenshots,
and code.

## Reporting bugs and ideas

[Open an issue](https://github.com/ajayboopalan/focus-blocks/issues) with:

- what you did, what you expected, and what happened instead;
- your Windows version and Focus Blocks version (Settings → Apps shows it);
- the relevant lines from `%USERPROFILE%\.focusblocks\focusblocks.log` (check it doesn't contain anything private).

## Making a change

1. Fork the repo and create a branch: `git checkout -b my-change`.
2. Set up a dev environment (Windows 10/11, Python 3.11+):

   ```powershell
   python -m venv .venv
   .venv\Scripts\python -m pip install -e ".[dev]"
   .venv\Scripts\pre-commit install
   ```

3. Make the change, with tests where it's logic (the engine runs on fakes, so most behaviour is easy to test).
4. Run the same checks CI runs:

   ```powershell
   .venv\Scripts\python -m pytest
   .venv\Scripts\python -m ruff check .
   .venv\Scripts\python -m mypy
   ```

5. Try it for real: `.venv\Scripts\focusblocks --test` runs 1-minute blocks with separate data and a
   **Test** menu on the pill to jump to the end of a block or break.
6. Open a pull request describing what changed and why. Screenshots help for UI changes.

## Building the installer

Needs [Inno Setup 6](https://jrsoftware.org/isdl.php) as well:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build.ps1           # dist\FocusBlocks-Setup-<version>.exe
powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -ExeOnly   # just dist\FocusBlocks\FocusBlocks.exe
```

Quit any copy running from `dist\FocusBlocks` first; it locks its files.

## Running from source

| Command | What it does |
| --- | --- |
| `focusblocksw` | Pill + tracker, no console window |
| `focusblocks` | Same, with a console log |
| `focusblocks --nogui` | Tracker only (starts tracking right away) |
| `focusblocks --test` | 1-minute blocks, 30-second breaks, separate data in `~/.focusblocks-test`, plus a **Test** menu |
| `focusblocks report [name]` | Build a report (default `heatmap`) as HTML and open it in the browser |


## Architecture

```
src/focusblocks/
├── cli.py               argument parsing
├── app.py               composition root: builds and wires every concrete adapter
├── paths.py             data-folder layout (normal vs test mode)
├── plugins.py           add-on discovery and registry
├── config/              defaults, load/migrate/save config.json
├── core/                domain logic, no OS / UI / DB imports
│   ├── engine.py        the tracking state machine (WORK, BREAK, WAIT, PAUSED, LUNCH)
│   ├── ports.py         interfaces the engine depends on
│   ├── work_sources.py  ordered rules deciding "does this window count as work?"
│   ├── events.py        domain events + event bus
│   ├── commands.py      commands the UI/hotkey send to the engine
│   └── models.py        Mode, Status, ForegroundWindow, ...
├── storage/             SQLite repository
├── platform/windows/    one adapter per OS signal: input, windows, desktops, devices,
│                        screenshots, hotkey, toast notifications, UI helpers
├── reports/             report registry + heatmap
└── ui/                  Tk: pill, break overlay, settings window (incl. heatmap), drawing kit, theme
packaging/               PyInstaller launcher, icon, Inno Setup script, build.ps1
```

Design rules:

- **Dependencies point inward.** `core` defines the ports (`InputMonitor`, `WindowMonitor`,
  `BlockRepository`, `Notifier`, `Clock`, ...). Adapters implement them. Only `app.py` picks the
  concrete classes. This keeps the engine fully testable with fakes (see `tests/fakes.py`), and
  another OS can be added as a sibling of `platform/windows/`.
- **One owner for state.** The engine runs on its own thread. The UI only reads its attributes and
  sends `Command`s through a queue.
- **Open for extension.** New work sources, event reactions and reports plug in without editing
  the engine (see below).
- **Failures stay contained.** A failing tick, command, event handler or plugin is logged and skipped.
  The tracker keeps running.

## Writing an add-on

An add-on is a package that exposes a `register(registry)` function under the
`focusblocks.plugins` entry-point group:

```toml
# your add-on's pyproject.toml
[project.entry-points."focusblocks.plugins"]
slack = "focusblocks_slack:register"
```

```python
from focusblocks.core.events import BlockCompleted, DailyGoalReached
from focusblocks.plugins import PluginRegistry


class BrowserTabRule:
    """Count a browser window as work when its title mentions the sprint board."""
    def match(self, ctx):
        if ctx.fg and ctx.fg.exe.lower() == "chrome.exe" and "Sprint board" in ctx.fg.title:
            return "the sprint board"
        return None


class WeeklyReport:
    name = "weekly"
    def render(self, cfg, repo, today):
        return "<!doctype html>..."


def register(registry: PluginRegistry) -> None:
    registry.subscribe(BlockCompleted, lambda e: print(f"block {e.done}/{e.goal} done"))
    registry.subscribe(DailyGoalReached, lambda e: ...)
    registry.add_work_rule(BrowserTabRule())          # or index=0 to take priority
    registry.add_report(WeeklyReport())               # then: focusblocks report weekly
```

Event handlers run on the engine thread, so keep them quick, or hand the work off to a thread
or queue of your own. Available events are listed in `focusblocks/core/events.py`.


CI runs the same checks on Windows for Python 3.11-3.13 (`.github/workflows/ci.yml`).
`legacy/focusblocks_v03.py` is the original single-file prototype, kept for reference; linters skip it.
