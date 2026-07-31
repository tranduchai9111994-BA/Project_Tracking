"""
Shared unassigned / missing-PIC helpers.

Rule nghiệp vụ:
  Phase sau chỉ bắt buộc có PIC (+ deadline nếu cùng chiều) khi phase
  liền trước trong chuỗi đã Closed. Phase đầu: flag khi đang in-scope
  (có status hoặc Start/End) mà thiếu PIC — không flag nếu hoàn toàn blank.
"""
from __future__ import annotations

from typing import Optional

from parser.excel_parser import FunctionRow, PhaseData
from analyzer.overdue import is_done_status


def is_phase_in_scope(pd: PhaseData) -> bool:
    """Phase cần theo dõi: chưa Closed/Cancelled + có dấu hiệu plan/làm."""
    if is_done_status(pd.status):
        return False
    return bool(pd.status) or pd.start_date is not None or pd.end_date is not None


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
) -> bool:
    """True nếu phase thiếu PIC và đã tới lượt (predecessor Closed / phase đầu)."""
    if pd.pics:
        return False
    if not is_phase_in_scope(pd):
        return False
    return is_predecessor_closed(row, phase_name, phase_order)


def is_missing_deadline_phase(
    row: FunctionRow,
    phase_name: str,
    pd: PhaseData,
    phase_order: list[str],
    *,
    require_active_status: bool = True,
) -> bool:
    """
    Thiếu End/deadline khi phase đã tới lượt.

    Mặc định giữ DQ cũ: chỉ khi status thuộc Open/Assigned/In-progress/
    Resolved/Pending (WIP) — cộng thêm gate predecessor Closed.
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
    return is_predecessor_closed(row, phase_name, phase_order)
