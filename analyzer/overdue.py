"""
Shared overdue helpers — đồng bộ dashboard / drill / gantt / charts.

Rule gốc (.cursorrules):
  - Có End date
  - End < today
  - Status KHÔNG phải Closed / Cancelled
  - Status blank/None VẪN overdue (user quên cập nhật status)

Ngoại lệ false-positive (sync iHRP Task Daily):
  Status blank NHƯNG một phase SAU đó đã Closed/Cancelled
  → không overdue. API nguồn thường để `stages.uat.status` rỗng
  trong khi Golive đã Closed (TMS.FR.84).
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from parser.excel_parser import FunctionRow, PhaseData

_DONE = frozenset({"closed", "cancelled"})


def is_done_status(status: Optional[str]) -> bool:
    """Closed / Cancelled (case-insensitive, trim). Blank → False."""
    if not status:
        return False
    return status.strip().lower() in _DONE


def is_phase_overdue(
    pd: PhaseData,
    today: date,
    *,
    row: Optional[FunctionRow] = None,
    phase_name: Optional[str] = None,
    phase_order: Optional[list[str]] = None,
) -> bool:
    """
    Phase có overdue không.

    Nếu `row` + `phase_name` + `phase_order` được truyền và status blank:
    bỏ qua khi bất kỳ phase sau trong `phase_order` đã Closed/Cancelled.
    """
    if pd.end_date is None:
        return False
    if is_done_status(pd.status):
        return False
    if pd.end_date >= today:
        return False

    # Blank status + later phase done → không overdue
    if not (pd.status or "").strip() and row is not None and phase_name and phase_order:
        try:
            idx = phase_order.index(phase_name)
        except ValueError:
            return True
        for later_name in phase_order[idx + 1:]:
            later_pd = row.phases.get(later_name)
            if later_pd is not None and is_done_status(later_pd.status):
                return False
    return True


def row_has_overdue(
    row: FunctionRow,
    today: date,
    phase_order: Optional[list[str]] = None,
) -> bool:
    """True nếu bất kỳ phase nào của function overdue."""
    order = phase_order or list(row.phases.keys())
    return any(
        is_phase_overdue(
            pd, today, row=row, phase_name=name, phase_order=order,
        )
        for name, pd in row.phases.items()
    )
