"""
Quy ước icon theo chiều dữ liệu — chống tái phát lỗi «cùng icon, ngược nghĩa».

Trước đây 📥 và 📤 (hai khay giấy trông gần giống nhau, chỉ khác hướng mũi tên)
bị dùng lẫn cho cả hai chiều, có chỗ nằm sát nhau trong cùng một hàng nút:
  - section «Chiều PM»: 📤 Kế hoạch (.xlsx) = UPLOAD, cạnh 📥 Xuất chiều PM = EXPORT
  - section «Quản lý đầu việc BA»: 📥 Import cạnh 📥 Xuất tất cả

Quy ước đã chốt:
  📥 = chiều RA (xuất / tải về máy)
  ⬆ = chiều VÀO (import / upload)
  📤 = KHÔNG dùng (quá giống 📥 nên luôn gây nhầm)
  ⬇ = KHÔNG dùng cho action (chỉ còn ⬇️/⬆️ làm mũi tên xu hướng trong nhãn metric)
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "templates" / "index.html"
JS_DIR = ROOT / "static" / "js"

OUT = "\U0001F4E5"          # 📥
IN = "\u2B06"               # ⬆
BANNED_TRAY = "\U0001F4E4"  # 📤
TREND_UP = "\u2B06\uFE0F"   # ⬆️ (mũi tên xu hướng, có variation selector)
TREND_DOWN = "\u2B07\uFE0F"  # ⬇️
PLAIN_DOWN = "\u2B07"       # ⬇


def _ui_files() -> list[Path]:
    return [HTML, *sorted(JS_DIR.glob("*.js"))]


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", _ui_files(), ids=lambda p: p.name)
def test_khong_dung_icon_khay_di_ra(path: Path):
    """📤 quá giống 📥 → bỏ hẳn, chiều vào dùng ⬆ cho khác biệt rõ."""
    assert BANNED_TRAY not in _text(path), (
        f"{path.name}: còn dùng 📤. Chiều VÀO dùng ⬆, chiều RA dùng 📥."
    )


@pytest.mark.parametrize("path", _ui_files(), ids=lambda p: p.name)
def test_mui_ten_xuong_chi_dung_lam_xu_huong(path: Path):
    """⬇ trần từng bị dùng cho cả «Tải» và «Áp seed» — nay chỉ còn ⬇️ xu hướng."""
    txt = _text(path).replace(TREND_DOWN, "")
    assert PLAIN_DOWN not in txt, (
        f"{path.name}: ⬇ dùng cho action. Tải về dùng 📥."
    )


# Từ khoá cho biết nút thuộc chiều VÀO.
_INBOUND = re.compile(r"import|upload|tải lên|nạp |kéo về", re.IGNORECASE)

# ...nhưng «Xuất FL chỉnh sửa (re-import)» hay «Đang tạo FL để import» là chiều RA:
# tạo file để *sau này* import lại. Có động từ chiều ra thì không tính là chiều vào.
_OUTBOUND = re.compile(r"xuất|export|tạo |tải về|building", re.IGNORECASE)


def _labels_with(icon: str, txt: str) -> list[str]:
    """Đoạn text ngắn ngay sau icon — xấp xỉ nhãn nút."""
    return [
        m.group(1)
        for m in re.finditer(re.escape(icon) + r"[ \u00A0]?([^<\n\"'`]{0,40})", txt)
    ]


@pytest.mark.parametrize("path", _ui_files(), ids=lambda p: p.name)
def test_icon_xuat_khong_gan_nhan_chieu_vao(path: Path):
    """📥 chỉ cho chiều RA — dán lên nút Import/Upload là nguồn gốc nhầm lẫn."""
    bad = [
        lb for lb in _labels_with(OUT, _text(path))
        if _INBOUND.search(lb) and not _OUTBOUND.search(lb)
    ]
    assert not bad, f"{path.name}: 📥 gắn nhãn chiều vào: {bad}"


@pytest.mark.parametrize("path", _ui_files(), ids=lambda p: p.name)
def test_icon_import_khong_gan_nhan_chieu_ra(path: Path):
    txt = _text(path).replace(TREND_UP, "")
    bad = [
        lb for lb in _labels_with(IN, txt)
        if re.search(r"xuất|export|tải về", lb, re.IGNORECASE)
    ]
    assert not bad, f"{path.name}: ⬆ gắn nhãn chiều ra: {bad}"


# ── Các chỗ cụ thể từng gây nhầm ──────────────────────────────────────────

def test_chieu_pm_upload_khac_icon_voi_export():
    """3 nút cạnh nhau: 2 nạp file (⬆) + 1 xuất (📥) phải nhìn ra ngay."""
    html = _text(HTML)
    assert f"{IN} Nạp Kế hoạch (.xlsx)" in html
    assert f"{IN} Nạp Weekly (.pptx)" in html
    assert f"{OUT} Xuất chiều PM" in html


def test_ba_tasks_import_khac_icon_voi_xuat_tat_ca():
    html = _text(HTML)
    assert f"{IN} Import</button>" in html
    assert f"{OUT} Xuất tất cả</button>" in html


def test_import_project_zip_dung_icon_chieu_vao():
    assert f"{IN} Import project từ .zip" in _text(HTML)


def test_sticky_upload_dung_icon_chieu_vao():
    html = _text(HTML)
    idx = html.index('title="Upload file mới"')
    assert IN in html[idx:idx + 40]


def test_menu_xuat_o_header_dung_icon_chieu_ra():
    assert f"{OUT} Xuất ▾" in _text(HTML)


def test_i18n_dong_bo_icon_ca_2_ngon_ngu():
    """Sót i18n thì đổi ngôn ngữ là icon nhảy về cũ."""
    txt = _text(JS_DIR / "i18n.js")
    assert f'"btn.export_menu": "{OUT} Xuất ▾"' in txt
    assert f'"btn.export_menu": "{OUT} Export ▾"' in txt
    assert f'"btn.upload_excel": "{IN} Tải Excel"' in txt


def test_tieu_de_khong_phai_action_dung_icon_trung_tinh():
    """📥 trên tiêu đề tĩnh làm loãng nghĩa «xuất»."""
    html = _text(HTML)
    assert "📅 Lịch sinh Digest tự động" in html
    assert "📂 Digest lưu trữ" in html
    assert "📄 Mẫu Function List (re-import)" in html
