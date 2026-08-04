"""Tests for BA/UX backlog math: function_diff badges, pic_upcoming, fl verify, gantt critical, bottleneck."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from parser.excel_parser import ParsedData, FunctionRow, PhaseData, PhaseGroup
from analyzer.function_diff import compute_function_diff
from analyzer.pic_upcoming import compute_pic_upcoming_weeks
from analyzer.fl_reimport_verify import verify_fl_reimport
from analyzer.gantt_calendar import compute_gantt_calendar
from analyzer.dashboard_engine import DashboardEngine


def _row(ma, module, phases: dict[str, PhaseData], **meta) -> FunctionRow:
    m = {"ma_cn": ma, "ten_cn": f"CN {ma}", "module": module, **meta}
    return FunctionRow(row_num=1, meta=m, phases=phases)


def _data(rows, phases=("Analysis", "Dev", "UAT")) -> ParsedData:
    pgs = [PhaseGroup(name=p, attributes={}) for p in phases]
    modules = sorted({r.meta.get("module") or "" for r in rows})
    return ParsedData(
        headers={},
        meta_columns={},
        phase_groups=pgs,
        rows=rows,
        all_phases=list(phases),
        all_modules=modules,
        all_processes=[],
        all_pics=[],
    )


TODAY = date(2026, 7, 28)


class TestFunctionDiffBadges:
    def test_status_rollback_and_pic_changed(self):
        prev = _data([
            _row("A1", "MOD", {
                "Analysis": PhaseData(status="Closed", pics=["Alice"]),
                "Dev": PhaseData(status="In-progress", pics=["Bob"], end_date=TODAY + timedelta(days=5)),
            }),
        ])
        cur = _data([
            _row("A1", "MOD", {
                "Analysis": PhaseData(status="Closed", pics=["Alice"]),
                "Dev": PhaseData(status="Open", pics=["Carol"], end_date=TODAY + timedelta(days=5)),
            }),
            _row("B2", "MOD", {
                "Analysis": PhaseData(status="Open", pics=["Dan"]),
            }),
        ])
        out = compute_function_diff(cur, prev)
        assert out["counts"]["added"] == 1
        assert out["counts"]["status_rollback"] >= 1
        assert out["counts"]["pic_changed"] >= 1
        assert out["badges"]["added"] == 1
        assert out["badges"]["status_rollback"] >= 1
        assert out["badges"]["pic_changed"] >= 1
        assert any(x.get("direction") == "backward" for x in out["status_rollback"])


class TestPicUpcoming:
    def test_counts_due_in_next_weeks(self):
        mon = date(2026, 7, 27)  # Monday of week containing TODAY
        rows = [
            _row("A1", "M", {
                "Dev": PhaseData(
                    status="In-progress",
                    pics=["Alice"],
                    start_date=mon,
                    end_date=mon + timedelta(days=2),
                ),
            }),
            _row("A2", "M", {
                "Dev": PhaseData(
                    status="Closed",
                    pics=["Alice"],
                    end_date=mon + timedelta(days=1),
                ),
            }),
            _row("A3", "M", {
                "Dev": PhaseData(
                    status="Assigned",
                    pics=["Bob"],
                    end_date=mon + timedelta(weeks=2),
                ),
            }),
        ]
        out = compute_pic_upcoming_weeks(_data(rows), weeks=4, today=TODAY)
        assert "Alice" in out["pics"]
        assert out["totals"]["by_pic"]["Alice"] == 1
        assert out["totals"]["by_pic"]["Bob"] == 1
        assert out["totals"]["grand"] == 2


class TestFlReimportVerify:
    def test_fixed_vs_still_empty(self):
        prev = _data([
            _row("A1", "M", {
                "Dev": PhaseData(status="", pics=[]),
            }),
        ])
        cur = _data([
            _row("A1", "M", {
                "Dev": PhaseData(status="In-progress", pics=["Alice"]),
            }),
        ])
        # Baseline yellow cells from "previous issues"
        overdue = [{"ma_cn": "A1", "phase": "Dev", "days_overdue": 3}]
        unassigned = [{"ma_cn": "A1", "phase": "Dev"}]
        report = verify_fl_reimport(
            prev, cur,
            overdue_list=overdue,
            unassigned_list=unassigned,
        )
        assert report["has_baseline"]
        assert report["summary"]["fixed"] >= 1
        assert report["summary"]["still_empty"] == 0


class TestGanttCriticalPath:
    def test_marks_longest_unfinished_row(self):
        rows = [
            _row("EARLY", "M1", {
                "Analysis": PhaseData(
                    status="Closed",
                    start_date=TODAY - timedelta(days=30),
                    end_date=TODAY - timedelta(days=20),
                ),
                "Dev": PhaseData(
                    status="In-progress",
                    start_date=TODAY - timedelta(days=10),
                    end_date=TODAY + timedelta(days=5),
                ),
            }),
            _row("LATE", "M2", {
                "Analysis": PhaseData(
                    status="Closed",
                    start_date=TODAY - timedelta(days=40),
                    end_date=TODAY - timedelta(days=30),
                ),
                "Dev": PhaseData(
                    status="In-progress",
                    start_date=TODAY - timedelta(days=5),
                    end_date=TODAY + timedelta(days=40),
                ),
            }),
        ]
        out = compute_gantt_calendar(_data(rows), group_by="function", today=TODAY)
        crit = [r for r in out["rows"] if r.get("on_critical_path")]
        assert len(crit) == 1
        assert "LATE" in crit[0]["name"]
        assert any(s.get("critical") for s in crit[0]["segments"])


class TestModuleRemainingAndBottleneck:
    def test_remaining_and_bottleneck(self):
        rows = [
            _row("A1", "MOD1", {
                "Analysis": PhaseData(status="Closed", end_date=TODAY - timedelta(days=10)),
                "Dev": PhaseData(status="In-progress", end_date=TODAY - timedelta(days=1), pics=["A"]),
                "UAT": PhaseData(status="Open"),
            }),
            _row("A2", "MOD1", {
                "Analysis": PhaseData(status="Closed"),
                "Dev": PhaseData(status="Closed"),
                "UAT": PhaseData(status="Closed"),
            }),
            _row("B1", "MOD2", {
                "Analysis": PhaseData(status="Closed"),
                "Dev": PhaseData(status="Closed"),
                "UAT": PhaseData(status="Closed"),
            }),
        ]
        engine = DashboardEngine(today=TODAY)
        metrics = engine.compute_all(_data(rows))
        mo = {r["module"]: r for r in metrics["module_overview"]}
        assert mo["MOD1"]["remaining"] == 1
        assert mo["MOD2"]["remaining"] == 0
        # Drill scope=remaining phải khớp số Còn lại
        from analyzer.drill_down import drill_down
        rem_items = drill_down(_data(rows), "module", {"module": "MOD1", "scope": "remaining"}, TODAY)
        all_items = drill_down(_data(rows), "module", {"module": "MOD1", "scope": "all"}, TODAY)
        assert len(rem_items) == mo["MOD1"]["remaining"] == 1
        assert rem_items[0]["ma_cn"] == "A1"
        assert rem_items[0]["is_remaining"] is True
        assert len(all_items) == 2
        bn = metrics["phase_status_matrix"].get("bottleneck") or {}
        assert "Dev" in bn
        # MOD1 stuck on Dev (overdue) → at least 1
        assert bn["Dev"] >= 1

    def test_risk_level_not_flagged_by_single_stalled(self):
        """1 stalled / module gần xong → không thành risk (dùng % chứ không count>0)."""
        # 10 function: 9 fully closed, 1 remaining+stalled-ish → stalled_pct=10% → warning max, not risk
        rows = []
        for i in range(9):
            rows.append(_row(f"C{i}", "APP", {
                "Analysis": PhaseData(status="Closed"),
                "Dev": PhaseData(status="Closed"),
                "UAT": PhaseData(status="Closed"),
            }))
        rows.append(_row("OPEN1", "APP", {
            "Analysis": PhaseData(status="Closed", end_date=TODAY - timedelta(days=20)),
            "Dev": PhaseData(status="Open", end_date=TODAY - timedelta(days=5)),
            "UAT": PhaseData(status=""),
        }))
        engine = DashboardEngine(today=TODAY)
        metrics = engine.compute_all(_data(rows))
        app = next(r for r in metrics["module_overview"] if r["module"] == "APP")
        assert app["remaining"] == 1
        assert app["stalled_count"] >= 1
        assert app["stalled_pct"] <= 20
        assert app["risk_level"] in ("safe", "warning")  # không phải risk chỉ vì 1 stalled
        assert app["risk_level"] != "risk"
