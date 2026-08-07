"""
Shared stalled-task helpers.

Rule nghiệp vụ (2026-08):
  Kẹt giữa 2 phase khi:
  1. Phase trước Status = Closed
  2. Phase sau chưa bắt đầu (None / Open / thiếu phase)
  3. Không yêu cầu End của phase chờ đã quá (nới rule)
  4. Caller nên gate thêm: mọi phase TRƯỚC curr đã Closed/Cancelled
     (`prev_phases_all_closed`) — tránh flag khi Analysis chưa xong
  Loại khỏi stalled khi không còn việc mở:
  - Phase cuối (Golive…) Status = Closed → coi xong toàn trình
  - Hoặc mọi phase trong order đều Closed / Cancelled
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from parser.excel_parser import FunctionRow, PhaseData
from analyzer.overdue import is_done_status, is_phase_overdue

# Phase sau chưa bắt đầu — khớp logic stalled hiện tại.
_NOT_STARTED = (None, "Open")


def phase_stuck_info(
    row: FunctionRow,
    phase_name: str,
    phase_order: list[str],
    today: date,
) -> Optional[dict[str, Any]]:
    """
    BA/UX #8 — function «stuck» ở 1 phase khi chưa Closed và
    (overdue ở phase đó HOẶC stalled từ phase trước sang phase này).

    Returns None nếu không stuck; else dict:
      overdue, stalled, predecessor_phase, predecessor_pd, phase_pd
    """
    pd = row.phases.get(phase_name, PhaseData())
    st = (pd.status or "").strip()
    if st == "Closed":
        return None

    overdue = is_phase_overdue(
        pd, today, row=row, phase_name=phase_name, phase_order=phase_order,
    )
    stalled = False
    pred_name: Optional[str] = None
    pred_pd: Optional[PhaseData] = None
    try:
        pi = phase_order.index(phase_name)
    except ValueError:
        pi = -1
    if pi > 0:
        pred_name = phase_order[pi - 1]
        pred_pd = row.phases.get(pred_name)
        stalled = is_stalled_transition(pred_pd, pd, today)

    if not overdue and not stalled:
        return None
    return {
        "overdue": overdue,
        "stalled": stalled,
        "predecessor_phase": pred_name,
        "predecessor_pd": pred_pd,
        "phase_pd": pd,
    }


def prev_phases_all_closed(row: FunctionRow, phase_names: list[str], curr_idx: int) -> bool:
    """
    True nếu tất cả phase TRƯỚC curr_idx đã Closed (hoặc Cancelled).

    Dùng để đảm bảo không flag stalled ở giữa luồng khi phase đầu chưa xong.
    VD: Analysis In-progress → không xét stalled cho Dev→UAT, UAT→Golive.
    """
    for i in range(curr_idx):
        name = phase_names[i]
        pd = row.phases.get(name)
        st = (pd.status or "").strip() if pd else ""
        if st not in ("Closed", "Cancelled"):
            return False
    return True


def is_fully_closed(row: FunctionRow, phase_names: list[str]) -> bool:
    """
    True nếu function không còn việc mở → loại khỏi stalled.

    Ưu tiên: phase cuối Closed; hoặc mọi phase ∈ {Closed, Cancelled}.
    """
    if not phase_names:
        return False

    last_pd = row.phases.get(phase_names[-1])
    if last_pd is not None and (last_pd.status or "").strip() == "Closed":
        return True

    for name in phase_names:
        pd = row.phases.get(name)
        st = pd.status if pd else None
        if not is_done_status(st):
            return False
    return True


def waiting_phase_deadline_passed(
    next_pd: Optional[PhaseData],
    today: date,
) -> bool:
    """
    True nếu phase chờ có End và End < today (đã quá hạn).

    Không End / thiếu phase → False (không stalled chỉ vì predecessor Closed).
    """
    if next_pd is None or next_pd.end_date is None:
        return False
    return next_pd.end_date < today


def is_stalled_transition(
    curr_pd: Optional[PhaseData],
    next_pd: Optional[PhaseData],
    today: date,
) -> bool:
    """
    Phase trước Closed + phase sau chưa bắt đầu (None / Open) = đình trệ.

    Đồng bộ gate Start với unassigned (PRM.FR.53):
    Dev Start tương lai → chưa đình trễ dù Analysis đã Closed.
    """
    curr_done = curr_pd is not None and (curr_pd.status or "").strip() == "Closed"
    if not curr_done:
        return False
    if next_pd is None:
        return True
    from analyzer.unassigned import has_phase_start_arrived
    if not has_phase_start_arrived(next_pd, today):
        return False
    if is_done_status(next_pd.status):
        return False
    next_not_started = (next_pd.status in _NOT_STARTED) or (
        (next_pd.status or "").strip() == ""
    )
    return next_not_started
