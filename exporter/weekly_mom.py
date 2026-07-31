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
from parser.excel_parser import VALID_STATUSES

# Styles riêng MoM (bám mẫu W30: header xanh đậm, section vàng)
TITLE_FONT = Font(name="Arial", bold=True, size=14, color="1F4E79")
SECTION_FILL = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
SECTION_FONT = Font(name="Arial", bold=True, size=11, color="1F4E79")
NOTE_FONT = Font(name="Arial", italic=True, size=9, color="666666")
LABEL_FONT = Font(name="Arial", bold=True, size=10)
MODULE_FILL = PatternFill(start_color="D6EAF8", end_color="D6EAF8", fill_type="solid")
GANTT_FILL = PatternFill(start_color="5B9BD5", end_color="5B9BD5", fill_type="solid")
GANTT_TODAY_FILL = PatternFill(start_color="F4B183", end_color="F4B183", fill_type="solid")
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
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
    for c in range(start_col, end_col + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER


def _apply_border_row(ws, row: int, start_col: int, end_col: int) -> None:
    for c in range(start_col, end_col + 1):
        cell = ws.cell(row=row, column=c)
        cell.border = THIN_BORDER
        if cell.font is None or cell.font.name is None:
            cell.font = BODY_FONT
        if cell.alignment is None or cell.alignment.vertical is None:
            cell.alignment = BODY_ALIGN


def _collect_week_plan(
    parsed_data,
    week_start: date,
    week_end: date,
    *,
    limit: int = _WEEK_PLAN_LIMIT,
) -> list[dict]:
    """
    Công việc gợi ý trong tuần ISO:
      - Phase chưa Closed/Cancelled
      - Sau normalize/swap Start–End: End nằm trong tuần, HOẶC Start–End giao tuần
    Ưu tiên: End trong tuần → Start trong tuần → chỉ overlap dài.
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
            if not _ranges_overlap(s, e, week_start, week_end):
                continue
            end_in = e is not None and week_start <= e <= week_end
            start_in = s is not None and week_start <= s <= week_end
            if end_in:
                priority = 0
            elif start_in:
                priority = 1
            else:
                priority = 2
            label = f"[{phase_name}] {ma} — {ten}".strip(" —")
            if not ma and not ten:
                label = f"[{phase_name}]"
            items.append({
                "ten": label,
                "pic": ", ".join(pd.pics or []) or NA,
                "from": _fmt_date(s),
                "to": _fmt_date(e),
                "status": st,
                "note": (("swap Start↔End; " if swapped else "") + (pd.note or ""))[:80].rstrip("; "),
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


def _build_master_rows(metrics: dict, parsed_data) -> list[dict]:
    """
    WBS-like: mỗi Module 1 dòng cha + mỗi Phase có date 1 dòng con.
    Dữ liệu từ timeline_data (+ bổ sung PIC/status từ ParsedData nếu có).
    """
    timeline = (metrics or {}).get("timeline_data") or {}
    modules = timeline.get("modules") or []
    phases = timeline.get("phases") or []
    data = timeline.get("data") or {}
    if not modules and parsed_data is not None:
        modules = list(parsed_data.all_modules or [])
        phases = list(parsed_data.all_phases or [])

    # PIC / status tổng hợp theo (module, phase) từ FL
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
        # Aggregate module dates
        mod_starts: list[date] = []
        mod_ends: list[date] = []
        phase_children: list[dict] = []
        for ph in phases:
            cell = mod_data.get(ph) or {}
            s, e, _ = _normalize_date_pair(cell.get("start"), cell.get("end"))
            if s is None and e is None:
                # fallback từ parsed rows nếu timeline thiếu
                if parsed_data is not None:
                    starts, ends = [], []
                    for r in parsed_data.rows:
                        if (r.meta.get("module") or "") != module:
                            continue
                        pd = (r.phases or {}).get(ph)
                        if not pd:
                            continue
                        ps, pe, _ = _normalize_date_pair(pd.start_date, pd.end_date)
                        if ps:
                            starts.append(ps)
                        if pe:
                            ends.append(pe)
                    s = min(starts) if starts else None
                    e = max(ends) if ends else None
                if s is None and e is None:
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
            # Tình trạng: status phổ biến nhất, kèm % Closed nếu có
            top_status = ""
            if counts:
                top_status = max(counts.items(), key=lambda kv: kv[1])[0]
            if pct is not None:
                status_txt = f"{top_status or '—'} · {pct}% Closed"
            else:
                status_txt = top_status or ""
            pics = pic_map.get((module, ph)) or []
            phase_children.append({
                "level": 1,
                "name": f"    {ph}",
                "status": status_txt,
                "pic_kdg": ", ".join(pics[:4]) if pics else "",
                "start": s,
                "end": e,
                "note": f"n={total}" if total else "",
                "pct": pct if pct is not None else "",
            })

        if not phase_children and not mod_starts and not mod_ends:
            continue
        stt_mod += 1
        # Module overview % nếu có
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
            "status": f"{mod_pct}% Closed" if mod_pct is not None else "",
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
    for col, w in zip("ABCDEFGHIJK", [4, 18, 16, 14, 14, 14, 28, 12, 12, 12, 12]):
        ws.column_dimensions[col].width = w

    ws["B4"] = "Project Code: "
    ws["B4"].font = LABEL_FONT
    ws["C4"] = project_code or NA
    ws["C4"].font = Font(name="Arial", bold=True, size=12, color="1F4E79")
    ws["G4"] = "Meeting Minutes Records"
    ws["G4"].font = TITLE_FONT

    ws["B5"] = "version: "
    ws["B5"].font = LABEL_FONT
    ws["C5"] = "v1.1 (auto từ iHRP Tracker)"
    ws["E5"] = "Tuần:"
    ws["E5"].font = LABEL_FONT
    ws["F5"] = week_label
    ws["F5"].font = Font(name="Arial", bold=True, size=12, color="C00000")

    ws["B6"] = "Ghi chú:"
    ws["C6"] = (
        "Master plan / Gantt sinh từ Function List (Module × Phase). "
        "MoM gợi ý deadline tuần này & tuần tới. PM bổ sung giờ họp / người tham gia."
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

    toc = [
        (meeting_sheet_name, f"Họp định kỳ dự án — {week_label}"),
        ("Master plan", "WBS Module × Phase (Start–End từ Function List)"),
        ("Gantt", "Timeline tuần (ô tô màu theo kế hoạch)"),
        ("PM Dashboard", "Tóm tắt metrics + biểu đồ Excel"),
    ]
    for i, (sheet, subject) in enumerate(toc):
        r = 9 + i
        ws.cell(row=r, column=2, value=sheet).font = BODY_FONT
        ws.cell(row=r, column=3, value=today.strftime("%d/%m/%Y")).font = BODY_FONT
        ws.cell(row=r, column=4, value=subject).font = BODY_FONT
        ws.merge_cells(f"D{r}:G{r}")
        for c in range(2, 8):
            ws.cell(row=r, column=c).border = THIN_BORDER

    for r in range(13, 18):
        ws.merge_cells(f"D{r}:G{r}")
        for c in range(2, 8):
            ws.cell(row=r, column=c).border = THIN_BORDER


def _write_master_plan(wb, metrics: dict, parsed_data) -> None:
    """Master plan: WBS Module × Phase từ timeline Function List."""
    ws = wb.create_sheet("Master plan")
    widths = {
        "B": 8, "C": 42, "D": 22, "E": 10, "F": 18,
        "G": 14, "H": 14, "I": 14, "J": 14, "K": 28,
    }
    for col, w in widths.items():
        ws.column_dimensions[col].width = w

    ws["I1"] = "Cập nhật liên tục"
    ws["I1"].font = NOTE_FONT
    ws.merge_cells("I1:J1")

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
            cell.font = HEADER_FONT
            cell.fill = HEADER_FILL
            cell.alignment = HEADER_ALIGN
            cell.border = THIN_BORDER

    master_rows = _build_master_rows(metrics, parsed_data)
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
                ws.cell(row=r, column=c).font = BODY_FONT
        return

    row = 4
    for item in master_rows:
        ws.cell(row=row, column=2, value=item.get("stt", ""))
        ws.cell(row=row, column=3, value=item.get("name", ""))
        ws.cell(row=row, column=4, value=item.get("status", ""))
        ws.cell(row=row, column=5, value="")  # FIS — không có trong FL
        ws.cell(row=row, column=6, value=item.get("pic_kdg", ""))
        # v1.0 = LU cùng nguồn FL (không có baseline riêng)
        ws.cell(row=row, column=7, value=_fmt_date(item.get("start")))
        ws.cell(row=row, column=8, value=_fmt_date(item.get("end")))
        ws.cell(row=row, column=9, value=_fmt_date(item.get("start")))
        ws.cell(row=row, column=10, value=_fmt_date(item.get("end")))
        ws.cell(row=row, column=11, value=item.get("note", ""))
        for c in range(2, 12):
            cell = ws.cell(row=row, column=c)
            cell.border = THIN_BORDER
            cell.font = Font(name="Arial", size=10, bold=(item.get("level") == 0))
            cell.alignment = BODY_ALIGN if c in (3, 4, 6, 11) else CENTER
        if item.get("level") == 0:
            for c in range(2, 12):
                ws.cell(row=row, column=c).fill = MODULE_FILL
        row += 1

    ws.cell(
        row=row + 1, column=2,
        value=(
            "Nguồn: Function List (timeline Module × Phase). "
            "PIC FIS trống (không có trong FL). Cột v1.0 = LU cùng mốc Start/End hiện tại."
        ),
    )
    ws.cell(row=row + 1, column=2).font = NOTE_FONT
    ws.merge_cells(start_row=row + 1, start_column=2, end_row=row + 1, end_column=11)


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
    """Sheet Gantt: hàng = Module × Phase; cột = tuần; tô màu nếu giao khoảng."""
    ws = wb.create_sheet("Gantt")
    master_rows = [r for r in _build_master_rows(metrics, parsed_data) if r.get("start") or r.get("end")]
    if not master_rows:
        ws["A1"] = "Gantt"
        ws["A1"].font = TITLE_FONT
        ws["A3"] = "N/A — không có Start/End để vẽ Gantt."
        ws["A3"].font = NOTE_FONT
        return

    dates: list[date] = []
    for r in master_rows:
        s, e, _ = _normalize_date_pair(r.get("start"), r.get("end"))
        if s:
            dates.append(s)
        if e:
            dates.append(e)
    dates.append(today)
    min_d, max_d = min(dates), max(dates)
    # Giới hạn span ~ 26 tuần quanh today nếu quá dài
    if (max_d - min_d).days > 26 * 7:
        min_d = max(min_d, today - timedelta(weeks=8))
        max_d = min(max_d, today + timedelta(weeks=18))
        if min_d > max_d:
            min_d, max_d = today - timedelta(weeks=4), today + timedelta(weeks=8)

    weeks = _iter_weeks(min_d, max_d)
    ws.column_dimensions["A"].width = 8
    ws.column_dimensions["B"].width = 36
    ws.column_dimensions["C"].width = 12
    ws.column_dimensions["D"].width = 12
    for i in range(len(weeks)):
        ws.column_dimensions[get_column_letter(5 + i)].width = 5

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=4 + max(len(weeks), 1))
    ws["A1"] = f"GANTT — Module × Phase theo tuần (xuất {today.strftime('%d/%m/%Y')})"
    ws["A1"].font = TITLE_FONT
    ws["A1"].alignment = Alignment(horizontal="left", vertical="center")

    headers = ["STT", "Công việc", "Từ ngày", "Đến ngày"] + [w[2] for w in weeks]
    for i, h in enumerate(headers, 1):
        cell = ws.cell(row=3, column=i, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER

    today_week = _week_range(today)[0]
    for ri, item in enumerate(master_rows):
        row = 4 + ri
        s, e, _ = _normalize_date_pair(item.get("start"), item.get("end"))
        vals = [item.get("stt", ""), item.get("name", ""), _fmt_date(s), _fmt_date(e)]
        for c, v in enumerate(vals, 1):
            cell = ws.cell(row=row, column=c, value=v)
            cell.border = THIN_BORDER
            cell.font = Font(name="Arial", size=9, bold=(item.get("level") == 0))
            cell.alignment = BODY_ALIGN if c == 2 else CENTER
            if item.get("level") == 0:
                cell.fill = MODULE_FILL
        for wi, (ws_d, we_d, _) in enumerate(weeks):
            cell = ws.cell(row=row, column=5 + wi, value="")
            cell.border = THIN_BORDER
            if s is not None or e is not None:
                if _ranges_overlap(s, e, ws_d, we_d):
                    cell.fill = GANTT_FILL
            if ws_d == today_week:
                if cell.fill is None or cell.fill.fgColor is None or cell.fill.fgColor.rgb in (None, "00000000"):
                    cell.fill = GANTT_TODAY_FILL
                # đánh dấu tuần hiện tại trên header đã có; body: nếu vừa gantt vừa today giữ gantt

    note_row = 4 + len(master_rows) + 1
    ws.cell(
        row=note_row, column=1,
        value="Ô xanh = khoảng Start–End giao tuần. Cột cam nhạt = tuần hiện tại (khi không có bar).",
    )
    ws.cell(row=note_row, column=1).font = NOTE_FONT
    ws.merge_cells(start_row=note_row, start_column=1, end_row=note_row, end_column=4)


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
    col_widths = {1: 3, 2: 6, 3: 55, 4: 16, 5: 14, 6: 12, 7: 12, 8: 12}
    for c, w in col_widths.items():
        ws.column_dimensions[get_column_letter(c)].width = w

    week_start, week_end = _week_range(today)
    next_start = week_start + timedelta(days=7)
    next_end = week_end + timedelta(days=7)

    # === Meta họp ===
    ws["B2"] = "Ngày/Date:  "
    ws["B2"].font = LABEL_FONT
    ws.merge_cells("B2:C2")
    ws["D2"] = today.strftime("%d/%m/%Y")
    ws["D2"].alignment = CENTER
    ws.merge_cells("D2:E2")
    ws["F2"] = "Return to Cover Page"
    ws["F2"].font = Font(name="Arial", italic=True, size=9, color="0563C1")
    ws.merge_cells("F2:H2")

    ws["B3"] = "Giờ/Time: "
    ws["B3"].font = LABEL_FONT
    ws.merge_cells("B3:C3")
    ws["D3"] = ""  # PM điền — không ghi N/A kiểu draft
    ws.merge_cells("D3:E3")

    ws["B4"] = "Tên/Subject:  "
    ws["B4"].font = LABEL_FONT
    ws.merge_cells("B4:C4")
    ws["D4"] = f"Họp định kỳ dự án — {week_label}"
    ws.merge_cells("D4:H4")

    ws["B5"] = "Người tham gia/Committee:  "
    ws["B5"].font = LABEL_FONT
    ws.merge_cells("B5:C5")
    ws["D5"] = ""
    ws.merge_cells("D5:H5")

    for r in range(2, 6):
        for c in range(2, 9):
            ws.cell(row=r, column=c).border = THIN_BORDER

    ws["B7"] = "Nội dung/ Content"
    ws["B7"].font = SECTION_FONT

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
        ws.cell(row=row, column=1).border = THIN_BORDER
        row += 1
        if items:
            for idx, it in enumerate(items, 1):
                vals = [idx, it["ten"], it["pic"], it.get("note", ""), it["from"], it["to"], it["status"]]
                for c, v in enumerate(vals, 2):
                    cell = ws.cell(row=row, column=c, value=v)
                    if c in (6, 7, 8):
                        cell.alignment = CENTER
                    else:
                        cell.alignment = BODY_ALIGN
                    cell.font = BODY_FONT
                _apply_border_row(ws, row, 1, 8)
                row += 1
        else:
            ws.cell(row=row, column=2, value=1)
            ws.cell(row=row, column=3, value=empty_hint)
            ws.cell(row=row, column=3).font = NOTE_FONT
            _apply_border_row(ws, row, 1, 8)
            row += 1
            for i in range(2, 5):
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
        f"Không có phase Start/End giao tuần này ({week_start.strftime('%d/%m')}–{week_end.strftime('%d/%m/%Y')}). PM điền tay.",
    )

    row += 1
    row = _write_plan_section(
        row, "B",
        f"KẾ HOẠCH TUẦN TỚI ({next_start.strftime('%d/%m')}–{next_end.strftime('%d/%m/%Y')})",
        next_week,
        f"Không có phase Start/End giao tuần tới ({next_start.strftime('%d/%m')}–{next_end.strftime('%d/%m/%Y')}). PM điền tay.",
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
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER

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
                cell.font = BODY_FONT
                cell.alignment = CENTER if c >= 6 else BODY_ALIGN
                if fill and c >= 2:
                    cell.fill = fill
            row += 1
    else:
        ws.cell(row=row, column=2, value=1)
        ws.cell(row=row, column=3, value="Không có task overdue.")
        ws.cell(row=row, column=3).font = NOTE_FONT
        ws.merge_cells(f"C{row}:E{row}")
        _apply_border_row(ws, row, 1, 8)
        row += 1
        for i in range(2, 5):
            ws.cell(row=row, column=2, value=i)
            ws.merge_cells(f"C{row}:E{row}")
            _apply_border_row(ws, row, 1, 8)
            row += 1

    row += 1
    ws.cell(
        row=row, column=2,
        value=(
            f"Gợi ý auto từ Function List ngày {today.strftime('%d/%m/%Y')}. "
            "Giờ họp / người tham gia: điền tay trước khi gửi."
        ),
    )
    ws.cell(row=row, column=2).font = NOTE_FONT
    ws.merge_cells(f"B{row}:H{row}")


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
    Sheet PM Dashboard — block số liệu + 3 chart Excel:
      1. Tóm tắt
      2. Overdue (sort ngày trễ)
      3. Tiến độ theo phase (% Closed) + bar chart
      4. Module (sort % / overdue) + bar overdue
      5. PIC workload (sort tải) + bar top PIC
    """
    ws = wb.create_sheet("PM Dashboard")
    for i in range(1, 12):
        ws.column_dimensions[get_column_letter(i)].width = 14
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 36
    ws.column_dimensions["D"].width = 14

    ws.merge_cells("A1:H1")
    ws["A1"] = f"BẢNG ĐIỀU KHIỂN PM — Function List ({week_label})"
    ws["A1"].font = TITLE_FONT
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    ws.merge_cells("A2:H2")
    ws["A2"] = f"Xuất ngày {today.strftime('%d/%m/%Y')} — số liệu từ metrics engine"
    ws["A2"].font = NOTE_FONT
    ws["A2"].alignment = Alignment(horizontal="center")

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
        if "trễ" in label.lower() and isinstance(val, (int, float)) and val > 0:
            c.fill = RED_FILL
        row += 1

    row += 1
    # --- 2. Overdue ---
    row = _block_title(ws, row, "2. CÔNG VIỆC TRỄ (top 20 — sắp theo số ngày trễ ↓)")
    overdue = sorted(
        list(metrics.get("overdue_list") or []),
        key=lambda x: (-int(x.get("days_overdue") or 0), x.get("module") or "", x.get("ma_cn") or ""),
    )[:20]
    ov_headers = ["STT", "Mã CN", "Tên chức năng", "Module", "Phase", "Deadline", "Ngày trễ", "Status", "PIC"]
    for i, h in enumerate(ov_headers, 1):
        cell = ws.cell(row=row, column=i, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER
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
                cell.font = BODY_FONT
                cell.border = THIN_BORDER
                cell.alignment = BODY_ALIGN
                if fill:
                    cell.fill = fill
            row += 1

    row += 1
    # --- 3. Phase progress + chart data ---
    row = _block_title(ws, row, "3. TIẾN ĐỘ THEO PHASE (% Closed)", n_cols=10)
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
            cell = ws.cell(row=row, column=i, value=h)
            cell.font = HEADER_FONT
            cell.fill = HEADER_FILL
            cell.alignment = HEADER_ALIGN
            cell.border = THIN_BORDER
        row += 1
        phase_chart_start = row
        phase_rows_tmp = []
        for ph in phases:
            counts = pdata.get(ph) or {}
            closed = int(counts.get("Closed", 0) or 0)
            total = sum(int(counts.get(s, 0) or 0) for s in statuses)
            pct = round(closed / total * 100, 1) if total > 0 else 0.0
            phase_rows_tmp.append((ph, pct, closed, total))
        phase_rows_tmp.sort(key=lambda x: -x[1])
        for ph, pct, closed, total in phase_rows_tmp:
            vals = [ph, pct, closed, total]
            for c, v in enumerate(vals, 1):
                cell = ws.cell(row=row, column=c, value=v)
                cell.font = BODY_FONT
                cell.border = THIN_BORDER
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
            chart.width = 15
            chart.height = 8
            ws.add_chart(chart, "F" + str(phase_chart_start - 1))

    row += 1
    # --- 4. Module overview ---
    row = _block_title(ws, row, "4. TỔNG QUAN MODULE (sắp theo số trễ ↓, rồi tiến độ %)")
    modules = list(metrics.get("module_overview") or [])
    modules.sort(
        key=lambda m: (-int(m.get("overdue_count") or 0), float(m.get("progress_pct") or 0), m.get("module") or ""),
    )
    mo_headers = ["STT", "Module", "Tổng CN", "Tiến độ %", "Phase active", "Overdue"]
    for i, h in enumerate(mo_headers, 1):
        cell = ws.cell(row=row, column=i, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER
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
                cell.font = BODY_FONT
                cell.border = THIN_BORDER
            od = int(m.get("overdue_count") or 0)
            if od > 0:
                ws.cell(row=row, column=6).fill = ORANGE_FILL if od < 5 else RED_FILL
            row += 1
        mod_chart_end = row - 1
        # Chart: overdue by module (top 12)
        chart_n = min(12, mod_chart_end - mod_chart_start + 1)
        if chart_n > 0:
            chart = BarChart()
            chart.type = "bar"
            chart.title = "Số function trễ theo Module (top)"
            data_ref = Reference(
                ws, min_col=6, min_row=mod_chart_start - 1,
                max_row=mod_chart_start + chart_n - 1,
            )
            cats = Reference(
                ws, min_col=2, min_row=mod_chart_start,
                max_row=mod_chart_start + chart_n - 1,
            )
            chart.add_data(data_ref, titles_from_data=True)
            chart.set_categories(cats)
            chart.width = 15
            chart.height = 9
            ws.add_chart(chart, "H" + str(mod_chart_start - 1))

    row += 1
    # --- 5. PIC workload ---
    row = _block_title(ws, row, "5. TẢI VIỆC PIC (top 25 — sắp theo tổng task ↓)")
    pics = sorted(
        list(metrics.get("pic_workload") or []),
        key=lambda p: (-int(p.get("total_tasks") or 0), -int(p.get("overdue") or 0), p.get("pic") or ""),
    )[:25]
    pic_headers = ["STT", "PIC", "Tổng", "Closed", "In-progress", "Assigned", "Overdue"]
    for i, h in enumerate(pic_headers, 1):
        cell = ws.cell(row=row, column=i, value=h)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = HEADER_ALIGN
        cell.border = THIN_BORDER
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
                cell.font = BODY_FONT
                cell.border = THIN_BORDER
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
            chart.width = 14
            chart.height = 8
            ws.add_chart(chart, "I" + str(pic_chart_start - 1))

    # Optional small pie: Closed vs còn lại từ summary nếu có overall
    # (chỉ khi có overall_progress_pct số)
    pct = summary.get("overall_progress_pct")
    if isinstance(pct, (int, float)):
        pie_row = row + 2
        ws.cell(row=pie_row, column=1, value="Phân bổ tiến độ chung").font = SECTION_FONT
        ws.cell(row=pie_row + 1, column=1, value="Đã Closed (ước lượng %)")
        ws.cell(row=pie_row + 1, column=2, value=float(pct))
        ws.cell(row=pie_row + 2, column=1, value="Còn lại")
        ws.cell(row=pie_row + 2, column=2, value=max(0.0, 100.0 - float(pct)))
        for r in (pie_row + 1, pie_row + 2):
            for c in (1, 2):
                ws.cell(row=r, column=c).border = THIN_BORDER
                ws.cell(row=r, column=c).font = BODY_FONT
        pie = PieChart()
        pie.title = "Tiến độ chung (%)"
        labels = Reference(ws, min_col=1, min_row=pie_row + 1, max_row=pie_row + 2)
        data = Reference(ws, min_col=2, min_row=pie_row, max_row=pie_row + 2)
        pie.add_data(data, titles_from_data=False)
        pie.set_categories(labels)
        pie.dataLabels = DataLabelList()
        pie.dataLabels.showPercent = True
        pie.width = 10
        pie.height = 8
        ws.add_chart(pie, "D" + str(pie_row))
        row = pie_row + 4

    row += 2
    ws.cell(
        row=row, column=1,
        value=(
            "Biểu đồ: % Closed theo phase · Overdue theo module · Top PIC · Pie tiến độ chung. "
            "Chi tiết sâu: Xuất vấn đề / Full Report / chart export riêng."
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
    _write_master_plan(wb, metrics or {}, parsed_data)
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
