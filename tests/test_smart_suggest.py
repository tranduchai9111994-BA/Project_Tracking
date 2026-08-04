"""Tests cho analyzer.smart_suggest (A7, C1-C3)."""
from datetime import date, timedelta

from parser.excel_parser import ParsedData, PhaseGroup, FunctionRow, PhaseData
from analyzer.smart_suggest import compute_smart_suggestions


def _data_with_ending_functions(n: int, today: date, days_ahead: int = 5) -> ParsedData:
    rows = []
    for i in range(n):
        rows.append(FunctionRow(
            row_num=i + 2,
            meta={"ma_cn": f"FR.{i:02d}", "module": "PR"},
            phases={"Dev": PhaseData(status="Open", end_date=today + timedelta(days=days_ahead))},
        ))
    return ParsedData(
        headers={}, meta_columns={}, rows=rows,
        phase_groups=[PhaseGroup(name="Dev", attributes={})],
        all_phases=["Dev"], all_modules=["PR"],
    )


def test_returns_phase_and_progress(metrics):
    result = compute_smart_suggestions({"metrics": metrics})
    assert "suggestions" in result
    assert result["project_phase"] in ("early", "mid", "late")
    assert result["progress_pct"] == round(metrics["summary"]["overall_progress_pct"], 1)


def test_high_priority_sorted_first():
    metrics = {
        "summary": {
            "overall_progress_pct": 50,
            "total_overdue": 20,
            "high_risk_count": 30,
            "dq_high_count": 10,
        }
    }
    result = compute_smart_suggestions({"metrics": metrics})
    prios = [s["priority"] for s in result["suggestions"]]
    # tất cả high đứng trước medium
    first_medium = next((i for i, p in enumerate(prios) if p == "medium"), len(prios))
    assert all(p == "high" for p in prios[:first_medium])
    ids = [s["section_id"] for s in result["suggestions"]]
    assert "section-aging-wip" in ids
    assert "section-risk" in ids
    assert "section-dataquality" in ids


def test_late_phase_suggests_uat_and_golive():
    metrics = {"summary": {"overall_progress_pct": 85}}
    result = compute_smart_suggestions({"metrics": metrics})
    assert result["project_phase"] == "late"
    ids = {s["section_id"] for s in result["suggestions"]}
    assert "section-uat-quality" in ids
    assert "section-forecast-gantt" in ids


def test_early_phase_suggests_scope_and_rlog():
    metrics = {"summary": {"overall_progress_pct": 10}}
    result = compute_smart_suggestions({"metrics": metrics})
    assert result["project_phase"] == "early"
    ids = {s["section_id"] for s in result["suggestions"]}
    assert "section-scope-creep" in ids
    assert "section-rlog" in ids


def test_missing_metrics_defaults_to_early_no_crash():
    result = compute_smart_suggestions({})
    assert result["project_phase"] == "early"
    assert result["progress_pct"] == 0.0


def test_c1_suggests_pic_upcoming_when_many_functions_ending_soon():
    today = date(2026, 8, 3)
    data = _data_with_ending_functions(15, today, days_ahead=5)
    state = {"metrics": {"summary": {"overall_progress_pct": 50}}, "data": data}
    result = compute_smart_suggestions(state, today=today)
    ids = {s["section_id"] for s in result["suggestions"]}
    assert "section-pic-upcoming" in ids


def test_c1_no_suggestion_when_few_functions_ending_soon():
    today = date(2026, 8, 3)
    data = _data_with_ending_functions(3, today, days_ahead=5)
    state = {"metrics": {"summary": {"overall_progress_pct": 50}}, "data": data}
    result = compute_smart_suggestions(state, today=today)
    ids = {s["section_id"] for s in result["suggestions"]}
    assert "section-pic-upcoming" not in ids


def test_c1_ignores_functions_ending_beyond_window():
    today = date(2026, 8, 3)
    data = _data_with_ending_functions(15, today, days_ahead=30)
    state = {"metrics": {"summary": {"overall_progress_pct": 50}}, "data": data}
    result = compute_smart_suggestions(state, today=today)
    ids = {s["section_id"] for s in result["suggestions"]}
    assert "section-pic-upcoming" not in ids


def test_c2_suggests_function_diff_when_dq_high():
    metrics = {"summary": {"overall_progress_pct": 50, "total_functions": 100, "dq_affected_rows": 10}}
    result = compute_smart_suggestions({"metrics": metrics})
    ids = {s["section_id"] for s in result["suggestions"]}
    assert "section-function-diff" in ids


def test_c2_no_suggestion_when_dq_low():
    metrics = {"summary": {"overall_progress_pct": 50, "total_functions": 100, "dq_affected_rows": 2}}
    result = compute_smart_suggestions({"metrics": metrics})
    ids = {s["section_id"] for s in result["suggestions"]}
    assert "section-function-diff" not in ids


def test_c2_pct_never_exceeds_100_when_issue_count_gt_functions():
    # dq_affected_rows lỗi logic không thể > total_functions, nhưng vẫn clamp
    # phòng trường hợp dữ liệu cũ / test giả lập sai để % không bao giờ > 100.
    metrics = {"summary": {"overall_progress_pct": 50, "total_functions": 10, "dq_affected_rows": 999}}
    result = compute_smart_suggestions({"metrics": metrics})
    hit = next(s for s in result["suggestions"] if s["section_id"] == "section-function-diff")
    assert "100%" in hit["reason"]


def test_c3_suggests_burndown_when_overdue_trend_increasing():
    # progress=50 (mid) tự nó cũng gợi ý section-burndown → verify dedup không lặp.
    metrics = {"summary": {"overall_progress_pct": 50}}
    result = compute_smart_suggestions({"metrics": metrics}, overdue_history=[5, 10, 15])
    ids = [s["section_id"] for s in result["suggestions"]]
    assert "section-burndown" in ids
    assert ids.count("section-burndown") == 1


def test_c3_no_suggestion_when_overdue_trend_flat():
    metrics = {"summary": {"overall_progress_pct": 10}}
    result = compute_smart_suggestions({"metrics": metrics}, overdue_history=[5, 5, 5])
    ids = {s["section_id"] for s in result["suggestions"]}
    assert "section-burndown" not in ids


def test_c3_no_suggestion_when_history_too_short():
    metrics = {"summary": {"overall_progress_pct": 10}}
    result = compute_smart_suggestions({"metrics": metrics}, overdue_history=[5, 10])
    ids = {s["section_id"] for s in result["suggestions"]}
    assert "section-burndown" not in ids
