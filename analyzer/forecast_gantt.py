"""
Forecast Gantt — dự kiến tháng hoàn thành milestone (UAT / Golive với KH…).

Rule tháng milestone (project-level aggregate):
  Với mọi phase thuộc task_type của milestone, bỏ Cancelled:
  1. Nếu còn phase CHƯA Closed (và có End date) → tháng = max(End còn mở).
     source = "open_max"  (dự báo khi workstream còn việc)
  2. Else nếu có phase Closed (có End) → tháng = max(End Closed).
     source = "closed_max"  (đã xong hết → tháng hoàn thành thực tế)
  3. Else → không có tháng (thiếu End / chưa có dữ liệu).

Không hardcode tên cột phase — map qua PhaseGroup.task_type (parser).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Callable, Optional

from parser.excel_parser import ParsedData

StateLoader = Callable[[str], Optional[dict]]

_DONE = frozenset({"closed", "cancelled"})
_CANCELLED = "cancelled"

# Milestone định nghĩa — id ổn định cho FE / export
MILESTONE_DEFS: list[dict[str, Any]] = [
    {
        "id": "analysis",
        "label": "Phân tích xong",
        "label_en": "Analysis done",
        "task_types": ("Phân tích",),
        "highlight": False,
    },
    {
        "id": "dev",
        "label": "Dev xong",
        "label_en": "Dev done",
        "task_types": ("Lập trình",),
        "highlight": False,
    },
    {
        "id": "config",
        "label": "Cấu hình xong",
        "label_en": "Config done",
        "task_types": ("Cấu hình UAT", "Kiểm thử"),
        "highlight": False,
    },
    {
        "id": "uat",
        "label": "UAT với KH",
        "label_en": "UAT with client",
        "task_types": ("UAT",),
        "highlight": True,
    },
    {
        "id": "golive",
        "label": "Golive với KH",
        "label_en": "Golive with client",
        "task_types": ("Cấu hình Golive",),
        "highlight": True,
    },
]

FORECAST_RULE_VI = (
    "Tháng milestone = max(End) của phase còn mở (chưa Closed/Cancelled); "
    "nếu không còn phase mở thì lấy max(End) của phase đã Closed. "
    "Bỏ Cancelled. Phase không có End → không đóng góp."
)


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _status_norm(status: Optional[str]) -> str:
    return (status or "").strip().lower()


def _phases_for_types(data: ParsedData, task_types: tuple[str, ...]) -> list[str]:
    wanted = set(task_types)
    return [pg.name for pg in data.phase_groups if pg.task_type in wanted]


def compute_milestone_for_data(
    data: ParsedData,
    task_types: tuple[str, ...],
) -> dict[str, Any]:
    """
    Aggregate 1 milestone trên 1 ParsedData.
    Trả dict: month, date, source, closed, open, total, no_end, phases.
    """
    phase_names = _phases_for_types(data, task_types)
    open_ends: list[date] = []
    closed_ends: list[date] = []
    n_closed = 0
    n_open = 0
    n_no_end = 0
    n_total = 0

    for row in data.rows:
        for ph in phase_names:
            pd = row.phases.get(ph)
            if pd is None:
                continue
            st = _status_norm(pd.status)
            if st == _CANCELLED:
                continue
            # Chỉ đếm phase có status hoặc có date (tránh blank hoàn toàn)
            if not pd.status and not pd.end_date and not pd.start_date:
                continue
            n_total += 1
            if st == "closed":
                n_closed += 1
                if pd.end_date:
                    closed_ends.append(pd.end_date)
                else:
                    n_no_end += 1
            else:
                n_open += 1
                if pd.end_date:
                    open_ends.append(pd.end_date)
                else:
                    n_no_end += 1

    result: dict[str, Any] = {
        "month": None,
        "date": None,
        "source": "no_date",
        "closed": n_closed,
        "open": n_open,
        "total": n_total,
        "no_end": n_no_end,
        "phases": phase_names,
        "pct_closed": round(100.0 * n_closed / n_total, 1) if n_total else 0.0,
    }

    if open_ends:
        d = max(open_ends)
        result["date"] = d.isoformat()
        result["month"] = _month_key(d)
        result["source"] = "open_max"
    elif closed_ends:
        d = max(closed_ends)
        result["date"] = d.isoformat()
        result["month"] = _month_key(d)
        result["source"] = "closed_max"

    return result


def compute_project_forecast(data: ParsedData) -> dict[str, dict[str, Any]]:
    """Trả {milestone_id: milestone_result} cho 1 project."""
    out: dict[str, dict[str, Any]] = {}
    for m in MILESTONE_DEFS:
        out[m["id"]] = compute_milestone_for_data(data, m["task_types"])
    return out


def _month_span(months: list[str], pad: int = 1) -> list[str]:
    """Sinh dải tháng liên tục từ min..max, pad thêm hai đầu."""
    if not months:
        today = date.today()
        base = today.year * 12 + today.month
        keys = []
        for i in range(-2, 7):
            y, m = divmod(base + i - 1, 12)
            keys.append(f"{y:04d}-{m + 1:02d}")
        return keys

    parsed = []
    for mk in months:
        y, m = mk.split("-")
        parsed.append(int(y) * 12 + int(m))
    lo, hi = min(parsed) - pad, max(parsed) + pad
    # Giới hạn độ dài hợp lý
    if hi - lo > 36:
        mid = (lo + hi) // 2
        lo, hi = mid - 18, mid + 18
    out = []
    for v in range(lo, hi + 1):
        y, m = divmod(v - 1, 12)
        out.append(f"{y:04d}-{m + 1:02d}")
    return out


def compute_forecast_gantt(
    project_mgr,
    state_loader: StateLoader,
    slugs: Optional[list[str]] = None,
    include_archived: bool = False,
) -> dict[str, Any]:
    """
    Forecast Gantt đa dự án.

    Args:
        slugs: danh sách slug cần tính; None/[] → tất cả project active có file.
    """
    projects = project_mgr.list_projects(include_archived=include_archived)
    if slugs:
        want = {s.strip() for s in slugs if s and str(s).strip()}
        projects = [p for p in projects if p.slug in want]

    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    all_months: list[str] = []

    for proj in projects:
        state = state_loader(proj.slug)
        if state is None or state.get("data") is None:
            skipped.append({"slug": proj.slug, "reason": "no_file"})
            continue
        data: ParsedData = state["data"]
        milestones = compute_project_forecast(data)
        for mid, info in milestones.items():
            if info.get("month"):
                all_months.append(info["month"])
        rows.append({
            "slug": proj.slug,
            "name": proj.name,
            "milestones": milestones,
        })

    months = _month_span(all_months)

    # Summary: UAT / Golive theo tháng (đếm project)
    uat_by_month: dict[str, list[str]] = defaultdict(list)
    golive_by_month: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        u = r["milestones"].get("uat") or {}
        g = r["milestones"].get("golive") or {}
        if u.get("month"):
            uat_by_month[u["month"]].append(r["name"])
        if g.get("month"):
            golive_by_month[g["month"]].append(r["name"])

    # Aggregate theo milestone (multi-project): max tháng across projects
    milestone_agg: dict[str, Any] = {}
    for m in MILESTONE_DEFS:
        mid = m["id"]
        dates = []
        for r in rows:
            info = r["milestones"].get(mid) or {}
            if info.get("date"):
                dates.append(date.fromisoformat(info["date"]))
        if dates:
            d = max(dates)
            milestone_agg[mid] = {
                "month": _month_key(d),
                "date": d.isoformat(),
                "source": "projects_max",
                "project_count": sum(
                    1 for r in rows if (r["milestones"].get(mid) or {}).get("month")
                ),
            }
        else:
            milestone_agg[mid] = {
                "month": None,
                "date": None,
                "source": "no_date",
                "project_count": 0,
            }

    return {
        "rule": FORECAST_RULE_VI,
        "milestones": [
            {
                "id": m["id"],
                "label": m["label"],
                "label_en": m["label_en"],
                "task_types": list(m["task_types"]),
                "highlight": m["highlight"],
            }
            for m in MILESTONE_DEFS
        ],
        "months": months,
        "projects": rows,
        "milestone_aggregate": milestone_agg,
        "summary": {
            "project_count": len(rows),
            "projects_skipped": skipped,
            "uat_by_month": {k: v for k, v in sorted(uat_by_month.items())},
            "golive_by_month": {k: v for k, v in sorted(golive_by_month.items())},
        },
    }
