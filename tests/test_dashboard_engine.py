"""Tests cho analyzer.dashboard_engine."""
from datetime import date

import pytest

from analyzer.dashboard_engine import DashboardEngine


def test_compute_all_returns_all_sections(metrics):
    """compute_all trả về đủ tất cả metric section."""
    expected = {
        "structure", "summary", "module_overview", "phase_status_matrix",
        "progress_by_task_type", "pic_workload", "overdue_list",
        "priority_breakdown", "complexity_breakdown", "fit_gap_analysis",
        "giai_doan_progress", "phase_progress_stacked",
        "unassigned_tasks", "duration_analysis", "stalled_tasks",
        "risk_scores", "effort_analysis", "process_analysis", "timeline_data",
    }
    assert expected.issubset(metrics.keys())


def test_summary_total_functions(metrics):
    """Summary đếm đúng total_functions."""
    assert metrics["summary"]["total_functions"] == 6


def test_summary_overdue_semantics(metrics):
    """
    Function unique có overdue:
      - Row 2 (TMS.FR.02): UAT In-progress, To 5d trước → overdue
      - Row 6 (ESS.FR.10): Analysis In-progress, End 20d trước → overdue
    → 2 function
    """
    assert metrics["summary"]["total_overdue"] == 2
    # Phase-level ít nhất phải bằng function-level
    assert metrics["summary"]["total_overdue_records"] >= 2


def test_summary_last_phase_name(metrics):
    """last_phase_name có giá trị (là 'UAT' vì file mẫu có Analysis-Dev-UAT)."""
    assert metrics["summary"]["last_phase_name"] == "UAT"


def test_summary_unassigned_semantics(metrics):
    """
    Function unique có unassigned:
      - Row 3 (HR.FR.05): Dev Open, no PIC
    → ít nhất 1 function unassigned
    """
    assert metrics["summary"]["unassigned_count"] >= 1
    assert metrics["summary"]["unassigned_records"] >= 1


def test_summary_high_risk_count(metrics):
    """High-risk >= 50 điểm. Row 2, 4, 6 đều có nhiều yếu tố → high risk."""
    assert metrics["summary"]["high_risk_count"] >= 2


def test_module_overview_progress_calculation(metrics):
    """
    TMS module có 2 function × 3 phase (Analysis/Dev/UAT) = 6 records.
    Weighted_all formula: closed_records / (rows × phases).
    - Row 1 (INV): Analysis Closed, Dev Closed, UAT Closed = 3 Closed
    - Row 2 (SO):  Analysis Closed, Dev Closed, UAT In-progress = 2 Closed
    → 5/6 = 83.33%
    """
    tms = next(m for m in metrics["module_overview"] if m["module"] == "TMS")
    assert tms["total"] == 2
    assert tms["progress_pct"] == pytest.approx(83.33, abs=0.01)


def test_module_active_phase_completion(metrics):
    """Module HR chỉ có Analysis Closed, Dev Open → active_phase = 'Dev'."""
    hr = next(m for m in metrics["module_overview"] if m["module"] == "HR")
    assert hr["active_phase"] == "Dev"


def test_module_overdue_count_consistency(metrics):
    """Tổng overdue_count của modules = summary.total_overdue."""
    total = sum(m["overdue_count"] for m in metrics["module_overview"])
    assert total == metrics["summary"]["total_overdue"]


def test_overdue_list_has_days_overdue(metrics):
    """Mỗi item overdue có days_overdue > 0."""
    for item in metrics["overdue_list"]:
        assert item["days_overdue"] > 0
        assert item["status"] not in ("Closed", "Cancelled")


def test_overdue_multi_pic_stored_as_list(metrics):
    """Row 2 UAT có multi-PIC → pic field là list."""
    tms02 = [i for i in metrics["overdue_list"]
             if i["ma_cn"] == "TMS.FR.02" and i["phase"] == "UAT"]
    if tms02:
        assert isinstance(tms02[0]["pic"], list)
        assert len(tms02[0]["pic"]) >= 2


def test_unassigned_flag_overdue(metrics):
    """Unassigned items có field is_overdue (bool)."""
    for u in metrics["unassigned_tasks"]:
        assert "is_overdue" in u
        assert isinstance(u["is_overdue"], bool)


def test_duration_analysis_has_scatter_and_distribution(metrics):
    """Duration analysis có đủ scatter, distribution, items, summary."""
    d = metrics["duration_analysis"]
    assert "scatter" in d
    assert "distribution" in d
    assert "items" in d
    assert "summary" in d
    assert "threshold_days" in d


def test_stalled_tasks_funnel_has_all_phases(metrics):
    """Funnel bao phủ tất cả phase."""
    st = metrics["stalled_tasks"]
    phases_in_funnel = {f["phase"] for f in st["funnel"]}
    assert "Analysis" in phases_in_funnel


def test_risk_scores_sorted_desc(metrics):
    """Risk scores được sort giảm dần."""
    scores = [r["risk_score"] for r in metrics["risk_scores"]]
    assert scores == sorted(scores, reverse=True)


def test_risk_score_range(metrics):
    """Risk score trong khoảng 0-100."""
    for r in metrics["risk_scores"]:
        assert 0 <= r["risk_score"] <= 100


def test_effort_analysis_totals(metrics):
    """Effort tổng closed + remaining = tổng estimated."""
    e = metrics["effort_analysis"]
    assert e["total_closed_mh"] + e["remaining_mh"] == pytest.approx(e["total_estimated"], abs=0.01)


def test_pic_workload_sorted(metrics):
    """PIC workload sort theo total_tasks giảm dần."""
    tasks = [p["total_tasks"] for p in metrics["pic_workload"]]
    assert tasks == sorted(tasks, reverse=True)


def test_process_analysis_has_all_processes(metrics):
    """Process analysis liệt kê được các quy trình."""
    processes = {p["process"] for p in metrics["process_analysis"]}
    assert any("TMS.BP.01" in p for p in processes)


def test_timeline_data_has_modules_and_phases(metrics):
    """Timeline có đủ modules và phases."""
    t = metrics["timeline_data"]
    assert len(t["modules"]) > 0
    assert len(t["phases"]) > 0
    assert "today" in t


def test_timeline_data_has_function_level(metrics):
    """
    Bug 1 (Gantt rework): timeline_data phải trả function-level detail
    (`functions_by_module`) để render mỗi function 1 row + segment theo phase.
    """
    t = metrics["timeline_data"]
    assert "functions_by_module" in t
    assert "total_functions" in t
    fbm = t["functions_by_module"]
    # Ít nhất module TMS phải có function
    assert "TMS" in fbm
    tms_funcs = fbm["TMS"]
    assert len(tms_funcs) >= 2

    # Function detail phải có các key cần cho Gantt
    for f in tms_funcs:
        assert "ma_cn" in f
        assert "ten_cn" in f
        assert "has_overdue" in f
        assert "phases" in f
        for seg in f["phases"]:
            assert "name" in seg
            assert "status" in seg or seg.get("start") or seg.get("end")
            assert "overdue" in seg

    # Gantt groupBy process: functions_by_process + processes list
    assert "functions_by_process" in t
    assert "processes" in t
    assert isinstance(t["functions_by_process"], dict)
    assert len(t["functions_by_process"]) >= 1
    for proc, flist in t["functions_by_process"].items():
        assert isinstance(proc, str)
        assert isinstance(flist, list)
        for f in flist:
            assert "module" in f
            assert "ma_cn" in f
            assert "pics" in seg

    # Function overdue phải xếp trước (sort key)
    tms_ordered = [f["has_overdue"] for f in tms_funcs]
    # True (overdue) đứng trước False → dạng [T,T,F,F...] tăng dần False
    assert tms_ordered == sorted(tms_ordered, reverse=True)


def test_metrics_json_serializable(metrics):
    """Toàn bộ metrics có thể serialize JSON."""
    import json
    json.dumps(metrics, default=str)  # Không được raise


def test_empty_rows_handled(tmp_path):
    """DashboardEngine không crash khi rows rỗng."""
    from parser.excel_parser import ParsedData
    empty_data = ParsedData(
        headers={}, meta_columns={}, phase_groups=[], rows=[],
        all_modules=[], all_phases=[], all_pics=[], all_statuses=[],
        all_priorities=[], all_complexities=[], all_giai_doan=[],
    )
    m = DashboardEngine().compute_all(empty_data)
    assert m["summary"]["total_functions"] == 0
    assert m["summary"]["total_overdue"] == 0
