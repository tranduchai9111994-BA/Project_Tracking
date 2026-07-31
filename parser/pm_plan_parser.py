# -*- coding: utf-8 -*-
"""
Parser kế hoạch dự án PM (KeHoachDuAn Excel).

Sheet roles (auto-propose):
  gantt          — WBS / milestone (Gantt-chart)
  gantt_old      — bản cũ (bỏ qua khi parse chính, vẫn liệt kê)
  schedule       — lịch trình chi tiết (UAT/Golive): ngày + PIC
  deliverables   — sản phẩm bàn giao
  team_vendor    — đội FPT
  team_client    — đội khách hàng
  ignore         — bỏ qua
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Optional

import openpyxl

# Vai trò sheet chuẩn cho mapping UI
SHEET_ROLES = [
    "gantt",
    "gantt_old",
    "schedule",
    "deliverables",
    "team_vendor",
    "team_client",
    "ignore",
]

ROLE_LABELS_VI = {
    "gantt": "Gantt / WBS (chính)",
    "gantt_old": "Gantt cũ (bỏ qua parse)",
    "schedule": "Lịch trình chi tiết (ngày + PIC)",
    "deliverables": "Sản phẩm bàn giao",
    "team_vendor": "Đội dự án FPT (vendor)",
    "team_client": "Đội dự án khách hàng",
    "ignore": "Bỏ qua",
}


def _cell_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v).strip()


def _to_iso_date(v: Any) -> Optional[str]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    s = str(v).strip()
    if not s or s.upper() in ("#REF!", "#N/A", "#VALUE!", "N/A"):
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _split_pics(raw: Any) -> list[str]:
    """Tách PIC giống Function List: dấu phẩy / ; / xuống dòng."""
    if raw is None or raw == "":
        return []
    text = str(raw).replace("\r\n", "\n").replace("\r", "\n")
    parts = re.split(r"[,;\n]+", text)
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        s = p.strip().lstrip("+").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def propose_sheet_mapping(sheet_names: list[str]) -> dict[str, str]:
    """Gợi ý role cho từng sheet theo keyword tên."""
    mapping: dict[str, str] = {}
    for name in sheet_names:
        n = (name or "").strip().lower()
        role = "ignore"
        if "gantt" in n and "old" in n:
            role = "gantt_old"
        elif "gantt" in n:
            role = "gantt"
        elif any(k in n for k in ("lịch trình", "lich trinh", "uat", "golive")):
            role = "schedule"
        elif any(k in n for k in ("sản phẩm", "san pham", "bàn giao", "ban giao", "deliverable")):
            role = "deliverables"
        elif any(k in n for k in ("đội", "doi ", "team")) and "fpt" in n:
            role = "team_vendor"
        elif any(k in n for k in ("đội", "doi ", "team")) and "fpt" not in n:
            role = "team_client"
        elif "fpt" in n and any(k in n for k in ("đội", "doi", "nhân sự", "nhan su")):
            role = "team_vendor"
        mapping[name] = role

    # Đảm bảo có đúng 1 gantt chính nếu có nhiều
    gantts = [s for s, r in mapping.items() if r == "gantt"]
    if len(gantts) > 1:
        # Giữ sheet không có "old", còn lại → gantt_old
        for s in gantts:
            if "old" in s.lower():
                mapping[s] = "gantt_old"
    return mapping


def preview_plan_workbook(filepath: str) -> dict[str, Any]:
    """Đọc tên sheet + vài dòng mẫu + đề xuất mapping (chưa parse đầy đủ)."""
    wb = openpyxl.load_workbook(filepath, data_only=True, read_only=True)
    sheets: list[dict[str, Any]] = []
    try:
        for name in wb.sheetnames:
            ws = wb[name]
            sample: list[list[Any]] = []
            for i, row in enumerate(ws.iter_rows(max_row=6, max_col=10, values_only=True)):
                sample.append([_cell_str(c) if c is not None else "" for c in row])
                if i >= 5:
                    break
            sheets.append({"name": name, "sample": sample})
    finally:
        wb.close()
    mapping = propose_sheet_mapping([s["name"] for s in sheets])
    return {
        "sheets": sheets,
        "proposed_mapping": mapping,
        "role_labels": ROLE_LABELS_VI,
        "roles": SHEET_ROLES,
    }


def parse_plan(
    filepath: str,
    sheet_mapping: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """
    Parse KeHoachDuAn → dict chuẩn hoá.

    sheet_mapping: {sheet_name: role}; nếu None → auto-propose.
    """
    wb = openpyxl.load_workbook(filepath, data_only=True)
    try:
        names = list(wb.sheetnames)
        mapping = sheet_mapping or propose_sheet_mapping(names)
        # Chỉ map sheet tồn tại
        mapping = {k: v for k, v in mapping.items() if k in names}

        result: dict[str, Any] = {
            "sheet_mapping": mapping,
            "sheet_names": names,
            "weeks": [],
            "milestones": [],
            "schedule": [],
            "deliverables": [],
            "team_vendor": [],
            "team_client": [],
        }

        for sheet_name, role in mapping.items():
            if role in ("ignore", "gantt_old"):
                continue
            ws = wb[sheet_name]
            if role == "gantt":
                weeks, milestones = _parse_gantt(ws)
                result["weeks"] = weeks
                result["milestones"] = milestones
            elif role == "schedule":
                result["schedule"] = _parse_schedule(ws)
            elif role == "deliverables":
                result["deliverables"] = _parse_deliverables(ws)
            elif role == "team_vendor":
                result["team_vendor"] = _parse_team(ws, side="vendor")
            elif role == "team_client":
                result["team_client"] = _parse_team(ws, side="client")

        result["summary"] = {
            "milestone_count": len(result["milestones"]),
            "schedule_count": len(result["schedule"]),
            "deliverable_count": len(
                [d for d in result["deliverables"] if not d.get("is_group")]
            ),
            "team_vendor_count": len(result["team_vendor"]),
            "team_client_count": len(result["team_client"]),
        }
        return result
    finally:
        wb.close()


def _parse_gantt(ws) -> tuple[list[dict], list[dict]]:
    """Đọc WBS: STT + Công việc + danh sách tuần (W1..). Thanh Gantt thường là shape → không lấy được week_start/end từ fill."""
    weeks: list[dict] = []
    # Row 2 = tháng, row 3 = W1..; hoặc tìm row có W1
    week_row = None
    month_row = None
    for r in range(1, 6):
        vals = [_cell_str(ws.cell(r, c).value) for c in range(1, min(50, (ws.max_column or 1) + 1))]
        if any(re.fullmatch(r"W\d+", v) for v in vals):
            week_row = r
            month_row = r - 1 if r > 1 else None
            break
    if week_row:
        current_month = ""
        for c in range(1, min(60, (ws.max_column or 1) + 1)):
            wlabel = _cell_str(ws.cell(week_row, c).value)
            if month_row:
                m = _cell_str(ws.cell(month_row, c).value)
                if m:
                    current_month = m
            if re.fullmatch(r"W\d+", wlabel):
                weeks.append({"col": c, "label": wlabel, "month": current_month})

    milestones: list[dict] = []
    start_r = (week_row or 3) + 1
    for r in range(start_r, (ws.max_row or 0) + 1):
        stt = ws.cell(r, 1).value
        name = _cell_str(ws.cell(r, 2).value)
        if not name:
            continue
        # Bỏ header lặp
        if name.lower() in ("công việc", "cong viec"):
            continue
        milestones.append({
            "stt": _cell_str(stt) if stt is not None else "",
            "name": name,
            "week_start": None,
            "week_end": None,
            "note": "Thanh Gantt (shape) — tuần chi tiết xem sheet Lịch trình",
        })
    return weeks, milestones


def _parse_schedule(ws) -> list[dict]:
    """Lịch trình UAT/Golive: header có Công việc / Từ ngày / Đến ngày / PIC."""
    # Tìm header row
    header_row = None
    col_map: dict[str, int] = {}
    for r in range(1, min(10, (ws.max_row or 1) + 1)):
        row_vals = {
            c: _cell_str(ws.cell(r, c).value).replace("\n", " ")
            for c in range(1, min(15, (ws.max_column or 1) + 1))
        }
        joined = " | ".join(row_vals.values()).lower()
        if "công việc" in joined or "cong viec" in joined:
            if any("ngày" in v.lower() or "ngay" in v.lower() for v in row_vals.values()):
                header_row = r
                for c, v in row_vals.items():
                    vl = v.lower()
                    if "công việc" in vl or "cong viec" in vl:
                        col_map["name"] = c
                    elif "từ ngày" in vl or "tu ngay" in vl or vl == "start":
                        col_map["start"] = c
                    elif "đến ngày" in vl or "den ngay" in vl or vl in ("end", "to"):
                        col_map["end"] = c
                    elif "phụ trách" in vl and "fpt" in vl:
                        col_map["pic_fpt"] = c
                    elif "hỗ trợ" in vl and "fpt" in vl:
                        col_map["support_fpt"] = c
                    elif "phụ trách" in vl and ("mphg" in vl or "khách" in vl or "client" in vl):
                        col_map["pic_client"] = c
                    elif "hỗ trợ" in vl and ("mphg" in vl or "khách" in vl or "client" in vl):
                        col_map["support_client"] = c
                    elif "ghi chú" in vl or "ghi chu" in vl or "note" in vl:
                        col_map["note"] = c
                break

    if not header_row:
        # Fallback: col 1-8 như mẫu MPHG
        header_row = 2
        col_map = {
            "name": 1, "start": 2, "end": 3,
            "pic_fpt": 4, "support_fpt": 5,
            "pic_client": 6, "support_client": 7, "note": 8,
        }

    items: list[dict] = []
    current_phase = ""
    for r in range(header_row + 1, (ws.max_row or 0) + 1):
        name = _cell_str(ws.cell(r, col_map.get("name", 1)).value)
        if not name:
            continue
        start = _to_iso_date(ws.cell(r, col_map["start"]).value) if "start" in col_map else None
        end = _to_iso_date(ws.cell(r, col_map["end"]).value) if "end" in col_map else None
        pic_fpt = _split_pics(ws.cell(r, col_map["pic_fpt"]).value) if "pic_fpt" in col_map else []
        support_fpt = _split_pics(ws.cell(r, col_map["support_fpt"]).value) if "support_fpt" in col_map else []
        pic_client = _split_pics(ws.cell(r, col_map["pic_client"]).value) if "pic_client" in col_map else []
        support_client = _split_pics(ws.cell(r, col_map["support_client"]).value) if "support_client" in col_map else []
        note = _cell_str(ws.cell(r, col_map["note"]).value) if "note" in col_map else ""

        is_phase = bool(re.match(r"(?i)^giai\s*đoạn|^giai\s*doan|^phase\b", name))
        # Phase header: có ngày nhưng không có PIC, hoặc tên bắt đầu bằng Giai đoạn
        has_any_pic = bool(pic_fpt or support_fpt or pic_client or support_client)
        if is_phase or (start and end and not has_any_pic and name.lower().startswith("giai")):
            current_phase = name
            items.append({
                "name": name,
                "start": start,
                "end": end,
                "pic_fpt": [],
                "support_fpt": [],
                "pic_client": [],
                "support_client": [],
                "note": note,
                "is_phase_header": True,
                "phase": name,
            })
            continue

        items.append({
            "name": name,
            "start": start,
            "end": end,
            "pic_fpt": pic_fpt,
            "support_fpt": support_fpt,
            "pic_client": pic_client,
            "support_client": support_client,
            "note": note,
            "is_phase_header": False,
            "phase": current_phase,
        })
    return items


def _parse_deliverables(ws) -> list[dict]:
    """Sản phẩm bàn giao — group header (STT text) + item rows."""
    header_row = None
    for r in range(1, 6):
        vals = [_cell_str(ws.cell(r, c).value).lower() for c in range(1, 12)]
        if any("sản phẩm" in v or "san pham" in v or "deliverable" in v for v in vals):
            header_row = r
            break
        if "stt" in vals and any("bàn giao" in v or "ban giao" in v for v in vals):
            header_row = r
            break
    if not header_row:
        header_row = 2

    items: list[dict] = []
    current_group = ""
    for r in range(header_row + 1, (ws.max_row or 0) + 1):
        stt_raw = ws.cell(r, 1).value
        name = _cell_str(ws.cell(r, 2).value)
        stt_s = _cell_str(stt_raw)
        # Group: có text ở col1, không có name hoặc name trống
        if stt_s and not str(stt_raw).replace(".", "").isdigit() and not name:
            current_group = stt_s
            items.append({
                "stt": "",
                "name": stt_s,
                "is_group": True,
                "group": stt_s,
                "due_date": None,
                "type": "",
                "note": "",
                "author": "",
                "reviewer_fpt": "",
                "approver_fpt": "",
            })
            continue
        if not name:
            continue
        items.append({
            "stt": stt_s,
            "name": name,
            "is_group": False,
            "group": current_group,
            "due_date": _to_iso_date(ws.cell(r, 3).value),
            "type": _cell_str(ws.cell(r, 4).value),
            "note": _cell_str(ws.cell(r, 5).value),
            "author": _cell_str(ws.cell(r, 6).value),
            "reviewer_fpt": _cell_str(ws.cell(r, 7).value),
            "approver_fpt": _cell_str(ws.cell(r, 8).value),
        })
    return items


def _parse_team(ws, side: str = "vendor") -> list[dict]:
    """Đội dự án — group + members (Họ tên, Chức vụ, Trách nhiệm, Email)."""
    header_row = None
    for r in range(1, 5):
        vals = [_cell_str(ws.cell(r, c).value).lower() for c in range(1, 8)]
        if any("họ" in v or "tên" in v or "name" in v for v in vals):
            header_row = r
            break
    if not header_row:
        header_row = 1

    # Map columns loosely
    headers = {
        c: _cell_str(ws.cell(header_row, c).value).lower()
        for c in range(1, min(8, (ws.max_column or 1) + 1))
    }
    col_name = col_title = col_role = col_resp = col_email = None
    for c, h in headers.items():
        if "họ" in h or "tên" in h or h == "name":
            col_name = c
        elif "chức vụ" in h or "chuc vu" in h or "title" in h:
            col_title = c
        elif "vai trò" in h or "vai tro" in h or h == "role":
            col_role = c
        elif "trách nhiệm" in h or "trach nhiem" in h:
            col_resp = c
        elif "email" in h:
            col_email = c
    col_name = col_name or 2
    col_title = col_title or 3
    col_resp = col_resp or (5 if side == "client" else 4)
    col_email = col_email or (6 if side == "client" else 5)

    members: list[dict] = []
    current_group = ""
    for r in range(header_row + 1, (ws.max_row or 0) + 1):
        stt_raw = ws.cell(r, 1).value
        name = _cell_str(ws.cell(r, col_name).value)
        stt_s = _cell_str(stt_raw)
        if stt_s and not str(stt_raw).replace(".", "").isdigit() and not name:
            current_group = stt_s
            continue
        if not name:
            continue
        members.append({
            "group": current_group,
            "stt": stt_s,
            "name": name,
            "title": _cell_str(ws.cell(r, col_title).value) if col_title else "",
            "role": _cell_str(ws.cell(r, col_role).value) if col_role else "",
            "responsibility": _cell_str(ws.cell(r, col_resp).value) if col_resp else "",
            "email": _cell_str(ws.cell(r, col_email).value) if col_email else "",
            "side": side,
        })
    return members
