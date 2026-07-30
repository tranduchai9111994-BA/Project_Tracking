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


# =========================================================================
# T30-extra: Auth methods bearer_token / basic_auth / api_key
# =========================================================================

@pytest.fixture
def env_bearer(monkeypatch):
    monkeypatch.setenv("FIS_API_TOKEN", "test-token-123")
    yield


@pytest.fixture
def env_apikey(monkeypatch):
    monkeypatch.setenv("FIS_API_KEY", "sk-abc-999")
    yield


def test_capabilities_all_first_class(project_dir):
    """5 auth methods + 3 response types (excel/json/database) đều supported=True."""
    caps = integ_mod.integration_capabilities()
    supported_auth = {m["value"] for m in caps["auth_methods"] if m["supported"]}
    # T31: thêm "database" method vào danh sách supported.
    assert supported_auth == {"form_login", "basic_auth", "bearer_token", "api_key", "database"}
    supported_resp = {r["value"] for r in caps["response_types"] if r["supported"]}
    assert "excel" in supported_resp
    assert "json" in supported_resp
    assert "database" in supported_resp
    # csv vẫn planned
    unsupported_resp = {r["value"] for r in caps["response_types"] if not r["supported"]}
    assert "csv" in unsupported_resp
    # auth_method_fields metadata cho FE dynamic render — bao gồm cả 'database'.
    assert set(caps["auth_method_fields"].keys()) == supported_auth
    assert caps["auth_method_fields"]["bearer_token"]["env_vars"] == ["<PREFIX>_TOKEN"]
    assert caps["auth_method_fields"]["api_key"]["env_vars"] == ["<PREFIX>_KEY"]
    assert caps["auth_method_fields"]["database"]["env_vars"] == ["<PREFIX>_USERNAME", "<PREFIX>_PASSWORD"]
    # apikey_locations expose để FE render dropdown
    assert set(caps["apikey_locations"]) == {"header", "query"}
    # T31: db_drivers metadata
    assert {d["value"] for d in caps["db_drivers"]} == {"sqlserver", "postgres", "mysql"}


def test_resolve_bearer_token(env_bearer):
    assert integ_mod.resolve_bearer_token("FIS_API") == "test-token-123"


def test_resolve_bearer_missing(monkeypatch):
    monkeypatch.delenv("NOSUCH_TOKEN", raising=False)
    with pytest.raises(ValueError, match="NOSUCH_TOKEN"):
        integ_mod.resolve_bearer_token("NOSUCH")


def test_resolve_api_key(env_apikey):
    assert integ_mod.resolve_api_key("FIS_API") == "sk-abc-999"


def test_resolve_api_key_missing():
    with pytest.raises(ValueError, match="apikey_env"):
        integ_mod.resolve_api_key("")


def test_prepare_session_bearer(env_bearer):
    session, extra, info = integ_mod._prepare_authenticated_session(
        base_url="https://fis.example.com",
        auth={"method": "bearer_token", "bearer_env": "FIS_API"},
    )
    try:
        assert session.headers.get("Authorization") == "Bearer test-token-123"
        assert extra == {}
        assert info["method"] == "bearer_token"
    finally:
        session.close()


def test_prepare_session_apikey_header(env_apikey):
    session, extra, _info = integ_mod._prepare_authenticated_session(
        base_url="https://fis.example.com",
        auth={"method": "api_key", "apikey_env": "FIS_API",
              "apikey_header": "X-API-Token", "apikey_location": "header"},
    )
    try:
        assert session.headers.get("X-API-Token") == "sk-abc-999"
        assert extra == {}
    finally:
        session.close()


def test_prepare_session_apikey_query(env_apikey):
    session, extra, _info = integ_mod._prepare_authenticated_session(
        base_url="https://fis.example.com",
        auth={"method": "api_key", "apikey_env": "FIS_API",
              "apikey_header": "api_key", "apikey_location": "query"},
    )
    try:
        # Header không bị set
        assert "api_key" not in session.headers
        # Extra query merge vào params khi fetch
        assert extra == {"api_key": "sk-abc-999"}
    finally:
        session.close()


def test_prepare_session_basic_auth(env_creds):
    session, extra, _info = integ_mod._prepare_authenticated_session(
        base_url="https://fis.example.com",
        auth={"method": "basic_auth", "credential_env": "IHRP_TEST"},
    )
    try:
        # Base64('abc:xyz') = YWJjOnh5eg==
        assert session.headers.get("Authorization") == "Basic YWJjOnh5eg=="
        assert extra == {}
    finally:
        session.close()


def test_bearer_sync_headers_sent(project_dir, env_bearer):
    """Verify bearer token thực sự đi kèm mỗi request tới endpoint."""
    integ = integ_mod.create_integration(project_dir, {
        "name": "FIS API",
        "base_url": "https://fis.example.com",
        "auth": {"method": "bearer_token", "bearer_env": "FIS_API"},
        "endpoints": [{
            "name": "Functions",
            "path": "/v1/functions",
            "response_type": "json",
            "data_path": "data",
            "field_mapping": {"Mã CN": "code"},
        }],
    })
    endpoint_id = integ["endpoints"][0]["id"]

    from app import _project_mgr
    with requests_mock.Mocker() as m:
        m.get("https://fis.example.com/v1/functions",
              json={"data": [{"code": "F001"}]},
              headers={"Content-Type": "application/json"})
        _res = integ_mod.sync_integration(
            project_dir=project_dir,
            integration_id=integ["id"],
            endpoint_id=endpoint_id,
            project_manager=_project_mgr,
            project_slug="default",
        )
        # 1 request duy nhất, mang Authorization: Bearer <token>
        assert len(m.request_history) == 1
        req = m.request_history[0]
        assert req.headers.get("Authorization") == "Bearer test-token-123"


def test_apikey_query_appended_to_url(project_dir, env_apikey):
    """api_key location=query → phải append vào query string endpoint."""
    integ = integ_mod.create_integration(project_dir, {
        "name": "Q",
        "base_url": "https://api.example.com",
        "auth": {"method": "api_key", "apikey_env": "FIS_API",
                 "apikey_header": "api_key", "apikey_location": "query"},
        "endpoints": [{
            "name": "List",
            "path": "/list",
            "response_type": "json",
            "data_path": "",
            "field_mapping": {"Mã CN": "code"},
            "params": {"module": "HR"},
        }],
    })
    endpoint_id = integ["endpoints"][0]["id"]
    from app import _project_mgr
    with requests_mock.Mocker() as m:
        m.get("https://api.example.com/list",
              json=[{"code": "F001"}],
              headers={"Content-Type": "application/json"})
        integ_mod.sync_integration(
            project_dir=project_dir,
            integration_id=integ["id"],
            endpoint_id=endpoint_id,
            project_manager=_project_mgr,
            project_slug="default",
        )
        req = m.request_history[0]
        assert "api_key=sk-abc-999" in req.url
        # Params gốc vẫn giữ
        assert "module=HR" in req.url


# =========================================================================
# JSON response mapping — unit test cho _dig_json / extract_records / build_xlsx
# =========================================================================

def test_dig_json_dot_notation():
    obj = {"data": {"items": [{"code": "F001", "phases": {"analysis": {"status": "Closed"}}}]}}
    assert integ_mod._dig_json(obj, "data.items.0.code") == "F001"
    assert integ_mod._dig_json(obj, "data.items.0.phases.analysis.status") == "Closed"
    # Không tồn tại → None
    assert integ_mod._dig_json(obj, "data.items.5.code") is None
    assert integ_mod._dig_json(obj, "data.items.0.nonexistent") is None
    # Path rỗng → identity
    assert integ_mod._dig_json(obj, "") is obj


def test_extract_records_root_list():
    """Payload là array top-level → data_path='' để trích trực tiếp."""
    payload = [{"a": 1}, {"a": 2}]
    assert integ_mod.extract_records(payload, "") == [{"a": 1}, {"a": 2}]


def test_extract_records_nested():
    payload = {"data": {"items": [{"code": "F1"}, {"code": "F2"}]}}
    assert integ_mod.extract_records(payload, "data.items") == [{"code": "F1"}, {"code": "F2"}]


def test_extract_records_not_list():
    payload = {"data": "not a list"}
    assert integ_mod.extract_records(payload, "data") == []


def test_build_xlsx_from_json_records(tmp_path):
    """Build xlsx từ 3 records với field mapping — verify parser đọc lại đúng."""
    records = [
        {"code": "F001", "name": "Chức năng 1", "module": "TMS", "priority": "Must-have",
         "phases": {"analysis": {"start": "2026-01-01", "end": "2026-01-05",
                                  "status": "Closed", "pic": "SonHN6"}}},
        {"code": "F002", "name": "Chức năng 2", "module": "HR", "priority": "Should-have",
         "phases": {"analysis": {"start": "2026-02-01", "end": None,
                                  "status": "In-progress", "pic": "PhatTPT3"}}},
    ]
    mapping = {
        "Mã CN": "code",
        "Tên chức năng": "name",
        "Module": "module",
        "Priority": "priority",
        "Analysis - Start": "phases.analysis.start",
        "Analysis - End": "phases.analysis.end",
        "Analysis - Status": "phases.analysis.status",
        "Analysis - PIC": "phases.analysis.pic",
    }
    xlsx_bytes = integ_mod.build_xlsx_from_json_records(records, mapping)
    # Ghi ra file rồi parse lại bằng parser thật
    p = tmp_path / "out.xlsx"
    p.write_bytes(xlsx_bytes)
    from parser.excel_parser import FunctionListParser
    parsed = FunctionListParser().parse(str(p))
    assert len(parsed.rows) == 2
    # Auto-detect phase Analysis
    assert "Analysis" in parsed.all_phases
    # Row 1 verify meta + phase status
    r1 = parsed.rows[0]
    assert r1.meta["ma_cn"] == "F001"
    assert r1.meta["module"] == "TMS"
    assert r1.phases["Analysis"].status == "Closed"
    assert "SonHN6" in r1.phases["Analysis"].pics


def test_build_xlsx_skips_empty_mapping():
    """field_mapping với value rỗng phải skip cột đó."""
    records = [{"a": 1, "b": 2}]
    xlsx = integ_mod.build_xlsx_from_json_records(records, {"A": "a", "SkipMe": "", "B": "b"})
    import openpyxl, io
    wb = openpyxl.load_workbook(io.BytesIO(xlsx))
    ws = wb.active
    headers = [c.value for c in ws[1]]
    assert headers == ["A", "B"]  # SkipMe không có


# =========================================================================
# E2E sync — Bearer + JSON API (mô phỏng REST API của team FIS)
# =========================================================================

def test_e2e_sync_bearer_json_api(flask_client, env_bearer):
    """
    Kịch bản chính: user config Bearer token + JSON API → mock endpoint trả 5
    record với structure {data: {items: [{...phases nested...}]}} → sync →
    verify snapshot có 5 dòng đúng cột map.
    """
    # 1) Tạo integration qua API
    r = flask_client.post(
        "/api/projects/default/integrations",
        json={
            "name": "FIS REST API",
            "base_url": "https://fis-api.company.com",
            "auth": {"method": "bearer_token", "bearer_env": "FIS_API"},
            "endpoints": [{
                "name": "Functions Export",
                "path": "/v1/projects/ihrp/functions",
                "http_method": "GET",
                "response_type": "json",
                "data_path": "data.items",
                "field_mapping": {
                    "Mã CN": "code",
                    "Tên chức năng": "name",
                    "Module": "module_code",
                    "Priority": "priority",
                    "FIT/GAP": "fit_gap",
                    "Analysis - Start": "phases.analysis.start",
                    "Analysis - End": "phases.analysis.end",
                    "Analysis - Status": "phases.analysis.status",
                    "Analysis - PIC": "phases.analysis.pic",
                    "Dev - Start": "phases.dev.start",
                    "Dev - End": "phases.dev.end",
                    "Dev - Status": "phases.dev.status",
                    "Dev - PIC": "phases.dev.pic",
                },
                "target_action": "snapshot",
            }],
        },
    )
    assert r.status_code == 201
    integ = r.get_json()["integration"]
    endpoint_id = integ["endpoints"][0]["id"]

    # 2) Mock 5 records
    fake_payload = {
        "data": {
            "items": [
                {
                    "code": f"FIS.FR.{i:02d}",
                    "name": f"Chức năng test {i}",
                    "module_code": ("TMS" if i % 2 == 0 else "HR"),
                    "priority": "Must-have",
                    "fit_gap": "FIT",
                    "phases": {
                        "analysis": {
                            "start": "2026-01-01",
                            "end": "2026-01-10",
                            "status": "Closed",
                            "pic": "SonHN6",
                        },
                        "dev": {
                            "start": "2026-01-11",
                            "end": None,
                            "status": ("In-progress" if i == 0 else "Assigned"),
                            "pic": "PhatTPT3",
                        },
                    },
                }
                for i in range(5)
            ]
        }
    }

    with requests_mock.Mocker() as m:
        m.get(
            "https://fis-api.company.com/v1/projects/ihrp/functions",
            json=fake_payload,
            headers={"Content-Type": "application/json"},
        )
        r_sync = flask_client.post(
            f"/api/projects/default/integrations/{integ['id']}/sync",
            json={"endpoint_id": endpoint_id},
        )
        # Verify Authorization header đã đi kèm request
        req = m.request_history[0]
        assert req.headers.get("Authorization") == "Bearer test-token-123"

    body = r_sync.get_json()
    assert body["status"] == "ok", body
    assert body["rows_imported"] == 5
    assert body["response_type"] == "json"
    assert body["snapshot_id"], "snapshot phải được tạo"

    # 3) Verify snapshot content — mở lại pkl / xlsx qua parser
    from app import _project_mgr
    smgr = _project_mgr.get_snapshot_manager("default")
    snaps = smgr.list_snapshots()
    assert snaps[0]["total_functions"] == 5
    loaded = smgr.load_snapshot(snaps[0]["date"])
    parsed = loaded["parsed"]
    assert len(parsed.rows) == 5
    # Verify field_mapping đã convert đúng: mã CN + module + phase
    ma_cns = {r.meta["ma_cn"] for r in parsed.rows}
    assert ma_cns == {"FIS.FR.00", "FIS.FR.01", "FIS.FR.02", "FIS.FR.03", "FIS.FR.04"}
    modules = {r.meta["module"] for r in parsed.rows}
    assert modules == {"TMS", "HR"}
    # Phase auto-detect từ header "Analysis - Start" etc.
    assert "Analysis" in parsed.all_phases
    assert "Dev" in parsed.all_phases
    # Verify status + PIC
    r0 = next(r for r in parsed.rows if r.meta["ma_cn"] == "FIS.FR.00")
    assert r0.phases["Analysis"].status == "Closed"
    assert "SonHN6" in r0.phases["Analysis"].pics
    assert r0.phases["Dev"].status == "In-progress"


def test_json_sync_missing_field_mapping_errors(flask_client, env_bearer):
    """response_type=json nhưng không config mapping → error rõ ràng."""
    r = flask_client.post(
        "/api/projects/default/integrations",
        json={
            "name": "X",
            "base_url": "https://x.example.com",
            "auth": {"method": "bearer_token", "bearer_env": "FIS_API"},
            "endpoints": [{
                "name": "E",
                "path": "/e",
                "response_type": "json",
                # KHÔNG có field_mapping
            }],
        },
    )
    integ = r.get_json()["integration"]
    endpoint_id = integ["endpoints"][0]["id"]
    with requests_mock.Mocker() as m:
        m.get("https://x.example.com/e",
              json=[{"a": 1}], headers={"Content-Type": "application/json"})
        r2 = flask_client.post(
            f"/api/projects/default/integrations/{integ['id']}/sync",
            json={"endpoint_id": endpoint_id},
        )
    body = r2.get_json()
    assert body["status"] == "error"
    assert "field_mapping" in body["message"]


def test_json_sync_wrong_data_path_errors(flask_client, env_bearer):
    """data_path sai → không trích được record → error rõ ràng."""
    r = flask_client.post(
        "/api/projects/default/integrations",
        json={
            "name": "X",
            "base_url": "https://x.example.com",
            "auth": {"method": "bearer_token", "bearer_env": "FIS_API"},
            "endpoints": [{
                "name": "E",
                "path": "/e",
                "response_type": "json",
                "data_path": "wrong.path",
                "field_mapping": {"Mã CN": "code"},
            }],
        },
    )
    integ = r.get_json()["integration"]
    endpoint_id = integ["endpoints"][0]["id"]
    with requests_mock.Mocker() as m:
        m.get("https://x.example.com/e",
              json={"data": [{"code": "F1"}]},
              headers={"Content-Type": "application/json"})
        r2 = flask_client.post(
            f"/api/projects/default/integrations/{integ['id']}/sync",
            json={"endpoint_id": endpoint_id},
        )
    body = r2.get_json()
    assert body["status"] == "error"
    assert "data_path" in body["message"] or "record nào" in body["message"]


# =========================================================================
# Preview endpoint — auto-suggest field_mapping
# =========================================================================

def test_preview_json_endpoint_returns_flat_keys(flask_client, env_bearer):
    r = flask_client.post(
        "/api/projects/default/integrations",
        json={
            "name": "P",
            "base_url": "https://p.example.com",
            "auth": {"method": "bearer_token", "bearer_env": "FIS_API"},
            "endpoints": [{
                "name": "E",
                "path": "/e",
                "response_type": "json",
                "data_path": "data",
                "field_mapping": {},
            }],
        },
    )
    integ = r.get_json()["integration"]
    endpoint_id = integ["endpoints"][0]["id"]
    with requests_mock.Mocker() as m:
        m.get("https://p.example.com/e",
              json={"data": [{"code": "F1", "name": "N", "phases": {"analysis": {"status": "Closed"}}}]},
              headers={"Content-Type": "application/json"})
        r2 = flask_client.post(
            f"/api/projects/default/integrations/{integ['id']}/preview-json",
            json={"endpoint_id": endpoint_id},
        )
    body = r2.get_json()
    assert body["status"] == "ok"
    assert body["record_count"] == 1
    # flat_keys nên có "code", "name", "phases.analysis.status"
    keys = set(body["flat_keys"].keys())
    assert "code" in keys
    assert "name" in keys
    assert "phases.analysis.status" in keys


# =========================================================================
# Backward compat — old integrations chỉ có credential_env vẫn hoạt động
# =========================================================================

def test_backward_compat_old_form_login_config(project_dir, env_creds):
    """
    Entry cũ chỉ có auth={method:form_login, credential_env:X} (không có
    bearer_env / apikey_env) vẫn sync được.
    """
    integ = integ_mod.create_integration(project_dir, {
        "name": "Legacy",
        "base_url": "https://legacy.example.com",
        "auth": {"method": "form_login", "credential_env": "IHRP_TEST"},
        "endpoints": [{
            "name": "E", "path": "/e", "response_type": "excel",
        }],
    })
    assert integ["auth"]["method"] == "form_login"
    # sanitize đã tự thêm default cho các field mới với giá trị rỗng — backward safe
    assert integ["auth"]["bearer_env"] == ""
    assert integ["auth"]["apikey_env"] == ""
    assert integ["auth"]["apikey_location"] == "header"
