"""
Rlog weekly dashboard — số Rlog coded tuần này + kế hoạch code tuần tới.

Định nghĩa (từ dữ liệu Function List thực tế MPHG):
  - Rlog = function có giá trị ở attribute phase chứa "Rlog" (thường
    ``Analysis - RlogID``). Nếu file không có cột Rlog nào có data →
    fallback: mọi function (dashboard vẫn dùng được).
  - Coded tuần này = phase Dev (auto-detect tên chứa dev/coding/lập trình)
    Status = Closed và End date ∈ tuần ISO hiện tại (Mon–Sun).
  - Kế hoạch tuần tới = Dev chưa Closed/Cancelled và (End ∈ tuần tới
    HOẶC khoảng Start–End giao tuần tới).
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from parser.excel_parser import ParsedData, FunctionRow, PhaseData, VALID_STATUSES

# Reuse keyword Dev từ kanban (tránh drift).
from analyzer.kanban import _phase_is_dev

_RLOG_KEY_RE = ("rlog", "r-log", "r_log")
_DONE = frozenset({"closed", "cancelled"})


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _week_bounds(today: date, offset_weeks: int = 0) -> tuple[date, date]:
    """(Monday, Sunday) của tuần ISO chứa today + offset."""
    mon = _monday_of(today) + timedelta(weeks=offset_weeks)
    return mon, mon + timedelta(days=6)


def _iso_week_label(d: date) -> str:
    return f"W{d.isocalendar()[1]:02d}"


def _normalize_status(status: Any) -> str:
    if status is None:
        return ""
    s = str(status).strip()
    if not s or s.isdigit():
        return ""
    for valid in VALID_STATUSES:
        if s.lower() == valid.lower():
            return valid
    return s


def _normalize_date_pair(
    start: Optional[date], end: Optional[date]
) -> tuple[Optional[date], Optional[date], bool]:
    """Swap nếu Start > End (bug FL phổ biến)."""
    if start is None or end is None:
        return start, end, False
    if start > end:
        return end, start, True
    return start, end, False


def _ranges_overlap(
    a_start: Optional[date],
    a_end: Optional[date],
    b_start: date,
    b_end: date,
) -> bool:
    if a_start is None and a_end is None:
        return False
    s = a_start if a_start is not None else a_end
    e = a_end if a_end is not None else a_start
    assert s is not None and e is not None
    return s <= b_end and e >= b_start


def _is_rlog_attr(name: str) -> bool:
    n = (name or "").strip().lower().replace(" ", "")
    return any(k.replace("-", "").replace("_", "") in n.replace("-", "").replace("_", "")
               for k in _RLOG_KEY_RE) or "rlog" in n


def _row_rlog_id(row: FunctionRow) -> Optional[str]:
    """Lấy RlogID đầu tiên tìm thấy trong phase.extra (auto-detect key)."""
    for _pn, pd in (row.phases or {}).items():
        for k, v in (pd.extra or {}).items():
            if not _is_rlog_attr(str(k)):
                continue
            if v is None:
                continue
            s = str(v).strip()
            if s:
                return s
    return None


def _file_has_rlog_column(data: ParsedData) -> bool:
    """True nếu phase_groups có attribute tên chứa Rlog (kể cả cột trống)."""
    for pg in (data.phase_groups or []):
        attrs = getattr(pg, "attributes", None) or {}
        for name in attrs:
            if _is_rlog_attr(str(name)):
                return True
    # Pickle cũ / sync thiếu phase_groups attrs → scan extras trên rows
    for r in data.rows[:50]:
        if _row_rlog_id(r):
            return True
    return False


def _any_row_has_rlog_id(data: ParsedData) -> bool:
    return any(_row_rlog_id(r) for r in data.rows)


def _find_dev_phase(row: FunctionRow) -> tuple[Optional[str], Optional[PhaseData]]:
    for pn, pd in (row.phases or {}).items():
        if _phase_is_dev(pn):
            return pn, pd
    return None, None


def _fmt_iso(d: Optional[date]) -> str:
    return d.isoformat() if d else ""


def _item_from_row(
    row: FunctionRow,
    *,
    phase_name: str,
    pd: PhaseData,
    rlog_id: Optional[str],
    start: Optional[date],
    end: Optional[date],
) -> dict[str, Any]:
    meta = row.meta or {}
    return {
        "ma_cn": str(meta.get("ma_cn") or ""),
        "ten_cn": str(meta.get("ten_cn") or ""),
        "module": str(meta.get("module") or ""),
        "pic": list(pd.pics or []),
        "rlog_id": rlog_id or "",
        "phase": phase_name,
        "status": _normalize_status(pd.status),
        "start_date": _fmt_iso(start),
        "end_date": _fmt_iso(end),
        "closed_date": _fmt_iso(end) if _normalize_status(pd.status) == "Closed" else "",
    }


def compute_rlog_weekly(
    data: ParsedData,
    today: Optional[date] = None,
) -> dict[str, Any]:
    """
    Trả payload:
      rlog_coded_this_week: {count, items}
      rlog_plan_next_week: {count, items}
      + metadata định nghĩa / tuần ISO.
    """
    today = today or date.today()
    this_mon, this_sun = _week_bounds(today, 0)
    next_mon, next_sun = _week_bounds(today, 1)

    col_detected = _file_has_rlog_column(data)
    has_filled = _any_row_has_rlog_id(data)
    # Scope: có RlogID filled → chỉ đếm row có RlogID; không → mọi function.
    scope = "with_rlog_id" if has_filled else "all_functions"

    coded: list[dict] = []
    plan: list[dict] = []

    for row in data.rows:
        rlog_id = _row_rlog_id(row)
        if scope == "with_rlog_id" and not rlog_id:
            continue

        phase_name, pd = _find_dev_phase(row)
        if not pd or not phase_name:
            continue

        st = _normalize_status(pd.status)
        start, end, _swapped = _normalize_date_pair(pd.start_date, pd.end_date)

        # 1) Coded tuần này
        if st == "Closed" and end is not None and this_mon <= end <= this_sun:
            coded.append(_item_from_row(
                row, phase_name=phase_name, pd=pd, rlog_id=rlog_id,
                start=start, end=end,
            ))
            continue  # đã closed tuần này → không vào plan

        # 2) Kế hoạch tuần tới (blank status vẫn tính nếu có ngày giao tuần)
        if st in ("Closed", "Cancelled"):
            continue
        if not _ranges_overlap(start, end, next_mon, next_sun):
            continue

        end_in = end is not None and next_mon <= end <= next_sun
        start_in = start is not None and next_mon <= start <= next_sun
        priority = 0 if end_in else (1 if start_in else 2)
        item = _item_from_row(
            row, phase_name=phase_name, pd=pd, rlog_id=rlog_id,
            start=start, end=end,
        )
        item["_priority"] = priority
        item["_sort_end"] = end or date.max
        plan.append(item)

    coded.sort(key=lambda x: (x.get("end_date") or "", x.get("ma_cn") or ""))
    plan.sort(key=lambda x: (x.pop("_priority", 9), x.pop("_sort_end", date.max), x.get("ma_cn") or ""))

    if scope == "with_rlog_id":
        definition = (
            "Rlog = function có RlogID (cột phase auto-detect chứa 'Rlog', "
            "thường Analysis - RlogID). Coded tuần này = phase Dev Closed và "
            "End ∈ tuần ISO hiện tại. Kế hoạch tuần tới = Dev chưa Closed/"
            "Cancelled, deadline hoặc Start–End giao tuần sau."
        )
    else:
        definition = (
            "File không có RlogID (hoặc cột trống) → Rlog = mọi function. "
            "Coded tuần này = phase Dev Closed và End ∈ tuần ISO hiện tại. "
            "Kế hoạch tuần tới = Dev chưa Closed/Cancelled, deadline hoặc "
            "Start–End giao tuần sau."
        )

    return {
        "definition": definition,
        "rlog_column_detected": col_detected,
        "rlog_scope": scope,
        "week": {
            "monday_iso": this_mon.isoformat(),
            "sunday_iso": this_sun.isoformat(),
            "iso_week_label": _iso_week_label(this_mon),
            "today_iso": today.isoformat(),
        },
        "next_week": {
            "monday_iso": next_mon.isoformat(),
            "sunday_iso": next_sun.isoformat(),
            "iso_week_label": _iso_week_label(next_mon),
        },
        "rlog_coded_this_week": {
            "count": len(coded),
            "items": coded,
        },
        "rlog_plan_next_week": {
            "count": len(plan),
            "items": plan,
        },
    }
