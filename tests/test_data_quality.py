"""Test analyzer/data_quality.py — issue detection (gồm missing_deadline)."""
from datetime import date
import pytest
from parser.excel_parser import ParsedData, FunctionRow, PhaseData, PhaseGroup
from analyzer.data_quality import compute_data_quality, count_missing_deadlines


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
    assert "missing_deadline" not in codes


def test_missing_deadline_in_progress_no_end():
    """In-progress + End trống → missing_deadline (không nhầm closed_no_end)."""
    r = _mk_row(phases={"Dev": PhaseData(
        start_date=date(2026, 1, 1), end_date=None,
        status="In-progress", pics=["A"],
    )})
    out = compute_data_quality(_mk_data([r]))
    codes = [i["code"] for i in out["issues"]]
    assert "missing_deadline" in codes
    assert "closed_no_end" not in codes
    assert out["summary"]["missing_deadline_count"] == 1
    assert out["summary"]["missing_deadline_records"] == 1
    issue = next(i for i in out["issues"] if i["code"] == "missing_deadline")
    assert "Thiếu End" in issue["label"] or "đang làm" in issue["label"]


def test_missing_deadline_all_active_statuses():
    """Open / Assigned / Resolved / Pending thiếu End đều flag."""
    for st in ("Open", "Assigned", "Resolved", "Pending"):
        r = _mk_row(phases={"Dev": PhaseData(status=st, end_date=None, pics=["A"])})
        out = compute_data_quality(_mk_data([r]))
        assert "missing_deadline" in [i["code"] for i in out["issues"]], st


def test_missing_deadline_blank_status_skipped():
    """Status blank + End trống → không báo missing_deadline."""
    r = _mk_row(phases={"Dev": PhaseData(status="", end_date=None, pics=["A"])})
    out = compute_data_quality(_mk_data([r]))
    assert "missing_deadline" not in [i["code"] for i in out["issues"]]


def test_missing_deadline_dedupe_functions():
    """2 phase cùng function thiếu End → count function=1, records=2."""
    r = _mk_row(ma_cn="F99", phases={
        "Analysis": PhaseData(status="Open", end_date=None, pics=["A"]),
        "Dev": PhaseData(status="In-progress", end_date=None, pics=["B"]),
    })
    out = compute_data_quality(_mk_data([r]))
    assert out["summary"]["missing_deadline_count"] == 1
    assert out["summary"]["missing_deadline_records"] == 2
    funcs, recs = count_missing_deadlines(_mk_data([r]))
    assert (funcs, recs) == (1, 2)


def test_blank_pic_when_active():
    r = _mk_row(phases={"Dev": PhaseData(
        status="In-progress", pics=[], end_date=date(2026, 2, 1),
    )})
    out = compute_data_quality(_mk_data([r]))
    codes = [i["code"] for i in out["issues"]]
    assert "blank_pic" in codes
    assert "missing_deadline" not in codes  # có End → không flag deadline


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


def test_export_includes_missing_deadline_label(tmp_path):
    """Export Excel Data Quality chứa label loại mới."""
    from exporter.excel_exporter import export_data_quality_report
    r = _mk_row(phases={"Dev": PhaseData(
        status="In-progress", end_date=None, pics=["A"],
    )})
    payload = compute_data_quality(_mk_data([r]))
    path = export_data_quality_report(payload, output_dir=str(tmp_path))
    import openpyxl
    wb = openpyxl.load_workbook(path)
    ws = wb["Issues"]
    labels = [cell.value for row in ws.iter_rows(min_row=1, max_col=10) for cell in row]
    assert any(v and "Thiếu End khi đang làm" in str(v) for v in labels)
    wb.close()


# ==========================================================================
# T35 Task 3 — API endpoint respects global module filter
# ==========================================================================
def test_data_quality_endpoint_respects_module_filter(flask_client, sample_xlsx_path):
    """GET /data-quality?module=X chỉ trả issue thuộc module X."""
    import io
    with open(sample_xlsx_path, "rb") as f:
        flask_client.post(
            "/api/projects/default/upload",
            data={"file": (io.BytesIO(f.read()), "sample.xlsx")},
            content_type="multipart/form-data",
        )
    r_all = flask_client.get("/api/projects/default/data-quality")
    assert r_all.status_code == 200
    all_payload = r_all.get_json()
    modules = sorted({
        (it.get("module") or "")
        for it in (all_payload.get("issues") or [])
        if it.get("module")
    })
    if not modules:
        # Sample không có DQ issue → endpoint vẫn 200 là đủ
        return
    target = modules[0]
    r_f = flask_client.get(f"/api/projects/default/data-quality?module={target}")
    assert r_f.status_code == 200
    filtered = r_f.get_json()
    for it in filtered.get("issues") or []:
        assert it.get("module") == target, f"Issue {it} không thuộc module {target}"
    assert (filtered.get("summary") or {}).get("total_issues", 0) <= (
        all_payload.get("summary") or {}
    ).get("total_issues", 0)


def test_phase_overlap_detected():
    """Hai phase chồng ngày → phase_overlap."""
    r = _mk_row(phases={
        "Analysis": PhaseData(
            start_date=date(2026, 1, 1), end_date=date(2026, 1, 20),
            status="Closed", pics=["A"],
        ),
        "Dev": PhaseData(
            start_date=date(2026, 1, 10), end_date=date(2026, 2, 1),
            status="In-progress", pics=["B"],
        ),
    })
    out = compute_data_quality(_mk_data([r]))
    assert "phase_overlap" in [i["code"] for i in out["issues"]]
    assert out["summary"]["anomaly_count"] >= 1


def test_phase_no_overlap_adjacent():
    """Phase liền kề không overlap."""
    r = _mk_row(phases={
        "Analysis": PhaseData(
            start_date=date(2026, 1, 1), end_date=date(2026, 1, 10),
            status="Closed", pics=["A"],
        ),
        "Dev": PhaseData(
            start_date=date(2026, 1, 11), end_date=date(2026, 1, 20),
            status="Closed", pics=["B"],
        ),
    })
    out = compute_data_quality(_mk_data([r]))
    assert "phase_overlap" not in [i["code"] for i in out["issues"]]


def test_estimate_vs_duration_flagged():
    """Estimate 800 MH trên 2 ngày → ratio > 3x → flag."""
    r = _mk_row(phases={
        "Dev": PhaseData(
            start_date=date(2026, 1, 1), end_date=date(2026, 1, 2),
            status="Closed", pics=["A"], estimate_mh=800.0,
        ),
    })
    out = compute_data_quality(_mk_data([r]))
    assert "estimate_vs_duration" in [i["code"] for i in out["issues"]]
