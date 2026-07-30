"""
Regression: local Module filter section Đình trệ phải scope funnel/transitions/table.

Reproduce logic FE (_stalledDerivedFunnel / transitions từ items) bằng Python
trên data mphg (có Module APP) hoặc sample fixture.
"""
from __future__ import annotations

import os
from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from analyzer.dashboard_engine import DashboardEngine
from app import PAYLOAD_LIMITS, _trim_payload
from parser.excel_parser import FunctionListParser

MPHG_XLSX = Path(__file__).resolve().parents[1] / "uploads" / "projects" / "mphg" / "current.xlsx"


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


@pytest.fixture(scope="module")
def mphg_metrics():
    if not MPHG_XLSX.exists():
        pytest.skip("mphg current.xlsx không có — skip verify APP")
    data = FunctionListParser().parse(str(MPHG_XLSX))
    return DashboardEngine(today=date(2026, 7, 30)).compute_all(data)


def test_payload_stalled_limit_keeps_full_mphg(mphg_metrics):
    """Trim không được cắt mất APP items (trước đây limit=200 → 15/21 APP)."""
    st = mphg_metrics["stalled_tasks"]
    n_all = len(st["items"])
    n_app = sum(1 for i in st["items"] if i.get("module") == "APP")
    assert n_all > 200, "fixture mphg cần >200 stalled để bắt regression trim"
    assert n_app >= 21

    trimmed = _trim_payload(mphg_metrics)
    t_items = trimmed["stalled_tasks"]["items"]
    n_app_trim = sum(1 for i in t_items if i.get("module") == "APP")
    assert n_app_trim == n_app, (
        f"Sau trim APP còn {n_app_trim}/{n_app} — limit={PAYLOAD_LIMITS['stalled_items']}"
    )
    assert len(t_items) == n_all


def test_app_vs_all_funnel_and_transitions(mphg_metrics):
    """Module=APP: funnel Closed + transitions + table count phải nhỏ hơn all."""
    st = mphg_metrics["stalled_tasks"]
    items = st["items"]
    funnel_all = _derive_funnel(mphg_metrics, [])
    funnel_app = _derive_funnel(mphg_metrics, ["APP"])
    items_app = _filter_items(items, ["APP"])
    trans_all = _derive_transitions(items)
    trans_app = _derive_transitions(items_app)

    assert len(items_app) == 21
    assert len(items_app) < len(items)

    # Funnel ALL Analysis Closed >> APP
    all_analysis = next(f["closed"] for f in funnel_all if f["phase"] == "Analysis")
    app_analysis = next(f["closed"] for f in funnel_app if f["phase"] == "Analysis")
    assert all_analysis == 353
    assert app_analysis == 13
    assert app_analysis < all_analysis

    # Transitions: sum counts == số rows
    assert sum(trans_all.values()) == len(items)
    assert sum(trans_app.values()) == len(items_app)
    assert trans_app == {
        ("Analysis", "Dev"): 6,
        ("Config UAT", "Document"): 5,
        ("Dev", "Config Local"): 4,
        ("UAT", "Golive"): 6,
    }

    # Mọi row APP
    assert {i["module"] for i in items_app} == {"APP"}


def test_dashboard_js_wires_local_badge_and_override():
    """FE phải có badge cục bộ + onChange truyền arr vào render charts."""
    root = Path(__file__).resolve().parents[1]
    js = (root / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")
    html = (root / "templates" / "index.html").read_text(encoding="utf-8")
    assert 'id="stalledScopeBanner"' in html
    assert "stalled-scope" in html
    assert "function _updateStalledScopeBanner(" in js
    assert "Đang lọc Module=" in js
    assert "lọc cục bộ section" in js
    assert "renderStalledChartsAndTable(arr)" in js
    assert "openStalledDrillDown" in js
    assert "stalled-scope" in js
