"""
Weekly GAP Report — Báo cáo tuần: các phase sẽ hoàn thành trong tuần.

Trả lời câu hỏi: "Tuần này xong được gì?" — functions có phase end_date rơi
trong tuần làm việc (Mon–Fri), có thể filter theo FIT/GAP.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from parser.excel_parser import ParsedData


_EXCLUDE_STATUS = {"Closed", "Cancelled"}
_INPROGRESS_STATUS = {"In-progress", "In progress", "Inprogress"}


def _safe_date(val: Any) -> date | None:
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y"):
            try:
                from datetime import datetime
                return datetime.strptime(val.strip(), fmt).date()
            except ValueError:
                pass
    return None


def _is_outlier(d: date, today: date, max_years: int = 10) -> bool:
    return abs((d - today).days) > max_years * 365


def _get_week_range(today: date, week_offset: int = 0) -> tuple[date, date]:
    """Tính Mon và Fri (workweek Mon–Fri) của tuần (today + offset*7)."""
    target = today + timedelta(weeks=week_offset)
    # weekday(): Mon=0 … Sun=6
    monday = target - timedelta(days=target.weekday())
    friday = monday + timedelta(days=4)
    return monday, friday


def _week_label(week_start: date, week_end: date) -> str:
    week_num = week_start.isocalendar()[1]
    return (
        f"Tuần {week_num} "
        f"({week_start.strftime('%d/%m')}–{week_end.strftime('%d/%m/%Y')})"
    )


def compute_weekly_gap(
    data: ParsedData,
    week_offset: int = 0,
    fitgap_filter: str = "",
) -> dict[str, Any]:
    """
    Quét ParsedData → trả về các function/phase sẽ hoàn thành trong tuần.

    Args:
        data: ParsedData từ parser.
        week_offset: 0 = tuần này, -1 = tuần trước, +1 = tuần sau.
        fitgap_filter: "" / "all" = tất cả; "gap" = chỉ GAP; "fit" = chỉ FIT.

    Returns dict:
        week_label, week_start, week_end, week_offset, fitgap_filter,
        items: [...], summary: {...}
    """
    today = date.today()
    week_start, week_end = _get_week_range(today, week_offset)
    label = _week_label(week_start, week_end)

    fg_norm = (fitgap_filter or "").strip().lower()
    if fg_norm in ("", "all"):
        fg_norm = ""

    items: list[dict[str, Any]] = []

    for row in data.rows:
        ma = str(row.meta.get("ma_cn") or "").strip()
        if not ma:
            continue

        # FIT/GAP filter
        row_fitgap = str(row.meta.get("fitgap") or "").strip().upper()
        if fg_norm == "gap" and row_fitgap != "GAP":
            continue
        if fg_norm == "fit" and row_fitgap != "FIT":
            continue

        for pname, pd in row.phases.items():
            status_raw = str(pd.status or "").strip()

            # Bỏ qua Closed / Cancelled — đã xong hoặc hủy
            if status_raw in _EXCLUDE_STATUS:
                continue

            end = _safe_date(pd.end_date)
            if not end:
                continue
            if _is_outlier(end, today):
                continue

            status_norm = status_raw
            is_inprogress = status_raw in _INPROGRESS_STATUS

            # Điều kiện "sẽ xong tuần này":
            # 1. end_date rơi trong [week_start..week_end]
            # 2. HOẶC In-progress và end_date <= week_end
            in_week = week_start <= end <= week_end
            overrun_inprogress = is_inprogress and end <= week_end

            if not (in_week or overrun_inprogress):
                continue

            start = _safe_date(pd.start_date)
            pic = str(pd.pic or "").strip()
            rlog_id = str(
                row.meta.get("rlog_id") or row.meta.get("fid") or ""
            ).strip()

            items.append({
                "ma_cn": ma,
                "ten_cn": str(row.meta.get("ten_cn") or "").strip(),
                "module": str(row.meta.get("module") or "").strip(),
                "quy_trinh": str(
                    row.meta.get("quy_trinh") or row.meta.get("process") or ""
                ).strip(),
                "fitgap": row_fitgap,
                "rlog_id": rlog_id,
                "phase": pname,
                "start": start.isoformat() if start else "",
                "end": end.isoformat(),
                "status": status_norm,
                "pic": pic,
                "week_label": label,
            })

    # Sort: module → rlog_id → ma_cn → phase
    items.sort(key=lambda x: (
        x["module"],
        x["rlog_id"] or "\xff",
        x["ma_cn"],
        x["phase"],
    ))

    # Summary
    by_phase: dict[str, int] = {}
    by_module: dict[str, int] = {}
    by_fitgap: dict[str, int] = {"GAP": 0, "FIT": 0, "": 0}
    by_status: dict[str, int] = {}

    for it in items:
        by_phase[it["phase"]] = by_phase.get(it["phase"], 0) + 1
        by_module[it["module"]] = by_module.get(it["module"], 0) + 1
        fg_key = it["fitgap"] if it["fitgap"] in ("GAP", "FIT") else ""
        by_fitgap[fg_key] = by_fitgap.get(fg_key, 0) + 1
        by_status[it["status"]] = by_status.get(it["status"], 0) + 1

    return {
        "week_label": label,
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "week_offset": week_offset,
        "fitgap_filter": fitgap_filter,
        "items": items,
        "summary": {
            "total": len(items),
            "by_phase": by_phase,
            "by_module": by_module,
            "by_fitgap": by_fitgap,
            "by_status": by_status,
        },
    }
