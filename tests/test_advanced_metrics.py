"""Tests cho advanced_metrics + project_store."""
from datetime import date, timedelta

from analyzer.advanced_metrics import (
    compute_burndown_velocity,
    compute_sla_violations,
    compute_slow_heatmap,
    compute_dependency_blockers,
    compute_baseline_variance,
    compute_capacity_load,
)
from analyzer.project_store import (
    save_capacity,
    load_capacity,
    upsert_saved_view,
    load_saved_views,
    append_upload_history,
    load_upload_history,
    save_project_settings,
    load_project_settings,
)
from parser.excel_parser import ParsedData, FunctionRow, PhaseData, PhaseGroup


def _sample_data(today: date) -> ParsedData:
    past = today - timedelta(days=10)
    week_ago = today - timedelta(days=7)
    rows = [
        FunctionRow(
            row_num=2,
            meta={
                "ma_cn": "A.01",
                "ten_cn": "Func A",
                "module": "PR",
                "priority": "Must-have",
                "function_lq": "B.01",
                "last_updated": week_ago.isoformat(),
            },
            phases={
                "Analysis": PhaseData(
                    status="In-progress",
                    end_date=past,
                    pics=["Alice"],
                    estimate_mh=16,
                ),
            },
        ),
        FunctionRow(
            row_num=3,
            meta={
                "ma_cn": "B.01",
                "ten_cn": "Func B",
                "module": "PR",
                "priority": "Should-have",
                "last_updated": week_ago.isoformat(),
            },
            phases={
                "Analysis": PhaseData(
                    status="Open",
                    end_date=past,
                    pics=["Bob"],
                    estimate_mh=8,
                    extra={"Planned": past.isoformat(), "Actual": today.isoformat()},
                ),
                "Dev": PhaseData(status="Closed", end_date=week_ago, pics=["Bob"], estimate_mh=8),
            },
        ),
    ]
    return ParsedData(
        headers={},
        meta_columns={},
        phase_groups=[PhaseGroup(name="Analysis", attributes={}), PhaseGroup(name="Dev", attributes={})],
        rows=rows,
        all_modules=["PR"],
        all_phases=["Analysis", "Dev"],
        all_pics=["Alice", "Bob"],
        all_statuses=["Open", "In-progress", "Closed"],
        all_priorities=["Must-have", "Should-have"],
        all_complexities=[],
        all_giai_doan=[],
        all_processes=[],
    )


def test_sla_finds_overdue_open(today=date(2026, 7, 28)):
    data = _sample_data(today)
    sla = compute_sla_violations(data, today, must_have_days=3, should_have_days=7)
    assert sla["total"] >= 1
    codes = {i["ma_cn"] for i in sla["items"]}
    assert "A.01" in codes


def test_slow_heatmap_has_alice(today=date(2026, 7, 28)):
    data = _sample_data(today)
    h = compute_slow_heatmap(data, today)
    assert "Alice" in h["pics"]
    assert h["heatmap"]["Alice"]["Analysis"] >= 1


def test_dependency_blocker_must_have(today=date(2026, 7, 28)):
    data = _sample_data(today)
    dep = compute_dependency_blockers(data)
    # A.01 Must-have depends on B.01; B.01 last phase Dev is Closed → may not block
    # Change: B.01 Dev not closed in another scenario — here Dev is Closed so blocker may be 0
    assert "blockers" in dep
    assert dep["edges_count"] >= 1


def test_burndown_has_closed_week(today=date(2026, 7, 28)):
    data = _sample_data(today)
    b = compute_burndown_velocity(data, today)
    assert b["total_closed_events"] >= 1
    assert len(b["weeks"]) >= 1


def test_baseline_variance(today=date(2026, 7, 28)):
    data = _sample_data(today)
    v = compute_baseline_variance(data)
    assert v["total_compared"] >= 1


def test_capacity_load(today=date(2026, 7, 28)):
    data = _sample_data(today)
    cap = {"default_md_per_week": 5.0, "pics": {"Alice": 2.0}}
    load = compute_capacity_load(data, cap, today)
    pics = {r["pic"] for r in load["by_pic"]}
    assert "Alice" in pics


def test_project_store_roundtrip(tmp_path):
    d = str(tmp_path)
    save_capacity(d, {"default_md_per_week": 4, "pics": {"X": 3}})
    c = load_capacity(d)
    assert c["default_md_per_week"] == 4
    assert c["pics"]["X"] == 3

    upsert_saved_view(d, {"name": "Lương", "modules": ["PR"], "processes": [], "pics": []})
    views = load_saved_views(d)
    assert len(views) == 1
    assert views[0]["name"] == "Lương"

    append_upload_history(d, filename="a.xlsx", row_count=10, checksum="abc")
    hist = load_upload_history(d)
    assert hist[0]["row_count"] == 10

    save_project_settings(d, {"upload_reminder_days": 14, "sla": {"must_have_days": 5}})
    s = load_project_settings(d)
    assert s["upload_reminder_days"] == 14
    assert s["sla"]["must_have_days"] == 5
