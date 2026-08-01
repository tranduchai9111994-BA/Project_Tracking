"""
Risk trend (theo snapshot) + mitigation tracking (note / owner / target date).

Không phải JIRA — chỉ meta gắn function (ma_cn) hoặc module trong project store.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from parser.excel_parser import ParsedData

from analyzer.risk_scorer import compute_all_risk_scores


def summarize_risk_snapshot(
    data: ParsedData,
    today: Optional[date] = None,
) -> dict[str, Any]:
    """Tóm tắt risk 1 snapshot: avg / high_count / top scores."""
    today = today or date.today()
    scores = compute_all_risk_scores(data, today)
    if not scores:
        return {
            "function_count": 0,
            "avg_score": 0.0,
            "high_risk_count": 0,
            "max_score": 0,
        }
    vals = [int(r.get("risk_score") or 0) for r in scores]
    high = sum(1 for v in vals if v >= 50)
    return {
        "function_count": len(vals),
        "avg_score": round(sum(vals) / len(vals), 1),
        "high_risk_count": high,
        "max_score": max(vals),
    }


def compute_risk_trend(
    snapshots: list[tuple[date, ParsedData]],
    *,
    weekly: bool = True,
) -> dict[str, Any]:
    """
    Chuỗi risk theo thời gian từ lịch sử snapshot.

    snapshots: (as_of, ParsedData) tăng dần.
    """
    from analyzer.earned_value import _week_monday

    if not snapshots:
        return {"points": [], "message": "Chưa có snapshot để xem xu hướng risk."}

    picked: dict[str, tuple[date, ParsedData]] = {}
    for as_of, pdata in snapshots:
        if pdata is None:
            continue
        key = _week_monday(as_of).isoformat() if weekly else as_of.isoformat()
        prev = picked.get(key)
        if prev is None or as_of >= prev[0]:
            picked[key] = (as_of, pdata)

    points: list[dict[str, Any]] = []
    for key in sorted(picked.keys()):
        as_of, pdata = picked[key]
        sm = summarize_risk_snapshot(pdata, today=as_of)
        points.append({
            "date": as_of.isoformat(),
            "week": key,
            **sm,
        })

    delta_high = None
    delta_avg = None
    if len(points) >= 2:
        delta_high = points[-1]["high_risk_count"] - points[-2]["high_risk_count"]
        delta_avg = round(points[-1]["avg_score"] - points[-2]["avg_score"], 1)

    return {
        "points": points,
        "weekly": weekly,
        "delta_vs_prior": {
            "high_risk_count": delta_high,
            "avg_score": delta_avg,
        },
        "message": (
            f"{len(points)} điểm risk"
            + (
                f" · high {points[-2]['high_risk_count']}→{points[-1]['high_risk_count']}"
                if len(points) >= 2 else ""
            )
        ),
    }


def attach_mitigations(
    risk_scores: list[dict[str, Any]],
    mitigations: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Gắn mitigation meta vào risk_scores theo ma_cn (và fallback module)."""
    mit = mitigations or {}
    out: list[dict[str, Any]] = []
    for r in risk_scores:
        item = dict(r)
        ma = str(r.get("ma_cn") or "").strip()
        mod = str(r.get("module") or "").strip()
        m = None
        if ma and ma in mit:
            m = mit[ma]
        elif mod and f"module:{mod}" in mit:
            m = mit[f"module:{mod}"]
        item["mitigation"] = m or None
        out.append(item)
    return out
