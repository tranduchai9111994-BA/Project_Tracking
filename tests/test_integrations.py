"""
T30 — Tests cho Registry API + Đồng bộ dữ liệu.

Cover:
  · CRUD integration (create / list / get / update / delete)
  · resolve_credentials từ os.environ + parse .env
  · Sanitize input (base_url không hợp lệ, endpoint thiếu name/path…)
  · Mock full sync flow bằng `requests_mock` — dùng file sample_xlsx để giả
    lập response Excel từ server nguồn.
  · API endpoints qua flask_client.
"""
from __future__ import annotations

import io
import os
from pathlib import Path

import pytest

# requests_mock là dev dep — mark skip nếu không có (để CI vẫn chạy được với
# requirements.txt minimum).
requests_mock = pytest.importorskip("requests_mock")

from analyzer import integrations as integ_mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def project_dir(tmp_path) -> str:
    """Thư mục project trống — dùng cho unit test module."""
    d = tmp_path / "proj"
    d.mkdir(exist_ok=True)
    return str(d)


@pytest.fixture
def minimal_payload() -> dict:
    """Payload create integration hợp lệ tối thiểu."""
    return {
        "name": "iHRP Test",
        "base_url": "https://ihrp.example.com",
        "auth": {
            "method": "form_login",
            "login_path": "/login",
            "username_field": "username",
            "password_field": "password",
            "credential_env": "IHRP_TEST",
        },
        "endpoints": [
            {
                "name": "Function List Export",
                "path": "/api/functions/export",
                "http_method": "GET",
                "params": {"module": "all"},
                "response_type": "excel",
                "target_action": "snapshot",
            }
        ],
    }


@pytest.fixture
def env_creds(monkeypatch):
    """Set IHRP_TEST_USERNAME / IHRP_TEST_PASSWORD trong process env."""
    monkeypatch.setenv("IHRP_TEST_USERNAME", "abc")
    monkeypatch.setenv("IHRP_TEST_PASSWORD", "xyz")
    yield


# ---------------------------------------------------------------------------
# CRUD unit tests
# ---------------------------------------------------------------------------

def test_create_and_list(project_dir, minimal_payload):
    created = integ_mod.create_integration(project_dir, minimal_payload)
    assert created["id"].startswith("int_")
    assert created["name"] == "iHRP Test"
    assert created["base_url"] == "https://ihrp.example.com"
    assert len(created["endpoints"]) == 1
    assert created["endpoints"][0]["id"].startswith("ep_")

    listed = integ_mod.list_integrations(project_dir)
    assert len(listed) == 1
    assert listed[0]["id"] == created["id"]


def test_create_missing_name_raises(project_dir, minimal_payload):
    minimal_payload["name"] = ""
    with pytest.raises(ValueError):
        integ_mod.create_integration(project_dir, minimal_payload)


def test_create_invalid_base_url_raises(project_dir, minimal_payload):
    minimal_payload["base_url"] = "not-a-url"
    with pytest.raises(ValueError):
        integ_mod.create_integration(project_dir, minimal_payload)


def test_get_integration(project_dir, minimal_payload):
    created = integ_mod.create_integration(project_dir, minimal_payload)
    got = integ_mod.get_integration(project_dir, created["id"])
    assert got == created


def test_update_integration_merges_fields(project_dir, minimal_payload):
    created = integ_mod.create_integration(project_dir, minimal_payload)
    updated = integ_mod.update_integration(project_dir, created["id"], {"name": "Renamed"})
    assert updated is not None
    assert updated["name"] == "Renamed"
    # Endpoints giữ nguyên khi PUT không kèm 'endpoints'
    assert len(updated["endpoints"]) == 1
    # id + created_at giữ nguyên
    assert updated["id"] == created["id"]
    assert updated["created_at"] == created["created_at"]


def test_update_partial_auth(project_dir, minimal_payload):
    created = integ_mod.create_integration(project_dir, minimal_payload)
    updated = integ_mod.update_integration(project_dir, created["id"], {
        "auth": {"credential_env": "NEW_PREFIX"}
    })
    assert updated["auth"]["credential_env"] == "NEW_PREFIX"
    # Field khác của auth vẫn giữ (login_path, method…)
    assert updated["auth"]["login_path"] == "/login"


def test_delete_integration(project_dir, minimal_payload):
    created = integ_mod.create_integration(project_dir, minimal_payload)
    assert integ_mod.delete_integration(project_dir, created["id"]) is True
    assert integ_mod.list_integrations(project_dir) == []


def test_delete_nonexistent(project_dir):
    assert integ_mod.delete_integration(project_dir, "no-such-id") is False


def test_endpoint_missing_path_dropped(project_dir):
    payload = {
        "name": "T",
        "base_url": "https://x.example.com",
        "auth": {"credential_env": "T"},
        "endpoints": [
            {"name": "Valid", "path": "/x"},
            {"name": "No path"},   # phải bị drop
            {"path": "/y"},         # thiếu name → drop
        ],
    }
    created = integ_mod.create_integration(project_dir, payload)
    assert len(created["endpoints"]) == 1
    assert created["endpoints"][0]["name"] == "Valid"


# ---------------------------------------------------------------------------
# Credential resolution
# ---------------------------------------------------------------------------

def test_resolve_credentials_from_env(env_creds):
    user, pwd = integ_mod.resolve_credentials("IHRP_TEST")
    assert user == "abc"
    assert pwd == "xyz"


def test_resolve_credentials_missing_prefix():
    with pytest.raises(ValueError, match="credential_env"):
        integ_mod.resolve_credentials("")


def test_resolve_credentials_missing_env(monkeypatch):
    monkeypatch.delenv("NOSUCH_USERNAME", raising=False)
    monkeypatch.delenv("NOSUCH_PASSWORD", raising=False)
    with pytest.raises(ValueError, match="NOSUCH_USERNAME"):
        integ_mod.resolve_credentials("NOSUCH")


def test_resolve_credentials_reads_dotenv(tmp_path, monkeypatch):
    """Nếu env process chưa có → module đọc .env ở workspace root."""
    # Không set env process
    monkeypatch.delenv("FROMFILE_USERNAME", raising=False)
    monkeypatch.delenv("FROMFILE_PASSWORD", raising=False)
    # Đặt .env ở workspace root (parent của folder analyzer/)
    root = Path(integ_mod.__file__).resolve().parent.parent
    env_path = root / ".env"
    backup = env_path.read_text(encoding="utf-8") if env_path.exists() else None
    try:
        env_path.write_text(
            "FROMFILE_USERNAME=from_file_user\n"
            'FROMFILE_PASSWORD="from_file_pass"\n',
            encoding="utf-8",
        )
        user, pwd = integ_mod.resolve_credentials("FROMFILE")
        assert user == "from_file_user"
        assert pwd == "from_file_pass"
    finally:
        # Khôi phục .env — hoặc xóa nếu ban đầu không có
        if backup is None:
            try:
                env_path.unlink()
            except OSError:
                pass
        else:
            env_path.write_text(backup, encoding="utf-8")


# ---------------------------------------------------------------------------
# HTTP flows — mock
# ---------------------------------------------------------------------------

def test_test_integration_login_ok(project_dir, minimal_payload, env_creds):
    created = integ_mod.create_integration(project_dir, minimal_payload)
    with requests_mock.Mocker() as m:
        # GET login page trả HTML có CSRF
        m.get(
            "https://ihrp.example.com/login",
            text='<html><form><input name="csrf_token" value="abc123"></form></html>',
        )
        # POST login trả 200, redirect final URL sang /dashboard
        m.post(
            "https://ihrp.example.com/login",
            status_code=200,
            text="<html>Welcome!</html>",
            headers={"Location": "/dashboard"},
        )
        result = integ_mod.test_integration(project_dir, created["id"])
    assert result["status"] == "ok"

    # last_sync_status được cập nhật
    got = integ_mod.get_integration(project_dir, created["id"])
    assert got["last_sync_status"] == "ok"


def test_test_integration_login_fail(project_dir, minimal_payload, env_creds):
    created = integ_mod.create_integration(project_dir, minimal_payload)
    with requests_mock.Mocker() as m:
        m.get("https://ihrp.example.com/login", text="<html></html>")
        m.post("https://ihrp.example.com/login", status_code=401, text="Unauthorized")
        result = integ_mod.test_integration(project_dir, created["id"])
    assert result["status"] == "error"
    assert "401" in result["message"] or "sai" in result["message"].lower()


def test_test_integration_missing_creds(project_dir, minimal_payload, monkeypatch):
    """Không set env → phải fail early, không đụng HTTP."""
    monkeypatch.delenv("IHRP_TEST_USERNAME", raising=False)
    monkeypatch.delenv("IHRP_TEST_PASSWORD", raising=False)
    # Nếu .env ở root có set thì test này skip
    root = Path(integ_mod.__file__).resolve().parent.parent
    if (root / ".env").exists():
        content = (root / ".env").read_text(encoding="utf-8")
        if "IHRP_TEST_USERNAME" in content:
            pytest.skip("Real .env has IHRP_TEST — skip missing-creds test")
    created = integ_mod.create_integration(project_dir, minimal_payload)
    result = integ_mod.test_integration(project_dir, created["id"])
    assert result["status"] == "error"
    assert "IHRP_TEST_USERNAME" in result["message"]


# ---------------------------------------------------------------------------
# Full sync flow (E2E-ish) — mock login + download Excel
# ---------------------------------------------------------------------------

def test_sync_integration_full_flow(flask_client, sample_xlsx_path, env_creds):
    """
    Chạy sync end-to-end qua Flask app: create integration → mock HTTP
    responses → gọi API sync → verify snapshot mới xuất hiện.
    """
    from app import _project_mgr

    # 1) Tạo integration qua API (dùng project 'default' đã có sẵn từ fixture)
    create_r = flask_client.post(
        "/api/projects/default/integrations",
        json={
            "name": "iHRP Test",
            "base_url": "https://ihrp.example.com",
            "auth": {"credential_env": "IHRP_TEST"},
            "endpoints": [{
                "name": "Function List Export",
                "path": "/api/functions/export",
                "http_method": "GET",
                "params": {"module": "all"},
                "response_type": "excel",
                "target_action": "snapshot",
            }],
        },
    )
    assert create_r.status_code == 201
    integ = create_r.get_json()["integration"]
    endpoint_id = integ["endpoints"][0]["id"]

    # Đọc sample xlsx thành bytes để mock server "trả" nội dung này
    with open(sample_xlsx_path, "rb") as f:
        excel_bytes = f.read()

    # 2) Mock HTTP + gọi API sync
    with requests_mock.Mocker() as m:
        m.get("https://ihrp.example.com/login", text="<html></html>")
        m.post("https://ihrp.example.com/login", text="OK", status_code=200)
        m.get(
            "https://ihrp.example.com/api/functions/export",
            content=excel_bytes,
            headers={"Content-Type":
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
        )
        sync_r = flask_client.post(
            f"/api/projects/default/integrations/{integ['id']}/sync",
            json={"endpoint_id": endpoint_id},
        )
    assert sync_r.status_code == 200
    body = sync_r.get_json()
    assert body["status"] == "ok", body
    assert body["rows_imported"] == 6  # sample có 6 dòng function
    assert body["snapshot_id"], "snapshot_id phải có value"

    # 3) Verify snapshot list có entry mới
    smgr = _project_mgr.get_snapshot_manager("default")
    snaps = smgr.list_snapshots()
    assert len(snaps) >= 1
    assert snaps[0]["total_functions"] == 6


def test_sync_response_not_excel_returns_error(flask_client, env_creds):
    """Server trả HTML thay vì xlsx → phải error rõ ràng, không crash."""
    create_r = flask_client.post(
        "/api/projects/default/integrations",
        json={
            "name": "T",
            "base_url": "https://x.example.com",
            "auth": {"credential_env": "IHRP_TEST"},
            "endpoints": [{
                "name": "E",
                "path": "/download",
                "response_type": "excel",
            }],
        },
    )
    integ = create_r.get_json()["integration"]
    endpoint_id = integ["endpoints"][0]["id"]

    with requests_mock.Mocker() as m:
        m.get("https://x.example.com/login", text="<html></html>")
        m.post("https://x.example.com/login", text="OK", status_code=200)
        m.get(
            "https://x.example.com/download",
            text="<html>Not an Excel</html>",
            headers={"Content-Type": "text/html"},
        )
        r = flask_client.post(
            f"/api/projects/default/integrations/{integ['id']}/sync",
            json={"endpoint_id": endpoint_id},
        )
    body = r.get_json()
    assert body["status"] == "error"
    assert "Excel" in body["message"] or "excel" in body["message"].lower()


# ---------------------------------------------------------------------------
# API layer smoke tests
# ---------------------------------------------------------------------------

def test_api_list_empty(flask_client):
    r = flask_client.get("/api/projects/default/integrations")
    assert r.status_code == 200
    body = r.get_json()
    assert body["integrations"] == []
    # Metadata capabilities cho FE
    assert body["capabilities"]["default_timeout_seconds"] > 0
    assert any(a["value"] == "form_login" and a["supported"]
               for a in body["capabilities"]["auth_methods"])


def test_api_crud_full_cycle(flask_client):
    # Create
    r = flask_client.post(
        "/api/projects/default/integrations",
        json={
            "name": "iHRP",
            "base_url": "https://x.example.com",
            "auth": {"credential_env": "IHRP_TEST"},
            "endpoints": [{"name": "E", "path": "/e"}],
        },
    )
    assert r.status_code == 201
    integ = r.get_json()["integration"]

    # Get
    r = flask_client.get(f"/api/projects/default/integrations/{integ['id']}")
    assert r.status_code == 200
    assert r.get_json()["integration"]["name"] == "iHRP"

    # Update
    r = flask_client.put(
        f"/api/projects/default/integrations/{integ['id']}",
        json={"name": "iHRP renamed"},
    )
    assert r.status_code == 200
    assert r.get_json()["integration"]["name"] == "iHRP renamed"

    # Delete
    r = flask_client.delete(f"/api/projects/default/integrations/{integ['id']}")
    assert r.status_code == 200

    # 404 sau khi delete
    r = flask_client.get(f"/api/projects/default/integrations/{integ['id']}")
    assert r.status_code == 404


def test_api_create_invalid_payload(flask_client):
    r = flask_client.post(
        "/api/projects/default/integrations",
        json={"name": "Missing base_url"},
    )
    assert r.status_code == 400


def test_api_sync_missing_endpoint_id(flask_client):
    r = flask_client.post(
        "/api/projects/default/integrations",
        json={
            "name": "T",
            "base_url": "https://x.example.com",
            "auth": {"credential_env": "X"},
            "endpoints": [{"name": "E", "path": "/e"}],
        },
    )
    integ = r.get_json()["integration"]
    r2 = flask_client.post(
        f"/api/projects/default/integrations/{integ['id']}/sync",
        json={},
    )
    assert r2.status_code == 400
