"""
Tests cho T33 Public API — token CRUD + verify + rate limit + read endpoints.

Chia 3 nhóm:
  A. Unit tests analyzer/public_api.py (không dùng Flask)
  B. HTTP tests admin CRUD /api/projects/<slug>/public-tokens
  C. HTTP tests public read /public/api/v1/... + scope check + rate limit
"""
from __future__ import annotations

import io
import os
import time

import pytest

from analyzer import public_api as pubapi


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

@pytest.fixture
def project_dir(tmp_path):
    d = tmp_path / "proj_test"
    d.mkdir()
    return str(d)


def _upload(client, xlsx_path):
    with open(xlsx_path, "rb") as f:
        return client.post(
            "/api/projects/default/upload",
            data={"file": (io.BytesIO(f.read()), "sample.xlsx")},
            content_type="multipart/form-data",
        )


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """Reset rate-limit buckets giữa các test để test isolation."""
    pubapi.reset_rate_limit()
    yield
    pubapi.reset_rate_limit()


# ==========================================================================
# A. Unit tests analyzer/public_api.py
# ==========================================================================

class TestTokenCRUD:
    def test_list_empty(self, project_dir):
        assert pubapi.list_tokens(project_dir) == []

    def test_create_returns_plaintext_and_masked(self, project_dir):
        plain, entry = pubapi.create_token(project_dir, name="Partner A", scope=["summary"])
        assert plain.startswith("pub_")
        assert len(plain) == len("pub_") + 40   # 40 hex chars
        assert entry["name"] == "Partner A"
        assert entry["scope"] == ["summary"]
        assert entry["revoked"] is False
        # Masked view không có token_hash / plaintext
        assert "token_hash" not in entry
        assert "token" not in entry
        # Token prefix có 12 ký tự: "pub_" + 8 hex
        assert entry["token_prefix"] == plain[:12]

    def test_create_persists_across_reads(self, project_dir):
        pubapi.create_token(project_dir, name="A", scope=["summary"])
        pubapi.create_token(project_dir, name="B", scope=["overdue"])
        tokens = pubapi.list_tokens(project_dir)
        assert len(tokens) == 2
        names = {t["name"] for t in tokens}
        assert names == {"A", "B"}

    def test_create_requires_name(self, project_dir):
        with pytest.raises(pubapi.PublicApiError):
            pubapi.create_token(project_dir, name="", scope=["summary"])
        with pytest.raises(pubapi.PublicApiError):
            pubapi.create_token(project_dir, name="   ", scope=["summary"])

    def test_create_requires_scope(self, project_dir):
        with pytest.raises(pubapi.PublicApiError):
            pubapi.create_token(project_dir, name="X", scope=[])
        with pytest.raises(pubapi.PublicApiError):
            pubapi.create_token(project_dir, name="X", scope=None)

    def test_create_normalizes_scope_underscore_to_dash(self, project_dir):
        _, entry = pubapi.create_token(project_dir, name="X", scope=["module_overview"])
        assert entry["scope"] == ["module-overview"]

    def test_create_accepts_scope_string_csv(self, project_dir):
        _, entry = pubapi.create_token(project_dir, name="X", scope="summary,overdue,stalled")
        # Sorted
        assert entry["scope"] == ["overdue", "stalled", "summary"]

    def test_create_dedupes_scope(self, project_dir):
        _, entry = pubapi.create_token(project_dir, name="X", scope=["summary", "summary", "SUMMARY".lower()])
        assert entry["scope"] == ["summary"]

    def test_revoke_marks_flag(self, project_dir):
        _, entry = pubapi.create_token(project_dir, name="X", scope=["*"])
        assert pubapi.revoke_token(project_dir, entry["id"]) is True
        tokens = pubapi.list_tokens(project_dir)
        assert tokens[0]["revoked"] is True

    def test_revoke_missing_returns_false(self, project_dir):
        assert pubapi.revoke_token(project_dir, "nonexistent-uuid") is False

    def test_revoke_idempotent(self, project_dir):
        _, entry = pubapi.create_token(project_dir, name="X", scope=["*"])
        pubapi.revoke_token(project_dir, entry["id"])
        # Gọi lần 2 vẫn OK (không raise)
        assert pubapi.revoke_token(project_dir, entry["id"]) is True

    def test_cap_active_tokens(self, project_dir, monkeypatch):
        # Giảm cap để test nhanh
        monkeypatch.setattr(pubapi, "_MAX_TOKENS_PER_PROJECT", 3)
        for i in range(3):
            pubapi.create_token(project_dir, name=f"T{i}", scope=["*"])
        with pytest.raises(pubapi.PublicApiError, match="giới hạn"):
            pubapi.create_token(project_dir, name="T4", scope=["*"])
        # Revoke 1 → có thể tạo thêm
        toks = pubapi.list_tokens(project_dir)
        pubapi.revoke_token(project_dir, toks[0]["id"])
        pubapi.create_token(project_dir, name="T4", scope=["*"])   # OK


class TestVerifyToken:
    def test_verify_valid(self, project_dir):
        plain, _ = pubapi.create_token(project_dir, name="X", scope=["summary", "overdue"])
        entry = pubapi.verify_token(project_dir, plain)
        assert entry["name"] == "X"
        # Với scope
        pubapi.verify_token(project_dir, plain, required_scope="summary")

    def test_verify_wildcard_scope(self, project_dir):
        plain, _ = pubapi.create_token(project_dir, name="X", scope=["*"])
        pubapi.verify_token(project_dir, plain, required_scope="anything-here")

    def test_verify_scope_mismatch_raises(self, project_dir):
        plain, _ = pubapi.create_token(project_dir, name="X", scope=["summary"])
        with pytest.raises(pubapi.TokenScopeError):
            pubapi.verify_token(project_dir, plain, required_scope="overdue")

    def test_verify_missing_token_raises(self, project_dir):
        with pytest.raises(pubapi.InvalidTokenError):
            pubapi.verify_token(project_dir, "pub_nonexistent")
        # Empty
        with pytest.raises(pubapi.InvalidTokenError):
            pubapi.verify_token(project_dir, "")
        # Wrong prefix
        with pytest.raises(pubapi.InvalidTokenError):
            pubapi.verify_token(project_dir, "wrong_format_token")

    def test_verify_revoked_raises(self, project_dir):
        plain, entry = pubapi.create_token(project_dir, name="X", scope=["*"])
        pubapi.revoke_token(project_dir, entry["id"])
        with pytest.raises(pubapi.InvalidTokenError, match="revoke"):
            pubapi.verify_token(project_dir, plain)

    def test_verify_scope_normalizes_underscore(self, project_dir):
        plain, _ = pubapi.create_token(project_dir, name="X", scope=["module-overview"])
        # Required scope "module_overview" — should normalize và pass
        pubapi.verify_token(project_dir, plain, required_scope="module_overview")

    def test_touch_last_used(self, project_dir):
        plain, entry = pubapi.create_token(project_dir, name="X", scope=["*"])
        pubapi.touch_last_used(project_dir, entry["id"])
        tokens = pubapi.list_tokens(project_dir)
        assert tokens[0]["last_used_at"] is not None


class TestRateLimit:
    def test_under_limit_ok(self, monkeypatch):
        # 3 request trong window → OK
        for _ in range(3):
            pubapi.check_rate_limit("tok-A")

    def test_over_limit_raises_429(self, monkeypatch):
        # Set limit thấp để test nhanh
        monkeypatch.setattr(pubapi, "_RL_MAX_REQUESTS", 5)
        pubapi.reset_rate_limit()
        for _ in range(5):
            pubapi.check_rate_limit("tok-B")
        with pytest.raises(pubapi.RateLimitError) as exc:
            pubapi.check_rate_limit("tok-B")
        assert exc.value.retry_after >= 1

    def test_sliding_window_recovery(self, monkeypatch):
        monkeypatch.setattr(pubapi, "_RL_MAX_REQUESTS", 3)
        monkeypatch.setattr(pubapi, "_RL_WINDOW_SEC", 1)
        pubapi.reset_rate_limit()
        # Fill bucket
        for _ in range(3):
            pubapi.check_rate_limit("tok-C")
        with pytest.raises(pubapi.RateLimitError):
            pubapi.check_rate_limit("tok-C")
        # Chờ hết window
        time.sleep(1.1)
        # Có thể request lại
        pubapi.check_rate_limit("tok-C")

    def test_isolation_between_tokens(self, monkeypatch):
        monkeypatch.setattr(pubapi, "_RL_MAX_REQUESTS", 2)
        pubapi.reset_rate_limit()
        pubapi.check_rate_limit("tok-D1")
        pubapi.check_rate_limit("tok-D2")
        pubapi.check_rate_limit("tok-D1")
        pubapi.check_rate_limit("tok-D2")
        with pytest.raises(pubapi.RateLimitError):
            pubapi.check_rate_limit("tok-D1")
        # Token khác vẫn OK 1 lần
        with pytest.raises(pubapi.RateLimitError):
            pubapi.check_rate_limit("tok-D2")


class TestScopeMetadata:
    def test_public_scopes_available(self):
        # Metadata phải include "*" và các scope quan trọng
        keys = {s["key"] for s in pubapi.PUBLIC_SCOPES}
        assert "*" in keys
        assert "summary" in keys
        assert "overdue" in keys
        assert "module-overview" in keys
        # Label tiếng Việt cho user
        for s in pubapi.PUBLIC_SCOPES:
            assert s.get("label"), f"Scope {s} thiếu label"


# ==========================================================================
# B. HTTP admin CRUD
# ==========================================================================

class TestAdminCRUDHTTP:
    def test_list_empty_returns_ok(self, flask_client):
        r = flask_client.get("/api/projects/default/public-tokens")
        assert r.status_code == 200
        assert r.get_json() == {"tokens": []}

    def test_missing_project_returns_404(self, flask_client):
        r = flask_client.get("/api/projects/nonexistent-slug/public-tokens")
        assert r.status_code == 404

    def test_create_returns_plaintext_once(self, flask_client):
        r = flask_client.post(
            "/api/projects/default/public-tokens",
            json={"name": "Partner Confluence", "scope": ["summary", "overdue"]},
        )
        assert r.status_code == 200
        payload = r.get_json()
        assert payload["token"].startswith("pub_")
        assert payload["entry"]["name"] == "Partner Confluence"
        assert set(payload["entry"]["scope"]) == {"summary", "overdue"}
        assert "warning" in payload

    def test_create_missing_name_returns_400(self, flask_client):
        r = flask_client.post(
            "/api/projects/default/public-tokens",
            json={"name": "", "scope": ["*"]},
        )
        assert r.status_code == 400

    def test_create_missing_scope_returns_400(self, flask_client):
        r = flask_client.post(
            "/api/projects/default/public-tokens",
            json={"name": "X", "scope": []},
        )
        assert r.status_code == 400

    def test_list_after_create(self, flask_client):
        flask_client.post(
            "/api/projects/default/public-tokens",
            json={"name": "T1", "scope": ["*"]},
        )
        r = flask_client.get("/api/projects/default/public-tokens")
        assert r.status_code == 200
        tokens = r.get_json()["tokens"]
        assert len(tokens) == 1
        # KHÔNG expose full token/hash trong list
        assert "token" not in tokens[0]
        assert "token_hash" not in tokens[0]
        assert tokens[0]["token_prefix"].startswith("pub_")

    def test_revoke(self, flask_client):
        r_create = flask_client.post(
            "/api/projects/default/public-tokens",
            json={"name": "T1", "scope": ["*"]},
        )
        token_id = r_create.get_json()["entry"]["id"]
        r_del = flask_client.delete(f"/api/projects/default/public-tokens/{token_id}")
        assert r_del.status_code == 200
        # List vẫn còn nhưng revoked=True
        tokens = flask_client.get("/api/projects/default/public-tokens").get_json()["tokens"]
        assert tokens[0]["revoked"] is True

    def test_revoke_missing_returns_404(self, flask_client):
        r = flask_client.delete("/api/projects/default/public-tokens/nonexistent-uuid")
        assert r.status_code == 404

    def test_scopes_metadata_endpoint(self, flask_client):
        r = flask_client.get("/api/projects/default/public-scopes")
        assert r.status_code == 200
        keys = {s["key"] for s in r.get_json()["scopes"]}
        assert "*" in keys
        assert "summary" in keys


# ==========================================================================
# C. Public read endpoints
# ==========================================================================

class TestPublicReadHTTP:
    def _make_token(self, client, scope):
        r = client.post(
            "/api/projects/default/public-tokens",
            json={"name": "test", "scope": scope},
        )
        return r.get_json()["token"]

    def test_summary_requires_token(self, flask_client, sample_xlsx_path):
        _upload(flask_client, sample_xlsx_path)
        r = flask_client.get("/public/api/v1/projects/default/summary")
        assert r.status_code == 401

    def test_summary_wrong_token(self, flask_client, sample_xlsx_path):
        _upload(flask_client, sample_xlsx_path)
        r = flask_client.get(
            "/public/api/v1/projects/default/summary",
            headers={"X-API-Key": "pub_wrongtoken"},
        )
        assert r.status_code == 401

    def test_summary_wrong_scope(self, flask_client, sample_xlsx_path):
        _upload(flask_client, sample_xlsx_path)
        # Token chỉ có scope overdue → không truy cập được summary
        tok = self._make_token(flask_client, ["overdue"])
        r = flask_client.get(
            "/public/api/v1/projects/default/summary",
            headers={"X-API-Key": tok},
        )
        assert r.status_code == 403

    def test_summary_ok_with_summary_scope(self, flask_client, sample_xlsx_path):
        _upload(flask_client, sample_xlsx_path)
        tok = self._make_token(flask_client, ["summary"])
        r = flask_client.get(
            "/public/api/v1/projects/default/summary",
            headers={"X-API-Key": tok},
        )
        assert r.status_code == 200
        payload = r.get_json()
        assert payload["project"]["slug"] == "default"
        assert "summary" in payload
        assert payload["generated_at"]

    def test_summary_ok_with_wildcard(self, flask_client, sample_xlsx_path):
        _upload(flask_client, sample_xlsx_path)
        tok = self._make_token(flask_client, ["*"])
        r = flask_client.get(
            "/public/api/v1/projects/default/summary",
            headers={"X-API-Key": tok},
        )
        assert r.status_code == 200

    def test_summary_query_param_token(self, flask_client, sample_xlsx_path):
        """Iframe tag <iframe src="...?token=..."> — verify query param cũng OK."""
        _upload(flask_client, sample_xlsx_path)
        tok = self._make_token(flask_client, ["summary"])
        r = flask_client.get(
            f"/public/api/v1/projects/default/summary?token={tok}",
        )
        assert r.status_code == 200

    def test_revoked_token_denied(self, flask_client, sample_xlsx_path):
        _upload(flask_client, sample_xlsx_path)
        r_create = flask_client.post(
            "/api/projects/default/public-tokens",
            json={"name": "X", "scope": ["*"]},
        )
        payload = r_create.get_json()
        tok = payload["token"]
        tid = payload["entry"]["id"]
        # Verify ok trước
        r = flask_client.get("/public/api/v1/projects/default/summary",
                             headers={"X-API-Key": tok})
        assert r.status_code == 200
        # Revoke
        flask_client.delete(f"/api/projects/default/public-tokens/{tid}")
        # Bây giờ deny
        r = flask_client.get("/public/api/v1/projects/default/summary",
                             headers={"X-API-Key": tok})
        assert r.status_code == 401

    def test_chart_endpoint_scope_check(self, flask_client, sample_xlsx_path):
        _upload(flask_client, sample_xlsx_path)
        tok_narrow = self._make_token(flask_client, ["overdue"])
        # OK vì scope match
        r = flask_client.get(
            "/public/api/v1/projects/default/charts/overdue",
            headers={"X-API-Key": tok_narrow},
        )
        assert r.status_code == 200
        assert r.get_json()["chart_id"] == "overdue"
        # Deny vì scope không có module-overview
        r = flask_client.get(
            "/public/api/v1/projects/default/charts/module-overview",
            headers={"X-API-Key": tok_narrow},
        )
        assert r.status_code == 403

    def test_chart_unsupported_id_returns_400(self, flask_client, sample_xlsx_path):
        _upload(flask_client, sample_xlsx_path)
        tok = self._make_token(flask_client, ["*"])
        r = flask_client.get(
            "/public/api/v1/projects/default/charts/xyz-not-real",
            headers={"X-API-Key": tok},
        )
        assert r.status_code == 400
        assert "supported" in r.get_json()

    def test_chart_wildcard_token_accesses_all(self, flask_client, sample_xlsx_path):
        _upload(flask_client, sample_xlsx_path)
        tok = self._make_token(flask_client, ["*"])
        for chart_id in ["module-overview", "phase-matrix", "overdue", "stalled",
                         "priority", "complexity"]:
            r = flask_client.get(
                f"/public/api/v1/projects/default/charts/{chart_id}",
                headers={"X-API-Key": tok},
            )
            assert r.status_code == 200, f"Chart {chart_id} failed"

    def test_functions_endpoint_pagination(self, flask_client, sample_xlsx_path):
        _upload(flask_client, sample_xlsx_path)
        tok = self._make_token(flask_client, ["functions"])
        r = flask_client.get(
            "/public/api/v1/projects/default/functions?page=1&size=3",
            headers={"X-API-Key": tok},
        )
        assert r.status_code == 200
        payload = r.get_json()
        assert payload["page"] == 1
        assert payload["size"] == 3
        assert len(payload["items"]) <= 3
        assert payload["total"] >= 1
        # Item schema
        item = payload["items"][0]
        assert "ma_cn" in item
        assert "module" in item
        assert "phase_stats" in item

    def test_no_project_data_returns_404(self, flask_client):
        # Không upload → không có data
        tok_r = flask_client.post(
            "/api/projects/default/public-tokens",
            json={"name": "X", "scope": ["*"]},
        )
        tok = tok_r.get_json()["token"]
        r = flask_client.get(
            "/public/api/v1/projects/default/summary",
            headers={"X-API-Key": tok},
        )
        assert r.status_code == 404

    def test_cors_headers(self, flask_client, sample_xlsx_path):
        _upload(flask_client, sample_xlsx_path)
        tok = self._make_token(flask_client, ["summary"])
        r = flask_client.get(
            "/public/api/v1/projects/default/summary",
            headers={"X-API-Key": tok},
        )
        assert r.headers.get("Access-Control-Allow-Origin") == "*"
        assert "GET" in r.headers.get("Access-Control-Allow-Methods", "")
        assert "X-API-Key" in r.headers.get("Access-Control-Allow-Headers", "")

    def test_options_preflight(self, flask_client):
        r = flask_client.options("/public/api/v1/projects/default/summary")
        # Không cần auth cho preflight
        assert r.status_code == 204
        assert r.headers.get("Access-Control-Allow-Origin") == "*"

    def test_rate_limit_returns_429(self, flask_client, sample_xlsx_path, monkeypatch):
        _upload(flask_client, sample_xlsx_path)
        # Giảm limit để test nhanh
        monkeypatch.setattr(pubapi, "_RL_MAX_REQUESTS", 3)
        pubapi.reset_rate_limit()
        tok = self._make_token(flask_client, ["summary"])
        for _ in range(3):
            r = flask_client.get(
                "/public/api/v1/projects/default/summary",
                headers={"X-API-Key": tok},
            )
            assert r.status_code == 200
        # Request thứ 4 → 429
        r = flask_client.get(
            "/public/api/v1/projects/default/summary",
            headers={"X-API-Key": tok},
        )
        assert r.status_code == 429
        assert r.headers.get("Retry-After")
        assert "retry_after" in r.get_json()


# ==========================================================================
# D. iframe embed (Task 2B)
# ==========================================================================

class TestIframeEmbed:
    def _make_token(self, client, scope):
        r = client.post(
            "/api/projects/default/public-tokens",
            json={"name": "embed-test", "scope": scope},
        )
        return r.get_json()["token"]

    def test_embed_serves_html(self, flask_client, sample_xlsx_path):
        _upload(flask_client, sample_xlsx_path)
        tok = self._make_token(flask_client, ["*"])
        # Embed KHÔNG verify token server-side — JS mới gọi API verify.
        # → HTML render ngay, kể cả không có token (nhưng JS sẽ báo error).
        r = flask_client.get(f"/embed/default/module-overview?token={tok}")
        assert r.status_code == 200
        assert "text/html" in r.content_type
        body = r.data.decode("utf-8")
        # Có canvas + slug + chart_id trong CFG object (JS build URL runtime)
        assert "chartCanvas" in body
        assert '"default"' in body   # slug embedded
        assert '"module-overview"' in body   # chart_id embedded
        assert "/public/api/v1/projects/" in body   # URL prefix có sẵn trong JS

    def test_embed_frame_ancestors_permissive(self, flask_client):
        r = flask_client.get("/embed/default/module-overview?token=pub_x")
        # X-Frame-Options ALLOWALL — override reverse-proxy default
        assert r.headers.get("X-Frame-Options") == "ALLOWALL"
        # CSP frame-ancestors * → nhúng vào bất cứ site nào
        csp = r.headers.get("Content-Security-Policy", "")
        assert "frame-ancestors *" in csp

    def test_embed_unsupported_chart_400(self, flask_client):
        r = flask_client.get("/embed/default/xyz-nonexistent?token=pub_x")
        assert r.status_code == 400
        assert "supported" in r.get_json()

    def test_embed_bg_transparent(self, flask_client):
        r = flask_client.get("/embed/default/module-overview?token=pub_x&bg=transparent")
        body = r.data.decode("utf-8")
        # CSS style dùng 'transparent' thay vì '#ffffff'
        assert "background: transparent" in body

    def test_embed_default_bg_white(self, flask_client):
        r = flask_client.get("/embed/default/module-overview?token=pub_x")
        body = r.data.decode("utf-8")
        assert "background: #ffffff" in body


# ==========================================================================
# E. PNG snapshot (Task 2B — Playwright fallback)
# ==========================================================================

class TestPngSnapshot:
    def _make_token(self, client, scope):
        r = client.post(
            "/api/projects/default/public-tokens",
            json={"name": "png-test", "scope": scope},
        )
        return r.get_json()["token"]

    def test_png_requires_token(self, flask_client, sample_xlsx_path):
        _upload(flask_client, sample_xlsx_path)
        r = flask_client.get("/public/api/v1/projects/default/charts/module-overview/image")
        assert r.status_code == 401

    def test_png_wrong_scope(self, flask_client, sample_xlsx_path):
        _upload(flask_client, sample_xlsx_path)
        tok = self._make_token(flask_client, ["overdue"])
        r = flask_client.get(
            "/public/api/v1/projects/default/charts/module-overview/image",
            headers={"X-API-Key": tok},
        )
        assert r.status_code == 403

    def test_png_unsupported_chart_400(self, flask_client, sample_xlsx_path):
        _upload(flask_client, sample_xlsx_path)
        tok = self._make_token(flask_client, ["*"])
        r = flask_client.get(
            "/public/api/v1/projects/default/charts/xyz-fake/image",
            headers={"X-API-Key": tok},
        )
        assert r.status_code == 400

    def test_png_playwright_fallback_returns_503(self, flask_client, sample_xlsx_path, monkeypatch):
        """
        Playwright thường CHƯA install trong CI. Endpoint phải trả 503 với
        message hướng dẫn cài — không crash. Nếu Playwright ĐÃ install →
        test này skip (chấp nhận cả 200 và 503 = kết quả mong đợi).
        """
        _upload(flask_client, sample_xlsx_path)
        tok = self._make_token(flask_client, ["*"])

        # Force-simulate playwright chưa install bằng cách patch hàm helper
        import app as app_module
        monkeypatch.setattr(
            app_module,
            "_try_playwright_screenshot",
            lambda *a, **kw: "Playwright chưa cài. Chạy: pip install playwright",
        )
        r = flask_client.get(
            "/public/api/v1/projects/default/charts/module-overview/image?w=400&h=200",
            headers={"X-API-Key": tok},
        )
        assert r.status_code == 503
        payload = r.get_json()
        assert "chưa cài" in payload["error"]
        assert "hint" in payload

    def test_png_cache_serves_from_disk(self, flask_client, sample_xlsx_path, monkeypatch, tmp_path):
        """
        Khi có sẵn file cache PNG → serve trực tiếp, KHÔNG gọi Playwright.
        Verify bằng cách tạo cache file thủ công + patch _try_playwright
        thành assert-never-called.
        """
        _upload(flask_client, sample_xlsx_path)
        tok = self._make_token(flask_client, ["*"])

        # Tạo cache file giả trong project dir
        import app as app_module
        cache_dir = app_module._png_cache_dir("default")
        cache_key = app_module._png_cache_key("module-overview", 400, 200, "")
        cache_path = os.path.join(cache_dir, cache_key)
        # PNG magic bytes để mimetype detect đúng
        with open(cache_path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        # Playwright sẽ raise nếu bị gọi — xác nhận serve từ cache
        def _no_call(*a, **kw):
            raise AssertionError("Playwright bị gọi dù có cache")
        monkeypatch.setattr(app_module, "_try_playwright_screenshot", _no_call)

        r = flask_client.get(
            "/public/api/v1/projects/default/charts/module-overview/image?w=400&h=200",
            headers={"X-API-Key": tok},
        )
        assert r.status_code == 200
        assert r.headers.get("X-Cache") == "HIT"
        assert r.content_type.startswith("image/png")

    def test_png_cache_key_deterministic(self):
        import app as app_module
        assert app_module._png_cache_key("module-overview", 800, 400, "") == "module-overview_800x400_white.png"
        assert app_module._png_cache_key("overdue", 400, 200, "transparent") == "overdue_400x200_transparent.png"

    def test_png_w_h_clamped(self, flask_client, sample_xlsx_path, monkeypatch):
        """w/h vượt cap (VD 10000x10000) phải clamp về 1920x1200."""
        _upload(flask_client, sample_xlsx_path)
        tok = self._make_token(flask_client, ["*"])
        captured = {}
        def _capture(url, w, h, out_path, **kw):
            captured["w"] = w
            captured["h"] = h
            # Ghi file placeholder để endpoint không lỗi
            with open(out_path, "wb") as f:
                f.write(b"\x89PNG\r\n\x1a\n")
            return None
        import app as app_module
        monkeypatch.setattr(app_module, "_try_playwright_screenshot", _capture)
        flask_client.get(
            "/public/api/v1/projects/default/charts/module-overview/image?w=10000&h=99999",
            headers={"X-API-Key": tok},
        )
        assert captured["w"] == 1920
        assert captured["h"] == 1200

    def test_png_cors_headers(self, flask_client, sample_xlsx_path, monkeypatch):
        _upload(flask_client, sample_xlsx_path)
        tok = self._make_token(flask_client, ["*"])
        import app as app_module
        # Return err để không phải gọi Playwright thật
        monkeypatch.setattr(
            app_module,
            "_try_playwright_screenshot",
            lambda *a, **kw: "Playwright chưa cài.",
        )
        r = flask_client.get(
            "/public/api/v1/projects/default/charts/module-overview/image",
            headers={"X-API-Key": tok},
        )
        # CORS headers phải luôn present, cả trên error response
        assert r.headers.get("Access-Control-Allow-Origin") == "*"

    def test_png_options_preflight(self, flask_client):
        r = flask_client.options(
            "/public/api/v1/projects/default/charts/module-overview/image"
        )
        assert r.status_code == 204
        assert r.headers.get("Access-Control-Allow-Origin") == "*"
