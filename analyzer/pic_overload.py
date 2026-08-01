"""
PIC Overload — đa dự án theo ngày / tuần / tháng.

Rule active trên 1 calendar day D:
  - Phase có Start và End, Start ≤ D ≤ End
  - Status KHÔNG phải Closed / Cancelled (blank vẫn active)
  - PIC parse multi (đã có sẵn trên PhaseData.pics)

Overload:
  - Ngày: concurrent tasks > day_max_tasks (default 5)
  - Tuần/tháng: số ngày overload ≥ *_min_overload_days
    HOẶC tổng task-day > *_max_task_days
"""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Callable, Optional

from analyzer.overdue import is_done_status, is_phase_overdue
from parser.excel_parser import ParsedData

StateLoader = Callable[[str], Optional[dict]]

# --- Defaults (config được qua settings / query) ---------------------------
DEFAULT_DAY_MAX_TASKS = 5
DEFAULT_WEEK_MIN_OVERLOAD_DAYS = 2
DEFAULT_MONTH_MIN_OVERLOAD_DAYS = 5
DEFAULT_WEEK_MAX_TASK_DAYS = 25
DEFAULT_MONTH_MAX_TASK_DAYS = 100

VALID_GRAINS = ("day", "week", "month")
_DONE = frozenset({"closed", "cancelled"})


def default_thresholds() -> dict[str, Any]:
    return {
        "day_max_tasks": DEFAULT_DAY_MAX_TASKS,
        "week_min_overload_days": DEFAULT_WEEK_MIN_OVERLOAD_DAYS,
        "month_min_overload_days": DEFAULT_MONTH_MIN_OVERLOAD_DAYS,
        "week_max_task_days": DEFAULT_WEEK_MAX_TASK_DAYS,
        "month_max_task_days": DEFAULT_MONTH_MAX_TASK_DAYS,
        # Optional: chỉ tính phase có tên chứa 1 trong các keyword (case-insensitive)
        "phase_keywords": [],  # VD ["Dev", "Config"] — rỗng = mọi phase
    }


def merge_thresholds(overrides: Optional[dict] = None) -> dict[str, Any]:
    base = default_thresholds()
    if not overrides or not isinstance(overrides, dict):
        return base
    for k in (
        "day_max_tasks",
        "week_min_overload_days",
        "month_min_overload_days",
        "week_max_task_days",
        "month_max_task_days",
    ):
        if k in overrides and overrides[k] is not None:
            try:
                base[k] = max(1, int(overrides[k]))
            except (TypeError, ValueError):
                pass
    if "phase_keywords" in overrides:
        kws = overrides["phase_keywords"]
        if isinstance(kws, str):
            kws = [p.strip() for p in kws.split(",") if p.strip()]
        if isinstance(kws, list):
            base["phase_keywords"] = [str(x).strip() for x in kws if str(x).strip()]
    return base


# ------------------------------------------------------------------
# Period helpers
# ------------------------------------------------------------------

def _parse_iso_date(value: Optional[str], fallback: date) -> date:
    if not value:
        return fallback
    s = str(value).strip()[:10]
    try:
        return date.fromisoformat(s)
    except ValueError:
        return fallback


def default_date_range(today: Optional[date] = None) -> tuple[date, date]:
    """Mặc định: 14 ngày trước → 28 ngày tới (nhìn cả lịch sử gần + kế hoạch)."""
    t = today or date.today()
    return t - timedelta(days=14), t + timedelta(days=28)


def period_key(d: date, grain: str) -> str:
    if grain == "week":
        iso = d.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"
    if grain == "month":
        return f"{d.year}-{d.month:02d}"
    return d.isoformat()


def period_label(key: str, grain: str) -> str:
    if grain == "week":
        return f"Tuần {key}"
    if grain == "month":
        y, m = key.split("-")
        return f"Tháng {m}/{y}"
    return key


def _daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def _phase_allowed(phase_name: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    low = phase_name.lower()
    return any(k.lower() in low for k in keywords)


# ------------------------------------------------------------------
# Collect active task-days across projects
# ------------------------------------------------------------------

def _iter_active_assignments(
    data: ParsedData,
    *,
    project_slug: str,
    project_name: str,
    range_from: date,
    range_to: date,
    today: date,
    phase_keywords: list[str],
    phase_order: list[str],
):
    """Yield dict assignment cho mỗi (PIC, calendar day, phase-task)."""
    for row in data.rows:
        ma = str(row.meta.get("ma_cn") or "")
        ten = str(row.meta.get("ten_cn") or "")
        module = str(row.meta.get("module") or "")
        quy_trinh = str(row.meta.get("quy_trinh") or row.meta.get("process") or "")
        for phase_name, pd in row.phases.items():
            if not _phase_allowed(phase_name, phase_keywords):
                continue
            if is_done_status(pd.status):
                continue
            if pd.start_date is None or pd.end_date is None:
                continue
            # Giao đoạn phase ∩ [from, to]
            seg_start = max(pd.start_date, range_from)
            seg_end = min(pd.end_date, range_to)
            if seg_start > seg_end:
                continue
            pics = [p for p in (pd.pics or []) if p]
            if not pics:
                continue
            overdue = is_phase_overdue(
                pd, today, row=row, phase_name=phase_name, phase_order=phase_order,
            )
            status = (pd.status or "").strip()
            for d in _daterange(seg_start, seg_end):
                for pic in pics:
                    yield {
                        "pic": pic,
                        "date": d.isoformat(),
                        "project_slug": project_slug,
                        "project_name": project_name,
                        "ma_cn": ma,
                        "ten_cn": ten,
                        "module": module,
                        "quy_trinh": quy_trinh,
                        "phase": phase_name,
                        "status": status,
                        "start": pd.start_date.isoformat(),
                        "end": pd.end_date.isoformat(),
                        "is_overdue": overdue,
                        # unique task key trong 1 ngày (tránh đếm trùng multi-phase cùng CN)
                        "task_key": f"{project_slug}|{ma}|{phase_name}",
                    }


def overloaded_pics_for_data(
    data: ParsedData,
    *,
    today: Optional[date] = None,
    thresholds: Optional[dict] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    project_slug: str = "_local",
) -> set[str]:
    """
    Tập PIC overload trong **một** ParsedData (cùng rule day-grain với
    compute_pic_overload). Dùng để feed vào risk_scorer khi không quét đa dự án.
    """
    thr = merge_thresholds(thresholds)
    today = today or date.today()
    d_from_default, d_to_default = default_date_range(today)
    d_from = date_from or d_from_default
    d_to = date_to or d_to_default
    if d_from > d_to:
        d_from, d_to = d_to, d_from

    order = list(data.all_phases) if data.all_phases else list(
        {ph for r in data.rows for ph in r.phases}
    )
    concurrent: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for asg in _iter_active_assignments(
        data,
        project_slug=project_slug,
        project_name=project_slug,
        range_from=d_from,
        range_to=d_to,
        today=today,
        phase_keywords=thr["phase_keywords"],
        phase_order=order,
    ):
        concurrent[asg["pic"]][asg["date"]].add(asg["task_key"])

    day_max = thr["day_max_tasks"]
    overloaded: set[str] = set()
    for pic, days in concurrent.items():
        if any(len(keys) > day_max for keys in days.values()):
            overloaded.add(pic)
    return overloaded


def compute_pic_overload(
    project_mgr,
    state_loader: StateLoader,
    *,
    grain: str = "day",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    thresholds: Optional[dict] = None,
    pic_filter: Optional[str] = None,
    include_archived: bool = False,
    today: Optional[date] = None,
    detail_limit: int = 5000,
) -> dict[str, Any]:
    """
    Aggregate PIC overload across all projects.

    Returns summary + detail + highlight_dates + calendar + thresholds.
    """
    grain = (grain or "day").strip().lower()
    if grain not in VALID_GRAINS:
        grain = "day"

    thr = merge_thresholds(thresholds)
    today = today or date.today()
    d_from_default, d_to_default = default_date_range(today)
    d_from = _parse_iso_date(date_from, d_from_default)
    d_to = _parse_iso_date(date_to, d_to_default)
    if d_from > d_to:
        d_from, d_to = d_to, d_from

    pic_filter_l = (pic_filter or "").strip().lower() or None

    # pic → date → set(task_key) + detail rows + overdue flags
    concurrent: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    detail_by_pic_date: dict[tuple[str, str], list[dict]] = defaultdict(list)
    overdue_pics: set[str] = set()

    projects = project_mgr.list_projects(include_archived=include_archived)
    scanned = 0
    skipped: list[dict] = []

    for proj in projects:
        slug = proj.slug
        name = getattr(proj, "name", None) or slug
        state = state_loader(slug)
        if not state or not state.get("data"):
            skipped.append({"slug": slug, "reason": "no_file"})
            continue
        data: ParsedData = state["data"]
        scanned += 1
        order = list(data.all_phases) if data.all_phases else list(
            {ph for r in data.rows for ph in r.phases}
        )
        for asg in _iter_active_assignments(
            data,
            project_slug=slug,
            project_name=name,
            range_from=d_from,
            range_to=d_to,
            today=today,
            phase_keywords=thr["phase_keywords"],
            phase_order=order,
        ):
            pic = asg["pic"]
            if pic_filter_l and pic.lower() != pic_filter_l:
                continue
            d = asg["date"]
            concurrent[pic][d].add(asg["task_key"])
            detail_by_pic_date[(pic, d)].append(asg)
            if asg["is_overdue"]:
                overdue_pics.add(pic)

    day_max = thr["day_max_tasks"]

    # Per PIC × day metrics
    pic_day_stats: dict[str, dict[str, dict]] = defaultdict(dict)
    highlight_dates: set[str] = set()
    calendar: dict[str, dict[str, Any]] = {}

    for pic, days in concurrent.items():
        for d, keys in days.items():
            count = len(keys)
            is_od = count > day_max
            pic_day_stats[pic][d] = {
                "date": d,
                "task_count": count,
                "is_overload": is_od,
            }
            cal = calendar.setdefault(d, {
                "date": d,
                "max_concurrent": 0,
                "overload_pics": [],
                "pic_count": 0,
            })
            cal["max_concurrent"] = max(cal["max_concurrent"], count)
            cal["pic_count"] += 1
            if is_od:
                highlight_dates.add(d)
                if pic not in cal["overload_pics"]:
                    cal["overload_pics"].append(pic)

    # Grain aggregation
    by_period: list[dict] = []
    by_pic: list[dict] = []

    for pic, day_map in pic_day_stats.items():
        # Whole-range PIC rollup
        overload_days_list = sorted(d for d, s in day_map.items() if s["is_overload"])
        task_days = sum(s["task_count"] for s in day_map.values())
        max_conc = max((s["task_count"] for s in day_map.values()), default=0)
        projects_set: set[str] = set()
        for d in day_map:
            for item in detail_by_pic_date.get((pic, d), []):
                projects_set.add(item["project_slug"])

        pic_is_overload = False
        if grain == "day":
            pic_is_overload = bool(overload_days_list)
        elif grain == "week":
            # Will refine per period below; whole-range flag if any week overload
            pic_is_overload = False
        else:
            pic_is_overload = False

        # Period buckets
        buckets: dict[str, dict] = {}
        for d, s in day_map.items():
            pk = period_key(date.fromisoformat(d), grain)
            b = buckets.setdefault(pk, {
                "period": pk,
                "label": period_label(pk, grain),
                "task_days": 0,
                "overload_days": 0,
                "max_concurrent": 0,
                "dates": [],
                "highlight_dates": [],
            })
            b["task_days"] += s["task_count"]
            b["max_concurrent"] = max(b["max_concurrent"], s["task_count"])
            b["dates"].append(d)
            if s["is_overload"]:
                b["overload_days"] += 1
                b["highlight_dates"].append(d)

        for pk, b in buckets.items():
            if grain == "day":
                is_ol = b["max_concurrent"] > day_max
            elif grain == "week":
                is_ol = (
                    b["overload_days"] >= thr["week_min_overload_days"]
                    or b["task_days"] > thr["week_max_task_days"]
                )
            else:
                is_ol = (
                    b["overload_days"] >= thr["month_min_overload_days"]
                    or b["task_days"] > thr["month_max_task_days"]
                )
            if is_ol:
                pic_is_overload = True
            row = {
                "pic": pic,
                "period": pk,
                "label": b["label"],
                "task_days": b["task_days"],
                "overload_days": b["overload_days"],
                "max_concurrent": b["max_concurrent"],
                "is_overload": is_ol,
                "highlight_dates": sorted(b["highlight_dates"]),
                "projects": sorted(projects_set),
                "also_overdue": pic in overdue_pics,
            }
            by_period.append(row)

        by_pic.append({
            "pic": pic,
            "is_overload": pic_is_overload,
            "max_concurrent": max_conc,
            "overload_days": len(overload_days_list),
            "task_days": task_days,
            "highlight_dates": overload_days_list,
            "projects": sorted(projects_set),
            "also_overdue": pic in overdue_pics,
            "periods_overload": sum(1 for r in by_period if r["pic"] == pic and r["is_overload"]),
        })

    by_pic.sort(key=lambda x: (
        not x["is_overload"],
        -x["max_concurrent"],
        -x["overload_days"],
        x["pic"].lower(),
    ))
    by_period.sort(key=lambda x: (
        not x["is_overload"],
        x["period"],
        -x["max_concurrent"],
        x["pic"].lower(),
    ))

    # Detail: ưu tiên ngày đỏ / PIC overload; cắt limit
    detail: list[dict] = []
    overload_pic_set = {p["pic"] for p in by_pic if p["is_overload"]}
    for (pic, d), items in sorted(detail_by_pic_date.items()):
        if pic_filter_l and pic.lower() != pic_filter_l:
            continue
        # Nếu không filter PIC: chỉ trả detail của PIC overload hoặc ngày đỏ
        if not pic_filter_l:
            if pic not in overload_pic_set and d not in highlight_dates:
                continue
        day_count = pic_day_stats.get(pic, {}).get(d, {}).get("task_count", len(items))
        for item in items:
            row = {
                k: item[k] for k in (
                    "pic", "date", "project_slug", "project_name",
                    "ma_cn", "ten_cn", "module", "quy_trinh", "phase", "status",
                    "start", "end", "is_overdue",
                )
            }
            row["concurrent_count"] = day_count
            row["threshold"] = day_max
            row["is_day_overload"] = day_count > day_max
            detail.append(row)
            if len(detail) >= detail_limit:
                break
        if len(detail) >= detail_limit:
            break

    # So sánh tuần này vs tuần trước (light) khi grain=week
    week_compare = None
    if grain == "week":
        week_compare = _week_over_week(by_period, today)

    calendar_list = [calendar[k] for k in sorted(calendar.keys())]
    for c in calendar_list:
        c["is_highlight"] = c["date"] in highlight_dates
        c["overload_pics"] = sorted(c["overload_pics"])

    return {
        "grain": grain,
        "from": d_from.isoformat(),
        "to": d_to.isoformat(),
        "today": today.isoformat(),
        "thresholds": thr,
        "summary": {
            "projects_scanned": scanned,
            "projects_skipped": skipped,
            "pic_count": len(by_pic),
            "overload_pic_count": sum(1 for p in by_pic if p["is_overload"]),
            "highlight_dates": sorted(highlight_dates),
            "highlight_date_count": len(highlight_dates),
            "detail_truncated": len(detail) >= detail_limit,
            "detail_count": len(detail),
            "week_compare": week_compare,
        },
        "by_pic": by_pic,
        "by_period": by_period,
        "calendar": calendar_list,
        "detail": detail,
    }


def _week_over_week(by_period: list[dict], today: date) -> Optional[dict]:
    """Đếm PIC overload tuần ISO hiện tại vs tuần trước."""
    cur = period_key(today, "week")
    prev_d = today - timedelta(days=7)
    prev = period_key(prev_d, "week")
    cur_pics = {r["pic"] for r in by_period if r["period"] == cur and r["is_overload"]}
    prev_pics = {r["pic"] for r in by_period if r["period"] == prev and r["is_overload"]}
    return {
        "current_week": cur,
        "previous_week": prev,
        "current_overload_pics": sorted(cur_pics),
        "previous_overload_pics": sorted(prev_pics),
        "current_count": len(cur_pics),
        "previous_count": len(prev_pics),
        "delta": len(cur_pics) - len(prev_pics),
        "new_overload": sorted(cur_pics - prev_pics),
        "resolved": sorted(prev_pics - cur_pics),
    }


# ------------------------------------------------------------------
# Global settings store (đa dự án — 1 file chung)
# ------------------------------------------------------------------

_SETTINGS_FILE = "pic_overload_settings.json"


def settings_path(projects_folder: str) -> str:
    return os.path.join(projects_folder, _SETTINGS_FILE)


def load_overload_settings(projects_folder: str) -> dict[str, Any]:
    path = settings_path(projects_folder)
    data: dict = {}
    if os.path.isfile(path):
        try:
            import json
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                data = raw
        except (OSError, ValueError):
            data = {}
    return merge_thresholds(data)


def save_overload_settings(projects_folder: str, payload: dict[str, Any]) -> dict[str, Any]:
    merged = merge_thresholds({**load_overload_settings(projects_folder), **(payload or {})})
    import json
    path = settings_path(projects_folder)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    return merged
