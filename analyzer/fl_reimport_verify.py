"""
FL re-import round-trip verify — sau khi re-upload file yellow-cell export.

So sánh issue hits (yellow PIC/Status) giữa snapshot trước và hiện tại:
  - fixed: ô vàng trước đó giờ đã có giá trị hợp lệ
  - still_empty: vẫn trống / bất thường
  - unchanged: vẫn cùng trạng thái empty (không cải thiện)

Ngoài ra: full cell-diff theo Mã CN (meta + mọi phase attribute).
"""
from __future__ import annotations

from typing import Any, Optional

from parser.excel_parser import ParsedData, PhaseData, VALID_STATUSES

# Meta keys so sánh trong full cell-diff (auto-detect đã map vào meta)
_META_DIFF_KEYS = (
    "ma_cn", "ten_cn", "module", "priority", "complexity", "fit_gap",
    "giai_doan", "process", "quy_trinh",
)


def _needs_status_empty(status: Any) -> bool:
    if status is None:
        return True
    s = str(status).strip()
    if not s or s.isdigit():
        return True
    return False


def _needs_pic_empty(pics: Any) -> bool:
    if not pics:
        return True
    if isinstance(pics, (list, tuple)):
        return not any(str(p).strip() for p in pics)
    return not str(pics).strip()


def _row_by_ma(data: ParsedData) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for r in data.rows:
        ma = str(r.meta.get("ma_cn") or "").strip()
        if ma and ma not in out:
            out[ma] = r
    return out


def _cell_state(row, phase: str, kind: str) -> dict[str, Any]:
    pd = row.phases.get(phase) if row else None
    if pd is None:
        pd = PhaseData()
    if kind == "pic":
        empty = _needs_pic_empty(pd.pics)
        value = ", ".join(pd.pics) if pd.pics else ""
    else:
        empty = _needs_status_empty(pd.status)
        value = (pd.status or "").strip()
        if value and value not in VALID_STATUSES and value.isdigit():
            empty = True
    return {"empty": empty, "value": value or "(trống)"}


def verify_fl_reimport(
    previous: ParsedData,
    current: ParsedData,
    *,
    overdue_list: Optional[list[dict]] = None,
    unassigned_list: Optional[list[dict]] = None,
    stalled_list: Optional[list[dict]] = None,
    anomaly_issues: Optional[list[dict]] = None,
) -> dict[str, Any]:
    """
    Dùng yellow cells từ issue hits của snapshot *trước* làm baseline,
    rồi kiểm tra từng ô trên file hiện tại.
    """
    from exporter.fl_reimport_export import collect_issue_hits

    hits = collect_issue_hits(
        overdue_list=overdue_list,
        unassigned_list=unassigned_list,
        stalled_list=stalled_list,
        anomaly_issues=anomaly_issues,
    )
    cell_diff_early = compute_fl_cell_diff(previous, current)
    if not hits:
        return {
            "has_baseline": False,
            "summary": {
                "fixed": 0,
                "still_empty": 0,
                "unchanged": 0,
                "total_yellow": 0,
                "cell_changed": cell_diff_early["summary"]["changed"],
                "cell_added": cell_diff_early["summary"]["added"],
                "cell_removed": cell_diff_early["summary"]["removed"],
            },
            "fixed": [],
            "still_empty": [],
            "cell_diff": cell_diff_early,
            "message": (
                "Snapshot trước không có ô vàng (issue) để verify"
                + (
                    f" · cell-diff {cell_diff_early['summary']['changed']} ô đổi"
                    if cell_diff_early["summary"]["changed"] else ""
                )
                + "."
            ),
        }

    prev_map = _row_by_ma(previous)
    cur_map = _row_by_ma(current)

    fixed: list[dict] = []
    still_empty: list[dict] = []

    for ma, hit in hits.items():
        prev_row = prev_map.get(ma)
        cur_row = cur_map.get(ma)
        ten = ""
        module = ""
        if cur_row:
            ten = str(cur_row.meta.get("ten_cn") or "")
            module = str(cur_row.meta.get("module") or "")
        elif prev_row:
            ten = str(prev_row.meta.get("ten_cn") or "")
            module = str(prev_row.meta.get("module") or "")

        for kind, phases in (("pic", hit.get("yellow_pic") or set()),
                             ("status", hit.get("yellow_status") or set())):
            for ph in phases:
                before = _cell_state(prev_row, ph, kind)
                after = _cell_state(cur_row, ph, kind)
                entry = {
                    "ma_cn": ma,
                    "ten_cn": ten,
                    "module": module,
                    "phase": ph,
                    "field": "PIC" if kind == "pic" else "Status",
                    "old": before["value"],
                    "new": after["value"],
                }
                if before["empty"] and not after["empty"]:
                    fixed.append(entry)
                elif after["empty"]:
                    # Vẫn trống — phân biệt unchanged (cùng empty) vs still
                    entry["unchanged"] = before["empty"] and after["empty"] and before["value"] == after["value"]
                    still_empty.append(entry)

    unchanged = [e for e in still_empty if e.get("unchanged")]
    cell_diff = compute_fl_cell_diff(previous, current)
    return {
        "has_baseline": True,
        "summary": {
            "fixed": len(fixed),
            "still_empty": len(still_empty),
            "unchanged": len(unchanged),
            "total_yellow": len(fixed) + len(still_empty),
            "cell_changed": cell_diff["summary"]["changed"],
            "cell_added": cell_diff["summary"]["added"],
            "cell_removed": cell_diff["summary"]["removed"],
        },
        "fixed": fixed,
        "still_empty": still_empty,
        "cell_diff": cell_diff,
        "message": (
            f"Đã sửa {len(fixed)} ô vàng · còn {len(still_empty)} ô trống/bất thường"
            + (
                f" · cell-diff {cell_diff['summary']['changed']} ô đổi"
                if cell_diff["summary"]["changed"] else ""
            )
            if (fixed or still_empty or cell_diff["summary"]["changed"])
            else "Không còn ô vàng cần verify · không có cell đổi."
        ),
    }


def _norm_cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        parts = sorted(str(x).strip() for x in v if str(x).strip())
        return ", ".join(parts)
    if hasattr(v, "isoformat"):
        try:
            return v.isoformat()[:10]
        except Exception:
            pass
    return str(v).strip()


def _phase_attr_map(pd: PhaseData) -> dict[str, Any]:
    return {
        "Start": pd.start_date,
        "End": pd.end_date,
        "Status": pd.status,
        "PIC": pd.pics,
        "Estimate MH": pd.estimate_mh,
    }


def compute_fl_cell_diff(
    previous: ParsedData,
    current: ParsedData,
    *,
    detail_limit: Optional[int] = 500,
) -> dict[str, Any]:
    """
    Full cell-diff theo Mã CN: meta + mọi phase attribute.

    Chỉ so các row có ma_cn. Row thiếu mã bị bỏ qua (không match được).
    """
    prev_map = _row_by_ma(previous)
    cur_map = _row_by_ma(current)
    all_ma = sorted(set(prev_map) | set(cur_map))

    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []

    # Meta keys thực sự xuất hiện
    meta_keys = list(_META_DIFF_KEYS)
    for src in (previous, current):
        for r in src.rows[:3]:
            for k in r.meta.keys():
                if k not in meta_keys and k not in ("row_num",):
                    meta_keys.append(k)

    phases = list(dict.fromkeys(
        list(previous.all_phases or []) + list(current.all_phases or [])
    ))

    for ma in all_ma:
        prev_row = prev_map.get(ma)
        cur_row = cur_map.get(ma)
        if prev_row is None and cur_row is not None:
            added.append({
                "ma_cn": ma,
                "ten_cn": str(cur_row.meta.get("ten_cn") or ""),
                "module": str(cur_row.meta.get("module") or ""),
            })
            continue
        if cur_row is None and prev_row is not None:
            removed.append({
                "ma_cn": ma,
                "ten_cn": str(prev_row.meta.get("ten_cn") or ""),
                "module": str(prev_row.meta.get("module") or ""),
            })
            continue
        if prev_row is None or cur_row is None:
            continue

        ten = str(cur_row.meta.get("ten_cn") or prev_row.meta.get("ten_cn") or "")
        module = str(cur_row.meta.get("module") or prev_row.meta.get("module") or "")

        for mk in meta_keys:
            if mk == "ma_cn":
                continue
            old_v = _norm_cell(prev_row.meta.get(mk))
            new_v = _norm_cell(cur_row.meta.get(mk))
            if old_v != new_v:
                changes.append({
                    "ma_cn": ma,
                    "ten_cn": ten,
                    "module": module,
                    "phase": "",
                    "field": mk,
                    "old": old_v or "(trống)",
                    "new": new_v or "(trống)",
                })

        for ph in phases:
            p_pd = prev_row.phases.get(ph) or PhaseData()
            c_pd = cur_row.phases.get(ph) or PhaseData()
            p_attrs = _phase_attr_map(p_pd)
            c_attrs = _phase_attr_map(c_pd)
            for attr in ("Start", "End", "Status", "PIC", "Estimate MH"):
                old_v = _norm_cell(p_attrs.get(attr))
                new_v = _norm_cell(c_attrs.get(attr))
                if old_v != new_v:
                    changes.append({
                        "ma_cn": ma,
                        "ten_cn": ten,
                        "module": module,
                        "phase": ph,
                        "field": attr,
                        "old": old_v or "(trống)",
                        "new": new_v or "(trống)",
                    })

    truncated = False
    detail = changes
    if detail_limit is not None and len(changes) > detail_limit:
        detail = changes[:detail_limit]
        truncated = True

    return {
        "summary": {
            "changed": len(changes),
            "added": len(added),
            "removed": len(removed),
            "functions_compared": len(all_ma),
            "truncated": truncated,
        },
        "changes": detail,
        "added": added[:200],
        "removed": removed[:200],
        "message": (
            f"Cell-diff: {len(changes)} ô đổi · +{len(added)} function · −{len(removed)}"
        ),
    }
