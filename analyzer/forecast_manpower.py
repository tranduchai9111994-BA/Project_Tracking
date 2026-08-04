"""
Forecast Manpower — ước lượng MH / MD / MM và nhu cầu tuyển theo công đoạn.

Cơ sở tính (basis):
  - unit: Estimate MH trên Function List; ô trống → mặc định 8 MH
  - duration: số ngày làm việc (Start→End, bỏ T7/CN) × 8 MH/ngày;
             thiếu Start/End → fallback như unit (MH mặc định 8)

Công đoạn:
  - Từng task_type (Phân tích, Lập trình, …) — map từ PhaseGroup.task_type
  - Pool: «Lập trình» riêng; «Triển khai chung» = các task_type còn lại
    (phân tích / test / cấu hình / UAT / tài liệu / golive…)

Headcount hiện tại (user nhập) → số người cần (theo target tháng) → cần tuyển thêm.

Target (tháng) mặc định: còn lại từ hôm nay → Golive (Forecast Gantt) /
max End còn mở / completion forecast — KHÔNG mặc định 1.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Optional

from parser.excel_parser import ParsedData, PhaseData

DEFAULT_MH = 8.0
MH_PER_MANDAY = 8.0
MH_PER_MANMONTH = 160.0  # 20 ngày làm × 8h
DEV_TASK_TYPE = "Lập trình"
IMPL_POOL_ID = "impl_shared"
IMPL_POOL_LABEL = "Triển khai chung"
DEV_POOL_ID = "dev"
DEV_POOL_LABEL = "Lập trình (riêng)"

# Preset quy mô → MH mặc định khi Estimate trống (HRIS nhỏ–vừa thường < 8)
SIZE_DEFAULT_MH: dict[str, float] = {
    "small": 2.0,
    "medium": 4.0,
    "large": 8.0,
}

_CANCELLED = frozenset({"cancelled", "Canceled", "CANCELLED"})


def _is_cancelled(status: Optional[str]) -> bool:
    return (status or "").strip().lower() in {"cancelled", "canceled"}


def _is_closed(status: Optional[str]) -> bool:
    return (status or "").strip().lower() == "closed"


def _working_days(start: date, end: date) -> int:
    """Số ngày làm việc inclusive Start→End (bỏ T7/CN)."""
    if end < start:
        start, end = end, start
    n = 0
    d = start
    while d <= end:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return max(n, 1)


def _phase_mh(
    pd: PhaseData,
    basis: str,
    default_mh: float = DEFAULT_MH,
) -> tuple[float, str, bool]:
    """
    Returns (mh, method_note, used_default).
    method_note: giải thích ngắn cho cột ghi chú.
    """
    basis = (basis or "unit").strip().lower()
    if basis == "duration":
        if pd.start_date and pd.end_date:
            days = _working_days(pd.start_date, pd.end_date)
            mh = float(days) * MH_PER_MANDAY
            return mh, f"Duration {days} ngày làm × {MH_PER_MANDAY:g} MH", False
        # fallback unit
        if pd.estimate_mh is not None and pd.estimate_mh > 0:
            return (
                float(pd.estimate_mh),
                "Duration thiếu ngày → dùng Estimate MH",
                False,
            )
        return (
            float(default_mh),
            f"Duration thiếu ngày + không MH → mặc định {default_mh:g} MH",
            True,
        )

    # unit
    if pd.estimate_mh is not None and pd.estimate_mh > 0:
        return float(pd.estimate_mh), "Estimate MH trên Function List", False
    return (
        float(default_mh),
        f"Không nhập Estimate MH → mặc định {default_mh:g} MH",
        True,
    )


def _task_type_for_phase(data: ParsedData, phase_name: str) -> str:
    for pg in data.phase_groups:
        if pg.name == phase_name:
            return pg.task_type or phase_name
    return phase_name


def _convert(mh: float, unit: str) -> float:
    unit = (unit or "manhour").strip().lower()
    if unit in ("manday", "md", "man_day"):
        return round(mh / MH_PER_MANDAY, 2)
    if unit in ("manmonth", "mm", "man_month"):
        return round(mh / MH_PER_MANMONTH, 2)
    return round(mh, 2)


def _people_needed(remaining_mh: float, target_months: float) -> int:
    """Số người nguyên cần để hết remaining trong target_months (full capacity)."""
    if remaining_mh <= 0:
        return 0
    months = max(float(target_months or 1.0), 0.25)
    capacity = months * MH_PER_MANMONTH
    if capacity <= 0:
        return 0
    return int(math.ceil(remaining_mh / capacity))


def months_until(today: date, end: date) -> float:
    """
    Số tháng còn lại today → end (tối thiểu 0.25), làm tròn bậc 0.25.

    Dùng chênh lệch lịch (năm/tháng) + hiệu chỉnh theo ngày / 30
    → Golive 12/2026 từ 01/08/2026 ≈ 4 tháng.
    """
    if end <= today:
        return 0.25
    months = (end.year - today.year) * 12 + (end.month - today.month)
    day_adj = (end.day - today.day) / 30.0
    raw = max(0.25, float(months) + day_adj)
    return max(0.25, round(raw * 4) / 4)


def _max_open_end(data: ParsedData) -> Optional[date]:
    """Max End của phase còn mở (chưa Closed/Cancelled)."""
    ends: list[date] = []
    for row in data.rows:
        for pd in row.phases.values():
            if _is_cancelled(pd.status) or _is_closed(pd.status):
                continue
            if pd.end_date:
                ends.append(pd.end_date)
    return max(ends) if ends else None


def suggest_target_months(
    data: ParsedData,
    *,
    today: Optional[date] = None,
) -> dict[str, Any]:
    """
    Gợi ý Target (tháng) từ thời hạn còn lại.

    Ưu tiên nguồn:
      1. Golive (Forecast Gantt milestone — max End còn mở / closed)
      2. Max End còn mở trên mọi phase
      3. completion_forecast.forecast_date (velocity)
      4. Fallback 1.0 nếu không có ngày
    """
    today = today or date.today()
    end: Optional[date] = None
    source = "fallback"
    source_label = "không có Golive/End — tạm 1 tháng"
    month_key: Optional[str] = None

    try:
        from analyzer.forecast_gantt import MILESTONE_DEFS, compute_milestone_for_data

        golive_def = next((m for m in MILESTONE_DEFS if m["id"] == "golive"), None)
        if golive_def:
            ms = compute_milestone_for_data(
                data, golive_def["task_types"], today=today
            )
            if ms.get("date"):
                end = date.fromisoformat(ms["date"])
                source = "golive"
                month_key = ms.get("month") or f"{end.year:04d}-{end.month:02d}"
                source_label = f"từ Golive {end.month:02d}/{end.year}"
    except Exception:
        pass

    if end is None:
        open_end = _max_open_end(data)
        if open_end is not None:
            end = open_end
            source = "max_open_end"
            month_key = f"{end.year:04d}-{end.month:02d}"
            source_label = f"từ max End còn mở {end.month:02d}/{end.year}"

    if end is None:
        try:
            from analyzer.completion_forecast import compute_completion_forecast

            fc = compute_completion_forecast(data, today=today)
            fd = fc.get("forecast_date")
            if fd:
                end = date.fromisoformat(str(fd)[:10])
                source = "completion_forecast"
                month_key = f"{end.year:04d}-{end.month:02d}"
                source_label = f"từ dự báo hoàn thành {end.month:02d}/{end.year}"
        except Exception:
            pass

    if end is None:
        return {
            "months": 1.0,
            "end_date": None,
            "month_key": None,
            "source": source,
            "source_label": source_label,
            "today": today.isoformat(),
        }

    months = months_until(today, end)
    return {
        "months": months,
        "end_date": end.isoformat(),
        "month_key": month_key,
        "source": source,
        "source_label": source_label,
        "today": today.isoformat(),
    }


def compute_forecast_manpower(
    data: ParsedData,
    *,
    basis: str = "unit",
    display_unit: str = "manhour",
    default_mh: float = DEFAULT_MH,
    target_months: Optional[float] = None,
    headcount: Optional[dict[str, float]] = None,
    only_remaining: bool = True,
    today: Optional[date] = None,
    auto_target: bool = False,
) -> dict[str, Any]:
    """
    Tính MH theo công đoạn + pool Dev/Triển khai, nhu cầu tuyển.

    headcount: map stage_id hoặc label → số người hiện tại
      keys chấp nhận: task_type label, "dev", "impl_shared", DEV_POOL_LABEL, …

    target_months: nếu None hoặc auto_target=True → dùng suggest_target_months.
    """
    today = today or date.today()
    suggested = suggest_target_months(data, today=today)
    target_overridden = False
    if auto_target or target_months is None:
        target_months = float(suggested["months"])
        target_overridden = False
    else:
        try:
            target_months = float(target_months)
        except (TypeError, ValueError):
            target_months = float(suggested["months"])
            target_overridden = False
        else:
            target_overridden = True
    target_months = max(float(target_months), 0.25)

    headcount = headcount or {}
    by_stage: dict[str, dict[str, Any]] = {}
    detail: list[dict[str, Any]] = []

    totals = {
        "functions": 0,
        "phase_rows": 0,
        "mh_total": 0.0,
        "mh_remaining": 0.0,
        "mh_closed": 0.0,
        "mh_defaulted": 0.0,
    }
    func_seen: set[str] = set()

    for row in data.rows:
        ma = row.meta.get("ma_cn") or ""
        for phase_name, pd in row.phases.items():
            if _is_cancelled(pd.status):
                continue
            mh, method, used_default = _phase_mh(pd, basis, default_mh)
            tt = _task_type_for_phase(data, phase_name)
            closed = _is_closed(pd.status)
            if only_remaining and closed:
                # vẫn cộng closed vào stage closed_mh nhưng không vào remaining
                pass

            st = by_stage.setdefault(
                tt,
                {
                    "stage_id": tt,
                    "label": tt,
                    "mh_total": 0.0,
                    "mh_remaining": 0.0,
                    "mh_closed": 0.0,
                    "count_total": 0,
                    "count_remaining": 0,
                    "count_defaulted": 0,
                    "pool": DEV_POOL_ID if tt == DEV_TASK_TYPE else IMPL_POOL_ID,
                },
            )
            st["mh_total"] += mh
            st["count_total"] += 1
            if used_default:
                st["count_defaulted"] += 1
                totals["mh_defaulted"] += mh
            if closed:
                st["mh_closed"] += mh
                totals["mh_closed"] += mh
            else:
                st["mh_remaining"] += mh
                st["count_remaining"] += 1
                totals["mh_remaining"] += mh

            totals["mh_total"] += mh
            totals["phase_rows"] += 1
            if ma:
                func_seen.add(ma)

            detail.append({
                "ma_cn": ma,
                "ten_cn": row.meta.get("ten_cn") or "",
                "module": row.meta.get("module") or "",
                "quy_trinh": row.meta.get("quy_trinh") or "",
                "phase": phase_name,
                "task_type": tt,
                "pool": DEV_POOL_LABEL if tt == DEV_TASK_TYPE else IMPL_POOL_LABEL,
                "status": pd.status or "",
                "estimate_mh_raw": pd.estimate_mh,
                "mh": round(mh, 2),
                "used_default": used_default,
                "closed": closed,
                "basis": basis,
                "method_note": method,
                "start": pd.start_date.isoformat() if pd.start_date else "",
                "end": pd.end_date.isoformat() if pd.end_date else "",
                "pic": ", ".join(pd.pics or []),
            })

    totals["functions"] = len(func_seen) or len({r.meta.get("ma_cn") for r in data.rows})

    def _hc_for(*keys: str) -> float:
        for k in keys:
            if k in headcount and headcount[k] is not None:
                try:
                    return float(headcount[k])
                except (TypeError, ValueError):
                    continue
        return 0.0

    def _enrich_row(row: dict[str, Any], hc_keys: tuple[str, ...]) -> dict[str, Any]:
        rem = float(row["mh_remaining"])
        hc = _hc_for(*hc_keys)
        needed = _people_needed(rem, target_months)
        needed_ceil = int(needed)
        hire = max(0, needed_ceil - int(math.floor(hc)))
        months_with_current = (
            round(rem / (hc * MH_PER_MANMONTH), 2) if hc > 0 and rem > 0 else None
        )
        note = (
            f"Cơ sở={basis}; còn {round(rem, 1)} MH ≈ {_convert(rem, 'manday')} MD "
            f"/ {_convert(rem, 'manmonth')} MM. "
            f"Target {target_months:g} tháng → cần ~{needed_ceil} người "
            f"(hiện {hc:g}) → tuyển thêm {hire}."
        )
        if row.get("count_defaulted"):
            note += f" {row['count_defaulted']} phase dùng MH mặc định {default_mh:g}."
        return {
            **row,
            "mh_total": round(row["mh_total"], 2),
            "mh_remaining": round(rem, 2),
            "mh_closed": round(row["mh_closed"], 2),
            "display_total": _convert(row["mh_total"], display_unit),
            "display_remaining": _convert(rem, display_unit),
            "display_closed": _convert(row["mh_closed"], display_unit),
            "headcount_current": hc,
            "people_needed": needed_ceil,
            "hire_needed": hire,
            "months_with_current": months_with_current,
            "method_note": note,
        }

    stages = []
    for tt, st in sorted(by_stage.items(), key=lambda x: (-x[1]["mh_remaining"], x[0])):
        stages.append(_enrich_row(st, (tt, st["stage_id"])))

    # Pools
    pools_raw = {
        DEV_POOL_ID: {
            "stage_id": DEV_POOL_ID,
            "label": DEV_POOL_LABEL,
            "mh_total": 0.0,
            "mh_remaining": 0.0,
            "mh_closed": 0.0,
            "count_total": 0,
            "count_remaining": 0,
            "count_defaulted": 0,
            "pool": DEV_POOL_ID,
        },
        IMPL_POOL_ID: {
            "stage_id": IMPL_POOL_ID,
            "label": IMPL_POOL_LABEL,
            "mh_total": 0.0,
            "mh_remaining": 0.0,
            "mh_closed": 0.0,
            "count_total": 0,
            "count_remaining": 0,
            "count_defaulted": 0,
            "pool": IMPL_POOL_ID,
        },
    }
    for st in by_stage.values():
        pid = st["pool"]
        p = pools_raw[pid]
        for k in (
            "mh_total",
            "mh_remaining",
            "mh_closed",
            "count_total",
            "count_remaining",
            "count_defaulted",
        ):
            p[k] += st[k]

    pools = [
        _enrich_row(
            pools_raw[DEV_POOL_ID],
            (DEV_POOL_ID, DEV_POOL_LABEL, DEV_TASK_TYPE, "dev"),
        ),
        _enrich_row(
            pools_raw[IMPL_POOL_ID],
            (IMPL_POOL_ID, IMPL_POOL_LABEL, "impl", "triển khai"),
        ),
    ]

    unit_label = {
        "manhour": "Man-hour (MH)",
        "manday": "Man-day (MD = MH÷8)",
        "manmonth": "Man-month (MM = MH÷160)",
    }.get((display_unit or "").lower(), display_unit)

    basis_label = (
        "Unit — Estimate MH (mặc định 8 nếu trống)"
        if (basis or "").lower() != "duration"
        else "Duration — ngày làm Start→End × 8 MH (fallback MH/default)"
    )

    # A5 — % MH đang dùng estimate mặc định (chưa nhập Estimate MH thực tế trên FL).
    totals["seed_pct"] = (
        round(totals["mh_defaulted"] / totals["mh_total"] * 100, 1)
        if totals["mh_total"] > 0 else 0.0
    )

    target_meta = {
        **suggested,
        "used": float(target_months),
        "overridden": target_overridden,
        "display": (
            f"Target {target_months:g} tháng"
            + (
                f" (override; gợi ý {suggested['months']:g} — {suggested['source_label']})"
                if target_overridden
                else f" ({suggested['source_label']})"
            )
        ),
    }

    return {
        "basis": basis,
        "basis_label": basis_label,
        "display_unit": display_unit,
        "display_unit_label": unit_label,
        "default_mh": default_mh,
        "target_months": float(target_months),
        "target_months_meta": target_meta,
        "suggested_target_months": float(suggested["months"]),
        "mh_per_manday": MH_PER_MANDAY,
        "mh_per_manmonth": MH_PER_MANMONTH,
        "size_default_mh": dict(SIZE_DEFAULT_MH),
        "totals": {
            **{k: (round(v, 2) if isinstance(v, float) else v) for k, v in totals.items()},
            "display_total": _convert(totals["mh_total"], display_unit),
            "display_remaining": _convert(totals["mh_remaining"], display_unit),
            "display_closed": _convert(totals["mh_closed"], display_unit),
            "hire_dev": pools[0]["hire_needed"],
            "hire_impl": pools[1]["hire_needed"],
        },
        "pools": pools,
        "stages": stages,
        "detail": detail,
        "hints": [
            "Lập trình tính riêng; Phân tích / Test / Cấu hình / UAT / Golive gộp pool «Triển khai chung».",
            "Target (tháng) mặc định = còn lại tới Golive / max End mở — có thể ghi đè.",
            "Nhập số người hiện tại theo pool hoặc theo từng công đoạn để ra số cần tuyển thêm.",
            f"1 MD = {MH_PER_MANDAY:g} MH · 1 MM = {MH_PER_MANMONTH:g} MH.",
        ],
    }
