"""
Function Traceability — Tra cứu full lifecycle 1 chức năng (Task 1).

Cung cấp 2 API chính cho BA:
- search_functions(data, query, limit): autocomplete theo mã CN / tên / quy trình / module
- get_function_detail(data, row_num, today): full lifecycle của 1 function
  (meta + phases theo thứ tự + summary: đang ở phase nào, có trễ không, next deadline)

Auto-detect toàn bộ từ `ParsedData` — không hardcode cột.
Overdue theo `.cursorrules`: End < today AND status ∉ {Closed, Cancelled}.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any, Optional

from parser.excel_parser import ParsedData, FunctionRow, PhaseGroup, PhaseData


# Status coi là đã "khoá" phase — không tính overdue, không tính là next deadline
CLOSED_STATUSES = {"closed", "cancelled"}


def _iso(d: Optional[date | datetime]) -> Optional[str]:
    """Serialize date/datetime → 'YYYY-MM-DD' (bỏ time nếu có). None → None."""
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date().isoformat()
    if isinstance(d, date):
        return d.isoformat()
    return str(d)


def _to_date(d: Optional[date | datetime]) -> Optional[date]:
    """Normalize date/datetime → date (bỏ time)."""
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return None


def _is_phase_closed(status: Optional[str]) -> bool:
    if not status:
        return False
    return status.strip().lower() in CLOSED_STATUSES


def _is_phase_overdue(pd: PhaseData, today: date) -> bool:
    """
    Theo `.cursorrules`: overdue = End date < today AND status ∉ {Closed, Cancelled}.
    Nếu không có End date → không tính overdue.
    """
    end = _to_date(pd.end_date)
    if end is None:
        return False
    if _is_phase_closed(pd.status):
        return False
    return end < today


def _match_query(row: FunctionRow, q_lower: str) -> bool:
    """Match substring trong ma_cn / ten_cn / module / quy_trinh (case-insensitive)."""
    if not q_lower:
        return False
    parts = [
        str(row.meta.get("ma_cn") or ""),
        str(row.meta.get("ten_cn") or ""),
        str(row.meta.get("module") or ""),
        str(row.meta.get("quy_trinh") or ""),
    ]
    hay = " ".join(parts).lower()
    return q_lower in hay


def search_functions(data: ParsedData, query: str, limit: int = 10) -> list[dict]:
    """
    Autocomplete: trả top `limit` function match `query`.

    Match theo substring trên ma_cn + ten_cn + module + quy_trinh. Ưu tiên:
    1. Match ở đầu ma_cn (exact-prefix)
    2. Match ở đầu ten_cn (exact-prefix)
    3. Match substring bất kỳ
    """
    q = (query or "").strip().lower()
    if not q or len(q) < 1:
        return []

    prefix_ma: list[dict] = []
    prefix_ten: list[dict] = []
    substr_hits: list[dict] = []

    for row in data.rows:
        ma = str(row.meta.get("ma_cn") or "").lower()
        ten = str(row.meta.get("ten_cn") or "").lower()

        if not _match_query(row, q):
            continue

        item = {
            "row_num": row.row_num,
            "ma_cn": row.meta.get("ma_cn") or "",
            "ten_cn": row.meta.get("ten_cn") or "",
            "module": row.meta.get("module") or "",
            "quy_trinh": row.meta.get("quy_trinh") or "",
            "priority": row.meta.get("priority") or "",
            "fit_gap": row.meta.get("fit_gap") or "",
        }
        if ma.startswith(q):
            prefix_ma.append(item)
        elif ten.startswith(q):
            prefix_ten.append(item)
        else:
            substr_hits.append(item)

        # Sớm dừng nếu đã đủ ở bucket ưu tiên nhất
        if len(prefix_ma) >= limit:
            break

    combined = (prefix_ma + prefix_ten + substr_hits)[:limit]
    return combined


def _phase_detail(pg: PhaseGroup, pd: PhaseData, today: date) -> dict:
    """Convert 1 (PhaseGroup, PhaseData) → dict cho FE, thêm derived fields."""
    start = _to_date(pd.start_date)
    end = _to_date(pd.end_date)
    duration_days: Optional[int] = None
    if start and end and end >= start:
        duration_days = (end - start).days

    days_to_end: Optional[int] = None
    if end is not None:
        days_to_end = (end - today).days  # âm = quá deadline, dương = còn X ngày

    return {
        "name": pg.name,
        "task_type": pg.task_type,           # tiếng Việt: "Phân tích" / "Lập trình"...
        "start_date": _iso(pd.start_date),
        "end_date": _iso(pd.end_date),
        "status": pd.status or "",
        "pics": list(pd.pics or []),
        "estimate_mh": pd.estimate_mh,
        "note": pd.note,
        "is_closed": _is_phase_closed(pd.status),
        "is_overdue": _is_phase_overdue(pd, today),
        "duration_days": duration_days,
        "days_to_end": days_to_end,
    }


def _find_row(data: ParsedData, row_num: int) -> Optional[FunctionRow]:
    for r in data.rows:
        if r.row_num == row_num:
            return r
    return None


def _summarize(phases: list[dict], meta: dict) -> dict:
    """
    Tính summary cho function:
    - current_phase: phase đầu tiên có Start hoặc Status nhưng chưa Closed.
      Nếu tất cả đều Closed → "Đã hoàn thành". Nếu chưa phase nào bắt đầu → "Chưa khởi động".
    - is_overdue: có ÍT NHẤT 1 phase overdue.
    - next_deadline: end_date sớm nhất trong các phase chưa Closed (chưa qua thì positive,
      quá thì negative).
    - total_estimate_mh: tổng estimate_mh non-None.
    - closed_count / total_phases_with_data: số phase Closed / số phase có data.
    """
    closed_count = 0
    started_count = 0
    total_est = 0.0
    est_seen = False
    any_overdue = False
    current_phase: Optional[str] = None
    next_deadline: Optional[str] = None
    days_to_next: Optional[int] = None
    days_overdue_max = 0

    for ph in phases:
        if ph["is_closed"]:
            closed_count += 1
        if ph["status"] or ph["start_date"] or ph["end_date"]:
            started_count += 1
        if isinstance(ph["estimate_mh"], (int, float)):
            total_est += float(ph["estimate_mh"])
            est_seen = True
        if ph["is_overdue"]:
            any_overdue = True
            # ngày quá deadline nhiều nhất (dùng end < today)
            if ph["days_to_end"] is not None and ph["days_to_end"] < 0:
                days_overdue_max = max(days_overdue_max, -ph["days_to_end"])

    # current_phase = phase đầu tiên chưa Closed nhưng đã có Start/Status
    for ph in phases:
        if not ph["is_closed"] and (ph["status"] or ph["start_date"]):
            current_phase = ph["task_type"]
            break

    if current_phase is None:
        if phases and all(ph["is_closed"] for ph in phases if ph["status"] or ph["start_date"]):
            # Có phase đã Closed nhưng phase còn lại chưa bắt đầu → tùy trạng thái
            if started_count > 0 and closed_count == started_count:
                current_phase = "Đã hoàn thành"
            else:
                current_phase = "Chưa khởi động"
        else:
            current_phase = "Chưa khởi động"

    # next_deadline: end_date sớm nhất trong các phase chưa Closed & còn tương lai
    upcoming = [
        (ph["end_date"], ph["days_to_end"])
        for ph in phases
        if not ph["is_closed"] and ph["end_date"] and ph["days_to_end"] is not None
    ]
    if upcoming:
        upcoming.sort(key=lambda t: t[0])
        next_deadline, days_to_next = upcoming[0]

    return {
        "current_phase": current_phase,
        "is_overdue": any_overdue,
        "days_overdue_max": days_overdue_max,
        "next_deadline": next_deadline,
        "days_to_next_deadline": days_to_next,
        "total_estimate_mh": round(total_est, 2) if est_seen else None,
        "closed_count": closed_count,
        "phases_with_data": started_count,
        "total_phases": len(phases),
    }


def get_function_detail(
    data: ParsedData,
    row_num: int,
    today: Optional[date] = None,
) -> Optional[dict]:
    """
    Trả full lifecycle 1 function theo `row_num` (số dòng Excel gốc).
    Trả None nếu không tìm thấy.
    """
    row = _find_row(data, row_num)
    if row is None:
        return None

    if today is None:
        today = date.today()

    # Meta — chỉ trả các key có giá trị (giữ nguyên keys từ META_KEYWORDS)
    # Giá trị datetime → iso string, còn lại để nguyên (str / int / float / None).
    meta_out: dict[str, Any] = {}
    for k, v in row.meta.items():
        if v is None:
            continue
        if isinstance(v, (datetime, date)):
            meta_out[k] = _iso(v)
        else:
            meta_out[k] = v

    # Phases — theo thứ tự phase_groups của file gốc
    phases_out: list[dict] = []
    for pg in data.phase_groups:
        pd = row.phases.get(pg.name) or PhaseData()
        phases_out.append(_phase_detail(pg, pd, today))

    summary = _summarize(phases_out, meta_out)

    return {
        "row_num": row_num,
        "meta": meta_out,
        "phases": phases_out,
        "summary": summary,
    }
