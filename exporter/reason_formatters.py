"""
Helper format câu «Lý do» tiếng Việt cho các export vi phạm / issue.

Dùng chung bởi overdue / unassigned / stalled / aging / overload / capacity /
duration / risk / scope creep / FIT-GAP / UAT — tránh mỗi exporter tự viết rule.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional


def fmt_date(val: Any) -> str:
    """Chuẩn hoá ngày → dd/MM/yyyy (hoặc chuỗi gốc nếu không parse được)."""
    if val is None or val == "":
        return ""
    if isinstance(val, datetime):
        return val.date().strftime("%d/%m/%Y")
    if isinstance(val, date):
        return val.strftime("%d/%m/%Y")
    s = str(val).strip()
    if not s:
        return ""
    # ISO yyyy-mm-dd
    try:
        if len(s) >= 10 and s[4] == "-" and s[7] == "-":
            return date.fromisoformat(s[:10]).strftime("%d/%m/%Y")
    except ValueError:
        pass
    # dd/MM/yyyy đã đúng
    if len(s) >= 8 and "/" in s:
        return s[:10] if len(s) >= 10 else s
    return s


def process_code(item: dict[str, Any] | None) -> str:
    """Lấy mã quy trình từ meta/item (auto-detect key quy_trinh / process)."""
    if not item:
        return ""
    return str(item.get("quy_trinh") or item.get("process") or "").strip()


def reason_overdue(item: dict[str, Any], *, today: date | None = None) -> str:
    """End < hôm nay; Status ∉ Closed/Cancelled."""
    today = today or date.today()
    end = fmt_date(item.get("end_date") or item.get("deadline"))
    st = item.get("status") or ""
    days = item.get("days_overdue")
    parts = []
    if end:
        parts.append(f"End {end} < hôm nay {fmt_date(today)}")
    else:
        parts.append(f"End đã qua hôm nay {fmt_date(today)}")
    if st:
        parts.append(f"Status={st} ∉ Closed/Cancelled")
    else:
        parts.append("Status ∉ Closed/Cancelled")
    if days is not None and days != "":
        try:
            parts.append(f"trễ {int(days)}d")
        except (TypeError, ValueError):
            pass
    return "; ".join(parts)


def reason_unassigned(item: dict[str, Any]) -> str:
    """
    Format: Thiếu PIC · phase trước «{P}» Closed · Start {d} đã đến · Status={S}
    """
    parts = ["Thiếu PIC"]
    pred = item.get("predecessor_phase") or item.get("prev_phase") or ""
    if pred:
        parts.append(f"phase trước «{pred}» Closed")
    elif item.get("is_first_phase"):
        parts.append("phase đầu (không cần pred)")
    start = fmt_date(item.get("start_date"))
    if start:
        parts.append(f"Start {start} đã đến")
    elif item.get("start_gate") == "end":
        end = fmt_date(item.get("end_date"))
        if end:
            parts.append(f"không Start · End {end} đã đến")
        else:
            parts.append("không Start · End đã đến")
    elif item.get("start_gate") == "active_status":
        parts.append("không Start · status đang làm")
    else:
        parts.append("Start đã đến")
    st = item.get("status") or ""
    if st:
        parts.append(f"Status={st}")
    return " · ".join(parts)


def reason_stalled(item: dict[str, Any]) -> str:
    """
    «{done}» Closed {date}; «{wait}» chưa start; End chờ {end} đã qua ({n}d)
    """
    done = item.get("completed_phase") or ""
    wait = item.get("waiting_phase") or ""
    done_d = fmt_date(item.get("completed_date"))
    wait_end = fmt_date(item.get("waiting_end_date") or item.get("waiting_end"))
    wait_days = item.get("wait_days")
    parts = []
    if done:
        parts.append(f"«{done}» Closed" + (f" {done_d}" if done_d else ""))
    if wait:
        parts.append(f"«{wait}» chưa start")
    if wait_end:
        tail = f"End chờ {wait_end} đã qua"
        try:
            if wait_days is not None and wait_days != "":
                tail += f" ({int(wait_days)}d)"
        except (TypeError, ValueError):
            pass
        parts.append(tail)
    elif wait_days is not None and wait_days != "":
        try:
            parts.append(f"chờ {int(wait_days)}d")
        except (TypeError, ValueError):
            pass
    return "; ".join(parts) if parts else "Đình trệ giữa 2 phase"


def reason_aging_wip(item: dict[str, Any], threshold: int | None = None) -> str:
    thr = threshold if threshold is not None else item.get("threshold_days")
    start = fmt_date(item.get("start_date") or item.get("opened_date"))
    aging = item.get("aging_days")
    parts = ["In-progress"]
    if start:
        parts.append(f"từ {start}")
    if aging is not None and thr is not None:
        try:
            parts.append(f"aging {int(aging)}d > ngưỡng {int(thr)}")
        except (TypeError, ValueError):
            pass
    elif aging is not None:
        try:
            parts.append(f"aging {int(aging)}d")
        except (TypeError, ValueError):
            pass
    return ", ".join(parts)


def reason_duration(item: dict[str, Any], threshold: int | None = None) -> str:
    thr = threshold if threshold is not None else item.get("threshold_days")
    days = item.get("duration_days")
    dtype = item.get("duration_type") or ""
    label = "elapsed" if dtype == "elapsed" else ("planned" if dtype == "planned" else dtype)
    if label == "elapsed":
        label_vn = "elapsed (đang chạy)"
    elif label == "planned":
        label_vn = "planned (đã lên KH)"
    else:
        label_vn = label or "duration"
    try:
        d = int(days) if days is not None else None
        t = int(thr) if thr is not None else None
    except (TypeError, ValueError):
        d, t = days, thr
    if d is not None and t is not None:
        return f"Duration {d}d > ngưỡng {t} ({label_vn})"
    if d is not None:
        return f"Duration {d}d ({label_vn})"
    return f"Duration bất thường ({label_vn})"


def reason_pic_overload(
    pic: str,
    day: Any,
    concurrent: int,
    threshold: int,
) -> str:
    """PIC X ngày {d}: {n} task > ngưỡng {max}."""
    d = fmt_date(day) or str(day or "")
    return f"PIC {pic} ngày {d}: {concurrent} task > ngưỡng {threshold}"


def reason_capacity(item: dict[str, Any]) -> str:
    """Remaining {r} MH / capacity {c} → cần {w} tuần."""
    r = item.get("remaining_mh")
    c = item.get("capacity_mh_per_week")
    w = item.get("weeks_needed")
    parts = []
    if r is not None:
        parts.append(f"Remaining {r} MH")
    if c is not None:
        parts.append(f"capacity {c} MH/tuần")
    base = " / ".join(parts) if parts else "Capacity"
    if w is not None and w != "":
        return f"{base} → cần {w} tuần"
    if item.get("overload"):
        return f"{base} → OVERLOAD"
    return base


def reason_fitgap_aging(item: dict[str, Any], threshold: int | None = None) -> str:
    thr = threshold if threshold is not None else item.get("threshold_days")
    aging = item.get("aging_days")
    opened = fmt_date(item.get("opened_date"))
    parts = ["GAP đang mở"]
    if opened:
        parts.append(f"từ {opened}")
    if aging is not None and thr is not None:
        try:
            parts.append(f"aging {int(aging)}d > ngưỡng {int(thr)}")
        except (TypeError, ValueError):
            pass
    return ", ".join(parts)


def reason_scope_creep(
    item: dict[str, Any],
    *,
    column_header: str = "",
) -> str:
    """Lý do phát hiện CR tiếng Việt + giá trị ô gốc nếu có."""
    source = (item.get("source") or "").strip().lower()
    raw = item.get("raw_cr")
    header = column_header or item.get("column_header") or "CR"
    if source in ("column",) or (raw is not None and source.startswith("column")):
        raw_s = "" if raw is None else str(raw).strip()
        if raw_s:
            return f"Cột «{header}» = «{raw_s}»"
        return f"Cột «{header}» đánh dấu CR"
    if source == "tag":
        return "Tag function «CR»"
    if source == "settings":
        return "Mã CN nằm trong danh sách Cài đặt (cr_function_codes)"
    if source == "tag+settings":
        return "Tag «CR» + Mã trong Cài đặt"
    if raw is not None and str(raw).strip():
        return f"Cột «{header}» = «{str(raw).strip()}»"
    return source or "Phát hiện CR"


def reason_uat_warning(item: dict[str, Any]) -> str:
    """Cảnh báo reopen / cycle ≥ 2 / tag."""
    parts = []
    r = item.get("reopen_count")
    c = item.get("uat_cycle")
    try:
        if r is not None and int(r) > 0:
            parts.append(f"Reopen {int(r)}")
    except (TypeError, ValueError):
        pass
    try:
        if c is not None and int(c) >= 2:
            parts.append(f"cycle {int(c)} ≥ 2")
    except (TypeError, ValueError):
        pass
    if item.get("tagged_uat_issue"):
        parts.append("tag «UAT issue»")
    d = item.get("defect_count")
    try:
        if d is not None and int(d) > 0:
            parts.append(f"defect {int(d)}")
    except (TypeError, ValueError):
        pass
    return " · ".join(parts) if parts else ""


def format_risk_factors_detailed(item: dict[str, Any]) -> str:
    """
    Ghép yếu tố rủi ro chi tiết từ risk_factors_detail (ưu tiên) hoặc
    risk_factors + risk_breakdown.
    """
    detail = item.get("risk_factors_detail")
    if isinstance(detail, list) and detail:
        return "; ".join(str(x) for x in detail if x)
    factors = item.get("risk_factors") or []
    breakdown = item.get("risk_breakdown") or {}
    if not factors and not breakdown:
        return ""
    # Nếu factors đã chi tiết (có dấu + hoặc «») → dùng luôn
    if factors and any(("(+") in str(f) or "«" in str(f) for f in factors):
        return "; ".join(str(f) for f in factors)
    # Fallback: gắn điểm từ breakdown theo thứ tự factor gần đúng
    parts: list[str] = []
    used_keys: set[str] = set()
    key_hints = [
        ("must", "priority"), ("should", "priority"),
        ("complexity", "complexity"),
        ("overdue", "overdue"), ("trễ", "overdue_days"),
        ("pic", "unassigned"), ("không có pic", "unassigned"),
        ("duration", "long_duration"),
        ("đình trệ", "stalled"), ("stalled", "stalled"),
        ("risk note", "risk_note"),
        ("overload", "pic_overload"),
        ("cascade", "cascade_delay"),
    ]
    for f in factors:
        fl = str(f).lower()
        pts = None
        matched = None
        for hint, key in key_hints:
            if hint in fl and key in breakdown and key not in used_keys:
                pts = breakdown[key]
                matched = key
                break
        if matched:
            used_keys.add(matched)
        if pts is not None:
            parts.append(f"{f} (+{pts})")
        else:
            parts.append(str(f))
    # Điểm còn lại trong breakdown chưa gắn
    for k, v in breakdown.items():
        if k not in used_keys and v:
            parts.append(f"{k} (+{v})")
    return "; ".join(parts)


def join_notes(notes: list[str] | None, *, sep: str = " | ") -> str:
    """Gộp notes FL re-import / issue hits."""
    if not notes:
        return ""
    seen: list[str] = []
    for n in notes:
        s = str(n or "").strip()
        if s and s not in seen:
            seen.append(s)
    return sep.join(seen)
