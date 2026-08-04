"""
Baseline Schedule Variance (SV) — so sánh snapshot hiện tại vs snapshot baseline.

Định nghĩa SV (ngày):
  SV = end_hiện_tại − end_baseline

  - end_baseline: End date của phase trong snapshot được đánh dấu baseline
    ("kế hoạch gốc được approved").
  - end_hiện_tại:
      · nếu phase Closed → End (fallback last_updated)
      · ngược lại → End trên file hiện tại (kế hoạch/actual đang theo dõi)
  - SV > 0 = trễ so với baseline; SV < 0 = sớm; SV = 0 = đúng kế hoạch.
  - Chỉ so sánh khi CẢ HAI bên có End date. Cancelled bị bỏ qua.

Khác với advanced_metrics.compute_baseline_variance (Planned/Actual trong cùng file):
module này so sánh CROSS-SNAPSHOT theo baseline_snapshot_id trong project settings.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any, Optional

from parser.excel_parser import ParsedData, FunctionRow, PhaseData

from analyzer.forecast_gantt import (
    MILESTONE_DEFS,
    compute_milestone_for_data,
)

DONE = frozenset({"Closed", "Cancelled"})
_CANCELLED = "Cancelled"


def _parse_iso(d: Any) -> Optional[date]:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    if isinstance(d, str):
        s = d.strip()
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "")[:19]).date()
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(s[:10], fmt).date()
            except ValueError:
                continue
    return None


def _primary_key(row: FunctionRow) -> str:
    code = (row.meta.get("ma_cn") or "").strip().lower()
    if code:
        return f"code:{code}"
    ten = (row.meta.get("ten_cn") or "").strip().lower()
    mod = (row.meta.get("module") or "").strip().lower()
    return f"name:{ten}|{mod}"


def _index_rows(data: ParsedData) -> dict[str, FunctionRow]:
    out: dict[str, FunctionRow] = {}
    for row in data.rows:
        out[_primary_key(row)] = row
    return out


def _current_end(row: FunctionRow, pd: PhaseData) -> Optional[date]:
    """End hiện tại dùng cho SV — Closed ưu tiên End/last_updated."""
    if (pd.status or "") == "Cancelled":
        return None
    if (pd.status or "") == "Closed":
        return (
            _parse_iso(pd.end_date)
            or _parse_iso(row.meta.get("last_updated"))
        )
    return _parse_iso(pd.end_date)


def _baseline_end(pd: PhaseData) -> Optional[date]:
    if (pd.status or "") == "Cancelled":
        return None
    return _parse_iso(pd.end_date)


def compute_function_sv(
    current: ParsedData,
    baseline: ParsedData,
) -> list[dict[str, Any]]:
    """SV cấp function×phase — list items (sort |SV| desc)."""
    base_idx = _index_rows(baseline)
    items: list[dict[str, Any]] = []

    for row in current.rows:
        key = _primary_key(row)
        base_row = base_idx.get(key)
        if base_row is None:
            continue
        phases = set(row.phases.keys()) & set(base_row.phases.keys())
        for phase_name in phases:
            cur_pd = row.phases.get(phase_name) or PhaseData()
            base_pd = base_row.phases.get(phase_name) or PhaseData()
            if (cur_pd.status or "") == _CANCELLED or (base_pd.status or "") == _CANCELLED:
                continue
            b_end = _baseline_end(base_pd)
            c_end = _current_end(row, cur_pd)
            if b_end is None or c_end is None:
                continue
            sv = (c_end - b_end).days
            items.append({
                "ma_cn": row.meta.get("ma_cn") or "",
                "ten_cn": row.meta.get("ten_cn") or "",
                "module": row.meta.get("module") or "",
                "quy_trinh": row.meta.get("quy_trinh") or row.meta.get("process") or "",
                "phase": phase_name,
                "baseline_end": b_end.isoformat(),
                "current_end": c_end.isoformat(),
                "sv_days": sv,
                "late": sv > 0,
                "early": sv < 0,
                "status": cur_pd.status or "",
            })

    items.sort(key=lambda x: -abs(x["sv_days"]))
    return items


def _aggregate_module(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_mod: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        by_mod[it.get("module") or "(trống)"].append(it)
    rows: list[dict[str, Any]] = []
    for mod, group in by_mod.items():
        svs = [g["sv_days"] for g in group]
        late = sum(1 for g in group if g["late"])
        early = sum(1 for g in group if g["early"])
        rows.append({
            "module": mod,
            "compared": len(group),
            "late_count": late,
            "early_count": early,
            "on_track_count": len(group) - late - early,
            "avg_sv_days": round(sum(svs) / len(svs), 1) if svs else 0,
            "max_sv_days": max(svs) if svs else 0,
            "min_sv_days": min(svs) if svs else 0,
        })
    rows.sort(key=lambda r: -abs(r["avg_sv_days"]))
    return rows


def compute_milestone_sv(
    current: ParsedData,
    baseline: ParsedData,
    today: Optional[date] = None,
) -> dict[str, dict[str, Any]]:
    """
    SV cấp milestone (UAT/Golive/…) — so sánh ngày milestone hiện tại vs baseline.

    Dùng cùng rule forecast_gantt (open_max / closed_max).
    SV_milestone = current_date − baseline_date (ngày).
    """
    today = today or date.today()
    out: dict[str, dict[str, Any]] = {}
    for m in MILESTONE_DEFS:
        mid = m["id"]
        cur = compute_milestone_for_data(current, m["task_types"], today=today)
        base = compute_milestone_for_data(baseline, m["task_types"], today=today)
        sv_days: Optional[int] = None
        if cur.get("date") and base.get("date"):
            sv_days = (
                date.fromisoformat(cur["date"]) - date.fromisoformat(base["date"])
            ).days
        out[mid] = {
            "id": mid,
            "label": m["label"],
            "current": {
                "date": cur.get("date"),
                "month": cur.get("month"),
                "source": cur.get("source"),
            },
            "baseline": {
                "date": base.get("date"),
                "month": base.get("month"),
                "source": base.get("source"),
            },
            "sv_days": sv_days,
            "late": sv_days is not None and sv_days > 0,
            "early": sv_days is not None and sv_days < 0,
        }
    return out


def compute_baseline_sv(
    current: ParsedData,
    baseline: ParsedData,
    baseline_snapshot_id: str,
    today: Optional[date] = None,
    top_functions: Optional[int] = 200,
) -> dict[str, Any]:
    """
    Tổng hợp SV: function / module / milestone + summary late/early.

    Args:
        baseline_snapshot_id: ngày snapshot baseline (YYYY-MM-DD) — echo cho FE.
        top_functions: cắt danh sách function (None/0 = all).
    """
    today = today or date.today()
    items = compute_function_sv(current, baseline)
    late = [i for i in items if i["late"]]
    early = [i for i in items if i["early"]]
    trimmed = items[:top_functions] if (top_functions and top_functions > 0) else items
    milestones = compute_milestone_sv(current, baseline, today=today)

    ms_late = sum(1 for m in milestones.values() if m.get("late"))
    ms_early = sum(1 for m in milestones.values() if m.get("early"))

    return {
        "definition": (
            "SV (ngày) = end_hiện_tại − end_baseline. "
            "Baseline = End trong snapshot được đánh dấu. "
            "Hiện tại = End (Closed → End/last_updated). "
            "SV>0 trễ, SV<0 sớm."
        ),
        "baseline_snapshot_id": baseline_snapshot_id,
        "functions": trimmed,
        "functions_total": len(items),
        "modules": _aggregate_module(items),
        "milestones": milestones,
        "summary": {
            "compared": len(items),
            "late_count": len(late),
            "early_count": len(early),
            "on_track_count": len(items) - len(late) - len(early),
            "avg_sv_days": round(
                sum(i["sv_days"] for i in items) / len(items), 1
            ) if items else 0,
            "milestone_late": ms_late,
            "milestone_early": ms_early,
        },
    }


def attach_baseline_to_forecast_row(
    milestones_current: dict[str, dict[str, Any]],
    baseline_data: Optional[ParsedData],
    today: Optional[date] = None,
) -> dict[str, Any]:
    """
    Gắn lớp baseline vào milestones của 1 project row Forecast Gantt.

    Trả dict phụ: {milestone_id: {baseline_month, baseline_date, sv_days, late, early}}
    và summary late/early milestone.
    """
    if baseline_data is None:
        return {"milestones": {}, "summary": None}

    today = today or date.today()
    layer: dict[str, Any] = {}
    late = early = compared = 0
    for m in MILESTONE_DEFS:
        mid = m["id"]
        cur = milestones_current.get(mid) or {}
        base = compute_milestone_for_data(baseline_data, m["task_types"], today=today)
        sv_days: Optional[int] = None
        if cur.get("date") and base.get("date"):
            sv_days = (
                date.fromisoformat(cur["date"]) - date.fromisoformat(base["date"])
            ).days
            compared += 1
            if sv_days > 0:
                late += 1
            elif sv_days < 0:
                early += 1
        layer[mid] = {
            "baseline_date": base.get("date"),
            "baseline_month": base.get("month"),
            "baseline_source": base.get("source"),
            # Span ghost bar trên Forecast Gantt (min Start → max End baseline)
            "baseline_span_start": base.get("span_start"),
            "baseline_span_end": base.get("span_end"),
            "baseline_span_start_date": base.get("span_start_date"),
            "baseline_span_end_date": base.get("span_end_date"),
            "sv_days": sv_days,
            "late": sv_days is not None and sv_days > 0,
            "early": sv_days is not None and sv_days < 0,
        }
        # Đảm bảo tháng/span baseline nằm trong ruler (caller merge all_months)
        if base.get("month"):
            layer[mid]["_month_for_ruler"] = base["month"]

    return {
        "milestones": layer,
        "summary": {
            "compared": compared,
            "late_count": late,
            "early_count": early,
            "on_track_count": compared - late - early,
        },
    }


# Re-export helper cho forecast_gantt tháng baseline
def baseline_months_from_layer(layer: dict[str, Any]) -> list[str]:
    months: list[str] = []
    for info in (layer.get("milestones") or {}).values():
        for key in (
            "baseline_month",
            "baseline_span_start",
            "baseline_span_end",
            "_month_for_ruler",
        ):
            mk = info.get(key)
            if mk:
                months.append(mk)
    return months
