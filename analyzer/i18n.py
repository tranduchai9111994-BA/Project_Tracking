"""
i18n server-side — nhãn Excel/PDF export theo ngôn ngữ.

UI bilingual dùng static/js/i18n.js; module này phục vụ backend export
(sheet name, header, banner title). Fallback: VI nếu thiếu key EN.
"""
from __future__ import annotations

from typing import Any, Optional

SUPPORTED_LANGS = ("vi", "en")
DEFAULT_LANG = "vi"


def normalize_lang(lang: Optional[str]) -> str:
    """Chuẩn hoá lang query/body → 'vi' | 'en'."""
    s = str(lang or "").strip().lower()
    if s.startswith("en"):
        return "en"
    return "vi"


# ---- Sheet names (Excel 31-char limit; tránh ký tự đặc biệt) ----
SHEET_NAMES: dict[str, dict[str, str]] = {
    "vi": {
        "cover": "Tong_quan",
        "overdue": "Tre_han",
        "unassigned": "Chua_PIC",
        "stalled": "Dinh_tre",
        "high_risk": "Rui_ro_cao",
        "aging_wip": "Aging_WIP",
        "data_quality": "Chat_luong_DL",
        "bookmark": "Bookmark",
        "overdue_report": "Bao_cao_tre",
        "summary": "Tom_tat",
        "anomaly": "Bat_thuong",
    },
    "en": {
        "cover": "Cover",
        "overdue": "Overdue",
        "unassigned": "Unassigned",
        "stalled": "Stalled",
        "high_risk": "High_Risk",
        "aging_wip": "Aging_WIP",
        "data_quality": "Data_Quality",
        "bookmark": "Bookmark",
        "overdue_report": "Overdue_Report",
        "summary": "Summary",
        "anomaly": "Anomalies",
    },
}

# ---- Labels / titles ----
_STRINGS: dict[str, dict[str, str]] = {
    "vi": {
        "all_issues.title": "BÁO CÁO TỔNG HỢP VẤN ĐỀ",
        "all_issues.export_date": "Ngày xuất",
        "all_issues.filter": "Filter đang áp dụng",
        "all_issues.total_records": "Tổng: {count} record",
        "all_issues.sheet.overdue": "Trễ hạn",
        "all_issues.sheet.unassigned": "Chưa có PIC",
        "all_issues.sheet.stalled": "Đình trệ",
        "all_issues.sheet.high_risk": "Rủi ro cao",
        "all_issues.sheet.aging": "Aging WIP",
        "all_issues.sheet.dq": "Chất lượng dữ liệu",
        "all_issues.sheet.bookmark": "Bookmark",
        "dq.title": "Báo cáo Data Quality",
        "overdue.title": "Báo cáo Overdue",
        "col.ma_cn": "Mã CN",
        "col.ten_cn": "Tên chức năng",
        "col.module": "Module",
        "col.phase": "Phase",
        "col.status": "Status",
        "col.pic": "PIC",
        "col.end": "End",
        "col.days_late": "Ngày trễ",
        "col.severity": "Mức độ",
        "col.code": "Mã lỗi",
        "col.label": "Nhãn",
        "col.detail": "Chi tiết",
        "col.suggestion": "Gợi ý",
        "col.priority": "Priority",
        "col.row": "Dòng",
        "anomaly.card": "Bất thường",
        "anomaly.phase_overlap": "Phase overlap ngày",
        "anomaly.estimate_vs_duration": "Estimate MH lệch duration",
    },
    "en": {
        "all_issues.title": "ALL ISSUES REPORT",
        "all_issues.export_date": "Export date",
        "all_issues.filter": "Active filters",
        "all_issues.total_records": "Total: {count} records",
        "all_issues.sheet.overdue": "Overdue",
        "all_issues.sheet.unassigned": "Unassigned",
        "all_issues.sheet.stalled": "Stalled",
        "all_issues.sheet.high_risk": "High Risk",
        "all_issues.sheet.aging": "Aging WIP",
        "all_issues.sheet.dq": "Data Quality",
        "all_issues.sheet.bookmark": "Bookmark",
        "dq.title": "Data Quality Report",
        "overdue.title": "Overdue Report",
        "col.ma_cn": "Code",
        "col.ten_cn": "Function Name",
        "col.module": "Module",
        "col.phase": "Phase",
        "col.status": "Status",
        "col.pic": "PIC",
        "col.end": "End",
        "col.days_late": "Days late",
        "col.severity": "Severity",
        "col.code": "Issue code",
        "col.label": "Label",
        "col.detail": "Detail",
        "col.suggestion": "Suggestion",
        "col.priority": "Priority",
        "col.row": "Row",
        "anomaly.card": "Anomalies",
        "anomaly.phase_overlap": "Overlapping phase dates",
        "anomaly.estimate_vs_duration": "Estimate MH vs duration mismatch",
    },
}


def sheet_name(key: str, lang: Optional[str] = None) -> str:
    """Tên sheet theo lang; fallback VI rồi key thô."""
    lang = normalize_lang(lang)
    return (
        SHEET_NAMES.get(lang, {}).get(key)
        or SHEET_NAMES["vi"].get(key)
        or key
    )


def t(key: str, lang: Optional[str] = None, **kwargs: Any) -> str:
    """Lấy chuỗi đã dịch; format kwargs nếu có. Fallback VI → key."""
    lang = normalize_lang(lang)
    text = _STRINGS.get(lang, {}).get(key)
    if text is None:
        text = _STRINGS["vi"].get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            return text
    return text
