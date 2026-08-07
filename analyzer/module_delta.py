"""
Delta cho bảng Tổng quan theo Module — tăng/giảm so với một mốc so sánh.

Nhận trực tiếp 2 list row do `DashboardEngine._overview_by()` sinh ra (bản hiện
tại và bản mốc) rồi join theo (module, process). Cố tình KHÔNG tự tính lại các
chỉ số từ ParsedData để không có nguy cơ lệch công thức với bảng gốc.

Quy ước bắt buộc (đọc trước khi sửa):
  - Tiến độ đã là phần trăm nên chiều "số lượng" của nó là **điểm phần trăm**
    (72% → 78% là +6pp), còn chiều "%" là phần trăm tương đối. Hai con số này
    khác nhau và không được dùng lẫn.
  - `*_delta_pct` trả None khi giá trị mốc bằng 0 (không chia 0) → UI hiện "—".
  - Nhóm chỉ có ở bản hiện tại → `is_new=True`, mọi delta là None (UI hiện
    "mới", không hiện +100%).
  - Nhóm chỉ có ở bản mốc → vào `removed[]`, không chèn row giả vào bảng để
    không phá drill-down.
"""
from __future__ import annotations

from typing import Any, Optional

# Thứ tự cột delta trên UI + đơn vị của chiều "số lượng".
METRICS: tuple[dict[str, str], ...] = (
    {"key": "total", "source": "total", "label": "SL", "unit": "count"},
    {"key": "progress", "source": "progress_pct", "label": "Tiến độ", "unit": "pp"},
    {"key": "overdue", "source": "overdue_count", "label": "Trễ", "unit": "count"},
    {"key": "remaining", "source": "remaining", "label": "Còn lại", "unit": "count"},
)

# Chiều tốt/xấu để FE tô màu. up_good: tăng là tốt. up_bad: tăng là xấu.
# down_good: giảm là tốt. neutral: chỉ là dấu hiệu (SL tăng = scope creep).
POLARITY: dict[str, str] = {
    "total": "neutral",
    "progress": "up_good",
    "overdue": "up_bad",
    "remaining": "down_good",
}


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _key(row: dict) -> str:
    """Khóa join: 'module||process'. Row cấp module có process rỗng."""
    return f"{str(row.get('module') or '')}||{str(row.get('process') or '')}"


def _rel_pct(cur: float, base: float) -> Optional[float]:
    """Phần trăm tương đối; None khi mốc bằng 0 để tránh chia 0."""
    if base == 0:
        return None
    return round((cur - base) / abs(base) * 100, 1)


def _delta_for(cur_row: dict, base_row: Optional[dict]) -> dict[str, Any]:
    """8 số delta cho 1 row (4 chỉ số × 2 chiều) + snapshot giá trị mốc."""
    if base_row is None:
        out: dict[str, Any] = {"is_new": True, "base": None}
        for m in METRICS:
            out[f"{m['key']}_delta"] = None
            out[f"{m['key']}_delta_pct"] = None
        return out

    out = {"is_new": False, "base": {}}
    for m in METRICS:
        src = m["source"]
        cur = _num(cur_row.get(src))
        base = _num(base_row.get(src))
        diff = cur - base
        # Chỉ số đếm giữ nguyên kiểu int để UI không hiện ".0"
        out[f"{m['key']}_delta"] = (
            round(diff, 2) if m["unit"] == "pp" else int(round(diff))
        )
        out[f"{m['key']}_delta_pct"] = _rel_pct(cur, base)
        out["base"][src] = base if m["unit"] == "pp" else int(round(base))
    return out


def _clone_row(row: dict) -> dict:
    """Copy nông + copy riêng list children để không mutate metrics gốc."""
    new = dict(row)
    if isinstance(row.get("children"), list):
        new["children"] = [dict(c) for c in row["children"]]
    return new


def compute_module_overview_delta(
    current_rows: list[dict],
    base_rows: list[dict],
    *,
    group_by: str = "module",
) -> dict[str, Any]:
    """
    Gắn delta vào từng row của bảng Tổng quan theo Module.

    Args:
        current_rows: rows của bản hiện tại (`_overview_by`).
        base_rows: rows của bản mốc so sánh, cùng `group_by`.
        group_by: "module" | "process" | "both" — chỉ dùng để join `children`.

    Returns:
        {
          "rows": rows đã gắn `delta` (và `children[].delta` khi group_by=both),
          "removed": [{key, module, process, label, total, progress_pct,
                       overdue_count, remaining}],
          "summary": {total_delta, progress_delta_pp, overdue_delta,
                      remaining_delta, new_count, removed_count},
          "metrics": METRICS, "polarity": POLARITY
        }
    """
    base_by_key: dict[str, dict] = {}
    for r in base_rows or []:
        base_by_key[_key(r)] = r
        for c in (r.get("children") or []):
            base_by_key[_key(c)] = c

    seen: set[str] = set()
    rows: list[dict] = []
    new_count = 0

    for r in current_rows or []:
        row = _clone_row(r)
        k = _key(row)
        seen.add(k)
        base_row = base_by_key.get(k)
        row["delta"] = _delta_for(row, base_row)
        if base_row is None:
            new_count += 1
        for child in (row.get("children") or []):
            ck = _key(child)
            seen.add(ck)
            child_base = base_by_key.get(ck)
            child["delta"] = _delta_for(child, child_base)
            if child_base is None:
                new_count += 1
        rows.append(row)

    removed: list[dict[str, Any]] = []
    for k, br in base_by_key.items():
        if k in seen:
            continue
        removed.append({
            "key": k,
            "module": str(br.get("module") or ""),
            "process": str(br.get("process") or ""),
            "label": str(br.get("label") or br.get("module") or ""),
            "total": int(_num(br.get("total"))),
            "progress_pct": _num(br.get("progress_pct")),
            "overdue_count": int(_num(br.get("overdue_count"))),
            "remaining": int(_num(br.get("remaining"))),
        })
    removed.sort(key=lambda x: (x["module"], x["process"]))

    # Tổng ở cấp trên: chỉ cộng row cấp cao nhất để không đếm 2 lần khi
    # group_by=both (parent module + children process của chính nó).
    top_rows = rows
    top_base = [r for r in (base_rows or [])]
    summary = {
        "total_delta": int(
            sum(_num(r.get("total")) for r in top_rows)
            - sum(_num(r.get("total")) for r in top_base)
        ),
        "overdue_delta": int(
            sum(_num(r.get("overdue_count")) for r in top_rows)
            - sum(_num(r.get("overdue_count")) for r in top_base)
        ),
        "remaining_delta": int(
            sum(_num(r.get("remaining")) for r in top_rows)
            - sum(_num(r.get("remaining")) for r in top_base)
        ),
        "progress_delta_pp": round(
            _avg(_num(r.get("progress_pct")) for r in top_rows)
            - _avg(_num(r.get("progress_pct")) for r in top_base),
            2,
        ),
        "new_count": new_count,
        "removed_count": len(removed),
    }

    return {
        "rows": rows,
        "removed": removed,
        "summary": summary,
        "metrics": [dict(m) for m in METRICS],
        "polarity": dict(POLARITY),
        "group_by": (group_by or "module").lower().strip(),
    }


def _avg(values) -> float:
    vals = list(values)
    return sum(vals) / len(vals) if vals else 0.0
