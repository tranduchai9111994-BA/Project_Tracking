"""
Regression: local Module filter section Đình trệ phải scope funnel/transitions/table.

Dùng synthetic multi-module data (rule deadline End đã quá) — không phụ thuộc
số lượng stalled cũ trên mphg.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import pytest

from analyzer.dashboard_engine import DashboardEngine
from app import PAYLOAD_LIMITS, _trim_payload
from parser.excel_parser import FunctionRow, PhaseData, PhaseGroup, ParsedData


TODAY = date(2026, 7, 30)
PAST = TODAY - timedelta(days=7)
PHASES = ["Analysis", "Dev", "Golive"]


def _row(ma: str, module: str, *, waiting_end: date | None = PAST) -> FunctionRow:
    return FunctionRow(
        row_num=1,
        meta={"ma_cn": ma, "ten_cn": ma, "module": module, "priority": "Must-have"},
        phases={
            "Analysis": PhaseData(status="Closed", end_date=PAST - timedelta(days=10)),
            "Dev": PhaseData(status="Open", end_date=waiting_end),
            "Golive": PhaseData(status=None),
        },
    )


def _metrics(n_hr: int = 3, n_app: int = 2, n_future: int = 1) -> dict:
    rows = [_row(f"HR-{i}", "HR") for i in range(n_hr)]
    rows += [_row(f"APP-{i}", "APP") for i in range(n_app)]
    # Future End — không vào stalled
    rows += [
        _row(f"FUT-{i}", "APP", waiting_end=TODAY + timedelta(days=14))
        for i in range(n_future)
    ]
    data = ParsedData(
        headers={},
        meta_columns={},
        phase_groups=[PhaseGroup(name=n) for n in PHASES],
        rows=rows,
        all_phases=list(PHASES),
        all_modules=["APP", "HR"],
    )
    return DashboardEngine(today=TODAY).compute_all(data)


def _derive_funnel(metrics: dict, selected_modules: list[str]) -> list[dict]:
    """Mirror FE _stalledDerivedFunnel."""
    data = metrics.get("stalled_tasks") or {}
    phases = data.get("phases") or [f["phase"] for f in (data.get("funnel") or [])]
    if not selected_modules:
        return list(data.get("funnel") or [])
    matrix = (metrics.get("phase_status_matrix") or {}).get("data") or {}
    out = []
    for phase in phases:
        closed = 0
        for mod in selected_modules:
            cell = (matrix.get(mod) or {}).get(phase) or {}
            closed += int(cell.get("Closed") or 0)
        out.append({"phase": phase, "closed": closed})
    return out


def _derive_transitions(items: list[dict]) -> dict[tuple[str, str], int]:
    """Mirror FE _stalledDerivedTransitions → Counter."""
    c: Counter = Counter()
    for i in items:
        c[(i.get("completed_phase") or "", i.get("waiting_phase") or "")] += 1
    return dict(c)


def _filter_items(items: list[dict], modules: list[str]) -> list[dict]:
    s = {m.strip() for m in modules}
    return [i for i in items if str(i.get("module") or "").strip() in s]


@pytest.fixture
def multi_metrics():
    return _metrics()


def test_payload_stalled_limit_keeps_all_items():
    """Trim không cắt stalled khi dưới PAYLOAD_LIMITS['stalled_items']."""
    # Tạo nhiều hơn limit cũ (200) nhưng dưới limit hiện tại — regression trim.
    n = min(PAYLOAD_LIMITS["stalled_items"] - 10, 250)
    assert n > 200, "cần limit stalled_items > 200 để regression có ý nghĩa"
    rows = [_row(f"M-{i}", "APP" if i % 2 == 0 else "HR") for i in range(n)]
    data = ParsedData(
        headers={},
        meta_columns={},
        phase_groups=[PhaseGroup(name=p) for p in PHASES],
        rows=rows,
        all_phases=list(PHASES),
        all_modules=["APP", "HR"],
    )
    metrics = DashboardEngine(today=TODAY).compute_all(data)
    st = metrics["stalled_tasks"]
    n_all = len(st["items"])
    assert n_all == n
    n_app = sum(1 for i in st["items"] if i.get("module") == "APP")

    trimmed = _trim_payload(metrics)
    t_items = trimmed["stalled_tasks"]["items"]
    n_app_trim = sum(1 for i in t_items if i.get("module") == "APP")
    assert n_app_trim == n_app
    assert len(t_items) == n_all


def test_app_vs_all_funnel_and_transitions(multi_metrics):
    """Module=APP: funnel Closed + transitions + table count phải nhỏ hơn all."""
    st = multi_metrics["stalled_tasks"]
    items = st["items"]
    funnel_all = _derive_funnel(multi_metrics, [])
    funnel_app = _derive_funnel(multi_metrics, ["APP"])
    items_app = _filter_items(items, ["APP"])
    trans_all = _derive_transitions(items)
    trans_app = _derive_transitions(items_app)

    # 3 HR + 2 APP past End + 1 future APP (rule mới: không yêu cầu End đã quá)
    assert len(items) == 6
    assert len(items_app) == 3
    assert len(items_app) < len(items)

    all_analysis = next(f["closed"] for f in funnel_all if f["phase"] == "Analysis")
    app_analysis = next(f["closed"] for f in funnel_app if f["phase"] == "Analysis")
    assert all_analysis == 6  # gồm cả row future (Analysis Closed)
    assert app_analysis == 3  # 2 stalled APP + 1 future APP
    assert app_analysis < all_analysis

    assert sum(trans_all.values()) == len(items)
    assert sum(trans_app.values()) == len(items_app)
    assert trans_all == {("Analysis", "Dev"): 6}
    assert trans_app == {("Analysis", "Dev"): 3}
    assert {i["module"] for i in items_app} == {"APP"}


def test_dashboard_js_wires_local_badge_and_override():
    """FE phải có badge cục bộ + onChange truyền arr vào render charts."""
    root = Path(__file__).resolve().parents[1]
    js = (root / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
    html = (root / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'id="stalledScopeBanner"' in html
    assert "stalled-scope" in html
    assert "Chỉ đình trệ khi phase chờ đã quá hạn End" in html
    assert "function _updateStalledScopeBanner(" in js
    assert "Đang lọc Module=" in js
    assert "lọc cục bộ section" in js
    assert "renderStalledChartsAndTable(arr)" in js
    assert "openStalledDrillDown" in js
    assert "stalled-scope" in js
