"""
PIC × upcoming weeks — bảng nhìn tới: mỗi PIC, số task đến hạn theo tuần.

Dựa trên Start/End + PIC của từng phase (không Closed/Cancelled).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Optional

from parser.excel_parser import ParsedData, VALID_STATUSES

_DONE = frozenset({"closed", "cancelled"})


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _norm_status(status: Any) -> str:
    if status is None:
        return ""
    s = str(status).strip()
    if not s or s.isdigit():
        return ""
    for v in VALID_STATUSES:
        if s.lower() == v.lower():
            return v
    return s


def compute_pic_upcoming_weeks(
    data: ParsedData,
    *,
    weeks: int = 4,
    today: Optional[date] = None,
) -> dict[str, Any]:
    """
    Return:
      {
        weeks: [{key, label, monday, sunday}],
        pics: [str],
        matrix: {pic: {week_key: count}},
        items: [{pic, week_key, ma_cn, ten_cn, module, phase, start, end, status}],
        totals: {pic: total, week_key: total},
      }
    """
    today = today or date.today()
    n = max(1, min(int(weeks or 4), 12))
    mon0 = _monday_of(today)

    week_defs: list[dict] = []
    for i in range(n):
        mon = mon0 + timedelta(weeks=i)
        sun = mon + timedelta(days=6)
        key = mon.isoformat()
        week_defs.append({
            "key": key,
            "label": f"W{mon.isocalendar()[1]:02d}",
            "monday": mon.isoformat(),
            "sunday": sun.isoformat(),
            "range_label": f"{mon.strftime('%d/%m')}–{sun.strftime('%d/%m')}",
        })

    week_by_key = {w["key"]: w for w in week_defs}
    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    items: list[dict] = []
    pic_totals: dict[str, int] = defaultdict(int)
    week_totals: dict[str, int] = defaultdict(int)

    for row in data.rows:
        ma = str(row.meta.get("ma_cn") or "")
        ten = str(row.meta.get("ten_cn") or "")
        module = str(row.meta.get("module") or "")
        for phase_name, pd in row.phases.items():
            st = _norm_status(pd.status)
            if st.lower() in _DONE:
                continue
            end = pd.end_date
            start = pd.start_date
            # Due = End nếu có; fallback Start nếu chỉ có Start trong cửa sổ
            due = end or start
            if due is None:
                continue
            # Chỉ tuần sắp tới (từ monday tuần này)
            if due < mon0 or due > mon0 + timedelta(weeks=n):
                continue
            due_mon = _monday_of(due)
            wk = due_mon.isoformat()
            if wk not in week_by_key:
                continue
            pics = [p for p in (pd.pics or []) if p]
            if not pics:
                pics = ["(Chưa PIC)"]
            for pic in pics:
                matrix[pic][wk] += 1
                pic_totals[pic] += 1
                week_totals[wk] += 1
                items.append({
                    "pic": pic,
                    "week_key": wk,
                    "ma_cn": ma,
                    "ten_cn": ten,
                    "module": module,
                    "phase": phase_name,
                    "start": start.isoformat() if start else "",
                    "end": end.isoformat() if end else "",
                    "status": st or "(trống)",
                })

    pics_sorted = sorted(matrix.keys(), key=lambda p: (-pic_totals[p], p.lower()))
    return {
        "weeks": week_defs,
        "pics": pics_sorted,
        "matrix": {p: dict(matrix[p]) for p in pics_sorted},
        "items": items,
        "totals": {
            "by_pic": dict(pic_totals),
            "by_week": dict(week_totals),
            "grand": sum(pic_totals.values()),
        },
        "today": today.isoformat(),
    }
