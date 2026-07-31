"""
Regression: Kanban local Module filter phải AND với global (không UNION).

Bug trước: FE mergeArray = Set(global ∪ local) → chọn Module=HR vẫn gửi
kèm mọi module global → board hiện PR/TMS/…

Contract FE `_kanbanAndCombine(global, local)` (mirror trong test):
  - cả 2 có → giao; giao rỗng → local thắng
  - chỉ 1 phía → phía đó
  - cả 2 rỗng → []
"""
from __future__ import annotations

import io

import pytest


def _kanban_and_combine(global_arr, local_arr):
    """Mirror JS `_kanbanAndCombine` — giữ sync với static/js/dashboard.js."""
    g = [str(x).strip() for x in (global_arr or []) if str(x).strip()]
    l = [str(x).strip() for x in (local_arr or []) if str(x).strip()]
    if l and g:
        g_set = set(g)
        inter = [x for x in l if x in g_set]
        return inter if inter else l
    if l:
        return l
    if g:
        return g
    return []


def _upload(client, xlsx_path, project="default"):
    with open(xlsx_path, "rb") as f:
        data = {"file": (io.BytesIO(f.read()), "test.xlsx")}
    return client.post(
        f"/api/projects/{project}/upload",
        data=data,
        content_type="multipart/form-data",
    )


def _all_cards(payload: dict) -> list[dict]:
    cards = []
    for col in payload.get("columns") or []:
        cards.extend(col.get("cards") or [])
    return cards


# ---- Unit: AND combine contract (FE mirror) ----

def test_and_combine_local_only():
    assert _kanban_and_combine([], ["HR"]) == ["HR"]


def test_and_combine_global_only():
    assert _kanban_and_combine(["PR", "TMS", "SYS"], []) == ["PR", "TMS", "SYS"]


def test_and_combine_intersect():
    """Global nhiều module + local HR (nằm trong global) → chỉ HR."""
    assert _kanban_and_combine(
        ["PR", "SYS", "TMS", "HR", "ESS"],
        ["HR"],
    ) == ["HR"]


def test_and_combine_empty_intersect_local_wins():
    """
    Screenshot bug case: global 8 module không gồm HR, local=HR.
    UNION cũ → hiện cả PR/TMS; AND đúng → chỉ HR (local thắng khi giao rỗng).
    """
    global_mods = ["PR", "SYS", "HK", "TMS", "SI", "PIT", "APP", "ESS"]
    assert "HR" not in global_mods
    assert _kanban_and_combine(global_mods, ["HR"]) == ["HR"]


def test_and_combine_both_empty():
    assert _kanban_and_combine([], []) == []


def test_and_combine_process_and_pic():
    assert _kanban_and_combine(
        ["A - x", "B - y"],
        ["A - x"],
    ) == ["A - x"]
    assert _kanban_and_combine(["SonHN6", "BaoLQ31"], ["BaoLQ31"]) == ["BaoLQ31"]


# ---- API: module filter scopes cards ----

def test_kanban_api_module_filter_hr_only(flask_client, sample_xlsx_path):
    """module=HR → mọi card đều module HR (sample có HR.FR.05)."""
    r = _upload(flask_client, sample_xlsx_path)
    assert r.status_code == 200

    r = flask_client.get("/api/projects/default/kanban?module=HR")
    assert r.status_code == 200
    data = r.get_json()
    cards = _all_cards(data)
    assert cards, "sample phải có ít nhất 1 card HR"
    assert all(c.get("module") == "HR" for c in cards)
    assert data.get("total_after_filter") == len(cards)


def test_kanban_api_module_filter_excludes_other_modules(flask_client, sample_xlsx_path):
    """module=HR không lẫn PR/TMS/SYS/ESS."""
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.get("/api/projects/default/kanban?module=HR")
    mods = {c.get("module") for c in _all_cards(r.get_json())}
    assert mods == {"HR"}


def test_kanban_api_effective_and_param_matches_combine(flask_client, sample_xlsx_path):
    """
    FE gửi param `module` = kết quả AND combine.
    Giả lập: global=[TMS,HR,PR] ∩ local=[HR] → module=HR trên wire.
    """
    _upload(flask_client, sample_xlsx_path)
    effective = _kanban_and_combine(["TMS", "HR", "PR"], ["HR"])
    assert effective == ["HR"]
    r = flask_client.get(
        "/api/projects/default/kanban",
        query_string={"module": ",".join(effective)},
    )
    assert r.status_code == 200
    assert {c["module"] for c in _all_cards(r.get_json())} == {"HR"}


def test_index_has_kanban_scope_banner(flask_client):
    """Badge «Đang lọc» container phải có trong HTML."""
    r = flask_client.get("/")
    assert r.status_code == 200
    assert b'id="kanbanScopeBanner"' in r.data
    assert b"kanban-scope" in r.data
