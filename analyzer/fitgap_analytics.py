"""
FIT/GAP Analytics — Section riêng cho BA quản lý lifecycle GAP (Task 2).

Auto-detect cột FIT/GAP theo `.cursorrules` (header chứa "FIT" hoặc "GAP" —
đã handled sẵn ở parser qua META_KEYWORDS["fit_gap"]).

Cung cấp 2 hàm:
- compute_fitgap_analytics(data, today, aging_threshold): cards + 3 chart data
  + aging list
- Aging GAP = GAP function ĐANG MỞ (có ít nhất 1 phase status ∉ Closed/Cancelled),
  aging_days = today - ngày sớm nhất (earliest Start/End của bất kỳ phase nào)
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Any, Optional

from parser.excel_parser import ParsedData, FunctionRow, PhaseData


CLOSED_STATUSES = {"closed", "cancelled"}
DEFAULT_AGING_THRESHOLD_DAYS = 14

# Priority buckets — normalize theo cách gọi thường gặp
_PRIORITY_MAP = {
    "must-have": "Must-have",
    "must have": "Must-have",
    "must": "Must-have",
    "high": "Must-have",
    "should-have": "Should-have",
    "should have": "Should-have",
    "should": "Should-have",
    "medium": "Should-have",
    "could-have": "Could-have",
    "could have": "Could-have",
    "could": "Could-have",
    "low": "Could-have",
}


def _to_date(d) -> Optional[date]:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return None


def _is_gap_value(v: Any) -> bool:
    """
    Check giá trị FIT/GAP có phải "GAP" hay không.
    Chấp nhận biến thể case, whitespace, kèm hyphen (VD "GAP", "gap", "Cust"→False, "Customization"→cũng False).
    Chỉ coi 'GAP' hoặc 'GAP/*' hay '*/GAP' là gap.
    """
    if v is None:
        return False
    s = str(v).strip().upper()
    if not s:
        return False
    # tách theo "/" để cover 'FIT/GAP' style cell
    tokens = [t.strip() for t in s.replace("\\", "/").split("/") if t.strip()]
    return "GAP" in tokens


def _is_fit_value(v: Any) -> bool:
    if v is None:
        return False
    s = str(v).strip().upper()
    if not s:
        return False
    tokens = [t.strip() for t in s.replace("\\", "/").split("/") if t.strip()]
    return "FIT" in tokens


def _is_row_closed_all_phases(row: FunctionRow) -> bool:
    """
    Function được coi là ĐÃ ĐÓNG hoàn toàn khi: tất cả phase có status đều thuộc
    Closed/Cancelled (không có phase nào đang In-progress / Assigned / Open / ...).
    Nếu không có phase nào có status → coi là CHƯA đóng (đang chờ triển khai).
    """
    seen_any_status = False
    for pd in row.phases.values():
        st = (pd.status or "").strip().lower()
        if not st:
            continue
        seen_any_status = True
        if st not in CLOSED_STATUSES:
            return False
    return seen_any_status


def _earliest_activity_date(row: FunctionRow) -> Optional[date]:
    """Ngày sớm nhất có hoạt động (Start hoặc End) trên bất kỳ phase nào của row."""
    dates: list[date] = []
    for pd in row.phases.values():
        d = _to_date(pd.start_date)
        if d:
            dates.append(d)
        d = _to_date(pd.end_date)
        if d:
            dates.append(d)
    return min(dates) if dates else None


def _current_open_phase(row: FunctionRow) -> Optional[str]:
    """
    Trả tên phase đầu tiên (theo thứ tự dict) đang mở (status ∉ Closed/Cancelled).
    Fallback: phase có status nhưng chưa Closed.
    """
    for phase_name, pd in row.phases.items():
        st = (pd.status or "").strip().lower()
        if st and st not in CLOSED_STATUSES:
            return phase_name
    return None


def _row_pics(row: FunctionRow) -> list[str]:
    """Gộp toàn bộ PIC của row (unique, giữ thứ tự xuất hiện)."""
    seen = set()
    out = []
    for pd in row.phases.values():
        for p in (pd.pics or []):
            if p and p not in seen:
                seen.add(p)
                out.append(p)
    return out


def _norm_priority(raw: Optional[str]) -> str:
    """Chuẩn hóa priority về 3 bucket. Không nhận biết → 'Khác'."""
    if not raw:
        return "Khác"
    key = str(raw).strip().lower()
    return _PRIORITY_MAP.get(key, str(raw).strip() or "Khác")


def compute_fitgap_analytics(
    data: ParsedData,
    today: Optional[date] = None,
    aging_threshold_days: int = DEFAULT_AGING_THRESHOLD_DAYS,
) -> dict[str, Any]:
    """
    Tính toàn bộ số liệu cho FIT/GAP Dashboard section.

    Returns:
        {
          "summary": {total, fit, gap, gap_closed, gap_open, gap_open_aging,
                      aging_threshold_days},
          "by_module": [{module, fit, gap, total, pct_gap}],
          "by_process": [{process, fit, gap, total, pct_gap}],
          "by_priority": [{priority, fit, gap, total, pct_gap}],
          "aging_items": [{ma_cn, ten_cn, module, quy_trinh, priority,
                           opened_date, aging_days, pics, current_phase,
                           status, row_num}]
        }
    """
    if today is None:
        today = date.today()

    total = 0
    fit_count = 0
    gap_count = 0
    gap_closed = 0
    gap_open = 0

    # Aggregators
    per_module: dict[str, dict[str, int]] = defaultdict(lambda: {"fit": 0, "gap": 0})
    per_process: dict[str, dict[str, int]] = defaultdict(lambda: {"fit": 0, "gap": 0})
    per_priority: dict[str, dict[str, int]] = defaultdict(lambda: {"fit": 0, "gap": 0})

    aging_items: list[dict] = []

    for row in data.rows:
        total += 1
        raw_fg = row.meta.get("fit_gap")
        is_gap = _is_gap_value(raw_fg)
        is_fit = _is_fit_value(raw_fg) if not is_gap else False  # ưu tiên GAP nếu row là "FIT/GAP"

        module = row.meta.get("module") or "(Chưa gán)"
        process = row.meta.get("quy_trinh") or "(Chưa gán)"
        pri = _norm_priority(row.meta.get("priority"))

        if is_fit:
            fit_count += 1
            per_module[module]["fit"] += 1
            per_process[process]["fit"] += 1
            per_priority[pri]["fit"] += 1
        elif is_gap:
            gap_count += 1
            per_module[module]["gap"] += 1
            per_process[process]["gap"] += 1
            per_priority[pri]["gap"] += 1

            if _is_row_closed_all_phases(row):
                gap_closed += 1
            else:
                gap_open += 1
                # Tính aging từ ngày sớm nhất có hoạt động
                earliest = _earliest_activity_date(row)
                aging_days: Optional[int] = None
                if earliest is not None:
                    aging_days = max(0, (today - earliest).days)
                aging_items.append({
                    "row_num": row.row_num,
                    "ma_cn": row.meta.get("ma_cn") or "",
                    "ten_cn": row.meta.get("ten_cn") or "",
                    "module": row.meta.get("module") or "",
                    "quy_trinh": row.meta.get("quy_trinh") or "",
                    "priority": row.meta.get("priority") or "",
                    "opened_date": earliest.isoformat() if earliest else None,
                    "aging_days": aging_days,
                    "pics": _row_pics(row),
                    "current_phase": _current_open_phase(row) or "",
                    # Status = status của current_phase (nếu có), else "N/A"
                    "status": (
                        row.phases.get(_current_open_phase(row)).status
                        if _current_open_phase(row) and row.phases.get(_current_open_phase(row))
                        else ""
                    ),
                })

    # Filter aging_items: chỉ giữ những cái > threshold ngày
    # Nếu aging_days = None (không có ngày nào) → vẫn giữ và đánh dấu "N/A" (BA cần biết)
    # để filter sau, sort giảm theo aging_days (None đẩy xuống cuối)
    def _sort_key(it):
        d = it.get("aging_days")
        return (-1 if d is None else -d, it.get("ma_cn") or "")

    aging_items.sort(key=_sort_key)
    aged_over_threshold = [
        it for it in aging_items
        if it.get("aging_days") is not None and it["aging_days"] >= aging_threshold_days
    ]

    def _to_chart_list(agg: dict[str, dict[str, int]], key_name: str) -> list[dict]:
        out = []
        for k, v in agg.items():
            fit = v["fit"]
            gap = v["gap"]
            tot = fit + gap
            pct_gap = round(gap / tot * 100, 1) if tot else 0.0
            out.append({key_name: k, "fit": fit, "gap": gap, "total": tot, "pct_gap": pct_gap})
        # Sort: nhiều GAP hơn lên trước; cùng số GAP thì theo tên
        out.sort(key=lambda r: (-r["gap"], -r["total"], r[key_name]))
        return out

    return {
        "summary": {
            "total": total,
            "fit": fit_count,
            "gap": gap_count,
            "gap_closed": gap_closed,
            "gap_open": gap_open,
            "gap_open_aging": len(aged_over_threshold),
            "aging_threshold_days": aging_threshold_days,
        },
        "by_module": _to_chart_list(per_module, "module"),
        "by_process": _to_chart_list(per_process, "process"),
        "by_priority": _to_chart_list(per_priority, "priority"),
        # Trả cả 2: aging_items (all open GAP, sorted) + aged_over_threshold (aging > N ngày).
        # FE hiển thị bảng aged_over_threshold; nút "Xem tất cả" có thể switch sang list all.
        "aging_items": aged_over_threshold,
        "all_open_gap_items": aging_items,
    }
