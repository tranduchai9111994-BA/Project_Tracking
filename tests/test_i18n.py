"""Tests analyzer/i18n.py — normalize + sheet names + t()."""
from analyzer.i18n import normalize_lang, sheet_name, t


def test_normalize_lang():
    assert normalize_lang(None) == "vi"
    assert normalize_lang("") == "vi"
    assert normalize_lang("vi") == "vi"
    assert normalize_lang("en") == "en"
    assert normalize_lang("en-US") == "en"
    assert normalize_lang("EN") == "en"


def test_sheet_names_vi_default():
    assert sheet_name("overdue") == "Tre_han"
    assert sheet_name("cover", "vi") == "Tong_quan"
    assert sheet_name("unassigned", "vi") == "Chua_PIC"


def test_sheet_names_en():
    assert sheet_name("overdue", "en") == "Overdue"
    assert sheet_name("cover", "en") == "Cover"
    assert sheet_name("data_quality", "en") == "Data_Quality"


def test_t_format_and_fallback():
    assert "Tổng" in t("all_issues.total_records", "vi", count=3)
    assert "Total" in t("all_issues.total_records", "en", count=3)
    # Missing key → return key
    assert t("no.such.key") == "no.such.key"
