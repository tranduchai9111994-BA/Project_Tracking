"""Test analyzer/data_quality.py — 7 loại issue detection."""
from datetime import date
import pytest
from parser.excel_parser import ParsedData, FunctionRow, PhaseData, PhaseGroup
from analyzer.data_quality import compute_data_quality


def _mk_row(row_num=2, ma_cn="F1", ten_cn="Func 1", module="M1",
            priority="Must-have", complexity="Low", fit_gap="FIT",
            quy_trinh="Q1", phases=None):
    return FunctionRow(
        row_num=row_num,
        meta={
            "ma_cn": ma_cn, "ten_cn": ten_cn, "module": module,
            "priority": priority, "complexity": complexity, "fit_gap": fit_gap,
            "quy_trinh": quy_trinh,
        },
        phases=phases or {},
    )


def _mk_data(rows):
    return ParsedData(
        headers={}, meta_columns={}, phase_groups=[], rows=rows,
    )


def test_no_issues_when_data_clean():
    """Data hoàn toàn clean → 0 issue, clean_pct=100."""
    r = _mk_row(phases={"Analysis": PhaseData(
        start_date=date(2026, 1, 1), end_date=date(2026, 1, 10),
        status="Closed", pics=["Alice"],
    )})
    out = compute_data_quality(_mk_data([r]))
    assert out["summary"]["total_issues"] == 0
    assert out["summary"]["clean_pct"] == 100.0
    assert out["summary"]["clean_rows"] == 1


def test_invalid_status():
    r = _mk_row(phases={"Dev": PhaseData(status="Xong roi")})
    out = compute_data_quality(_mk_data([r]))
    codes = [i["code"] for i in out["issues"]]
    assert "invalid_status" in codes


def test_end_before_start():
    r = _mk_row(phases={"Dev": PhaseData(
        start_date=date(2026, 5, 10), end_date=date(2026, 5, 1),
        status="Closed", pics=["A"],
    )})
    out = compute_data_quality(_mk_data([r]))
    codes = [i["code"] for i in out["issues"]]
    assert "end_before_start" in codes


def test_closed_no_end():
    """Status=Closed nhưng thiếu End (chỉ báo khi có Start hoặc phase có dates)."""
    r = _mk_row(phases={"Dev": PhaseData(
        start_date=date(2026, 1, 1), end_date=None,
        status="Closed", pics=["A"],
    )})
    out = compute_data_quality(_mk_data([r]))
    codes = [i["code"] for i in out["issues"]]
    assert "closed_no_end" in codes


def test_blank_pic_when_active():
    r = _mk_row(phases={"Dev": PhaseData(
        status="In-progress", pics=[],
    )})
    out = compute_data_quality(_mk_data([r]))
    codes = [i["code"] for i in out["issues"]]
    assert "blank_pic" in codes


def test_blank_pic_not_when_closed():
    """Closed → không cần PIC."""
    r = _mk_row(phases={"Dev": PhaseData(
        status="Closed", pics=[], end_date=date(2026, 1, 1),
    )})
    out = compute_data_quality(_mk_data([r]))
    codes = [i["code"] for i in out["issues"]]
    assert "blank_pic" not in codes


def test_blank_meta_fields():
    r = _mk_row(priority="", complexity="", fit_gap="")
    out = compute_data_quality(_mk_data([r]))
    codes = [i["code"] for i in out["issues"]]
    assert "blank_priority" in codes
    assert "blank_complexity" in codes
    assert "blank_fitgap" in codes


def test_duplicate_ma_cn():
    r1 = _mk_row(row_num=2, ma_cn="DUP-01")
    r2 = _mk_row(row_num=5, ma_cn="DUP-01")
    out = compute_data_quality(_mk_data([r1, r2]))
    dups = [i for i in out["issues"] if i["code"] == "duplicate_ma_cn"]
    # Cả 2 row đều bị flag
    assert len(dups) == 2


def test_summary_counts():
    r_bad = _mk_row(row_num=2, ma_cn="F1", phases={"Dev": PhaseData(status="XyZ")})  # invalid_status
    r_good = _mk_row(row_num=3, ma_cn="F2", phases={"Dev": PhaseData(status="Closed", end_date=date(2026,1,1), pics=["A"])})
    out = compute_data_quality(_mk_data([r_bad, r_good]))
    assert out["summary"]["total_rows"] == 2
    assert out["summary"]["affected_rows"] == 1  # chỉ r_bad
    assert out["summary"]["clean_rows"] == 1
    assert out["summary"]["clean_pct"] == 50.0


def test_row_empty_ma_cn_skipped_for_blank_meta():
    """Row không có Mã CN → không báo blank_priority/complexity/fitgap (row rỗng)."""
    r = _mk_row(ma_cn="", priority="", complexity="", fit_gap="")
    out = compute_data_quality(_mk_data([r]))
    codes = [i["code"] for i in out["issues"]]
    assert "blank_priority" not in codes
    assert "blank_complexity" not in codes
