"""
`?v=` của JS/CSS phải định danh **bản đang chạy**, không phải file trên đĩa.

Bối cảnh (2026-08d): `start.bat` chạy `debug=False` → Jinja giữ template đã
biên dịch trong RAM, Python không nạp lại `.py`. Nhưng `static_ver()` được gọi
lúc render nên trước đây nó đọc mtime *hiện tại* → sửa file là browser tải ngay
**JS mới** trong khi **HTML + backend vẫn là bản lúc khởi động**. Nút HTML cũ
gọi hàm JS mới, hàm đó gọi endpoint backend cũ chưa có → lỗi hiện ở chỗ không
liên quan. Đã xảy ra thật với section FID.

Chốt: PRODUCTION → stamp cố định theo process; `--debug` (template theo đĩa) →
mtime file như cũ.
"""
from __future__ import annotations

import os
import re
import time

import pytest

import app as A


@pytest.fixture
def prod_mode():
    """debug=False + TEMPLATES_AUTO_RELOAD=None — đúng như start.bat."""
    old_debug = A.app.debug
    old_cfg = A.app.config.get("TEMPLATES_AUTO_RELOAD")
    A.app.debug = False
    A.app.config["TEMPLATES_AUTO_RELOAD"] = None
    yield
    A.app.debug = old_debug
    A.app.config["TEMPLATES_AUTO_RELOAD"] = old_cfg


@pytest.fixture
def debug_mode():
    old_debug = A.app.debug
    old_cfg = A.app.config.get("TEMPLATES_AUTO_RELOAD")
    A.app.debug = True
    A.app.config["TEMPLATES_AUTO_RELOAD"] = None
    yield
    A.app.debug = old_debug
    A.app.config["TEMPLATES_AUTO_RELOAD"] = old_cfg


def _touch(rel: str) -> None:
    full = os.path.join(A._STATIC_DIR, rel.replace("/", os.sep))
    now = time.time() + 5  # chắc chắn mtime mới hơn
    os.utime(full, (now, now))


class TestProduction:
    def test_stamp_khong_doi_khi_file_doi(self, prod_mode):
        """Đây là bất biến quan trọng nhất: chưa restart thì không gì đổi."""
        before = A._static_ver("js/dashboard.js")
        st = os.stat(os.path.join(A._STATIC_DIR, "js", "dashboard.js"))
        try:
            _touch("js/dashboard.js")
            assert A._static_ver("js/dashboard.js") == before
        finally:
            os.utime(
                os.path.join(A._STATIC_DIR, "js", "dashboard.js"),
                (st.st_atime, st.st_mtime),
            )

    def test_moi_asset_dung_chung_stamp(self, prod_mode):
        """Cùng 1 bản chạy → cùng 1 stamp, không lệch nhau từng file."""
        vers = {
            A._static_ver(p)
            for p in ("js/dashboard.js", "js/sidebar_hubs.js", "css/style.css")
        }
        assert len(vers) == 1

    def test_stamp_la_so_hop_le(self, prod_mode):
        assert A._static_ver("js/dashboard.js").isdigit()

    def test_stamp_khong_phu_thuoc_file_ton_tai(self, prod_mode):
        """File không có thật vẫn ra stamp — không rơi về "0" gây cache vĩnh viễn."""
        assert A._static_ver("js/khong-ton-tai.js") == A._BUILD_STAMP


class TestDebug:
    def test_theo_mtime_khi_template_bam_dia(self, debug_mode):
        st = os.stat(os.path.join(A._STATIC_DIR, "js", "dashboard.js"))
        before = A._static_ver("js/dashboard.js")
        try:
            _touch("js/dashboard.js")
            assert A._static_ver("js/dashboard.js") != before
        finally:
            os.utime(
                os.path.join(A._STATIC_DIR, "js", "dashboard.js"),
                (st.st_atime, st.st_mtime),
            )

    def test_file_thieu_tra_ve_0(self, debug_mode):
        assert A._static_ver("js/khong-ton-tai.js") == "0"


class TestTemplatesTrackDisk:
    def test_theo_app_debug_khi_config_None(self):
        old = A.app.debug, A.app.config.get("TEMPLATES_AUTO_RELOAD")
        try:
            A.app.config["TEMPLATES_AUTO_RELOAD"] = None
            A.app.debug = True
            assert A._templates_track_disk() is True
            A.app.debug = False
            assert A._templates_track_disk() is False
        finally:
            A.app.debug, A.app.config["TEMPLATES_AUTO_RELOAD"] = old

    def test_config_tuong_minh_thang_app_debug(self):
        old = A.app.debug, A.app.config.get("TEMPLATES_AUTO_RELOAD")
        try:
            A.app.debug = False
            A.app.config["TEMPLATES_AUTO_RELOAD"] = True
            assert A._templates_track_disk() is True
        finally:
            A.app.debug, A.app.config["TEMPLATES_AUTO_RELOAD"] = old


def test_html_render_gan_dung_stamp(flask_client, prod_mode):
    """Kiểm tới tận HTML: mọi asset phải mang cùng stamp của bản đang chạy."""
    html = flask_client.get("/").get_data(as_text=True)
    vers = set(re.findall(r"/static/(?:js|css)/[\w.\-/]+\?v=(\d+)", html))
    assert vers, "không thấy asset nào có ?v="
    assert vers == {A._BUILD_STAMP}


class TestCacheHeaderHtml:
    """
    HTML phải luôn được revalidate. Ghim `?v=` vô nghĩa nếu browser dùng lại HTML
    cũ — bản cũ nhúng `?v=` cũ nên bundle JS cũng bị ghim theo bản cũ.
    """

    def test_html_buoc_revalidate(self, flask_client):
        cc = flask_client.get("/").headers.get("Cache-Control", "")
        assert "no-cache" in cc

    def test_trang_login_cung_the(self, flask_client_anon):
        r = flask_client_anon.get("/login")
        assert "no-cache" in r.headers.get("Cache-Control", "")

    def test_khong_cham_json_api(self, flask_client):
        """API JSON không được vô tình gắn header của HTML."""
        r = flask_client.get("/api/projects")
        assert r.mimetype == "application/json"
        assert "no-cache, must-revalidate" not in r.headers.get("Cache-Control", "")

    def test_khong_cham_file_tai_ve(self, flask_client, sample_xlsx_path):
        import io as _io

        with open(sample_xlsx_path, "rb") as f:
            flask_client.post(
                "/api/upload",
                data={"file": (_io.BytesIO(f.read()), "fl.xlsx")},
                content_type="multipart/form-data",
            )
        r = flask_client.get("/api/projects/default/export-all-issues")
        assert r.status_code == 200
        assert r.mimetype != "text/html"
        assert "no-cache, must-revalidate" not in r.headers.get("Cache-Control", "")
