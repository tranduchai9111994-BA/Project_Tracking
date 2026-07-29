"""
Task 10 — Kanban theo tuần: chia rows thành 6 nhóm theo ngữ cảnh tuần này.

Logic priority (mỗi row chỉ vào 1 cột, theo thứ tự check):
  1. done_this_week   ✅ Đã xong tuần này (all phases Closed & latest end ∈ tuần này)
  2. overdue          🔴 Quá hạn (End < today, chưa Closed) — trong tuần này
  3. carryover        ⚠️ Tuần trước chưa xong (End < Monday tuần này, chưa Closed)
  4. in_progress      🔄 Đang làm (có phase In-progress)
  5. next_week        📅 Tuần sau (earliest Start ∈ tuần sau)
  6. not_started      ⏸ Chưa làm (default fallback)
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from parser.excel_parser import ParsedData, FunctionRow
from analyzer.generic_chart import (
    _row_earliest_start, _row_latest_end, _row_overall_status,
    _row_is_closed, _row_is_overdue, _row_pics_all,
)


def _monday_of(d: date) -> date:
    """Monday của tuần chứa d (ISO: Monday=0)."""
    return d - timedelta(days=d.weekday())


def _week_bounds(today: date, offset_weeks: int = 0) -> tuple[date, date]:
    """Return (Monday, Sunday) của tuần today + offset."""
    mon = _monday_of(today) + timedelta(weeks=offset_weeks)
    sun = mon + timedelta(days=6)
    return mon, sun


def _row_in_progress(row: FunctionRow) -> bool:
    for pd in row.phases.values():
        if (pd.status or "").strip().lower() == "in-progress":
            return True
    return False


def _row_current_phase_name(row: FunctionRow) -> tuple[str, str]:
    """(phase_name, status) — phase đang In-progress nếu có; else phase mới nhất."""
    ip = None
    latest = None
    latest_start = None
    for pn, pd in row.phases.items():
        st = (pd.status or "").strip()
        if st.lower() == "in-progress":
            ip = (pn, st)
        if pd.start_date and (latest_start is None or pd.start_date > latest_start):
            latest_start = pd.start_date
            latest = (pn, st or "")
    if ip:
        return ip
    return latest or ("", "")


def _row_next_deadline(row: FunctionRow, today: date) -> Optional[date]:
    """End date gần nhất trong tương lai (hoặc quá khứ nếu chưa Closed)."""
    for pd in row.phases.values():
        if pd.end_date:
            st = (pd.status or "").strip().lower()
            if st in ("closed", "cancelled"):
                continue
            return pd.end_date
    return None


def _row_to_card(row: FunctionRow, today: date, pic_role_map: dict[str, str]) -> dict:
    meta = row.meta or {}
    phase_name, phase_status = _row_current_phase_name(row)
    pics = _row_pics_all(row)
    roles = sorted({pic_role_map.get(p, "") for p in pics if pic_role_map.get(p)})
    deadline = _row_next_deadline(row, today)
    aging_days = None
    if deadline and deadline < today:
        aging_days = (today - deadline).days
    return {
        "row_num": row.row_num,
        "ma_cn": str(meta.get("ma_cn") or ""),
        "ten_cn": str(meta.get("ten_cn") or "")[:120],
        "module": str(meta.get("module") or ""),
        "process": str(meta.get("process") or ""),
        "priority": str(meta.get("priority") or ""),
        "complexity": str(meta.get("complexity") or ""),
        "phase": phase_name,
        "phase_status": phase_status,
        "pics": pics,
        "roles": roles,
        "deadline_iso": deadline.isoformat() if deadline else None,
        "aging_days": aging_days,
        "is_overdue": _row_is_overdue(row, today),
        "is_closed": _row_is_closed(row),
    }


def _card_passes_filters(card: dict, f: dict) -> bool:
    """Filter mini bar: modules/processes/pics/roles/search."""
    if not f:
        return True
    if f.get("modules") and card["module"] not in f["modules"]:
        return False
    if f.get("processes") and card["process"] not in f["processes"]:
        return False
    if f.get("pics"):
        if not any(p in f["pics"] for p in card["pics"]):
            return False
    if f.get("roles"):
        if not any(r in f["roles"] for r in card["roles"]):
            return False
    q = (f.get("search") or "").strip().lower()
    if q:
        blob = " ".join([card["ma_cn"], card["ten_cn"], card["module"], card["process"]]).lower()
        if q not in blob:
            return False
    return True


def compute_kanban(
    data: ParsedData,
    today: Optional[date] = None,
    week_offset: int = 0,
    pic_role_map: Optional[dict[str, str]] = None,
    filters: Optional[dict] = None,
) -> dict:
    today = today or date.today()
    pic_role_map = pic_role_map or {}
    filters = filters or {}
    mon, sun = _week_bounds(today, week_offset)
    prev_mon = mon - timedelta(days=7)
    next_mon = mon + timedelta(days=7)
    next_sun = next_mon + timedelta(days=6)

    buckets = {
        "done_this_week": [],
        "overdue": [],
        "carryover": [],
        "in_progress": [],
        "next_week": [],
        "not_started": [],
    }

    for r in data.rows:
        card = _row_to_card(r, today, pic_role_map)
        if not _card_passes_filters(card, filters):
            continue
        earliest = _row_earliest_start(r)
        latest = _row_latest_end(r)

        # 1. Done this week
        if _row_is_closed(r) and latest and mon <= latest <= sun:
            buckets["done_this_week"].append(card)
            continue
        # 2. Carryover (past week's tail)
        if latest and latest < mon and not _row_is_closed(r):
            buckets["carryover"].append(card)
            continue
        # 3. Overdue (in this week)
        if _row_is_overdue(r, today):
            buckets["overdue"].append(card)
            continue
        # 4. In progress
        if _row_in_progress(r):
            buckets["in_progress"].append(card)
            continue
        # 5. Next week
        if earliest and next_mon <= earliest <= next_sun:
            buckets["next_week"].append(card)
            continue
        # 6. Fallback: not started
        buckets["not_started"].append(card)

    # Sort mỗi bucket theo deadline asc (None sau)
    for k in buckets:
        buckets[k].sort(key=lambda c: (c["deadline_iso"] or "9999-99-99", c["ma_cn"] or "zzz"))

    return {
        "week": {
            "monday_iso": mon.isoformat(),
            "sunday_iso": sun.isoformat(),
            "week_offset": week_offset,
            "today_iso": today.isoformat(),
        },
        "columns": [
            {"key": "not_started", "title": "⏸ Chưa làm",       "count": len(buckets["not_started"]),   "cards": buckets["not_started"]},
            {"key": "in_progress", "title": "🔄 Đang làm",       "count": len(buckets["in_progress"]),   "cards": buckets["in_progress"]},
            {"key": "overdue",     "title": "🔴 Quá hạn",         "count": len(buckets["overdue"]),       "cards": buckets["overdue"]},
            {"key": "done_this_week", "title": "✅ Xong tuần này",  "count": len(buckets["done_this_week"]), "cards": buckets["done_this_week"]},
            {"key": "next_week",   "title": "📅 Tuần sau",        "count": len(buckets["next_week"]),     "cards": buckets["next_week"]},
            {"key": "carryover",   "title": "⚠️ Tuần trước chưa xong", "count": len(buckets["carryover"]), "cards": buckets["carryover"]},
        ],
        "total_after_filter": sum(len(b) for b in buckets.values()),
    }


def unique_pics(data: ParsedData) -> list[str]:
    """List unique PIC từ tất cả rows (sort alphabet)."""
    s: set[str] = set()
    for r in data.rows:
        s.update(_row_pics_all(r))
    return sorted(s)
