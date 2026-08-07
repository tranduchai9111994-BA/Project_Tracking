"""
Checklist lấy source test Rlog — cảnh báo theo từng ngày dev đến hạn.

Nghiệp vụ (quy trình MPHG):
  Mỗi Rlog có phase Dev đến hạn (End date rơi vào cửa sổ lookback) thì
  Config Local phải làm checklist lấy source đưa lên môi trường test.
  **Người lấy source là người config local** (PIC của phase Config Local).
  Nếu Config Local chưa có PIC hoặc chưa bắt đầu → việc lấy source chưa có
  ai làm → cảnh báo.

Định nghĩa (NGHIỆP VỤ MỚI — Aug 2026):
  - "Ngày dev đến hạn" = End date của phase Dev, **không phụ thuộc Dev
    Status**. Trước đây yêu cầu Dev.Closed → PM phải đợi dev đóng phase
    mới thấy row → checklist làm muộn. Nay chỉ cần có End date là kéo vào
    danh sách để Config Local chuẩn bị checklist sớm ngay khi dev push.
  - Loại trừ duy nhất: Dev.Status = Cancelled (task hủy — không cần
    source). Row thiếu End date cũng bỏ (không có mốc để theo dõi).
  - Phase "người lấy source" = phase auto-detect có tên chứa config + local.
    Nếu file không có → fallback phase ngay sau Dev theo thứ tự cột
    (``taker_phase_source = "next_after_dev"``, UI phải ghi rõ đang fallback).
  - Đã lấy source (không cảnh báo) = phase taker CÓ PIC **và** đã bắt đầu
    (có Start date, hoặc Status khác Open/trống).
  - Phase taker Cancelled → không cần lấy source, loại khỏi cả cảnh báo.
  - Scope Rlog theo ``rlog_weekly``: file có RlogID filled → chỉ tính function
    có RlogID; ngược lại tính mọi function.
  - Chỉ quét các End date trong cửa sổ ``lookback_days`` gần nhất (mặc định
    14) để danh sách còn dùng được cho vận hành.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from parser.excel_parser import ParsedData, FunctionRow, PhaseData

from analyzer.kanban import _phase_is_dev
from analyzer.rlog_weekly import (
    _any_row_has_rlog_id,
    _file_has_rlog_column,
    _normalize_status,
    _row_rlog_id,
)

DEFAULT_LOOKBACK_DAYS = 14

# Ngày coded quá xa (lỗi nhập liệu kiểu 1936 / 2036) → bỏ, tránh làm nhiễu.
_MAX_OUTLIER_DAYS = 10 * 365

# Status coi như phase taker đã được khởi động (dù chưa có Start date).
_STARTED_STATUSES = frozenset({"Assigned", "In-progress", "Resolved", "Closed", "Pending"})

_CONFIG_KEYWORDS = ("config", "cấu hình", "cau hinh", "cfg")

_REASON_LABELS = {
    "no_taker": "Chưa có người config local để lấy source",
    "not_started": "Đã có người config local nhưng chưa bắt đầu lấy source",
    "no_taker_phase": "File không xác định được phase config local",
}

_WEEKDAY_VI = ("Thứ 2", "Thứ 3", "Thứ 4", "Thứ 5", "Thứ 6", "Thứ 7", "Chủ nhật")


def _is_config_local_phase(phase_name: str) -> bool:
    """True nếu tên phase vừa chứa 'local' vừa chứa từ khoá config."""
    n = (phase_name or "").strip().lower()
    if "local" not in n:
        return False
    return any(k in n for k in _CONFIG_KEYWORDS)


def _phase_order(data: ParsedData) -> list[str]:
    """Thứ tự phase theo thứ tự cột trong file (fallback all_phases)."""
    names = [pg.name for pg in (data.phase_groups or []) if getattr(pg, "name", "")]
    if names:
        return names
    return [str(p) for p in (data.all_phases or [])]


def detect_taker_phase(data: ParsedData) -> tuple[Optional[str], str]:
    """
    Xác định phase của "người lấy source".

    Returns:
        (phase_name, source) với source ∈ {"config_local", "next_after_dev", "none"}.
    """
    order = _phase_order(data)
    if not order:
        # Pickle cũ / sync thiếu phase_groups → quét trực tiếp trên rows.
        seen: list[str] = []
        for r in data.rows[:50]:
            for pn in (r.phases or {}):
                if pn not in seen:
                    seen.append(pn)
        order = seen

    for name in order:
        if _is_config_local_phase(name):
            return name, "config_local"

    for idx, name in enumerate(order):
        if _phase_is_dev(name):
            for nxt in order[idx + 1:]:
                return nxt, "next_after_dev"
            break

    return None, "none"


def _find_dev_phase(row: FunctionRow) -> tuple[Optional[str], Optional[PhaseData]]:
    for pn, pd in (row.phases or {}).items():
        if _phase_is_dev(pn):
            return pn, pd
    return None, None


def _is_outlier(d: date, today: date) -> bool:
    return abs((d - today).days) > _MAX_OUTLIER_DAYS


def _taker_state(pd: Optional[PhaseData]) -> tuple[str, str]:
    """
    Đánh giá phase taker → (state, reason).

    state ∈ {"done", "pending", "not_required"}; reason rỗng khi không pending.
    """
    if pd is None:
        return "pending", "no_taker_phase"

    status = _normalize_status(pd.status)
    if status == "Cancelled":
        return "not_required", ""

    pics = [p for p in (pd.pics or []) if str(p).strip()]
    if not pics:
        return "pending", "no_taker"

    started = pd.start_date is not None or status in _STARTED_STATUSES
    if not started:
        return "pending", "not_started"
    return "done", ""


def _severity(reason: str, days_since_coded: int) -> str:
    if reason in ("no_taker", "no_taker_phase"):
        return "high"
    if days_since_coded >= 3:
        return "high"
    return "medium"


def _fmt_vi(d: Optional[date]) -> str:
    return d.strftime("%d/%m/%Y") if d else ""


def compute_source_checklist(
    data: ParsedData,
    today: Optional[date] = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> dict[str, Any]:
    """
    Quét ParsedData → cảnh báo checklist lấy source test theo từng ngày coded.

    Args:
        data: dữ liệu Function List đã parse (đã áp global filter nếu có).
        today: ngày mốc (mặc định hôm nay) — inject để test.
        lookback_days: số ngày lùi lại tính từ today (1–365).

    Returns:
        {
          "days": [{
            "date", "date_label", "weekday_label", "coded_count",
            "pending_count", "done_count", "max_days_since_coded", "items": [...]
          }, ...],                       # sort giảm dần theo ngày
          "summary": {total_coded, total_pending, total_done, total_not_required,
                      days_with_coded, days_with_pending, by_reason, by_severity,
                      by_taker, max_days_pending, out_of_window},
          "taker_phase", "taker_phase_source", "dev_phases_detected",
          "rlog_scope", "rlog_column_detected", "lookback_days",
          "window_start", "today", "checklist_note", "definition"
        }
    """
    today = today or date.today()
    try:
        lookback_days = int(lookback_days)
    except (TypeError, ValueError):
        lookback_days = DEFAULT_LOOKBACK_DAYS
    lookback_days = max(1, min(365, lookback_days))
    window_start = today - timedelta(days=lookback_days)

    taker_phase, taker_phase_source = detect_taker_phase(data)
    rlog_col = _file_has_rlog_column(data)
    scope = "with_rlog_id" if _any_row_has_rlog_id(data) else "all_functions"

    by_date: dict[date, list[dict[str, Any]]] = {}
    dev_phases_detected: list[str] = []
    out_of_window = 0

    for row in data.rows:
        rlog_id = _row_rlog_id(row)
        if scope == "with_rlog_id" and not rlog_id:
            continue

        dev_phase, dev_pd = _find_dev_phase(row)
        if not dev_phase or dev_pd is None:
            continue
        if dev_phase not in dev_phases_detected:
            dev_phases_detected.append(dev_phase)

        dev_status = _normalize_status(dev_pd.status)
        # Không chờ Dev.Closed — Config Local cần thấy row NGAY khi có End
        # date để chuẩn bị checklist trước lúc dev đóng phase. Chỉ loại
        # Cancelled (task hủy → không cần source, tránh nhiễu).
        if dev_status == "Cancelled":
            continue
        coded_date = dev_pd.end_date
        if not isinstance(coded_date, date) or _is_outlier(coded_date, today):
            continue
        if not (window_start <= coded_date <= today):
            out_of_window += 1
            continue

        taker_pd = (row.phases or {}).get(taker_phase) if taker_phase else None
        state, reason = _taker_state(taker_pd)
        days_since = (today - coded_date).days
        taker_pics = [p for p in ((taker_pd.pics if taker_pd else []) or []) if str(p).strip()]
        taker_status = _normalize_status(taker_pd.status) if taker_pd else ""

        item: dict[str, Any] = {
            "ma_cn": str(row.meta.get("ma_cn") or "").strip(),
            "ten_cn": str(row.meta.get("ten_cn") or "").strip(),
            "module": str(row.meta.get("module") or "").strip(),
            "quy_trinh": str(
                row.meta.get("quy_trinh") or row.meta.get("process") or ""
            ).strip(),
            "rlog_id": rlog_id or "",
            "dev_phase": dev_phase,
            "dev_pic": ", ".join(str(p) for p in (dev_pd.pics or [])),
            "dev_status": dev_status,
            # BC: field name giữ `coded_date` (FE/exporter dùng), nhưng
            # nghĩa mới là "Dev End date" — không đảm bảo Dev đã Closed.
            "coded_date": coded_date.isoformat(),
            "coded_date_label": _fmt_vi(coded_date),
            "days_since_coded": days_since,
            "taker_phase": taker_phase or "",
            "taker_pic": ", ".join(taker_pics),
            "taker_status": taker_status,
            "taker_start": taker_pd.start_date.isoformat() if (taker_pd and taker_pd.start_date) else "",
            "state": state,
            "reason": reason,
            "reason_label": _REASON_LABELS.get(reason, ""),
            "severity": _severity(reason, days_since) if state == "pending" else "",
            "checklist_action": (
                f"Làm checklist lấy source test cho Rlog {rlog_id}"
                if rlog_id else "Làm checklist lấy source test"
            ),
        }
        by_date.setdefault(coded_date, []).append(item)

    days: list[dict[str, Any]] = []
    total_pending = total_done = total_not_required = 0
    by_reason: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    by_taker: dict[str, int] = {}
    max_days_pending = 0

    for d in sorted(by_date.keys(), reverse=True):
        items = sorted(
            by_date[d],
            key=lambda x: (x["state"] != "pending", x["ma_cn"]),
        )
        pending = [i for i in items if i["state"] == "pending"]
        done = [i for i in items if i["state"] == "done"]
        not_required = [i for i in items if i["state"] == "not_required"]

        total_pending += len(pending)
        total_done += len(done)
        total_not_required += len(not_required)

        for i in pending:
            by_reason[i["reason"]] = by_reason.get(i["reason"], 0) + 1
            by_severity[i["severity"]] = by_severity.get(i["severity"], 0) + 1
            for name in [p.strip() for p in i["taker_pic"].split(",") if p.strip()]:
                by_taker[name] = by_taker.get(name, 0) + 1
            max_days_pending = max(max_days_pending, i["days_since_coded"])

        days.append({
            "date": d.isoformat(),
            "date_label": _fmt_vi(d),
            "weekday_label": _WEEKDAY_VI[d.weekday()],
            "coded_count": len(items),
            "pending_count": len(pending),
            "done_count": len(done),
            "not_required_count": len(not_required),
            "days_since_coded": (today - d).days,
            "items": items,
        })

    total_coded = sum(dd["coded_count"] for dd in days)

    return {
        "days": days,
        "summary": {
            "total_coded": total_coded,
            "total_pending": total_pending,
            "total_done": total_done,
            "total_not_required": total_not_required,
            "days_with_coded": len(days),
            "days_with_pending": sum(1 for dd in days if dd["pending_count"] > 0),
            "by_reason": by_reason,
            "by_severity": by_severity,
            "by_taker": dict(sorted(by_taker.items(), key=lambda kv: -kv[1])),
            "max_days_pending": max_days_pending,
            "out_of_window": out_of_window,
        },
        "taker_phase": taker_phase or "",
        "taker_phase_source": taker_phase_source,
        "dev_phases_detected": dev_phases_detected,
        "rlog_scope": scope,
        "rlog_column_detected": rlog_col,
        "lookback_days": lookback_days,
        "window_start": window_start.isoformat(),
        "today": today.isoformat(),
        "checklist_note": (
            "Mỗi Rlog có Dev đến hạn (End date trong lookback) → người config "
            "local phải chuẩn bị checklist lấy source test. Không đợi "
            "Dev.Closed để làm sớm ngay khi dev push."
        ),
        "definition": (
            "Ngày dev đến hạn = End date của phase Dev (không phụ thuộc Status; "
            "chỉ loại Cancelled). "
            f"Người lấy source = PIC phase {taker_phase!r} "
            + (
                "(auto-detect Config Local)."
                if taker_phase_source == "config_local"
                else "(fallback: phase ngay sau Dev vì file không có phase Config Local)."
                if taker_phase_source == "next_after_dev"
                else "(không xác định được — file thiếu phase config local)."
            )
            + " Đã lấy source = phase đó có PIC và đã bắt đầu (có Start hoặc "
            "Status khác Open/trống)."
        ),
    }
