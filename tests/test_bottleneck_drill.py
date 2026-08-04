"""Drill-down chart=bottleneck — stuck functions + lý do (BA/UX #8)."""
from __future__ import annotations

from datetime import date, timedelta

from parser.excel_parser import ParsedData, FunctionRow, PhaseData, PhaseGroup
from analyzer.drill_down import drill_down, build_title, SUPPORTED_CHARTS
from analyzer.dashboard_engine import DashboardEngine


TODAY = date(2026, 7, 28)
PAST = TODAY - timedelta(days=3)
PHASES = ("Analysis", "Dev", "UAT")


def _row(ma: str, module: str, phases: dict[str, PhaseData], **meta) -> FunctionRow:
    m = {"ma_cn": ma, "ten_cn": f"CN {ma}", "module": module, "quy_trinh": f"QT-{module}", **meta}
    return FunctionRow(row_num=1, meta=m, phases=phases)


def _data(rows) -> ParsedData:
    pgs = [PhaseGroup(name=p, attributes={}) for p in PHASES]
    modules = sorted({r.meta.get("module") or "" for r in rows})
    return ParsedData(
        headers={},
        meta_columns={},
        phase_groups=pgs,
        rows=rows,
        all_phases=list(PHASES),
        all_modules=modules,
        all_processes=[],
        all_pics=[],
    )


def test_bottleneck_in_supported_charts():
    assert "bottleneck" in SUPPORTED_CHARTS


def test_bottleneck_drill_overdue_has_ly_do():
    """Dev In-progress + End quá hạn → stuck overdue + ly_do."""
    rows = [
        _row("A1", "MOD1", {
            "Analysis": PhaseData(status="Closed", end_date=PAST),
            "Dev": PhaseData(status="In-progress", end_date=PAST, pics=["X"]),
            "UAT": PhaseData(status="Open"),
        }),
        _row("A2", "MOD1", {
            "Analysis": PhaseData(status="Closed"),
            "Dev": PhaseData(status="Closed"),
            "UAT": PhaseData(status="Closed"),
        }),
    ]
    data = _data(rows)
    items = drill_down(data, "bottleneck", {"phase": "Dev"}, TODAY)
    assert len(items) == 1
    assert items[0]["ma_cn"] == "A1"
    assert items[0]["module"] == "MOD1"
    assert items[0]["quy_trinh"]
    assert items[0]["status"] == "In-progress"
    assert items[0].get("ly_do")
    assert "End" in items[0]["ly_do"] or "trễ" in items[0]["ly_do"].lower()
    assert items[0].get("stuck_kind") in ("overdue", "both")


def test_bottleneck_drill_stalled_has_ly_do():
    """Analysis Closed, Dev chưa start, End Dev quá hạn → stalled."""
    rows = [
        _row("S1", "MOD2", {
            "Analysis": PhaseData(status="Closed", end_date=PAST - timedelta(days=5)),
            "Dev": PhaseData(status="Open", end_date=PAST),
            "UAT": PhaseData(status="Open"),
        }),
    ]
    data = _data(rows)
    items = drill_down(data, "bottleneck", {"phase": "Dev"}, TODAY)
    assert len(items) == 1
    assert items[0]["ma_cn"] == "S1"
    assert items[0].get("ly_do")
    assert "Analysis" in items[0]["ly_do"] or items[0].get("completed_phase") == "Analysis"
    assert items[0].get("stuck_kind") in ("stalled", "both", "overdue")


def test_bottleneck_title_and_matrix_count_align():
    rows = [
        _row("A1", "MOD1", {
            "Analysis": PhaseData(status="Closed", end_date=PAST),
            "Dev": PhaseData(status="In-progress", end_date=PAST, pics=["X"]),
            "UAT": PhaseData(status="Open"),
        }),
        _row("B1", "MOD2", {
            "Analysis": PhaseData(status="Closed"),
            "Dev": PhaseData(status="Closed"),
            "UAT": PhaseData(status="Closed"),
        }),
    ]
    data = _data(rows)
    engine = DashboardEngine(today=TODAY)
    mx = engine.compute_all(data)["phase_status_matrix"]
    assert (mx.get("bottleneck") or {}).get("Dev", 0) >= 1

    items = drill_down(data, "bottleneck", {"phase": "Dev"}, TODAY)
    assert len(items) >= 1
    title = build_title("bottleneck", {"phase": "Dev"})
    assert "Dev" in title
    assert "Bottleneck" in title


def test_phase_matrix_enrich_ly_do_for_stuck():
    """Ô matrix % vẫn drill phase_matrix — stuck item có ly_do."""
    rows = [
        _row("A1", "MOD1", {
            "Analysis": PhaseData(status="Closed"),
            "Dev": PhaseData(status="In-progress", end_date=PAST, pics=["X"]),
            "UAT": PhaseData(status="Open"),
        }),
        _row("A2", "MOD1", {
            "Analysis": PhaseData(status="Closed"),
            "Dev": PhaseData(status="Closed"),
            "UAT": PhaseData(status="Closed"),
        }),
    ]
    data = _data(rows)
    items = drill_down(
        data, "phase_matrix", {"module": "MOD1", "phase": "Dev"}, TODAY,
    )
    by = {i["ma_cn"]: i for i in items}
    assert by["A1"].get("ly_do")
    assert not by["A2"].get("ly_do")
