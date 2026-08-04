"""
FID Check — phát hiện function Dev đã Closed nhưng FID trống hoặc trùng.

Nghiệp vụ: khi phase Dev (hoặc bất kỳ phase có tên chứa từ khoá dev/coding) đã
Closed thì chức năng đó phải có mã định danh FID duy nhất.

- missing_fid  : Dev Closed, cột FID không có giá trị
- duplicate_fid: FID có giá trị nhưng xuất hiện ở nhiều row (>1 lần)
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from analyzer.kanban import _phase_is_dev
from parser.excel_parser import ParsedData, FunctionRow


def _row_ma_cn(row: FunctionRow) -> str:
    return str(row.meta.get("ma_cn") or "").strip()


def _row_ten_cn(row: FunctionRow) -> str:
    return str(row.meta.get("ten_cn") or "").strip()


def _row_module(row: FunctionRow) -> str:
    return str(row.meta.get("module") or "").strip()


def _row_quy_trinh(row: FunctionRow) -> str:
    return str(row.meta.get("quy_trinh") or row.meta.get("process") or "").strip()


def _row_fid(row: FunctionRow) -> str:
    return str(row.meta.get("fid") or "").strip()


def _dev_closed_phases(row: FunctionRow) -> list[str]:
    """Trả danh sách tên phase dev đã Closed."""
    return [
        pname
        for pname, pd in row.phases.items()
        if _phase_is_dev(pname) and (pd.status or "").strip() == "Closed"
    ]


def compute_fid_issues(data: ParsedData) -> dict[str, Any]:
    """
    Quét ParsedData → trả về:
      {
        "issues": [{ma_cn, ten_cn, module, quy_trinh, fid, issue_type,
                    dev_phase, detail}, ...],
        "summary": {total_issues, missing, duplicate, affected_rows,
                    total_dev_closed_rows},
        "fid_column_present": bool,   # cột FID/Function ID có trong file không
      }
    """
    fid_column_present = data.meta_columns.get("fid") is not None

    # Pass 1 — đếm FID để phát hiện duplicate
    fid_counter: Counter = Counter()
    # map fid → list of ma_cn (để report đầy đủ)
    fid_to_ma: dict[str, list[str]] = {}

    for row in data.rows:
        fid = _row_fid(row)
        if not fid:
            continue
        ma = _row_ma_cn(row)
        fid_counter[fid] += 1
        fid_to_ma.setdefault(fid, []).append(ma)

    duplicate_fids = {f for f, c in fid_counter.items() if c > 1}

    issues: list[dict[str, Any]] = []
    seen_ma_missing: set[str] = set()
    seen_ma_dup: set[str] = set()

    for row in data.rows:
        ma = _row_ma_cn(row)
        if not ma:
            continue
        dev_phases = _dev_closed_phases(row)
        if not dev_phases:
            continue

        fid = _row_fid(row)
        dev_phase_str = ", ".join(dev_phases)

        # missing_fid — mỗi function chỉ báo 1 lần
        if not fid and ma not in seen_ma_missing:
            seen_ma_missing.add(ma)
            issues.append({
                "ma_cn": ma,
                "ten_cn": _row_ten_cn(row),
                "module": _row_module(row),
                "quy_trinh": _row_quy_trinh(row),
                "fid": "",
                "issue_type": "missing_fid",
                "dev_phase": dev_phase_str,
                "detail": f"Phase {dev_phase_str!r} đã Closed nhưng FID trống",
            })

        # duplicate_fid
        if fid and fid in duplicate_fids and ma not in seen_ma_dup:
            seen_ma_dup.add(ma)
            dup_mas = [m for m in fid_to_ma.get(fid, []) if m != ma]
            issues.append({
                "ma_cn": ma,
                "ten_cn": _row_ten_cn(row),
                "module": _row_module(row),
                "quy_trinh": _row_quy_trinh(row),
                "fid": fid,
                "issue_type": "duplicate_fid",
                "dev_phase": dev_phase_str,
                "detail": (
                    f"FID '{fid}' xuất hiện {fid_counter[fid]} lần"
                    + (f" (trùng với: {', '.join(dup_mas[:3])})" if dup_mas else "")
                ),
            })

    missing_count = sum(1 for i in issues if i["issue_type"] == "missing_fid")
    dup_count = sum(1 for i in issues if i["issue_type"] == "duplicate_fid")
    total_dev_closed = sum(1 for row in data.rows if _dev_closed_phases(row))

    return {
        "issues": issues,
        "summary": {
            "total_issues": len(issues),
            "missing": missing_count,
            "duplicate": dup_count,
            "affected_rows": len({i["ma_cn"] for i in issues}),
            "total_dev_closed_rows": total_dev_closed,
        },
        "fid_column_present": fid_column_present,
    }
