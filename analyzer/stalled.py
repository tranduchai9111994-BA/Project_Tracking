"""
Shared stalled-task helpers.

Rule nghiệp vụ:
  Kẹt giữa 2 phase khi ALL:
  1. Phase trước Status = Closed
  2. Phase sau chưa bắt đầu (None / Open / thiếu phase)
  3. Deadline (End) của phase chờ đã quá: end < today
     (cùng convention overdue). Không có End → không stalled
     (tránh false positive «chưa plan» / deadline chưa tới).
  Loại khỏi stalled khi không còn việc mở:
  - Phase cuối (Golive…) Status = Closed → coi xong toàn trình
  - Hoặc mọi phase trong order đều Closed / Cancelled
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from parser.excel_parser import FunctionRow, PhaseData
from analyzer.overdue import is_done_status

# Phase sau chưa bắt đầu — khớp logic stalled hiện tại.
_NOT_STARTED = (None, "Open")


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
    Phase trước Closed, phase sau chưa bắt đầu, và End phase chờ đã quá hạn.
    """
    curr_done = curr_pd is not None and (curr_pd.status or "").strip() == "Closed"
    next_not_started = (next_pd is None) or (next_pd.status in _NOT_STARTED)
    if not (curr_done and next_not_started):
        return False
    return waiting_phase_deadline_passed(next_pd, today)
