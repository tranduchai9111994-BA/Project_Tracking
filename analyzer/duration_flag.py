"""
Duration Flag — phát hiện phase có Start→End kéo dài bất thường.

Nghiệp vụ:
  - Với mỗi function, quét từng phase có cả Start và End date.
  - Nếu (end - start).days > threshold → đưa vào danh sách "thời gian dài".
  - Ngưỡng mặc định: 60 ngày (khoảng 2 tháng).
  - Chỉ phase **chưa hoàn thành** (không Closed / Cancelled) — việc đã
    Closed dài ngày không còn actionable (rule PMO 06/08/2026).
  - Hỗ trợ filter theo module / phase_name.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from parser.excel_parser import ParsedData, FunctionRow
from analyzer.overdue import is_done_status

_DEFAULT_THRESHOLD = 60  # ngày


def _safe_date(val: Any) -> date | None:
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%m/%d/%Y"):
            try:
                from datetime import datetime
                return datetime.strptime(val.strip(), fmt).date()
            except ValueError:
                pass
    return None


def _is_outlier(d: date, today: date, max_years: int = 10) -> bool:
    """Bỏ date outlier quá xa (VD: 1936-03-26 hoặc 2036)."""
    diff = abs((d - today).days)
    return diff > max_years * 365


def compute_long_duration(
    data: ParsedData,
    threshold_days: int = _DEFAULT_THRESHOLD,
    module_filter: str = "",
    phase_filter: str = "",
) -> dict[str, Any]:
    """
    Quét ParsedData → trả về:
      {
        "items": [{
          ma_cn, ten_cn, module, quy_trinh, phase, start, end,
          duration_days, status, pic
        }, ...],
        "summary": {total, by_phase: {phase: count}, avg_days, max_days},
        "threshold_days": int,
        "phases_checked": [str],
      }
    """
    today = date.today()
    phase_names = [pg.name for pg in data.phase_groups]
    items: list[dict[str, Any]] = []

    for row in data.rows:
        if module_filter and row.meta.get("module") != module_filter:
            continue
        ma = str(row.meta.get("ma_cn") or "").strip()
        if not ma:
            continue

        for pname, pd in row.phases.items():
            if phase_filter and pname != phase_filter:
                continue
            status = (pd.status or "").strip()
            # Closed / Cancelled → bỏ (chỉ cảnh báo phase còn mở)
            if is_done_status(status):
                continue

            start = _safe_date(pd.start_date)
            end = _safe_date(pd.end_date)
            if not start or not end:
                continue
            if end <= start:
                continue
            if _is_outlier(start, today) or _is_outlier(end, today):
                continue

            duration = (end - start).days
            if duration <= threshold_days:
                continue

            pic = ", ".join(pd.pics or [])
            items.append({
                "ma_cn": ma,
                "ten_cn": str(row.meta.get("ten_cn") or "").strip(),
                "module": str(row.meta.get("module") or "").strip(),
                "quy_trinh": str(
                    row.meta.get("quy_trinh") or row.meta.get("process") or ""
                ).strip(),
                "phase": pname,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "duration_days": duration,
                "status": status,
                "pic": pic,
            })

    # Sắp xếp giảm dần theo duration_days
    items.sort(key=lambda x: x["duration_days"], reverse=True)

    # Summary
    by_phase: dict[str, int] = {}
    for it in items:
        by_phase[it["phase"]] = by_phase.get(it["phase"], 0) + 1

    durations = [it["duration_days"] for it in items]
    avg = round(sum(durations) / len(durations)) if durations else 0
    mx = max(durations) if durations else 0

    return {
        "items": items,
        "summary": {
            "total": len(items),
            "by_phase": by_phase,
            "avg_days": avg,
            "max_days": mx,
        },
        "threshold_days": threshold_days,
        "phases_checked": phase_names,
    }
