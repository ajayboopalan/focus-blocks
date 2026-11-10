"""Reports built from the block history. Plugins can register more through ``focusblocks.plugins``."""

from focusblocks.reports.base import Report, ReportRegistry, publish_html
from focusblocks.reports.heatmap import HeatmapReport

__all__ = ["HeatmapReport", "Report", "ReportRegistry", "default_reports", "publish_html"]


def default_reports() -> ReportRegistry:
    registry = ReportRegistry()
    registry.register(HeatmapReport())
    return registry
