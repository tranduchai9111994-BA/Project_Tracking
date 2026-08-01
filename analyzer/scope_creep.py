"""
Change Request / Scope Creep tracking (Phase C).

Phân biệt function thuộc **scope gốc** vs **CR (phát sinh)**.

Detection (ưu tiên):
  1. **Cột Excel auto-detect** (primary) — header chứa CR / Change Request /
     Phát sinh / Scope Creep / exact "CR" (không partial vào "Description").
  2. **Fallback** khi không có cột: tag function `CR` (bulk tag) **hoặc**
     danh sách Mã CN trong project settings `cr_function_codes`.

Effort MH: Σ Estimate MH mọi phase không Cancelled; ô trống → DEFAULT_MH
(giống EVM / forecast_manpower).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any, Optional

from parser.excel_parser import ParsedData, FunctionRow, PhaseData

from analyzer.forecast_manpower import DEFAULT_MH

# Tag chuẩn để đánh dấu CR thủ công (fallback)
CR_TAG = "CR"

_FALSE_TOKENS = {
    "", "0", "n", "no", "false", "không", "khong", "ko", "-",
    "n/a", "na", "null", "none", "×", "✗",
}
_TRUE_TOKENS = {
    "1", "y", "yes", "true", "x", "✓", "✔", "v",
    "cr", "phát sinh", "phat sinh", "change request", "scope creep",
}


def _parse_date(v: Any) -> Optional[date]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)):
        return None  # tránh Excel serial lộn
    s = str(v).strip()
    if not s:
        return None
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


def is_cr_cell_value(val: Any) -> bool:
    """Ô cột CR có nghĩa là phát sinh?"""
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val != 0
    s = str(val).strip().lower()
    if s in _FALSE_TOKENS:
        return False
    if s in _TRUE_TOKENS:
        return True
    # Giá trị khác rỗng (VD "CR-001", "Yes - KH") → coi là CR
    return bool(s)


def _phase_meaningful(pd: PhaseData) -> bool:
    if pd.status or pd.start_date or pd.end_date:
        return True
    if pd.estimate_mh is not None and pd.estimate_mh > 0:
        return True
    return False


def _row_effort_mh(row: FunctionRow, default_mh: float) -> tuple[float, int, int]:
    """
    Tổng MH ngân sách 1 function (bỏ Cancelled / phase trống).
    Trả (mh, phases_counted, phases_default_mh).
    """
    total = 0.0
    counted = 0
    defaults = 0
    for pd in row.phases.values():
        if not _phase_meaningful(pd):
            continue
        st = (pd.status or "").strip()
        if st == "Cancelled":
            continue
        counted += 1
        if pd.estimate_mh is not None and pd.estimate_mh > 0:
            total += float(pd.estimate_mh)
        else:
            total += float(default_mh)
            defaults += 1
    return total, counted, defaults


def _ma_cn(row: FunctionRow) -> str:
    return str(row.meta.get("ma_cn") or "").strip()


def _has_cr_column(data: ParsedData) -> bool:
    col = (data.meta_columns or {}).get("is_cr")
    return col is not None


def _cr_header_name(data: ParsedData) -> Optional[str]:
    """Tên header cột CR nếu có (để UI/report)."""
    col = (data.meta_columns or {}).get("is_cr")
    if col is None:
        return None
    for h, idx in (data.headers or {}).items():
        if idx == col:
            return h
    return "is_cr"


def _cr_date_header_name(data: ParsedData) -> Optional[str]:
    col = (data.meta_columns or {}).get("cr_date")
    if col is None:
        return None
    for h, idx in (data.headers or {}).items():
        if idx == col:
            return h
    return "cr_date"


def compute_scope_creep(
    data: ParsedData,
    *,
    function_tags: Optional[dict[str, list[str]]] = None,
    cr_function_codes: Optional[list[str]] = None,
    default_mh: float = DEFAULT_MH,
    detail_limit: Optional[int] = 200,
) -> dict[str, Any]:
    """
    Tính scope creep: % CR, effort CR vs gốc, breakdown theo module.

    Args:
        data: ParsedData hiện tại (đã filter nếu caller filter).
        function_tags: map ma_cn → [tags] (fallback khi không có cột).
        cr_function_codes: list Mã CN đánh dấu CR trong settings (fallback).
        default_mh: MH mặc định khi Estimate trống.
        detail_limit: cắt danh sách CR (None/0 = tất cả — dùng khi xuất Excel).
    """
    tags_map = function_tags or {}
    codes_set = {
        str(c).strip().lower()
        for c in (cr_function_codes or [])
        if str(c).strip()
    }
    use_column = _has_cr_column(data)
    cr_header = _cr_header_name(data) if use_column else None
    cr_date_header = _cr_date_header_name(data)

    total = 0
    cr_count = 0
    orig_count = 0
    mh_cr = 0.0
    mh_orig = 0.0
    phases_default = 0
    cr_with_date = 0
    by_mod: dict[str, dict[str, float]] = defaultdict(
        lambda: {
            "total": 0, "cr": 0, "original": 0,
            "mh_cr": 0.0, "mh_original": 0.0,
        }
    )
    cr_items: list[dict[str, Any]] = []

    for row in data.rows:
        total += 1
        ma = _ma_cn(row)
        mod = (row.meta.get("module") or "").strip() or "(trống)"
        mh, _n_ph, n_def = _row_effort_mh(row, default_mh)
        phases_default += n_def

        if use_column:
            is_cr = is_cr_cell_value(row.meta.get("is_cr"))
            source = "column" if is_cr else "column"
        else:
            tag_hit = CR_TAG in (tags_map.get(ma) or [])
            code_hit = bool(ma) and ma.lower() in codes_set
            is_cr = tag_hit or code_hit
            if tag_hit and code_hit:
                source = "tag+settings"
            elif tag_hit:
                source = "tag"
            elif code_hit:
                source = "settings"
            else:
                source = "none"

        raised = _parse_date(row.meta.get("cr_date")) if cr_date_header else None
        if is_cr and raised is not None:
            cr_with_date += 1

        acc = by_mod[mod]
        acc["total"] += 1
        if is_cr:
            cr_count += 1
            mh_cr += mh
            acc["cr"] += 1
            acc["mh_cr"] += mh
            cr_items.append({
                "ma_cn": ma,
                "ten_cn": row.meta.get("ten_cn") or "",
                "module": mod,
                "quy_trinh": row.meta.get("quy_trinh") or row.meta.get("process") or "",
                "mh": round(mh, 2),
                "source": source if use_column else source,
                "cr_raised_date": raised.isoformat() if raised else None,
                "raw_cr": row.meta.get("is_cr") if use_column else None,
                "column_header": cr_header or "",
            })
        else:
            orig_count += 1
            mh_orig += mh
            acc["original"] += 1
            acc["mh_original"] += mh

    creep_rate = round(cr_count / total * 100, 1) if total > 0 else None
    mh_total = mh_cr + mh_orig
    mh_cr_pct = round(mh_cr / mh_total * 100, 1) if mh_total > 0 else None

    modules: list[dict[str, Any]] = []
    for mod, a in by_mod.items():
        t = int(a["total"])
        c = int(a["cr"])
        modules.append({
            "module": mod,
            "total": t,
            "cr": c,
            "original": int(a["original"]),
            "creep_rate_pct": round(c / t * 100, 1) if t > 0 else None,
            "mh_cr": round(a["mh_cr"], 2),
            "mh_original": round(a["mh_original"], 2),
        })
    modules.sort(key=lambda r: (-(r["creep_rate_pct"] or 0), -r["cr"], r["module"]))

    # Sắp CR items: MH lớn trước (đàm phán effort)
    cr_items.sort(key=lambda x: (-x["mh"], x["ma_cn"] or ""))

    detection_mode = "column" if use_column else (
        "tag_or_settings" if (codes_set or any(CR_TAG in (t or []) for t in tags_map.values()))
        else "none"
    )

    messages: list[str] = []
    if use_column:
        messages.append(
            f"Phát hiện cột CR: «{cr_header}» — đây là nguồn chính."
        )
    else:
        messages.append(
            "Không có cột CR / Phát sinh trên Excel. "
            "Đang dùng fallback: tag «CR» hoặc danh sách Mã CN trong Cài đặt."
        )
        if not codes_set and not any(CR_TAG in (t or []) for t in tags_map.values()):
            messages.append(
                "Chưa có tag CR / danh sách mã — mọi function đang tính là scope gốc. "
                "Gắn tag CR trong drill-down hoặc nhập Mã CN ở Cài đặt."
            )
    if cr_date_header:
        messages.append(f"Có cột ngày phát sinh: «{cr_date_header}».")
    if phases_default > 0:
        messages.append(
            f"{phases_default} phase dùng MH mặc định {default_mh:g} "
            "(không có Estimate MH)."
        )
    if creep_rate is not None and creep_rate >= 15:
        messages.append(
            f"Scope creep {creep_rate}% — nên đàm phán effort / timeline với khách."
        )

    return {
        "definition": (
            "CR = function phát sinh ngoài scope gốc. "
            "Scope creep rate = số CR ÷ tổng function. "
            "Effort = Σ Estimate MH (trống → mặc định)."
        ),
        "detection": {
            "mode": detection_mode,
            "primary": "column" if use_column else "tag_or_settings",
            "column_header": cr_header,
            "cr_date_header": cr_date_header,
            "cr_tag": CR_TAG,
            "cr_codes_count": len(codes_set),
            "rules": [
                "Primary: cột Excel auto-detect (CR / Change Request / Phát sinh / Scope Creep).",
                "Fallback (không có cột): tag function «CR» hoặc settings cr_function_codes.",
                f"Estimate MH trống → mặc định {default_mh:g} MH (giống EVM).",
            ],
        },
        "summary": {
            "total_functions": total,
            "cr_count": cr_count,
            "original_count": orig_count,
            "creep_rate_pct": creep_rate,
            "mh_cr": round(mh_cr, 2),
            "mh_original": round(mh_orig, 2),
            "mh_total": round(mh_total, 2),
            "mh_cr_pct": mh_cr_pct,
            "cr_with_raised_date": cr_with_date,
            "phases_default_mh": phases_default,
            "default_mh": default_mh,
        },
        "modules": modules,
        "cr_functions": (
            cr_items if not detail_limit or detail_limit <= 0
            else cr_items[:detail_limit]
        ),
        "cr_functions_truncated": (
            0 if not detail_limit or detail_limit <= 0
            else max(0, len(cr_items) - detail_limit)
        ),
        "messages": messages,
        "assumptions": [
            f"Estimate MH trống → {default_mh:g} MH / phase (giống Forecast Manpower / EVM).",
            "Phase Cancelled và phase hoàn toàn trống không cộng effort.",
            "Khi có cột CR: giá trị Yes/1/X/CR-xxx = phát sinh; trống/No/0 = gốc.",
            "Khi không có cột: tag «CR» hoặc mã trong Cài đặt.",
        ],
        "unit": "MH",
    }
