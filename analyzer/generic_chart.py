"""
Task 8 — Generic chart aggregation cho Chart Config Phase B.

Cho phép user chọn X field + Y measure + optional series/group field, apply filter
riêng cho từng chart → trả về dữ liệu chart.js chuẩn hoá.

Cũng được reuse cho Task 9 (Dynamic Dashboard Builder).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable, Optional

from parser.excel_parser import ParsedData, FunctionRow

# --- Field & measure enum (khớp UI dropdown) ------------------------------

# Key → hàm lấy value từ 1 FunctionRow (có thể trả về list nếu là multi-value,
# VD "pic" → list PIC ở phase Hiện tại; caller sẽ flatten trước khi group).
def _row_pics_all(row: FunctionRow) -> list[str]:
    """Union PIC của mọi phase."""
    out: list[str] = []
    for pd in row.phases.values():
        out.extend(p for p in (pd.pics or []) if p)
    # dedup giữ order
    seen: set[str] = set()
    uniq: list[str] = []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def _row_current_phase(row: FunctionRow) -> str:
    """Phase in-progress cuối cùng (hoặc phase mới nhất theo start_date)."""
    latest = ""
    latest_start = None
    for phase_name, pd in row.phases.items():
        st = (pd.status or "").strip()
        if st and st.lower() not in ("closed", "cancelled"):
            if pd.start_date and (latest_start is None or pd.start_date > latest_start):
                latest_start = pd.start_date
                latest = phase_name
    return latest


def _row_overall_status(row: FunctionRow) -> str:
    """Status "chung": nếu tất cả phase Closed → Closed; có In-progress → In-progress; ngược lại lấy status mới nhất."""
    statuses = [(pd.status or "").strip() for pd in row.phases.values() if pd.status]
    if not statuses:
        return ""
    lower = [s.lower() for s in statuses]
    if all(s in ("closed", "cancelled") for s in lower):
        return "Closed"
    if any(s == "in-progress" for s in lower):
        return "In-progress"
    if any(s == "resolved" for s in lower):
        return "Resolved"
    if any(s == "assigned" for s in lower):
        return "Assigned"
    if any(s == "pending" for s in lower):
        return "Pending"
    return statuses[-1]


def _row_earliest_start(row: FunctionRow) -> Optional[date]:
    starts = [pd.start_date for pd in row.phases.values() if pd.start_date]
    return min(starts) if starts else None


def _row_latest_end(row: FunctionRow) -> Optional[date]:
    ends = [pd.end_date for pd in row.phases.values() if pd.end_date]
    return max(ends) if ends else None


def _row_total_mh(row: FunctionRow) -> float:
    return sum((pd.estimate_mh or 0) for pd in row.phases.values())


def _row_is_closed(row: FunctionRow) -> bool:
    """Tất cả phase đều Closed/Cancelled."""
    for pd in row.phases.values():
        st = (pd.status or "").strip().lower()
        if st and st not in ("closed", "cancelled"):
            return False
    return any(pd.status for pd in row.phases.values())


def _row_is_overdue(row: FunctionRow, today: Optional[date] = None) -> bool:
    """Có 1 phase End < today mà chưa Closed/Cancelled (kèm rule later-Closed)."""
    from analyzer.overdue import row_has_overdue
    today = today or date.today()
    return row_has_overdue(row, today)


def _row_duration_days(row: FunctionRow) -> Optional[int]:
    """Ngày giữa earliest start và latest end (chưa Closed thì tính đến today)."""
    st = _row_earliest_start(row)
    if not st:
        return None
    en = _row_latest_end(row) or date.today()
    if en < st:
        return 0
    return (en - st).days


def _row_week_key(row: FunctionRow, ref: str = "start") -> str:
    """Format "YYYY-Www" cho earliest start hoặc latest end."""
    d = _row_earliest_start(row) if ref == "start" else _row_latest_end(row)
    if not d:
        return ""
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


# --- Field extractor: (row) → single value HOẶC list values (multi-explode) ---

def _row_field_values(row: FunctionRow, field: str) -> list[str]:
    """
    Trả list value của 1 row cho 1 field. Nhiều field là single (Module → 1
    value); PIC là multi (row có 3 PIC → 3 value → row đóng góp vào 3 bucket).
    Trả [""] nếu không có value để row vẫn được đếm trong bucket "Không xác định".
    """
    f = (field or "").strip().lower()
    meta = row.meta or {}
    if f in ("module", "phân hệ"):
        v = str(meta.get("module") or "").strip()
        return [v or "(Không có Module)"]
    if f in ("process", "quy trình", "quy_trinh"):
        v = str(meta.get("process") or meta.get("quy_trinh") or "").strip()
        return [v or "(Không có Quy trình)"]
    if f in ("priority", "ưu tiên"):
        v = str(meta.get("priority") or "").strip()
        return [v or "(Không có Priority)"]
    if f in ("complexity", "độ phức tạp"):
        v = str(meta.get("complexity") or "").strip()
        return [v or "(Không có Complexity)"]
    if f in ("fitgap", "fit/gap", "fit_gap"):
        # b15 fix: meta key là 'fit_gap' (parser); giữ fallback 'fitgap' cho
        # backward compat nếu code khác set key này.
        v = str(meta.get("fit_gap") or meta.get("fitgap") or "").strip()
        return [v or "(Không có FIT/GAP)"]
    if f in ("giai_doan", "giai đoạn", "stage"):
        v = str(meta.get("giai_doan") or "").strip()
        return [v or "(Không có Giai đoạn)"]
    if f in ("pic", "người phụ trách"):
        pics = _row_pics_all(row)
        return pics or ["(Chưa có PIC)"]
    if f in ("phase", "phase_name"):
        # Explode row thành từng phase (kèm phase name)
        names = [pn for pn in row.phases.keys()]
        return names or ["(Chưa có phase)"]
    if f in ("status",):
        return [_row_overall_status(row) or "(Không xác định)"]
    if f in ("task_type", "loại công việc"):
        # Từ phase → task_type
        types = set()
        for pn in row.phases.keys():
            # Không có access PhaseGroup ở đây → dùng regex đơn giản
            n = pn.lower()
            if "phân tích" in n or "analysis" in n:
                types.add("Phân tích")
            elif "coding" in n or "dev" in n or "lập trình" in n:
                types.add("Lập trình")
            elif "test" in n or "config" in n:
                types.add("Config & Test")
            elif "uat" in n:
                types.add("UAT")
            elif "go" in n and "live" in n:
                types.add("Go-live")
            else:
                types.add(pn)
        return sorted(types) or ["(Không phân loại)"]
    if f in ("week_start",):
        return [_row_week_key(row, "start") or "(Chưa start)"]
    if f in ("week_end",):
        return [_row_week_key(row, "end") or "(Chưa end)"]
    return ["(Trường không hỗ trợ)"]


# --- Filters -----------------------------------------------------------

def _row_passes_filters(row: FunctionRow, filters: dict, today: Optional[date] = None) -> bool:
    """
    filters có thể chứa: modules, processes, pics, priorities, complexities,
    fitgaps, statuses, overdue_only (bool).
    Rỗng/None = pass hết.
    """
    if not filters:
        return True
    meta = row.meta or {}
    mods = filters.get("modules")
    if mods and str(meta.get("module") or "") not in mods:
        return False
    procs = filters.get("processes")
    # b15 fix: meta lưu key 'quy_trinh' (theo parser), không phải 'process'.
    # Filter cũ luôn miss → không filter được → chart không đúng scope.
    if procs and str(meta.get("quy_trinh") or meta.get("process") or "") not in procs:
        return False
    prios = filters.get("priorities")
    if prios and str(meta.get("priority") or "") not in prios:
        return False
    cplxs = filters.get("complexities")
    if cplxs and str(meta.get("complexity") or "") not in cplxs:
        return False
    fgs = filters.get("fitgaps")
    if fgs:
        # b15 fix: meta key là 'fit_gap' theo parser; 'fitgap' luôn None.
        v = str(meta.get("fit_gap") or meta.get("fitgap") or "").strip()
        # FIT/GAP có thể là "FIT / GAP" → split
        vs = [p.strip() for p in v.replace("/", ",").split(",") if p.strip()]
        if not any(x in fgs for x in vs):
            return False
    stats = filters.get("statuses")
    if stats and _row_overall_status(row) not in stats:
        return False
    pics = filters.get("pics")
    if pics:
        row_pics = set(_row_pics_all(row))
        if not any(p in row_pics for p in pics):
            return False
    if filters.get("overdue_only") and not _row_is_overdue(row, today):
        return False
    if filters.get("closed_only") and not _row_is_closed(row):
        return False
    if filters.get("open_only") and _row_is_closed(row):
        return False
    return True


# --- Measure computation -----------------------------------------------

MEASURES = {
    # b15 (b): label tiếng Việt cho wizard dropdown + legend/axis.
    "count":         "Số task",
    "pct_closed":    "% Closed",
    "overdue_count": "Số task trễ",
    "pct_overdue":   "% task trễ",
    "sum_mh":        "Sum MH",
    "sum_md":        "Sum MD",
    "avg_duration":  "Avg Duration",
    "pct_ontime":    "% On-time",
}


# Format hint cho FE data label — phân biệt "%" vs "count" vs "hour".
MEASURE_FORMAT = {
    "count":         "int",
    "pct_closed":    "pct",
    "overdue_count": "int",
    "pct_overdue":   "pct",
    "sum_mh":        "hour",
    "sum_md":        "day",
    "avg_duration":  "day",
    "pct_ontime":    "pct",
}

FIELDS = {
    "module": "Module",
    "process": "Quy trình",
    "pic": "PIC",
    "phase": "Phase",
    "status": "Status",
    "priority": "Priority",
    "complexity": "Complexity",
    "fitgap": "FIT/GAP",
    "giai_doan": "Giai đoạn",
    "task_type": "Loại công việc",
    "week_start": "Tuần bắt đầu",
    "week_end": "Tuần kết thúc",
}


def _measure_value(rows: list[FunctionRow], measure: str, today: Optional[date] = None) -> float:
    """Compute 1 aggregate value cho subset rows.

    b15 (a) fix: truyền today qua _row_is_overdue để đảm bảo giá trị nhất
    quán với `dashboard_engine._is_overdue` — trước đây fallback về
    date.today() ở mỗi call nên aggregate có thể lệch nếu qua nửa đêm.
    """
    if not rows:
        return 0
    m = (measure or "count").lower()
    if m == "count":
        return len(rows)
    if m == "overdue_count":
        return sum(1 for r in rows if _row_is_overdue(r, today))
    if m == "sum_mh":
        return round(sum(_row_total_mh(r) for r in rows), 1)
    if m == "sum_md":
        return round(sum(_row_total_mh(r) for r in rows) / 8.0, 2)
    if m == "pct_closed":
        closed = sum(1 for r in rows if _row_is_closed(r))
        return round(closed / len(rows) * 100, 1)
    if m == "pct_overdue":
        overdue = sum(1 for r in rows if _row_is_overdue(r, today))
        return round(overdue / len(rows) * 100, 1)
    if m == "pct_ontime":
        # b15 (a): "% On-time" = 100 - pct_overdue. Trước đây user chỉ có
        # pct_overdue → khi tất cả row đều overdue -> 100% khó phân biệt vs
        # empty bucket. On-time làm rõ nghĩa cho PM report.
        overdue = sum(1 for r in rows if _row_is_overdue(r, today))
        return round((len(rows) - overdue) / len(rows) * 100, 1)
    if m == "avg_duration":
        durs = [_row_duration_days(r) for r in rows]
        vals = [d for d in durs if d is not None]
        if not vals:
            return 0
        return round(sum(vals) / len(vals), 1)
    return len(rows)


# --- Aggregate main ----------------------------------------------------

def aggregate_chart(
    data: ParsedData,
    x_field: str,
    y_measure: str = "count",
    series_field: Optional[str] = None,
    filters: Optional[dict] = None,
    today: Optional[date] = None,
    limit_x: int = 50,
) -> dict:
    """
    Trả về:
    {
        "labels": [...],
        "datasets": [{label, data: [...]}, ...],  # 1 dataset nếu ko có series_field
        "meta": {x_field, y_measure, series_field, total_rows_after_filter}
    }
    """
    today = today or date.today()
    # 1) filter rows theo filters
    rows_filtered = [r for r in data.rows if _row_passes_filters(r, filters or {}, today)]

    # 2) explode theo x_field (nếu multi-value)
    #    → build map: x_value → list of (row, series_value)
    x_to_series_rows: dict[str, dict[str, list[FunctionRow]]] = {}
    for r in rows_filtered:
        x_vals = _row_field_values(r, x_field) or ["(Trống)"]
        if series_field:
            s_vals = _row_field_values(r, series_field) or ["(Trống)"]
        else:
            s_vals = ["_"]
        for xv in x_vals:
            for sv in s_vals:
                x_to_series_rows.setdefault(xv, {}).setdefault(sv, []).append(r)

    # 3) sắp xếp labels
    labels_ordered = sorted(x_to_series_rows.keys(),
                            key=lambda k: (-_measure_value(
                                [r for slist in x_to_series_rows[k].values() for r in slist],
                                y_measure, today), k))
    labels = labels_ordered[:limit_x]

    # 4) build datasets
    series_names: list[str] = []
    if series_field:
        seen: set[str] = set()
        for x in labels:
            for s in x_to_series_rows[x].keys():
                if s not in seen:
                    seen.add(s)
                    series_names.append(s)
        series_names.sort()
    else:
        series_names = ["_"]

    datasets = []
    for s in series_names:
        vals = []
        for x in labels:
            rows_here = x_to_series_rows.get(x, {}).get(s, [])
            vals.append(_measure_value(rows_here, y_measure, today))
        datasets.append({
            "label": (s if series_field else MEASURES.get(y_measure, y_measure)),
            "data": vals,
        })

    return {
        "labels": labels,
        "datasets": datasets,
        "meta": {
            "x_field": x_field,
            "y_measure": y_measure,
            "y_measure_label": MEASURES.get(y_measure, y_measure),
            "y_measure_format": MEASURE_FORMAT.get(y_measure, "int"),
            "series_field": series_field,
            "total_rows_after_filter": len(rows_filtered),
        },
    }


def drill_chart(
    data: ParsedData,
    x_field: str,
    x_value: str,
    series_field: Optional[str] = None,
    series_value: Optional[str] = None,
    filters: Optional[dict] = None,
    today: Optional[date] = None,
    limit: int = 500,
) -> dict:
    """T27 — Trả về danh sách FunctionRow rơi vào bucket (x_value, series_value)
    của aggregate_chart. Dùng cho drill-down modal khi user click bar/pie.

    Rules:
    - Apply cùng filters + explode logic như aggregate_chart để đảm bảo count khớp.
    - Nếu 1 row có nhiều x_value (VD PIC multi) chỉ match theo x_value được click.
    - Sắp xếp: overdue trước, sau đó theo priority Must-have, cuối theo ma_cn.

    Returns:
        {
            "x_field": ..., "x_value": ..., "series_field": ..., "series_value": ...,
            "items": [...],  # tối đa `limit` rows
            "total": <int>,
        }
    """
    today = today or date.today()
    x_field_norm = (x_field or "").strip().lower()
    x_target = str(x_value or "").strip()
    s_target = str(series_value or "").strip() if series_field else ""

    # 1) filter theo filters
    rows_filtered = [r for r in data.rows if _row_passes_filters(r, filters or {}, today)]

    # 2) chọn rows match x_value (và optional series_value)
    matched: list[FunctionRow] = []
    seen_row_ids: set[int] = set()   # dedupe row nếu explode cho match trùng
    for r in rows_filtered:
        x_vals = _row_field_values(r, x_field) or ["(Trống)"]
        if x_target not in x_vals:
            continue
        if series_field and s_target:
            s_vals = _row_field_values(r, series_field) or ["(Trống)"]
            if s_target not in s_vals:
                continue
        rid = id(r)
        if rid in seen_row_ids:
            continue
        seen_row_ids.add(rid)
        matched.append(r)

    total = len(matched)

    # 3) Sort: overdue first, Must-have priority, ma_cn
    def _sort_key(r: FunctionRow):
        meta = r.meta or {}
        prio = str(meta.get("priority") or "")
        return (
            0 if _row_is_overdue(r, today) else 1,
            0 if "Must" in prio else 1,
            str(meta.get("ma_cn") or ""),
        )
    matched.sort(key=_sort_key)

    # 4) Serialize (chỉ field cần cho drill modal)
    items = []
    for r in matched[:limit]:
        meta = r.meta or {}
        # Phase gần nhất có end_date để hiển thị deadline
        latest_end = _row_latest_end(r)
        items.append({
            "ma_cn":     str(meta.get("ma_cn") or ""),
            "ten_cn":    str(meta.get("ten_cn") or ""),
            "module":    str(meta.get("module") or ""),
            "quy_trinh": str(meta.get("quy_trinh") or meta.get("process") or ""),
            "priority":  str(meta.get("priority") or ""),
            "complexity": str(meta.get("complexity") or ""),
            "fit_gap":   str(meta.get("fit_gap") or meta.get("fitgap") or ""),
            "giai_doan": str(meta.get("giai_doan") or ""),
            "status":    _row_overall_status(r) or "",
            "pic":       _row_pics_all(r),
            "end_date":  latest_end.isoformat() if latest_end else "",
            "is_overdue": _row_is_overdue(r, today),
            "duration_days": _row_duration_days(r),
            "total_mh":  round(_row_total_mh(r), 1),
            "row_num":   int(meta.get("row_num") or 0) or None,
        })

    return {
        "x_field": x_field,
        "x_value": x_value,
        "series_field": series_field,
        "series_value": series_value if series_field else None,
        "items": items,
        "total": total,
        "truncated": total > limit,
    }


def get_available_fields() -> dict:
    """Trả cấu trúc field + measure + palette + chart types cho FE dropdown."""
    return {
        "fields": FIELDS,
        "measures": MEASURES,
        "chart_types": {
            "bar": "Bar (dọc)",
            "horizontalBar": "Bar (ngang)",
            "line": "Line",
            "area": "Area",
            "pie": "Pie",
            "doughnut": "Doughnut",
            "stackedBar": "Stacked Bar",
            "groupedBar": "Grouped Bar",
        },
        "palettes": {
            "default": ["#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899", "#14b8a6", "#f97316"],
            "blue":    ["#1e3a8a", "#1e40af", "#2563eb", "#3b82f6", "#60a5fa", "#93c5fd", "#bfdbfe", "#dbeafe"],
            "green":   ["#064e3b", "#065f46", "#047857", "#059669", "#10b981", "#34d399", "#6ee7b7", "#a7f3d0"],
            "warm":    ["#7c2d12", "#c2410c", "#ea580c", "#f97316", "#fb923c", "#fdba74", "#fed7aa", "#ffedd5"],
            "cool":    ["#0c4a6e", "#075985", "#0369a1", "#0284c7", "#0ea5e9", "#38bdf8", "#7dd3fc", "#bae6fd"],
            "corporate": ["#334155", "#475569", "#64748b", "#94a3b8", "#cbd5e1", "#e2e8f0", "#f1f5f9", "#f8fafc"],
            "pastel":  ["#fecaca", "#fed7aa", "#fef08a", "#bbf7d0", "#bfdbfe", "#ddd6fe", "#fbcfe8", "#e9d5ff"],
            "monochrome": ["#0f172a", "#1e293b", "#334155", "#475569", "#64748b", "#94a3b8", "#cbd5e1", "#e2e8f0"],
        },
    }
