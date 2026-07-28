"""
Xuất báo cáo Excel:
- export_overdue_report: danh sách task trễ (single sheet)
- export_full_report:    báo cáo tổng hợp nhiều sheet (Overdue / Unassigned / Long Duration / Stalled / High Risk / Summary)
- export_by_pic:         báo cáo riêng cho 1 PIC
Format chuyên nghiệp, highlight theo mức trễ / risk score.
"""
import os
from datetime import date
from typing import Any, Optional

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


# === Styles chung ===
HEADER_FONT = Font(name="Arial", bold=True, color="FFFFFF", size=11)
HEADER_FILL = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)

BODY_FONT = Font(name="Arial", size=10)
BODY_ALIGN = Alignment(vertical="center", wrap_text=True)

RED_FILL = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")     # nặng
ORANGE_FILL = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")  # trung
YELLOW_FILL = PatternFill(start_color="FEF9C3", end_color="FEF9C3", fill_type="solid")  # nhẹ
GREEN_FILL = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")   # ok

THIN_BORDER = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)


def _write_sheet(
    ws,
    title: str,
    columns: list[tuple[str, int]],
    data_rows: list[list[Any]],
    row_fill_fn=None,
    subtitle: str = "",
) -> None:
    """
    Helper: viết 1 sheet chuẩn (title + subtitle + header + data + summary + auto-filter + freeze).

    Args:
        columns: list of (col_name, col_width)
        data_rows: list of value lists tương ứng columns
        row_fill_fn: optional callable(row_idx, item_index) -> PatternFill|None
    """
    n_cols = len(columns)
    last_col_letter = get_column_letter(n_cols)

    # Title
    ws.merge_cells(f"A1:{last_col_letter}1")
    tc = ws["A1"]
    tc.value = title
    tc.font = Font(name="Arial", bold=True, size=14, color="1F4E79")
    tc.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    # Subtitle
    ws.merge_cells(f"A2:{last_col_letter}2")
    sc = ws["A2"]
    sc.value = subtitle or f"Ngày xuất: {date.today().strftime('%d/%m/%Y')}"
    sc.font = Font(name="Arial", size=10, italic=True, color="666666")
    sc.alignment = Alignment(horizontal="center")

    # Header row (row 4)
    header_row = 4
    for col_idx, (col_name, col_width) in enumerate(columns, 1):
        cell = ws.cell(row=header_row, column=col_idx, value=col_name)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER
        ws.column_dimensions[get_column_letter(col_idx)].width = col_width
    ws.row_dimensions[header_row].height = 25

    # Data rows
    for row_offset, values in enumerate(data_rows):
        row_idx = header_row + 1 + row_offset
        fill = row_fill_fn(row_idx, row_offset) if row_fill_fn else None
        for col_idx, val in enumerate(values, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.font = BODY_FONT
            cell.alignment = BODY_ALIGN
            cell.border = THIN_BORDER
            if fill:
                cell.fill = fill

    # Summary
    summary_row = header_row + len(data_rows) + 2
    ws.merge_cells(f"A{summary_row}:{last_col_letter}{summary_row}")
    scell = ws.cell(row=summary_row, column=1)
    scell.value = f"Tổng: {len(data_rows)} record | Xuất ngày {date.today().strftime('%d/%m/%Y')}"
    scell.font = Font(name="Arial", bold=True, size=10, color="1F4E79")

    # Freeze + auto-filter
    ws.freeze_panes = f"A{header_row + 1}"
    if data_rows:
        ws.auto_filter.ref = f"A{header_row}:{last_col_letter}{header_row + len(data_rows)}"

COLUMNS = [
    ("STT", 6),
    ("Mã CN", 14),
    ("Tên chức năng", 40),
    ("Module", 10),
    ("Phase bị trễ", 16),
    ("Deadline", 13),
    ("Số ngày trễ", 12),
    ("Trạng thái", 13),
    ("PIC phụ trách", 20),
    ("Priority", 12),
    ("Ghi chú", 30),
]


def export_overdue_report(
    overdue_list: list[dict[str, Any]],
    output_dir: str = "uploads",
    filters: Optional[dict] = None,
) -> str:
    """
    Tạo file Excel chứa danh sách task trễ deadline.

    Args:
        overdue_list: Danh sách overdue items từ DashboardEngine
        output_dir: Thư mục lưu file output
        filters: Optional filter dict {"module": ..., "pic": ..., "phase": ...}

    Returns:
        Filepath of created .xlsx file
    """
    # Áp dụng filter nếu có
    items = overdue_list
    if filters:
        if filters.get("module"):
            items = [i for i in items if i.get("module") == filters["module"]]
        if filters.get("pic"):
            items = [i for i in items if filters["pic"] in i.get("pic", [])]
        if filters.get("phase"):
            items = [i for i in items if i.get("phase") == filters["phase"]]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Overdue_Report"

    # === Title row ===
    ws.merge_cells("A1:K1")
    title_cell = ws["A1"]
    title_cell.value = "BÁO CÁO TASK TRỄ DEADLINE"
    title_cell.font = Font(name="Arial", bold=True, size=14, color="1F4E79")
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 30

    # === Subtitle row ===
    ws.merge_cells("A2:K2")
    sub_cell = ws["A2"]
    filter_text = ""
    if filters:
        parts = []
        if filters.get("module"):
            parts.append(f"Module: {filters['module']}")
        if filters.get("pic"):
            parts.append(f"PIC: {filters['pic']}")
        if filters.get("phase"):
            parts.append(f"Phase: {filters['phase']}")
        filter_text = " | ".join(parts)
    sub_cell.value = f"Ngày xuất: {date.today().strftime('%d/%m/%Y')}" + (f"  |  Bộ lọc: {filter_text}" if filter_text else "")
    sub_cell.font = Font(name="Arial", size=10, italic=True, color="666666")
    sub_cell.alignment = Alignment(horizontal="center")

    # === Header row (row 4) ===
    header_row = 4
    for col_idx, (col_name, col_width) in enumerate(COLUMNS, 1):
        cell = ws.cell(row=header_row, column=col_idx, value=col_name)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER
        ws.column_dimensions[get_column_letter(col_idx)].width = col_width

    ws.row_dimensions[header_row].height = 25

    # === Data rows ===
    for row_offset, item in enumerate(items):
        row_idx = header_row + 1 + row_offset
        values = [
            row_offset + 1,
            item.get("ma_cn", ""),
            item.get("ten_cn", ""),
            item.get("module", ""),
            item.get("phase", ""),
            item.get("end_date", ""),
            item.get("days_overdue", 0),
            item.get("status", ""),
            ", ".join(item.get("pic", [])),
            item.get("priority", ""),
            item.get("note", ""),
        ]

        # Chọn fill theo mức trễ
        days = item.get("days_overdue", 0)
        if days > 7:
            row_fill = RED_FILL
        elif days > 3:
            row_fill = ORANGE_FILL
        elif days > 0:
            row_fill = YELLOW_FILL
        else:
            row_fill = None

        for col_idx, val in enumerate(values, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.font = BODY_FONT
            cell.alignment = BODY_ALIGN
            cell.border = THIN_BORDER
            if row_fill:
                cell.fill = row_fill

    # === Summary row ===
    summary_row = header_row + len(items) + 2
    ws.merge_cells(f"A{summary_row}:K{summary_row}")
    summary_cell = ws.cell(row=summary_row, column=1)
    summary_cell.value = f"Tổng: {len(items)} task trễ deadline | Báo cáo xuất ngày {date.today().strftime('%d/%m/%Y')}"
    summary_cell.font = Font(name="Arial", bold=True, size=10, color="1F4E79")

    # === Freeze panes ===
    ws.freeze_panes = f"A{header_row + 1}"

    # === Auto-filter ===
    last_col = get_column_letter(len(COLUMNS))
    last_row = header_row + len(items)
    ws.auto_filter.ref = f"A{header_row}:{last_col}{last_row}"

    # === Save ===
    os.makedirs(output_dir, exist_ok=True)
    filename = f"Overdue_Report_{date.today().strftime('%Y%m%d')}.xlsx"
    filepath = os.path.join(output_dir, filename)
    wb.save(filepath)
    wb.close()

    return filepath


# ======================================================================
# V2 EXPORTS
# ======================================================================


def _fill_by_days(days: int) -> Optional[PatternFill]:
    """Chọn màu highlight theo số ngày."""
    if days > 14:
        return RED_FILL
    if days > 7:
        return ORANGE_FILL
    if days > 0:
        return YELLOW_FILL
    return None


def _fill_by_risk(score: int) -> Optional[PatternFill]:
    if score >= 80:
        return RED_FILL
    if score >= 50:
        return ORANGE_FILL
    if score >= 30:
        return YELLOW_FILL
    return None


def export_full_report(
    metrics: dict,
    output_dir: str = "uploads",
) -> str:
    """
    Xuất báo cáo tổng hợp nhiều sheet:
    - Summary
    - Overdue_Report
    - Unassigned_Tasks
    - Long_Duration
    - Stalled_Tasks
    - High_Risk
    """
    wb = openpyxl.Workbook()
    # Xóa sheet default
    wb.remove(wb.active)

    summary = metrics.get("summary", {})
    overdue_list = metrics.get("overdue_list", [])
    unassigned = metrics.get("unassigned_tasks", [])
    duration_items = metrics.get("duration_analysis", {}).get("items", [])
    stalled_items = metrics.get("stalled_tasks", {}).get("items", [])
    risk_scores = metrics.get("risk_scores", [])
    # Rule V4: xuất ALL high-risk có score >= 30, KHÔNG cắt top 100 như trước
    high_risk = [r for r in risk_scores if r["risk_score"] >= 30]

    # === Sheet 1: Summary ===
    ws = wb.create_sheet("Summary")
    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 20

    ws.merge_cells("A1:B1")
    ws["A1"] = "BÁO CÁO TỔNG HỢP DỰ ÁN"
    ws["A1"].font = Font(name="Arial", bold=True, size=16, color="1F4E79")
    ws["A1"].alignment = Alignment(horizontal="center")
    ws.row_dimensions[1].height = 32

    ws.merge_cells("A2:B2")
    ws["A2"] = f"Ngày xuất: {date.today().strftime('%d/%m/%Y')}"
    ws["A2"].font = Font(name="Arial", italic=True, color="666666")
    ws["A2"].alignment = Alignment(horizontal="center")

    summary_rows = [
        ("Tổng số chức năng", summary.get("total_functions", 0)),
        ("Số Module", summary.get("modules_count", 0)),
        ("Số Phase", summary.get("phases_count", 0)),
        ("Tiến độ chung (%)", summary.get("overall_progress_pct", 0)),
        ("Task trễ deadline", summary.get("total_overdue", 0)),
        ("Task chưa có PIC", summary.get("unassigned_count", 0)),
        ("Function high-risk (>=50)", summary.get("high_risk_count", 0)),
    ]
    for idx, (label, value) in enumerate(summary_rows, start=4):
        ws.cell(row=idx, column=1, value=label).font = Font(name="Arial", bold=True, size=11)
        ws.cell(row=idx, column=1).border = THIN_BORDER
        c = ws.cell(row=idx, column=2, value=value)
        c.font = Font(name="Arial", size=11)
        c.alignment = Alignment(horizontal="right")
        c.border = THIN_BORDER

    # === Sheet 2: Overdue_Report ===
    ws = wb.create_sheet("Overdue_Report")
    columns = [
        ("STT", 6), ("Mã CN", 14), ("Tên chức năng", 40), ("Module", 10),
        ("Phase", 16), ("Deadline", 13), ("Số ngày trễ", 12),
        ("Trạng thái", 13), ("PIC", 20), ("Priority", 12), ("Ghi chú", 30),
    ]
    data_rows = [
        [
            idx + 1,
            i.get("ma_cn", ""), i.get("ten_cn", ""), i.get("module", ""),
            i.get("phase", ""), i.get("end_date", ""), i.get("days_overdue", 0),
            i.get("status", ""), ", ".join(i.get("pic", [])),
            i.get("priority", ""), i.get("note", ""),
        ]
        for idx, i in enumerate(overdue_list)
    ]
    _write_sheet(
        ws, "DANH SÁCH TASK TRỄ DEADLINE", columns, data_rows,
        row_fill_fn=lambda ri, idx: _fill_by_days(overdue_list[idx].get("days_overdue", 0)),
    )

    # === Sheet 3: Unassigned_Tasks ===
    ws = wb.create_sheet("Unassigned_Tasks")
    columns = [
        ("STT", 6), ("Mã CN", 14), ("Tên chức năng", 40), ("Module", 10),
        ("Phase", 16), ("Trạng thái", 13), ("Priority", 12), ("Complexity", 12),
        ("Deadline", 13), ("Trễ (ngày)", 12),
    ]
    data_rows = [
        [
            idx + 1,
            i.get("ma_cn", ""), i.get("ten_cn", ""), i.get("module", ""),
            i.get("phase", ""), i.get("status", ""),
            i.get("priority", ""), i.get("complexity", ""),
            i.get("end_date", ""), i.get("days_overdue", 0),
        ]
        for idx, i in enumerate(unassigned)
    ]

    def _unassigned_fill(ri: int, idx: int) -> Optional[PatternFill]:
        item = unassigned[idx]
        if item.get("is_overdue"):
            return RED_FILL
        if "Must" in (item.get("priority") or ""):
            return ORANGE_FILL
        return None

    _write_sheet(
        ws, "TASK CHƯA CÓ PIC PHỤ TRÁCH", columns, data_rows,
        row_fill_fn=_unassigned_fill,
    )

    # === Sheet 4: Long_Duration ===
    ws = wb.create_sheet("Long_Duration")
    columns = [
        ("STT", 6), ("Mã CN", 14), ("Tên chức năng", 40), ("Module", 10),
        ("Phase", 16), ("Start", 13), ("End", 13),
        ("Duration (ngày)", 14), ("Loại", 10), ("Status", 12),
        ("PIC", 20), ("Priority", 12), ("Estimate MH", 12),
    ]
    data_rows = [
        [
            idx + 1,
            i.get("ma_cn", ""), i.get("ten_cn", ""), i.get("module", ""),
            i.get("phase", ""), i.get("start_date", ""), i.get("end_date", ""),
            i.get("duration_days", 0),
            "Đang chạy" if i.get("duration_type") == "elapsed" else "Đã lên KH",
            i.get("status", ""),
            ", ".join(i.get("pic", [])),
            i.get("priority", ""), i.get("estimate_mh", ""),
        ]
        for idx, i in enumerate(duration_items)
    ]
    _write_sheet(
        ws, "TASK CÓ DURATION BẤT THƯỜNG", columns, data_rows,
        row_fill_fn=lambda ri, idx: _fill_by_days(duration_items[idx].get("duration_days", 0)),
    )

    # === Sheet 5: Stalled_Tasks ===
    ws = wb.create_sheet("Stalled_Tasks")
    columns = [
        ("STT", 6), ("Mã CN", 14), ("Tên chức năng", 40), ("Module", 10),
        ("Phase đã xong", 16), ("Phase chờ", 16), ("Xong ngày", 13),
        ("Chờ (ngày)", 12), ("Priority", 12),
    ]
    data_rows = [
        [
            idx + 1,
            i.get("ma_cn", ""), i.get("ten_cn", ""), i.get("module", ""),
            i.get("completed_phase", ""), i.get("waiting_phase", ""),
            i.get("completed_date", ""), i.get("wait_days", 0),
            i.get("priority", ""),
        ]
        for idx, i in enumerate(stalled_items)
    ]
    _write_sheet(
        ws, "TASK BỊ STALLED (KẸT GIỮA 2 PHASE)", columns, data_rows,
        row_fill_fn=lambda ri, idx: _fill_by_days(stalled_items[idx].get("wait_days", 0)),
    )

    # === Sheet 6: High_Risk ===
    ws = wb.create_sheet("High_Risk")
    columns = [
        ("STT", 6), ("Risk Score", 12), ("Mã CN", 14),
        ("Tên chức năng", 40), ("Module", 10),
        ("Priority", 12), ("Complexity", 12),
        ("Risk Factors", 45),
    ]
    data_rows = [
        [
            idx + 1, i.get("risk_score", 0),
            i.get("ma_cn", ""), i.get("ten_cn", ""), i.get("module", ""),
            i.get("priority", ""), i.get("complexity", ""),
            " | ".join(i.get("risk_factors", [])),
        ]
        for idx, i in enumerate(high_risk)
    ]
    _write_sheet(
        ws, "TOP FUNCTION CÓ ĐIỂM RỦI RO CAO", columns, data_rows,
        row_fill_fn=lambda ri, idx: _fill_by_risk(high_risk[idx].get("risk_score", 0)),
    )

    # === Save ===
    os.makedirs(output_dir, exist_ok=True)
    filename = f"Full_Report_{date.today().strftime('%Y%m%d')}.xlsx"
    filepath = os.path.join(output_dir, filename)
    wb.save(filepath)
    wb.close()
    return filepath


def export_by_pic(
    metrics: dict,
    pic_name: str,
    output_dir: str = "uploads",
) -> str:
    """
    Xuất Excel chứa toàn bộ task liên quan đến 1 PIC:
    - Sheet Overdue: task overdue của PIC này
    - Sheet Active: task đang In-progress / Assigned của PIC này
    - Sheet Effort: tổng MH gánh
    """
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    overdue_all = metrics.get("overdue_list", [])
    duration_all = metrics.get("duration_analysis", {}).get("items", [])
    effort = metrics.get("effort_analysis", {})

    my_overdue = [i for i in overdue_all if pic_name in i.get("pic", [])]
    my_active = [i for i in duration_all if pic_name in i.get("pic", [])]

    pic_effort = next(
        (p for p in effort.get("by_pic", []) if p.get("pic") == pic_name),
        {"total_mh": 0, "closed_mh": 0, "remaining_mh": 0},
    )

    # Sheet 1: Info + Effort
    ws = wb.create_sheet("Info")
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 20

    ws.merge_cells("A1:B1")
    ws["A1"] = f"BÁO CÁO CÔNG VIỆC — {pic_name}"
    ws["A1"].font = Font(name="Arial", bold=True, size=14, color="1F4E79")
    ws["A1"].alignment = Alignment(horizontal="center")
    ws.row_dimensions[1].height = 28

    ws.merge_cells("A2:B2")
    ws["A2"] = f"Ngày xuất: {date.today().strftime('%d/%m/%Y')}"
    ws["A2"].font = Font(name="Arial", italic=True, color="666666")
    ws["A2"].alignment = Alignment(horizontal="center")

    info_rows = [
        ("PIC", pic_name),
        ("Task trễ deadline", len(my_overdue)),
        ("Task đang chạy/kéo dài", len(my_active)),
        ("Tổng Estimate MH", pic_effort.get("total_mh", 0)),
        ("MH đã Closed", pic_effort.get("closed_mh", 0)),
        ("MH còn lại", pic_effort.get("remaining_mh", 0)),
    ]
    for idx, (label, value) in enumerate(info_rows, start=4):
        ws.cell(row=idx, column=1, value=label).font = Font(name="Arial", bold=True)
        ws.cell(row=idx, column=1).border = THIN_BORDER
        c = ws.cell(row=idx, column=2, value=value)
        c.alignment = Alignment(horizontal="right")
        c.border = THIN_BORDER

    # Sheet 2: Overdue
    ws = wb.create_sheet("Overdue")
    columns = [
        ("STT", 6), ("Mã CN", 14), ("Tên chức năng", 40), ("Module", 10),
        ("Phase", 16), ("Deadline", 13), ("Số ngày trễ", 12),
        ("Trạng thái", 13), ("Priority", 12), ("Ghi chú", 30),
    ]
    data_rows = [
        [
            idx + 1,
            i.get("ma_cn", ""), i.get("ten_cn", ""), i.get("module", ""),
            i.get("phase", ""), i.get("end_date", ""), i.get("days_overdue", 0),
            i.get("status", ""), i.get("priority", ""), i.get("note", ""),
        ]
        for idx, i in enumerate(my_overdue)
    ]
    _write_sheet(
        ws, f"TASK TRỄ CỦA {pic_name}", columns, data_rows,
        row_fill_fn=lambda ri, idx: _fill_by_days(my_overdue[idx].get("days_overdue", 0)),
    )

    # Sheet 3: Active (đang In-progress / kéo dài)
    ws = wb.create_sheet("Active")
    columns = [
        ("STT", 6), ("Mã CN", 14), ("Tên chức năng", 40), ("Module", 10),
        ("Phase", 16), ("Start", 13), ("End", 13),
        ("Duration (ngày)", 14), ("Status", 13), ("Priority", 12), ("Estimate MH", 12),
    ]
    data_rows = [
        [
            idx + 1,
            i.get("ma_cn", ""), i.get("ten_cn", ""), i.get("module", ""),
            i.get("phase", ""), i.get("start_date", ""), i.get("end_date", ""),
            i.get("duration_days", 0), i.get("status", ""),
            i.get("priority", ""), i.get("estimate_mh", ""),
        ]
        for idx, i in enumerate(my_active)
    ]
    _write_sheet(ws, f"TASK ĐANG THỰC HIỆN — {pic_name}", columns, data_rows)

    # Save
    os.makedirs(output_dir, exist_ok=True)
    safe_pic = "".join(c for c in pic_name if c.isalnum() or c in ("_", "-"))
    filename = f"PIC_{safe_pic}_{date.today().strftime('%Y%m%d')}.xlsx"
    filepath = os.path.join(output_dir, filename)
    wb.save(filepath)
    wb.close()
    return filepath


def export_compare_report(
    compare_result: dict,
    old_date: str,
    new_date: str,
    output_dir: str = "uploads",
) -> str:
    """
    Xuất báo cáo so sánh 2 snapshot:
    - Sheet Summary
    - Sheet New_Functions
    - Sheet Removed_Functions
    - Sheet Status_Changes
    - Sheet Module_Delta
    """
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    # === Sheet 1: Summary ===
    ws = wb.create_sheet("Summary")
    ws.column_dimensions["A"].width = 32
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 18
    ws.column_dimensions["D"].width = 18

    ws.merge_cells("A1:D1")
    ws["A1"] = f"BÁO CÁO SO SÁNH: {old_date} → {new_date}"
    ws["A1"].font = Font(name="Arial", bold=True, size=14, color="1F4E79")
    ws["A1"].alignment = Alignment(horizontal="center")
    ws.row_dimensions[1].height = 30

    # Header
    headers = ["Chỉ tiêu", "Trước", "Sau", "Chênh lệch"]
    for i, h in enumerate(headers, 1):
        c = ws.cell(row=3, column=i, value=h)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
        c.alignment = HEADER_ALIGN
        c.border = THIN_BORDER

    rows = [
        ("Tổng chức năng",       compare_result.get("old_total"),        compare_result.get("new_total"),        compare_result.get("delta_total")),
        ("Tiến độ chung (%)",    compare_result.get("old_overall_pct"),  compare_result.get("new_overall_pct"),  compare_result.get("delta_pct")),
        ("Task trễ deadline",    compare_result.get("old_overdue"),      compare_result.get("new_overdue"),      compare_result.get("delta_overdue")),
    ]
    for idx, r in enumerate(rows, start=4):
        for cidx, val in enumerate(r, 1):
            c = ws.cell(row=idx, column=cidx, value=val)
            c.font = BODY_FONT
            c.border = THIN_BORDER
            c.alignment = Alignment(horizontal="center" if cidx > 1 else "left")

    # Velocity
    velocity = compare_result.get("velocity", {})
    ws.merge_cells(f"A{len(rows) + 6}:D{len(rows) + 6}")
    ws.cell(row=len(rows) + 6, column=1, value="VELOCITY").font = Font(name="Arial", bold=True, size=12, color="1F4E79")

    vrow = len(rows) + 7
    velocity_rows = [
        ("Số ngày giữa 2 snapshot", velocity.get("days_between")),
        ("Số function đã Closed",    velocity.get("functions_closed")),
        ("Tốc độ close (func/ngày)", velocity.get("close_rate_per_day")),
        ("Ước lượng ngày còn lại",   velocity.get("est_days_remaining")),
        ("Function mới phát sinh",   velocity.get("functions_new")),
    ]
    for label, val in velocity_rows:
        ws.cell(row=vrow, column=1, value=label).font = Font(name="Arial", bold=True)
        ws.cell(row=vrow, column=1).border = THIN_BORDER
        c = ws.cell(row=vrow, column=2, value=val)
        c.alignment = Alignment(horizontal="right")
        c.border = THIN_BORDER
        vrow += 1

    # === Sheet 2: New Functions ===
    ws = wb.create_sheet("New_Functions")
    columns = [
        ("STT", 6), ("Mã CN", 14), ("Tên chức năng", 40),
        ("Module", 10), ("Priority", 12),
    ]
    new_fns = compare_result.get("new_functions", [])
    data_rows = [
        [idx + 1, f.get("ma_cn", ""), f.get("ten_cn", ""), f.get("module", ""), f.get("priority", "")]
        for idx, f in enumerate(new_fns)
    ]
    _write_sheet(ws, "FUNCTIONS MỚI PHÁT SINH", columns, data_rows,
                 row_fill_fn=lambda ri, idx: ORANGE_FILL)

    # === Sheet 3: Removed ===
    ws = wb.create_sheet("Removed_Functions")
    columns = [
        ("STT", 6), ("Mã CN", 14), ("Tên chức năng", 40),
        ("Module", 10), ("Priority", 12),
    ]
    removed = compare_result.get("removed_functions", [])
    data_rows = [
        [idx + 1, f.get("ma_cn", ""), f.get("ten_cn", ""), f.get("module", ""), f.get("priority", "")]
        for idx, f in enumerate(removed)
    ]
    _write_sheet(ws, "FUNCTIONS BỊ XÓA", columns, data_rows)

    # === Sheet 4: Status Changes ===
    ws = wb.create_sheet("Status_Changes")
    columns = [
        ("STT", 6), ("Mã CN", 14), ("Tên chức năng", 40), ("Module", 10),
        ("Phase", 16), ("Status cũ", 13), ("Status mới", 13), ("Hướng", 10),
    ]
    changes = compare_result.get("status_changes", [])
    data_rows = [
        [
            idx + 1, c.get("ma_cn", ""), c.get("ten_cn", ""), c.get("module", ""),
            c.get("phase", ""), c.get("old_status", ""), c.get("new_status", ""),
            c.get("direction", ""),
        ]
        for idx, c in enumerate(changes)
    ]

    def _fill_by_direction(ri: int, idx: int) -> Optional[PatternFill]:
        d = changes[idx].get("direction", "")
        if d == "forward":
            return GREEN_FILL
        if d == "backward":
            return RED_FILL
        return None

    _write_sheet(ws, "THAY ĐỔI TRẠNG THÁI", columns, data_rows,
                 row_fill_fn=_fill_by_direction)

    # === Sheet 5: Module Delta ===
    ws = wb.create_sheet("Module_Delta")
    columns = [
        ("Module", 12), ("% Trước", 12), ("% Sau", 12),
        ("Chênh lệch", 12), ("Closed mới", 12), ("Function mới", 12),
    ]
    module_deltas = compare_result.get("module_deltas", {})
    data_rows = [
        [
            m,
            d.get("old_pct"), d.get("new_pct"),
            d.get("delta_pct"), d.get("closed_count"),
            d.get("new_count"),
        ]
        for m, d in module_deltas.items()
    ]
    _write_sheet(ws, "CHÊNH LỆCH TIẾN ĐỘ THEO MODULE", columns, data_rows)

    # === Save ===
    os.makedirs(output_dir, exist_ok=True)
    filename = f"Compare_{old_date}_vs_{new_date}.xlsx"
    filepath = os.path.join(output_dir, filename)
    wb.save(filepath)
    wb.close()
    return filepath


# ==========================================================================
# Drill-Down Export — Xuất Excel từ modal chi tiết biểu đồ
# ==========================================================================

DRILL_COLUMNS = [
    ("STT", 6),
    ("Mã CN", 14),
    ("Tên chức năng", 42),
    ("Module", 10),
    ("Quy trình", 22),
    ("Giai đoạn", 10),
    ("Phase", 14),
    ("Status", 13),
    ("PIC", 22),
    ("Start", 12),
    ("End", 12),
    ("Ngày trễ", 10),
    ("Priority", 12),
    ("Complexity", 12),
    ("FIT/GAP", 10),
    ("Estimate MH", 12),
]


def _drill_row_fill(row_idx: int, row_offset: int, items: list[dict]):
    """Row fill: overdue → RED, closed → GREEN, in-progress → YELLOW."""
    if row_offset >= len(items):
        return None
    item = items[row_offset]
    if item.get("is_overdue"):
        return RED_FILL
    status = (item.get("status") or "").lower()
    if status == "closed":
        return GREEN_FILL
    if status in ("in-progress", "assigned"):
        return YELLOW_FILL
    return None


def export_drill_down(
    items: list[dict[str, Any]],
    title: str = "Chi tiết biểu đồ",
    subtitle: str = "",
    output_dir: str = "uploads",
) -> str:
    """
    Xuất Excel danh sách function chi tiết từ drill-down (click biểu đồ).

    Args:
        items: List function dict theo format của `analyzer.drill_down.drill_down`
        title: Tiêu đề chính (VD: "Priority: Must-have")
        subtitle: Dòng subtitle (VD: "Tổng 292 function")
        output_dir: Thư mục lưu file

    Returns:
        Filepath của file .xlsx đã tạo.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Chi_Tiet"

    data_rows = []
    for idx, it in enumerate(items):
        pics = it.get("pics", []) or []
        pic_str = ", ".join(pics) if isinstance(pics, list) else str(pics)
        data_rows.append([
            idx + 1,
            it.get("ma_cn", ""),
            it.get("ten_cn", ""),
            it.get("module", ""),
            it.get("quy_trinh", ""),
            it.get("giai_doan", ""),
            it.get("phase", ""),
            it.get("status", ""),
            pic_str,
            it.get("start_date", ""),
            it.get("end_date", ""),
            it.get("days_overdue", 0) or "",
            it.get("priority", ""),
            it.get("complexity", ""),
            it.get("fit_gap", ""),
            it.get("estimate_mh", "") or "",
        ])

    _write_sheet(
        ws,
        title=f"CHI TIẾT — {title}",
        columns=DRILL_COLUMNS,
        data_rows=data_rows,
        subtitle=subtitle or f"Tổng: {len(items)} function | Ngày xuất: {date.today().strftime('%d/%m/%Y')}",
        row_fill_fn=lambda r, o: _drill_row_fill(r, o, items),
    )

    os.makedirs(output_dir, exist_ok=True)
    safe_title = "".join(c if c.isalnum() or c in "._- " else "_" for c in title).strip()[:60]
    filename = f"DrillDown_{safe_title}_{date.today().strftime('%Y%m%d')}.xlsx"
    filepath = os.path.join(output_dir, filename)
    wb.save(filepath)
    wb.close()
    return filepath


# ======================================================================
# PIC BLACKLIST — data-quality report
# ======================================================================

# Columns cho báo cáo PIC bị blacklist khỏi parser.
# Thứ tự đặt để user dễ tra Excel: Row → Header → giá trị → keyword match → context.
BLACKLIST_COLUMNS: list[tuple[str, int]] = [
    ("STT", 6),
    ("Row Excel", 10),
    ("Mã CN", 16),
    ("Module", 10),
    ("Phase", 14),
    ("Cột (header text)", 26),
    ("Giá trị bị bỏ", 20),
    ("Keyword khớp", 14),
    ("Ghi chú", 40),
]


# ======================================================================
# PORTFOLIO COMPARE — Cross-project side-by-side compare export
# ======================================================================

def export_portfolio_compare(
    compare_result: dict,
    output_dir: str = "uploads",
) -> str:
    """
    Xuất bảng so sánh N project (từ `analyzer.portfolio.compare_projects`) ra
    Excel. Layout:
    - Cột 1: tên metric
    - Cột 2..N+1: value cho từng project (đặt tên = slug + name)
    - Highlight: cell best = xanh nhạt, worst = đỏ nhạt (theo `best_worst`)

    Args:
        compare_result: dict trả về từ compare_projects — có keys:
            projects, metrics, metric_labels, best_worst, skipped
        output_dir: folder lưu

    Returns:
        Filepath .xlsx đã tạo.
    """
    projects = compare_result.get("projects", []) or []
    metrics = compare_result.get("metrics", {}) or {}
    metric_labels = compare_result.get("metric_labels", []) or []
    best_worst = compare_result.get("best_worst", {}) or {}
    skipped = compare_result.get("skipped", []) or []

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Portfolio_Compare"

    n_projects = len(projects)
    n_cols = 1 + n_projects  # 1 col metric + N col project

    # === Title (merge cả row) ===
    last_col_letter = get_column_letter(n_cols)
    ws.merge_cells(f"A1:{last_col_letter}1")
    tc = ws["A1"]
    tc.value = "BÁO CÁO SO SÁNH DỰ ÁN (PORTFOLIO)"
    tc.font = Font(name="Arial", bold=True, size=14, color="1F4E79")
    tc.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    # === Subtitle ===
    ws.merge_cells(f"A2:{last_col_letter}2")
    sc = ws["A2"]
    subtitle_parts = [f"Ngày xuất: {date.today().strftime('%d/%m/%Y')}"]
    subtitle_parts.append(f"So sánh {n_projects} dự án")
    if skipped:
        subtitle_parts.append(f"Bỏ qua {len(skipped)} dự án (chưa upload file)")
    sc.value = " | ".join(subtitle_parts)
    sc.font = Font(name="Arial", size=10, italic=True, color="666666")
    sc.alignment = Alignment(horizontal="center")

    # === Header row (row 4) ===
    header_row = 4
    ws.cell(row=header_row, column=1, value="Chỉ tiêu")
    for col_idx in range(1, n_cols + 1):
        cell = ws.cell(row=header_row, column=col_idx)
        if col_idx == 1:
            pass  # đã set value ở trên
        else:
            proj = projects[col_idx - 2]
            cell.value = proj.get("name") or proj.get("slug", "")
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER

    # Width cột
    ws.column_dimensions["A"].width = 24
    for col_idx in range(2, n_cols + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = 20
    ws.row_dimensions[header_row].height = 30

    # === Data rows: mỗi metric 1 row ===
    for row_offset, ml in enumerate(metric_labels):
        row_idx = header_row + 1 + row_offset
        key = ml["key"]
        label = ml["label"]

        # Col 1: metric label
        c = ws.cell(row=row_idx, column=1, value=label)
        c.font = Font(name="Arial", bold=True, size=10)
        c.alignment = BODY_ALIGN
        c.border = THIN_BORDER

        # Col 2..N: value + highlight best/worst
        bw = best_worst.get(key, {})
        best_slug = bw.get("best")
        worst_slug = bw.get("worst")
        for col_idx, proj in enumerate(projects, 2):
            slug = proj["slug"]
            val = metrics.get(key, {}).get(slug, "")
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.font = BODY_FONT
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = THIN_BORDER
            if best_slug == slug:
                cell.fill = GREEN_FILL
            elif worst_slug == slug:
                cell.fill = RED_FILL

    # === Skipped section (nếu có) ===
    if skipped:
        skip_row = header_row + len(metric_labels) + 2
        ws.merge_cells(f"A{skip_row}:{last_col_letter}{skip_row}")
        sk_cell = ws.cell(row=skip_row, column=1)
        sk_cell.value = "DỰ ÁN BỊ BỎ QUA:"
        sk_cell.font = Font(name="Arial", bold=True, color="B45309")
        for i, sk in enumerate(skipped, 1):
            r = skip_row + i
            ws.cell(row=r, column=1, value=f"  • {sk.get('slug', '')}").font = BODY_FONT
            ws.cell(row=r, column=2, value=f"Lý do: {sk.get('reason', '')}").font = BODY_FONT

    # === Freeze + auto-filter ===
    ws.freeze_panes = f"B{header_row + 1}"

    os.makedirs(output_dir, exist_ok=True)
    filename = f"Portfolio_Compare_{date.today().strftime('%Y%m%d')}.xlsx"
    filepath = os.path.join(output_dir, filename)
    wb.save(filepath)
    wb.close()
    return filepath


def export_pic_blacklist_report(
    items: list[dict[str, Any]],
    output_dir: str = "uploads",
    subtitle: str = "",
) -> str:
    """
    Xuất báo cáo Excel danh sách PIC bị blacklist khi parse Function List.

    Đây là báo cáo "chất lượng dữ liệu" — mỗi hàng = 1 token PIC bị parser bỏ
    do trùng tên với 1 status hợp lệ (dấu hiệu cột Status bị lệch qua cột PIC).

    Args:
        items: list dict {row_index, phase_name, header_text, raw_value,
                          matched_keyword, ma_cn, module}
        output_dir: thư mục lưu file
        subtitle: dòng subtitle tùy chọn

    Returns:
        Filepath .xlsx đã tạo.
    """
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "PIC_Blacklist"

    data_rows = []
    for idx, it in enumerate(items):
        data_rows.append([
            idx + 1,
            it.get("row_index", ""),
            it.get("ma_cn", ""),
            it.get("module", ""),
            it.get("phase_name", ""),
            it.get("header_text", ""),
            it.get("raw_value", ""),
            it.get("matched_keyword", ""),
            # Ghi chú: hướng dẫn user tra Excel gốc
            f'Kiểm tra ô cột "{it.get("header_text", "")}" row {it.get("row_index", "?")} — '
            f'có thể user paste lệch cột Status sang PIC.',
        ])

    _write_sheet(
        ws,
        title="BÁO CÁO PIC BỊ BLACKLIST (Data Quality)",
        columns=BLACKLIST_COLUMNS,
        data_rows=data_rows,
        subtitle=subtitle or (
            f"Tổng: {len(items)} token PIC bị parser bỏ do trùng status keyword "
            f"| Ngày xuất: {date.today().strftime('%d/%m/%Y')}"
        ),
        # Highlight vàng nhẹ toàn bảng — đây là warning (không phải error đỏ)
        row_fill_fn=lambda r, o: YELLOW_FILL,
    )

    os.makedirs(output_dir, exist_ok=True)
    filename = f"PIC_Blacklist_{date.today().strftime('%Y%m%d')}.xlsx"
    filepath = os.path.join(output_dir, filename)
    wb.save(filepath)
    wb.close()
    return filepath


# ==========================================================================
# Export chart đơn lẻ + Audit Report
# ==========================================================================

SUPPORTED_EXPORT_CHARTS = {
    "effort_heatmap",
    "effort_pic",
    "module_overview",
    "phase_matrix",
    "phase_stacked",
    "overdue",
    "pic_workload",
    "risk",
    "stalled",
    "unassigned",
    "task_type",
    "priority",
    "complexity",
    "fit_gap",
    "giai_doan",
    "process",
    "duration",
}


def export_chart(
    chart: str,
    metrics: dict[str, Any],
    output_dir: str = "uploads",
    subtitle: str = "",
) -> str:
    """
    Xuất 1 sheet Excel cho chart cụ thể từ metrics đã compute.

    chart: xem SUPPORTED_EXPORT_CHARTS
    """
    if chart not in SUPPORTED_EXPORT_CHARTS:
        raise ValueError(f"Chart không hỗ trợ: {chart}. Hỗ trợ: {sorted(SUPPORTED_EXPORT_CHARTS)}")

    wb = openpyxl.Workbook()
    ws = wb.active
    sub = subtitle or f"Ngày xuất: {date.today().strftime('%d/%m/%Y')}"

    if chart == "effort_heatmap":
        ws.title = "Effort_Heatmap"
        e = metrics.get("effort_analysis") or {}
        modules = e.get("modules") or []
        phases = e.get("phases") or []
        heatmap = e.get("heatmap") or {}
        columns = [("Module", 14)] + [(p, 12) for p in phases] + [("Tổng MH", 12)]
        data_rows = []
        for m in modules:
            row_vals = [m]
            total = 0.0
            for p in phases:
                v = float((heatmap.get(m) or {}).get(p) or 0)
                row_vals.append(v if v else "")
                total += v
            row_vals.append(round(total, 1))
            data_rows.append(row_vals)
        _write_sheet(ws, "EFFORT HEATMAP — Module × Phase (MH)", columns, data_rows, subtitle=sub)

    elif chart == "effort_pic":
        ws.title = "Effort_PIC"
        e = metrics.get("effort_analysis") or {}
        # Sheet 1: by_pic bar data
        columns = [
            ("STT", 6), ("PIC", 20), ("Total MH", 12),
            ("Closed MH", 12), ("Remaining MH", 12),
        ]
        by_pic = e.get("by_pic") or []
        data_rows = [
            [idx + 1, p.get("pic", ""), p.get("total_mh", 0),
             p.get("closed_mh", 0), p.get("remaining_mh", 0)]
            for idx, p in enumerate(by_pic)
        ]
        _write_sheet(ws, "EFFORT THEO PIC", columns, data_rows, subtitle=sub)

        # Sheet 2: open tasks (chưa Closed/Cancelled)
        ws2 = wb.create_sheet("Open_Tasks")
        open_tasks = e.get("open_tasks_by_pic") or []
        columns2 = [
            ("STT", 6), ("Mã CN", 14), ("Tên chức năng", 40), ("Module", 10),
            ("Phase", 16), ("PIC", 24), ("Status", 12),
            ("End date", 13), ("Estimate MH", 12),
        ]
        data_rows2 = [
            [
                idx + 1,
                t.get("ma_cn", ""), t.get("ten_cn", ""), t.get("module", ""),
                t.get("phase", ""),
                ", ".join(t.get("pic") or []) if isinstance(t.get("pic"), list) else (t.get("pic") or ""),
                t.get("status", ""), t.get("end_date", ""), t.get("estimate_mh", ""),
            ]
            for idx, t in enumerate(open_tasks)
        ]
        _write_sheet(
            ws2, "TASK CHƯA DONE CÓ ESTIMATE MH", columns2, data_rows2, subtitle=sub
        )

    elif chart == "module_overview":
        ws.title = "Module_Overview"
        items = metrics.get("module_overview") or []
        columns = [
            ("STT", 6), ("Module", 12), ("Số CN", 10), ("Số QT", 10),
            ("% Progress", 12), ("Phase active", 18), ("Overdue", 10),
        ]
        data_rows = [
            [
                i.get("stt", idx + 1), i.get("module", ""), i.get("total", 0),
                i.get("quy_trinh_count", 0), i.get("progress_pct", 0),
                i.get("active_phase", ""), i.get("overdue_count", 0),
            ]
            for idx, i in enumerate(items)
        ]
        _write_sheet(ws, "TỔNG QUAN THEO MODULE", columns, data_rows, subtitle=sub)

    elif chart == "phase_matrix":
        ws.title = "Phase_Matrix"
        mx = metrics.get("phase_status_matrix") or {}
        phases = mx.get("phases") or []
        modules = mx.get("modules") or []
        data = mx.get("data") or {}
        columns = [("Module", 12)] + [(f"{p} %Closed", 12) for p in phases]
        data_rows = []
        for m in modules:
            row = [m]
            for p in phases:
                cell = (data.get(m) or {}).get(p) or {}
                row.append(cell.get("pct_closed", 0) if isinstance(cell, dict) else cell)
            data_rows.append(row)
        _write_sheet(ws, "PHASE × MODULE (% Closed)", columns, data_rows, subtitle=sub)

    elif chart == "phase_stacked":
        ws.title = "Phase_Stacked"
        d = metrics.get("phase_progress_stacked") or {}
        phases = d.get("phases") or []
        statuses = d.get("statuses") or []
        data = d.get("data") or {}
        columns = [("Phase", 16)] + [(s, 12) for s in statuses]
        data_rows = []
        for ph in phases:
            row = [ph]
            for s in statuses:
                row.append((data.get(ph) or {}).get(s, 0))
            data_rows.append(row)
        _write_sheet(ws, "TIẾN ĐỘ THEO PHASE (Status count)", columns, data_rows, subtitle=sub)

    elif chart == "task_type":
        ws.title = "Task_Type"
        d = metrics.get("progress_by_task_type") or {}
        task_types = d.get("task_types") or []
        by_module = d.get("by_module") or {}
        modules = list(by_module.keys())
        columns = [("Module", 12)] + [(tt, 14) for tt in task_types]
        data_rows = []
        for m in modules:
            row = [m]
            for tt in task_types:
                row.append((by_module.get(m) or {}).get(tt, 0))
            data_rows.append(row)
        _write_sheet(ws, "TIẾN ĐỘ THEO CÔNG VIỆC (% Closed)", columns, data_rows, subtitle=sub)

    elif chart == "priority":
        ws.title = "Priority"
        # priority_breakdown: dict {priority: count}
        d = metrics.get("priority_breakdown") or {}
        columns = [("STT", 6), ("Priority", 20), ("Số lượng", 12)]
        data_rows = [
            [idx + 1, k, v]
            for idx, (k, v) in enumerate(sorted(d.items(), key=lambda x: -x[1]))
        ]
        _write_sheet(ws, "PHÂN BỐ PRIORITY", columns, data_rows, subtitle=sub)

    elif chart == "complexity":
        ws.title = "Complexity"
        d = metrics.get("complexity_breakdown") or {}
        columns = [("STT", 6), ("Complexity", 20), ("Số lượng", 12)]
        data_rows = [
            [idx + 1, k, v]
            for idx, (k, v) in enumerate(sorted(d.items(), key=lambda x: -x[1]))
        ]
        _write_sheet(ws, "PHÂN BỐ COMPLEXITY", columns, data_rows, subtitle=sub)

    elif chart == "fit_gap":
        ws.title = "FIT_GAP"
        # fit_gap_analysis: {module: {FIT: n, GAP: n, ...}}
        d = metrics.get("fit_gap_analysis") or {}
        modules = list(d.keys())
        keys: set[str] = set()
        for m in modules:
            keys.update((d.get(m) or {}).keys())
        keys_sorted = sorted(keys)
        columns = [("Module", 12)] + [(k, 10) for k in keys_sorted]
        data_rows = []
        for m in modules:
            row = [m]
            for k in keys_sorted:
                row.append((d.get(m) or {}).get(k, 0))
            data_rows.append(row)
        _write_sheet(ws, "FIT / GAP THEO MODULE", columns, data_rows, subtitle=sub)

    elif chart == "giai_doan":
        ws.title = "Giai_Doan"
        # giai_doan_progress: {gd: {phase: {total, closed, pct}}}
        d = metrics.get("giai_doan_progress") or {}
        giai_doans = list(d.keys())
        phases: list[str] = []
        for gd in giai_doans:
            for p in (d.get(gd) or {}).keys():
                if p not in phases:
                    phases.append(p)
        columns = [("Giai đoạn", 14)] + [(f"{p} %Closed", 12) for p in phases]
        data_rows = []
        for gd in giai_doans:
            row = [gd]
            cell = d.get(gd) or {}
            for p in phases:
                val = cell.get(p, 0)
                if isinstance(val, dict):
                    val = val.get("pct", val.get("pct_closed", 0))
                row.append(val)
            data_rows.append(row)
        _write_sheet(ws, "TIẾN ĐỘ THEO GIAI ĐOẠN (% Closed)", columns, data_rows, subtitle=sub)

    elif chart == "process":
        ws.title = "Process"
        items = metrics.get("process_analysis") or []
        columns = [
            ("STT", 6), ("Quy trình", 40), ("Số CN", 10), ("% Closed", 12),
            ("Overdue", 10), ("Modules", 24),
        ]
        data_rows = [
            [
                idx + 1, i.get("process", ""), i.get("total", 0),
                i.get("pct_closed", 0), i.get("overdue", 0),
                ", ".join(i.get("modules") or []),
            ]
            for idx, i in enumerate(items)
        ]
        _write_sheet(ws, "PHÂN TÍCH THEO QUY TRÌNH", columns, data_rows, subtitle=sub)

    elif chart == "duration":
        ws.title = "Duration"
        d = metrics.get("duration_analysis") or {}
        items = d.get("items") or []
        columns = [
            ("STT", 6), ("Mã CN", 14), ("Tên chức năng", 40), ("Module", 10),
            ("Phase", 16), ("Start", 13), ("End", 13),
            ("Duration (ngày)", 14), ("Loại", 12), ("Status", 12), ("PIC", 20),
        ]
        data_rows = [
            [
                idx + 1, i.get("ma_cn", ""), i.get("ten_cn", ""), i.get("module", ""),
                i.get("phase", ""), i.get("start_date", ""), i.get("end_date", ""),
                i.get("duration_days", 0),
                "Elapsed" if i.get("duration_type") == "elapsed" else "Planned",
                i.get("status", ""),
                ", ".join(i.get("pic") or []) if isinstance(i.get("pic"), list) else (i.get("pic") or ""),
            ]
            for idx, i in enumerate(items)
        ]
        _write_sheet(ws, "TASK DURATION BẤT THƯỜNG", columns, data_rows, subtitle=sub)

    elif chart == "overdue":
        ws.title = "Overdue"
        items = metrics.get("overdue_list") or []
        columns = [
            ("STT", 6), ("Mã CN", 14), ("Tên chức năng", 40), ("Module", 10),
            ("Phase", 16), ("Deadline", 13), ("Số ngày trễ", 12),
            ("Status", 12), ("PIC", 20), ("Priority", 12),
        ]
        data_rows = [
            [
                idx + 1, i.get("ma_cn", ""), i.get("ten_cn", ""), i.get("module", ""),
                i.get("phase", ""), i.get("end_date", ""), i.get("days_overdue", 0),
                i.get("status", ""),
                ", ".join(i.get("pic") or []) if isinstance(i.get("pic"), list) else "",
                i.get("priority", ""),
            ]
            for idx, i in enumerate(items)
        ]
        _write_sheet(
            ws, "TASK TRỄ DEADLINE", columns, data_rows, subtitle=sub,
            row_fill_fn=lambda ri, idx: _fill_by_days(items[idx].get("days_overdue", 0)),
        )

    elif chart == "pic_workload":
        ws.title = "PIC_Workload"
        items = metrics.get("pic_workload") or []
        columns = [
            ("STT", 6), ("PIC", 20), ("Total tasks", 12), ("Closed", 10),
            ("In-progress", 12), ("Overdue", 10), ("Unassigned share", 14),
        ]
        data_rows = []
        for idx, i in enumerate(items):
            # pic_workload có thể có field khác nhau — lấy linh hoạt
            data_rows.append([
                idx + 1,
                i.get("pic", ""),
                i.get("total_tasks", i.get("total", 0)),
                i.get("closed", i.get("closed_count", "")),
                i.get("in_progress", i.get("inprogress", "")),
                i.get("overdue", i.get("overdue_count", "")),
                i.get("unassigned", ""),
            ])
        _write_sheet(ws, "WORKLOAD THEO PIC", columns, data_rows, subtitle=sub)

    elif chart == "risk":
        ws.title = "High_Risk"
        # Rule V4: xuất ALL high-risk items (score >= 30), không cắt top 100
        items = [r for r in (metrics.get("risk_scores") or []) if (r.get("risk_score") or 0) >= 30]
        columns = [
            ("STT", 6), ("Risk Score", 12), ("Mã CN", 14), ("Tên chức năng", 40),
            ("Module", 10), ("Priority", 12), ("Complexity", 12), ("Risk Factors", 45),
        ]
        data_rows = [
            [
                idx + 1, i.get("risk_score", 0), i.get("ma_cn", ""), i.get("ten_cn", ""),
                i.get("module", ""), i.get("priority", ""), i.get("complexity", ""),
                " | ".join(i.get("risk_factors") or []),
            ]
            for idx, i in enumerate(items)
        ]
        _write_sheet(
            ws, "FUNCTION RỦI RO CAO", columns, data_rows, subtitle=sub,
            row_fill_fn=lambda ri, idx: _fill_by_risk(items[idx].get("risk_score", 0)),
        )

    elif chart == "stalled":
        ws.title = "Stalled"
        items = (metrics.get("stalled_tasks") or {}).get("items") or []
        columns = [
            ("STT", 6), ("Mã CN", 14), ("Tên chức năng", 40), ("Module", 10),
            ("Phase đã xong", 16), ("Phase chờ", 16), ("Xong ngày", 13),
            ("Chờ (ngày)", 12), ("Priority", 12),
        ]
        data_rows = [
            [
                idx + 1, i.get("ma_cn", ""), i.get("ten_cn", ""), i.get("module", ""),
                i.get("completed_phase", ""), i.get("waiting_phase", ""),
                i.get("completed_date", ""), i.get("wait_days", 0), i.get("priority", ""),
            ]
            for idx, i in enumerate(items)
        ]
        _write_sheet(ws, "TASK BỊ STALLED", columns, data_rows, subtitle=sub)

    elif chart == "unassigned":
        ws.title = "Unassigned"
        items = metrics.get("unassigned_tasks") or []
        columns = [
            ("STT", 6), ("Mã CN", 14), ("Tên chức năng", 40), ("Module", 10),
            ("Phase", 16), ("Status", 12), ("Priority", 12),
            ("Deadline", 13), ("Trễ (ngày)", 12),
        ]
        data_rows = [
            [
                idx + 1, i.get("ma_cn", ""), i.get("ten_cn", ""), i.get("module", ""),
                i.get("phase", ""), i.get("status", ""), i.get("priority", ""),
                i.get("end_date", ""), i.get("days_overdue", 0),
            ]
            for idx, i in enumerate(items)
        ]
        _write_sheet(ws, "TASK CHƯA CÓ PIC", columns, data_rows, subtitle=sub)

    os.makedirs(output_dir, exist_ok=True)
    filename = f"Chart_{chart}_{date.today().strftime('%Y%m%d')}.xlsx"
    filepath = os.path.join(output_dir, filename)
    wb.save(filepath)
    wb.close()
    return filepath


def export_audit_report(
    parsed,
    metrics: dict[str, Any],
    output_dir: str = "uploads",
    subtitle: str = "",
) -> str:
    """
    Xuất Report Đánh giá 11 sheet từ ParsedData + metrics.

    Returns filepath .xlsx.
    """
    from analyzer.audit_report import build_audit_issues, AUDIT_SHEET_NAMES

    issues = build_audit_issues(parsed, metrics)
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    sub = subtitle or f"Ngày xuất: {date.today().strftime('%d/%m/%Y')}"

    # 01 Summary
    ws = wb.create_sheet(AUDIT_SHEET_NAMES[0])
    ws.column_dimensions["A"].width = 36
    ws.column_dimensions["B"].width = 18
    ws["A1"] = "REPORT ĐÁNH GIÁ CHẤT LƯỢNG DỮ LIỆU"
    ws["A1"].font = Font(name="Arial", bold=True, size=14, color="1F4E79")
    ws.merge_cells("A1:B1")
    ws["A2"] = sub
    ws["A2"].font = Font(name="Arial", italic=True, color="666666")
    summary = issues["summary"]
    labels = [
        ("Tổng chức năng", "total_functions"),
        ("Số Module", "modules_count"),
        ("Số Phase", "phases_count"),
        ("Tiến độ chung (%)", "overall_progress_pct"),
        ("Meta thiếu", "missing_meta_count"),
        ("Date lỗi", "date_errors_count"),
        ("Status lệch/thiếu", "status_errors_count"),
        ("PIC blacklist", "pic_blacklist_count"),
        ("Estimate MH rejected", "estimate_rejected_count"),
        ("Unassigned", "unassigned_count"),
        ("Overdue", "overdue_count"),
        ("Stalled", "stalled_count"),
        ("High risk (>=50)", "high_risk_count"),
        ("Discrepancy", "discrepancy_count"),
    ]
    for idx, (label, key) in enumerate(labels, start=4):
        ws.cell(row=idx, column=1, value=label).font = Font(name="Arial", bold=True, size=11)
        ws.cell(row=idx, column=1).border = THIN_BORDER
        c = ws.cell(row=idx, column=2, value=summary.get(key, 0))
        c.font = Font(name="Arial", size=11)
        c.border = THIN_BORDER

    # 02 Meta thiếu
    ws = wb.create_sheet(AUDIT_SHEET_NAMES[1])
    items = issues["missing_meta"]
    _write_sheet(
        ws, "META THIẾU",
        [("STT", 6), ("Row", 8), ("Mã CN", 14), ("Tên CN", 36), ("Module", 10), ("Thiếu", 40)],
        [[idx + 1, i.get("row_index", ""), i.get("ma_cn", ""), i.get("ten_cn", ""),
          i.get("module", ""), i.get("missing_fields", "")] for idx, i in enumerate(items)],
        subtitle=sub,
    )

    # 03 Date lỗi
    ws = wb.create_sheet(AUDIT_SHEET_NAMES[2])
    items = issues["date_errors"]
    _write_sheet(
        ws, "DATE LỖI (End < Start)",
        [("STT", 6), ("Row", 8), ("Mã CN", 14), ("Tên CN", 36), ("Module", 10),
         ("Phase", 16), ("Start", 13), ("End", 13), ("Issue", 18)],
        [[idx + 1, i.get("row_index", ""), i.get("ma_cn", ""), i.get("ten_cn", ""),
          i.get("module", ""), i.get("phase", ""), i.get("start_date", ""),
          i.get("end_date", ""), i.get("issue", "")] for idx, i in enumerate(items)],
        subtitle=sub,
    )

    # 04 Status lệch
    ws = wb.create_sheet(AUDIT_SHEET_NAMES[3])
    items = issues["status_errors"]
    _write_sheet(
        ws, "STATUS LỆCH / THIẾU",
        [("STT", 6), ("Row", 8), ("Mã CN", 14), ("Tên CN", 36), ("Module", 10),
         ("Phase", 16), ("Issue", 28), ("Chi tiết", 45)],
        [[idx + 1, i.get("row_index", ""), i.get("ma_cn", ""), i.get("ten_cn", ""),
          i.get("module", ""), i.get("phase", ""), i.get("issue", ""),
          i.get("detail", "")] for idx, i in enumerate(items)],
        subtitle=sub,
    )

    # 05 PIC blacklist
    ws = wb.create_sheet(AUDIT_SHEET_NAMES[4])
    items = issues["pic_blacklist"]
    _write_sheet(
        ws, "PIC BLACKLIST",
        [("STT", 6), ("Row", 8), ("Mã CN", 14), ("Module", 10), ("Phase", 16),
         ("Header", 22), ("Raw value", 16), ("Keyword", 14)],
        [[idx + 1, i.get("row_index", ""), i.get("ma_cn", ""), i.get("module", ""),
          i.get("phase_name", ""), i.get("header_text", ""), i.get("raw_value", ""),
          i.get("matched_keyword", "")] for idx, i in enumerate(items)],
        subtitle=sub, row_fill_fn=lambda r, o: YELLOW_FILL,
    )

    # 06 Estimate rejected
    ws = wb.create_sheet(AUDIT_SHEET_NAMES[5])
    items = issues["estimate_rejected"]
    _write_sheet(
        ws, "ESTIMATE MH BỊ REJECT",
        [("STT", 6), ("Row", 8), ("Mã CN", 14), ("Module", 10), ("Phase", 16),
         ("Header", 24), ("Raw value", 22), ("Reason", 22)],
        [[idx + 1, i.get("row_index", ""), i.get("ma_cn", ""), i.get("module", ""),
          i.get("phase_name", ""), i.get("header", ""), i.get("raw_value", ""),
          i.get("reason", "")] for idx, i in enumerate(items)],
        subtitle=sub, row_fill_fn=lambda r, o: ORANGE_FILL,
    )

    # 07 Unassigned
    ws = wb.create_sheet(AUDIT_SHEET_NAMES[6])
    items = issues["unassigned"]
    _write_sheet(
        ws, "UNASSIGNED",
        [("STT", 6), ("Mã CN", 14), ("Tên CN", 40), ("Module", 10), ("Phase", 16),
         ("Status", 12), ("Priority", 12), ("Deadline", 13)],
        [[idx + 1, i.get("ma_cn", ""), i.get("ten_cn", ""), i.get("module", ""),
          i.get("phase", ""), i.get("status", ""), i.get("priority", ""),
          i.get("end_date", "")] for idx, i in enumerate(items)],
        subtitle=sub,
    )

    # 08 Overdue
    ws = wb.create_sheet(AUDIT_SHEET_NAMES[7])
    items = issues["overdue"]
    _write_sheet(
        ws, "OVERDUE",
        [("STT", 6), ("Mã CN", 14), ("Tên CN", 40), ("Module", 10), ("Phase", 16),
         ("Deadline", 13), ("Ngày trễ", 10), ("Status", 12), ("PIC", 20)],
        [[idx + 1, i.get("ma_cn", ""), i.get("ten_cn", ""), i.get("module", ""),
          i.get("phase", ""), i.get("end_date", ""), i.get("days_overdue", 0),
          i.get("status", ""),
          ", ".join(i.get("pic") or []) if isinstance(i.get("pic"), list) else ""]
         for idx, i in enumerate(items)],
        subtitle=sub,
        row_fill_fn=lambda ri, idx: _fill_by_days(items[idx].get("days_overdue", 0)),
    )

    # 09 Stalled
    ws = wb.create_sheet(AUDIT_SHEET_NAMES[8])
    items = issues["stalled"]
    _write_sheet(
        ws, "STALLED",
        [("STT", 6), ("Mã CN", 14), ("Tên CN", 40), ("Module", 10),
         ("Phase xong", 16), ("Phase chờ", 16), ("Chờ (ngày)", 12), ("Priority", 12)],
        [[idx + 1, i.get("ma_cn", ""), i.get("ten_cn", ""), i.get("module", ""),
          i.get("completed_phase", ""), i.get("waiting_phase", ""),
          i.get("wait_days", 0), i.get("priority", "")] for idx, i in enumerate(items)],
        subtitle=sub,
    )

    # 10 High risk
    ws = wb.create_sheet(AUDIT_SHEET_NAMES[9])
    items = issues["high_risk"]
    _write_sheet(
        ws, "HIGH RISK (>=50)",
        [("STT", 6), ("Score", 10), ("Mã CN", 14), ("Tên CN", 40), ("Module", 10),
         ("Priority", 12), ("Factors", 45)],
        [[idx + 1, i.get("risk_score", 0), i.get("ma_cn", ""), i.get("ten_cn", ""),
          i.get("module", ""), i.get("priority", ""),
          " | ".join(i.get("risk_factors") or [])] for idx, i in enumerate(items)],
        subtitle=sub,
        row_fill_fn=lambda ri, idx: _fill_by_risk(items[idx].get("risk_score", 0)),
    )

    # 11 Discrepancy
    ws = wb.create_sheet(AUDIT_SHEET_NAMES[10])
    items = issues["discrepancy"]
    _write_sheet(
        ws, "DISCREPANCY / MÂU THUẪN",
        [("STT", 6), ("Mã CN", 14), ("Tên CN", 36), ("Module", 10),
         ("Issue", 28), ("Chi tiết", 50)],
        [[idx + 1, i.get("ma_cn", ""), i.get("ten_cn", ""), i.get("module", ""),
          i.get("issue", ""), i.get("detail", "")] for idx, i in enumerate(items)],
        subtitle=sub,
    )

    os.makedirs(output_dir, exist_ok=True)
    filename = f"Audit_Report_{date.today().strftime('%Y%m%d')}.xlsx"
    filepath = os.path.join(output_dir, filename)
    wb.save(filepath)
    wb.close()
    return filepath


# ======================================================================
# PHASE 4/5 EXPORTS: SLA / Capacity / Slow / Baseline
# Rule (V4): XEM THÌ PHÂN TRANG NHƯNG XUẤT LÀ XUẤT ALL RECORD
# ======================================================================


def _severity_fill(sev: str) -> Optional[PatternFill]:
    """Highlight theo severity: critical=đỏ, warning=cam."""
    s = (sev or "").lower()
    if s == "critical":
        return RED_FILL
    if s == "warning":
        return ORANGE_FILL
    return None


def _filter_subtitle(filters: Optional[dict]) -> str:
    """Build subtitle chuẩn: 'Ngày xuất: dd/mm/yyyy  |  Bộ lọc: Module=..., Quy trình=..., PIC=...'."""
    date_part = f"Ngày xuất: {date.today().strftime('%d/%m/%Y')}"
    if not filters:
        return date_part
    parts = []
    for key, label in [("modules", "Module"), ("processes", "Quy trình"), ("pics", "PIC")]:
        vals = filters.get(key) or filters.get(key.rstrip("s")) or []
        if isinstance(vals, str):
            vals = [vals] if vals else []
        if vals:
            parts.append(f"{label}=[{', '.join(vals)}]")
    return f"{date_part}  |  Bộ lọc: {' · '.join(parts)}" if parts else date_part


def export_sla_report(
    payload: dict[str, Any],
    output_dir: str = "uploads",
    filters: Optional[dict] = None,
) -> str:
    """
    Xuất báo cáo SLA vi phạm deadline theo Priority.

    Args:
        payload: kết quả compute_sla_violations {items, total, critical_count,
                 warning_count, thresholds}
        output_dir: thư mục lưu file
        filters: dict global filter đã áp trước khi compute (chỉ để in vào subtitle)

    Rule V4: XUẤT ALL items, không cắt theo pagination FE.
    """
    items = list(payload.get("items") or [])
    thresholds = payload.get("thresholds") or {}
    critical_count = payload.get("critical_count", 0)
    warning_count = payload.get("warning_count", 0)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "SLA_Violations"

    subtitle = _filter_subtitle(filters)
    subtitle += (f"  |  Must-have quá {thresholds.get('must_have_days', '?')}d / "
                 f"Should-have quá {thresholds.get('should_have_days', '?')}d → critical")
    subtitle += f"  |  Critical: {critical_count} · Warning: {warning_count}"

    _write_sheet(
        ws,
        title="BÁO CÁO SLA — VI PHẠM DEADLINE",
        columns=[
            ("STT", 6),
            ("Severity", 12),
            ("Mã CN", 14),
            ("Tên chức năng", 40),
            ("Module", 10),
            ("Priority", 14),
            ("Phase", 16),
            ("End (deadline)", 14),
            ("Số ngày trễ", 12),
            ("Ngưỡng (d)", 12),
            ("Status", 12),
            ("PIC", 24),
        ],
        data_rows=[
            [
                idx + 1,
                (i.get("severity") or "").upper(),
                i.get("ma_cn", ""),
                i.get("ten_cn", ""),
                i.get("module", ""),
                i.get("priority", ""),
                i.get("phase", ""),
                i.get("end_date", ""),
                i.get("days_late", 0),
                i.get("threshold_days", 0),
                i.get("status", ""),
                ", ".join(i.get("pics") or []),
            ]
            for idx, i in enumerate(items)
        ],
        row_fill_fn=lambda _ri, idx: _severity_fill(items[idx].get("severity")),
        subtitle=subtitle,
    )

    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, f"SLA_Violations_{date.today().strftime('%Y%m%d')}.xlsx")
    wb.save(filepath)
    wb.close()
    return filepath


def _overload_fill(overload: bool) -> Optional[PatternFill]:
    return RED_FILL if overload else None


def export_capacity_report(
    payload: dict[str, Any],
    output_dir: str = "uploads",
    filters: Optional[dict] = None,
) -> str:
    """
    Xuất báo cáo Capacity PIC — remaining MH vs công suất tuần.

    Args:
        payload: kết quả compute_capacity_load {by_pic, default_md_per_week, overload_count}

    Rule V4: XUẤT ALL PIC rows.
    """
    rows = list(payload.get("by_pic") or [])
    default_md = payload.get("default_md_per_week")
    overload_count = payload.get("overload_count", 0)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Capacity_PIC"

    subtitle = _filter_subtitle(filters)
    if default_md:
        subtitle += f"  |  Default: {default_md} MD/tuần"
    subtitle += f"  |  Overload: {overload_count}"

    _write_sheet(
        ws,
        title="BÁO CÁO CAPACITY PIC",
        columns=[
            ("STT", 6),
            ("PIC", 20),
            ("Remaining (MH)", 15),
            ("Closed (MH)", 15),
            ("Capacity (MH/tuần)", 18),
            ("Số tuần cần", 14),
            ("Overload?", 12),
        ],
        data_rows=[
            [
                idx + 1,
                r.get("pic", ""),
                r.get("remaining_mh", 0),
                r.get("closed_mh", 0),
                r.get("capacity_mh_per_week", 0),
                r.get("weeks_needed") if r.get("weeks_needed") is not None else "",
                "OVERLOAD" if r.get("overload") else "",
            ]
            for idx, r in enumerate(rows)
        ],
        row_fill_fn=lambda _ri, idx: _overload_fill(bool(rows[idx].get("overload"))),
        subtitle=subtitle,
    )

    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, f"Capacity_PIC_{date.today().strftime('%Y%m%d')}.xlsx")
    wb.save(filepath)
    wb.close()
    return filepath


def _slow_cell_fill(count: int) -> Optional[PatternFill]:
    """Highlight ô heatmap theo số phase-record trễ."""
    if count >= 10:
        return RED_FILL
    if count >= 5:
        return ORANGE_FILL
    if count >= 1:
        return YELLOW_FILL
    return None


def export_slow_heatmap_report(
    payload: dict[str, Any],
    output_dir: str = "uploads",
    filters: Optional[dict] = None,
) -> str:
    """
    Xuất báo cáo "Ai đang chậm" — Heatmap PIC × Phase.

    Sheet 1: Matrix PIC × Phase (highlight theo count).
    Sheet 2: Flat list (chỉ ô > 0) — dễ pivot.

    Rule V4: XUẤT ALL PIC × Phase records.
    """
    pics = list(payload.get("pics") or [])
    phases = list(payload.get("phases") or [])
    heatmap = payload.get("heatmap") or {}
    total_slow = payload.get("total_slow", 0)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Heatmap_PIC_x_Phase"

    subtitle = _filter_subtitle(filters) + f"  |  Tổng phase-record trễ: {total_slow}"

    # === Sheet 1: matrix ===
    n_cols = 1 + len(phases) + 1  # cột PIC + N phases + Σ
    last_col_letter = get_column_letter(n_cols)
    ws.merge_cells(f"A1:{last_col_letter}1")
    tc = ws["A1"]
    tc.value = "HEATMAP PIC × PHASE — Task đang chậm"
    tc.font = Font(name="Arial", bold=True, size=14, color="1F4E79")
    tc.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28
    ws.merge_cells(f"A2:{last_col_letter}2")
    sc = ws["A2"]
    sc.value = subtitle
    sc.font = Font(name="Arial", size=10, italic=True, color="666666")
    sc.alignment = Alignment(horizontal="center")

    hdr_row = 4
    cells = ["PIC"] + phases + ["Σ"]
    widths = [22] + [max(12, len(ph) + 2) for ph in phases] + [10]
    for c_idx, (name, w) in enumerate(zip(cells, widths), 1):
        cell = ws.cell(row=hdr_row, column=c_idx, value=name)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER
        ws.column_dimensions[get_column_letter(c_idx)].width = w
    ws.row_dimensions[hdr_row].height = 25

    for row_offset, pic in enumerate(pics):
        r_idx = hdr_row + 1 + row_offset
        row_data = heatmap.get(pic) or {}
        row_sum = 0
        pic_cell = ws.cell(row=r_idx, column=1, value=pic)
        pic_cell.font = Font(name="Arial", bold=True, size=10)
        pic_cell.border = THIN_BORDER
        pic_cell.alignment = BODY_ALIGN
        for ph_idx, ph in enumerate(phases, 2):
            v = int(row_data.get(ph) or 0)
            row_sum += v
            cell = ws.cell(row=r_idx, column=ph_idx, value=v if v > 0 else "")
            cell.font = BODY_FONT
            cell.alignment = Alignment(horizontal="center")
            cell.border = THIN_BORDER
            fill = _slow_cell_fill(v)
            if fill:
                cell.fill = fill
        sum_cell = ws.cell(row=r_idx, column=n_cols, value=row_sum)
        sum_cell.font = Font(name="Arial", bold=True, size=10)
        sum_cell.alignment = Alignment(horizontal="center")
        sum_cell.border = THIN_BORDER

    if pics:
        total_row = hdr_row + len(pics) + 2
        ws.merge_cells(f"A{total_row}:{last_col_letter}{total_row}")
        s = ws.cell(row=total_row, column=1)
        s.value = (f"Tổng: {len(pics)} PIC × {len(phases)} phase | "
                   f"{total_slow} phase-record trễ | "
                   f"Xuất ngày {date.today().strftime('%d/%m/%Y')}")
        s.font = Font(name="Arial", bold=True, size=10, color="1F4E79")
    ws.freeze_panes = f"B{hdr_row + 1}"

    # === Sheet 2: flat list ===
    ws2 = wb.create_sheet("Flat_List")
    flat_rows = []
    for pic in pics:
        row_data = heatmap.get(pic) or {}
        for ph in phases:
            v = int(row_data.get(ph) or 0)
            if v > 0:
                flat_rows.append([len(flat_rows) + 1, pic, ph, v])
    _write_sheet(
        ws2,
        title="FLAT LIST — PIC × Phase với count > 0",
        columns=[
            ("STT", 6),
            ("PIC", 22),
            ("Phase", 20),
            ("Số phase-record trễ", 18),
        ],
        data_rows=flat_rows,
        row_fill_fn=lambda _ri, idx: _slow_cell_fill(flat_rows[idx][3]),
        subtitle=subtitle,
    )

    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, f"Slow_Heatmap_{date.today().strftime('%Y%m%d')}.xlsx")
    wb.save(filepath)
    wb.close()
    return filepath


def _variance_fill(days: int) -> Optional[PatternFill]:
    """Highlight theo variance ngày (trễ hoặc sớm nhiều đều đáng để ý)."""
    a = abs(int(days or 0))
    if a >= 14:
        return RED_FILL
    if a >= 7:
        return ORANGE_FILL
    if a >= 3:
        return YELLOW_FILL
    return None


def export_baseline_variance_report(
    payload: dict[str, Any],
    output_dir: str = "uploads",
    filters: Optional[dict] = None,
    all_items: Optional[list[dict]] = None,
) -> str:
    """
    Xuất báo cáo Baseline vs Actual variance ngày.

    Args:
        payload: kết quả compute_baseline_variance {items (max 200), total_compared, ...}
        all_items: OPTIONAL — full list khi caller cần bỏ giới hạn 200 của FE.
                   Nếu None thì dùng payload["items"] (đã bị cắt 200).

    Rule V4: XUẤT ALL items — caller (endpoint) nên truyền `all_items` để bỏ giới hạn.
    """
    items = list(all_items) if all_items is not None else list(payload.get("items") or [])
    total_compared = payload.get("total_compared", len(items))
    late_count = payload.get("late_count", sum(1 for i in items if i.get("late")))
    avg_var = payload.get("avg_variance_days", 0)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Baseline_vs_Actual"

    subtitle = _filter_subtitle(filters)
    subtitle += (f"  |  So sánh: {total_compared} · Trễ: {late_count} · "
                 f"Avg variance: {avg_var}d")

    _write_sheet(
        ws,
        title="BÁO CÁO BASELINE vs ACTUAL — VARIANCE NGÀY",
        columns=[
            ("STT", 6),
            ("Mã CN", 14),
            ("Tên chức năng", 40),
            ("Module", 10),
            ("Phase", 16),
            ("Plan date", 14),
            ("Actual date", 14),
            ("Variance (ngày)", 14),
            ("Trễ?", 8),
            ("Status", 12),
        ],
        data_rows=[
            [
                idx + 1,
                i.get("ma_cn", ""),
                i.get("ten_cn", ""),
                i.get("module", ""),
                i.get("phase", ""),
                i.get("plan_date", ""),
                i.get("actual_date", ""),
                i.get("variance_days", 0),
                "YES" if i.get("late") else "",
                i.get("status", ""),
            ]
            for idx, i in enumerate(items)
        ],
        row_fill_fn=lambda _ri, idx: _variance_fill(items[idx].get("variance_days", 0)),
        subtitle=subtitle,
    )

    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, f"Baseline_Variance_{date.today().strftime('%Y%m%d')}.xlsx")
    wb.save(filepath)
    wb.close()
    return filepath


# --------------------------------------------------------------------------
# FIT/GAP Dashboard export (Task 2). Multi-sheet: Summary + Aging + by-Module +
# by-Process + by-Priority. Rule V4: xuất ALL — không cắt aging list theo pagination.
# --------------------------------------------------------------------------

def _aging_fill(days: Optional[int]) -> Optional[PatternFill]:
    """Fill row aging: >= 30d red, 21-29d orange, 14-20d yellow."""
    if days is None:
        return None
    if days >= 30:
        return RED_FILL
    if days >= 21:
        return ORANGE_FILL
    if days >= 14:
        return YELLOW_FILL
    return None


def export_fitgap_report(
    payload: dict[str, Any],
    output_dir: str = "uploads",
    filters: Optional[dict] = None,
) -> str:
    """
    Xuất báo cáo FIT/GAP Dashboard sang Excel (multi-sheet).

    Rule V4: XUẤT ALL. Aging list dùng `payload["aging_items"]` (đã filter theo
    threshold ở backend); nếu caller muốn xuất TẤT CẢ GAP đang mở (không filter
    theo threshold), truyền vào `payload["all_open_gap_items"]` thay thế.
    """
    summary = payload.get("summary") or {}
    by_module = payload.get("by_module") or []
    by_process = payload.get("by_process") or []
    by_priority = payload.get("by_priority") or []
    aging_items = payload.get("aging_items") or []

    wb = openpyxl.Workbook()

    subtitle_base = _filter_subtitle(filters)
    thr = summary.get("aging_threshold_days", 14)

    # === Sheet 1: Summary ===
    ws = wb.active
    ws.title = "Summary"
    _write_sheet(
        ws,
        title="FIT/GAP DASHBOARD — TỔNG QUAN",
        subtitle=subtitle_base + f"  |  Aging threshold: {thr} ngày",
        columns=[("Chỉ số", 30), ("Số lượng", 14)],
        data_rows=[
            ["Tổng function", summary.get("total", 0)],
            ["FIT", summary.get("fit", 0)],
            ["GAP (tổng)", summary.get("gap", 0)],
            ["GAP đã đóng (all phase Closed/Cancelled)", summary.get("gap_closed", 0)],
            ["GAP đang mở", summary.get("gap_open", 0)],
            [f"GAP aging > {thr} ngày", summary.get("gap_open_aging", 0)],
        ],
    )

    # === Sheet 2: Aging GAP list ===
    ws2 = wb.create_sheet("Aging_GAP")
    _write_sheet(
        ws2,
        title=f"GAP AGING — ĐANG MỞ > {thr} NGÀY",
        subtitle=subtitle_base + f"  |  Tổng: {len(aging_items)}",
        columns=[
            ("STT", 6),
            ("Mã CN", 14),
            ("Tên chức năng", 40),
            ("Module", 10),
            ("Quy trình", 30),
            ("Priority", 14),
            ("Ngày mở", 14),
            ("Aging (ngày)", 12),
            ("Phase đang mở", 14),
            ("Status", 12),
            ("PIC", 24),
        ],
        data_rows=[
            [
                idx + 1,
                it.get("ma_cn", ""),
                it.get("ten_cn", ""),
                it.get("module", ""),
                it.get("quy_trinh", ""),
                it.get("priority", ""),
                it.get("opened_date") or "N/A",
                it.get("aging_days") if it.get("aging_days") is not None else "N/A",
                it.get("current_phase", ""),
                it.get("status", ""),
                ", ".join(it.get("pics") or []),
            ]
            for idx, it in enumerate(aging_items)
        ],
        row_fill_fn=lambda _ri, idx: _aging_fill(aging_items[idx].get("aging_days")),
    )

    def _breakdown_sheet(sheet_name: str, title: str, rows: list[dict], key_field: str, label: str):
        ws_bk = wb.create_sheet(sheet_name)
        _write_sheet(
            ws_bk,
            title=title,
            subtitle=subtitle_base,
            columns=[
                ("STT", 6),
                (label, 32),
                ("FIT", 10),
                ("GAP", 10),
                ("Tổng", 10),
                ("% GAP", 10),
            ],
            data_rows=[
                [idx + 1, r.get(key_field, ""), r.get("fit", 0), r.get("gap", 0),
                 r.get("total", 0), f"{r.get('pct_gap', 0)}%"]
                for idx, r in enumerate(rows)
            ],
        )

    _breakdown_sheet("By_Module", "FIT/GAP THEO MODULE", by_module, "module", "Module")
    _breakdown_sheet("By_Process", "FIT/GAP THEO QUY TRÌNH", by_process, "process", "Quy trình")
    _breakdown_sheet("By_Priority", "FIT/GAP THEO PRIORITY", by_priority, "priority", "Priority")

    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, f"FITGAP_Dashboard_{date.today().strftime('%Y%m%d')}.xlsx")
    wb.save(filepath)
    wb.close()
    return filepath
