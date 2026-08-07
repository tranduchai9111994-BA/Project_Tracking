"""
Regression: Chiều PM Gantt Phase A — panel + render từ plan.schedule.

Kiểm tra tầng static (HTML/JS/CSS) + HELP — không cần browser.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_JS = (ROOT / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
INDEX_HTML = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
STYLE_CSS = (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")
HELP_JS = (ROOT / "static" / "js" / "help_content.js").read_text(encoding="utf-8")
GUIDE_MD = (ROOT / "docs" / "PM_DIMENSION_GUIDE.md").read_text(encoding="utf-8")


class TestHtmlShell:
    def test_gantt_wrap_and_zoom_controls(self):
        assert 'id="pmGanttSummary"' in INDEX_HTML
        assert 'id="pmGanttAlertBox"' in INDEX_HTML
        assert 'id="pmPlanGanttPanel"' in INDEX_HTML
        assert 'id="pmGanttZoomWeek"' in INDEX_HTML
        assert 'id="pmGanttZoomMonth"' in INDEX_HTML
        assert 'id="pmGanttScaleLabel"' in INDEX_HTML
        assert "setPmGanttZoom('week')" in INDEX_HTML
        assert "setPmGanttZoom('month')" in INDEX_HTML
        assert "pmGanttZoomIn()" in INDEX_HTML
        assert "togglePmGanttPhase" in DASHBOARD_JS
        # Nằm trong section-pm
        pm_idx = INDEX_HTML.index('id="section-pm"')
        wrap_idx = INDEX_HTML.index('id="pmPlanGanttWrap"')
        assert wrap_idx > pm_idx
        # Gantt trước bảng lịch trình
        sched_idx = INDEX_HTML.index('id="pmScheduleBody"')
        assert wrap_idx < sched_idx


class TestJs:
    def test_render_and_zoom_exported(self):
        assert "function renderPmPlanGantt(" in DASHBOARD_JS
        assert "window.renderPmPlanGantt = renderPmPlanGantt" in DASHBOARD_JS
        assert "function setPmGanttZoom(" in DASHBOARD_JS
        assert "window.setPmGanttZoom = setPmGanttZoom" in DASHBOARD_JS

    def test_called_from_render_pm_dimension(self):
        idx = DASHBOARD_JS.index("function renderPmDimension(")
        chunk = DASHBOARD_JS[idx: idx + 2800]
        assert "_pmRefreshGanttViews()" in chunk
        assert "_pmPopulateGanttFilters(plan)" in chunk

    def test_overdue_and_zoom_logic(self):
        assert "pm-gantt-bar--overdue" in DASHBOARD_JS
        assert "pm-gantt-bar--ontime" in DASHBOARD_JS
        assert "pm-gantt-bar--deadline" in DASHBOARD_JS
        assert "pm-gantt-bar--actual" in DASHBOARD_JS
        assert "togglePmGanttPhase" in DASHBOARD_JS
        assert "_pmScheduleForDisplay" in DASHBOARD_JS
        idx = DASHBOARD_JS.index("function _renderPmTimelineGantt(")
        fn = DASHBOARD_JS[idx: idx + 12000]
        assert "is_phase_header" in fn
        assert "pm-gantt-today-line" in fn
        assert "_paintPmGanttSummary" in DASHBOARD_JS
        assert "schedule_insights" in DASHBOARD_JS
        assert "_pmLazyLoadGanttView" in DASHBOARD_JS
        assert "/pm/gantt-view" in DASHBOARD_JS
        assert 'zoom === "week"' in fn
        assert "pic_client" in fn
        assert "is_phase_header" in fn
        assert "pm-gantt-today-line" in fn


class TestCss:
    def test_pm_gantt_classes(self):
        for cls in (
            ".pm-gantt-wrap",
            ".pm-gantt-bar",
            ".pm-gantt-bar--overdue",
            ".pm-gantt-bar--ontime",
            ".pm-gantt-bar--deadline",
            ".pm-gantt-today-line",
            ".pm-gantt-row--phase",
            ".pm-gantt-toggle",
            ".pm-gantt-legend",
        ):
            assert cls in STYLE_CSS


class TestDocsHelp:
    def test_help_pm_key(self):
        assert '"pm":' in HELP_JS
        assert "Gantt lịch trình" in HELP_JS or "Gantt thanh" in HELP_JS

    def test_guide_mentions_phase_a(self):
        assert "Gantt lịch trình PM" in GUIDE_MD
        assert "Phase A" in GUIDE_MD
