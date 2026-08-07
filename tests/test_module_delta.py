"""
Tests — delta bảng Tổng quan theo Module (analyzer/module_delta.py).

Chốt các quy ước dễ bị hiểu sai:
  - Tiến độ dùng điểm phần trăm cho chiều số lượng, phần trăm tương đối cho chiều %.
  - base = 0 → `*_delta_pct` là None (không chia 0, UI hiện "—").
  - Nhóm mới → is_new, mọi delta None (không hiện +100%).
  - Nhóm mất → vào `removed[]`, không chèn row giả.
"""
from __future__ import annotations

import io

import pytest

from analyzer.module_delta import (
    METRICS,
    POLARITY,
    compute_module_overview_delta,
)


def _row(module, *, process="", total=10, progress=50.0, overdue=2, remaining=5,
         label=None, children=None):
    r = {
        "stt": 1, "module": module, "process": process,
        "label": label or (process or module),
        "total": total, "quy_trinh_count": 1, "progress_pct": progress,
        "active_phase": "Dev", "overdue_count": overdue, "overdue_pct": 0,
        "stalled_count": 0, "stalled_pct": 0, "risk_level": "safe",
        "risk_reason": "An toàn", "remaining": remaining, "remaining_mh": 0.0,
    }
    if children is not None:
        r["children"] = children
    return r


# ------------------------------------------------------------------
# Join theo group_by
# ------------------------------------------------------------------

def test_join_by_module():
    cur = [_row("TMS", total=12, progress=60.0, overdue=1, remaining=4)]
    base = [_row("TMS", total=10, progress=50.0, overdue=2, remaining=5)]
    out = compute_module_overview_delta(cur, base, group_by="module")

    d = out["rows"][0]["delta"]
    assert d["is_new"] is False
    assert d["total_delta"] == 2
    assert d["total_delta_pct"] == 20.0
    assert d["progress_delta"] == 10.0           # điểm phần trăm
    assert d["progress_delta_pct"] == 20.0       # tương đối: 50 → 60
    assert d["overdue_delta"] == -1
    assert d["overdue_delta_pct"] == -50.0
    assert d["remaining_delta"] == -1
    assert d["remaining_delta_pct"] == -20.0
    assert d["base"]["total"] == 10


def test_join_by_process_uses_module_and_process():
    """Cùng process khác module là 2 nhóm khác nhau, không được trộn."""
    cur = [
        _row("TMS", process="P1", total=5),
        _row("HR", process="P1", total=9),
    ]
    base = [
        _row("TMS", process="P1", total=4),
        _row("HR", process="P1", total=3),
    ]
    out = compute_module_overview_delta(cur, base, group_by="process")
    by_mod = {r["module"]: r["delta"] for r in out["rows"]}
    assert by_mod["TMS"]["total_delta"] == 1
    assert by_mod["HR"]["total_delta"] == 6


def test_join_by_both_covers_children():
    cur = [_row("TMS", total=10, children=[_row("TMS", process="P1", total=6)])]
    base = [_row("TMS", total=8, children=[_row("TMS", process="P1", total=4)])]
    out = compute_module_overview_delta(cur, base, group_by="both")

    parent = out["rows"][0]
    assert parent["delta"]["total_delta"] == 2
    assert parent["children"][0]["delta"]["total_delta"] == 2


def test_input_rows_not_mutated():
    cur = [_row("TMS", children=[_row("TMS", process="P1")])]
    base = [_row("TMS", children=[_row("TMS", process="P1")])]
    compute_module_overview_delta(cur, base, group_by="both")
    assert "delta" not in cur[0]
    assert "delta" not in cur[0]["children"][0]


# ------------------------------------------------------------------
# Edge case số học
# ------------------------------------------------------------------

def test_zero_base_gives_none_pct_not_infinity():
    cur = [_row("TMS", total=5, overdue=3, remaining=2, progress=10.0)]
    base = [_row("TMS", total=5, overdue=0, remaining=0, progress=0.0)]
    d = compute_module_overview_delta(cur, base, group_by="module")["rows"][0]["delta"]

    assert d["overdue_delta"] == 3
    assert d["overdue_delta_pct"] is None
    assert d["remaining_delta_pct"] is None
    assert d["progress_delta"] == 10.0
    assert d["progress_delta_pct"] is None


def test_no_change_gives_zero_not_none():
    cur = [_row("TMS")]
    base = [_row("TMS")]
    d = compute_module_overview_delta(cur, base, group_by="module")["rows"][0]["delta"]
    assert d["total_delta"] == 0
    assert d["total_delta_pct"] == 0.0
    assert d["progress_delta"] == 0.0


def test_negative_base_uses_absolute_denominator():
    """Không để dấu của mốc đảo chiều phần trăm (dữ liệu rác vẫn phải đọc được)."""
    cur = [_row("TMS", overdue=0)]
    base = [_row("TMS", overdue=-4)]
    d = compute_module_overview_delta(cur, base, group_by="module")["rows"][0]["delta"]
    assert d["overdue_delta"] == 4
    assert d["overdue_delta_pct"] == 100.0


def test_count_delta_stays_integer():
    cur = [_row("TMS", total=11)]
    base = [_row("TMS", total=10)]
    d = compute_module_overview_delta(cur, base, group_by="module")["rows"][0]["delta"]
    assert isinstance(d["total_delta"], int)
    assert isinstance(d["progress_delta"], float)


# ------------------------------------------------------------------
# Nhóm mới / nhóm mất
# ------------------------------------------------------------------

def test_new_module_marked_and_all_deltas_none():
    cur = [_row("TMS"), _row("NEW")]
    base = [_row("TMS")]
    out = compute_module_overview_delta(cur, base, group_by="module")
    new_row = next(r for r in out["rows"] if r["module"] == "NEW")

    assert new_row["delta"]["is_new"] is True
    assert new_row["delta"]["base"] is None
    for m in METRICS:
        assert new_row["delta"][f"{m['key']}_delta"] is None
        assert new_row["delta"][f"{m['key']}_delta_pct"] is None
    assert out["summary"]["new_count"] == 1


def test_removed_module_listed_not_rendered_as_row():
    cur = [_row("TMS")]
    base = [_row("TMS"), _row("GONE", total=7, remaining=3)]
    out = compute_module_overview_delta(cur, base, group_by="module")

    assert [r["module"] for r in out["rows"]] == ["TMS"]
    assert len(out["removed"]) == 1
    assert out["removed"][0]["module"] == "GONE"
    assert out["removed"][0]["total"] == 7
    assert out["summary"]["removed_count"] == 1


def test_removed_children_also_listed():
    cur = [_row("TMS", children=[_row("TMS", process="P1")])]
    base = [_row("TMS", children=[_row("TMS", process="P1"), _row("TMS", process="P2")])]
    out = compute_module_overview_delta(cur, base, group_by="both")
    assert [(x["module"], x["process"]) for x in out["removed"]] == [("TMS", "P2")]


def test_empty_base_marks_everything_new():
    out = compute_module_overview_delta([_row("TMS"), _row("HR")], [], group_by="module")
    assert all(r["delta"]["is_new"] for r in out["rows"])
    assert out["summary"]["new_count"] == 2
    assert out["removed"] == []


# ------------------------------------------------------------------
# Summary + metadata
# ------------------------------------------------------------------

def test_summary_totals_and_average_progress():
    cur = [_row("TMS", total=10, progress=60.0, overdue=1, remaining=3),
           _row("HR", total=6, progress=40.0, overdue=0, remaining=2)]
    base = [_row("TMS", total=8, progress=50.0, overdue=2, remaining=5),
            _row("HR", total=6, progress=30.0, overdue=1, remaining=4)]
    s = compute_module_overview_delta(cur, base, group_by="module")["summary"]
    assert s["total_delta"] == 2
    assert s["overdue_delta"] == -2
    assert s["remaining_delta"] == -4
    assert s["progress_delta_pp"] == 10.0  # (60+40)/2 − (50+30)/2


def test_polarity_and_metrics_metadata():
    out = compute_module_overview_delta([_row("TMS")], [_row("TMS")], group_by="module")
    assert out["polarity"] == {
        "total": "neutral", "progress": "up_good",
        "overdue": "up_bad", "remaining": "down_good",
    }
    assert [m["key"] for m in out["metrics"]] == ["total", "progress", "overdue", "remaining"]
    assert next(m for m in out["metrics"] if m["key"] == "progress")["unit"] == "pp"
    assert out["group_by"] == "module"
    # Không sửa hằng số dùng chung
    assert POLARITY["overdue"] == "up_bad"


# ------------------------------------------------------------------
# API smoke — /module-overview?compare=
# ------------------------------------------------------------------

def _upload(client, xlsx_path, project="default"):
    with open(xlsx_path, "rb") as f:
        data = {"file": (io.BytesIO(f.read()), "test.xlsx")}
    return client.post(
        f"/api/projects/{project}/upload", data=data,
        content_type="multipart/form-data",
    )


def test_api_module_overview_compare_off(flask_client, sample_xlsx_path):
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.get("/api/projects/default/module-overview?compare=off")
    assert r.status_code == 200
    body = r.get_json()
    assert body["delta"] is None
    assert body["compare_base"]["mode"] == "off"
    assert body["rows"]
    assert "delta" not in body["rows"][0]


def test_api_module_overview_without_baseline_reports_error_not_500(flask_client, sample_xlsx_path):
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.get("/api/projects/default/module-overview?compare=baseline")
    assert r.status_code == 200
    body = r.get_json()
    assert body["delta"] is None
    assert "Chốt baseline" in body["compare_base"]["error"]


def test_api_module_overview_compare_baseline_gives_zero_delta(flask_client, sample_xlsx_path):
    """Chốt baseline rồi so ngay → mọi delta bằng 0 (cùng một bản dữ liệu)."""
    _upload(flask_client, sample_xlsx_path)
    assert flask_client.post(
        "/api/projects/default/baselines", json={"label": "T0"},
    ).status_code == 200

    r = flask_client.get("/api/projects/default/module-overview?compare=baseline")
    body = r.get_json()
    assert body["compare_base"]["source"] == "baseline"
    assert "Baseline v1" in body["compare_base"]["label"]
    assert body["delta"]["removed"] == []
    assert body["delta"]["summary"]["total_delta"] == 0
    for row in body["rows"]:
        assert row["delta"]["is_new"] is False
        assert row["delta"]["total_delta"] == 0
        assert row["delta"]["progress_delta"] == 0


def test_api_module_overview_compare_respects_global_filter(flask_client, sample_xlsx_path):
    """Filter phải áp lên cả bản mốc, nếu không module bị lọc sẽ thành 'mới'."""
    _upload(flask_client, sample_xlsx_path)
    flask_client.post("/api/projects/default/baselines", json={})

    r = flask_client.get(
        "/api/projects/default/module-overview?compare=baseline&module=TMS",
    )
    body = r.get_json()
    assert body["applied_filter"]["modules"] == ["TMS"]
    assert body["delta"] is not None
    tms = [x for x in body["rows"] if x["module"] == "TMS" and x["total"] > 0]
    assert tms and all(x["delta"]["total_delta"] == 0 for x in tms)


def test_api_module_overview_compare_group_by_process(flask_client, sample_xlsx_path):
    _upload(flask_client, sample_xlsx_path)
    flask_client.post("/api/projects/default/baselines", json={})
    r = flask_client.get(
        "/api/projects/default/module-overview?compare=baseline&group_by=process",
    )
    body = r.get_json()
    assert body["group_by"] == "process"
    assert body["rows"] and all(row["process"] for row in body["rows"])
    assert all(row["delta"]["total_delta"] == 0 for row in body["rows"])


# ------------------------------------------------------------------
# Export Excel
# ------------------------------------------------------------------

def _summary_header_row(xlsx_bytes: bytes) -> list[str]:
    """Hàng header của sheet Tong_hop (dòng đầu có >= 3 ô có chữ)."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
    ws = wb["Tong_hop"]
    for row in ws.iter_rows(values_only=True):
        vals = [str(c) for c in row if c not in (None, "")]
        if len(vals) >= 3 and "STT" in vals:
            wb.close()
            return vals
    wb.close()
    return []


def test_export_module_overview_has_remaining_and_risk_columns(flask_client, sample_xlsx_path):
    """2 cột UI có mà export thiếu trước đây: Còn lại và Đánh giá."""
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.get(
        "/api/projects/default/export-chart?chart=module_overview&mode=summary&compare=off",
    )
    assert r.status_code == 200
    header = _summary_header_row(r.data)
    assert "Còn lại" in header
    assert "Đánh giá" in header
    assert not any(h.startswith("±") for h in header)


def test_export_module_overview_with_compare_adds_delta_columns(flask_client, sample_xlsx_path):
    _upload(flask_client, sample_xlsx_path)
    flask_client.post("/api/projects/default/baselines", json={})
    r = flask_client.get(
        "/api/projects/default/export-chart?chart=module_overview&mode=summary&compare=baseline",
    )
    assert r.status_code == 200
    header = _summary_header_row(r.data)
    assert "± SL" in header
    assert "± Tiến độ (pp)" in header
    assert "±% Còn lại" in header


def test_export_module_overview_group_by_process_adds_process_column(flask_client, sample_xlsx_path):
    """group_by trước đây bị bỏ qua ở export → luôn ra bảng theo module."""
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.get(
        "/api/projects/default/export-chart"
        "?chart=module_overview&mode=summary&group_by=process&compare=off",
    )
    assert r.status_code == 200
    assert "Quy trình" in _summary_header_row(r.data)
