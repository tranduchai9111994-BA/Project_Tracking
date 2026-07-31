# -*- coding: utf-8 -*-
"""
Xuất Excel tổng hợp chiều PM (kế hoạch + weekly snapshot).
"""
from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any, Optional

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
PHASE_FILL = PatternFill("solid", fgColor="FFF2CC")
SECTION_FILL = PatternFill("solid", fgColor="D6EAF8")
THIN = Border(
    left=Side(style="thin", color="B0B0B0"),
    right=Side(style="thin", color="B0B0B0"),
    top=Side(style="thin", color="B0B0B0"),
    bottom=Side(style="thin", color="B0B0B0"),
)
WRAP = Alignment(wrap_text=True, vertical="center")


def _header_row(ws, headers: list[str], row: int = 1) -> None:
    for c, h in enumerate(headers, 1):
        cell = ws.cell(row, c, h)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN


def _autosize(ws, max_width: int = 45) -> None:
    for col in ws.columns:
        letter = get_column_letter(col[0].column)
        width = 10
        for cell in col:
            if cell.value is not None:
                width = max(width, min(max_width, len(str(cell.value).split("\n")[0]) + 2))
        ws.column_dimensions[letter].width = width


def export_pm_report(
    plan: Optional[dict[str, Any]],
    weekly: Optional[dict[str, Any]],
    output_dir: str,
    *,
    project_code: str = "",
    fl_links: Optional[dict[str, Any]] = None,
) -> str:
    """Sinh workbook chiều PM. Returns filepath."""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    _write_cover(wb, plan, weekly, project_code)
    if plan:
        _write_milestones(wb, plan)
        _write_schedule(wb, plan)
        _write_deliverables(wb, plan)
        _write_teams(wb, plan)
    if weekly:
        _write_weekly(wb, weekly)
    if fl_links and fl_links.get("link_count"):
        _write_fl_links(wb, fl_links)

    os.makedirs(output_dir, exist_ok=True)
    today = date.today().isoformat()
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (project_code or "project"))[:40]
    filename = f"{safe}_ChieuPM_{today}.xlsx"
    filepath = os.path.join(output_dir, filename)
    wb.save(filepath)
    return filepath


def _write_cover(wb, plan, weekly, project_code: str) -> None:
    ws = wb.create_sheet("Tổng quan", 0)
    ws["A1"] = "Báo cáo chiều PM"
    ws["A1"].font = Font(name="Calibri", bold=True, size=16, color="1F4E79")
    ws["A2"] = f"Dự án: {project_code or '—'}"
    ws["A3"] = f"Xuất lúc: {datetime.now().isoformat(timespec='seconds')}"

    row = 5
    ws.cell(row, 1, "Nguồn").font = Font(bold=True)
    ws.cell(row, 2, "Trạng thái")
    ws.cell(row, 3, "Chi tiết")
    _header_row(ws, ["Nguồn", "Trạng thái", "Chi tiết"], row)

    row = 6
    if plan:
        s = plan.get("summary") or {}
        ws.cell(row, 1, "Kế hoạch dự án (Excel)")
        ws.cell(row, 2, "Đã import")
        ws.cell(
            row, 3,
            f"{plan.get('source_filename', '')} | "
            f"WBS {s.get('milestone_count', 0)} | "
            f"Lịch trình {s.get('schedule_count', 0)} | "
            f"Deliverable {s.get('deliverable_count', 0)} | "
            f"Import {plan.get('imported_at', '')}",
        )
    else:
        ws.cell(row, 1, "Kế hoạch dự án (Excel)")
        ws.cell(row, 2, "Chưa có")
        ws.cell(row, 3, "Upload file KeHoachDuAn (.xlsx)")
    row += 1
    if weekly:
        s = weekly.get("summary") or {}
        period = f"{weekly.get('period_start') or '?'} → {weekly.get('period_end') or '?'}"
        ws.cell(row, 1, "Weekly Report (PPT)")
        ws.cell(row, 2, "Đã import")
        ws.cell(
            row, 3,
            f"{weekly.get('source_filename', '')} | {period} | "
            f"Done {s.get('done_count', 0)} | Next {s.get('next_count', 0)} | "
            f"Import {weekly.get('imported_at', '')}",
        )
    else:
        ws.cell(row, 1, "Weekly Report (PPT)")
        ws.cell(row, 2, "Chưa có")
        ws.cell(row, 3, "Upload file Weekly Report (.pptx)")
    _autosize(ws)


def _write_milestones(wb, plan: dict) -> None:
    ws = wb.create_sheet("WBS Gantt")
    _header_row(ws, ["STT", "Công việc (milestone)", "Ghi chú"])
    for i, m in enumerate(plan.get("milestones") or [], 1):
        ws.cell(i + 1, 1, m.get("stt") or i)
        ws.cell(i + 1, 2, m.get("name"))
        ws.cell(i + 1, 3, m.get("note") or "")
        for c in range(1, 4):
            ws.cell(i + 1, c).border = THIN
            ws.cell(i + 1, c).alignment = WRAP
    # Weeks legend
    weeks = plan.get("weeks") or []
    if weeks:
        r = len(plan.get("milestones") or []) + 3
        ws.cell(r, 1, "Trục tuần (từ Gantt):").font = Font(bold=True)
        ws.cell(r + 1, 1, ", ".join(
            f"{w['label']}({w.get('month') or ''})" for w in weeks[:40]
        ))
    _autosize(ws)


def _write_schedule(wb, plan: dict) -> None:
    ws = wb.create_sheet("Lịch trình")
    headers = [
        "Giai đoạn", "Công việc", "Từ ngày", "Đến ngày",
        "PIC FPT", "Hỗ trợ FPT", "PIC KH", "Hỗ trợ KH", "Ghi chú", "Phase header?",
    ]
    _header_row(ws, headers)
    for i, item in enumerate(plan.get("schedule") or [], 1):
        r = i + 1
        vals = [
            item.get("phase") or "",
            item.get("name") or "",
            item.get("start") or "",
            item.get("end") or "",
            ", ".join(item.get("pic_fpt") or []),
            ", ".join(item.get("support_fpt") or []),
            ", ".join(item.get("pic_client") or []),
            ", ".join(item.get("support_client") or []),
            item.get("note") or "",
            "Yes" if item.get("is_phase_header") else "",
        ]
        for c, v in enumerate(vals, 1):
            cell = ws.cell(r, c, v)
            cell.border = THIN
            cell.alignment = WRAP
            if item.get("is_phase_header"):
                cell.fill = PHASE_FILL
    _autosize(ws)


def _write_deliverables(wb, plan: dict) -> None:
    ws = wb.create_sheet("Sản phẩm bàn giao")
    _header_row(ws, ["Nhóm", "STT", "Sản phẩm", "Ngày", "Loại", "Ghi chú", "Người lập"])
    for i, d in enumerate(plan.get("deliverables") or [], 1):
        r = i + 1
        vals = [
            d.get("group") or "",
            d.get("stt") or "",
            d.get("name") or "",
            d.get("due_date") or "",
            d.get("type") or "",
            d.get("note") or "",
            d.get("author") or "",
        ]
        for c, v in enumerate(vals, 1):
            cell = ws.cell(r, c, v)
            cell.border = THIN
            if d.get("is_group"):
                cell.fill = SECTION_FILL
                cell.font = Font(bold=True)
    _autosize(ws)


def _write_teams(wb, plan: dict) -> None:
    ws = wb.create_sheet("Đội dự án")
    _header_row(ws, ["Side", "Nhóm", "STT", "Họ tên", "Chức vụ", "Vai trò", "Email"])
    rows = []
    for m in plan.get("team_vendor") or []:
        rows.append(("FPT", m))
    for m in plan.get("team_client") or []:
        rows.append(("Khách hàng", m))
    for i, (side, m) in enumerate(rows, 1):
        r = i + 1
        vals = [
            side,
            m.get("group") or "",
            m.get("stt") or "",
            m.get("name") or "",
            m.get("title") or "",
            m.get("role") or "",
            m.get("email") or "",
        ]
        for c, v in enumerate(vals, 1):
            cell = ws.cell(r, c, v)
            cell.border = THIN
            cell.alignment = WRAP
    _autosize(ws)


def _write_weekly(wb, weekly: dict) -> None:
    ws = wb.create_sheet("Weekly Done")
    period = f"{weekly.get('period_start') or '?'} → {weekly.get('period_end') or '?'}"
    ws["A1"] = weekly.get("title") or "Weekly"
    ws["A1"].font = Font(bold=True, size=13, color="1F4E79")
    ws["A2"] = f"Kỳ báo cáo: {period}"
    ws["A3"] = weekly.get("project_title") or ""
    _header_row(ws, ["STT", "Công việc", "Đơn vị", "Ngày", "Tình trạng", "Ghi chú"], row=5)
    for i, item in enumerate(weekly.get("done") or [], 1):
        r = i + 5
        for c, v in enumerate([
            item.get("stt"), item.get("task"), item.get("unit"),
            item.get("date"), item.get("status"), item.get("note"),
        ], 1):
            cell = ws.cell(r, c, v or "")
            cell.border = THIN
            cell.alignment = WRAP
    _autosize(ws)

    ws2 = wb.create_sheet("Weekly Next")
    _header_row(ws2, ["STT", "Công việc", "Đơn vị", "Bắt đầu", "Kết thúc", "Ghi chú"])
    for i, item in enumerate(weekly.get("next") or [], 1):
        r = i + 1
        for c, v in enumerate([
            item.get("stt"), item.get("task"), item.get("unit"),
            item.get("start"), item.get("end"), item.get("note"),
        ], 1):
            cell = ws2.cell(r, c, v or "")
            cell.border = THIN
            cell.alignment = WRAP
    _autosize(ws2)

    ws3 = wb.create_sheet("Weekly Risk")
    _header_row(ws3, ["Loại", "Nội dung"])
    r = 2
    for t in weekly.get("issues") or []:
        ws3.cell(r, 1, "Issue")
        ws3.cell(r, 2, t)
        r += 1
    for t in weekly.get("risks") or []:
        ws3.cell(r, 1, "Risk")
        ws3.cell(r, 2, t)
        r += 1
    _autosize(ws3)


def _write_fl_links(wb, fl_links: dict) -> None:
    ws = wb.create_sheet("FL Links")
    _header_row(ws, ["Nguồn", "Tên công việc", "Module trùng", "Phase trùng", "PIC trùng"])
    r = 2
    for link in fl_links.get("schedule_links") or []:
        ws.cell(r, 1, "Lịch trình")
        ws.cell(r, 2, link.get("name"))
        ws.cell(r, 3, ", ".join(link.get("modules") or []))
        ws.cell(r, 4, ", ".join(link.get("phases") or []))
        ws.cell(r, 5, ", ".join(link.get("pics") or []))
        r += 1
    for link in fl_links.get("weekly_links") or []:
        ws.cell(r, 1, f"Weekly/{link.get('kind')}")
        ws.cell(r, 2, link.get("task"))
        ws.cell(r, 3, ", ".join(link.get("modules") or []))
        r += 1
    _autosize(ws)
