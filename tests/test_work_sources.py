from focusblocks.config import DEFAULT_CONFIG
from focusblocks.core.models import ForegroundWindow
from focusblocks.core.work_sources import WorkContext, default_rules, find_work_source

from fakes import FakeSystem


def source(desktops=(), apps=(), tags=None, fg=None, current="Work"):
    system = FakeSystem()
    system.desktop = current
    cfg = dict(DEFAULT_CONFIG, work_desktops=list(desktops), work_apps=list(apps))
    ctx = WorkContext(cfg=cfg, fg=fg, tags=tags or {}, desktops=system)
    return find_work_source(ctx, default_rules())


CODE = ForegroundWindow(1, 10, "Code.exe", "x")


def test_nothing_configured_counts_any_window():
    assert source() == "any window"


def test_tagged_window_wins_first():
    assert source(desktops=["Work"], apps=["Code.exe"], tags={1: "x"}, fg=CODE) == "a tagged window"


def test_app_match_is_case_insensitive_and_strips_exe():
    assert source(apps=["code.EXE"], fg=CODE) == "Code"


def test_desktop_match():
    assert source(desktops=["work"], fg=CODE, current="Work") == "the Work desktop"


def test_desktop_mismatch():
    assert source(desktops=["Work"], fg=CODE, current="Play") is None


def test_desktop_unreadable_falls_back_to_any_window():
    assert source(desktops=["Work"], fg=CODE, current=None) == "any window (desktop check unavailable)"


def test_custom_rule_can_take_priority():
    class Always:
        def match(self, ctx):
            return "custom"

    system = FakeSystem()
    ctx = WorkContext(cfg=dict(DEFAULT_CONFIG), fg=CODE, tags={}, desktops=system)
    assert find_work_source(ctx, [Always(), *default_rules()]) == "custom"


def test_failing_rule_is_skipped():
    class Broken:
        def match(self, ctx):
            raise RuntimeError("plugin bug")

    system = FakeSystem()
    ctx = WorkContext(cfg=dict(DEFAULT_CONFIG, work_apps=["Code.exe"]), fg=CODE, tags={}, desktops=system)
    assert find_work_source(ctx, [Broken(), *default_rules()]) == "Code"
