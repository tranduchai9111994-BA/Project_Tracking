"""
Advanced metrics — Burndown/Velocity, SLA, Capacity vs load, Slow heatmap,
Dependency blockers, Baseline vs Actual.

Tách khỏi dashboard_engine để tránh file quá lớn; gọi từ compute_all hoặc endpoint riêng.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Optional

from parser.excel_parser import ParsedData, FunctionRow, PhaseData

DONE = {"Closed", "Cancelled"}


def _parse_iso(d: Any) -> Optional[date]:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    if isinstance(d, str):
        s = d.strip()
        if not s:
            return None
        # Ưu tiên ISO
        try:
            return datetime.fromisoformat(s.replace("Z", "")[:19]).date()
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
            try:
                return datetime.strptime(s[:10], fmt).date()
            except ValueError:
                continue
    return None


def _week_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def compute_burndown_velocity(data: ParsedData, today: Optional[date] = None) -> dict[str, Any]:
    """
    Closed count theo tuần — dựa End date khi Closed, fallback Last Updated meta.
    Trả: weeks[], closed_per_week[], cumulative[], velocity (avg 4 tuần gần).
    """
    today = today or date.today()
    closed_by_week: dict[str, int] = defaultdict(int)

    for row in data.rows:
        last_upd = _parse_iso(row.meta.get("last_updated"))
        for phase_name, pd in row.phases.items():
            if pd.status != "Closed":
                continue
            event = _parse_iso(pd.end_date) or last_upd
            if event is None:
                continue
            wk = _week_monday(event).isoformat()
            closed_by_week[wk] += 1

    if not closed_by_week:
        return {
            "weeks": [],
            "closed_per_week": [],
            "cumulative": [],
            "velocity_4w": 0,
        }

    # Fill tuần liên tục từ min → today
    keys = sorted(closed_by_week.keys())
    start = datetime.fromisoformat(keys[0]).date()
    end = _week_monday(today)
    weeks: list[str] = []
    counts: list[int] = []
    cur = start
    while cur <= end:
        k = cur.isoformat()
        weeks.append(k)
        counts.append(closed_by_week.get(k, 0))
        cur += timedelta(days=7)

    cumulative = []
    s = 0
    for c in counts:
        s += c
        cumulative.append(s)

    last4 = counts[-4:] if counts else []
    velocity = round(sum(last4) / len(last4), 1) if last4 else 0

    return {
        "weeks": weeks,
        "closed_per_week": counts,
        "cumulative": cumulative,
        "velocity_4w": velocity,
        "total_closed_events": s,
    }


def compute_sla_violations(
    data: ParsedData,
    today: Optional[date] = None,
    must_have_days: int = 3,
    should_have_days: int = 7,
) -> dict[str, Any]:
    """
    Function có phase End < today, status chưa Closed/Cancelled.
    Must-have cảnh báo nếu trễ > must_have_days; Should-have > should_have_days.
    """
    today = today or date.today()
    items: list[dict] = []

    for row in data.rows:
        priority = str(row.meta.get("priority") or "")
        for phase_name, pd in row.phases.items():
            if pd.status in DONE:
                continue
            end = _parse_iso(pd.end_date)
            if end is None or end >= today:
                continue
            days_late = (today - end).days
            threshold = must_have_days if "must" in priority.lower() else should_have_days
            # Mọi priority quá End đều là violation; severity theo threshold
            severity = "critical" if days_late > threshold else "warning"
            items.append({
                "ma_cn": row.meta.get("ma_cn") or "",
                "ten_cn": row.meta.get("ten_cn") or "",
                "module": row.meta.get("module") or "",
                "priority": priority,
                "phase": phase_name,
                "end_date": end.isoformat(),
                "days_late": days_late,
                "threshold_days": threshold,
                "severity": severity,
                "pics": list(pd.pics or []),
                "status": pd.status or "",
            })

    items.sort(key=lambda x: (-x["days_late"], x.get("priority") or ""))
    critical = sum(1 for i in items if i["severity"] == "critical")
    return {
        "items": items,
        "total": len(items),
        "critical_count": critical,
        "warning_count": len(items) - critical,
        "thresholds": {
            "must_have_days": must_have_days,
            "should_have_days": should_have_days,
        },
    }


def compute_capacity_load(
    data: ParsedData,
    capacity: dict[str, Any],
    today: Optional[date] = None,
) -> dict[str, Any]:
    """
    So remaining MH (chưa Closed/Cancelled) theo PIC vs capacity MH/tuần.
    overload nếu remaining > capacity_week * 4 (ước lượng 1 tháng).
    """
    from analyzer.project_store import capacity_mh_for_pic

    today = today or date.today()
    remaining: dict[str, float] = defaultdict(float)
    closed: dict[str, float] = defaultdict(float)

    for row in data.rows:
        for pd in row.phases.values():
            mh = pd.estimate_mh
            if mh is None or mh <= 0:
                continue
            pics = pd.pics or ["(Unassigned)"]
            share = float(mh) / len(pics)
            for pic in pics:
                if pd.status == "Closed":
                    closed[pic] += share
                elif pd.status != "Cancelled":
                    remaining[pic] += share

    all_pics = sorted(set(remaining) | set(closed) | set((capacity.get("pics") or {}).keys()))
    rows = []
    for pic in all_pics:
        cap_mh = capacity_mh_for_pic(capacity, pic)
        rem = round(remaining.get(pic, 0), 1)
        cl = round(closed.get(pic, 0), 1)
        weeks_needed = round(rem / cap_mh, 1) if cap_mh > 0 else None
        rows.append({
            "pic": pic,
            "remaining_mh": rem,
            "closed_mh": cl,
            "capacity_mh_per_week": round(cap_mh, 1),
            "weeks_needed": weeks_needed,
            "overload": bool(weeks_needed is not None and weeks_needed > 4),
        })
    rows.sort(key=lambda r: r["remaining_mh"], reverse=True)
    return {
        "by_pic": rows,
        "default_md_per_week": capacity.get("default_md_per_week"),
        "overload_count": sum(1 for r in rows if r["overload"]),
    }


def compute_slow_heatmap(data: ParsedData, today: Optional[date] = None) -> dict[str, Any]:
    """
    Matrix PIC × Phase: số phase-record overdue hoặc stalled-ish (End < today, not done).
    """
    today = today or date.today()
    matrix: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    pics_set: set[str] = set()

    for row in data.rows:
        for phase_name, pd in row.phases.items():
            if pd.status in DONE:
                continue
            end = _parse_iso(pd.end_date)
            if end is None or end >= today:
                continue
            pics = pd.pics or ["(Unassigned)"]
            for pic in pics:
                pics_set.add(pic)
                matrix[pic][phase_name] += 1

    pics = sorted(pics_set)
    phases = list(data.all_phases)
    heatmap = {p: {ph: matrix[p].get(ph, 0) for ph in phases} for p in pics}
    return {
        "pics": pics,
        "phases": phases,
        "heatmap": heatmap,
        "total_slow": sum(sum(v.values()) for v in heatmap.values()),
    }


def compute_dependency_blockers(data: ParsedData) -> dict[str, Any]:
    """
    Parse function_lq → cạnh ma_cn phụ thuộc related.
    Liệt kê Must-have đang bị block bởi related chưa Closed toàn bộ phase cuối.
    """
    by_code: dict[str, FunctionRow] = {}
    for row in data.rows:
        code = str(row.meta.get("ma_cn") or "").strip()
        if code:
            by_code[code.upper()] = row

    last_phase = data.all_phases[-1] if data.all_phases else None
    edges: list[dict] = []
    blockers: list[dict] = []

    for row in data.rows:
        code = str(row.meta.get("ma_cn") or "").strip()
        raw_lq = row.meta.get("function_lq") or ""
        if not raw_lq:
            continue
        # Tách bằng dấu phẩy / chấm phẩy / xuống dòng
        parts = []
        for chunk in str(raw_lq).replace(";", ",").replace("\n", ",").split(","):
            c = chunk.strip()
            if c:
                parts.append(c)

        for dep in parts:
            dep_key = dep.upper()
            edges.append({"from": code, "depends_on": dep})
            dep_row = by_code.get(dep_key)
            if dep_row is None:
                continue
            # Related chưa xong phase cuối?
            blocked = False
            if last_phase:
                st = (dep_row.phases.get(last_phase) or PhaseData()).status
                blocked = st != "Closed"
            else:
                blocked = any(
                    (pd.status or "") not in DONE
                    for pd in dep_row.phases.values()
                )
            priority = str(row.meta.get("priority") or "")
            if blocked and "must" in priority.lower():
                blockers.append({
                    "ma_cn": code,
                    "ten_cn": row.meta.get("ten_cn") or "",
                    "module": row.meta.get("module") or "",
                    "priority": priority,
                    "blocked_by": dep,
                    "blocked_by_name": dep_row.meta.get("ten_cn") or "",
                    "blocked_by_module": dep_row.meta.get("module") or "",
                })

    return {
        "edges_count": len(edges),
        "blockers": blockers,
        "blocker_count": len(blockers),
    }


def compute_baseline_variance(data: ParsedData, top: Optional[int] = 200) -> dict[str, Any]:
    """
    Variance ngày: actual − plan.
    Plan = End (hoặc Planned trong extra nếu có).
    Actual = Actual trong extra / attributes proxy qua note không có —
              dùng last_updated khi Closed, hoặc end_date nếu chỉ có 1 mốc.
    Parser hiện map End/Actual cùng estimate_mh path; PhaseData.extra có thể chứa Planned/Actual.

    Args:
        top: cắt items ở top N sau khi sort theo |variance| desc.
             Truyền None hoặc 0 để lấy ALL items (dùng cho Excel export — rule V4).
    """
    items: list[dict] = []
    for row in data.rows:
        for phase_name, pd in row.phases.items():
            plan = _parse_iso(pd.extra.get("Planned") if pd.extra else None) or _parse_iso(pd.end_date)
            actual = _parse_iso(pd.extra.get("Actual") if pd.extra else None)
            if actual is None and pd.status == "Closed":
                actual = _parse_iso(row.meta.get("last_updated")) or _parse_iso(pd.end_date)
            if plan is None or actual is None:
                continue
            variance = (actual - plan).days
            items.append({
                "ma_cn": row.meta.get("ma_cn") or "",
                "ten_cn": row.meta.get("ten_cn") or "",
                "module": row.meta.get("module") or "",
                "phase": phase_name,
                "plan_date": plan.isoformat(),
                "actual_date": actual.isoformat(),
                "variance_days": variance,
                "status": pd.status or "",
                "late": variance > 0,
            })

    items.sort(key=lambda x: -abs(x["variance_days"]))
    late = [i for i in items if i["late"]]
    # top=None/0 → không cắt (rule V4 xuất ALL); top>0 → cắt top N cho FE render.
    trimmed = items[:top] if (top and top > 0) else items
    return {
        "items": trimmed,
        "total_compared": len(items),
        "late_count": len(late),
        "avg_variance_days": round(sum(i["variance_days"] for i in items) / len(items), 1) if items else 0,
    }
