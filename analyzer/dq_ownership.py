"""
DQ ownership + SLA — gán PIC / target date cho issue Data Quality.

Key issue: ``ma_cn|phase|code`` (ổn định giữa các lần upload nếu cùng mã).
Resolution rate WoW: so sánh số issue mở giữa 2 thời điểm + số đã đánh dấu resolved.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Optional


def issue_key(issue: dict[str, Any]) -> str:
    ma = str(issue.get("ma_cn") or "").strip()
    phase = str(issue.get("phase") or "").strip()
    code = str(issue.get("code") or "").strip()
    return f"{ma}|{phase}|{code}"


def attach_ownership(
    issues: list[dict[str, Any]],
    ownership: dict[str, dict[str, Any]],
    *,
    today: Optional[date] = None,
) -> list[dict[str, Any]]:
    """Gắn owner_pic / target_date / sla_status vào từng issue."""
    today = today or date.today()
    own = ownership or {}
    out: list[dict[str, Any]] = []
    for it in issues:
        item = dict(it)
        key = issue_key(it)
        meta = own.get(key) or {}
        item["ownership_key"] = key
        item["owner_pic"] = meta.get("owner_pic") or ""
        item["target_date"] = meta.get("target_date") or ""
        item["assigned_at"] = meta.get("assigned_at") or ""
        item["assigned_by"] = meta.get("assigned_by") or ""
        item["resolved_at"] = meta.get("resolved_at") or ""
        item["resolved"] = bool(meta.get("resolved_at"))
        item["sla_status"] = _sla_status(meta, today=today, still_open=True)
        out.append(item)
    return out


def _parse_date(s: Any) -> Optional[date]:
    if not s:
        return None
    if isinstance(s, date) and not isinstance(s, datetime):
        return s
    try:
        return datetime.fromisoformat(str(s)[:10]).date()
    except ValueError:
        return None


def _sla_status(
    meta: dict[str, Any],
    *,
    today: date,
    still_open: bool,
) -> str:
    if meta.get("resolved_at"):
        return "resolved"
    td = _parse_date(meta.get("target_date"))
    if td is None:
        return "unassigned" if not meta.get("owner_pic") else "no_target"
    if still_open and td < today:
        return "overdue"
    if still_open and td <= today + timedelta(days=3):
        return "due_soon"
    return "on_track"


def compute_dq_sla_stats(
    issues: list[dict[str, Any]],
    ownership: dict[str, dict[str, Any]],
    *,
    prior_open_count: Optional[int] = None,
    today: Optional[date] = None,
) -> dict[str, Any]:
    """
    Thống kê ownership + resolution rate.

    prior_open_count: số issue mở tuần trước (từ snapshot/metrics).
    Resolution rate ≈ (prior_open - current_open + newly_resolved_marked) / prior_open
    đơn giản hơn: resolved_this_week / (open_now + resolved_this_week).
    """
    today = today or date.today()
    week_ago = today - timedelta(days=7)
    attached = attach_ownership(issues, ownership, today=today)

    open_issues = [i for i in attached if not i.get("resolved")]
    assigned = [i for i in open_issues if i.get("owner_pic")]
    overdue_sla = [i for i in open_issues if i.get("sla_status") == "overdue"]

    resolved_week = 0
    for key, meta in (ownership or {}).items():
        ra = _parse_date(meta.get("resolved_at"))
        if ra and ra >= week_ago:
            resolved_week += 1

    open_now = len(open_issues)
    if prior_open_count is not None and prior_open_count > 0:
        # Số issue biến mất khỏi list ≈ resolved tự nhiên; cộng marked
        natural = max(0, prior_open_count - open_now)
        rate = round((natural + resolved_week) / prior_open_count * 100, 1)
    elif open_now + resolved_week > 0:
        rate = round(resolved_week / (open_now + resolved_week) * 100, 1)
    else:
        rate = None

    return {
        "total_issues": len(attached),
        "open_issues": open_now,
        "assigned_count": len(assigned),
        "unassigned_count": open_now - len(assigned),
        "sla_overdue_count": len(overdue_sla),
        "resolved_this_week": resolved_week,
        "prior_open_count": prior_open_count,
        "resolution_rate_wow_pct": rate,
        "by_sla": {
            "overdue": sum(1 for i in open_issues if i["sla_status"] == "overdue"),
            "due_soon": sum(1 for i in open_issues if i["sla_status"] == "due_soon"),
            "on_track": sum(1 for i in open_issues if i["sla_status"] == "on_track"),
            "no_target": sum(1 for i in open_issues if i["sla_status"] == "no_target"),
            "unassigned": sum(1 for i in open_issues if i["sla_status"] == "unassigned"),
        },
    }
