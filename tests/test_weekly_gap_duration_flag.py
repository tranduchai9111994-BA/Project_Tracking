"""
Tab «Báo cáo tuần» và «Thời gian dài» — regression cho 3 bug làm 2 tab này chết.

Bug đã sửa (2026-08-05):
  1. `dashboard.js` gọi `apiFetch(...)` — hàm không tồn tại ở đâu cả (helper thật
     là `apiJson`). Báo cáo tuần hiện toast "apiFetch is not defined";
     Thời gian dài thì swallow lỗi nên chỉ ra bảng rỗng.
  2. `weekly_gap_report.py` + `duration_flag.py` đọc `pd.pic` trong khi
     `PhaseData` chỉ có `pics` (list) → AttributeError → API 500 ngay khi có
     từ 1 dòng khớp.
  3. `weekly_gap_report.py` đọc `row.meta["fitgap"]` trong khi parser lưu
     `fit_gap` → cột FIT/GAP luôn rỗng và filter "chỉ GAP"/"chỉ FIT" ra 0 dòng.

Hai module này trước đó không có test nào — đó là lý do bug sống sót.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from analyzer.duration_flag import compute_long_duration
from analyzer.weekly_gap_report import compute_weekly_gap
from parser.excel_parser import FunctionRow, PhaseData, PhaseGroup, ParsedData


PHASES = ["Analysis", "Dev", "Config Local"]


def _this_week() -> tuple[date, date]:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return monday, monday + timedelta(days=4)


def _data(rows: list[FunctionRow]) -> ParsedData:
    return ParsedData(
        headers={},
        meta_columns={},
        phase_groups=[PhaseGroup(name=n) for n in PHASES],
        rows=rows,
        all_phases=list(PHASES),
        all_modules=sorted({r.meta.get("module", "") for r in rows}),
    )


def _row(ma: str, *, phases: dict[str, PhaseData], fit_gap: str = "GAP",
         module: str = "HR", meta_key: str = "fit_gap") -> FunctionRow:
    return FunctionRow(
        row_num=2,
        meta={"ma_cn": ma, "ten_cn": f"Func {ma}", "module": module,
              meta_key: fit_gap},
        phases=phases,
    )


# ── Weekly GAP ─────────────────────────────────────────────────────────────

def test_weekly_gap_joins_multiple_pics_without_crashing():
    """PhaseData.pics là list — trước đây đọc pd.pic nên nổ AttributeError."""
    _, friday = _this_week()
    rows = [_row("A.01", phases={
        "Dev": PhaseData(status="Assigned", end_date=friday,
                         pics=["BaoLQ31", "NhiVN"]),
    })]
    out = compute_weekly_gap(_data(rows))
    assert out["summary"]["total"] == 1
    assert out["items"][0]["pic"] == "BaoLQ31, NhiVN"


def test_weekly_gap_pic_empty_when_no_assignee():
    _, friday = _this_week()
    rows = [_row("A.02", phases={
        "Dev": PhaseData(status="Open", end_date=friday, pics=[]),
    })]
    out = compute_weekly_gap(_data(rows))
    assert out["items"][0]["pic"] == ""


def test_weekly_gap_reads_fit_gap_meta_key():
    """Parser lưu key `fit_gap` — cột FITGAP phải có giá trị, không rỗng."""
    _, friday = _this_week()
    rows = [_row("A.03", fit_gap="GAP", phases={
        "Dev": PhaseData(status="Assigned", end_date=friday, pics=["X"]),
    })]
    out = compute_weekly_gap(_data(rows))
    assert out["items"][0]["fitgap"] == "GAP"
    assert out["summary"]["by_fitgap"]["GAP"] == 1


def test_weekly_gap_falls_back_to_legacy_fitgap_key():
    _, friday = _this_week()
    rows = [_row("A.04", fit_gap="FIT", meta_key="fitgap", phases={
        "Dev": PhaseData(status="Assigned", end_date=friday, pics=["X"]),
    })]
    out = compute_weekly_gap(_data(rows))
    assert out["items"][0]["fitgap"] == "FIT"


def test_weekly_gap_filter_gap_and_fit_actually_narrow():
    """Trước fix, filter luôn ra 0 dòng vì fitgap của row luôn rỗng."""
    _, friday = _this_week()
    rows = [
        _row("G.01", fit_gap="GAP", phases={
            "Dev": PhaseData(status="Assigned", end_date=friday, pics=["A"])}),
        _row("F.01", fit_gap="FIT", phases={
            "Dev": PhaseData(status="Assigned", end_date=friday, pics=["B"])}),
        _row("F.02", fit_gap="FIT", phases={
            "Dev": PhaseData(status="Assigned", end_date=friday, pics=["C"])}),
    ]
    data = _data(rows)
    assert compute_weekly_gap(data, fitgap_filter="")["summary"]["total"] == 3
    gap = compute_weekly_gap(data, fitgap_filter="gap")
    assert [i["ma_cn"] for i in gap["items"]] == ["G.01"]
    fit = compute_weekly_gap(data, fitgap_filter="fit")
    assert sorted(i["ma_cn"] for i in fit["items"]) == ["F.01", "F.02"]


def test_weekly_gap_skips_closed_and_other_weeks():
    monday, friday = _this_week()
    rows = [
        _row("S.01", phases={  # Closed → bỏ
            "Dev": PhaseData(status="Closed", end_date=friday, pics=["A"])}),
        _row("S.02", phases={  # tuần sau → bỏ khi offset=0
            "Dev": PhaseData(status="Assigned",
                             end_date=monday + timedelta(days=9), pics=["B"])}),
    ]
    out = compute_weekly_gap(_data(rows))
    assert out["summary"]["total"] == 0
    nxt = compute_weekly_gap(_data(rows), week_offset=1)
    assert [i["ma_cn"] for i in nxt["items"]] == ["S.02"]


# ── Duration flag ──────────────────────────────────────────────────────────

def test_duration_flag_joins_multiple_pics_without_crashing():
    today = date.today()
    rows = [_row("D.01", phases={
        "Dev": PhaseData(status="In-progress",
                         start_date=today - timedelta(days=120),
                         end_date=today - timedelta(days=10),
                         pics=["CuongNM129", "TungTT83"]),
    })]
    out = compute_long_duration(_data(rows), threshold_days=60)
    assert out["summary"]["total"] == 1
    assert out["items"][0]["pic"] == "CuongNM129, TungTT83"
    assert out["items"][0]["duration_days"] == 110


def test_duration_flag_respects_threshold_and_skips_done():
    """Cancelled + Closed bị bỏ; chỉ phase còn mở + vượt ngưỡng mới đếm."""
    today = date.today()
    rows = [
        _row("D.02", phases={  # 30 ngày < ngưỡng 60
            "Dev": PhaseData(status="Open",
                             start_date=today - timedelta(days=40),
                             end_date=today - timedelta(days=10), pics=["A"])}),
        _row("D.03", phases={  # Cancelled → bỏ
            "Dev": PhaseData(status="Cancelled",
                             start_date=today - timedelta(days=200),
                             end_date=today - timedelta(days=10), pics=["B"])}),
        _row("D.04", phases={  # Closed dài → bỏ (rule 06/08/2026)
            "Dev": PhaseData(status="Closed",
                             start_date=today - timedelta(days=250),
                             end_date=today - timedelta(days=1), pics=["C"])}),
        _row("D.05", phases={  # Assigned dài → giữ
            "Analysis": PhaseData(status="Assigned",
                                  start_date=today - timedelta(days=100),
                                  end_date=today + timedelta(days=10), pics=["D"])}),
    ]
    out = compute_long_duration(_data(rows), threshold_days=60)
    assert out["summary"]["total"] == 1
    assert out["items"][0]["ma_cn"] == "D.05"
    assert out["items"][0]["status"] == "Assigned"


# ── API smoke ──────────────────────────────────────────────────────────────

def _upload(flask_client, sample_xlsx_path) -> str:
    with open(sample_xlsx_path, "rb") as f:
        r = flask_client.post(
            "/api/upload",
            data={"file": (f, "sample.xlsx")},
            content_type="multipart/form-data",
        )
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json().get("project", {}).get("slug") or "default"


def test_api_weekly_gap_report_ok(flask_client, sample_xlsx_path):
    slug = _upload(flask_client, sample_xlsx_path)
    for params in ("", "?week_offset=1", "?fitgap=gap", "?fitgap=fit"):
        r = flask_client.get(f"/api/projects/{slug}/weekly-gap-report{params}")
        assert r.status_code == 200, f"{params}: {r.get_data(as_text=True)}"
        payload = r.get_json()
        assert "items" in payload and "summary" in payload
        assert "week_label" in payload
        for it in payload["items"]:
            assert isinstance(it["pic"], str)


def test_api_duration_flag_ok(flask_client, sample_xlsx_path):
    slug = _upload(flask_client, sample_xlsx_path)
    r = flask_client.get(f"/api/projects/{slug}/duration-flag?threshold=30")
    assert r.status_code == 200, r.get_data(as_text=True)
    payload = r.get_json()
    assert payload["threshold_days"] == 30
    for it in payload["items"]:
        assert isinstance(it["pic"], str)


def test_api_export_weekly_gap_ok(flask_client, sample_xlsx_path):
    """Export dùng cùng compute_weekly_gap nên cũng từng 500."""
    slug = _upload(flask_client, sample_xlsx_path)
    r = flask_client.get(f"/api/projects/{slug}/export-weekly-gap")
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.headers["Content-Type"].startswith(
        "application/vnd.openxmlformats-officedocument"
    )


# ── FE wiring ──────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_JS = (ROOT / "static" / "js" / "dashboard.js").read_text(encoding="utf-8")

# Global nạp từ CDN — không định nghĩa trong dashboard.js.
_EXTERNAL_GLOBALS = {"html2canvas", "fetch", "Promise", "import", "eval"}


def test_no_apifetch_helper_left():
    assert "apiFetch" not in DASHBOARD_JS, (
        "apiFetch không tồn tại — dùng apiJson"
    )


def test_weekly_gap_and_duration_loaders_use_apijson():
    for fn in ("loadWeeklyGap", "loadDurationFlag"):
        body = DASHBOARD_JS.split(f"async function {fn}(")[1].split("\nwindow.")[0]
        assert "await apiJson(" in body, f"{fn} không gọi apiJson"


def test_every_awaited_helper_is_defined_somewhere():
    """Lint: `await foo(...)` mà foo không định nghĩa → ReferenceError runtime."""
    called = set(re.findall(r"await\s+([A-Za-z_$][\w$]*)\s*\(", DASHBOARD_JS))
    assert called, "không parse được call await nào"
    defined: set[str] = set()
    defined |= set(re.findall(
        r"(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(", DASHBOARD_JS))
    defined |= set(re.findall(
        r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", DASHBOARD_JS))
    defined |= set(re.findall(r"window\.([A-Za-z_$][\w$]*)\s*=", DASHBOARD_JS))
    defined |= set(re.findall(
        r"([A-Za-z_$][\w$]*)\s*:\s*(?:async\s+)?function", DASHBOARD_JS))
    missing = sorted(called - defined - _EXTERNAL_GLOBALS)
    assert missing == [], f"hàm await nhưng chưa định nghĩa: {missing}"


def test_duration_flag_loader_surfaces_error():
    """Không swallow lỗi API — trước đây chỉ console.error nên tab im lặng."""
    body = DASHBOARD_JS.split("async function loadDurationFlag(")[1].split(
        "\nwindow.")[0]
    assert "showToast(" in body
