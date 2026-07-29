"""Test T22 - compute_aging_wip."""
from datetime import date, timedelta
from parser.excel_parser import ParsedData, FunctionRow, PhaseData
from analyzer.advanced_metrics import compute_aging_wip


def _mk(row_num=2, ma_cn="F1", module="M1", phases=None):
    return FunctionRow(
        row_num=row_num,
        meta={"ma_cn": ma_cn, "ten_cn": "Func", "module": module,
              "quy_trinh": "Q1", "priority": "Must", "complexity": "Low"},
        phases=phases or {},
    )


def _mk_data(rows):
    return ParsedData(headers={}, meta_columns={}, phase_groups=[], rows=rows)


def test_no_wip():
    r = _mk(phases={"Dev": PhaseData(status="Closed", end_date=date(2026, 1, 1))})
    out = compute_aging_wip(_mk_data([r]), threshold_days=14, today=date(2026, 3, 1))
    assert out["summary"]["total_wip"] == 0
    assert out["summary"]["total_aging"] == 0


def test_wip_under_threshold():
    """In-progress mới bắt đầu 5 ngày → chưa aging (threshold=14)."""
    today = date(2026, 3, 1)
    r = _mk(phases={"Dev": PhaseData(status="In-progress", start_date=today - timedelta(days=5))})
    out = compute_aging_wip(_mk_data([r]), threshold_days=14, today=today)
    assert out["summary"]["total_wip"] == 1
    assert out["summary"]["total_aging"] == 0


def test_wip_over_threshold():
    """In-progress 20 ngày → aging (threshold=14)."""
    today = date(2026, 3, 1)
    r = _mk(phases={"Dev": PhaseData(status="In-progress", start_date=today - timedelta(days=20), pics=["Alice"])})
    out = compute_aging_wip(_mk_data([r]), threshold_days=14, today=today)
    assert out["summary"]["total_wip"] == 1
    assert out["summary"]["total_aging"] == 1
    it = out["items"][0]
    assert it["aging_days"] == 20
    assert it["over_by_days"] == 6
    assert it["pic"] == "Alice"


def test_sort_by_aging_desc():
    today = date(2026, 3, 1)
    r1 = _mk(row_num=2, ma_cn="A", phases={"Dev": PhaseData(status="In-progress", start_date=today - timedelta(days=15))})
    r2 = _mk(row_num=3, ma_cn="B", phases={"Dev": PhaseData(status="In-progress", start_date=today - timedelta(days=50))})
    r3 = _mk(row_num=4, ma_cn="C", phases={"Dev": PhaseData(status="In-progress", start_date=today - timedelta(days=25))})
    out = compute_aging_wip(_mk_data([r1, r2, r3]), threshold_days=14, today=today)
    codes = [it["ma_cn"] for it in out["items"]]
    assert codes == ["B", "C", "A"]  # B=50, C=25, A=15


def test_wip_no_dates_skipped():
    """In-progress nhưng không có Start/End → skip (không đủ thông tin)."""
    today = date(2026, 3, 1)
    r = _mk(phases={"Dev": PhaseData(status="In-progress")})
    out = compute_aging_wip(_mk_data([r]), threshold_days=14, today=today)
    assert out["summary"]["total_wip"] == 1
    assert out["summary"]["total_aging"] == 0  # skip vì không có date anchor


def test_threshold_clamped_in_endpoint():
    """Endpoint clamp trong app.py — ở đây test analyzer accept any int."""
    today = date(2026, 3, 1)
    r = _mk(phases={"Dev": PhaseData(status="In-progress", start_date=today - timedelta(days=100))})
    out = compute_aging_wip(_mk_data([r]), threshold_days=30, today=today)
    assert out["summary"]["total_aging"] == 1
    assert out["items"][0]["over_by_days"] == 70


def test_summary_stats():
    today = date(2026, 3, 1)
    r1 = _mk(row_num=2, ma_cn="A", phases={"Dev": PhaseData(status="In-progress", start_date=today - timedelta(days=20))})
    r2 = _mk(row_num=3, ma_cn="B", phases={"Dev": PhaseData(status="In-progress", start_date=today - timedelta(days=40))})
    out = compute_aging_wip(_mk_data([r1, r2]), threshold_days=14, today=today)
    s = out["summary"]
    assert s["total_wip"] == 2
    assert s["total_aging"] == 2
    assert s["max_aging_days"] == 40
    assert s["avg_aging_days"] == 30.0
