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
        status="In-progress", pics=["A"],
    )})
    out = compute_data_quality(_mk_data([r]))
    codes = [i["code"] for i in out["issues"]]
    assert "end_before_start" in codes


def test_end_before_start_skipped_when_closed():
    """Phase đã Closed/Cancelled — không ép sửa Start/End nữa."""
    r = _mk_row(phases={"Dev": PhaseData(
        start_date=date(2026, 5, 10), end_date=date(2026, 5, 1),
        status="Closed", pics=["A"],
    )})
    out = compute_data_quality(_mk_data([r]))
    codes = [i["code"] for i in out["issues"]]
    assert "end_before_start" not in codes


def test_closed_no_end():
    """Status=Closed nhưng thiếu End — chỉ báo khi function vẫn còn phase
    active. Nếu ALL phase đã done thì rule 06/08/2026 skip toàn bộ row.
    """
    r = _mk_row(phases={
        "Analysis": PhaseData(
            start_date=date(2026, 1, 1), end_date=None,
            status="Closed", pics=["A"],
        ),
        # Phase khác chưa done → row chưa done toàn bộ → vẫn flag closed_no_end
        "Dev": PhaseData(status="In-progress", end_date=date(2026, 2, 1), pics=["B"]),
    })
    out = compute_data_quality(_mk_data([r]))
    codes = [i["code"] for i in out["issues"]]
    assert "closed_no_end" in codes
    assert "missing_deadline" not in codes


def test_closed_no_end_skipped_when_row_fully_done():
    """Row Closed hết toàn bộ phase → không flag closed_no_end
    (rule PMO 06/08/2026: closed hết → không đếm để tránh thừa)."""
    r = _mk_row(phases={"Dev": PhaseData(
        start_date=date(2026, 1, 1), end_date=None,
        status="Closed", pics=["A"],
    )})
    out = compute_data_quality(_mk_data([r]))
    codes = [i["code"] for i in out["issues"]]
    assert "closed_no_end" not in codes
    assert out["summary"]["total_issues"] == 0


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
    """Open/Assigned (không Start) và Resolved/Pending (có Start đã đến) thiếu End → flag."""
    today = date(2026, 7, 31)
    for st in ("Open", "Assigned"):
        r = _mk_row(phases={"Dev": PhaseData(status=st, end_date=None, pics=["A"])})
        out = compute_data_quality(_mk_data([r]), today=today)
        assert "missing_deadline" in [i["code"] for i in out["issues"]], st
    # Resolved/Pending không thuộc fallback no-Start → cần Start đã đến
    for st in ("Resolved", "Pending"):
        r = _mk_row(phases={"Dev": PhaseData(
            status=st, start_date=date(2026, 7, 1), end_date=None, pics=["A"],
        )})
        out = compute_data_quality(_mk_data([r]), today=today)
        assert "missing_deadline" in [i["code"] for i in out["issues"]], st


def test_missing_deadline_blank_status_skipped():
    """Status blank + End trống → không báo missing_deadline."""
    r = _mk_row(phases={"Dev": PhaseData(status="", end_date=None, pics=["A"])})
    out = compute_data_quality(_mk_data([r]))
    assert "missing_deadline" not in [i["code"] for i in out["issues"]]


def test_missing_deadline_dedupe_functions():
    """Cùng ma_cn, 2 row thiếu End → function_count=1, records=2."""
    r1 = _mk_row(ma_cn="F99", row_num=2, phases={
        "Analysis": PhaseData(status="Open", end_date=None, pics=["A"]),
    })
    r2 = _mk_row(ma_cn="F99", row_num=3, phases={
        "Analysis": PhaseData(status="In-progress", end_date=None, pics=["B"]),
    })
    out = compute_data_quality(_mk_data([r1, r2]))
    assert out["summary"]["missing_deadline_count"] == 1
    assert out["summary"]["missing_deadline_records"] == 2
    funcs, recs = count_missing_deadlines(_mk_data([r1, r2]))
    assert (funcs, recs) == (1, 2)


def test_missing_deadline_respects_predecessor_gate():
    """Dev thiếu End nhưng Analysis chưa Closed → không báo missing_deadline."""
    r = _mk_row(phases={
        "Analysis": PhaseData(status="In-progress", end_date=date(2026, 2, 1), pics=["A"]),
        "Dev": PhaseData(status="Open", end_date=None, pics=["B"]),
    })
    out = compute_data_quality(_mk_data([r]))
    assert "missing_deadline" not in [i["code"] for i in out["issues"]]

    r2 = _mk_row(phases={
        "Analysis": PhaseData(status="Closed", end_date=date(2026, 1, 1), pics=["A"]),
        "Dev": PhaseData(status="Open", end_date=None, pics=["B"]),
    })
    out2 = compute_data_quality(_mk_data([r2]))
    assert "missing_deadline" in [i["code"] for i in out2["issues"]]


def test_blank_pic_and_deadline_respect_start_gate():
    """Start tương lai → không blank_pic / missing_deadline dù pred Closed."""
    today = date(2026, 7, 31)
    future = date(2026, 8, 15)
    r = _mk_row(phases={
        "Analysis": PhaseData(status="Closed", end_date=date(2026, 7, 1), pics=["A"]),
        "Dev": PhaseData(
            status="Open", start_date=future, end_date=None, pics=[],
        ),
    })
    out = compute_data_quality(_mk_data([r]), today=today)
    codes = [i["code"] for i in out["issues"]]
    assert "blank_pic" not in codes
    assert "missing_deadline" not in codes

    past = date(2026, 7, 20)
    r2 = _mk_row(phases={
        "Analysis": PhaseData(status="Closed", end_date=date(2026, 7, 1), pics=["A"]),
        "Dev": PhaseData(
            status="Open", start_date=past, end_date=None, pics=[],
        ),
    })
    out2 = compute_data_quality(_mk_data([r2]), today=today)
    codes2 = [i["code"] for i in out2["issues"]]
    assert "blank_pic" in codes2
    assert "missing_deadline" in codes2



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


def test_phase_overlap_config_local_uat_allowed():
    """Config Local ↔ Config UAT trùng ngày → không flag (song song hợp lệ)."""
    r = _mk_row(phases={
        "Config Local": PhaseData(
            start_date=date(2026, 7, 12), end_date=date(2026, 7, 12),
            status="Closed", pics=["A"],
        ),
        "Config UAT": PhaseData(
            start_date=date(2026, 7, 12), end_date=date(2026, 7, 12),
            status="Closed", pics=["B"],
        ),
    })
    out = compute_data_quality(_mk_data([r]))
    assert "phase_overlap" not in [i["code"] for i in out["issues"]]


def test_phase_overlap_config_local_uat_case_insensitive():
    """Biến thể case/whitespace của Config Local/UAT cũng được bỏ qua."""
    r = _mk_row(phases={
        "config  local": PhaseData(
            start_date=date(2026, 7, 12), end_date=date(2026, 7, 13),
            status="In-progress", pics=["A"],
        ),
        "CONFIG UAT": PhaseData(
            start_date=date(2026, 7, 12), end_date=date(2026, 7, 13),
            status="In-progress", pics=["B"],
        ),
    })
    out = compute_data_quality(_mk_data([r]))
    assert "phase_overlap" not in [i["code"] for i in out["issues"]]


def test_phase_overlap_analysis_dev_still_flagged():
    """Analysis ↔ Dev chồng ngày → vẫn flag phase_overlap."""
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


def test_estimate_vs_duration_flagged():
    """Estimate 800 MH trên 2 ngày → ratio > 3x → flag (phase còn active)."""
    r = _mk_row(phases={
        "Dev": PhaseData(
            start_date=date(2026, 1, 1), end_date=date(2026, 1, 2),
            status="In-progress", pics=["A"], estimate_mh=800.0,
        ),
        "UAT": PhaseData(status="Open", end_date=date(2026, 2, 1), pics=["B"]),
    })
    out = compute_data_quality(_mk_data([r]))
    assert "estimate_vs_duration" in [i["code"] for i in out["issues"]]


def test_estimate_vs_duration_ok_short_task_low_mh_pr_fr_41():
    """PR.FR.41 — Config Local 1 ngày, 1.5 MH: effort nhỏ hơn cửa sổ ngày → hợp lý."""
    r = _mk_row(ma_cn="PR.FR.41", phases={
        "Config Local": PhaseData(
            status="In-progress",
            start_date=date(2026, 1, 10), end_date=date(2026, 1, 10),
            pics=["A"], estimate_mh=1.5,
        ),
        "UAT": PhaseData(status="Open", end_date=date(2026, 2, 1), pics=["B"]),
    })
    out = compute_data_quality(_mk_data_with_phases([r]))
    est = [i for i in out["issues"] if i["code"] == "estimate_vs_duration"]
    assert est == []


def test_estimate_vs_duration_ok_low_ratio_not_flagged():
    """8 MH / 7 ngày (ratio ~0.14) — không flag vì estimate nhỏ hơn cửa sổ là OK."""
    r = _mk_row(phases={
        "Analysis": PhaseData(
            start_date=date(2026, 9, 1), end_date=date(2026, 9, 7),
            status="In-progress", pics=["A"], estimate_mh=8.0,
        ),
    })
    out = compute_data_quality(_mk_data_with_phases([r]))
    assert "estimate_vs_duration" not in [i["code"] for i in out["issues"]]


def test_estimate_vs_duration_skipped_when_row_fully_done():
    """Row đã Closed hết → skip mọi flag, kể cả estimate lệch duration."""
    r = _mk_row(phases={
        "Dev": PhaseData(
            start_date=date(2026, 1, 1), end_date=date(2026, 1, 2),
            status="Closed", pics=["A"], estimate_mh=800.0,
        ),
    })
    out = compute_data_quality(_mk_data([r]))
    assert "estimate_vs_duration" not in [i["code"] for i in out["issues"]]


def test_row_all_closed_skipped_entirely():
    """Toàn bộ phase Closed/Cancelled → không đếm bất kỳ flag DQ nào
    (rule PMO 06/08/2026 — báo tránh thừa cho function đã done).
    """
    r = _mk_row(priority="", complexity="", fit_gap="", phases={
        "Analysis": PhaseData(status="Closed", end_date=date(2026, 1, 5), pics=["A"]),
        "Dev": PhaseData(status="Cancelled", end_date=date(2026, 1, 10), pics=["B"]),
    })
    out = compute_data_quality(_mk_data([r]))
    assert out["summary"]["total_issues"] == 0
    assert out["summary"]["affected_rows"] == 0
    assert out["summary"]["clean_rows"] == 1


def test_row_all_closed_but_has_active_still_flagged():
    """Nếu vẫn còn phase active → không phải fully-done, DQ chạy bình thường."""
    r = _mk_row(priority="", phases={
        "Analysis": PhaseData(status="Closed", end_date=date(2026, 1, 5), pics=["A"]),
        "Dev": PhaseData(status="In-progress", end_date=date(2026, 2, 1), pics=["B"]),
    })
    out = compute_data_quality(_mk_data([r]))
    codes = [i["code"] for i in out["issues"]]
    assert "blank_priority" in codes


def test_duplicate_ma_cn_skipped_when_all_copies_done():
    """Nếu tất cả copies của cùng ma_cn đều Closed → không đếm duplicate."""
    r1 = _mk_row(row_num=2, ma_cn="DONE-01", phases={
        "Dev": PhaseData(status="Closed", end_date=date(2026, 1, 10), pics=["A"]),
    })
    r2 = _mk_row(row_num=5, ma_cn="DONE-01", phases={
        "Dev": PhaseData(status="Cancelled", end_date=date(2026, 1, 12), pics=["B"]),
    })
    out = compute_data_quality(_mk_data([r1, r2]))
    dups = [i for i in out["issues"] if i["code"] == "duplicate_ma_cn"]
    assert dups == []


def test_duplicate_ma_cn_kept_when_one_copy_active():
    """1 copy done, 1 copy active → chỉ flag copy active (dup chỉ đếm những
    row chưa done, đồng bộ compute_data_quality vs count_anomalies)."""
    r_done = _mk_row(row_num=2, ma_cn="DUP-02", phases={
        "Dev": PhaseData(status="Closed", end_date=date(2026, 1, 10), pics=["A"]),
    })
    r_open = _mk_row(row_num=5, ma_cn="DUP-02", phases={
        "Dev": PhaseData(status="In-progress", end_date=date(2026, 2, 1), pics=["B"]),
    })
    # 2 copies mà chỉ 1 chưa done → không còn duplicate (counter=1)
    out = compute_data_quality(_mk_data([r_done, r_open]))
    dups = [i for i in out["issues"] if i["code"] == "duplicate_ma_cn"]
    assert dups == []

    # 3 copies: 1 done + 2 chưa done → counter=2 (duplicate) → flag cho 2
    # copies chưa done, copy done vẫn skip.
    r_open2 = _mk_row(row_num=7, ma_cn="DUP-02", phases={
        "Dev": PhaseData(status="Open", end_date=date(2026, 2, 5), pics=["C"]),
    })
    out2 = compute_data_quality(_mk_data([r_done, r_open, r_open2]))
    dups2 = [i for i in out2["issues"] if i["code"] == "duplicate_ma_cn"]
    assert len(dups2) == 2
    assert {i["row_num"] for i in dups2} == {5, 7}


# ==========================================================================
# Analysis deadline gate (rule PMO 06/08/2026 — screenshot DQ TMS.FR.65/66)
# ==========================================================================

def _mk_data_with_phases(rows, phase_names=None):
    """ParsedData kèm phase_groups + all_phases để detect Analysis."""
    names = phase_names or ["Analysis", "Dev", "Config Local", "Config UAT", "Document"]
    return ParsedData(
        headers={}, meta_columns={},
        phase_groups=[PhaseGroup(name=n, attributes={}) for n in names],
        rows=rows,
        all_phases=names,
    )


def test_analysis_future_deadline_skips_entire_function():
    """Analysis End còn tương lai → không đưa function lên DQ
    (kể cả estimate lệch ở Config/Document như TMS.FR.65)."""
    today = date(2026, 8, 6)
    r = _mk_row(ma_cn="TMS.FR.65", phases={
        "Analysis": PhaseData(
            status="Assigned", start_date=date(2026, 9, 1), end_date=date(2026, 9, 7),
            pics=["A"], estimate_mh=8.0,
        ),
        "Config UAT": PhaseData(
            status="Assigned", start_date=date(2026, 9, 11), end_date=date(2026, 9, 12),
            pics=["A"], estimate_mh=2.0,
        ),
        "Document": PhaseData(
            status="Assigned", start_date=date(2026, 9, 13), end_date=date(2026, 9, 14),
            pics=["A"], estimate_mh=1.0,
        ),
    })
    out = compute_data_quality(_mk_data_with_phases([r]), today=today)
    assert out["summary"]["total_issues"] == 0
    assert [i for i in out["issues"] if i["ma_cn"] == "TMS.FR.65"] == []


def test_analysis_due_but_not_closed_only_flags_analysis():
    """Đã tới deadline Analysis nhưng chưa Closed → chỉ flag Analysis,
    không flag Config/Document/overlap phase sau."""
    today = date(2026, 9, 10)  # sau Analysis End 09/07
    r = _mk_row(ma_cn="TMS.FR.66", phases={
        "Analysis": PhaseData(
            status="Assigned", start_date=date(2026, 9, 1), end_date=date(2026, 9, 7),
            pics=["A"], estimate_mh=200.0,  # >> 7d×8h → flag Analysis
        ),
        "Dev": PhaseData(
            status="Open", start_date=date(2026, 9, 10), end_date=date(2026, 9, 20),
            pics=[], estimate_mh=0.0,
        ),
        "Config Local": PhaseData(
            status="Assigned", start_date=date(2026, 9, 20), end_date=date(2026, 9, 27),
            pics=["A"],
        ),
        "Config UAT": PhaseData(
            status="Assigned", start_date=date(2026, 9, 27), end_date=date(2026, 9, 29),
            pics=["A"], estimate_mh=2.0,
        ),
        "Document": PhaseData(
            status="Assigned", start_date=date(2026, 9, 29), end_date=date(2026, 9, 30),
            pics=["A"], estimate_mh=1.0,
        ),
    })
    out = compute_data_quality(_mk_data_with_phases([r]), today=today)
    phases = {i["phase"] for i in out["issues"]}
    # Chỉ Analysis — không Config/Document/Dev overlap
    assert phases == {"Analysis"}
    assert all(i["code"] == "estimate_vs_duration" for i in out["issues"])
    assert "phase_overlap" not in [i["code"] for i in out["issues"]]


def test_analysis_closed_full_scan_allows_later_phase_issues():
    """Analysis Closed → quét bình thường; overlap Dev∩Config được flag."""
    today = date(2026, 9, 15)
    r = _mk_row(ma_cn="OK.01", phases={
        "Analysis": PhaseData(
            status="Closed", start_date=date(2026, 8, 1), end_date=date(2026, 8, 5),
            pics=["A"],
        ),
        "Dev": PhaseData(
            status="In-progress", start_date=date(2026, 9, 10), end_date=date(2026, 9, 20),
            pics=["B"],
        ),
        "Config Local": PhaseData(
            status="Open", start_date=date(2026, 9, 18), end_date=date(2026, 9, 25),
            pics=["C"],
        ),
    })
    out = compute_data_quality(_mk_data_with_phases([r]), today=today)
    codes = [i["code"] for i in out["issues"]]
    assert "phase_overlap" in codes


def test_closed_phases_skip_estimate_and_overlap_pr_fr_47():
    """PR.FR.47 — Analysis/Document/Dev đã Closed; UAT còn mở.
    Không flag estimate lệch hay overlap trên phase đã đóng."""
    today = date(2026, 8, 7)
    r = _mk_row(ma_cn="PR.FR.47", phases={
        "Analysis": PhaseData(
            status="Closed", start_date=date(2025, 12, 1), end_date=date(2025, 12, 30),
            pics=["A"], estimate_mh=4.0,
        ),
        "Dev": PhaseData(
            status="Closed", start_date=date(2025, 12, 1), end_date=date(2025, 12, 30),
            pics=["A"],
        ),
        "Document": PhaseData(
            status="Closed", start_date=date(2025, 12, 1), end_date=date(2025, 12, 30),
            pics=["A"], estimate_mh=1.0,
        ),
        "Config UAT": PhaseData(
            status="In-progress", start_date=date(2026, 1, 1), end_date=date(2026, 1, 15),
            pics=["B"],
        ),
    })
    out = compute_data_quality(_mk_data_with_phases([r]), today=today)
    for it in out["issues"]:
        if it["code"] == "estimate_vs_duration":
            assert it["phase"] not in ("Analysis", "Document", "Dev"), it
        if it["code"] == "phase_overlap":
            assert "Analysis" not in it["phase"], it
            assert "Document" not in it["phase"], it
            assert "Dev" not in it["phase"] or "Config UAT" in it["phase"], it


def test_estimate_vs_duration_skipped_per_closed_phase():
    """Phase Closed lệch estimate — không flag dù row còn phase active."""
    r = _mk_row(phases={
        "Analysis": PhaseData(
            start_date=date(2025, 12, 1), end_date=date(2025, 12, 30),
            status="Closed", pics=["A"], estimate_mh=4.0,
        ),
        "UAT": PhaseData(status="In-progress", end_date=date(2026, 2, 1), pics=["B"]),
    })
    out = compute_data_quality(_mk_data_with_phases([r]))
    est = [i for i in out["issues"] if i["code"] == "estimate_vs_duration"]
    assert est == []


def test_phase_overlap_skipped_when_both_closed():
    """Analysis ∩ Dev cùng Closed + trùng ngày → không flag overlap."""
    r = _mk_row(phases={
        "Analysis": PhaseData(
            status="Closed", start_date=date(2025, 12, 1), end_date=date(2025, 12, 30),
            pics=["A"],
        ),
        "Dev": PhaseData(
            status="Closed", start_date=date(2025, 12, 1), end_date=date(2025, 12, 30),
            pics=["A"],
        ),
        "UAT": PhaseData(status="Open", end_date=date(2026, 3, 1), pics=["B"]),
    })
    out = compute_data_quality(_mk_data_with_phases([r]))
    overlaps = [i for i in out["issues"] if i["code"] == "phase_overlap"]
    assert not any("Analysis" in i["phase"] for i in overlaps)
    assert not any(i["phase"] == "Analysis ∩ Dev" for i in overlaps)


def test_analysis_dq_scope_helpers():
    from analyzer.data_quality import analysis_dq_scope
    today = date(2026, 8, 6)
    future = _mk_row(phases={
        "Analysis": PhaseData(status="Open", end_date=date(2026, 9, 7), pics=["A"]),
    })
    data = _mk_data_with_phases([future])
    assert analysis_dq_scope(data, future, today)[0] == "skip"

    due = _mk_row(phases={
        "Analysis": PhaseData(status="Assigned", end_date=date(2026, 8, 1), pics=["A"]),
        "Dev": PhaseData(status="Open", pics=[]),
    })
    data2 = _mk_data_with_phases([due])
    assert analysis_dq_scope(data2, due, today)[0] == "analysis_only"

    done = _mk_row(phases={
        "Analysis": PhaseData(status="Closed", end_date=date(2026, 8, 1), pics=["A"]),
        "Dev": PhaseData(status="Open", pics=["B"]),
    })
    data3 = _mk_data_with_phases([done])
    assert analysis_dq_scope(data3, done, today)[0] == "full"
