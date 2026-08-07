"""
Shared unassigned / missing-PIC helpers.

Rule nghiệp vụ:
  Flag thiếu PIC (+ deadline nếu cùng chiều) khi ALL:
  1. Phase in-scope (chưa Closed/Cancelled + có status hoặc Start/End)
  2. Predecessor gate: phase liền trước Closed (phase đầu: luôn tới lượt)
  3. Start đã đến (start <= today). Không có Start: chỉ khi End <= today
     hoặc status đang làm thật (Open / Assigned / In-progress) — **không**
     gồm "Not Started" đã map sang Open/Assigned (chưa tới ngày bắt đầu).
  Không flag khi Start còn ở tương lai.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from parser.excel_parser import FunctionRow, PhaseData
from analyzer.overdue import is_done_status

# Status coi là "đang làm" khi thiếu Start — fallback cho start gate.
_ACTIVE_NO_START_STATUSES = frozenset({"open", "assigned", "in-progress"})


def is_phase_in_scope(pd: PhaseData) -> bool:
    """Phase cần theo dõi: chưa Closed/Cancelled + có dấu hiệu plan/làm."""
    if is_done_status(pd.status):
        return False
    return bool(pd.status) or pd.start_date is not None or pd.end_date is not None


def has_phase_start_arrived(pd: PhaseData, today: date) -> bool:
    """
    True nếu đã tới thời điểm cần bắt buộc có PIC / deadline.

    - Có Start → ``start <= today`` (Start tương lai → False).
    - Không có Start → End đã đến (``end <= today``) hoặc status
      Open / Assigned / In-progress **thật** (không phải Not Started map sang).
    - ``from_not_started`` + chưa có Start/End tới hạn → False.
      (VD PR.FR.49: Analysis Closed, Dev = Not Started, chưa có Dev Start
      → không đếm thiếu PIC; PRM.FR.53: Dev Start 17/08 > today → False.)
    """
    if pd.start_date is not None:
        return pd.start_date <= today
    if pd.end_date is not None and pd.end_date <= today:
        return True
    # Not Started map → Open/Assigned nhưng chưa phải "đang làm" — đợi Start/End.
    if getattr(pd, "from_not_started", False):
        return False
    st = (pd.status or "").strip().lower()
    return st in _ACTIVE_NO_START_STATUSES


def _is_closed_status(status: Optional[str]) -> bool:
    """Chỉ Closed (không gồm Cancelled) — unlock phase sau."""
    if not status:
        return False
    return status.strip().lower() == "closed"


def is_predecessor_closed(
    row: FunctionRow,
    phase_name: str,
    phase_order: list[str],
) -> bool:
    """
    True nếu phase hiện tại đã tới lượt cần PIC/ngày.

    - Phase đầu trong ``phase_order`` → True (luôn "tới lượt" nếu in-scope).
    - Phase sau → True chỉ khi phase liền trước status == Closed.
    - Phase không có trong order → True (không chặn khi thiếu metadata).
    """
    if not phase_order:
        return True
    try:
        idx = phase_order.index(phase_name)
    except ValueError:
        return True
    if idx == 0:
        return True
    pred_name = phase_order[idx - 1]
    pred_pd = row.phases.get(pred_name)
    if pred_pd is None:
        return False
    return _is_closed_status(pred_pd.status)


def is_unassigned_phase(
    row: FunctionRow,
    phase_name: str,
    pd: PhaseData,
    phase_order: list[str],
    today: date | None = None,
) -> bool:
    """True nếu thiếu PIC + in-scope + predecessor Closed + Start đã đến."""
    if pd.pics:
        return False
    if not is_phase_in_scope(pd):
        return False
    if not is_predecessor_closed(row, phase_name, phase_order):
        return False
    return has_phase_start_arrived(pd, today or date.today())


def is_missing_deadline_phase(
    row: FunctionRow,
    phase_name: str,
    pd: PhaseData,
    phase_order: list[str],
    *,
    today: date | None = None,
    require_active_status: bool = True,
) -> bool:
    """
    Thiếu End/deadline khi phase đã tới lượt và Start đã đến.

    Mặc định giữ DQ cũ: chỉ khi status thuộc Open/Assigned/In-progress/
    Resolved/Pending (WIP) — cộng thêm gate predecessor Closed + Start.
    """
    if pd.end_date is not None:
        return False
    if is_done_status(pd.status):
        return False
    if require_active_status:
        st = (pd.status or "").strip().lower()
        if st not in ("open", "assigned", "in-progress", "resolved", "pending"):
            return False
    elif not is_phase_in_scope(pd):
        return False
    if not is_predecessor_closed(row, phase_name, phase_order):
        return False
    return has_phase_start_arrived(pd, today or date.today())
