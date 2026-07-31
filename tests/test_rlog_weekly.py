"""Tests smoke cho analyzer.rlog_weekly — week window + count."""
from datetime import date, timedelta

from parser.excel_parser import ParsedData, FunctionRow, PhaseData, PhaseGroup
from analyzer.rlog_weekly import (
    compute_rlog_weekly,
    _week_bounds,
    _row_rlog_id,
    _is_rlog_attr,
)


TODAY = date(2026, 7, 31)  # Friday → ISO week Mon 27/07 – Sun 02/08


def _pg(*names: str) -> list[PhaseGroup]:
    groups = []
    for n in names:
        attrs = {"Start": 1, "End": 2, "Status": 3}
        if n == "Analysis":
            attrs["RlogID"] = 4
        groups.append(PhaseGroup(name=n, attributes=attrs))
    return groups


def _row(ma, ten, module, rlog_id=None, dev_status=None, dev_start=None, dev_end=None, pics=None):
    phases = {
        "Analysis": PhaseData(
            status="Closed",
            end_date=date(2026, 3, 1),
            extra={"RlogID": rlog_id} if rlog_id else {},
        ),
    }
    if dev_status is not None or dev_start or dev_end:
        phases["Dev"] = PhaseData(
            status=dev_status,
            start_date=dev_start,
            end_date=dev_end,
            pics=pics or ["DevA"],
        )
    return FunctionRow(
        row_num=2,
        meta={"ma_cn": ma, "ten_cn": ten, "module": module},
        phases=phases,
    )


def _data(rows) -> ParsedData:
    return ParsedData(
        headers={},
        meta_columns={},
        phase_groups=_pg("Analysis", "Dev"),
        rows=rows,
        all_modules=["PR"],
        all_phases=["Analysis", "Dev"],
        all_pics=["DevA"],
        all_statuses=["Open", "In-progress", "Closed"],
        all_priorities=[],
        all_complexities=[],
        all_giai_doan=[],
        all_processes=[],
    )


def test_week_bounds_iso_monday_sunday():
    mon, sun = _week_bounds(TODAY, 0)
    assert mon == date(2026, 7, 27)
    assert sun == date(2026, 8, 2)
    assert mon.weekday() == 0
    nmon, nsun = _week_bounds(TODAY, 1)
    assert nmon == date(2026, 8, 3)
    assert nsun == date(2026, 8, 9)


def test_rlog_attr_detect():
    assert _is_rlog_attr("RlogID")
    assert _is_rlog_attr("R-Log ID")
    assert _is_rlog_attr("rlog")
    assert not _is_rlog_attr("Note")
    assert not _is_rlog_attr("Defect")


def test_coded_this_week_count_and_list():
    """Dev Closed + End trong tuần hiện tại + có RlogID → coded."""
    rows = [
        _row("A.01", "Func A", "PR", rlog_id="25001",
             dev_status="Closed", dev_end=date(2026, 7, 29), pics=["Alice"]),
        _row("A.02", "Func B", "PR", rlog_id="25002",
             dev_status="Closed", dev_end=date(2026, 7, 20)),  # tuần trước
        _row("A.03", "Func C", "PR", rlog_id="25003",
             dev_status="In-progress", dev_end=date(2026, 7, 30)),
        _row("A.04", "No Rlog", "PR", rlog_id=None,
             dev_status="Closed", dev_end=date(2026, 7, 28)),  # không RlogID
    ]
    payload = compute_rlog_weekly(_data(rows), today=TODAY)
    coded = payload["rlog_coded_this_week"]
    assert coded["count"] == 1
    assert coded["items"][0]["ma_cn"] == "A.01"
    assert coded["items"][0]["rlog_id"] == "25001"
    assert coded["items"][0]["closed_date"] == "2026-07-29"
    assert coded["items"][0]["pic"] == ["Alice"]
    assert payload["rlog_scope"] == "with_rlog_id"
    assert payload["week"]["iso_week_label"] == "W31"


def test_plan_next_week_end_in_window():
    """Dev chưa Closed, End ∈ tuần tới → plan."""
    next_mon, _ = _week_bounds(TODAY, 1)
    rows = [
        _row("B.01", "Plan 1", "PR", rlog_id="26001",
             dev_status="In-progress",
             dev_start=date(2026, 7, 28),
             dev_end=next_mon + timedelta(days=2)),
        _row("B.02", "Already closed next", "PR", rlog_id="26002",
             dev_status="Closed",
             dev_end=next_mon + timedelta(days=1)),
        _row("B.03", "Far future", "PR", rlog_id="26003",
             dev_status="Open",
             dev_start=date(2026, 9, 1),
             dev_end=date(2026, 9, 10)),
        _row("B.04", "Cancelled", "PR", rlog_id="26004",
             dev_status="Cancelled",
             dev_end=next_mon + timedelta(days=1)),
    ]
    payload = compute_rlog_weekly(_data(rows), today=TODAY)
    plan = payload["rlog_plan_next_week"]
    assert plan["count"] == 1
    assert plan["items"][0]["ma_cn"] == "B.01"
    assert payload["next_week"]["monday_iso"] == next_mon.isoformat()


def test_plan_next_week_overlap_span():
    """Start–End giao tuần tới (không End đúng trong tuần) vẫn vào plan."""
    next_mon, next_sun = _week_bounds(TODAY, 1)
    rows = [
        _row("C.01", "Long span", "PR", rlog_id="27001",
             dev_status="Assigned",
             dev_start=next_mon - timedelta(days=10),
             dev_end=next_sun + timedelta(days=10)),
    ]
    payload = compute_rlog_weekly(_data(rows), today=TODAY)
    assert payload["rlog_plan_next_week"]["count"] == 1


def test_fallback_all_functions_when_no_rlog_id():
    """Không có RlogID filled → scope all_functions, vẫn đếm Dev Closed tuần này."""
    rows = [
        _row("D.01", "No rlog col value", "PR", rlog_id=None,
             dev_status="Closed", dev_end=date(2026, 7, 28)),
        _row("D.02", "Also none", "PR", rlog_id=None,
             dev_status="Closed", dev_end=date(2026, 7, 10)),
    ]
    # phase_groups vẫn có RlogID attr nhưng không có value filled
    payload = compute_rlog_weekly(_data(rows), today=TODAY)
    assert payload["rlog_scope"] == "all_functions"
    assert payload["rlog_coded_this_week"]["count"] == 1
    assert payload["rlog_coded_this_week"]["items"][0]["ma_cn"] == "D.01"
    assert "mọi function" in payload["definition"].lower() or "moi function" in payload["definition"].lower() or "mọi function" in payload["definition"]


def test_dashboard_engine_includes_rlog_weekly():
    from analyzer.dashboard_engine import DashboardEngine
    rows = [
        _row("E.01", "X", "PR", rlog_id="1",
             dev_status="Closed", dev_end=date(2026, 7, 29)),
    ]
    metrics = DashboardEngine(today=TODAY).compute_all(_data(rows))
    assert "rlog_weekly" in metrics
    assert metrics["rlog_weekly"]["rlog_coded_this_week"]["count"] == 1


def test_row_rlog_id_from_extra():
    r = _row("F.01", "Y", "PR", rlog_id="SonHN6: 25265")
    assert _row_rlog_id(r) == "SonHN6: 25265"
