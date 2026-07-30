"""
T33 Task 2C — Smoke tests cho UI Settings tab "Public API".

Test này KHÔNG chạy browser thật (không có Selenium/Playwright dep). Chỉ:
  1. Verify HTML template có đủ các element cần thiết (id, button, table).
  2. Verify JS bundle có các function global cần được onclick gọi từ template.
  3. Verify end-to-end HTTP flow: create → list → view snippet metadata →
     revoke → list.
"""
from __future__ import annotations

import io
import os
import re
import pytest


TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "templates", "index.html"
)
JS_PATH = os.path.join(os.path.dirname(__file__), "..", "static", "js", "dashboard.js")


@pytest.fixture(scope="module")
def index_html() -> str:
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def dashboard_js() -> str:
    with open(JS_PATH, "r", encoding="utf-8") as f:
        return f.read()


class TestSettingsTabHtml:
    """Kiểm tra template chứa đủ các element mà JS tương tác."""

    def test_public_api_section_present(self, index_html):
        assert 'id="setPublicApiSection"' in index_html
        assert "🌐 Public API" in index_html

    def test_token_list_table_present(self, index_html):
        assert 'id="pubTokListTable"' in index_html
        assert 'id="pubTokListBody"' in index_html
        assert 'id="pubTokListEmpty"' in index_html

    def test_create_form_present(self, index_html):
        assert 'id="pubTokCreatePanel"' in index_html
        assert 'id="pubTokCreateForm"' in index_html
        assert 'id="pubTokName"' in index_html
        assert 'id="pubTokScopeGrid"' in index_html
        # 3 nút quick-select
        for label in ["✔ Tất cả", "✖ Bỏ hết", "🌟 Wildcard *"]:
            assert label in index_html

    def test_new_token_modal_present(self, index_html):
        assert 'id="pubTokNewModal"' in index_html
        assert 'id="pubTokNewValue"' in index_html
        # Cảnh báo 1-lần
        assert "chỉ hiển thị 1 lần" in index_html
        # Snippet tabs
        assert 'data-snip-tab="rest"' in index_html
        assert 'data-snip-tab="iframe"' in index_html
        assert 'data-snip-tab="png"' in index_html
        assert 'id="pubTokSnipBody"' in index_html

    def test_snippet_view_modal_present(self, index_html):
        assert 'id="pubTokSnipModal"' in index_html
        assert 'id="pubTokSnipTokenName"' in index_html
        assert 'data-snip-view-tab="rest"' in index_html
        assert 'id="pubTokSnipViewBody"' in index_html
        # Placeholder pub_YOUR_TOKEN — không expose token thật
        assert "pub_YOUR_TOKEN" in index_html


class TestJsGlobalFunctions:
    """Verify tất cả window.* function mà template onclick gọi đều tồn tại."""

    REQUIRED_GLOBALS = [
        "_pubTokRefresh",
        "_pubTokToggleCreate",
        "_pubTokScopeAll",
        "_pubTokScopeNone",
        "_pubTokScopeWildcard",
        "_pubTokOnScopeToggle",
        "_pubTokSubmitCreate",
        "_pubTokRevoke",
        "_pubTokViewSnippets",
        "_pubTokCloseNewModal",
        "_pubTokCloseSnipModal",
        "_pubTokCopyValue",
        "_pubTokCopySnippet",
        "_pubTokSnipTab",
        "_pubTokSnipUpdate",
    ]

    def test_all_required_globals_defined(self, dashboard_js):
        for name in self.REQUIRED_GLOBALS:
            # Match "window.<name> ="  hoặc "window.<name> = function"
            pattern = re.compile(r"window\." + re.escape(name) + r"\s*=")
            assert pattern.search(dashboard_js), f"Missing global: window.{name}"

    def test_snippet_builder_covers_3_tabs(self, dashboard_js):
        # Verify _pubTokBuildSnippet handle cả rest/iframe/png
        # (không dùng regex phức tạp — chỉ check các fragment key)
        assert '"rest"' in dashboard_js  # tab check
        assert '"iframe"' in dashboard_js
        assert '"png"' in dashboard_js
        # REST snippet chứa curl
        assert "curl -H" in dashboard_js
        # iframe tag
        assert "<iframe" in dashboard_js
        # PNG img tag
        assert "<img src=" in dashboard_js

    def test_settings_modal_hooks_refresh(self, dashboard_js):
        # openSettingsModal phải gọi _pubTokRefresh
        # (chỉ check sự có mặt call — không parse control flow)
        m = re.search(r"openSettingsModal[\s\S]{0,2000}_pubTokRefresh\(\)", dashboard_js)
        assert m, "openSettingsModal phải trigger _pubTokRefresh"


# ==========================================================================
# HTTP end-to-end (dùng flask_client fixture từ conftest)
# ==========================================================================

def _upload(client, xlsx_path):
    with open(xlsx_path, "rb") as f:
        return client.post(
            "/api/projects/default/upload",
            data={"file": (io.BytesIO(f.read()), "sample.xlsx")},
            content_type="multipart/form-data",
        )


class TestSettingsTabFlow:
    def test_full_flow_create_view_revoke(self, flask_client, sample_xlsx_path):
        # Setup: upload để có project data
        _upload(flask_client, sample_xlsx_path)

        # 1. Fetch scopes metadata (dùng để render form)
        r = flask_client.get("/api/projects/default/public-scopes")
        assert r.status_code == 200
        scopes = r.get_json()["scopes"]
        assert any(s["key"] == "*" for s in scopes)

        # 2. List rỗng ban đầu
        r = flask_client.get("/api/projects/default/public-tokens")
        assert r.status_code == 200
        assert r.get_json()["tokens"] == []

        # 3. Create
        r = flask_client.post(
            "/api/projects/default/public-tokens",
            json={"name": "UI test partner", "scope": ["summary", "overdue"]},
        )
        assert r.status_code == 200
        d = r.get_json()
        token = d["token"]
        assert token.startswith("pub_")
        token_id = d["entry"]["id"]

        # 4. List → có 1 token
        r = flask_client.get("/api/projects/default/public-tokens")
        tokens = r.get_json()["tokens"]
        assert len(tokens) == 1
        assert tokens[0]["name"] == "UI test partner"
        assert tokens[0]["revoked"] is False

        # 5. Dùng token — verify hoạt động
        r = flask_client.get(
            "/public/api/v1/projects/default/summary",
            headers={"X-API-Key": token},
        )
        assert r.status_code == 200

        # 6. Revoke
        r = flask_client.delete(f"/api/projects/default/public-tokens/{token_id}")
        assert r.status_code == 200

        # 7. Sau revoke: list vẫn có nhưng revoked=True
        tokens = flask_client.get("/api/projects/default/public-tokens").get_json()["tokens"]
        assert tokens[0]["revoked"] is True

        # 8. Dùng token đã revoke → 401
        r = flask_client.get(
            "/public/api/v1/projects/default/summary",
            headers={"X-API-Key": token},
        )
        assert r.status_code == 401

    def test_wildcard_token_covers_all(self, flask_client, sample_xlsx_path):
        _upload(flask_client, sample_xlsx_path)
        r = flask_client.post(
            "/api/projects/default/public-tokens",
            json={"name": "admin", "scope": ["*"]},
        )
        assert r.status_code == 200
        tok = r.get_json()["token"]
        # Truy cập nhiều chart_id khác nhau
        for cid in ["module-overview", "phase-matrix", "priority", "overdue"]:
            r = flask_client.get(
                f"/public/api/v1/projects/default/charts/{cid}",
                headers={"X-API-Key": tok},
            )
            assert r.status_code == 200, f"Chart {cid} failed"
