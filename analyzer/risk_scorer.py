"""
Risk Scorer — Tính điểm rủi ro tổng hợp (0-100) cho mỗi function.

Trọng số (theo UPGRADE_V2.md B7 + Phase D):
- +20 nếu Priority = Must-have; +10 nếu Should-have
- +15 nếu Complexity = High; +5 nếu Medium
- +20 nếu có ít nhất 1 phase overdue
- +10 mỗi 7 ngày overdue (cap +30)
- +15 nếu phase active không có PIC
- +10 nếu có phase duration bất thường (> threshold)
- +10 nếu bị stalled (pred Closed, phase sau chưa start, End phase chờ đã quá)
- +5  nếu có Risk/Blocker note
- +15 nếu PIC của function đang overload (Phase D — feed pic_overload)
- +10 nếu module bị cascade delay từ predecessor (Phase D)
Cap tối đa 100.

Phase D cũng expose `compute_pmo_risk` — rollup chiều Resource + Dependency
cho PM (không chỉ per-function).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Optional, Sequence

from parser.excel_parser import ParsedData, FunctionRow


# Điểm Phase D
PIC_OVERLOAD_POINTS = 15
CASCADE_DELAY_POINTS = 10


def compute_risk_score(
    row: FunctionRow,
    today: date,
    phase_names: list[str],
    long_duration_threshold: int = 3,
    *,
    overloaded_pics: Optional[set[str]] = None,
    cascade_blocked_by: Optional[str] = None,
) -> dict[str, Any]:
    """
    Tính điểm rủi ro cho 1 function.
    Return: {score, factors: list[str], breakdown: dict[str, int]}
    """
    score = 0
    factors: list[str] = []
    breakdown: dict[str, int] = {}

    priority = str(row.meta.get("priority") or "").strip()
    complexity = str(row.meta.get("complexity") or "").strip()

    # factors_detail: câu chi tiết phase + ngày + điểm (cho export Lý do)
    factors_detail: list[str] = []

    # === Priority ===
    if "Must" in priority or "must" in priority:
        score += 20
        factors.append("Must-have")
        breakdown["priority"] = 20
        factors_detail.append("Must-have (+20)")
    elif "Should" in priority or "should" in priority:
        score += 10
        factors.append("Should-have")
        breakdown["priority"] = 10
        factors_detail.append("Should-have (+10)")

    # === Complexity ===
    if "High" in complexity or "high" in complexity or "Cao" in complexity:
        score += 15
        factors.append("Complexity cao")
        breakdown["complexity"] = 15
        factors_detail.append("Complexity cao (+15)")
    elif "Medium" in complexity or "medium" in complexity or "TB" in complexity:
        score += 5
        breakdown["complexity"] = 5
        factors_detail.append("Complexity TB (+5)")

    # === Overdue ===
    max_overdue_days = 0
    overdue_phase = ""
    has_overdue = False
    for pname, pd in row.phases.items():
        if (pd.end_date
            and pd.status not in ("Closed", "Cancelled", None)
            and pd.end_date < today):
            has_overdue = True
            days = (today - pd.end_date).days
            if days > max_overdue_days:
                max_overdue_days = days
                overdue_phase = pname

    if has_overdue:
        score += 20
        factors.append("Có phase overdue")
        breakdown["overdue"] = 20
        ph_lbl = f" «{overdue_phase}»" if overdue_phase else ""
        factors_detail.append(f"Overdue{ph_lbl} {max_overdue_days}d (+20)")
        extra = min(30, (max_overdue_days // 7) * 10)
        if extra > 0:
            score += extra
            factors.append(f"Trễ {max_overdue_days} ngày")
            breakdown["overdue_days"] = extra
            factors_detail.append(f"Trễ thêm {max_overdue_days}d (+{extra})")

    # === Unassigned: thiếu PIC khi đã tới lượt (pred Closed + Start) ===
    from analyzer.unassigned import is_unassigned_phase
    unassigned_phases = [
        pname for pname, pd in row.phases.items()
        if is_unassigned_phase(row, pname, pd, phase_names, today)
    ]
    if unassigned_phases:
        score += 15
        factors.append("Không có PIC")
        breakdown["unassigned"] = 15
        ph = unassigned_phases[0]
        more = f" +{len(unassigned_phases) - 1}" if len(unassigned_phases) > 1 else ""
        factors_detail.append(f"Thiếu PIC «{ph}»{more} (+15)")

    # === Long duration ===
    long_dur_phase = ""
    long_dur_days = 0
    for pname, pd in row.phases.items():
        duration = None
        if pd.start_date and pd.end_date:
            duration = (pd.end_date - pd.start_date).days
        elif pd.start_date and not pd.end_date and pd.status == "In-progress":
            duration = (today - pd.start_date).days
        if (duration is not None
            and duration > long_duration_threshold
            and pd.status not in ("Closed", "Cancelled")):
            if duration > long_dur_days:
                long_dur_days = duration
                long_dur_phase = pname
    if long_dur_phase:
        score += 10
        factors.append("Duration bất thường")
        breakdown["long_duration"] = 10
        factors_detail.append(
            f"Duration «{long_dur_phase}» {long_dur_days}d > ngưỡng "
            f"{long_duration_threshold} (+10)"
        )

    # === Stalled (bỏ qua nếu đã Closed hết / phase cuối Closed) ===
    from analyzer.stalled import is_fully_closed, is_stalled_transition, prev_phases_all_closed

    stalled_from = stalled_to = ""
    if not is_fully_closed(row, phase_names):
        for i in range(len(phase_names) - 1):
            if not prev_phases_all_closed(row, phase_names, i):
                continue
            curr = row.phases.get(phase_names[i])
            nxt = row.phases.get(phase_names[i + 1])
            if is_stalled_transition(curr, nxt, today):
                stalled_from = phase_names[i]
                stalled_to = phase_names[i + 1]
                break
    if stalled_from:
        score += 10
        factors.append("Bị đình trệ")
        breakdown["stalled"] = 10
        factors_detail.append(f"Đình trệ «{stalled_from}»→«{stalled_to}» (+10)")

    # === Risk/Blocker note ===
    risk_note = row.meta.get("risk_blocker")
    if risk_note and str(risk_note).strip():
        score += 5
        factors.append("Có risk note")
        breakdown["risk_note"] = 5
        factors_detail.append("Có risk note (+5)")

    # === Phase D: PIC Overload ===
    overload_hit: list[str] = []
    if overloaded_pics:
        for pd in row.phases.values():
            for pic in (pd.pics or []):
                if pic and pic in overloaded_pics and pic not in overload_hit:
                    overload_hit.append(pic)
        if overload_hit:
            score += PIC_OVERLOAD_POINTS
            label = ", ".join(overload_hit[:3])
            if len(overload_hit) > 3:
                label += f" (+{len(overload_hit) - 3})"
            factors.append(f"PIC overload: {label}")
            breakdown["pic_overload"] = PIC_OVERLOAD_POINTS
            factors_detail.append(f"PIC overload: {label} (+{PIC_OVERLOAD_POINTS})")

    # === Phase D: Module cascade delay ===
    if cascade_blocked_by:
        score += CASCADE_DELAY_POINTS
        factors.append(f"Cascade delay từ {cascade_blocked_by}")
        breakdown["cascade_delay"] = CASCADE_DELAY_POINTS
        factors_detail.append(
            f"Cascade delay từ {cascade_blocked_by} (+{CASCADE_DELAY_POINTS})"
        )

    return {
        "score": min(100, score),
        "factors": factors,
        "factors_detail": factors_detail,
        "breakdown": breakdown,
        "overload_pics": overload_hit,
        "cascade_from": cascade_blocked_by,
    }


def compute_all_risk_scores(
    data: ParsedData,
    today: date,
    long_duration_threshold: int = 3,
    *,
    overloaded_pics: Optional[set[str]] = None,
    blocked_by_map: Optional[dict[str, str]] = None,
) -> list[dict]:
    """Tính risk score cho tất cả functions, sort giảm dần theo score."""
    phase_names = [pg.name for pg in data.phase_groups]
    ol = overloaded_pics or set()
    bmap = blocked_by_map or {}
    results: list[dict] = []
    for row in data.rows:
        module = str(row.meta.get("module") or "").strip()
        rs = compute_risk_score(
            row, today, phase_names, long_duration_threshold,
            overloaded_pics=ol,
            cascade_blocked_by=bmap.get(module),
        )
        entry = {
            "ma_cn": row.meta.get("ma_cn", ""),
            "ten_cn": row.meta.get("ten_cn", ""),
            "module": row.meta.get("module", ""),
            "quy_trinh": row.meta.get("quy_trinh") or row.meta.get("process") or "",
            "priority": row.meta.get("priority", ""),
            "complexity": row.meta.get("complexity", ""),
            "risk_score": rs["score"],
            "risk_factors": rs["factors"],
            "risk_factors_detail": rs.get("factors_detail") or rs["factors"],
            "risk_breakdown": rs["breakdown"],
            "overload_pics": rs.get("overload_pics") or [],
            "cascade_from": rs.get("cascade_from"),
        }
        results.append(entry)
    results.sort(key=lambda x: x["risk_score"], reverse=True)
    return results


def _risk_level(score_or_count: float, *, kind: str = "score") -> str:
    if kind == "count":
        if score_or_count >= 5:
            return "cao"
        if score_or_count >= 1:
            return "trung bình"
        return "thấp"
    if score_or_count >= 70:
        return "cao"
    if score_or_count >= 40:
        return "trung bình"
    return "thấp"


def compute_pmo_risk(
    data: ParsedData,
    today: Optional[date] = None,
    *,
    long_duration_threshold: int = 3,
    module_order: Optional[Sequence[str]] = None,
    overloaded_pics: Optional[set[str]] = None,
    overload_thresholds: Optional[dict] = None,
    function_lq_blocker_count: Optional[int] = None,
) -> dict[str, Any]:
    """
    Phase D entry: risk scores + chiều Resource / Dependency cho PM.

    Nếu `overloaded_pics` None → tự tính từ data (single-project).
    Truyền sẵn set từ compute_pic_overload (đa dự án) khi có.
    """
    today = today or date.today()

    # --- Resource: PIC overload ---
    if overloaded_pics is None:
        from analyzer.pic_overload import overloaded_pics_for_data
        overloaded_pics = overloaded_pics_for_data(
            data, today=today, thresholds=overload_thresholds,
        )
    else:
        overloaded_pics = set(overloaded_pics)

    # --- Dependency: module cascade ---
    from analyzer.module_dependency import compute_module_cascade
    cascade = compute_module_cascade(
        data, module_order, today=today,
    )
    blocked_by_map = cascade.get("blocked_by_map") or {}

    risk_scores = compute_all_risk_scores(
        data, today, long_duration_threshold,
        overloaded_pics=overloaded_pics,
        blocked_by_map=blocked_by_map,
    )

    # Functions / modules touched by overload
    funcs_ol = 0
    mods_ol: set[str] = set()
    pics_on_funcs: dict[str, int] = defaultdict(int)
    for r in risk_scores:
        hits = r.get("overload_pics") or []
        if hits:
            funcs_ol += 1
            if r.get("module"):
                mods_ol.add(str(r["module"]))
            for p in hits:
                pics_on_funcs[str(p)] += 1

    resource = {
        "overload_pic_count": len(overloaded_pics),
        "overload_pics": sorted(overloaded_pics),
        "functions_touched": funcs_ol,
        "modules_touched": sorted(mods_ol),
        "pic_function_hits": [
            {"pic": p, "functions": n}
            for p, n in sorted(pics_on_funcs.items(), key=lambda x: -x[1])
        ],
        "risk_level": _risk_level(len(overloaded_pics), kind="count"),
        "points_per_hit": PIC_OVERLOAD_POINTS,
    }

    lq_count = function_lq_blocker_count
    if lq_count is None:
        try:
            from analyzer.advanced_metrics import compute_dependency_blockers
            lq_count = int(
                (compute_dependency_blockers(data) or {}).get("blocker_count") or 0
            )
        except Exception:
            lq_count = 0

    dependency = {
        "gate_phase": cascade.get("gate_phase"),
        "cascade_warning_count": cascade.get("warning_count", 0),
        "modules_blocked": cascade.get("modules_blocked") or [],
        "warnings": cascade.get("warnings") or [],
        "function_lq_blocker_count": lq_count,
        "risk_level": _risk_level(
            (cascade.get("warning_count") or 0) + (1 if lq_count else 0),
            kind="count",
        ),
        "points_per_hit": CASCADE_DELAY_POINTS,
        "assumptions": cascade.get("assumptions") or [],
    }

    # Module rollup
    by_mod: dict[str, dict] = {}
    for r in risk_scores:
        m = str(r.get("module") or "").strip() or "(Không có module)"
        bucket = by_mod.setdefault(m, {
            "module": m,
            "function_count": 0,
            "high_risk_count": 0,
            "sum_score": 0,
            "max_score": 0,
            "resource_flag": False,
            "dependency_flag": m in blocked_by_map,
            "blocked_by": blocked_by_map.get(m),
        })
        sc = int(r.get("risk_score") or 0)
        bucket["function_count"] += 1
        bucket["sum_score"] += sc
        bucket["max_score"] = max(bucket["max_score"], sc)
        if sc >= 50:
            bucket["high_risk_count"] += 1
        if r.get("overload_pics"):
            bucket["resource_flag"] = True

    modules = []
    for m, b in by_mod.items():
        n = b["function_count"] or 1
        modules.append({
            "module": m,
            "function_count": b["function_count"],
            "avg_risk": round(b["sum_score"] / n, 1),
            "max_risk": b["max_score"],
            "high_risk_count": b["high_risk_count"],
            "resource_flag": b["resource_flag"],
            "dependency_flag": b["dependency_flag"],
            "blocked_by": b["blocked_by"],
        })
    modules.sort(key=lambda x: (-x["avg_risk"], -x["high_risk_count"], x["module"]))

    high_risk = sum(1 for r in risk_scores if (r.get("risk_score") or 0) >= 50)
    return {
        "risk_scores": risk_scores,
        "summary": {
            "function_count": len(risk_scores),
            "high_risk_count": high_risk,
            "resource_level": resource["risk_level"],
            "dependency_level": dependency["risk_level"],
            "overload_pic_count": resource["overload_pic_count"],
            "cascade_warning_count": dependency["cascade_warning_count"],
        },
        "dimensions": {
            "resource": resource,
            "dependency": dependency,
        },
        "modules": modules,
        "cascade": {
            "gate_phase": cascade.get("gate_phase"),
            "ordered_modules": cascade.get("ordered_modules"),
            "by_module": cascade.get("by_module"),
        },
        "scoring_notes": [
            f"PIC overload → +{PIC_OVERLOAD_POINTS} điểm / function có PIC đang overload.",
            f"Cascade delay → +{CASCADE_DELAY_POINTS} điểm / function thuộc module bị block.",
            "Các yếu tố cũ (priority, complexity, overdue, unassigned, duration, stalled, note) giữ nguyên.",
            "Điểm tổng cap 100.",
        ],
    }
