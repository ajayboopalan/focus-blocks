"""Composition root: the only place that knows which concrete adapters are used."""

from __future__ import annotations

import os
import shutil
import threading
import time
from dataclasses import dataclass, field

from focusblocks.config import ConfigStore, seed_test_config
from focusblocks.core.clock import SystemClock
from focusblocks.core.commands import Command
from focusblocks.core.engine import Engine, EngineServices
from focusblocks.core.events import ConfigReloaded, EventBus
from focusblocks.core.ports import Notifier
from focusblocks.core.work_sources import WorkSourceRule, default_rules
from focusblocks.logging_setup import close_file_logs
from focusblocks.paths import AppPaths
from focusblocks.platform.windows import (
    HotkeyListener,
    PillowDesktopSnapshotter,
    PyvdaDesktopMonitor,
    RegistryDeviceMonitor,
    SingleInstanceLock,
    ToastNotifier,
    Win32InputMonitor,
    Win32WindowMonitor,
    WindowsUiPlatform,
)
from focusblocks.plugins import Plugin, PluginRegistry, load_plugins
from focusblocks.reports import ReportRegistry, default_reports, publish_html
from focusblocks.storage import SqliteBlockRepository

DEFAULT_REPORT = "heatmap"
ENGINE_STOP_SECONDS = 5


@dataclass
class Application:
    paths: AppPaths
    test_mode: bool
    notifier: Notifier
    config_store: ConfigStore
    events: EventBus = field(default_factory=EventBus)
    reports: ReportRegistry = field(default_factory=default_reports)
    work_rules: list[WorkSourceRule] = field(default_factory=default_rules)

    @classmethod
    def create(cls, test_mode: bool = False, plugins: list[tuple[str, Plugin]] | None = None) -> Application:
        paths = AppPaths.test() if test_mode else AppPaths.default()
        if test_mode:
            seed_test_config(paths.config, AppPaths.default().config)
        notifier = ToastNotifier()
        app = cls(paths=paths, test_mode=test_mode, notifier=notifier,
                  config_store=ConfigStore(paths.config, notifier))
        load_plugins(PluginRegistry(app.events, app.work_rules, app.reports), plugins)
        return app

    # ----- reports -----
    def block_history(self) -> dict[str, tuple[int, float]]:
        """{iso day: (completed blocks, minutes)}. Opens its own connection, so any thread may call it."""
        repo = SqliteBlockRepository(self.paths.db)
        try:
            return repo.blocks_by_day()
        finally:
            repo.close()

    def open_report(self, name: str = DEFAULT_REPORT) -> None:
        """Build a report and open it in the browser. Safe to call from any thread."""
        cfg = self.config_store.load()
        repo = SqliteBlockRepository(self.paths.db)     # own connection: may run off the engine thread
        try:
            html = self.reports.get(name).render(cfg, repo, SystemClock().today())
        finally:
            repo.close()
        publish_html(html, self.paths.report(name))

    # ----- tracker -----
    def build_engine(self) -> Engine:
        services = EngineServices(
            clock=SystemClock(),
            notifier=self.notifier,
            repo=SqliteBlockRepository(self.paths.db),
            config=self.config_store,
            input=Win32InputMonitor(),
            windows=Win32WindowMonitor(),
            desktops=PyvdaDesktopMonitor(),
            devices=RegistryDeviceMonitor(),
            snapshots=PillowDesktopSnapshotter(self.paths.snaps),
        )
        return Engine(self.config_store.load(), services, self.events, self.work_rules)

    def start_hotkey(self, engine: Engine) -> None:
        windows = Win32WindowMonitor()

        def tag_focused_window() -> None:
            fg = windows.foreground()
            if fg and fg.pid != os.getpid():
                engine.send(Command.TAG_TOGGLE, fg.hwnd, fg.title or fg.exe)

        def listen(spec: str) -> HotkeyListener:
            listener = HotkeyListener(spec, tag_focused_window, self.notifier)
            threading.Thread(target=listener.run, daemon=True, name="hotkey").start()
            return listener

        current = listen(engine.cfg["tag_hotkey"])

        def rebind(_: ConfigReloaded) -> None:       # runs on the engine thread
            nonlocal current
            if engine.cfg["tag_hotkey"] != current.spec:
                current.stop()
                current = listen(engine.cfg["tag_hotkey"])

        self.events.subscribe(ConfigReloaded, rebind)

    def run(self, gui: bool = True) -> None:
        lock = SingleInstanceLock(self.paths.data_dir)
        if not lock.acquire():
            self.notifier.notify("Focus Blocks is already running", "Look for the pill on your screen.")
            return
        engine = self.build_engine()
        engine_thread = threading.Thread(target=engine.run, daemon=True, name="engine")
        engine_thread.start()
        if not self.test_mode:   # leave the hotkey to the real copy if both are running
            self.start_hotkey(engine)
        else:
            self.notifier.notify("Focus Blocks test mode",
                                 "1-min blocks, 30-s breaks, separate data. Right-click > Test.")
        clear_test_data = False
        try:
            if gui:
                clear_test_data = self._run_pill(engine)
            else:
                engine.send(Command.START)   # no pill to click Start on
                while True:
                    time.sleep(3600)
        except KeyboardInterrupt:
            pass
        finally:
            engine.stop()                    # saves the block in progress and closes the database
            engine_thread.join(timeout=ENGINE_STOP_SECONDS)
            lock.release()
        if clear_test_data and self.test_mode:
            close_file_logs()                # Windows won't delete open files
            shutil.rmtree(self.paths.data_dir, ignore_errors=True)

    def _run_pill(self, engine: Engine) -> bool:
        """Show the pill until it closes. True if the user picked "Clear test data and quit"."""
        from focusblocks.ui.context import UiContext
        from focusblocks.ui.pill import Pill
        ctx = UiContext(
            paths=self.paths,
            config_store=self.config_store,
            platform=WindowsUiPlatform(PillowDesktopSnapshotter(self.paths.snaps)),
            load_history=self.block_history,
            test_mode=self.test_mode,
        )
        pill = Pill(engine, ctx)
        pill.mainloop()
        return pill.clear_requested
