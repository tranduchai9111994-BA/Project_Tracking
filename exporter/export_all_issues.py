"""
T34 Task 1 — Xuất "Toàn bộ vấn đề" ra 1 Excel workbook duy nhất.

File: `iHRP_Van_De_Tong_Hop_<slug>_YYYYMMDD.xlsx`

Sheet layout (0-indexed theo README, thực tế openpyxl là 1-indexed):
  0. Cover        — Tổng quan project + filter + count mỗi loại (link đến sheet)
  1. Overdue      — Function trễ deadline (dedup theo Mã CN, phase merged)
  2. Chua_Co_PIC  — Function chưa assign
  3. Dinh_Tre     — Function stalled giữa 2 phase
  4. High_Risk    — Function risk score cao (>=30)
  5. Aging_WIP    — Function In-progress quá lâu
  6. Data_Quality — Row có lỗi data
  7. Bookmark     — Function đã star (nếu có)

Reuse ParsedData đã filter — không tự filter lại. Signature nhận sẵn:
  - overdue_list (deduped theo ma_cn)
  - unassigned_list
  - stalled_list
  - risk_list (>=30)
  - aging_wip_items
  - data_quality_issues
  - bookmark_functions
Giúp caller apply global filter một lần và inject vào exporter → tránh
tính lại 8 lần.

Layout theo spec:
  - Banner row 1 (merge A1:H1) tên sheet + count + màu category.
  - Header row 2 bold + fill xanh nhạt.
  - Freeze pane row 3.
  - Auto-filter, auto column width (đã tính sẵn qua bảng CFG).
"""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import date
from typing import Any, Optional

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.hyperlink import Hyperlink


# ==========================================================================
# STYLE — Palette theo spec (banner màu category)
# ==========================================================================

BANNER_COLORS = {
    "cover":       "1F4E79",  # Xanh navy
    "overdue":     "C00000",  # Đỏ
    "unassigned":  "ED7D31",  # Cam
    "stalled":     "BF8F00",  # Vàng đậm
    "high_risk":   "E60000",  # Đỏ tươi
    "aging":       "FFC000",  # Vàng nhạt
    "data_quality":"595959",  # Xám
    "bookmark":    "7030A0",  # Tím
}

HEADER_FILL = PatternFill(start_color="DEEBF7", end_color="DEEBF7", fill_type="solid")
HEADER_FONT = Font(name="Arial", bold=True, size=10, color="1F4E79")
HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)

BODY_FONT = Font(name="Arial", size=10)
BODY_ALIGN = Alignment(vertical="center", wrap_text=True)

THIN_BORDER = Border(
    left=Side(style="thin", color="D0D0D0"),
    right=Side(style="thin", color="D0D0D0"),
    top=Side(style="thin", color="D0D0D0"),
    bottom=Side(style="thin", color="D0D0D0"),
)

# Fill theo mức trễ (tôn màu overdue > aging > stalled > default)
RED_FILL = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")
ORANGE_FILL = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")
YELLOW_FILL = PatternFill(start_color="FEF9C3", end_color="FEF9C3", fill_type="solid")


def _fill_by_days(days: int) -> Optional[PatternFill]:
    if not days or days < 0:
        return None
    if days >= 30:
        return RED_FILL
    if days >= 14:
        return ORANGE_FILL
    if days >= 7:
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


# ==========================================================================
# Helper — banner + header + data + freeze
# ==========================================================================

def _write_banner(ws, title: str, count: int, category: str, n_cols: int) -> None:
    """Row 1: banner merge A1:<lastcol>1, fill màu category, text trắng đậm."""
    last = get_column_letter(n_cols)
    ws.merge_cells(f"A1:{last}1")
    c = ws["A1"]
    c.value = f"{title}  —  Tổng: {count} record"
    c.font = Font(name="Arial", bold=True, size=13, color="FFFFFF")
    c.alignment = Alignment(horizontal="center", vertical="center")
    c.fill = PatternFill(
        start_color=BANNER_COLORS.get(category, "1F4E79"),
        end_color=BANNER_COLORS.get(category, "1F4E79"),
        fill_type="solid",
    )
    ws.row_dimensions[1].height = 30


def _write_header(ws, columns: list[tuple[str, int]]) -> None:
    """Row 2: header bold + fill xanh nhạt."""
    for col_idx, (name, width) in enumerate(columns, 1):
        cell = ws.cell(row=2, column=col_idx, value=name)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER
        ws.column_dimensions[get_column_letter(col_idx)].width = width
    ws.row_dimensions[2].height = 28


def _write_data(
    ws,
    rows: list[list[Any]],
    row_fill_fn=None,
    n_cols: int = 0,
) -> None:
    """Ghi data từ row 3 trở đi."""
    for offset, values in enumerate(rows):
        r_idx = 3 + offset
        fill = row_fill_fn(offset) if row_fill_fn else None
        for c_idx, val in enumerate(values, 1):
            cell = ws.cell(row=r_idx, column=c_idx, value=val)
            cell.font = BODY_FONT
            cell.alignment = BODY_ALIGN
            cell.border = THIN_BORDER
            if fill:
                cell.fill = fill

    # Empty state — thông báo "Không có record" ở A3
    if not rows and n_cols:
        last = get_column_letter(n_cols)
        ws.merge_cells(f"A3:{last}3")
        c = ws["A3"]
        c.value = "✓ Không có record nào trong nhóm này (đã áp dụng filter global)."
        c.font = Font(name="Arial", italic=True, color="666666")
        c.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[3].height = 24


def _finalize_sheet(ws, n_rows: int, n_cols: int) -> None:
    """Freeze pane row 3, auto-filter row 2."""
    ws.freeze_panes = "A3"
    if n_rows > 0:
        last = get_column_letter(n_cols)
        ws.auto_filter.ref = f"A2:{last}{2 + n_rows}"


# ==========================================================================
# Dedup helper — gom nhiều phase của 1 function thành 1 row
# ==========================================================================

def _dedup_by_ma_cn(items: list[dict], phase_field: str = "phase") -> list[dict]:
    """
    Gom nhiều phase-record của cùng 1 Mã CN thành 1 row (spec: sheet Overdue
    dedup theo Mã CN, phase merged bằng dấu phẩy).

    - Giữ ma_cn/ten_cn/module/priority của record đầu tiên.
    - Merge phase → "Analysis, UAT".
    - Chọn days_overdue = MAX (worst-case).
    - Merge PIC (unique, giữ order first-seen).
    """
    groups: dict[str, dict] = {}
    for it in items:
        key = str(it.get("ma_cn") or "").strip() or f"__norow_{id(it)}"
        if key not in groups:
            g = dict(it)  # copy
            g["_phases"] = [str(it.get(phase_field) or "")]
            g["_pics"] = list(it.get("pic") or [])
            g["_max_days"] = int(it.get("days_overdue") or 0)
            groups[key] = g
        else:
            g = groups[key]
            ph = str(it.get(phase_field) or "")
            if ph and ph not in g["_phases"]:
                g["_phases"].append(ph)
            for p in (it.get("pic") or []):
                if p and p not in g["_pics"]:
                    g["_pics"].append(p)
            days = int(it.get("days_overdue") or 0)
            if days > g["_max_days"]:
                g["_max_days"] = days

    out = []
    for g in groups.values():
        g[phase_field] = ", ".join([p for p in g["_phases"] if p])
        g["pic"] = g["_pics"]
        g["days_overdue"] = g["_max_days"]
        g.pop("_phases", None)
        g.pop("_pics", None)
        g.pop("_max_days", None)
        out.append(g)
    out.sort(key=lambda x: x.get("days_overdue", 0), reverse=True)
    return out


# ==========================================================================
# Main entry
# ==========================================================================

def export_all_issues(
    *,
    project_name: str,
    slug: str,
    overdue_list: list[dict],
    unassigned_list: list[dict],
    stalled_list: list[dict],
    risk_list: list[dict],
    aging_wip_items: list[dict],
    data_quality_issues: list[dict],
    bookmark_functions: list[dict],
    filter_info: Optional[dict] = None,
    output_dir: str = "uploads",
) -> str:
    """
    Xuất 1 workbook 8 sheet (Cover + 7 loại vấn đề).

    Args:
      project_name: tên project (hiển thị ở cover).
      slug: dùng để đặt tên file.
      overdue_list / unassigned_list / …: đã filter global (caller lo).
      filter_info: {"modules": [...], "processes": [...], "pics": [...]}
        — để render dòng "Filter đang áp dụng" ở cover.
      output_dir: thư mục output (mặc định uploads/).

    Returns:
      Path to Excel file.
    """
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    # === Sheet 0: Cover ===
    _write_cover_sheet(
        wb,
        project_name=project_name,
        slug=slug,
        counts={
            "Overdue":     len(_dedup_by_ma_cn(overdue_list)),
            "Chua_Co_PIC": len(unassigned_list),
            "Dinh_Tre":    len(stalled_list),
            "High_Risk":   len(risk_list),
            "Aging_WIP":   len(aging_wip_items),
            "Data_Quality":len(data_quality_issues),
            "Bookmark":    len(bookmark_functions),
        },
        filter_info=filter_info or {},
    )

    # === Sheet 1: Overdue (dedup theo Mã CN, phase merged) ===
    _write_overdue_sheet(wb, _dedup_by_ma_cn(overdue_list))

    # === Sheet 2: Chua_Co_PIC ===
    _write_unassigned_sheet(wb, unassigned_list)

    # === Sheet 3: Dinh_Tre ===
    _write_stalled_sheet(wb, stalled_list)

    # === Sheet 4: High_Risk ===
    _write_risk_sheet(wb, risk_list)

    # === Sheet 5: Aging_WIP ===
    _write_aging_sheet(wb, aging_wip_items)

    # === Sheet 6: Data_Quality ===
    _write_dq_sheet(wb, data_quality_issues)

    # === Sheet 7: Bookmark ===
    _write_bookmark_sheet(wb, bookmark_functions)

    # Set active = Cover
    wb.active = 0

    os.makedirs(output_dir, exist_ok=True)
    safe_slug = "".join(c for c in slug if c.isalnum() or c in ("_", "-")) or "project"
    filename = f"iHRP_Van_De_Tong_Hop_{safe_slug}_{date.today().strftime('%Y%m%d')}.xlsx"
    filepath = os.path.join(output_dir, filename)
    wb.save(filepath)
    wb.close()
    return filepath


# ==========================================================================
# Per-sheet writers
# ==========================================================================

def _write_cover_sheet(
    wb, *, project_name: str, slug: str, counts: dict[str, int], filter_info: dict,
) -> None:
    """Cover sheet: project name, filter info, timestamp, count mỗi loại với link."""
    ws = wb.create_sheet("Cover")

    # Banner
    ws.merge_cells("A1:D1")
    c = ws["A1"]
    c.value = f"📊 BÁO CÁO TỔNG HỢP VẤN ĐỀ — {project_name}"
    c.font = Font(name="Arial", bold=True, size=15, color="FFFFFF")
    c.alignment = Alignment(horizontal="center", vertical="center")
    c.fill = PatternFill(start_color=BANNER_COLORS["cover"],
                         end_color=BANNER_COLORS["cover"], fill_type="solid")
    ws.row_dimensions[1].height = 32

    # Metadata block
    meta_rows = [
        ("Project", project_name),
        ("Slug", slug),
        ("Ngày xuất", date.today().strftime("%d/%m/%Y")),
        ("Tổng loại vấn đề", len(counts)),
    ]
    # Filter info
    modules = ", ".join(filter_info.get("modules") or []) or "(tất cả)"
    processes = ", ".join(filter_info.get("processes") or []) or "(tất cả)"
    pics = ", ".join(filter_info.get("pics") or []) or "(tất cả)"
    meta_rows.extend([
        ("Filter Module", modules),
        ("Filter Quy trình", processes),
        ("Filter PIC", pics),
    ])

    for idx, (label, value) in enumerate(meta_rows, start=3):
        lc = ws.cell(row=idx, column=1, value=label)
        lc.font = Font(name="Arial", bold=True, size=11)
        lc.alignment = Alignment(horizontal="left", vertical="center")
        lc.border = THIN_BORDER
        vc = ws.cell(row=idx, column=2, value=str(value))
        vc.font = Font(name="Arial", size=11)
        vc.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        vc.border = THIN_BORDER
        ws.merge_cells(start_row=idx, start_column=2, end_row=idx, end_column=4)

    # Count table với link đến sheet — bắt đầu ở row 12
    start = 3 + len(meta_rows) + 2  # thêm 2 dòng blank buffer
    ws.cell(row=start - 1, column=1, value="📋 TỔNG HỢP THEO LOẠI VẤN ĐỀ").font = Font(
        name="Arial", bold=True, size=12, color="1F4E79"
    )
    ws.merge_cells(start_row=start - 1, start_column=1, end_row=start - 1, end_column=4)

    headers = ["Loại vấn đề", "Số record", "Sheet", "Link"]
    for i, h in enumerate(headers, 1):
        cell = ws.cell(row=start, column=i, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER

    display_map = [
        ("🔴 Trễ deadline", "Overdue"),
        ("🟠 Chưa có PIC", "Chua_Co_PIC"),
        ("🟡 Đình trệ", "Dinh_Tre"),
        ("🔺 High Risk (≥30)", "High_Risk"),
        ("🟡 Aging WIP", "Aging_WIP"),
        ("⚫ Data Quality", "Data_Quality"),
        ("🟣 Bookmark", "Bookmark"),
    ]
    for offset, (label, sheet_name) in enumerate(display_map):
        r = start + 1 + offset
        cnt = counts.get(sheet_name, 0)

        c1 = ws.cell(row=r, column=1, value=label)
        c1.font = BODY_FONT
        c1.alignment = BODY_ALIGN
        c1.border = THIN_BORDER

        c2 = ws.cell(row=r, column=2, value=cnt)
        c2.font = Font(name="Arial", bold=True, size=11,
                       color="C00000" if cnt > 0 else "666666")
        c2.alignment = Alignment(horizontal="right", vertical="center")
        c2.border = THIN_BORDER

        c3 = ws.cell(row=r, column=3, value=sheet_name)
        c3.font = BODY_FONT
        c3.alignment = BODY_ALIGN
        c3.border = THIN_BORDER

        c4 = ws.cell(row=r, column=4, value="→ Mở sheet")
        # Hyperlink nội bộ tới sheet
        c4.hyperlink = Hyperlink(
            ref=f"D{r}",
            location=f"'{sheet_name}'!A1",
            display=f"→ Mở sheet {sheet_name}",
        )
        c4.font = Font(name="Arial", size=10, color="0563C1", underline="single")
        c4.alignment = BODY_ALIGN
        c4.border = THIN_BORDER

    # Column width
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 20
    ws.column_dimensions["D"].width = 28

    # Footer help
    footer_r = start + 1 + len(display_map) + 2
    ws.merge_cells(start_row=footer_r, start_column=1, end_row=footer_r, end_column=4)
    fc = ws.cell(row=footer_r, column=1)
    fc.value = (
        "💡 Ghi chú: 'Số record' đã áp dụng filter global hiện tại. "
        "Sheet Overdue dedup theo Mã CN (phase merged). Các sheet khác giữ mọi record."
    )
    fc.font = Font(name="Arial", italic=True, size=9, color="666666")
    fc.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    ws.row_dimensions[footer_r].height = 32


def _write_overdue_sheet(wb, items: list[dict]) -> None:
    """Sheet Overdue dedup theo Mã CN."""
    ws = wb.create_sheet("Overdue")
    cols = [
        ("STT", 6), ("Mã CN", 14), ("Tên chức năng", 40), ("Module", 12),
        ("Phase trễ (gộp)", 28), ("Deadline (max)", 13), ("Số ngày trễ (max)", 15),
        ("Status", 13), ("PIC", 22), ("Priority", 12), ("Ghi chú", 30),
    ]
    _write_banner(ws, "🔴 TASK TRỄ DEADLINE (dedup theo Mã CN)",
                  len(items), "overdue", len(cols))
    _write_header(ws, cols)

    rows = []
    for idx, it in enumerate(items):
        rows.append([
            idx + 1,
            it.get("ma_cn", ""), it.get("ten_cn", ""), it.get("module", ""),
            it.get("phase", ""), it.get("end_date", ""), it.get("days_overdue", 0),
            it.get("status", ""), ", ".join(it.get("pic", [])),
            it.get("priority", ""), it.get("note", ""),
        ])

    _write_data(
        ws, rows,
        row_fill_fn=lambda i: _fill_by_days(items[i].get("days_overdue", 0)),
        n_cols=len(cols),
    )
    _finalize_sheet(ws, len(rows), len(cols))


def _write_unassigned_sheet(wb, items: list[dict]) -> None:
    ws = wb.create_sheet("Chua_Co_PIC")
    cols = [
        ("STT", 6), ("Mã CN", 14), ("Tên chức năng", 40), ("Module", 12),
        ("Phase", 16), ("Status", 16), ("Priority", 12), ("Complexity", 12),
        ("Deadline", 13), ("Trễ (ngày)", 12),
    ]
    _write_banner(ws, "🟠 TASK CHƯA CÓ PIC PHỤ TRÁCH",
                  len(items), "unassigned", len(cols))
    _write_header(ws, cols)

    rows = []
    for idx, it in enumerate(items):
        rows.append([
            idx + 1,
            it.get("ma_cn", ""), it.get("ten_cn", ""), it.get("module", ""),
            it.get("phase", ""), it.get("status", ""),
            it.get("priority", ""), it.get("complexity", ""),
            it.get("end_date", ""), it.get("days_overdue", 0),
        ])

    def _fill(i):
        it = items[i]
        if it.get("is_overdue"):
            return RED_FILL
        if "Must" in (it.get("priority") or ""):
            return ORANGE_FILL
        return None

    _write_data(ws, rows, row_fill_fn=_fill, n_cols=len(cols))
    _finalize_sheet(ws, len(rows), len(cols))


def _write_stalled_sheet(wb, items: list[dict]) -> None:
    ws = wb.create_sheet("Dinh_Tre")
    cols = [
        ("STT", 6), ("Mã CN", 14), ("Tên chức năng", 40), ("Module", 12),
        ("Phase đã xong", 18), ("Phase chờ", 18),
        ("Xong ngày", 13), ("Số ngày chờ", 12), ("Priority", 12),
    ]
    _write_banner(ws, "🟡 TASK ĐÌNH TRỆ (KẸT GIỮA 2 PHASE)",
                  len(items), "stalled", len(cols))
    _write_header(ws, cols)

    rows = []
    for idx, it in enumerate(items):
        rows.append([
            idx + 1,
            it.get("ma_cn", ""), it.get("ten_cn", ""), it.get("module", ""),
            it.get("completed_phase", ""), it.get("waiting_phase", ""),
            it.get("completed_date", ""), it.get("wait_days", 0),
            it.get("priority", ""),
        ])
    _write_data(
        ws, rows,
        row_fill_fn=lambda i: _fill_by_days(items[i].get("wait_days", 0)),
        n_cols=len(cols),
    )
    _finalize_sheet(ws, len(rows), len(cols))


def _write_risk_sheet(wb, items: list[dict]) -> None:
    ws = wb.create_sheet("High_Risk")
    cols = [
        ("STT", 6), ("Risk Score", 12), ("Mã CN", 14),
        ("Tên chức năng", 40), ("Module", 12),
        ("Priority", 12), ("Complexity", 12), ("Risk Factors", 50),
    ]
    _write_banner(ws, "🔺 FUNCTION CÓ ĐIỂM RỦI RO CAO (≥30)",
                  len(items), "high_risk", len(cols))
    _write_header(ws, cols)

    rows = []
    for idx, it in enumerate(items):
        rows.append([
            idx + 1, it.get("risk_score", 0),
            it.get("ma_cn", ""), it.get("ten_cn", ""), it.get("module", ""),
            it.get("priority", ""), it.get("complexity", ""),
            " | ".join(it.get("risk_factors", [])),
        ])
    _write_data(
        ws, rows,
        row_fill_fn=lambda i: _fill_by_risk(items[i].get("risk_score", 0)),
        n_cols=len(cols),
    )
    _finalize_sheet(ws, len(rows), len(cols))


def _write_aging_sheet(wb, items: list[dict]) -> None:
    ws = wb.create_sheet("Aging_WIP")
    cols = [
        ("STT", 6), ("Mã CN", 14), ("Tên chức năng", 40), ("Module", 12),
        ("Quy trình", 20), ("Phase", 16), ("Status", 13),
        ("Start", 13), ("End (plan)", 13), ("PIC", 22),
        ("Aging (ngày)", 12), ("Over by (ngày)", 12),
        ("Priority", 12), ("Complexity", 12),
    ]
    _write_banner(ws, "🟡 TASK AGING WIP (In-progress quá lâu)",
                  len(items), "aging", len(cols))
    _write_header(ws, cols)

    rows = []
    for idx, it in enumerate(items):
        rows.append([
            idx + 1,
            it.get("ma_cn", ""), it.get("ten_cn", ""), it.get("module", ""),
            it.get("quy_trinh", ""), it.get("phase", ""), it.get("status", ""),
            it.get("start_date", ""), it.get("end_date", ""),
            ", ".join(it.get("pic", []) if isinstance(it.get("pic"), list) else [str(it.get("pic") or "")]),
            it.get("aging_days", 0), it.get("over_by_days", 0),
            it.get("priority", ""), it.get("complexity", ""),
        ])
    _write_data(
        ws, rows,
        row_fill_fn=lambda i: _fill_by_days(items[i].get("aging_days", 0)),
        n_cols=len(cols),
    )
    _finalize_sheet(ws, len(rows), len(cols))


def _write_dq_sheet(wb, items: list[dict]) -> None:
    ws = wb.create_sheet("Data_Quality")
    cols = [
        ("STT", 6), ("Mã CN", 14), ("Tên chức năng", 32), ("Module", 12),
        ("Phase", 14), ("Mã lỗi", 22), ("Mức", 8),
        ("Mô tả", 40), ("Chi tiết", 40), ("Gợi ý", 30),
    ]
    _write_banner(ws, "⚫ DATA QUALITY — LỖI DỮ LIỆU",
                  len(items), "data_quality", len(cols))
    _write_header(ws, cols)

    rows = []
    for idx, it in enumerate(items):
        rows.append([
            idx + 1,
            it.get("ma_cn", ""), it.get("ten_cn", ""), it.get("module", ""),
            it.get("phase", ""), it.get("code", ""), it.get("severity", ""),
            it.get("label", ""), it.get("detail", ""), it.get("suggestion", ""),
        ])

    def _fill(i):
        sev = (items[i].get("severity") or "").lower()
        if sev == "high":
            return RED_FILL
        if sev == "medium":
            return ORANGE_FILL
        if sev == "low":
            return YELLOW_FILL
        return None

    _write_data(ws, rows, row_fill_fn=_fill, n_cols=len(cols))
    _finalize_sheet(ws, len(rows), len(cols))


def _write_bookmark_sheet(wb, items: list[dict]) -> None:
    ws = wb.create_sheet("Bookmark")
    cols = [
        ("STT", 6), ("Mã CN", 14), ("Tên chức năng", 40), ("Module", 12),
        ("Quy trình", 20), ("Priority", 12), ("Complexity", 12),
        ("Giai đoạn", 16), ("FIT/GAP", 10),
    ]
    _write_banner(ws, "🟣 FUNCTION ĐÃ BOOKMARK",
                  len(items), "bookmark", len(cols))
    _write_header(ws, cols)

    rows = []
    for idx, it in enumerate(items):
        rows.append([
            idx + 1,
            it.get("ma_cn", ""), it.get("ten_cn", ""), it.get("module", ""),
            it.get("quy_trinh", ""), it.get("priority", ""),
            it.get("complexity", ""), it.get("giai_doan", ""),
            it.get("fit_gap", ""),
        ])
    _write_data(ws, rows, n_cols=len(cols))
    _finalize_sheet(ws, len(rows), len(cols))
