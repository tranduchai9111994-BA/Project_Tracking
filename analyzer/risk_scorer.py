"""
Risk Scorer — Tính điểm rủi ro tổng hợp (0-100) cho mỗi function.

Trọng số (theo UPGRADE_V2.md B7):
- +20 nếu Priority = Must-have; +10 nếu Should-have
- +15 nếu Complexity = High; +5 nếu Medium
- +20 nếu có ít nhất 1 phase overdue
- +10 mỗi 7 ngày overdue (cap +30)
- +15 nếu phase active không có PIC
- +10 nếu có phase duration bất thường (> threshold)
- +10 nếu bị stalled (phase trước Closed, phase sau chưa bắt đầu)
- +5  nếu có Risk/Blocker note
Cap tối đa 100.
"""
from datetime import date
from typing import Any

from parser.excel_parser import ParsedData, FunctionRow


def compute_risk_score(
    row: FunctionRow,
    today: date,
    phase_names: list[str],
    long_duration_threshold: int = 3,
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

    # === Priority ===
    if "Must" in priority or "must" in priority:
        score += 20
        factors.append("Must-have")
        breakdown["priority"] = 20
    elif "Should" in priority or "should" in priority:
        score += 10
        factors.append("Should-have")
        breakdown["priority"] = 10

    # === Complexity ===
    if "High" in complexity or "high" in complexity or "Cao" in complexity:
        score += 15
        factors.append("Complexity cao")
        breakdown["complexity"] = 15
    elif "Medium" in complexity or "medium" in complexity or "TB" in complexity:
        score += 5
        breakdown["complexity"] = 5

    # === Overdue ===
    max_overdue_days = 0
    has_overdue = False
    for _, pd in row.phases.items():
        if (pd.end_date
            and pd.status not in ("Closed", "Cancelled", None)
            and pd.end_date < today):
            has_overdue = True
            days = (today - pd.end_date).days
            if days > max_overdue_days:
                max_overdue_days = days

    if has_overdue:
        score += 20
        factors.append("Có phase overdue")
        breakdown["overdue"] = 20
        extra = min(30, (max_overdue_days // 7) * 10)
        if extra > 0:
            score += extra
            factors.append(f"Trễ {max_overdue_days} ngày")
            breakdown["overdue_days"] = extra

    # === Unassigned: thiếu PIC khi đã tới lượt (pred Closed + Start) ===
    from analyzer.unassigned import is_unassigned_phase
    unassigned = any(
        is_unassigned_phase(row, pname, pd, phase_names, today)
        for pname, pd in row.phases.items()
    )
    if unassigned:
        score += 15
        factors.append("Không có PIC")
        breakdown["unassigned"] = 15

    # === Long duration ===
    long_dur = False
    for _, pd in row.phases.items():
        duration = None
        if pd.start_date and pd.end_date:
            duration = (pd.end_date - pd.start_date).days
        elif pd.start_date and not pd.end_date and pd.status == "In-progress":
            duration = (today - pd.start_date).days
        if (duration is not None
            and duration > long_duration_threshold
            and pd.status not in ("Closed", "Cancelled")):
            long_dur = True
            break
    if long_dur:
        score += 10
        factors.append("Duration bất thường")
        breakdown["long_duration"] = 10

    # === Stalled ===
    stalled = False
    for i in range(len(phase_names) - 1):
        curr = row.phases.get(phase_names[i])
        nxt = row.phases.get(phase_names[i + 1])
        curr_done = curr and curr.status == "Closed"
        next_not_started = (not nxt) or (nxt.status in (None, "Open"))
        if curr_done and next_not_started:
            stalled = True
            break
    if stalled:
        score += 10
        factors.append("Bị đình trệ")
        breakdown["stalled"] = 10

    # === Risk/Blocker note ===
    risk_note = row.meta.get("risk_blocker")
    if risk_note and str(risk_note).strip():
        score += 5
        factors.append("Có risk note")
        breakdown["risk_note"] = 5

    return {
        "score": min(100, score),
        "factors": factors,
        "breakdown": breakdown,
    }


def compute_all_risk_scores(
    data: ParsedData,
    today: date,
    long_duration_threshold: int = 3,
) -> list[dict]:
    """Tính risk score cho tất cả functions, sort giảm dần theo score."""
    phase_names = [pg.name for pg in data.phase_groups]
    results: list[dict] = []
    for row in data.rows:
        rs = compute_risk_score(row, today, phase_names, long_duration_threshold)
        results.append({
            "ma_cn": row.meta.get("ma_cn", ""),
            "ten_cn": row.meta.get("ten_cn", ""),
            "module": row.meta.get("module", ""),
            "priority": row.meta.get("priority", ""),
            "complexity": row.meta.get("complexity", ""),
            "risk_score": rs["score"],
            "risk_factors": rs["factors"],
            "risk_breakdown": rs["breakdown"],
        })
    results.sort(key=lambda x: x["risk_score"], reverse=True)
    return results
