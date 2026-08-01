"""
Insight strip — delta OD / UA / ST theo module (không chỉ tổng).

So sánh snapshot trước vs hiện tại bằng DashboardEngine metrics.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any, Optional

from parser.excel_parser import ParsedData


def _count_by_module(items: list[dict], *, module_key: str = "module") -> Counter:
    c: Counter = Counter()
    for it in items or []:
        mod = str(it.get(module_key) or "").strip() or "(trống)"
        c[mod] += 1
    return c


def compute_module_issue_deltas(
    previous: ParsedData,
    current: ParsedData,
    *,
    today: Optional[date] = None,
    top_n: int = 8,
) -> dict[str, Any]:
    """
    Trả deltas theo module cho Overdue / Unassigned / Stalled.

    modules[]: {module, overdue_delta, unassigned_delta, stalled_delta,
                overdue_cur, ...}
    """
    today = today or date.today()
    from analyzer.dashboard_engine import DashboardEngine

    eng = DashboardEngine()
    eng.today = today
    cur_m = eng.compute_all(current)
    prev_m = eng.compute_all(previous)

    cur_od = _count_by_module(cur_m.get("overdue_list") or [])
    prev_od = _count_by_module(prev_m.get("overdue_list") or [])
    cur_ua = _count_by_module(cur_m.get("unassigned_tasks") or [])
    prev_ua = _count_by_module(prev_m.get("unassigned_tasks") or [])
    cur_st = _count_by_module(
        list((cur_m.get("stalled_tasks") or {}).get("items") or [])
    )
    prev_st = _count_by_module(
        list((prev_m.get("stalled_tasks") or {}).get("items") or [])
    )

    all_mods = sorted(
        set(cur_od) | set(prev_od) | set(cur_ua) | set(prev_ua) | set(cur_st) | set(prev_st)
    )
    modules: list[dict[str, Any]] = []
    for mod in all_mods:
        od_c, od_p = cur_od.get(mod, 0), prev_od.get(mod, 0)
        ua_c, ua_p = cur_ua.get(mod, 0), prev_ua.get(mod, 0)
        st_c, st_p = cur_st.get(mod, 0), prev_st.get(mod, 0)
        modules.append({
            "module": mod,
            "overdue_cur": od_c,
            "overdue_prev": od_p,
            "overdue_delta": od_c - od_p,
            "unassigned_cur": ua_c,
            "unassigned_prev": ua_p,
            "unassigned_delta": ua_c - ua_p,
            "stalled_cur": st_c,
            "stalled_prev": st_p,
            "stalled_delta": st_c - st_p,
            "abs_change": abs(od_c - od_p) + abs(ua_c - ua_p) + abs(st_c - st_p),
        })

    modules.sort(key=lambda m: (-m["abs_change"], m["module"]))
    top = modules[: max(1, top_n)]

    totals = {
        "overdue_delta": sum(cur_od.values()) - sum(prev_od.values()),
        "unassigned_delta": sum(cur_ua.values()) - sum(prev_ua.values()),
        "stalled_delta": sum(cur_st.values()) - sum(prev_st.values()),
        "overdue_cur": sum(cur_od.values()),
        "unassigned_cur": sum(cur_ua.values()),
        "stalled_cur": sum(cur_st.values()),
    }
    return {
        "modules": top,
        "all_modules": modules,
        "totals": totals,
        "message": (
            f"Top {len(top)} module biến động OD/UA/ST "
            f"(OD {totals['overdue_delta']:+d} · UA {totals['unassigned_delta']:+d} · "
            f"ST {totals['stalled_delta']:+d})"
        ),
    }
