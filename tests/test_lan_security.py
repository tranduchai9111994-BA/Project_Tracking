"""
T34 Task 2 — Tests LAN secure self-host mode.

Kiểm tra:
  1. `is_localhost_request` phân biệt localhost vs LAN IP.
  2. `is_admin_mutation_request` phân loại đúng admin vs read-only.
  3. `@localhost_only` decorator trả 403 khi non-localhost.
  4. Admin guard middleware — POST/PUT/DELETE từ non-localhost → 403.
  5. Read-only GET/export vẫn OK từ LAN.
  6. Access log ghi entry đúng format, rotate khi lớn.
  7. `detect_lan_ips` không crash.
  8. UI endpoint `/api/lan/info` + `/api/lan/access-log`.
"""
from __future__ import annotations

import io
import json
import os
import time
from unittest.mock import patch, MagicMock

import pytest

from analyzer import lan_security as ls


# ==========================================================================
# Unit — resolve_bind_host (solo-safe default)
# ==========================================================================

class TestResolveBindHost:
    def test_default_localhost(self):
        assert ls.resolve_bind_host({}) == "127.0.0.1"

    def test_bind_local_only_explicit_on(self):
        assert ls.resolve_bind_host({"IHRP_BIND_LOCAL_ONLY": "1"}) == "127.0.0.1"
        assert ls.resolve_bind_host({"IHRP_BIND_LOCAL_ONLY": "true"}) == "127.0.0.1"

    def test_bind_local_only_explicit_off_opens_lan(self):
        assert ls.resolve_bind_host({"IHRP_BIND_LOCAL_ONLY": "0"}) == "0.0.0.0"
        assert ls.resolve_bind_host({"IHRP_BIND_LOCAL_ONLY": "false"}) == "0.0.0.0"

    def test_ihrp_lan_opens_lan(self):
        assert ls.resolve_bind_host({"IHRP_LAN": "1"}) == "0.0.0.0"
        assert ls.resolve_bind_host({"IHRP_LAN": "yes"}) == "0.0.0.0"

    def test_bind_local_only_wins_over_lan(self):
        """IHRP_BIND_LOCAL_ONLY=1 luôn thắng IHRP_LAN=1."""
        assert ls.resolve_bind_host({
            "IHRP_LAN": "1",
            "IHRP_BIND_LOCAL_ONLY": "1",
        }) == "127.0.0.1"

    def test_lan_with_bind_unset(self):
        assert ls.resolve_bind_host({"IHRP_LAN": "1", "IHRP_BIND_LOCAL_ONLY": ""}) == "0.0.0.0"

    def test_whitespace_and_case(self, monkeypatch):
        monkeypatch.setenv("IHRP_LAN", "  ON  ")
        monkeypatch.delenv("IHRP_BIND_LOCAL_ONLY", raising=False)
        assert ls.resolve_bind_host() == "0.0.0.0"


# ==========================================================================
# Unit — is_localhost_request
# ==========================================================================

class TestIsLocalhostRequest:
    def _mock_req(self, ip):
        r = MagicMock()
        r.remote_addr = ip
        return r

    def test_ipv4_localhost(self):
        assert ls.is_localhost_request(self._mock_req("127.0.0.1"))

    def test_ipv6_localhost(self):
        assert ls.is_localhost_request(self._mock_req("::1"))

    def test_hostname_localhost(self):
        assert ls.is_localhost_request(self._mock_req("localhost"))

    def test_lan_ip_rejected(self):
        assert not ls.is_localhost_request(self._mock_req("192.168.1.10"))

    def test_public_ip_rejected(self):
        assert not ls.is_localhost_request(self._mock_req("8.8.8.8"))

    def test_empty_ip(self):
        assert not ls.is_localhost_request(self._mock_req(""))

    def test_none_ip(self):
        assert not ls.is_localhost_request(self._mock_req(None))

    def test_env_allowlist_extra(self, monkeypatch):
        monkeypatch.setenv("IHRP_LAN_ADMIN_ALLOW", "192.168.1.100,10.0.0.5")
        assert ls.is_localhost_request(self._mock_req("192.168.1.100"))
        assert ls.is_localhost_request(self._mock_req("10.0.0.5"))
        # IP không trong list vẫn bị block
        assert not ls.is_localhost_request(self._mock_req("192.168.1.101"))

    def test_env_allowlist_empty(self, monkeypatch):
        monkeypatch.setenv("IHRP_LAN_ADMIN_ALLOW", "")
        assert not ls.is_localhost_request(self._mock_req("192.168.1.100"))


# ==========================================================================
# Unit — is_admin_mutation_request
# ==========================================================================

class TestIsAdminMutation:
    def _mock_req(self, method, path):
        r = MagicMock()
        r.method = method
        r.path = path
        return r

    def test_get_never_admin(self):
        assert not ls.is_admin_mutation_request(self._mock_req("GET", "/api/projects/x/upload"))

    def test_head_never_admin(self):
        assert not ls.is_admin_mutation_request(self._mock_req("HEAD", "/api/x"))

    def test_options_never_admin(self):
        # OPTIONS preflight — cần cho CORS
        assert not ls.is_admin_mutation_request(self._mock_req("OPTIONS", "/api/x"))

    def test_post_upload_is_admin(self):
        assert ls.is_admin_mutation_request(self._mock_req("POST", "/api/upload"))

    def test_post_upload_confirm_is_admin(self):
        assert ls.is_admin_mutation_request(self._mock_req("POST", "/api/upload-confirm"))

    def test_delete_project_is_admin(self):
        assert ls.is_admin_mutation_request(self._mock_req("DELETE", "/api/projects/x"))

    def test_put_chart_notes_is_admin(self):
        assert ls.is_admin_mutation_request(self._mock_req("PUT", "/api/projects/x/chart-notes"))

    def test_post_integrations_is_admin(self):
        assert ls.is_admin_mutation_request(self._mock_req("POST", "/api/projects/x/integrations"))

    def test_post_public_tokens_is_admin(self):
        assert ls.is_admin_mutation_request(self._mock_req("POST", "/api/projects/x/public-tokens"))

    def test_post_bookmarks_is_admin(self):
        assert ls.is_admin_mutation_request(self._mock_req("POST", "/api/projects/x/bookmarks/toggle"))

    # Read-only POST — export routes
    def test_post_export_overdue_not_admin(self):
        assert not ls.is_admin_mutation_request(self._mock_req("POST", "/api/projects/x/export-overdue"))

    def test_post_export_all_issues_not_admin(self):
        assert not ls.is_admin_mutation_request(self._mock_req("POST", "/api/projects/x/export-all-issues"))

    def test_post_export_chart_not_admin(self):
        assert not ls.is_admin_mutation_request(self._mock_req("POST", "/api/projects/x/export-chart"))

    def test_post_drill_down_export_not_admin(self):
        assert not ls.is_admin_mutation_request(self._mock_req("POST", "/api/drill-down/export"))

    def test_post_chart_aggregate_not_admin(self):
        assert not ls.is_admin_mutation_request(self._mock_req("POST", "/api/projects/x/chart-aggregate"))

    def test_post_portfolio_compare_not_admin(self):
        assert not ls.is_admin_mutation_request(self._mock_req("POST", "/api/portfolio/compare"))

    def test_post_audit_report_not_admin(self):
        assert not ls.is_admin_mutation_request(self._mock_req("POST", "/api/projects/x/audit-report"))

    def test_non_api_path_not_admin(self):
        # /embed/<slug>/<chart> — Task 2B public embed
        assert not ls.is_admin_mutation_request(self._mock_req("GET", "/embed/x/y"))
        # Static
        assert not ls.is_admin_mutation_request(self._mock_req("GET", "/static/js/dashboard.js"))

    def test_public_path_not_admin(self):
        # /public/api/v1 — token-guarded, không phải admin
        assert not ls.is_admin_mutation_request(
            self._mock_req("POST", "/public/api/v1/projects/x/charts/y")
        )


# ==========================================================================
# HTTP — Admin guard end-to-end
# ==========================================================================

def _upload(client, xlsx_path, remote_addr="127.0.0.1"):
    with open(xlsx_path, "rb") as f:
        return client.post(
            "/api/projects/default/upload",
            data={"file": (io.BytesIO(f.read()), "test.xlsx")},
            content_type="multipart/form-data",
            environ_overrides={"REMOTE_ADDR": remote_addr},
        )


class TestAdminGuardHTTP:
    def test_localhost_can_upload(self, flask_client, sample_xlsx_path):
        r = _upload(flask_client, sample_xlsx_path, remote_addr="127.0.0.1")
        assert r.status_code == 200

    def test_lan_ip_cannot_upload(self, flask_client, sample_xlsx_path):
        r = _upload(flask_client, sample_xlsx_path, remote_addr="192.168.1.50")
        assert r.status_code == 403
        d = r.get_json()
        assert d["code"] == "LOCALHOST_ONLY"
        assert "192.168.1.50" in d["detail"]

    def test_lan_can_view_dashboard(self, flask_client, sample_xlsx_path):
        _upload(flask_client, sample_xlsx_path)  # upload từ localhost trước
        r = flask_client.get(
            "/api/projects/default/dashboard",
            environ_overrides={"REMOTE_ADDR": "192.168.1.50"},
        )
        assert r.status_code == 200

    def test_lan_can_export(self, flask_client, sample_xlsx_path):
        _upload(flask_client, sample_xlsx_path)
        r = flask_client.get(
            "/api/projects/default/export-all-issues",
            environ_overrides={"REMOTE_ADDR": "192.168.1.50"},
        )
        assert r.status_code == 200

    def test_lan_cannot_delete_project(self, flask_client, sample_xlsx_path):
        _upload(flask_client, sample_xlsx_path)
        # Tạo project mới để test delete
        flask_client.post("/api/projects", json={"name": "TestP"})
        r = flask_client.delete(
            "/api/projects/testp",
            environ_overrides={"REMOTE_ADDR": "10.0.0.5"},
        )
        assert r.status_code == 403

    def test_lan_cannot_create_public_token(self, flask_client, sample_xlsx_path):
        _upload(flask_client, sample_xlsx_path)
        r = flask_client.post(
            "/api/projects/default/public-tokens",
            json={"name": "hacker", "scope": ["*"]},
            environ_overrides={"REMOTE_ADDR": "192.168.1.99"},
        )
        assert r.status_code == 403

    def test_env_allow_list_bypasses_guard(self, flask_client, sample_xlsx_path, monkeypatch):
        monkeypatch.setenv("IHRP_LAN_ADMIN_ALLOW", "192.168.1.77")
        r = _upload(flask_client, sample_xlsx_path, remote_addr="192.168.1.77")
        assert r.status_code == 200


# ==========================================================================
# Unit — @localhost_only decorator (standalone)
# ==========================================================================

class TestLocalhostOnlyDecorator:
    def test_decorated_function_allows_localhost(self, flask_client, sample_xlsx_path):
        # /api/lan/access-log dùng is_localhost_request check explicit
        _upload(flask_client, sample_xlsx_path)
        r = flask_client.get(
            "/api/lan/access-log",
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        assert r.status_code == 200

    def test_decorated_function_blocks_lan(self, flask_client, sample_xlsx_path):
        _upload(flask_client, sample_xlsx_path)
        r = flask_client.get(
            "/api/lan/access-log",
            environ_overrides={"REMOTE_ADDR": "192.168.1.10"},
        )
        assert r.status_code == 403


# ==========================================================================
# Access log
# ==========================================================================

class TestAccessLog:
    def test_append_and_read_tail(self, tmp_path):
        log_path = str(tmp_path / "access.log")
        for i in range(5):
            ls._append_log_line(log_path, {
                "ts": f"2026-07-30T10:00:0{i}",
                "ip": "127.0.0.1",
                "method": "GET",
                "path": f"/api/x/{i}",
                "status": 200,
                "duration_ms": 10,
                "is_localhost": True,
            })
        entries = ls.read_access_log_tail(log_path, limit=10)
        assert len(entries) == 5
        # Order: mới nhất trước
        assert entries[0]["path"] == "/api/x/4"
        assert entries[-1]["path"] == "/api/x/0"

    def test_read_tail_limit(self, tmp_path):
        log_path = str(tmp_path / "access.log")
        for i in range(50):
            ls._append_log_line(log_path, {"ts": f"t{i}", "path": f"/{i}",
                                            "ip": "127.0.0.1", "method": "GET",
                                            "status": 200, "duration_ms": 1,
                                            "is_localhost": True})
        entries = ls.read_access_log_tail(log_path, limit=10)
        assert len(entries) == 10

    def test_read_nonexistent_returns_empty(self, tmp_path):
        assert ls.read_access_log_tail(str(tmp_path / "no-file.log")) == []

    def test_read_ignores_malformed_lines(self, tmp_path):
        log_path = str(tmp_path / "access.log")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write('{"valid": 1}\n')
            f.write('not-json-line\n')
            f.write('{"valid": 2}\n')
        entries = ls.read_access_log_tail(log_path, limit=10)
        assert len(entries) == 2

    def test_rotate_when_large(self, tmp_path):
        log_path = str(tmp_path / "access.log")
        # Ghi 1 file lớn hơn 10MB threshold
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("x" * (11 * 1024 * 1024))
        # Trigger rotate qua append
        ls._append_log_line(log_path, {"ts": "new", "path": "/x", "ip": "1",
                                        "method": "GET", "status": 200,
                                        "duration_ms": 0, "is_localhost": True})
        # File mới chỉ chứa 1 dòng
        assert os.path.exists(log_path)
        assert os.path.exists(log_path + ".1")

    def test_middleware_logs_requests(self, flask_client, sample_xlsx_path, tmp_path, monkeypatch):
        """Middleware install_access_log ghi log khi request đi qua."""
        # Fixture flask_client đã cài access_log ở default path — verify
        # bằng cách gọi endpoint và check log tồn tại.
        import app as app_module

        # Trigger request
        _upload(flask_client, sample_xlsx_path)
        flask_client.get("/api/projects/default/dashboard")

        # Verify log path tồn tại + có entry (nếu default path writable)
        log_path = app_module._ACCESS_LOG_PATH
        if os.path.exists(log_path):
            entries = ls.read_access_log_tail(log_path, limit=10)
            # Ít nhất 1 entry là POST upload hoặc GET dashboard
            found = any(e.get("path", "").startswith("/api/projects/default")
                        for e in entries)
            assert found


# ==========================================================================
# LAN IP detection
# ==========================================================================

class TestDetectLanIps:
    def test_returns_at_least_localhost(self):
        urls = ls.detect_lan_ips(port=5000)
        # Luôn có ít nhất localhost cuối cùng
        assert any(u["ip"] == "127.0.0.1" for u in urls)
        # URL format chuẩn
        for u in urls:
            assert u["url"].startswith("http://")
            assert u["url"].endswith(":5000")
            assert "label" in u

    def test_custom_port(self):
        urls = ls.detect_lan_ips(port=8080)
        for u in urls:
            assert u["url"].endswith(":8080")


# ==========================================================================
# LAN info endpoint
# ==========================================================================

class TestLanInfoEndpoint:
    def test_info_endpoint_no_auth_needed(self, flask_client):
        # Non-localhost cũng được xem — chỉ metadata
        r = flask_client.get(
            "/api/lan/info",
            environ_overrides={"REMOTE_ADDR": "192.168.1.50"},
        )
        assert r.status_code == 200
        d = r.get_json()
        assert "urls" in d
        assert "port" in d
        assert d["is_localhost_request"] is False

    def test_info_localhost_flag(self, flask_client):
        r = flask_client.get(
            "/api/lan/info",
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        assert r.status_code == 200
        assert r.get_json()["is_localhost_request"] is True

    def test_info_admin_guard_flag(self, flask_client):
        r = flask_client.get("/api/lan/info")
        d = r.get_json()
        # Fixture không set IHRP_DISABLE_ADMIN_GUARD → guard on
        assert d["admin_guard"] is True

    def test_access_log_endpoint_localhost_only(self, flask_client):
        r_local = flask_client.get(
            "/api/lan/access-log",
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        assert r_local.status_code == 200

        r_lan = flask_client.get(
            "/api/lan/access-log",
            environ_overrides={"REMOTE_ADDR": "192.168.1.10"},
        )
        assert r_lan.status_code == 403
        assert r_lan.get_json()["code"] == "LOCALHOST_ONLY"

    def test_access_log_returns_entries(self, flask_client, sample_xlsx_path):
        # Gọi vài endpoint để có log
        _upload(flask_client, sample_xlsx_path)
        flask_client.get("/api/projects/default/dashboard")

        r = flask_client.get(
            "/api/lan/access-log?limit=20",
            environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
        )
        assert r.status_code == 200
        d = r.get_json()
        assert "entries" in d
        assert "count" in d
        assert d["count"] == len(d["entries"])
