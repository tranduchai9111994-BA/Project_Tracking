"""
Trạng thái bản đang chạy: phát hiện code mới, restart, git (chỉ báo).

Các bất biến ở đây đều xuất phát từ bug đã gặp thật khi làm tính năng, ghi lại để
không tái diễn:
  * `os.path.commonpath` raise khi khác ổ đĩa (stdlib ở C:, project ở D:).
  * venv nằm TRONG project ⇒ site-packages bị tính là source (317 file thay vì 29).
  * `list2cmdline` escape quote kiểu MSVC (`\\"`) mà cmd.exe không hiểu ⇒ lệnh lồng
    im lặng không chạy, `Popen` vẫn báo thành công.
  * static phải `no-cache`; nếu ai đó set SEND_FILE_MAX_AGE_DEFAULT thì quay lại
    thời JS cũ mà không ai biết.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from unittest.mock import patch

import pytest

from analyzer import build_info as bi
from analyzer import restart_service as rs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ==========================================================================
# Đường dẫn — bẫy đa ổ đĩa trên Windows
# ==========================================================================

class TestIsInside:
    def test_file_trong_root(self):
        assert bi._is_inside(os.path.join(ROOT, "app.py"), ROOT)

    def test_file_ngoai_root(self):
        assert not bi._is_inside(os.path.dirname(ROOT), ROOT)

    def test_khac_o_dia_khong_raise(self):
        """`commonpath` raise ValueError ở đây — đó là lý do không dùng nó."""
        assert bi._is_inside("C:/Windows/py.py", "D:/Project") is False
        assert bi._is_inside("/usr/lib/x.py", "/srv/app") is False

    def test_khong_phan_biet_hoa_thuong_tren_windows(self):
        if os.name != "nt":
            pytest.skip("chỉ áp dụng cho Windows")
        assert bi._is_inside(os.path.join(ROOT.upper(), "app.py"), ROOT.lower())

    def test_khong_khop_prefix_nham(self):
        """`/srv/app2` không nằm trong `/srv/app`."""
        assert not bi._is_inside("/srv/app2/x.py", "/srv/app")


# ==========================================================================
# Nguồn theo dõi — tự phát hiện, không hardcode
# ==========================================================================

class TestLoadedSourceFiles:
    def test_bat_duoc_module_cua_project(self):
        files = bi.loaded_source_files(ROOT)
        rel = {os.path.relpath(f, ROOT).replace(os.sep, "/") for f in files}
        assert "analyzer/build_info.py" in rel

    def test_loai_venv_va_site_packages(self):
        """
        Bug đã gặp: venv do start.bat tạo nằm TRONG project, nên mọi thư viện bị
        tính là code của mình — 317 file thay vì 29, badge đầy path thư viện.
        """
        files = bi.loaded_source_files(ROOT)
        for f in files:
            low = f.replace(os.sep, "/").lower()
            assert "site-packages" not in low, f
            assert "/venv/" not in low, f
            assert "/.venv/" not in low, f

    def test_khong_lay_stdlib(self):
        files = bi.loaded_source_files(ROOT)
        assert all(bi._is_inside(f, ROOT) for f in files)
        assert not any("json/decoder.py" in f.replace(os.sep, "/") for f in files)

    def test_dependency_roots_tim_ra_venv_dang_chay(self):
        """Phát hiện từ runtime, không hardcode tên `venv` — đúng cho cả `.venv`, `env`."""
        roots = bi._dependency_roots()
        assert sys.prefix in roots
        assert any("site-packages" in r or "dist-packages" in r for r in roots)

    def test_loai_file_trong_venv_nam_long_trong_project(self, tmp_path, monkeypatch):
        """
        Bất biến gốc của bug 317-file, kiểm tất định thay vì đếm số lượng.

        Không dùng phép đếm ngưỡng: khi chạy cả suite, pytest import ~90 file test
        nên số đếm phụ thuộc cách chạy — test sẽ pass lúc chạy riêng và fail lúc
        chạy chung.
        """
        import types

        root = tmp_path
        lib = root / "venv" / "Lib" / "site-packages" / "thuvien.py"
        lib.parent.mkdir(parents=True)
        lib.write_text("x = 1", encoding="utf-8")
        mine = root / "cua_toi.py"
        mine.write_text("y = 1", encoding="utf-8")

        for name, path in (("thuvien_gia", lib), ("cua_toi_gia", mine)):
            mod = types.ModuleType(name)
            mod.__file__ = str(path)
            monkeypatch.setitem(sys.modules, name, mod)
        monkeypatch.setattr(bi, "_dependency_roots", lambda: [str(root / "venv")])

        got = {os.path.basename(f) for f in bi.loaded_source_files(str(root))}
        assert "cua_toi.py" in got
        assert "thuvien.py" not in got


# ==========================================================================
# build_info — phân biệt "cần restart" với "chỉ cần reload"
# ==========================================================================

class TestBuildInfo:
    def test_vua_khoi_dong_thi_sach(self):
        info = bi.build_info(ROOT, time.time() + 60)  # mốc ở tương lai
        assert info["needs_restart"] is False
        assert info["server_changed"] == []
        assert info["static_changed"] == []

    def test_moi_thu_cu_hon_thi_bao_het(self):
        info = bi.build_info(ROOT, 0)
        assert info["needs_restart"] is True
        assert info["server_changed"]

    def test_py_va_template_vao_server_changed(self):
        info = bi.build_info(ROOT, 0)
        paths = {f["path"] for f in info["server_changed"]}
        assert any(p.endswith(".py") for p in paths)
        assert any(p.startswith("templates/") for p in paths)

    def test_js_khong_doi_hoi_restart(self):
        """
        Đổi JS/CSS chỉ cần reload: Flask trả static kèm `no-cache` + ETag nên nội
        dung mới về ngay. Gộp chung sẽ bắt người dùng restart vô cớ.
        """
        info = bi.build_info(ROOT, 0)
        server = {f["path"] for f in info["server_changed"]}
        static = {f["path"] for f in info["static_changed"]}
        assert any(p.startswith("static/js/") for p in static)
        assert not any(p.startswith("static/") for p in server)

    def test_bo_qua_file_khong_duoc_import(self, tmp_path, monkeypatch):
        """
        Sửa script tạm hay test không đòi restart server. Cách dùng sys.modules cho
        việc này miễn phí — không cần danh sách loại trừ.

        Không thể khẳng định "tests/ không bao giờ xuất hiện": chính pytest đã
        import các module test nên chúng nằm trong sys.modules. Bất biến thật là
        **file chưa được import thì không bị tính**, kiểm bằng file mới tạo.
        """
        stray = tmp_path / "_khong_ai_import.py"
        stray.write_text("x = 1", encoding="utf-8")
        info = bi.build_info(str(tmp_path), 0)
        assert info["server_changed"] == []
        assert info["needs_restart"] is False

    def test_sap_xep_moi_nhat_truoc(self):
        changed = bi.build_info(ROOT, 0)["server_changed"]
        times = [f["mtime"] for f in changed]
        assert times == sorted(times, reverse=True)

    def test_static_mtime_de_client_so_voi_luc_nap_trang(self):
        """
        Frontend so mốc này với **thời điểm trang được nạp**, không phải với lúc
        server khởi động — trang có thể nạp muộn hơn server rất nhiều.
        """
        info = bi.build_info(ROOT, 0)
        assert info["static_mtime"] > 0
        assert info["static_mtime"] >= max(f["mtime"] for f in info["static_changed"])

    def test_co_thong_tin_interpreter(self):
        info = bi.build_info(ROOT, 0)
        assert info["python"]["executable"]
        assert isinstance(info["python"]["in_venv"], bool)


# ==========================================================================
# Git — chỉ đọc. Không pull, không reset.
# ==========================================================================

class TestGitStatus:
    def test_khong_fetch_khi_khong_yeu_cau(self):
        """`git fetch` cần mạng; endpoint poll gọi phải nhanh và offline-safe."""
        with patch.object(bi, "_git", wraps=bi._git) as spy:
            bi.git_status(ROOT, fetch=False)
        called = [c.args[1:] for c in spy.call_args_list]
        assert not any(a and a[0] == "fetch" for a in called)

    def test_bao_so_file_dirty(self):
        info = bi.git_status(ROOT)
        assert info["available"] is True
        assert isinstance(info["dirty_files"], int)
        assert info["branch"]

    def test_khong_bao_gio_chay_lenh_ghi(self):
        """
        Bất biến bảo mật + an toàn dữ liệu: một endpoint pull/reset được từ UI web
        là đường thực thi code tuỳ ý, và sẽ xoá việc chưa commit của người dùng.
        """
        src = open(os.path.join(ROOT, "analyzer", "build_info.py"), encoding="utf-8").read()
        for bad in ("\"pull\"", "'pull'", "\"reset\"", "\"checkout\"", "\"merge\"",
                    "\"stash\"", "\"clean\""):
            assert bad not in src, f"build_info.py không được chạy git {bad}"

    def test_git_khong_raise_khi_loi(self):
        rc, out = bi._git(ROOT, "khong-phai-lenh-that")
        assert rc != 0 and out == ""


# ==========================================================================
# Restart — giao cho launcher, không tự exec
# ==========================================================================

class TestCanRestart:
    def test_can_duoc_tren_windows_khi_co_du_file(self):
        ok, why = rs.can_restart(ROOT)
        if os.name == "nt":
            assert ok, why
        else:
            assert not ok and "Windows" in why

    def test_bao_ro_ly_do_khi_khong_ho_tro(self):
        with patch.object(os, "name", "posix"):
            ok, why = rs.can_restart(ROOT)
        assert not ok
        assert "start.sh" in why  # nói rõ phải làm gì thay thế

    def test_thieu_helper_thi_tu_choi(self, tmp_path):
        (tmp_path / "start.bat").write_text("@echo off")
        with patch.object(os, "name", "nt"):
            ok, why = rs.can_restart(str(tmp_path))
        assert not ok and rs.HELPER_WINDOWS in why


class TestSpawnRestart:
    def test_khong_co_quote_long_trong_argv(self):
        """
        Bug đã gặp: truyền lệnh lồng vào `cmd /c` thì list2cmdline sinh `\\"x\\"`
        — quy ước MSVC, cmd.exe không hiểu — nên KHÔNG GÌ CHẠY mà Popen vẫn báo
        thành công. Toàn bộ script phải nằm trong file .bat.
        """
        if os.name != "nt":
            pytest.skip("chỉ áp dụng cho Windows")
        with patch.object(subprocess, "Popen") as popen:
            popen.return_value.pid = 1234
            rs.spawn_restart(ROOT)
        argv = popen.call_args.args[0]
        assert argv == ["cmd", "/c", rs.HELPER_WINDOWS]
        assert '\\"' not in subprocess.list2cmdline(argv)

    def test_khong_de_con_thua_huong_socket(self):
        """Nếu con giữ socket lắng nghe, server mới không bind được port."""
        if os.name != "nt":
            pytest.skip("chỉ áp dụng cho Windows")
        with patch.object(subprocess, "Popen") as popen:
            popen.return_value.pid = 1
            rs.spawn_restart(ROOT)
        assert popen.call_args.kwargs["close_fds"] is True

    def test_truyen_co_tat_browser_va_danh_dau_restart(self):
        if os.name != "nt":
            pytest.skip("chỉ áp dụng cho Windows")
        with patch.object(subprocess, "Popen") as popen:
            popen.return_value.pid = 1
            rs.spawn_restart(ROOT)
        env = popen.call_args.kwargs["env"]
        assert env["IHRP_NO_BROWSER"] == "1"
        assert env["IHRP_RESTART"] == "1"

    def test_quay_ve_cach_thuong_khi_breakaway_bi_tu_choi(self):
        """Không phải Job Object nào cũng cho breakaway — không được vì thế mà chết."""
        if os.name != "nt":
            pytest.skip("chỉ áp dụng cho Windows")
        calls = []

        def fake(*a, **k):
            calls.append(k["creationflags"])
            if len(calls) == 1:
                raise OSError("job không cho breakaway")
            class P:
                pid = 7
            return P()

        with patch.object(subprocess, "Popen", side_effect=fake):
            out = rs.spawn_restart(ROOT)
        assert len(calls) == 2
        assert out["breakaway"] is False
        assert out["spawned"] is True

    def test_khong_dung_execv_hay_tu_spawn_python(self):
        """
        Tự thay ảnh process trong khi đang giữ socket là đường dễ treo.

        Quét trên AST chứ không trên text: docstring của module có nhắc `os.execv`
        và `python app.py` để giải thích **vì sao không** dùng chúng, quét text sẽ
        khớp vào đó và báo sai.
        """
        import ast

        path = os.path.join(ROOT, "analyzer", "restart_service.py")
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())

        names = {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        } | {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        }
        for bad in ("execv", "execve", "execl", "fork"):
            assert bad not in names, f"không được gọi {bad}"

        # Docstring cũng là ast.Constant, mà docstring ở đây có nhắc "python app.py"
        # để giải thích lý do không dùng → phải loại ra trước khi quét.
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc is not None:
                    docstrings.add(doc)

        literals = {
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and node.value not in docstrings
        }
        # Không tự khởi chạy app — phải đi qua launcher.
        assert not any("app.py" in s for s in literals), literals


# ==========================================================================
# Launcher — các mốc mà restart_service phụ thuộc vào
# ==========================================================================

class TestLauncherContract:
    def _read(self, name):
        with open(os.path.join(ROOT, name), encoding="utf-8", errors="replace") as f:
            return f.read()

    def test_helper_dung_start_de_cat_cay_process(self):
        """
        start.bat có `taskkill /F /T` — /T kill cả cây con theo PPID. Nếu start.bat
        là con trực tiếp của server thì nó tự kill chính mình. `start` tạo process
        mới rồi cmd trung gian thoát, nên cha trở thành PID đã chết.
        """
        src = self._read(rs.HELPER_WINDOWS)
        assert re.search(r'start\s+""\s+"%~dp0start\.bat"', src)

    def test_start_bat_ton_trong_co_tat_browser(self):
        src = self._read(rs.LAUNCHER_WINDOWS)
        assert "IHRP_NO_BROWSER" in src
        idx = src.index("IHRP_NO_BROWSER")
        assert "start %APP_URL%" in src[idx:], "cờ phải bọc đúng lệnh mở browser"

    def test_start_bat_khong_treo_pause_khi_la_ban_restart(self):
        """
        Lần restart kế tiếp sẽ taskkill python này ⇒ exit code khác 0. Nếu vẫn
        `pause` thì mỗi lần restart để lại một cửa sổ treo kèm thông báo "[LOI]"
        sai lệch. Chạy tay thì vẫn phải dừng để đọc log.
        """
        src = self._read(rs.LAUNCHER_WINDOWS)
        assert "IHRP_RESTART" in src
        assert re.search(r'if /I "%IHRP_RESTART%"=="1"[\s\S]{0,200}?exit /b', src)


# ==========================================================================
# API
# ==========================================================================

class TestBuildInfoApi:
    def test_tra_du_khoa_frontend_can(self, flask_client):
        j = flask_client.get("/api/build-info").get_json()
        for k in ("started_at", "needs_restart", "server_changed", "static_changed",
                  "static_mtime", "watched", "python", "restart_available",
                  "build_stamp"):
            assert k in j, k

    def test_khong_goi_git_trong_build_info(self, flask_client):
        """Endpoint này bị poll định kỳ — không được phụ thuộc mạng."""
        with patch.object(bi, "_git") as spy:
            flask_client.get("/api/build-info")
        spy.assert_not_called()

    def test_health_co_started_at_de_poll_luc_restart(self, flask_client_anon):
        """Phải dùng được khi CHƯA đăng nhập: lúc server vừa lên, session có thể chưa sẵn."""
        j = flask_client_anon.get("/api/health").get_json()
        assert j["ok"] is True
        assert isinstance(j["started_at"], int)


class TestRestartApi:
    def test_viewer_bi_tu_choi(self, flask_client):
        with patch("app._auth_current_user", return_value={"role": "viewer"}):
            r = flask_client.post("/api/restart")
        assert r.status_code == 403
        assert r.get_json()["code"] == "FORBIDDEN"

    def test_admin_duoc_phep(self, flask_client):
        with patch("app._auth_current_user", return_value={"role": "admin"}), \
             patch("analyzer.restart_service.spawn_restart",
                   return_value={"spawned": True}) as spawn:
            r = flask_client.post("/api/restart")
        assert r.status_code == 200
        assert r.get_json()["success"] is True
        spawn.assert_called_once()

    def test_bao_501_khi_nen_tang_khong_ho_tro(self, flask_client):
        with patch("app._auth_current_user", return_value={"role": "admin"}), \
             patch("analyzer.restart_service.spawn_restart",
                   side_effect=rs.RestartUnsupported("chỉ Windows")):
            r = flask_client.post("/api/restart")
        assert r.status_code == 501
        assert r.get_json()["code"] == "RESTART_UNSUPPORTED"

    def test_khong_co_endpoint_pull(self, flask_client):
        """Không được tồn tại đường pull/update code qua HTTP."""
        import app as A
        rules = {str(r) for r in A.app.url_map.iter_rules()}
        for bad in ("/api/git-pull", "/api/update", "/api/self-update"):
            assert bad not in rules


class TestGitInfoApi:
    def test_chan_non_localhost(self, flask_client):
        with patch("analyzer.lan_security.is_localhost_request", return_value=False):
            r = flask_client.get("/api/git-info")
        assert r.status_code == 403
        assert r.get_json()["code"] == "LOCALHOST_ONLY"

    def test_mac_dinh_khong_fetch(self, flask_client):
        with patch.object(bi, "git_status", return_value={"available": True}) as spy:
            flask_client.get("/api/git-info")
        assert spy.call_args.kwargs["fetch"] is False

    def test_fetch_khi_co_tham_so(self, flask_client):
        with patch.object(bi, "git_status", return_value={"available": True}) as spy:
            flask_client.get("/api/git-info?fetch=1")
        assert spy.call_args.kwargs["fetch"] is True


# ==========================================================================
# Bất biến cache — nền móng của toàn bộ tính năng này
# ==========================================================================

class TestCacheInvariants:
    def test_khong_set_send_file_max_age(self):
        """
        Static phải `no-cache` + ETag để một lần reload là đủ lấy JS mới. Đó là
        **mặc định của Flask**, không phải config tường minh — ai set biến này để
        "tối ưu" sẽ đưa app về thời phục vụ JS cũ mà không ai biết vì sao.
        """
        import app as A
        assert A.app.config.get("SEND_FILE_MAX_AGE_DEFAULT") is None

    def test_static_tra_no_cache(self, flask_client):
        cc = flask_client.get("/static/js/dashboard.js").headers.get("Cache-Control", "")
        assert "no-cache" in cc


# ==========================================================================
# Nối dây frontend
# ==========================================================================

class TestFrontendWiring:
    @pytest.fixture(scope="class")
    def html(self):
        with open(os.path.join(ROOT, "templates", "index.html"), encoding="utf-8") as f:
            return f.read()

    @pytest.fixture(scope="class")
    def js(self):
        with open(os.path.join(ROOT, "static", "js", "dashboard.js"), encoding="utf-8") as f:
            return f.read()

    def test_co_badge_tren_header(self, html):
        assert 'id="buildStatusBtn"' in html
        assert 'onclick="openBuildStatus()"' in html

    def test_moi_handler_deu_ton_tai(self, html, js):
        """Nút gọi hàm không tồn tại là bug từng gặp; ESLint không thấy được HTML."""
        # `restartServer` giữ lại làm export (waitForServer, integration khác có
        # thể gọi) nhưng không còn onclick trực tiếp — thay bằng `applyUpdate`
        # (nút gộp restart + reload). Xem docstring `applyUpdate` trong dashboard.js.
        for fn in ("openBuildStatus", "closeBuildStatus", "checkGithubUpdate",
                   "applyUpdate", "cancelRestartWait", "resetUiPrefs"):
            assert f'onclick="{fn}(' in html, f"{fn} chưa gắn vào HTML"
            assert f"window.{fn} =" in js, f"{fn} chưa export ra global"

    def test_co_overlay_cho_server(self, html):
        assert 'id="restartOverlay"' in html
        assert 'id="restartOverlayElapsed"' in html

    def test_poll_health_chu_khong_poll_build_info_luc_restart(self, js):
        """
        Lúc chờ server, chỉ `/api/health` là chắc chắn trả lời được (không cần
        đăng nhập). Poll endpoint cần auth sẽ treo nếu session chưa sẵn sàng.
        """
        body = js[js.index("function waitForServer"):]
        body = body[:body.index("function cancelWait")]
        assert "/api/health" in body
        assert "/api/build-info" not in body

    def test_reset_khong_tu_nhan_la_clear_cache(self, js):
        """
        JS không xoá được HTTP cache — `location.reload(true)` bị mọi browser hiện
        đại bỏ qua. Gắn nhãn "clear cache" cho việc xoá localStorage là nói sai.
        """
        body = js[js.index("function resetPrefs"):]
        body = body[:body.index("function openModal")]
        assert "localStorage.clear" in body
        assert "confirm(" in body, "phải xác nhận — đây là dữ liệu người dùng tự sắp đặt"
        assert "reload(true)" not in js
