"""Tests cho exporter.excel_exporter."""
import os

import openpyxl

from exporter.excel_exporter import (
    export_overdue_report,
    export_full_report,
    export_by_pic,
    export_compare_report,
)


def test_export_overdue_creates_file(tmp_path, metrics):
    """export_overdue_report tạo file .xlsx hợp lệ."""
    path = export_overdue_report(metrics["overdue_list"], str(tmp_path))
    assert os.path.exists(path)
    wb = openpyxl.load_workbook(path)
    assert len(wb.sheetnames) >= 1
    wb.close()


def test_export_overdue_with_filter(tmp_path, metrics):
    """Có filter → chỉ export row match module=TMS."""
    path = export_overdue_report(
        metrics["overdue_list"], str(tmp_path),
        filters={"module": "TMS"},
    )
    wb = openpyxl.load_workbook(path)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    # Header ở row 4 (row 1=title, row 2=subtitle, row 3=trống)
    header = rows[3]
    module_idx = None
    for i, h in enumerate(header):
        if h and "Module" in str(h):
            module_idx = i
            break
    assert module_idx is not None, f"Không tìm thấy cột Module trong header: {header}"
    for r in rows[4:]:
        val = r[module_idx]
        if val and str(val).startswith(("TMS", "ESS", "HR", "SI")):
            assert val == "TMS", f"Row bị lọt: {val}"
    wb.close()


def test_export_full_report_has_multiple_sheets(tmp_path, metrics):
    """Full report có nhiều sheet: Summary + Overdue + Unassigned + Long Duration + Stalled + High Risk."""
    path = export_full_report(metrics, str(tmp_path))
    wb = openpyxl.load_workbook(path)
    assert len(wb.sheetnames) >= 4
    wb.close()


def test_export_by_pic(tmp_path, metrics):
    """Export theo PIC tạo file .xlsx với sheet Info."""
    pic_list = metrics["pic_workload"]
    # Sample data trong conftest luôn có PIC (SonHN6/PhatTPT3/...); nếu không có,
    # nghĩa là parser hoặc fixture đã hỏng — assert thay vì silent-skip.
    assert pic_list, "Sample data phải có ít nhất 1 PIC (fixture bị hỏng?)"
    pic = pic_list[0]["pic"]
    path = export_by_pic(metrics, pic, str(tmp_path))
    assert os.path.exists(path)
    wb = openpyxl.load_workbook(path)
    assert len(wb.sheetnames) >= 1
    wb.close()


def test_export_compare_report(tmp_path, parsed_data):
    """export_compare_report chạy được, tạo file .xlsx."""
    from analyzer.compare_engine import CompareEngine
    result = CompareEngine().compare(
        parsed_data, parsed_data,
        old_date="2026-07-01", new_date="2026-07-28",
    )
    path = export_compare_report(result, "2026-07-01", "2026-07-28", str(tmp_path))
    assert os.path.exists(path)
    wb = openpyxl.load_workbook(path)
    assert len(wb.sheetnames) >= 1
    wb.close()


def test_export_empty_overdue_still_creates_file(tmp_path):
    """Empty overdue list vẫn tạo file (không crash)."""
    path = export_overdue_report([], str(tmp_path))
    assert os.path.exists(path)
