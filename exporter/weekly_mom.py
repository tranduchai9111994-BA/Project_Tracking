"""
Xuất báo cáo tuần MoM (Meeting Minutes) theo mẫu W30.

Sheets:
  1. Cover Page     — mục lục cuộc họp + mã dự án
  2. Master plan    — khung WBS (PM nhập thủ công; Function List không có dữ liệu này)
  3. MoM_W{n}       — biên bản họp tuần (gợi ý từ overdue / deadline tuần nếu có ParsedData)
  4. PM Dashboard   — số liệu dashboard tiêu biểu cho PM (từ metrics engine)

Ô thiếu data → để trống / "N/A" + ghi chú, không bịa số.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any, Optional

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from exporter.excel_exporter import (
    BODY_ALIGN,
    BODY_FONT,
    GREEN_FILL,
    HEADER_ALIGN,
    HEADER_FILL,
    HEADER_FONT,
    ORANGE_FILL,
    RED_FILL,
    THIN_BORDER,
    YELLOW_FILL,
    _fill_by_days,
)

# Styles riêng MoM (bám mẫu W30: header xanh đậm, section vàng)
TITLE_FONT = Font(name="Arial", bold=True, size=14, color="1F4E79")
SECTION_FILL = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
SECTION_FONT = Font(name="Arial", bold=True, size=11, color="1F4E79")
NOTE_FONT = Font(name="Arial", italic=True, size=9, color="666666")
LABEL_FONT = Font(name="Arial", bold=True, size=10)
NA = "N/A"


def _iso_week_label(d: date) -> str:
    """VD: W30 (ISO week)."""
    return f"W{d.isocalendar()[1]:02d}"


def _fmt_date(v: Any) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, datetime):
        return v.strftime("%d/%m/%Y")
    if isinstance(v, date):
        return v.strftime("%d/%m/%Y")
    s = str(v).strip()
    # ISO → dd/MM/yyyy nếu parse được
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    return s


def _week_range(d: date) -> tuple[date, date]:
    """Thứ 2 → Chủ nhật của tuần ISO chứa d."""
    start = d - timedelta(days=d.weekday())
    return start, start + timedelta(days=6)


def _style_header_row(ws, row: int, n_cols: int) -> None:
    for c in range(1, n_cols + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER


def _apply_border_row(ws, row: int, n_cols: int) -> None:
    for c in range(1, n_cols + 1):
        cell = ws.cell(row=row, column=c)
        cell.border = THIN_BORDER
        cell.font = BODY_FONT
        cell.alignment = BODY_ALIGN


def _collect_week_deadlines(parsed_data, week_start: date, week_end: date) -> list[dict]:
    """Gợi ý công việc có End date trong tuần (phase chưa Closed/Cancelled)."""
    if parsed_data is None:
        return []
    items: list[dict] = []
    for r in parsed_data.rows:
        for phase_name, pd in (r.phases or {}).items():
            if not pd.end_date:
                continue
            if pd.end_date < week_start or pd.end_date > week_end:
                continue
            st = (pd.status or "").strip()
            if st in ("Closed", "Cancelled"):
                continue
            items.append({
                "ten": f"[{phase_name}] {r.meta.get('ten_cn') or r.meta.get('ma_cn') or ''}",
                "pic": ", ".join(pd.pics or []) or NA,
                "from": _fmt_date(pd.start_date),
                "to": _fmt_date(pd.end_date),
                "status": st or "",
                "note": (pd.note or "")[:80],
                "module": r.meta.get("module") or "",
            })
    items.sort(key=lambda x: (x["to"], x["module"]))
    return items[:15]  # giới hạn gợi ý


def _write_cover(
    wb,
    project_code: str,
    week_label: str,
    meeting_sheet_name: str,
    today: date,
) -> None:
    ws = wb.create_sheet("Cover Page", 0)
    for col, w in zip("ABCDEFGHIJK", [4, 18, 16, 14, 14, 14, 22, 12, 12, 12, 12]):
        ws.column_dimensions[col].width = w

    ws["B4"] = "Project Code: "
    ws["B4"].font = LABEL_FONT
    ws["C4"] = project_code or NA
    ws["C4"].font = Font(name="Arial", bold=True, size=12, color="1F4E79")
    ws["G4"] = "Meeting Minutes Records"
    ws["G4"].font = TITLE_FONT

    ws["B5"] = "version: "
    ws["B5"].font = LABEL_FONT
    ws["C5"] = "v1.0 (auto từ iHRP Tracker)"
    ws["E5"] = "Tuần:"
    ws["E5"].font = LABEL_FONT
    ws["F5"] = week_label
    ws["F5"].font = Font(name="Arial", bold=True, size=12, color="C00000")

    ws["B6"] = "Ghi chú:"
    ws["C6"] = (
        "Cover/Master plan/MoM bám mẫu W30. "
        "Ô N/A hoặc trống = không có trong Function List — PM điền tay. "
        "Sheet PM Dashboard = số liệu dashboard tự động."
    )
    ws["C6"].font = NOTE_FONT
    ws.merge_cells("C6:H6")

    headers = ["Sheet Name", "Date", "Review subject"]
    for i, h in enumerate(headers, 2):
        cell = ws.cell(row=8, column=i, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER
    ws.merge_cells("D8:G8")

    # Dòng 1: sheet MoM tuần hiện tại
    ws["B9"] = meeting_sheet_name
    ws["C9"] = today.strftime("%d/%m/%Y")
    ws["D9"] = f"Họp định kỳ dự án — {week_label}"
    ws.merge_cells("D9:G9")
    for c in range(2, 8):
        ws.cell(row=9, column=c).border = THIN_BORDER
        ws.cell(row=9, column=c).font = BODY_FONT

    # Dòng 2: PM Dashboard
    ws["B10"] = "PM Dashboard"
    ws["C10"] = today.strftime("%d/%m/%Y")
    ws["D10"] = "Tóm tắt metrics Function List (auto)"
    ws.merge_cells("D10:G10")
    for c in range(2, 8):
        ws.cell(row=10, column=c).border = THIN_BORDER
        ws.cell(row=10, column=c).font = BODY_FONT

    # Chỗ trống cho lần họp sau (PM điền)
    for r in range(11, 16):
        ws.merge_cells(f"D{r}:G{r}")
        for c in range(2, 8):
            ws.cell(row=r, column=c).border = THIN_BORDER


def _write_master_plan(wb) -> None:
    """Khung Master plan giống mẫu — nội dung WBS không có trong Function List."""
    ws = wb.create_sheet("Master plan")
    widths = {"B": 8, "C": 55, "D": 14, "E": 12, "F": 12, "G": 16, "H": 16, "I": 16, "J": 16, "K": 24}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w

    ws["I1"] = "Cập nhật liên tục"
    ws["I1"].font = NOTE_FONT
    ws.merge_cells("I1:J1")

    # Header 2 hàng như mẫu
    ws["B2"] = "STT"
    ws["C2"] = "Công việc"
    ws["D2"] = "Tình trạng"
    ws["E2"] = "PIC"
    ws["G2"] = "Kế hoạch v1.0"
    ws["I2"] = "Kế hoạch LU"
    ws["K2"] = "Ghi chú"
    ws.merge_cells("B2:B3")
    ws.merge_cells("C2:C3")
    ws.merge_cells("E2:F2")
    ws.merge_cells("G2:H2")
    ws.merge_cells("I2:J2")
    ws["E3"] = "FIS"
    ws["F3"] = "KDG"
    ws["G3"] = "Thời gian bắt đầu"
    ws["H3"] = "Thời gian kết thúc"
    ws["I3"] = "Thời gian bắt đầu"
    ws["J3"] = "Thời gian kết thúc"

    for r in (2, 3):
        for c in range(2, 12):
            cell = ws.cell(row=r, column=c)
            cell.font = HEADER_FONT
            cell.fill = HEADER_FILL
            cell.alignment = HEADER_ALIGN
            cell.border = THIN_BORDER

    ws["B4"] = ""
    ws["C4"] = (
        "N/A — Master plan (WBS dự án) không sinh từ Function List. "
        "PM copy từ kế hoạch gốc hoặc điền tay."
    )
    ws["C4"].font = NOTE_FONT
    ws.merge_cells("C4:K4")

    # Vài dòng trống có border để PM điền
    for r in range(5, 12):
        ws.cell(row=r, column=2, value=r - 4)
        for c in range(2, 12):
            ws.cell(row=r, column=c).border = THIN_BORDER
            ws.cell(row=r, column=c).font = BODY_FONT


def _write_mom_sheet(
    wb,
    sheet_name: str,
    week_label: str,
    today: date,
    metrics: dict,
    parsed_data=None,
) -> None:
    """Biên bản họp tuần — cấu trúc bám sheet '1'/'2' của mẫu W30."""
    ws = wb.create_sheet(sheet_name)
    for col, w in zip("ABCDEFGH", [6, 12, 55, 18, 14, 12, 12, 12]):
        ws.column_dimensions[col].width = w

    week_start, week_end = _week_range(today)

    # === Meta họp ===
    ws["B2"] = "Ngày/Date:  "
    ws["B2"].font = LABEL_FONT
    ws.merge_cells("B2:C2")
    ws["D2"] = today
    ws["D2"].number_format = "DD/MM/YYYY"
    ws.merge_cells("D2:E2")
    ws["F2"] = "Return to Cover Page"
    ws["F2"].font = Font(name="Arial", italic=True, size=9, color="0563C1")
    ws.merge_cells("F2:H2")

    ws["B3"] = "Giờ/Time: "
    ws["B3"].font = LABEL_FONT
    ws.merge_cells("B3:C3")
    ws["D3"] = NA  # PM điền
    ws["D3"].font = NOTE_FONT

    ws["B4"] = "Tên/Subject:  "
    ws["B4"].font = LABEL_FONT
    ws.merge_cells("B4:C4")
    ws["D4"] = f"Họp định kỳ dự án — {week_label}"
    ws.merge_cells("D4:H4")

    ws["B5"] = "Người tham gia/Committee:  "
    ws["B5"].font = LABEL_FONT
    ws.merge_cells("B5:C5")
    ws["D5"] = NA  # PM điền
    ws["D5"].font = NOTE_FONT
    ws.merge_cells("D5:H5")

    ws["B7"] = "Nội dung/ Content"
    ws["B7"].font = SECTION_FONT

    # Header bảng công việc
    headers = ["STT", "Công việc", "PIC", "Ghi chú", "Từ ngày", "Đến ngày", "Tình trạng"]
    for i, h in enumerate(headers, 2):
        ws.cell(row=8, column=i, value=h)
    _style_header_row(ws, 8, 8)
    # cột A trống như mẫu (bắt đầu từ B)
    ws.cell(row=8, column=1).border = THIN_BORDER

    # --- Section A: Kế hoạch tuần này (gợi ý từ deadline trong tuần) ---
    row = 9
    ws.cell(row=row, column=2, value="A")
    ws.cell(row=row, column=3, value="KẾ HOẠCH TUẦN NÀY (gợi ý từ Function List)")
    for c in range(2, 9):
        ws.cell(row=row, column=c).fill = SECTION_FILL
        ws.cell(row=row, column=c).font = SECTION_FONT
        ws.cell(row=row, column=c).border = THIN_BORDER

    upcoming = _collect_week_deadlines(parsed_data, week_start, week_end)
    row = 10
    if upcoming:
        for idx, it in enumerate(upcoming, 1):
            vals = [idx, it["ten"], it["pic"], it["note"], it["from"], it["to"], it["status"]]
            for c, v in enumerate(vals, 2):
                ws.cell(row=row, column=c, value=v)
            _apply_border_row(ws, row, 8)
            row += 1
    else:
        ws.cell(row=row, column=2, value=1)
        ws.cell(
            row=row, column=3,
            value=(
                "N/A — không có phase End date trong tuần này "
                f"({week_start.strftime('%d/%m')}–{week_end.strftime('%d/%m/%Y')}). "
                "PM điền kế hoạch họp."
            ),
        )
        ws.cell(row=row, column=3).font = NOTE_FONT
        _apply_border_row(ws, row, 8)
        row += 1
        # Thêm vài dòng trống
        for i in range(2, 5):
            ws.cell(row=row, column=2, value=i)
            _apply_border_row(ws, row, 8)
            row += 1

    # --- Section B: Kế hoạch tuần tới (khung trống) ---
    row += 1
    ws.cell(row=row, column=2, value="B")
    ws.cell(row=row, column=3, value="KẾ HOẠCH TUẦN TỚI (PM điền tay)")
    for c in range(2, 9):
        ws.cell(row=row, column=c).fill = SECTION_FILL
        ws.cell(row=row, column=c).font = SECTION_FONT
        ws.cell(row=row, column=c).border = THIN_BORDER
    row += 1
    for i in range(1, 6):
        ws.cell(row=row, column=2, value=i)
        _apply_border_row(ws, row, 8)
        row += 1

    # --- Hành động (gợi ý từ overdue top) ---
    row += 1
    action_header_row = row
    ws.cell(row=row, column=2, value="Hành động (gợi ý từ Overdue)")
    ws.cell(row=row, column=6, value="PIC")
    ws.cell(row=row, column=7, value="Ngày")
    ws.cell(row=row, column=8, value="Trạng thái")
    ws.merge_cells(f"B{row}:E{row}")
    for c in range(2, 9):
        cell = ws.cell(row=row, column=c)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER

    overdue = list(metrics.get("overdue_list") or [])[:10]
    row += 1
    if overdue:
        for idx, it in enumerate(overdue, 1):
            ten = (
                f"Xử lý trễ [{it.get('phase', '')}] "
                f"{it.get('ma_cn') or ''} — {it.get('ten_cn') or ''}"
            ).strip(" —")
            pic = ", ".join(it.get("pic") or []) or NA
            ws.cell(row=row, column=2, value=idx)
            ws.cell(row=row, column=3, value=ten)
            ws.merge_cells(f"C{row}:E{row}")
            ws.cell(row=row, column=6, value=pic)
            ws.cell(row=row, column=7, value=_fmt_date(it.get("end_date")))
            ws.cell(row=row, column=8, value=it.get("status") or "Open")
            fill = _fill_by_days(int(it.get("days_overdue") or 0))
            for c in range(2, 9):
                cell = ws.cell(row=row, column=c)
                cell.border = THIN_BORDER
                cell.font = BODY_FONT
                cell.alignment = BODY_ALIGN
                if fill:
                    cell.fill = fill
            row += 1
    else:
        ws.cell(row=row, column=2, value=1)
        ws.cell(row=row, column=3, value="N/A — không có task overdue.")
        ws.cell(row=row, column=3).font = NOTE_FONT
        ws.merge_cells(f"C{row}:E{row}")
        _apply_border_row(ws, row, 8)
        row += 1
        for i in range(2, 5):
            ws.cell(row=row, column=2, value=i)
            ws.merge_cells(f"C{row}:E{row}")
            _apply_border_row(ws, row, 8)
            row += 1

    # Footer note
    row += 1
    ws.cell(
        row=row, column=2,
        value=(
            f"Gợi ý auto từ metrics ngày {today.strftime('%d/%m/%Y')}. "
            "Giờ họp / người tham gia / kế hoạch tuần tới: điền tay trước khi gửi sếp."
        ),
    )
    ws.cell(row=row, column=2).font = NOTE_FONT
    ws.merge_cells(f"B{row}:H{row}")
    _ = action_header_row  # giữ biến cho đọc code


def _block_title(ws, row: int, title: str, n_cols: int = 8) -> int:
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=n_cols)
    cell = ws.cell(row=row, column=1, value=title)
    cell.font = SECTION_FONT
    cell.fill = SECTION_FILL
    for c in range(1, n_cols + 1):
        ws.cell(row=row, column=c).fill = SECTION_FILL
        ws.cell(row=row, column=c).border = THIN_BORDER
    return row + 1


def _write_pm_dashboard(wb, metrics: dict, today: date, week_label: str) -> None:
    """
    Sheet PM Dashboard — 5 block số liệu tiêu biểu:
      1. Summary cards
      2. Overdue (top)
      3. Phase progress
      4. Module overview
      5. PIC workload (top)
    """
    ws = wb.create_sheet("PM Dashboard")
    for i in range(1, 12):
        ws.column_dimensions[get_column_letter(i)].width = 14
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 36

    ws.merge_cells("A1:H1")
    ws["A1"] = f"PM DASHBOARD — Function List Tracker ({week_label})"
    ws["A1"].font = TITLE_FONT
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    ws.merge_cells("A2:H2")
    ws["A2"] = f"Xuất ngày {today.strftime('%d/%m/%Y')} — số liệu từ metrics engine (không phải MoM tay)"
    ws["A2"].font = NOTE_FONT
    ws["A2"].alignment = Alignment(horizontal="center")

    summary = metrics.get("summary") or {}
    row = 4

    # --- 1. Summary cards ---
    row = _block_title(ws, row, "1. TÓM TẮT (Summary cards)")
    cards = [
        ("Tổng chức năng", summary.get("total_functions", NA)),
        ("Tiến độ chung (%)", summary.get("overall_progress_pct", NA)),
        ("Task trễ (function)", summary.get("total_overdue", NA)),
        ("Task trễ (phase records)", summary.get("total_overdue_records", NA)),
        ("Chưa có PIC", summary.get("unassigned_count", NA)),
        ("High-risk (≥50)", summary.get("high_risk_count", NA)),
        ("Số Module", summary.get("modules_count", NA)),
        ("Số Phase", summary.get("phases_count", NA)),
    ]
    ws.cell(row=row, column=1, value="Chỉ số").font = HEADER_FONT
    ws.cell(row=row, column=1).fill = HEADER_FILL
    ws.cell(row=row, column=1).border = THIN_BORDER
    ws.cell(row=row, column=2, value="Giá trị").font = HEADER_FONT
    ws.cell(row=row, column=2).fill = HEADER_FILL
    ws.cell(row=row, column=2).border = THIN_BORDER
    row += 1
    for label, val in cards:
        ws.cell(row=row, column=1, value=label).font = LABEL_FONT
        ws.cell(row=row, column=1).border = THIN_BORDER
        c = ws.cell(row=row, column=2, value=val if val is not None else NA)
        c.font = BODY_FONT
        c.border = THIN_BORDER
        c.alignment = Alignment(horizontal="right")
        # Highlight overdue
        if "trễ" in label.lower() and isinstance(val, (int, float)) and val > 0:
            c.fill = RED_FILL
        row += 1

    row += 1
    # --- 2. Overdue top ---
    row = _block_title(ws, row, "2. OVERDUE (top 20 theo số ngày trễ)")
    overdue = list(metrics.get("overdue_list") or [])[:20]
    ov_headers = ["STT", "Mã CN", "Tên chức năng", "Module", "Phase", "Deadline", "Ngày trễ", "Status", "PIC"]
    for i, h in enumerate(ov_headers, 1):
        cell = ws.cell(row=row, column=i, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER
    row += 1
    if not overdue:
        ws.cell(row=row, column=1, value="N/A — không có task overdue.").font = NOTE_FONT
        row += 1
    else:
        for idx, it in enumerate(overdue, 1):
            vals = [
                idx,
                it.get("ma_cn", ""),
                it.get("ten_cn", ""),
                it.get("module", ""),
                it.get("phase", ""),
                _fmt_date(it.get("end_date")),
                it.get("days_overdue", 0),
                it.get("status", ""),
                ", ".join(it.get("pic") or []),
            ]
            fill = _fill_by_days(int(it.get("days_overdue") or 0))
            for c, v in enumerate(vals, 1):
                cell = ws.cell(row=row, column=c, value=v)
                cell.font = BODY_FONT
                cell.border = THIN_BORDER
                cell.alignment = BODY_ALIGN
                if fill:
                    cell.fill = fill
            row += 1

    row += 1
    # --- 3. Phase progress ---
    row = _block_title(ws, row, "3. PHASE PROGRESS (số function theo status)", n_cols=10)
    stacked = metrics.get("phase_progress_stacked") or {}
    phases = stacked.get("phases") or []
    statuses = stacked.get("statuses") or []
    pdata = stacked.get("data") or {}
    if not phases:
        ws.cell(row=row, column=1, value="N/A — chưa có phase_progress_stacked.").font = NOTE_FONT
        row += 1
    else:
        hdr = ["Phase"] + list(statuses) + ["Tổng"]
        for i, h in enumerate(hdr, 1):
            cell = ws.cell(row=row, column=i, value=h)
            cell.font = HEADER_FONT
            cell.fill = HEADER_FILL
            cell.alignment = HEADER_ALIGN
            cell.border = THIN_BORDER
        row += 1
        for ph in phases:
            counts = pdata.get(ph) or {}
            vals = [ph] + [counts.get(s, 0) for s in statuses]
            total = sum(int(counts.get(s, 0) or 0) for s in statuses)
            vals.append(total)
            for c, v in enumerate(vals, 1):
                cell = ws.cell(row=row, column=c, value=v)
                cell.font = BODY_FONT
                cell.border = THIN_BORDER
            # Highlight Closed ratio
            closed = int(counts.get("Closed", 0) or 0)
            if total > 0 and closed / total >= 0.8:
                ws.cell(row=row, column=1).fill = GREEN_FILL
            elif total > 0 and closed / total < 0.3:
                ws.cell(row=row, column=1).fill = YELLOW_FILL
            row += 1

    row += 1
    # --- 4. Module overview ---
    row = _block_title(ws, row, "4. MODULE OVERVIEW")
    modules = metrics.get("module_overview") or []
    mo_headers = ["STT", "Module", "Tổng CN", "Tiến độ %", "Phase active", "Overdue"]
    for i, h in enumerate(mo_headers, 1):
        cell = ws.cell(row=row, column=i, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER
    row += 1
    if not modules:
        ws.cell(row=row, column=1, value="N/A — chưa có module_overview.").font = NOTE_FONT
        row += 1
    else:
        for m in modules:
            vals = [
                m.get("stt", ""),
                m.get("module") or m.get("label") or "",
                m.get("total", 0),
                m.get("progress_pct", 0),
                m.get("active_phase", ""),
                m.get("overdue_count", 0),
            ]
            for c, v in enumerate(vals, 1):
                cell = ws.cell(row=row, column=c, value=v)
                cell.font = BODY_FONT
                cell.border = THIN_BORDER
            od = int(m.get("overdue_count") or 0)
            if od > 0:
                ws.cell(row=row, column=6).fill = ORANGE_FILL if od < 5 else RED_FILL
            row += 1

    row += 1
    # --- 5. PIC workload top ---
    row = _block_title(ws, row, "5. PIC WORKLOAD (top 25 theo tổng task)")
    pics = list(metrics.get("pic_workload") or [])[:25]
    pic_headers = ["STT", "PIC", "Tổng", "Closed", "In-progress", "Assigned", "Overdue"]
    for i, h in enumerate(pic_headers, 1):
        cell = ws.cell(row=row, column=i, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER
    row += 1
    if not pics:
        ws.cell(row=row, column=1, value="N/A — chưa có pic_workload.").font = NOTE_FONT
        row += 1
    else:
        for idx, p in enumerate(pics, 1):
            vals = [
                idx,
                p.get("pic", ""),
                p.get("total_tasks", 0),
                p.get("closed", 0),
                p.get("in_progress", 0),
                p.get("assigned", 0),
                p.get("overdue", 0),
            ]
            for c, v in enumerate(vals, 1):
                cell = ws.cell(row=row, column=c, value=v)
                cell.font = BODY_FONT
                cell.border = THIN_BORDER
            if int(p.get("overdue") or 0) > 0:
                ws.cell(row=row, column=7).fill = RED_FILL
            row += 1

    row += 2
    ws.cell(
        row=row, column=1,
        value=(
            "Không nhồi mọi chart dashboard — chỉ 5 block PM hay dùng. "
            "Chi tiết sâu: dùng Xuất vấn đề / Full Report / chart export riêng."
        ),
    )
    ws.cell(row=row, column=1).font = NOTE_FONT
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=8)

    ws.freeze_panes = "A4"


def export_weekly_mom(
    metrics: dict,
    output_dir: str = "uploads",
    *,
    project_code: str = "",
    parsed_data=None,
    today: Optional[date] = None,
) -> str:
    """
    Sinh workbook báo cáo tuần MoM (mẫu W30) + sheet PM Dashboard.

    Args:
        metrics: dict từ DashboardEngine.compute()
        output_dir: thư mục lưu file
        project_code: mã dự án (slug hoặc tên) — hiện trên Cover
        parsed_data: ParsedData optional — để gợi ý deadline trong tuần trên sheet MoM
        today: ngày báo cáo (test có thể cố định)

    Returns:
        Đường dẫn file .xlsx đã lưu.
    """
    today = today or date.today()
    week_label = _iso_week_label(today)
    meeting_sheet = f"MoM_{week_label}"
    code = (project_code or "").strip() or NA

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    _write_cover(wb, code, week_label, meeting_sheet, today)
    _write_master_plan(wb)
    _write_mom_sheet(wb, meeting_sheet, week_label, today, metrics, parsed_data)
    _write_pm_dashboard(wb, metrics, today, week_label)

    os.makedirs(output_dir, exist_ok=True)
    safe_code = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in code)[:40]
    filename = f"{safe_code}_MoM_{today.year}.{week_label}.xlsx"
    filepath = os.path.join(output_dir, filename)
    wb.save(filepath)
    wb.close()
    return filepath
