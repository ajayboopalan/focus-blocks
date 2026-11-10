import pytest

from focusblocks.core.events import BlockCompleted, EventBus
from focusblocks.core.work_sources import default_rules
from focusblocks.plugins import PluginRegistry, load_plugins
from focusblocks.reports import default_reports


def make_registry():
    return PluginRegistry(EventBus(), default_rules(), default_reports())


def test_plugin_can_extend_every_point():
    class Rule:
        def match(self, ctx):
            return None

    class Report:
        name = "weekly"

        def render(self, cfg, repo, today):
            return ""

    seen = []

    def register(reg: PluginRegistry):
        reg.subscribe(BlockCompleted, seen.append)
        reg.add_work_rule(Rule(), index=0)
        reg.add_report(Report())

    reg = make_registry()
    assert load_plugins(reg, [("demo", register)]) == ["demo"]
    assert isinstance(reg.work_rules[0], Rule)
    assert "weekly" in reg.reports.names()


def test_broken_plugin_is_skipped():
    def bad(reg):
        raise RuntimeError("nope")

    def good(reg):
        pass

    assert load_plugins(make_registry(), [("bad", bad), ("good", good)]) == ["good"]


def test_unknown_report_lists_available():
    with pytest.raises(KeyError, match="heatmap"):
        default_reports().get("nope")
