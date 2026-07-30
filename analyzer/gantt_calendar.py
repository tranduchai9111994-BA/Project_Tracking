"""
Gantt Calendar — Timeline dạng Excel-style (Month/Week/Day header 3 tầng).

Mỗi row = 1 aggregate (Module/Quy trình/Function). Cell = timeslot (day/week/
month). Bar màu theo category phase, text `%` completion, marker "Today".

Không hardcode cột — tận dụng ParsedData.all_phases & PhaseGroup.task_type
để phân loại category. Auto-detect range date từ tất cả phase Start/End.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any, Optional

from parser.excel_parser import FunctionRow, ParsedData, PhaseData


# ==========================================================================
# Category → màu (đồng bộ với legend UI + Excel fill)
# ==========================================================================
# Map task_type (tiếng Việt, do parser.excel_parser.TASK_TYPE_RULES sinh) →
# category dùng cho tô màu bar. Key khớp label FE hiển thị trong legend.
_TASK_TYPE_CATEGORY: dict[str, str] = {
    "Phân tích": "phase1",       # Analysis/Design/Config — xanh
    "Lập trình": "phase2",       # Dev — cam
    "Config+Test": "phase2",     # config/test cũng Phase 2
    "UAT": "phase3",             # UAT — tím
    "Golive": "milestone",       # Golive/Deploy — xanh lá (milestone)
}

# Màu hex cho từng category (đồng bộ với FE `_GANTT_CAT_COLOR` + Excel).
CATEGORY_COLORS: dict[str, str] = {
    "phase1":    "#3b82f6",  # blue-500
    "phase2":    "#f59e0b",  # amber-500
    "phase3":    "#a855f7",  # purple-500
    "milestone": "#22c55e",  # green-500
    "summary":   "#1f2937",  # gray-800 (dark)
    "idle":      "#94a3b8",  # slate-400 (chưa bắt đầu / không có phase)
}

_VALID_GROUP_BY = ("module", "phan_he", "process", "quy_trinh", "function")
_VALID_GRANULARITY = ("day", "week", "month", "auto")


# ==========================================================================
# Helpers — date range / column building
# ==========================================================================

def _collect_all_dates(rows: list[FunctionRow]) -> list[date]:
    """Gom mọi Start/End date từ mọi phase của mọi row."""
    out: list[date] = []
    for r in rows:
        for pd in r.phases.values():
            if pd.start_date:
                out.append(pd.start_date)
            if pd.end_date:
                out.append(pd.end_date)
    return out


def _choose_granularity(min_d: date, max_d: date) -> str:
    """Auto-select granularity dựa theo độ dài range."""
    span_days = max((max_d - min_d).days, 1)
    if span_days <= 60:
        return "day"
    if span_days <= 400:
        return "week"
    return "month"


def _month_add(d: date, months: int) -> date:
    """Cộng tháng vào 1 date (giữ nguyên day, clamp về cuối tháng nếu cần)."""
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    # Clamp day về ngày cuối tháng nếu overflow (VD 31/1 + 1 tháng → 28/2)
    for day in (d.day, 28, 29, 30, 31):
        try:
            return date(y, m, min(day, 31))
        except ValueError:
            continue
    return date(y, m, 1)


def _week_start(d: date) -> date:
    """Đầu tuần ISO (Monday) của 1 date."""
    return d - timedelta(days=d.weekday())


def _month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def _month_label(d: date) -> str:
    """VD 'Jun-26' (khớp format ví dụ Excel gốc)."""
    return d.strftime("%b-%y")


def _day_label(d: date) -> str:
    """VD '01-Jun'."""
    return d.strftime("%d-%b")


def _build_columns(min_d: date, max_d: date, granularity: str) -> list[dict]:
    """
    Sinh danh sách cột timeline theo granularity. Mỗi cột có:
      idx, label, start, end (inclusive), week_num, month_label
    """
    cols: list[dict] = []
    idx = 0
    if granularity == "day":
        d = min_d
        while d <= max_d:
            cols.append({
                "idx": idx,
                "label": _day_label(d),
                "start": d.isoformat(),
                "end": d.isoformat(),
                "week_num": d.isocalendar()[1],
                "month_label": _month_label(d),
            })
            idx += 1
            d += timedelta(days=1)
    elif granularity == "week":
        d = _week_start(min_d)
        end_ws = _week_start(max_d)
        while d <= end_ws:
            wk_end = d + timedelta(days=6)
            cols.append({
                "idx": idx,
                "label": f"W{d.isocalendar()[1]:02d}",
                "start": d.isoformat(),
                "end": wk_end.isoformat(),
                "week_num": d.isocalendar()[1],
                "month_label": _month_label(d),
                "week_date_label": _day_label(d),
            })
            idx += 1
            d += timedelta(days=7)
    else:  # month
        d = _month_start(min_d)
        end_ms = _month_start(max_d)
        while d <= end_ms:
            # Cuối tháng = ngày trước đầu tháng kế
            nxt = _month_add(d, 1)
            m_end = nxt - timedelta(days=1)
            cols.append({
                "idx": idx,
                "label": _month_label(d),
                "start": d.isoformat(),
                "end": m_end.isoformat(),
                "week_num": None,
                "month_label": _month_label(d),
            })
            idx += 1
            d = nxt
    return cols


def _build_month_spans(columns: list[dict]) -> list[dict]:
    """Gom colspan cho header row 'Month' — VD 4 tuần trong tháng 6 → colspan=4."""
    spans: list[dict] = []
    for c in columns:
        lbl = c.get("month_label") or c["label"]
        if spans and spans[-1]["label"] == lbl:
            spans[-1]["colspan"] += 1
        else:
            spans.append({"label": lbl, "colspan": 1})
    return spans


def _build_week_spans(columns: list[dict], granularity: str) -> list[dict]:
    """Chỉ dùng khi granularity=day — gom day column theo tuần."""
    if granularity != "day":
        return []
    spans: list[dict] = []
    for c in columns:
        wn = c.get("week_num")
        if wn is None:
            continue
        lbl = f"W{wn:02d}"
        if spans and spans[-1]["week_num"] == wn:
            spans[-1]["colspan"] += 1
        else:
            spans.append({"label": lbl, "week_num": wn, "colspan": 1})
    return spans


# ==========================================================================
# Aggregate metric cho 1 nhóm rows
# ==========================================================================

@dataclass
class _RowAgg:
    """Kết quả aggregate 1 nhóm function → 1 row Gantt."""
    name: str
    start: Optional[date] = None
    end: Optional[date] = None
    pct: int = 0
    category: str = "summary"
    func_count: int = 0
    closed_records: int = 0
    total_slots: int = 0
    overdue_count: int = 0
    active_phase: str = ""
    module: str = ""
    process: str = ""


def _phase_category(phase_name: str, task_type_map: dict[str, str]) -> str:
    """Map phase name → category (dùng task_type từ PhaseGroup)."""
    tt = task_type_map.get(phase_name, "")
    return _TASK_TYPE_CATEGORY.get(tt, "summary")


def _detect_row_category(
    rows: list[FunctionRow],
    all_phases: list[str],
    task_type_map: dict[str, str],
    is_aggregate: bool,
) -> tuple[str, str]:
    """
    Xác định (category, active_phase) cho 1 row aggregate.

    - Nếu aggregate mode (module/process): category = "summary".
    - Nếu function mode: category = phase category của phase "đang active nhất".
      Phase active = phase có nhiều task chưa Closed nhất; nếu tất cả Closed
      → "milestone" (đã golive).
    """
    if not rows or not all_phases:
        return ("idle", "")
    if is_aggregate:
        return ("summary", "")
    # Function mode: phase active nhất
    phase_active_count: Counter[str] = Counter()
    all_closed = True
    for r in rows:
        for ph in all_phases:
            pd = r.phases.get(ph, PhaseData())
            if pd.status not in ("Closed", "Cancelled"):
                all_closed = all_closed and (pd.status is None or pd.status == "Closed")
            if pd.status and pd.status not in ("Closed", "Cancelled"):
                phase_active_count[ph] += 1
    if not phase_active_count:
        # Không phase nào active → đã Closed hết hoặc chưa bắt đầu
        last = all_phases[-1]
        return (_phase_category(last, task_type_map) or "milestone", last)
    active = phase_active_count.most_common(1)[0][0]
    return (_phase_category(active, task_type_map), active)


def _aggregate_rows(
    rows: list[FunctionRow],
    name: str,
    all_phases: list[str],
    task_type_map: dict[str, str],
    is_aggregate: bool,
    today: date,
    module: str = "",
    process: str = "",
) -> _RowAgg:
    """Tính aggregate cho 1 nhóm."""
    agg = _RowAgg(name=name, module=module, process=process, func_count=len(rows))
    if not rows or not all_phases:
        agg.category = "idle"
        return agg

    starts: list[date] = []
    ends: list[date] = []
    closed = 0
    total = len(rows) * len(all_phases)
    overdue = 0
    for r in rows:
        row_has_overdue = False
        for ph in all_phases:
            pd = r.phases.get(ph, PhaseData())
            if pd.start_date:
                starts.append(pd.start_date)
            if pd.end_date:
                ends.append(pd.end_date)
            if pd.status == "Closed":
                closed += 1
            # Overdue = end < today, status != Closed/Cancelled
            if (
                pd.end_date is not None
                and pd.end_date < today
                and pd.status not in ("Closed", "Cancelled")
            ):
                row_has_overdue = True
        if row_has_overdue:
            overdue += 1

    agg.start = min(starts) if starts else None
    agg.end = max(ends) if ends else None
    agg.closed_records = closed
    agg.total_slots = total
    agg.overdue_count = overdue
    agg.pct = round(closed / total * 100) if total > 0 else 0
    agg.category, agg.active_phase = _detect_row_category(
        rows, all_phases, task_type_map, is_aggregate,
    )
    return agg


# ==========================================================================
# Grouping — module | process | function
# ==========================================================================

def _group_rows(data: ParsedData, group_by: str) -> list[tuple[str, str, str, list[FunctionRow]]]:
    """
    Return list of (name, module, process, rows) theo `group_by`.
    - "module" / "phan_he" → 1 group / Module.
    - "process" / "quy_trinh" → 1 group / (Module, Quy trình).
    - "function" → 1 group / function.
    Rows không có key phù hợp bị bỏ qua để tránh row "(rỗng)" gây nhiễu UI.
    """
    gb = (group_by or "module").lower().strip()
    if gb in ("phan_he", "module"):
        by_mod: dict[str, list[FunctionRow]] = defaultdict(list)
        for r in data.rows:
            m = r.meta.get("module") or ""
            if not m:
                continue
            by_mod[m].append(r)
        # Giữ thứ tự data.all_modules để UI ổn định
        result = []
        seen = set()
        for m in data.all_modules:
            if m in by_mod:
                result.append((m, m, "", by_mod[m]))
                seen.add(m)
        # Fallback: module chưa có trong all_modules (ít khi xảy ra)
        for m, lst in by_mod.items():
            if m not in seen:
                result.append((m, m, "", lst))
        return result

    if gb in ("process", "quy_trinh"):
        by_key: dict[tuple[str, str], list[FunctionRow]] = defaultdict(list)
        for r in data.rows:
            m = r.meta.get("module") or ""
            p = r.meta.get("quy_trinh") or ""
            if not p:
                continue
            by_key[(m, p)].append(r)
        sorted_keys = sorted(by_key.keys(), key=lambda t: (t[0], t[1]))
        return [(f"{m} · {p}", m, p, by_key[(m, p)]) for m, p in sorted_keys]

    # function
    result = []
    for r in data.rows:
        code = r.meta.get("ma_cn") or ""
        name = r.meta.get("ten_cn") or code or f"Row#{r.row_num}"
        label = f"{code} · {name}" if code else name
        result.append((label, r.meta.get("module") or "", r.meta.get("quy_trinh") or "", [r]))
    return result


# ==========================================================================
# Main entry
# ==========================================================================

def compute_gantt_calendar(
    data: ParsedData,
    group_by: str = "module",
    granularity: str = "auto",
    today: Optional[date] = None,
) -> dict[str, Any]:
    """
    Build shape để FE render Gantt Calendar Excel-style.

    Args:
        data: ParsedData (đã áp global filter nếu cần từ caller).
        group_by: "module" | "phan_he" | "process" | "quy_trinh" | "function".
        granularity: "day" | "week" | "month" | "auto" (tự chọn theo range).
        today: date hôm nay (mặc định date.today()).

    Return dict shape:
      {
        group_by, granularity,
        min_date, max_date,
        columns: [{idx, label, start, end, month_label, week_num, ...}],
        month_spans: [{label, colspan}],
        week_spans:  [{label, week_num, colspan}]  # chỉ khi granularity=day
        today_col: int | None,
        rows: [{
          name, module, process, func_count, start, end, pct,
          category, active_phase, overdue_count,
          span_start_col, span_end_col,
          cells: [bool...]   # length = len(columns)
        }],
        legend: {category → {label, color}}
      }
    """
    today = today or date.today()

    gb = (group_by or "module").lower().strip()
    if gb not in _VALID_GROUP_BY:
        gb = "module"
    gr = (granularity or "auto").lower().strip()
    if gr not in _VALID_GRANULARITY:
        gr = "auto"

    # Task type map: phase_name → task_type tiếng Việt
    task_type_map = {pg.name: pg.task_type for pg in data.phase_groups}

    all_dates = _collect_all_dates(data.rows)
    if not all_dates:
        # Empty state — trả về skeleton để FE hiện thông báo
        return {
            "group_by": gb,
            "granularity": gr if gr != "auto" else "week",
            "min_date": None,
            "max_date": None,
            "columns": [],
            "month_spans": [],
            "week_spans": [],
            "today_col": None,
            "rows": [],
            "legend": _legend_dict(),
            "empty": True,
        }

    min_d = min(all_dates)
    max_d = max(all_dates)
    # Extend range để bao today (cho marker "Today" luôn có chỗ vẽ)
    if today < min_d:
        min_d = today
    if today > max_d:
        max_d = today

    granularity_final = _choose_granularity(min_d, max_d) if gr == "auto" else gr

    # Snap min/max về đầu week/month để header đẹp
    if granularity_final == "week":
        min_d = _week_start(min_d)
        max_d = _week_start(max_d) + timedelta(days=6)
    elif granularity_final == "month":
        min_d = _month_start(min_d)
        max_d = _month_add(_month_start(max_d), 1) - timedelta(days=1)

    columns = _build_columns(min_d, max_d, granularity_final)
    month_spans = _build_month_spans(columns)
    week_spans = _build_week_spans(columns, granularity_final)

    # Tìm today_col
    today_col: Optional[int] = None
    for c in columns:
        if c["start"] <= today.isoformat() <= c["end"]:
            today_col = c["idx"]
            break

    # Build rows
    is_aggregate = gb != "function"
    groups = _group_rows(data, gb)
    rows_out: list[dict] = []
    for name, module, process, group_rows in groups:
        agg = _aggregate_rows(
            group_rows, name, data.all_phases, task_type_map,
            is_aggregate=is_aggregate, today=today,
            module=module, process=process,
        )
        cells, span_start, span_end = _cells_for_row(agg, columns)
        rows_out.append({
            "name": agg.name,
            "module": agg.module,
            "process": agg.process,
            "func_count": agg.func_count,
            "start": agg.start.isoformat() if agg.start else None,
            "end": agg.end.isoformat() if agg.end else None,
            "pct": agg.pct,
            "category": agg.category,
            "active_phase": agg.active_phase,
            "overdue_count": agg.overdue_count,
            "span_start_col": span_start,
            "span_end_col": span_end,
            "cells": cells,
        })

    return {
        "group_by": gb,
        "granularity": granularity_final,
        "min_date": min_d.isoformat(),
        "max_date": max_d.isoformat(),
        "columns": columns,
        "month_spans": month_spans,
        "week_spans": week_spans,
        "today_col": today_col,
        "today": today.isoformat(),
        "rows": rows_out,
        "legend": _legend_dict(),
        "empty": False,
    }


def _cells_for_row(agg: _RowAgg, columns: list[dict]) -> tuple[list[bool], Optional[int], Optional[int]]:
    """
    Xác định cell active + span index cho 1 row.

    Cell overlaps [row.start, row.end] ↔ cell.end >= row.start AND
    cell.start <= row.end (inclusive interval intersection).
    """
    n = len(columns)
    cells = [False] * n
    if agg.start is None or agg.end is None:
        return cells, None, None
    start_iso = agg.start.isoformat()
    end_iso = agg.end.isoformat()
    span_start: Optional[int] = None
    span_end: Optional[int] = None
    for c in columns:
        if c["end"] >= start_iso and c["start"] <= end_iso:
            cells[c["idx"]] = True
            if span_start is None:
                span_start = c["idx"]
            span_end = c["idx"]
    return cells, span_start, span_end


def _legend_dict() -> dict[str, dict[str, str]]:
    """Legend hiển thị cuối section — label VN, màu khớp CATEGORY_COLORS."""
    return {
        "phase1":    {"label": "Phân tích / Config", "color": CATEGORY_COLORS["phase1"]},
        "phase2":    {"label": "Lập trình / Test",    "color": CATEGORY_COLORS["phase2"]},
        "phase3":    {"label": "UAT",                 "color": CATEGORY_COLORS["phase3"]},
        "milestone": {"label": "Golive / Milestone",  "color": CATEGORY_COLORS["milestone"]},
        "summary":   {"label": "Tổng hợp (aggregate)", "color": CATEGORY_COLORS["summary"]},
        "idle":      {"label": "Chưa có ngày",         "color": CATEGORY_COLORS["idle"]},
    }
