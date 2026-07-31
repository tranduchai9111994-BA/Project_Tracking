"""
Shared stalled-task helpers.

Rule nghiệp vụ:
  Kẹt giữa 2 phase = phase trước Closed, phase sau None/Open.
  Loại khỏi stalled khi không còn việc mở:
  - Phase cuối (Golive…) Status = Closed → coi xong toàn trình
  - Hoặc mọi phase trong order đều Closed / Cancelled
  Blank không tính done — Analysis Closed + Dev blank vẫn có thể stalled
  (trừ khi phase cuối đã Closed).
"""
from __future__ import annotations

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


def is_stalled_transition(
    curr_pd: Optional[PhaseData],
    next_pd: Optional[PhaseData],
) -> bool:
    """Phase trước Closed và phase sau chưa bắt đầu (None/Open / thiếu phase)."""
    curr_done = curr_pd is not None and (curr_pd.status or "").strip() == "Closed"
    next_not_started = (next_pd is None) or (next_pd.status in _NOT_STARTED)
    return bool(curr_done and next_not_started)
