"""
Xuất báo cáo tuần MoM (Meeting Minutes) theo mẫu W30.

Sheets:
  1. Cover Page     — mục lục cuộc họp + mã dự án
  2. Master plan    — WBS Module × Phase từ Function List (Start–End, % Closed, PIC)
  3. Gantt          — timeline tuần (ô tô màu theo Start–End)
  4. MoM_W{n}       — biên bản họp tuần (kế hoạch tuần này / tuần tới + overdue)
  5. PM Dashboard   — số liệu + vài biểu đồ Excel tiêu biểu

Ô thiếu data → để trống / "N/A" + ghi chú, không bịa số.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any, Optional

import openpyxl
from openpyxl.chart import BarChart, PieChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from exporter.excel_exporter import (
    BODY_ALIGN,
    GREEN_FILL,
    ORANGE_FILL,
    RED_FILL,
    THIN_BORDER,
    YELLOW_FILL,
    _fill_by_days,
)
from parser.excel_parser import VALID_STATUSES

# Styles MoM — bám mẫu W30 (header #0070C0 trắng, section vàng, module xanh lá)
MOM_HEADER_FILL = PatternFill(start_color="0070C0", end_color="0070C0", fill_type="solid")
MOM_HEADER_FONT = Font(name="Calibri", bold=True, size=11, color="FFFFFF")
MOM_HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)
TITLE_FONT = Font(name="Calibri", bold=True, size=16, color="1F4E79")
TITLE_BAR_FILL = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
TITLE_BAR_FONT = Font(name="Calibri", bold=True, size=14, color="FFFFFF")
SECTION_FILL = PatternFill(start_color="FFC000", end_color="FFC000", fill_type="solid")
SECTION_FONT = Font(name="Calibri", bold=True, size=11, color="FFFFFF")
CONTENT_BAR_FILL = PatternFill(start_color="0070C0", end_color="0070C0", fill_type="solid")
CONTENT_BAR_FONT = Font(name="Calibri", bold=True, size=12, color="FFFFFF")
NOTE_FONT = Font(name="Calibri", italic=True, size=9, color="666666")
GUIDE_FONT = Font(name="Calibri", size=9, italic=True, color="595959")
LABEL_FONT = Font(name="Calibri", bold=True, size=11)
META_LABEL_FILL = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
META_VALUE_FONT = Font(name="Calibri", size=11, color="0000FF")
BODY_MOM_FONT = Font(name="Calibri", size=10)
BODY_MOM_BOLD = Font(name="Calibri", size=10, bold=True)
MODULE_FILL = PatternFill(start_color="A8D08D", end_color="A8D08D", fill_type="solid")
LU_DATE_FILL = PatternFill(start_color="DDEBF7", end_color="DDEBF7", fill_type="solid")
BANNER_FILL = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
BANNER_FONT = Font(name="Calibri", bold=True, size=11, color="9C5700")
GANTT_FILL = PatternFill(start_color="5B9BD5", end_color="5B9BD5", fill_type="solid")
GANTT_TODAY_FILL = PatternFill(start_color="F4B183", end_color="F4B183", fill_type="solid")
ALT_ROW_FILL = PatternFill(start_color="F8F9FA", end_color="F8F9FA", fill_type="solid")
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
LEFT_TOP = Alignment(horizontal="left", vertical="top", wrap_text=True)
LEFT_CENTER = Alignment(horizontal="left", vertical="center", wrap_text=True)
NA = "N/A"

# Giới hạn dòng gợi ý trên MoM (tránh flood khi nhiều phase overlap dài)
_WEEK_PLAN_LIMIT = 40


def _iso_week_label(d: date) -> str:
    """VD: W30 (ISO week)."""
    return f"W{d.isocalendar()[1]:02d}"


def _parse_date(v: Any) -> Optional[date]:
    """Chuẩn hóa mọi kiểu date thường gặp về date | None."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    if not s:
        return None
    # ISO có thể dài hơn 10 (datetime)
    for fmt, n in (("%Y-%m-%d", 10), ("%d/%m/%Y", 10), ("%Y/%m/%d", 10), ("%d-%m-%Y", 10)):
        try:
            return datetime.strptime(s[:n], fmt).date()
        except ValueError:
            continue
    return None


def _fmt_date(v: Any) -> str:
    """Format hiển thị dd/MM/yyyy; rỗng nếu không parse được."""
    d = _parse_date(v)
    return d.strftime("%d/%m/%Y") if d else ""


def _normalize_date_pair(
    start: Any, end: Any,
) -> tuple[Optional[date], Optional[date], bool]:
    """
    Parse Start/End; nếu cả hai có và start > end → swap.

    Returns: (start, end, swapped)
    """
    s = _parse_date(start)
    e = _parse_date(end)
    swapped = False
    if s is not None and e is not None and s > e:
        s, e = e, s
        swapped = True
    return s, e, swapped


def _week_range(d: date) -> tuple[date, date]:
    """Thứ 2 → Chủ nhật của tuần ISO chứa d."""
    start = d - timedelta(days=d.weekday())
    return start, start + timedelta(days=6)


def _ranges_overlap(
    a_start: Optional[date],
    a_end: Optional[date],
    b_start: date,
    b_end: date,
) -> bool:
    """True nếu [a_start, a_end] giao [b_start, b_end] (điểm đơn = start=end)."""
    if a_start is None and a_end is None:
        return False
    s = a_start if a_start is not None else a_end
    e = a_end if a_end is not None else a_start
    assert s is not None and e is not None
    return s <= b_end and e >= b_start


def _normalize_status(status: Any) -> str:
    """Trả status chuẩn nếu khớp VALID_STATUSES (case-insensitive); else giữ nguyên trimmed."""
    if status is None:
        return ""
    s = str(status).strip()
    if not s:
        return ""
    # Số thuần → lỗi lệch cột Estimate MH
    if s.isdigit():
        return ""
    for valid in VALID_STATUSES:
        if s.lower() == valid.lower():
            return valid
    return s


def _style_header_row(ws, row: int, start_col: int, end_col: int) -> None:
    """Header xanh #0070C0, chữ trắng, center — đồng bộ mẫu W30."""
    for c in range(start_col, end_col + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = MOM_HEADER_FONT
        cell.fill = MOM_HEADER_FILL
        cell.alignment = MOM_HEADER_ALIGN
        cell.border = THIN_BORDER
    ws.row_dimensions[row].height = 22


def _apply_border_row(ws, row: int, start_col: int, end_col: int) -> None:
    for c in range(start_col, end_col + 1):
        cell = ws.cell(row=row, column=c)
        cell.border = THIN_BORDER
        if cell.font is None or cell.font.name is None:
            cell.font = BODY_MOM_FONT
        if cell.alignment is None or cell.alignment.vertical is None:
            cell.alignment = BODY_ALIGN


def _style_title_bar(ws, row: int, title: str, end_col: int) -> None:
    """Thanh tiêu đề xanh đậm + chữ trắng (Cover / Gantt / Dashboard)."""
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=end_col)
    cell = ws.cell(row=row, column=1, value=title)
    cell.font = TITLE_BAR_FONT
    cell.fill = TITLE_BAR_FILL
    cell.alignment = Alignment(horizontal="left", vertical="center")
    for c in range(1, end_col + 1):
        ws.cell(row=row, column=c).fill = TITLE_BAR_FILL
        ws.cell(row=row, column=c).border = THIN_BORDER
    ws.row_dimensions[row].height = 26


def _set_print_landscape(ws, *, fit_width: bool = True) -> None:
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToPage = True
    ws.page_setup.fitToWidth = 1 if fit_width else 0
    ws.page_setup.fitToHeight = 0
    ws.print_title_rows = "1:3"


def _collect_week_plan(
    parsed_data,
    week_start: date,
    week_end: date,
    *,
    limit: int = _WEEK_PLAN_LIMIT,
) -> list[dict]:
    """
    Công việc gợi ý trong tuần ISO (đủ dùng PM, không flood overlap dài):
      - Phase chưa Closed/Cancelled
      - Sau normalize/swap Start–End: End nằm trong tuần HOẶC Start nằm trong tuần
      - Không lấy phase chỉ "giao tuần" dài (overlap-only) — gây trùng A/B và đầy limit
    Ưu tiên: End trong tuần → Start trong tuần.
    """
    if parsed_data is None:
        return []
    items: list[dict] = []
    for r in parsed_data.rows:
        ma = r.meta.get("ma_cn") or ""
        ten = r.meta.get("ten_cn") or ""
        module = r.meta.get("module") or ""
        for phase_name, pd in (r.phases or {}).items():
            st = _normalize_status(pd.status)
            if st in ("Closed", "Cancelled"):
                continue
            s, e, swapped = _normalize_date_pair(pd.start_date, pd.end_date)
            end_in = e is not None and week_start <= e <= week_end
            start_in = s is not None and week_start <= s <= week_end
            if not end_in and not start_in:
                continue
            priority = 0 if end_in else 1
            label = f"[{phase_name}] {ma} — {ten}".strip(" —")
            if not ma and not ten:
                label = f"[{phase_name}]"
            pics = ", ".join(pd.pics or [])
            note = (("swap Start↔End; " if swapped else "") + (pd.note or "")).strip()
            items.append({
                "ten": label,
                "pic": pics,
                "from": _fmt_date(s),
                "to": _fmt_date(e),
                "status": st,
                "note": note[:80].rstrip("; "),
                "module": module,
                "phase": phase_name,
                "priority": priority,
                "_end": e or date.max,
                "_start": s or date.max,
            })
    items.sort(key=lambda x: (x["priority"], x["_end"], x["module"], x["phase"]))
    out = items[:limit]
    for it in out:
        it.pop("_end", None)
        it.pop("_start", None)
        it.pop("priority", None)
    return out


def _phase_dates_from_rows(
    parsed_data,
    module: str,
    phase: str,
    today: Optional[date] = None,
) -> tuple[Optional[date], Optional[date], int]:
    """
    Min Start / max End sau swap từng function; bỏ outlier năm.
    Returns: (start, end, n_dated).
    """
    from analyzer.gantt_calendar import _is_outlier_date

    starts: list[date] = []
    ends: list[date] = []
    if parsed_data is None:
        return None, None, 0
    for r in parsed_data.rows:
        if (r.meta.get("module") or "") != module:
            continue
        pd = (r.phases or {}).get(phase)
        if not pd:
            continue
        ps, pe, _ = _normalize_date_pair(pd.start_date, pd.end_date)
        if ps and not _is_outlier_date(ps, today):
            starts.append(ps)
        if pe and not _is_outlier_date(pe, today):
            ends.append(pe)
    return (
        min(starts) if starts else None,
        max(ends) if ends else None,
        len(starts) + len(ends),
    )


def _format_phase_status(pct: Any, top_status: str) -> str:
    """Tránh chữ dư kiểu 'Closed · 100.0% Closed'."""
    if pct is not None and pct != "":
        try:
            pct_f = float(pct)
            pct_txt = f"{pct_f:g}% Closed"
        except (TypeError, ValueError):
            pct_txt = f"{pct}% Closed"
        if top_status and top_status not in ("Closed", "—"):
            return f"{top_status} · {pct_txt}"
        return pct_txt
    return top_status or ""


def _build_master_rows(
    metrics: dict,
    parsed_data,
    today: Optional[date] = None,
) -> list[dict]:
    """
    WBS-like: mỗi Module 1 dòng cha + mỗi Phase có date 1 dòng con.
    % / n từ timeline_data; Start–End ưu tiên aggregate từ ParsedData (đã swap).
    """
    timeline = (metrics or {}).get("timeline_data") or {}
    modules = timeline.get("modules") or []
    phases = timeline.get("phases") or []
    data = timeline.get("data") or {}
    if not modules and parsed_data is not None:
        modules = list(parsed_data.all_modules or [])
        phases = list(parsed_data.all_phases or [])

    pic_map: dict[tuple[str, str], list[str]] = {}
    status_map: dict[tuple[str, str], dict[str, int]] = {}
    if parsed_data is not None:
        for r in parsed_data.rows:
            mod = r.meta.get("module") or ""
            for ph, pd in (r.phases or {}).items():
                key = (mod, ph)
                for p in (pd.pics or []):
                    pic_map.setdefault(key, [])
                    if p not in pic_map[key]:
                        pic_map[key].append(p)
                st = _normalize_status(pd.status)
                if st:
                    status_map.setdefault(key, {})
                    status_map[key][st] = status_map[key].get(st, 0) + 1

    rows: list[dict] = []
    stt_mod = 0
    for module in modules:
        mod_data = data.get(module) or {}
        mod_starts: list[date] = []
        mod_ends: list[date] = []
        phase_children: list[dict] = []
        for ph in phases:
            cell = mod_data.get(ph) or {}
            s, e, n_dated = _phase_dates_from_rows(parsed_data, module, ph, today)
            if s is None and e is None:
                s, e, _ = _normalize_date_pair(cell.get("start"), cell.get("end"))
            if s is None and e is None and not cell:
                continue
            if s is None and e is None and not (cell.get("total") or cell.get("pct_closed") is not None):
                continue
            if s:
                mod_starts.append(s)
            if e:
                mod_ends.append(e)
            pct = cell.get("pct_closed")
            closed = cell.get("closed")
            total = cell.get("total")
            if pct is None and total:
                pct = round(100.0 * int(closed or 0) / int(total), 1)
            counts = status_map.get((module, ph)) or {}
            top_status = max(counts.items(), key=lambda kv: kv[1])[0] if counts else ""
            status_txt = _format_phase_status(pct, top_status)
            pics = pic_map.get((module, ph)) or []
            note_bits = []
            if total:
                note_bits.append(f"n={total}")
            elif n_dated:
                note_bits.append(f"dated={n_dated}")
            phase_children.append({
                "level": 1,
                "name": f"    {ph}",
                "status": status_txt,
                "pic_kdg": ", ".join(pics[:4]) if pics else "",
                "start": s,
                "end": e,
                "note": " · ".join(note_bits),
                "pct": pct if pct is not None else "",
            })

        if not phase_children and not mod_starts and not mod_ends:
            continue
        stt_mod += 1
        mod_ov = None
        for m in (metrics or {}).get("module_overview") or []:
            if (m.get("module") or m.get("label")) == module:
                mod_ov = m
                break
        mod_pct = mod_ov.get("progress_pct") if mod_ov else None
        mod_od = mod_ov.get("overdue_count") if mod_ov else None
        active = (mod_ov or {}).get("active_phase") or ""
        note_parts = []
        if mod_ov:
            note_parts.append(f"{mod_ov.get('total', 0)} CN")
        if mod_od:
            note_parts.append(f"overdue={mod_od}")
        if active:
            note_parts.append(f"phase: {active}")
        rows.append({
            "level": 0,
            "stt": str(stt_mod),
            "name": module,
            "status": f"{mod_pct:g}% Closed" if isinstance(mod_pct, (int, float)) else (
                f"{mod_pct}% Closed" if mod_pct is not None else ""
            ),
            "pic_kdg": "",
            "start": min(mod_starts) if mod_starts else None,
            "end": max(mod_ends) if mod_ends else None,
            "note": " · ".join(note_parts),
            "pct": mod_pct if mod_pct is not None else "",
        })
        for i, ch in enumerate(phase_children, 1):
            ch["stt"] = f"{stt_mod}.{i}"
            rows.append(ch)
    return rows


def _write_cover(
    wb,
    project_code: str,
    week_label: str,
    meeting_sheet_name: str,
    today: date,
) -> None:
    ws = wb.create_sheet("Cover Page", 0)
    widths = {
        "A": 2, "B": 18, "C": 14, "D": 36, "E": 10, "F": 12,
        "G": 28, "H": 10, "I": 10, "J": 10, "K": 10,
    }
    for col, w in widths.items():
        ws.column_dimensions[col].width = w

    # Thanh tiêu đề
    ws.merge_cells("B2:H2")
    ws["B2"] = "MEETING MINUTES — iHRP Tracker"
    ws["B2"].font = TITLE_BAR_FONT
    ws["B2"].fill = TITLE_BAR_FILL
    ws["B2"].alignment = Alignment(horizontal="left", vertical="center")
    for c in range(2, 9):
        ws.cell(row=2, column=c).fill = TITLE_BAR_FILL
    ws.row_dimensions[2].height = 28

    ws["B4"] = "Project Code"
    ws["B4"].font = LABEL_FONT
    ws["B4"].fill = META_LABEL_FILL
    ws["C4"] = project_code or NA
    ws["C4"].font = Font(name="Calibri", bold=True, size=13, color="1F4E79")
    ws.merge_cells("C4:D4")

    ws["F4"] = "Meeting Minutes Records"
    ws["F4"].font = TITLE_FONT
    ws["F4"].alignment = Alignment(horizontal="right", vertical="center")
    ws.merge_cells("F4:H4")

    ws["B5"] = "Version"
    ws["B5"].font = LABEL_FONT
    ws["B5"].fill = META_LABEL_FILL
    ws["C5"] = "v1.2 (auto từ iHRP Tracker)"
    ws["C5"].font = BODY_MOM_FONT

    ws["E5"] = "Tuần"
    ws["E5"].font = LABEL_FONT
    ws["E5"].fill = META_LABEL_FILL
    ws["E5"].alignment = CENTER
    ws["F5"] = week_label
    ws["F5"].font = Font(name="Calibri", bold=True, size=14, color="C00000")
    ws["F5"].alignment = CENTER
    ws["F5"].fill = BANNER_FILL

    ws.merge_cells("B6:H6")
    ws["B6"] = (
        f"Hướng dẫn: Master/Gantt từ Function List · MoM gợi ý deadline tuần này/tới · "
        f"điền giờ họp & người tham gia trước khi gửi · xuất {today.strftime('%d/%m/%Y')}"
    )
    ws["B6"].font = GUIDE_FONT
    ws["B6"].alignment = LEFT_CENTER
    ws.row_dimensions[6].height = 20

    headers = ["Sheet Name", "Date", "Review subject"]
    for i, h in enumerate(headers, 2):
        cell = ws.cell(row=8, column=i, value=h)
    _style_header_row(ws, 8, 2, 7)
    ws.merge_cells("D8:G8")

    toc = [
        ("Master plan", "WBS Module × Phase (Start–End + % Closed từ Function List)"),
        ("Gantt", "Timeline tuần quanh ngày xuất (ô tô màu theo kế hoạch)"),
        (meeting_sheet_name, f"Họp định kỳ dự án — {week_label}"),
        ("PM Dashboard", "Tóm tắt metrics + biểu đồ Excel"),
    ]
    for i, (sheet, subject) in enumerate(toc):
        r = 9 + i
        ws.cell(row=r, column=2, value=sheet).font = BODY_MOM_BOLD
        ws.cell(row=r, column=3, value=today.strftime("%d/%m/%Y")).font = BODY_MOM_FONT
        ws.cell(row=r, column=3).alignment = CENTER
        ws.cell(row=r, column=4, value=subject).font = BODY_MOM_FONT
        ws.cell(row=r, column=4).alignment = LEFT_CENTER
        ws.merge_cells(f"D{r}:G{r}")
        for c in range(2, 8):
            cell = ws.cell(row=r, column=c)
            cell.border = THIN_BORDER
            if i % 2 == 1 and c >= 2:
                cell.fill = ALT_ROW_FILL
        ws.row_dimensions[r].height = 18

    for r in range(13, 18):
        ws.merge_cells(f"D{r}:G{r}")
        for c in range(2, 8):
            ws.cell(row=r, column=c).border = THIN_BORDER
        ws.row_dimensions[r].height = 16

    ws.freeze_panes = "B9"
    _set_print_landscape(ws)


def _write_master_plan(wb, metrics: dict, parsed_data, today: Optional[date] = None) -> None:
    """Master plan: WBS Module × Phase từ timeline Function List."""
    ws = wb.create_sheet("Master plan")
    widths = {
        "A": 3, "B": 7, "C": 48, "D": 18, "E": 10, "F": 16,
        "G": 14, "H": 14, "I": 14, "J": 14, "K": 24,
    }
    for col, w in widths.items():
        ws.column_dimensions[col].width = w

    ws["I1"] = "Cập nhật liên tục"
    ws["I1"].font = BANNER_FONT
    ws["I1"].fill = BANNER_FILL
    ws["I1"].alignment = CENTER
    ws.merge_cells("I1:J1")
    ws["I1"].border = THIN_BORDER
    ws["J1"].border = THIN_BORDER
    ws["J1"].fill = BANNER_FILL

    ws["B2"] = "STT"
    ws["C2"] = "Công việc"
    ws["D2"] = "Tình trạng"
    ws["E2"] = "PIC"
    ws["G2"] = "Kế hoạch v1.0"
    ws["I2"] = "Kế hoạch LU"
    ws["K2"] = "Ghi chú"
    ws.merge_cells("B2:B3")
    ws.merge_cells("C2:C3")
    ws.merge_cells("D2:D3")
    ws.merge_cells("E2:F2")
    ws.merge_cells("G2:H2")
    ws.merge_cells("I2:J2")
    ws.merge_cells("K2:K3")
    ws["E3"] = "FIS"
    ws["F3"] = "KDG"
    ws["G3"] = "Thời gian bắt đầu"
    ws["H3"] = "Thời gian kết thúc"
    ws["I3"] = "Thời gian bắt đầu"
    ws["J3"] = "Thời gian kết thúc"

    for r in (2, 3):
        for c in range(2, 12):
            cell = ws.cell(row=r, column=c)
            cell.font = MOM_HEADER_FONT
            cell.fill = MOM_HEADER_FILL
            cell.alignment = MOM_HEADER_ALIGN
            cell.border = THIN_BORDER
        ws.row_dimensions[r].height = 20

    master_rows = _build_master_rows(metrics, parsed_data, today=today)
    if not master_rows:
        ws["B4"] = ""
        ws["C4"] = (
            "N/A — chưa có Start/End phase trong Function List để dựng Master plan."
        )
        ws["C4"].font = NOTE_FONT
        ws.merge_cells("C4:K4")
        for r in range(5, 10):
            ws.cell(row=r, column=2, value=r - 4)
            for c in range(2, 12):
                ws.cell(row=r, column=c).border = THIN_BORDER
                ws.cell(row=r, column=c).font = BODY_MOM_FONT
        return

    row = 4
    for item in master_rows:
        ws.cell(row=row, column=2, value=item.get("stt", ""))
        # Bỏ indent khoảng trắng thừa — dùng alignment indent trực quan hơn
        name = (item.get("name") or "").strip()
        ws.cell(row=row, column=3, value=name)
        ws.cell(row=row, column=4, value=item.get("status", ""))
        ws.cell(row=row, column=5, value="")  # FIS — không có trong FL
        ws.cell(row=row, column=6, value=item.get("pic_kdg", ""))
        # v1.0 để trống (baseline PM điền); LU = mốc Start/End hiện tại từ FL
        ws.cell(row=row, column=7, value="")
        ws.cell(row=row, column=8, value="")
        ws.cell(row=row, column=9, value=_fmt_date(item.get("start")))
        ws.cell(row=row, column=10, value=_fmt_date(item.get("end")))
        ws.cell(row=row, column=11, value=item.get("note", ""))
        is_mod = item.get("level") == 0
        for c in range(2, 12):
            cell = ws.cell(row=row, column=c)
            cell.border = THIN_BORDER
            cell.font = BODY_MOM_BOLD if is_mod else BODY_MOM_FONT
            if c == 3:
                cell.alignment = LEFT_CENTER
                if not is_mod:
                    cell.alignment = Alignment(
                        horizontal="left", vertical="center", wrap_text=True, indent=1,
                    )
            elif c in (4, 6, 11):
                cell.alignment = LEFT_CENTER
            else:
                cell.alignment = CENTER
            if is_mod:
                cell.fill = MODULE_FILL
            elif c in (9, 10) and cell.value:
                cell.fill = LU_DATE_FILL
        ws.row_dimensions[row].height = 18
        row += 1

    ws.cell(
        row=row + 1, column=2,
        value="Nguồn FL (đã swap From>To). PIC FIS trống · LU = mốc hiện tại · v1.0 = baseline PM điền.",
    )
    ws.cell(row=row + 1, column=2).font = GUIDE_FONT
    ws.merge_cells(start_row=row + 1, start_column=2, end_row=row + 1, end_column=11)
    ws.freeze_panes = "C4"
    _set_print_landscape(ws)


def _iter_weeks(start: date, end: date) -> list[tuple[date, date, str]]:
    """Danh sách (week_start, week_end, label Wxx) bao phủ [start, end]."""
    if start > end:
        start, end = end, start
    cur = start - timedelta(days=start.weekday())
    weeks = []
    guard = 0
    while cur <= end and guard < 80:
        we = cur + timedelta(days=6)
        weeks.append((cur, we, _iso_week_label(cur)))
        cur = cur + timedelta(days=7)
        guard += 1
    return weeks


def _write_gantt_sheet(wb, metrics: dict, parsed_data, today: date) -> None:
    """Sheet Gantt: hàng = Module × Phase giao cửa sổ; cột = tuần cố định quanh today."""
    ws = wb.create_sheet("Gantt")
    # Cửa sổ cố định quanh today — dễ đọc, không kéo từ Dec/2025
    min_d = today - timedelta(weeks=6)
    max_d = today + timedelta(weeks=14)
    weeks = _iter_weeks(min_d, max_d)
    win_start, win_end = weeks[0][0], weeks[-1][1]

    all_rows = _build_master_rows(metrics, parsed_data, today=today)
    # Chỉ giữ hàng giao cửa sổ (module cha giữ nếu còn child)
    visible: list[dict] = []
    i = 0
    while i < len(all_rows):
        item = all_rows[i]
        if item.get("level") == 0:
            children = []
            j = i + 1
            while j < len(all_rows) and all_rows[j].get("level") == 1:
                ch = all_rows[j]
                s, e, _ = _normalize_date_pair(ch.get("start"), ch.get("end"))
                if _ranges_overlap(s, e, win_start, win_end):
                    children.append(ch)
                j += 1
            s0, e0, _ = _normalize_date_pair(item.get("start"), item.get("end"))
            if children or _ranges_overlap(s0, e0, win_start, win_end):
                visible.append(item)
                visible.extend(children)
            i = j
        else:
            s, e, _ = _normalize_date_pair(item.get("start"), item.get("end"))
            if _ranges_overlap(s, e, win_start, win_end):
                visible.append(item)
            i += 1

    end_col = 4 + max(len(weeks), 1)
    if not visible:
        _style_title_bar(ws, 1, "GANTT", 6)
        ws["A3"] = (
            f"N/A — không có Module/Phase giao cửa sổ "
            f"{win_start.strftime('%d/%m/%Y')}–{win_end.strftime('%d/%m/%Y')}."
        )
        ws["A3"].font = NOTE_FONT
        return

    ws.column_dimensions["A"].width = 7
    ws.column_dimensions["B"].width = 28
    ws.column_dimensions["C"].width = 12
    ws.column_dimensions["D"].width = 12
    for i in range(len(weeks)):
        ws.column_dimensions[get_column_letter(5 + i)].width = 7

    title = (
        f"GANTT — Module × Phase theo tuần "
        f"({win_start.strftime('%d/%m')}–{win_end.strftime('%d/%m/%Y')}, xuất {today.strftime('%d/%m/%Y')})"
    )
    _style_title_bar(ws, 1, title, end_col)

    # Legend
    ws["A2"] = "Chú thích:"
    ws["A2"].font = LABEL_FONT
    ws["B2"] = "Trong kế hoạch"
    ws["B2"].fill = GANTT_FILL
    ws["B2"].font = Font(name="Calibri", size=9, color="FFFFFF", bold=True)
    ws["B2"].alignment = CENTER
    ws["C2"] = "Tuần hiện tại"
    ws["C2"].fill = GANTT_TODAY_FILL
    ws["C2"].font = Font(name="Calibri", size=9, bold=True)
    ws["C2"].alignment = CENTER
    ws["D2"] = "Module (nhóm)"
    ws["D2"].fill = MODULE_FILL
    ws["D2"].font = Font(name="Calibri", size=9, bold=True)
    ws["D2"].alignment = CENTER
    ws.merge_cells(start_row=2, start_column=5, end_row=2, end_column=min(end_col, 10))
    ws.cell(
        row=2, column=5,
        value="Ô xanh = Start–End giao tuần · Cam = tuần hiện tại (không bar)",
    ).font = GUIDE_FONT
    ws.row_dimensions[2].height = 18

    headers = ["STT", "Công việc", "Từ ngày", "Đến ngày"] + [w[2] for w in weeks]
    for i, h in enumerate(headers, 1):
        cell = ws.cell(row=3, column=i, value=h)
    _style_header_row(ws, 3, 1, end_col)

    today_week = _week_range(today)[0]
    # Highlight cột tuần hiện tại trên header
    for wi, (ws_d, _we_d, _) in enumerate(weeks):
        if ws_d == today_week:
            cell = ws.cell(row=3, column=5 + wi)
            cell.fill = GANTT_TODAY_FILL
            cell.font = Font(name="Calibri", bold=True, size=10, color="000000")

    for ri, item in enumerate(visible):
        row = 4 + ri
        s, e, _ = _normalize_date_pair(item.get("start"), item.get("end"))
        name = (item.get("name") or "").strip()
        vals = [item.get("stt", ""), name, _fmt_date(s), _fmt_date(e)]
        is_mod = item.get("level") == 0
        for c, v in enumerate(vals, 1):
            cell = ws.cell(row=row, column=c, value=v)
            cell.border = THIN_BORDER
            cell.font = BODY_MOM_BOLD if is_mod else Font(name="Calibri", size=9)
            if c == 2:
                cell.alignment = LEFT_CENTER if is_mod else Alignment(
                    horizontal="left", vertical="center", wrap_text=True, indent=1,
                )
            else:
                cell.alignment = CENTER
            if is_mod:
                cell.fill = MODULE_FILL
        for wi, (ws_d, we_d, _) in enumerate(weeks):
            cell = ws.cell(row=row, column=5 + wi, value="")
            cell.border = THIN_BORDER
            has_bar = False
            if s is not None or e is not None:
                if _ranges_overlap(s, e, ws_d, we_d):
                    cell.fill = GANTT_FILL
                    has_bar = True
            if ws_d == today_week and not has_bar:
                cell.fill = GANTT_TODAY_FILL
        ws.row_dimensions[row].height = 16

    note_row = 4 + len(visible) + 1
    ws.cell(
        row=note_row, column=1,
        value="Chỉ hiện hàng giao cửa sổ ±6…+14 tuần quanh ngày xuất.",
    )
    ws.cell(row=note_row, column=1).font = GUIDE_FONT
    ws.merge_cells(start_row=note_row, start_column=1, end_row=note_row, end_column=6)
    ws.freeze_panes = "E4"
    _set_print_landscape(ws, fit_width=False)


def _write_mom_sheet(
    wb,
    sheet_name: str,
    week_label: str,
    today: date,
    metrics: dict,
    parsed_data=None,
) -> None:
    """Biên bản họp tuần — cấu trúc bám sheet mẫu W30."""
    ws = wb.create_sheet(sheet_name)
    col_widths = {1: 2.5, 2: 5, 3: 48, 4: 14, 5: 28, 6: 12, 7: 12, 8: 12}
    for c, w in col_widths.items():
        ws.column_dimensions[get_column_letter(c)].width = w

    week_start, week_end = _week_range(today)
    next_start = week_start + timedelta(days=7)
    next_end = week_end + timedelta(days=7)

    # === Meta họp ===
    meta_rows = [
        (2, "Ngày/Date", today.strftime("%d/%m/%Y"), True),
        (3, "Giờ/Time", "", False),
        (4, "Tên/Subject", f"Họp định kỳ dự án — {week_label}", True),
        (5, "Người tham gia/Committee", "", False),
    ]
    for r, label, value, filled in meta_rows:
        ws.cell(row=r, column=2, value=label).font = LABEL_FONT
        ws.merge_cells(f"B{r}:C{r}")
        ws.cell(row=r, column=4, value=value)
        if r == 5:
            ws.merge_cells(f"D{r}:H{r}")
            ws.row_dimensions[r].height = 36
        elif r == 4:
            ws.merge_cells(f"D{r}:H{r}")
        else:
            ws.merge_cells(f"D{r}:E{r}")
        for c in range(2, 9):
            cell = ws.cell(row=r, column=c)
            cell.border = THIN_BORDER
            if c <= 3:
                cell.fill = META_LABEL_FILL
                cell.alignment = LEFT_CENTER
            else:
                cell.font = META_VALUE_FONT if filled or value else BODY_MOM_FONT
                cell.alignment = LEFT_CENTER if r in (4, 5) else CENTER

    ws["F2"] = "Return to Cover Page"
    ws["F2"].font = Font(name="Calibri", italic=True, size=10, color="0070C0")
    ws["F2"].alignment = CENTER
    ws.merge_cells("F2:H2")

    ws.merge_cells("B7:H7")
    ws["B7"] = "Nội dung / Content"
    ws["B7"].font = CONTENT_BAR_FONT
    for c in range(2, 9):
        ws.cell(row=7, column=c).fill = CONTENT_BAR_FILL
        ws.cell(row=7, column=c).border = THIN_BORDER
        ws.cell(row=7, column=c).font = CONTENT_BAR_FONT
    ws.row_dimensions[7].height = 22

    headers = ["STT", "Công việc", "PIC", "Ghi chú", "Từ ngày", "Đến ngày", "Tình trạng"]
    for i, h in enumerate(headers, 2):
        ws.cell(row=8, column=i, value=h)
    _style_header_row(ws, 8, 1, 8)

    def _write_plan_section(row: int, letter: str, title: str, items: list[dict], empty_hint: str) -> int:
        ws.cell(row=row, column=2, value=letter)
        ws.cell(row=row, column=3, value=title)
        for c in range(2, 9):
            ws.cell(row=row, column=c).fill = SECTION_FILL
            ws.cell(row=row, column=c).font = SECTION_FONT
            ws.cell(row=row, column=c).border = THIN_BORDER
            ws.cell(row=row, column=c).alignment = LEFT_CENTER
        ws.cell(row=row, column=1).border = THIN_BORDER
        ws.row_dimensions[row].height = 20
        row += 1
        if items:
            for idx, it in enumerate(items, 1):
                vals = [idx, it["ten"], it["pic"], it.get("note", ""), it["from"], it["to"], it["status"]]
                for c, v in enumerate(vals, 2):
                    cell = ws.cell(row=row, column=c, value=v)
                    if c in (6, 7, 8):
                        cell.alignment = CENTER
                    elif c == 3:
                        cell.alignment = LEFT_TOP
                    else:
                        cell.alignment = LEFT_CENTER
                    cell.font = BODY_MOM_FONT
                _apply_border_row(ws, row, 1, 8)
                # Wrap tên CN — ước lượng chiều cao
                ten_len = len(str(it.get("ten") or ""))
                ws.row_dimensions[row].height = 28 if ten_len > 60 else 18
                row += 1
        else:
            ws.cell(row=row, column=2, value=1)
            ws.cell(row=row, column=3, value=empty_hint)
            ws.cell(row=row, column=3).font = NOTE_FONT
            _apply_border_row(ws, row, 1, 8)
            row += 1
            for i in range(2, 4):
                ws.cell(row=row, column=2, value=i)
                _apply_border_row(ws, row, 1, 8)
                row += 1
        return row

    this_week = _collect_week_plan(parsed_data, week_start, week_end)
    next_week = _collect_week_plan(parsed_data, next_start, next_end)

    row = 9
    row = _write_plan_section(
        row, "A",
        f"KẾ HOẠCH TUẦN NÀY ({week_start.strftime('%d/%m')}–{week_end.strftime('%d/%m/%Y')})",
        this_week,
        f"Không có phase Start/End trong tuần này. PM điền tay.",
    )

    row += 1  # khoảng cách giữa block
    row = _write_plan_section(
        row, "B",
        f"KẾ HOẠCH TUẦN TỚI ({next_start.strftime('%d/%m')}–{next_end.strftime('%d/%m/%Y')})",
        next_week,
        f"Không có phase Start/End trong tuần tới. PM điền tay.",
    )

    # --- Hành động (overdue, sort severity) ---
    row += 1
    ws.cell(row=row, column=2, value="C")
    ws.cell(row=row, column=3, value="Hành động (gợi ý từ Overdue)")
    ws.cell(row=row, column=6, value="PIC")
    ws.cell(row=row, column=7, value="Ngày")
    ws.cell(row=row, column=8, value="Trạng thái")
    ws.merge_cells(f"C{row}:E{row}")
    for c in range(1, 9):
        cell = ws.cell(row=row, column=c)
        cell.font = MOM_HEADER_FONT
        cell.fill = MOM_HEADER_FILL
        cell.alignment = MOM_HEADER_ALIGN
        cell.border = THIN_BORDER
    ws.row_dimensions[row].height = 20

    overdue = sorted(
        list(metrics.get("overdue_list") or []),
        key=lambda x: (-int(x.get("days_overdue") or 0), x.get("end_date") or ""),
    )[:15]
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
            ws.cell(row=row, column=8, value=_normalize_status(it.get("status")) or "Open")
            fill = _fill_by_days(int(it.get("days_overdue") or 0))
            for c in range(1, 9):
                cell = ws.cell(row=row, column=c)
                cell.border = THIN_BORDER
                cell.font = BODY_MOM_FONT
                cell.alignment = CENTER if c >= 6 else LEFT_TOP
                if fill and c >= 2:
                    cell.fill = fill
            ws.row_dimensions[row].height = 28 if len(ten) > 50 else 18
            row += 1
    else:
        ws.cell(row=row, column=2, value=1)
        ws.cell(row=row, column=3, value="Không có task overdue.")
        ws.cell(row=row, column=3).font = NOTE_FONT
        ws.merge_cells(f"C{row}:E{row}")
        _apply_border_row(ws, row, 1, 8)
        row += 1
        for i in range(2, 4):
            ws.cell(row=row, column=2, value=i)
            ws.merge_cells(f"C{row}:E{row}")
            _apply_border_row(ws, row, 1, 8)
            row += 1

    row += 1
    ws.merge_cells(f"B{row}:H{row}")
    ws.cell(
        row=row, column=2,
        value=f"Gợi ý auto {today.strftime('%d/%m/%Y')} · Điền giờ họp / người tham gia trước khi gửi.",
    ).font = GUIDE_FONT
    ws.freeze_panes = "C9"
    _set_print_landscape(ws)


def _block_title(ws, row: int, title: str, n_cols: int = 8) -> int:
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=n_cols)
    cell = ws.cell(row=row, column=1, value=title)
    cell.font = SECTION_FONT
    cell.fill = SECTION_FILL
    cell.alignment = LEFT_CENTER
    for c in range(1, n_cols + 1):
        ws.cell(row=row, column=c).fill = SECTION_FILL
        ws.cell(row=row, column=c).border = THIN_BORDER
        ws.cell(row=row, column=c).font = SECTION_FONT
    ws.row_dimensions[row].height = 20
    return row + 1


def _write_pm_dashboard(wb, metrics: dict, today: date, week_label: str) -> None:
    """
    Sheet PM Dashboard — block số liệu + 3 chart Excel:
      1. Tóm tắt
      2. Overdue (sort ngày trễ)
      3. Tiến độ theo phase (% Closed) + bar chart
      4. Module (sort % / overdue) + bar overdue
      5. PIC workload (sort tải) + bar top PIC
    """
    ws = wb.create_sheet("PM Dashboard")
    for i in range(1, 12):
        ws.column_dimensions[get_column_letter(i)].width = 13
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 32
    ws.column_dimensions["D"].width = 12
    ws.column_dimensions["E"].width = 12
    ws.column_dimensions["F"].width = 12
    ws.column_dimensions["G"].width = 11
    ws.column_dimensions["H"].width = 14
    ws.column_dimensions["I"].width = 12

    _style_title_bar(
        ws, 1,
        f"BẢNG ĐIỀU KHIỂN PM — Function List ({week_label})",
        9,
    )

    ws.merge_cells("A2:I2")
    ws["A2"] = f"Xuất ngày {today.strftime('%d/%m/%Y')} — số liệu từ metrics engine"
    ws["A2"].font = GUIDE_FONT
    ws["A2"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 16

    summary = metrics.get("summary") or {}
    row = 4

    # --- 1. Summary ---
    row = _block_title(ws, row, "1. TÓM TẮT DỰ ÁN")
    cards = [
        ("Tổng chức năng", summary.get("total_functions", NA)),
        ("Tiến độ chung (%)", summary.get("overall_progress_pct", NA)),
        ("Số function đang trễ", summary.get("total_overdue", NA)),
        ("Số bản ghi phase trễ", summary.get("total_overdue_records", NA)),
        ("Chưa có PIC", summary.get("unassigned_count", NA)),
        ("Rủi ro cao (score ≥50)", summary.get("high_risk_count", NA)),
        ("Số Module", summary.get("modules_count", NA)),
        ("Số Phase", summary.get("phases_count", NA)),
    ]
    ws.cell(row=row, column=1, value="Chỉ số")
    ws.cell(row=row, column=2, value="Giá trị")
    _style_header_row(ws, row, 1, 2)
    row += 1
    for label, val in cards:
        ws.cell(row=row, column=1, value=label).font = LABEL_FONT
        ws.cell(row=row, column=1).border = THIN_BORDER
        c = ws.cell(row=row, column=2, value=val if val is not None else NA)
        c.font = BODY_MOM_FONT
        c.border = THIN_BORDER
        c.alignment = Alignment(horizontal="right", vertical="center")
        if "trễ" in label.lower() and isinstance(val, (int, float)) and val > 0:
            c.fill = RED_FILL
        row += 1

    row += 2
    # --- 2. Overdue ---
    row = _block_title(ws, row, "2. CÔNG VIỆC TRỄ (top 20 — sắp theo số ngày trễ ↓)", n_cols=9)
    overdue = sorted(
        list(metrics.get("overdue_list") or []),
        key=lambda x: (-int(x.get("days_overdue") or 0), x.get("module") or "", x.get("ma_cn") or ""),
    )[:20]
    ov_headers = ["STT", "Mã CN", "Tên chức năng", "Module", "Phase", "Deadline", "Ngày trễ", "Status", "PIC"]
    for i, h in enumerate(ov_headers, 1):
        ws.cell(row=row, column=i, value=h)
    _style_header_row(ws, row, 1, 9)
    row += 1
    if not overdue:
        ws.cell(row=row, column=1, value="Không có task overdue.").font = NOTE_FONT
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
                _normalize_status(it.get("status")),
                ", ".join(it.get("pic") or []),
            ]
            fill = _fill_by_days(int(it.get("days_overdue") or 0))
            for c, v in enumerate(vals, 1):
                cell = ws.cell(row=row, column=c, value=v)
                cell.font = BODY_MOM_FONT
                cell.border = THIN_BORDER
                cell.alignment = LEFT_TOP if c == 3 else CENTER if c in (1, 6, 7) else LEFT_CENTER
                if fill:
                    cell.fill = fill
            ten = str(it.get("ten_cn") or "")
            ws.row_dimensions[row].height = 28 if len(ten) > 40 else 16
            row += 1

    row += 2
    # --- 3. Phase progress + chart data ---
    row = _block_title(ws, row, "3. TIẾN ĐỘ THEO PHASE (% Closed trên status đã fill)", n_cols=5)
    stacked = metrics.get("phase_progress_stacked") or {}
    phases = list(stacked.get("phases") or [])
    statuses = list(stacked.get("statuses") or [])
    pdata = stacked.get("data") or {}
    phase_chart_start = None
    phase_chart_end = None
    if not phases:
        ws.cell(row=row, column=1, value="Chưa có dữ liệu phase.").font = NOTE_FONT
        row += 1
    else:
        hdr = ["Phase", "% Closed", "Closed", "Tổng có status"]
        for i, h in enumerate(hdr, 1):
            ws.cell(row=row, column=i, value=h)
        _style_header_row(ws, row, 1, 4)
        row += 1
        phase_chart_start = row
        phase_rows_tmp = []
        # Giữ thứ tự phase pipeline gốc; % = Closed / (tổng status ≠ Blank)
        status_keys = [s for s in statuses if s != "(Blank)"]
        for ph in phases:
            counts = pdata.get(ph) or {}
            closed = int(counts.get("Closed", 0) or 0)
            total = sum(int(counts.get(s, 0) or 0) for s in status_keys)
            pct = round(closed / total * 100, 1) if total > 0 else 0.0
            phase_rows_tmp.append((ph, pct, closed, total))
        for ph, pct, closed, total in phase_rows_tmp:
            vals = [ph, pct, closed, total]
            for c, v in enumerate(vals, 1):
                cell = ws.cell(row=row, column=c, value=v)
                cell.font = BODY_MOM_FONT
                cell.border = THIN_BORDER
                cell.alignment = CENTER if c > 1 else LEFT_CENTER
            if total > 0 and pct >= 80:
                ws.cell(row=row, column=1).fill = GREEN_FILL
            elif total > 0 and pct < 30:
                ws.cell(row=row, column=1).fill = YELLOW_FILL
            row += 1
        phase_chart_end = row - 1

        if phase_chart_start and phase_chart_end >= phase_chart_start:
            chart = BarChart()
            chart.type = "col"
            chart.title = "% Closed theo Phase"
            chart.y_axis.title = "%"
            chart.x_axis.title = None
            data_ref = Reference(ws, min_col=2, min_row=phase_chart_start - 1, max_row=phase_chart_end)
            cats = Reference(ws, min_col=1, min_row=phase_chart_start, max_row=phase_chart_end)
            chart.add_data(data_ref, titles_from_data=True)
            chart.set_categories(cats)
            chart.shape = 4
            chart.width = 14
            chart.height = 8
            # Đặt bên phải bảng, không đè cột A–D
            ws.add_chart(chart, "F" + str(phase_chart_start - 1))
        # Chừa chỗ cho chart trước block kế
        row = max(row, (phase_chart_start or row) + 14)

    row += 1
    # --- 4. Module overview ---
    row = _block_title(ws, row, "4. TỔNG QUAN MODULE (sắp theo số trễ ↓, rồi tiến độ %)", n_cols=6)
    modules = list(metrics.get("module_overview") or [])
    modules.sort(
        key=lambda m: (-int(m.get("overdue_count") or 0), float(m.get("progress_pct") or 0), m.get("module") or ""),
    )
    mo_headers = ["STT", "Module", "Tổng CN", "Tiến độ %", "Phase active", "Overdue"]
    for i, h in enumerate(mo_headers, 1):
        ws.cell(row=row, column=i, value=h)
    _style_header_row(ws, row, 1, 6)
    row += 1
    mod_chart_start = None
    mod_chart_end = None
    if not modules:
        ws.cell(row=row, column=1, value="Chưa có module_overview.").font = NOTE_FONT
        row += 1
    else:
        mod_chart_start = row
        for idx, m in enumerate(modules, 1):
            vals = [
                idx,
                m.get("module") or m.get("label") or "",
                m.get("total", 0),
                m.get("progress_pct", 0),
                m.get("active_phase", ""),
                m.get("overdue_count", 0),
            ]
            for c, v in enumerate(vals, 1):
                cell = ws.cell(row=row, column=c, value=v)
                cell.font = BODY_MOM_FONT
                cell.border = THIN_BORDER
                cell.alignment = CENTER if c != 2 and c != 5 else LEFT_CENTER
            od = int(m.get("overdue_count") or 0)
            if od > 0:
                ws.cell(row=row, column=6).fill = ORANGE_FILL if od < 5 else RED_FILL
            row += 1
        mod_chart_end = row - 1
        # Chart: tiến độ % theo module (overdue thường gần 0 → chart trống)
        chart_n = mod_chart_end - mod_chart_start + 1
        if chart_n > 0:
            chart = BarChart()
            chart.type = "bar"
            chart.title = "Tiến độ % theo Module"
            data_ref = Reference(
                ws, min_col=4, min_row=mod_chart_start - 1,
                max_row=mod_chart_end,
            )
            cats = Reference(
                ws, min_col=2, min_row=mod_chart_start,
                max_row=mod_chart_end,
            )
            chart.add_data(data_ref, titles_from_data=True)
            chart.set_categories(cats)
            chart.width = 14
            chart.height = 9
            ws.add_chart(chart, "H" + str(mod_chart_start - 1))
        row = max(row, (mod_chart_start or row) + 12)

    row += 1
    # --- 5. PIC workload ---
    row = _block_title(ws, row, "5. TẢI VIỆC PIC (top 25 — sắp theo tổng task ↓)", n_cols=7)
    pics = sorted(
        list(metrics.get("pic_workload") or []),
        key=lambda p: (-int(p.get("total_tasks") or 0), -int(p.get("overdue") or 0), p.get("pic") or ""),
    )[:25]
    pic_headers = ["STT", "PIC", "Tổng", "Closed", "In-progress", "Assigned", "Overdue"]
    for i, h in enumerate(pic_headers, 1):
        ws.cell(row=row, column=i, value=h)
    _style_header_row(ws, row, 1, 7)
    row += 1
    pic_chart_start = None
    if not pics:
        ws.cell(row=row, column=1, value="Chưa có pic_workload.").font = NOTE_FONT
        row += 1
    else:
        pic_chart_start = row
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
                cell.font = BODY_MOM_FONT
                cell.border = THIN_BORDER
                cell.alignment = CENTER if c != 2 else LEFT_CENTER
            if int(p.get("overdue") or 0) > 0:
                ws.cell(row=row, column=7).fill = RED_FILL
            row += 1
        pic_chart_end = row - 1
        top_n = min(10, pic_chart_end - pic_chart_start + 1)
        if top_n > 0:
            chart = BarChart()
            chart.type = "col"
            chart.title = "Top PIC theo tổng task"
            data_ref = Reference(
                ws, min_col=3, min_row=pic_chart_start - 1,
                max_row=pic_chart_start + top_n - 1,
            )
            cats = Reference(
                ws, min_col=2, min_row=pic_chart_start,
                max_row=pic_chart_start + top_n - 1,
            )
            chart.add_data(data_ref, titles_from_data=True)
            chart.set_categories(cats)
            chart.width = 13
            chart.height = 8
            ws.add_chart(chart, "I" + str(pic_chart_start - 1))
        row = max(row, (pic_chart_start or row) + 12)

    # Pie tiến độ chung — data range chỉ 2 dòng số (không gồm title)
    pct = summary.get("overall_progress_pct")
    if isinstance(pct, (int, float)):
        pie_row = row + 2
        ws.cell(row=pie_row, column=1, value="Phân bổ tiến độ chung").font = Font(
            name="Calibri", bold=True, size=11, color="1F4E79",
        )
        closed_pct = round(float(pct), 1)
        remain_pct = round(max(0.0, 100.0 - closed_pct), 1)
        ws.cell(row=pie_row + 1, column=1, value="Đã Closed (ước lượng %)")
        ws.cell(row=pie_row + 1, column=2, value=closed_pct)
        ws.cell(row=pie_row + 2, column=1, value="Còn lại")
        ws.cell(row=pie_row + 2, column=2, value=remain_pct)
        for r in (pie_row + 1, pie_row + 2):
            for c in (1, 2):
                ws.cell(row=r, column=c).border = THIN_BORDER
                ws.cell(row=r, column=c).font = BODY_MOM_FONT
        pie = PieChart()
        pie.title = "Tiến độ chung (%)"
        labels = Reference(ws, min_col=1, min_row=pie_row + 1, max_row=pie_row + 2)
        data = Reference(ws, min_col=2, min_row=pie_row + 1, max_row=pie_row + 2)
        pie.add_data(data, titles_from_data=False)
        pie.set_categories(labels)
        pie.dataLabels = DataLabelList()
        pie.dataLabels.showPercent = True
        pie.width = 10
        pie.height = 8
        ws.add_chart(pie, "D" + str(pie_row))
        row = pie_row + 12

    row += 1
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=8)
    ws.cell(
        row=row, column=1,
        value="Biểu đồ: Phase % Closed · Module tiến độ · Top PIC · Pie tiến độ chung.",
    ).font = GUIDE_FONT

    ws.freeze_panes = "A4"
    _set_print_landscape(ws)


def export_weekly_mom(
    metrics: dict,
    output_dir: str = "uploads",
    *,
    project_code: str = "",
    parsed_data=None,
    today: Optional[date] = None,
) -> str:
    """
    Sinh workbook báo cáo tuần MoM (mẫu W30) + Master/Gantt + PM Dashboard.

    Args:
        metrics: dict từ DashboardEngine.compute()
        output_dir: thư mục lưu file
        project_code: mã dự án (slug hoặc tên) — hiện trên Cover
        parsed_data: ParsedData optional — kế hoạch tuần / PIC / Master plan
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
    _write_master_plan(wb, metrics or {}, parsed_data, today=today)
    _write_gantt_sheet(wb, metrics or {}, parsed_data, today)
    _write_mom_sheet(wb, meeting_sheet, week_label, today, metrics or {}, parsed_data)
    _write_pm_dashboard(wb, metrics or {}, today, week_label)

    os.makedirs(output_dir, exist_ok=True)
    safe_code = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in code)[:40]
    filename = f"{safe_code}_MoM_{today.year}.{week_label}.xlsx"
    filepath = os.path.join(output_dir, filename)
    wb.save(filepath)
    wb.close()
    return filepath
