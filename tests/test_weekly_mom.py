"""Smoke test cho export_weekly_mom (mẫu MoM W30 + PM Dashboard)."""
import os
from datetime import date

import openpyxl
import pytest

from exporter.weekly_mom import export_weekly_mom, _iso_week_label


# Cùng today với conftest để metrics reproducible
TODAY = date(2026, 7, 28)


def test_export_weekly_mom_sheets_and_headers(tmp_path, metrics, parsed_data):
    """Workbook có Cover / Master plan / MoM_Wxx / PM Dashboard; header MoM khớp mẫu."""
    path = export_weekly_mom(
        metrics,
        str(tmp_path),
        project_code="KDG_iHRP_2026_PM",
        parsed_data=parsed_data,
        today=TODAY,
    )
    assert os.path.exists(path)
    week = _iso_week_label(TODAY)
    assert week in os.path.basename(path)

    wb = openpyxl.load_workbook(path)
    names = wb.sheetnames
    assert names[0] == "Cover Page"
    assert "Master plan" in names
    mom_name = f"MoM_{week}"
    assert mom_name in names
    assert "PM Dashboard" in names

    # Cover: project code
    cover = wb["Cover Page"]
    assert cover["C4"].value == "KDG_iHRP_2026_PM"
    assert week in str(cover["F5"].value)

    # Master plan: header giống mẫu
    mp = wb["Master plan"]
    assert mp["B2"].value == "STT"
    assert mp["C2"].value == "Công việc"
    assert "N/A" in str(mp["C4"].value)

    # MoM: cột Content như mẫu W30
    mom = wb[mom_name]
    assert "Ngày" in str(mom["B2"].value)
    assert mom["B8"].value == "STT"
    assert mom["C8"].value == "Công việc"
    assert mom["D8"].value == "PIC"
    assert mom["H8"].value == "Tình trạng"
    # Section A kế hoạch tuần
    assert mom["B9"].value == "A"
    assert "KẾ HOẠCH TUẦN" in str(mom["C9"].value)

    # PM Dashboard: 5 block
    dash = wb["PM Dashboard"]
    a_vals = [str(c.value or "") for c in dash["A"] if c.value]
    joined = " | ".join(a_vals)
    assert "TÓM TẮT" in joined
    assert "OVERDUE" in joined
    assert "PHASE PROGRESS" in joined
    assert "MODULE OVERVIEW" in joined
    assert "PIC WORKLOAD" in joined

    wb.close()


def test_export_weekly_mom_empty_metrics_still_creates(tmp_path):
    """Metrics rỗng vẫn tạo file (không crash); PM Dashboard ghi N/A."""
    path = export_weekly_mom({}, str(tmp_path), project_code="demo", today=TODAY)
    assert os.path.exists(path)
    wb = openpyxl.load_workbook(path)
    assert "PM Dashboard" in wb.sheetnames
    wb.close()
