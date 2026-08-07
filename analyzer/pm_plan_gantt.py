# -*- coding: utf-8 -*-
"""
Insights Gantt lịch trình PM — overdue, done, slip planned vs actual.

Dùng cho Chiều PM Phase B: summary cards + cảnh báo trên UI.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Optional

from analyzer.overdue import is_done_status


def _parse_iso(d: Optional[str]) -> Optional[date]:
    if not d:
        return None
    try:
        return datetime.strptime(str(d)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _is_pm_done(item: dict[str, Any]) -> bool:
    if item.get("is_phase_header"):
        return False
    status = item.get("status")
    if is_done_status(status):
        return True
    pct = item.get("percent_complete")
    if isinstance(pct, (int, float)) and pct >= 100:
        return True
    return False


def _slip_days(item: dict[str, Any]) -> Optional[int]:
    """Số ngày trễ so với kế hoạch (actual_end − planned end). Dương = trễ."""
    end = _parse_iso(item.get("end"))
    actual = _parse_iso(item.get("actual_end"))
    if end is None or actual is None:
        return None
    return (actual - end).days


def _is_pm_overdue(item: dict[str, Any], today: date) -> bool:
    if item.get("is_phase_header"):
        return False
    if _is_pm_done(item):
        return False
    end = _parse_iso(item.get("end"))
    if end is None:
        return False
    return end < today


def _item_snapshot(item: dict[str, Any], today: date) -> dict[str, Any]:
    slip = _slip_days(item)
    overdue = _is_pm_overdue(item, today)
    return {
        "name": item.get("name") or "",
        "stt": item.get("stt") or "",
        "phase": item.get("phase") or "",
        "start": item.get("start"),
        "end": item.get("end"),
        "actual_end": item.get("actual_end"),
        "status": item.get("status"),
        "percent_complete": item.get("percent_complete"),
        "overdue": overdue,
        "slip_days": slip,
        "done": _is_pm_done(item),
        "pic_fpt": item.get("pic_fpt") or [],
        "pic_client": item.get("pic_client") or [],
    }


def compute_pm_schedule_insights(
    plan: Optional[dict[str, Any]],
    *,
    today: Optional[date] = None,
) -> dict[str, Any]:
    """
    Tính summary + danh sách overdue / slip từ plan.schedule.

    Returns:
        summary: total_tasks, done, overdue, in_progress, with_actual, avg_slip_days, max_slip_days
        overdue_items: task chưa xong + End < today (top 50)
        slip_items: task có actual_end trễ hơn end (slip_days > 0, top 50)
    """
    today = today or date.today()
    schedule = (plan or {}).get("schedule") or []
    tasks = [it for it in schedule if not it.get("is_phase_header")]

    done = 0
    overdue = 0
    in_progress = 0
    with_actual = 0
    slip_vals: list[int] = []
    overdue_items: list[dict[str, Any]] = []
    slip_items: list[dict[str, Any]] = []

    for item in tasks:
        snap = _item_snapshot(item, today)
        if snap["done"]:
            done += 1
        elif snap["overdue"]:
            overdue += 1
            overdue_items.append(snap)
        else:
            in_progress += 1

        if snap.get("actual_end"):
            with_actual += 1
        slip = snap.get("slip_days")
        if slip is not None:
            slip_vals.append(slip)
            if slip > 0:
                slip_items.append(snap)

    overdue_items.sort(key=lambda x: x.get("end") or "")
    slip_items.sort(key=lambda x: x.get("slip_days") or 0, reverse=True)

    positive_slips = [s for s in slip_vals if s > 0]
    avg_slip = round(sum(positive_slips) / len(positive_slips), 1) if positive_slips else 0
    max_slip = max(positive_slips) if positive_slips else 0

    return {
        "summary": {
            "total_tasks": len(tasks),
            "done": done,
            "overdue": overdue,
            "in_progress": in_progress,
            "with_actual_end": with_actual,
            "avg_slip_days": avg_slip,
            "max_slip_days": max_slip,
        },
        "overdue_items": overdue_items[:50],
        "slip_items": slip_items[:50],
    }


def _monday_on_or_before(d: date) -> date:
    return d - timedelta(days=d.weekday())


def compute_pm_week_axis(plan: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    """Trục tuần ISO cho Master grid + week slider."""
    if not plan:
        return []
    schedule = plan.get("schedule") or []
    weeks_meta = plan.get("weeks") or []
    project_start = _parse_iso(plan.get("project_start"))

    dates: list[date] = []
    for it in schedule:
        for key in ("start", "end", "actual_end"):
            d = _parse_iso(it.get(key))
            if d:
                dates.append(d)

    if not project_start and dates:
        project_start = min(dates)
    if not project_start:
        project_start = date.today()

    anchor = _monday_on_or_before(project_start)
    n = len(weeks_meta) if weeks_meta else 8
    if dates:
        max_d = max(dates)
        needed = int((max_d - anchor).days / 7) + 2
        n = max(n, needed)

    axis: list[dict[str, Any]] = []
    for i in range(n):
        wstart = anchor + timedelta(days=7 * i)
        wend = wstart + timedelta(days=6)
        label = f"W{i + 1}"
        month = ""
        if i < len(weeks_meta):
            wm = weeks_meta[i]
            raw_label = str(wm.get("label") or label)
            label = raw_label if raw_label.upper().startswith("W") else f"W{raw_label}"
            month = wm.get("month") or ""
        axis.append({
            "index": i,
            "label": label,
            "month": month,
            "start": wstart.isoformat(),
            "end": wend.isoformat(),
        })
    return axis


def _week_indices_for_range(
    start: Optional[date],
    end: Optional[date],
    axis: list[dict[str, Any]],
) -> list[int]:
    if not start or not end or not axis:
        return []
    out: list[int] = []
    for w in axis:
        ws = _parse_iso(w.get("start"))
        we = _parse_iso(w.get("end"))
        if ws and we and start <= we and end >= ws:
            out.append(w["index"])
    return out


def build_pm_master_week_grid(
    plan: Optional[dict[str, Any]],
    axis: list[dict[str, Any]],
    *,
    today: Optional[date] = None,
) -> dict[str, Any]:
    """Hàng × tuần cho view Master (ô active khi task giao tuần)."""
    today = today or date.today()
    rows: list[dict[str, Any]] = []
    if not plan:
        return {"rows": [], "week_count": 0}

    for m in (plan.get("milestones") or [])[:40]:
        rows.append({
            "name": m.get("name") or "",
            "stt": m.get("stt") or "",
            "kind": "milestone",
            "week_active": [],
            "start": None,
            "end": None,
            "status": None,
            "done": False,
            "overdue": False,
        })

    for it in plan.get("schedule") or []:
        start = _parse_iso(it.get("start"))
        end = _parse_iso(it.get("end"))
        active = _week_indices_for_range(start, end, axis)
        rows.append({
            "name": it.get("name") or "",
            "stt": it.get("stt") or "",
            "kind": "phase_header" if it.get("is_phase_header") else "task",
            "week_active": active,
            "start": it.get("start"),
            "end": it.get("end"),
            "status": it.get("status"),
            "done": _is_pm_done(it),
            "overdue": _is_pm_overdue(it, today),
        })

    return {"rows": rows, "week_count": len(axis)}


def compute_pm_milestone_markers(plan: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    """Điểm milestone trên timeline — section header + WBS khớp tên."""
    if not plan:
        return []
    markers: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for it in plan.get("schedule") or []:
        end = it.get("end")
        if not end:
            continue
        stt = str(it.get("stt") or "").strip()
        is_marker = it.get("is_phase_header") or (len(stt) == 1 and stt.isalpha())
        if not is_marker:
            continue
        name = it.get("name") or ""
        key = (name, end)
        if key in seen:
            continue
        seen.add(key)
        markers.append({
            "name": name,
            "date": end,
            "stt": stt,
            "kind": "section",
        })

    for m in plan.get("milestones") or []:
        mname = (m.get("name") or "").strip()
        if not mname:
            continue
        low = mname.lower()
        for it in plan.get("schedule") or []:
            sname = (it.get("name") or "").lower()
            if low in sname or sname in low:
                end = it.get("end")
                if end:
                    key = (mname, end)
                    if key not in seen:
                        seen.add(key)
                        markers.append({
                            "name": mname,
                            "date": end,
                            "stt": m.get("stt") or "",
                            "kind": "wbs",
                        })
                break

    return markers[:40]


def compute_pm_day_axis(plan: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    """Trục ngày từ day_columns Excel hoặc synthesize từ schedule."""
    if not plan:
        return []
    raw = plan.get("day_columns") or []
    axis: list[dict[str, Any]] = []
    for i, dc in enumerate(raw):
        d = _parse_iso(dc.get("date"))
        if not d:
            continue
        axis.append({
            "index": len(axis),
            "label": dc.get("label") or "",
            "date": d.isoformat(),
            "weekday": d.weekday(),
        })
    if axis:
        return axis

    dates: list[date] = []
    for it in plan.get("schedule") or []:
        for key in ("start", "end", "actual_end"):
            d = _parse_iso(it.get(key))
            if d:
                dates.append(d)
    if not dates:
        return []
    d0, d1 = min(dates), max(dates)
    cur = d0
    idx = 0
    lbl_map = ["M", "T", "W", "T", "F", "S", "S"]
    while cur <= d1 and idx < 180:
        axis.append({
            "index": idx,
            "label": lbl_map[cur.weekday() % 7] if cur.weekday() < 7 else "D",
            "date": cur.isoformat(),
            "weekday": cur.weekday(),
        })
        cur += timedelta(days=1)
        idx += 1
    return axis


def _day_indices_for_range(
    start: Optional[date],
    end: Optional[date],
    axis: list[dict[str, Any]],
) -> list[int]:
    if not start or not end or not axis:
        return []
    out: list[int] = []
    for w in axis:
        d = _parse_iso(w.get("date"))
        if d and start <= d <= end:
            out.append(w["index"])
    return out


def build_pm_day_grid(
    plan: Optional[dict[str, Any]],
    axis: list[dict[str, Any]],
    *,
    today: Optional[date] = None,
) -> dict[str, Any]:
    """Lưới ngày chi tiết — ô active khi task giao ngày."""
    today = today or date.today()
    rows: list[dict[str, Any]] = []
    if not plan or not axis:
        return {"rows": [], "day_count": 0}

    for it in plan.get("schedule") or []:
        start = _parse_iso(it.get("start"))
        end = _parse_iso(it.get("end"))
        active = _day_indices_for_range(start, end, axis)
        rows.append({
            "name": it.get("name") or "",
            "stt": it.get("stt") or "",
            "kind": "phase_header" if it.get("is_phase_header") else "task",
            "day_active": active,
            "start": it.get("start"),
            "end": it.get("end"),
            "status": it.get("status"),
            "done": _is_pm_done(it),
            "overdue": _is_pm_overdue(it, today),
        })

    return {"rows": rows, "day_count": len(axis)}


def compute_pm_resource_heatmap(
    plan: Optional[dict[str, Any]],
    week_axis: list[dict[str, Any]],
    *,
    top_pics: int = 8,
) -> dict[str, Any]:
    """Đếm số task active mỗi tuần — tổng + top PIC (resource load)."""
    n = len(week_axis)
    if not plan or not n:
        return {"week_labels": [], "rows": [], "max_count": 0}

    totals = [0] * n
    pic_map: dict[str, list[int]] = {}
    tasks = [it for it in (plan.get("schedule") or []) if not it.get("is_phase_header")]

    for it in tasks:
        start = _parse_iso(it.get("start"))
        end = _parse_iso(it.get("end"))
        active = _week_indices_for_range(start, end, week_axis)
        pics = [p for p in (it.get("pic_fpt") or []) if str(p).strip()]
        pic_key = pics[0] if pics else "(chưa PIC)"
        if pic_key not in pic_map:
            pic_map[pic_key] = [0] * n
        for idx in active:
            if 0 <= idx < n:
                totals[idx] += 1
                pic_map[pic_key][idx] += 1

    ranked = sorted(pic_map.items(), key=lambda x: sum(x[1]), reverse=True)[:top_pics]
    rows: list[dict[str, Any]] = [{"label": "Tổng", "counts": totals, "kind": "total"}]
    for pic, counts in ranked:
        if pic == "(chưa PIC)" and sum(counts) == 0:
            continue
        rows.append({"label": pic, "counts": counts, "kind": "pic"})

    max_val = max(totals) if totals else 0
    return {
        "week_labels": [w.get("label") or "" for w in week_axis],
        "rows": rows,
        "max_count": max_val,
    }


def build_pm_gantt_view(plan: Optional[dict[str, Any]], *, today: Optional[date] = None) -> Optional[dict[str, Any]]:
    """Bundle Phase C/D/E: week + day grid + milestones + resource heatmap."""
    if not plan or not (plan.get("schedule") or plan.get("milestones")):
        return None
    today = today or date.today()
    axis = compute_pm_week_axis(plan)
    grid = build_pm_master_week_grid(plan, axis, today=today)
    day_axis = compute_pm_day_axis(plan)
    day_grid = build_pm_day_grid(plan, day_axis, today=today)
    markers = compute_pm_milestone_markers(plan)
    heatmap = compute_pm_resource_heatmap(plan, axis)
    return {
        "project_start": plan.get("project_start"),
        "week_axis": axis,
        "master_grid": grid,
        "day_axis": day_axis,
        "day_grid": day_grid,
        "milestone_markers": markers,
        "resource_heatmap": heatmap,
        "default_window_weeks": 12,
        "default_window_days": 21,
    }
