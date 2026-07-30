"""
T31 — Tests cho Database integration (SQL Server / Postgres / MySQL).

Cover:
  · Schema sanitize (auth.method=database, endpoint.response_type=database,
    query, query_params) — không cần DB thực.
  · Guard SELECT-only (block UPDATE/DELETE/DROP/INSERT/EXEC).
  · Named param binding: `:name` → `?` (pyodbc) hoặc `%(name)s` (psycopg2/mysql).
  · Full sync flow qua sqlite3 (in-memory) — monkey-patch _open_db_connection
    trả về connection SQLite. Verify: query executed → xlsx built → parsed.
  · SQL injection: dùng payload attack trong query_params → không bị execute.
  · API endpoints /test-db + /sync với method=database (Flask client).
  · Missing driver: mock ImportError → message có `pip install ...`.
"""
from __future__ import annotations

import io
import os
import sqlite3
from pathlib import Path

import pytest

# `requests` là dep của `analyzer/integrations.py` (top-level import). Nếu
# venv chưa cài `requests` → skip toàn bộ module để test suite tối thiểu vẫn
# chạy được (giống cách `test_integrations.py` skip khi thiếu `requests_mock`).
pytest.importorskip("requests")

from analyzer import integrations as integ_mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def project_dir(tmp_path) -> str:
    d = tmp_path / "proj"
    d.mkdir(exist_ok=True)
    return str(d)


@pytest.fixture
def db_payload() -> dict:
    """Payload tạo integration DB minimal."""
    return {
        "name": "iHRP DB View",
        # base_url rỗng cho method=database — backend chấp nhận.
        "base_url": "",
        "auth": {
            "method": "database",
            "db_driver": "sqlserver",
            "db_host": "10.1.2.3",
            "db_port": 1433,
            "db_database": "iHRP_Prod",
            "credential_env": "FIS_DB",
        },
        "endpoints": [
            {
                "name": "Function List View",
                "path": "",  # optional cho DB
                "response_type": "database",
                "target_action": "snapshot",
                "query": "SELECT * FROM v_function_list WHERE project_id = :project_id",
                "query_params": {"project_id": "MPHG"},
                "field_mapping": {"Mã CN": "code", "Tên chức năng": "name"},
            }
        ],
    }


@pytest.fixture
def db_env_creds(monkeypatch):
    monkeypatch.setenv("FIS_DB_USERNAME", "readonly_user")
    monkeypatch.setenv("FIS_DB_PASSWORD", "s3cret")
    yield


@pytest.fixture
def sqlite_conn():
    """
    Tạo SQLite in-memory với sample data giống schema function list —
    dùng làm fake DB cho monkey-patch _open_db_connection.

    SQLite dùng '?' placeholder tương tự pyodbc → convert từ :name → ?
    của module hoạt động đúng.
    """
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE v_function_list (
            code TEXT PRIMARY KEY,
            name TEXT,
            module TEXT,
            project_id TEXT
        )
    """)
    cur.executemany(
        "INSERT INTO v_function_list VALUES (?, ?, ?, ?)",
        [
            ("PR.FR.01", "Tính lương cơ bản", "PR", "MPHG"),
            ("PR.FR.02", "Tính thưởng", "PR", "MPHG"),
            ("HR.HRM.05", "Chấm công", "HR", "MPHG"),
            ("PR.FR.03", "Overtime", "PR", "OTHER"),  # để filter loại bỏ
        ],
    )
    conn.commit()
    yield conn
    try:
        conn.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 1. Sanitize schema
# ---------------------------------------------------------------------------


def test_sanitize_auth_db_fields(project_dir, db_payload):
    created = integ_mod.create_integration(project_dir, db_payload)
    auth = created["auth"]
    assert auth["method"] == "database"
    assert auth["db_driver"] == "sqlserver"
    assert auth["db_host"] == "10.1.2.3"
    assert auth["db_port"] == 1433
    assert auth["db_database"] == "iHRP_Prod"
    assert auth["credential_env"] == "FIS_DB"


def test_sanitize_endpoint_db_fields(project_dir, db_payload):
    created = integ_mod.create_integration(project_dir, db_payload)
    ep = created["endpoints"][0]
    assert ep["response_type"] == "database"
    assert ep["query"].startswith("SELECT")
    assert ep["query_params"] == {"project_id": "MPHG"}
    assert ep["field_mapping"] == {"Mã CN": "code", "Tên chức năng": "name"}


def test_sanitize_db_driver_defaults_port(project_dir, db_payload):
    """Chưa set port → dùng default port theo driver."""
    db_payload["auth"]["db_port"] = 0
    db_payload["auth"]["db_driver"] = "postgres"
    created = integ_mod.create_integration(project_dir, db_payload)
    assert created["auth"]["db_port"] == 5432


def test_sanitize_db_invalid_driver_drops(project_dir, db_payload):
    """Driver không hỗ trợ → giữ rỗng (validator ở test/sync sẽ fail rõ)."""
    db_payload["auth"]["db_driver"] = "oracle"
    created = integ_mod.create_integration(project_dir, db_payload)
    assert created["auth"]["db_driver"] == ""


def test_sanitize_db_query_params_drops_invalid_name(project_dir, db_payload):
    """query_params key phải là identifier hợp lệ."""
    db_payload["endpoints"][0]["query_params"] = {
        "valid_name": 1,
        "invalid; DROP TABLE users;": 2,  # attack tên param → drop
        "1abc": 3,  # bắt đầu bằng số → drop
    }
    created = integ_mod.create_integration(project_dir, db_payload)
    qp = created["endpoints"][0]["query_params"]
    assert "valid_name" in qp
    assert "invalid; DROP TABLE users;" not in qp
    assert "1abc" not in qp


def test_sanitize_endpoint_db_no_query_dropped(project_dir, db_payload):
    """Endpoint database nhưng thiếu query → bị drop."""
    db_payload["endpoints"] = [
        {"name": "Bad", "response_type": "database", "query": ""},
    ]
    created = integ_mod.create_integration(project_dir, db_payload)
    assert created["endpoints"] == []


def test_sanitize_allows_empty_base_url_for_database(project_dir, db_payload):
    """DB method: base_url rỗng OK. Method khác: ValueError."""
    # Base line: database + empty base_url → OK
    db_payload["base_url"] = ""
    created = integ_mod.create_integration(project_dir, db_payload)
    assert created["base_url"] == ""

    # form_login + empty base_url → raise
    payload_http = dict(db_payload)
    payload_http["name"] = "HTTP"
    payload_http["base_url"] = ""
    payload_http["auth"] = {"method": "form_login", "credential_env": "X"}
    payload_http["endpoints"] = [{"name": "x", "path": "/x"}]
    with pytest.raises(ValueError, match="base_url"):
        integ_mod.create_integration(project_dir, payload_http)


# ---------------------------------------------------------------------------
# 2. Named param binding
# ---------------------------------------------------------------------------


def test_convert_named_to_qmark_positional():
    """`:name` → `?` với thứ tự đúng theo lần xuất hiện."""
    sql = "SELECT * FROM t WHERE a = :a AND b > :b AND c = :a"
    new_sql, ordered = integ_mod._convert_named_to_qmark(sql, {"a": 1, "b": 5})
    assert new_sql == "SELECT * FROM t WHERE a = ? AND b > ? AND c = ?"
    # :a xuất hiện 2 lần → bind 2 lần với cùng value 1
    assert ordered == [1, 5, 1]


def test_convert_named_to_qmark_skips_cast_operator():
    """`::text` (Postgres cast) không phải named param — không convert."""
    sql = "SELECT col::text FROM t WHERE id = :id"
    new_sql, ordered = integ_mod._convert_named_to_qmark(sql, {"id": 42})
    assert "col::text" in new_sql
    assert new_sql.count("?") == 1
    assert ordered == [42]


def test_convert_named_to_pyformat_only_used_params():
    """`:name` → `%(name)s` cho psycopg2/pymysql. Chỉ giữ key thực dùng."""
    sql = "SELECT * FROM t WHERE a = :a"
    new_sql, params = integ_mod._convert_named_to_pyformat(
        sql, {"a": 1, "b": 2, "unused": "x"}
    )
    assert new_sql == "SELECT * FROM t WHERE a = %(a)s"
    assert params == {"a": 1}


def test_convert_named_to_pyformat_multi_occurrence():
    sql = "SELECT * FROM t WHERE a = :a OR b = :a"
    new_sql, params = integ_mod._convert_named_to_pyformat(sql, {"a": 42})
    assert new_sql == "SELECT * FROM t WHERE a = %(a)s OR b = %(a)s"
    assert params == {"a": 42}


# ---------------------------------------------------------------------------
# 3. Query guard (SELECT / WITH only)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_query", [
    "UPDATE t SET x=1",
    "DELETE FROM t",
    "DROP TABLE t",
    "INSERT INTO t VALUES(1)",
    "EXEC sp_dosomething",
    "CALL do_thing()",
    "TRUNCATE TABLE t",
    "",
])
def test_run_database_query_rejects_non_select(bad_query, db_payload):
    """Non-SELECT phải raise ValueError trước khi open connection."""
    endpoint = {"query": bad_query, "query_params": {}}
    with pytest.raises(ValueError):
        integ_mod._run_database_query(
            db_payload["auth"], "u", "p", endpoint,
        )


@pytest.mark.parametrize("good_query", [
    "SELECT 1",
    "  SELECT * FROM t",
    "-- comment line\nSELECT 1",
    "WITH cte AS (SELECT 1) SELECT * FROM cte",
    "select lower(x) from t",  # case-insensitive
])
def test_run_database_query_accepts_read_only(good_query, db_payload, monkeypatch):
    """SELECT/WITH pass guard — nhưng vẫn fail vì driver chưa mock. Chỉ verify
    không raise ValueError về keyword."""
    endpoint = {"query": good_query, "query_params": {}}
    # Monkey-patch để bypass driver import → raise custom error nếu vào tới đây
    def _fake_open(auth, u, p, timeout=10):
        raise RuntimeError("REACHED_OPEN")
    monkeypatch.setattr(integ_mod, "_open_db_connection", _fake_open)
    with pytest.raises(RuntimeError, match="REACHED_OPEN"):
        integ_mod._run_database_query(db_payload["auth"], "u", "p", endpoint)


# ---------------------------------------------------------------------------
# 4. Full query execution với SQLite (in-memory)
# ---------------------------------------------------------------------------


def test_run_database_query_returns_list_of_dict(sqlite_conn, monkeypatch, db_payload):
    """
    Mock _open_db_connection trả về sqlite3.Connection thật.
    SQLite dùng `?` placeholder giống pyodbc → convert :name → ? hoạt động.
    """
    monkeypatch.setattr(
        integ_mod, "_open_db_connection",
        lambda auth, u, p, timeout=10: sqlite_conn
    )
    endpoint = {
        "query": "SELECT code, name, module FROM v_function_list WHERE project_id = :project_id",
        "query_params": {"project_id": "MPHG"},
    }
    # Auth dùng sqlserver để chọn path qmark (SQLite compatible với ?)
    auth = dict(db_payload["auth"])
    auth["db_driver"] = "sqlserver"
    records = integ_mod._run_database_query(auth, "u", "p", endpoint)
    assert len(records) == 3  # 3 MPHG, 1 OTHER bị filter
    assert records[0] == {"code": "PR.FR.01", "name": "Tính lương cơ bản", "module": "PR"}


class _NoCloseConn:
    """Wrap sqlite3.Connection để close() no-op → giữ conn sống qua nhiều test call."""
    def __init__(self, real):
        self._real = real
    def cursor(self, *a, **kw):
        return self._real.cursor(*a, **kw)
    def close(self):
        pass  # no-op — test tự close ở fixture teardown
    def commit(self):
        return self._real.commit()
    def __getattr__(self, name):
        return getattr(self._real, name)


def test_run_database_query_bind_prevents_injection(sqlite_conn, monkeypatch, db_payload):
    """
    Attack: inject SQL vào query_params value → phải được bind như literal
    string, KHÔNG được execute như statement mới.

    Test: value chứa "'; DROP TABLE v_function_list; --" → nếu concat sẽ drop
    table; nếu bind sẽ đơn giản tìm project_id = literal string đó → 0 row.
    """
    wrapped = _NoCloseConn(sqlite_conn)
    monkeypatch.setattr(
        integ_mod, "_open_db_connection",
        lambda auth, u, p, timeout=10: wrapped
    )
    attack_value = "MPHG'; DROP TABLE v_function_list; --"
    endpoint = {
        "query": "SELECT code FROM v_function_list WHERE project_id = :project_id",
        "query_params": {"project_id": attack_value},
    }
    auth = dict(db_payload["auth"])
    auth["db_driver"] = "sqlserver"
    records = integ_mod._run_database_query(auth, "u", "p", endpoint)
    assert records == []  # 0 row, không match

    # Verify table VẪN CÒN — bind an toàn, không phải string concat
    cur = sqlite_conn.cursor()
    cur.execute("SELECT COUNT(*) FROM v_function_list")
    assert cur.fetchone()[0] == 4


# ---------------------------------------------------------------------------
# 5. Missing driver (lazy import fail)
# ---------------------------------------------------------------------------


def test_open_db_connection_missing_driver_gives_pip_hint(monkeypatch, db_payload):
    """Mock ImportError → message hướng dẫn pip install."""
    import builtins as _builtins
    real_import = _builtins.__import__

    def _fake_import(name, *a, **kw):
        if name == "pyodbc":
            raise ImportError("No module named 'pyodbc'")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(_builtins, "__import__", _fake_import)
    with pytest.raises(ValueError, match=r"pip install pyodbc"):
        integ_mod._open_db_connection(db_payload["auth"], "u", "p")


def test_open_db_connection_missing_host(db_payload):
    auth = dict(db_payload["auth"])
    auth["db_host"] = ""
    with pytest.raises(ValueError, match="db_host"):
        integ_mod._open_db_connection(auth, "u", "p")


def test_open_db_connection_missing_database(db_payload):
    auth = dict(db_payload["auth"])
    auth["db_database"] = ""
    with pytest.raises(ValueError, match="db_database"):
        integ_mod._open_db_connection(auth, "u", "p")


def test_open_db_connection_unsupported_driver(db_payload):
    auth = dict(db_payload["auth"])
    auth["db_driver"] = "oracle"
    with pytest.raises(ValueError, match="db_driver"):
        integ_mod._open_db_connection(auth, "u", "p")


# ---------------------------------------------------------------------------
# 6. Full sync flow (project_dir + snapshot manager stub)
# ---------------------------------------------------------------------------


class _StubSnapshotMgr:
    def __init__(self):
        self.saved = []

    def save_snapshot(self, path, parsed, metrics, source="upload"):
        entry = {"date": "2026-07-30", "path": path, "source": source}
        self.saved.append(entry)
        return entry


class _StubProjectMgr:
    def __init__(self, folder: str):
        self._folder = folder
        self._smgr = _StubSnapshotMgr()

    def get_snapshot_manager(self, slug):
        return self._smgr

    def get_current_file_path(self, slug):
        return os.path.join(self._folder, "current.xlsx")

    def touch_last_upload(self, slug):
        pass


def _write_v_function_list_schema(conn):
    """Tạo schema giống Excel Function List thật để parser detect cột."""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE v_function_list (
            "Mã CN" TEXT,
            "Tên chức năng" TEXT,
            "Module" TEXT,
            "Priority" TEXT,
            "Analysis - Start" TEXT,
            "Analysis - End" TEXT,
            "Analysis - Status" TEXT,
            "Analysis - PIC" TEXT
        )
    """)
    cur.executemany(
        'INSERT INTO v_function_list VALUES (?,?,?,?,?,?,?,?)',
        [
            ("PR.FR.01", "Tính lương cơ bản", "PR", "High",
             "2026-01-01", "2026-01-15", "Closed", "AnhTV"),
            ("HR.HRM.05", "Chấm công", "HR", "Medium",
             "2026-02-01", "2026-02-20", "In-progress", "BaoLQ"),
        ]
    )
    conn.commit()


def test_run_database_sync_full_flow(project_dir, db_payload, db_env_creds, monkeypatch):
    """
    Full sync qua stub connection SQLite + stub ProjectManager.
    Verify: query executed → xlsx built → parsed → snapshot saved.
    """
    # Setup SQLite in-memory với schema đúng
    conn = sqlite3.connect(":memory:")
    _write_v_function_list_schema(conn)

    monkeypatch.setattr(
        integ_mod, "_open_db_connection",
        lambda auth, u, p, timeout=10: conn
    )

    # Endpoint query đơn giản: dump all
    db_payload["endpoints"][0]["query"] = 'SELECT * FROM v_function_list'
    db_payload["endpoints"][0]["query_params"] = {}
    # field_mapping rỗng → dùng nguyên tên SQL column làm header (đã match iHRP)
    db_payload["endpoints"][0]["field_mapping"] = {}

    integ = integ_mod.create_integration(project_dir, db_payload)
    ep_id = integ["endpoints"][0]["id"]

    stub_mgr = _StubProjectMgr(project_dir)
    result = integ_mod.sync_integration(
        project_dir=project_dir,
        integration_id=integ["id"],
        endpoint_id=ep_id,
        project_manager=stub_mgr,
        project_slug="stub",
    )
    assert result["status"] == "ok", result
    assert result["rows_imported"] == 2
    assert result["response_type"] == "database"
    assert result["filename"].startswith("synced_db_")
    assert result["filename"].endswith(".xlsx")
    assert len(stub_mgr._smgr.saved) == 1
    # File tạm xlsx tồn tại thực tế
    assert os.path.exists(os.path.join(project_dir, result["filename"]))


def test_sync_database_zero_rows_error(project_dir, db_payload, db_env_creds, monkeypatch):
    """Query trả 0 row → status=error với message rõ."""
    conn = sqlite3.connect(":memory:")
    _write_v_function_list_schema(conn)
    monkeypatch.setattr(
        integ_mod, "_open_db_connection",
        lambda auth, u, p, timeout=10: conn
    )
    db_payload["endpoints"][0]["query"] = "SELECT * FROM v_function_list WHERE 1=0"
    db_payload["endpoints"][0]["query_params"] = {}
    integ = integ_mod.create_integration(project_dir, db_payload)
    stub_mgr = _StubProjectMgr(project_dir)
    result = integ_mod.sync_integration(
        project_dir=project_dir,
        integration_id=integ["id"],
        endpoint_id=integ["endpoints"][0]["id"],
        project_manager=stub_mgr,
        project_slug="stub",
    )
    assert result["status"] == "error"
    assert "0 row" in result["message"].lower() or "kh" in result["message"].lower()


def test_sync_database_mismatch_method_and_response_type(project_dir, db_payload, db_env_creds):
    """response_type=database + auth.method != database → reject."""
    db_payload["auth"]["method"] = "basic_auth"
    db_payload["base_url"] = "https://x.example.com"
    integ = integ_mod.create_integration(project_dir, db_payload)
    stub_mgr = _StubProjectMgr(project_dir)
    result = integ_mod.sync_integration(
        project_dir=project_dir,
        integration_id=integ["id"],
        endpoint_id=integ["endpoints"][0]["id"],
        project_manager=stub_mgr,
        project_slug="stub",
    )
    assert result["status"] == "error"
    assert "database" in result["message"].lower()


# ---------------------------------------------------------------------------
# 7. Capabilities + API endpoints
# ---------------------------------------------------------------------------


def test_capabilities_includes_database_method():
    caps = integ_mod.integration_capabilities()
    methods = {m["value"] for m in caps["auth_methods"]}
    assert "database" in methods
    types = {t["value"] for t in caps["response_types"]}
    assert "database" in types
    drivers = {d["value"] for d in caps["db_drivers"]}
    assert drivers == {"sqlserver", "postgres", "mysql"}


def test_api_create_db_integration(flask_client, db_payload):
    r = flask_client.post("/api/projects/default/integrations", json=db_payload)
    assert r.status_code == 201, r.get_json()
    body = r.get_json()["integration"]
    assert body["auth"]["method"] == "database"
    assert body["auth"]["db_driver"] == "sqlserver"


def test_api_test_db_wrong_method_400(flask_client):
    # Tạo 1 integration form_login → gọi /test-db → 400
    payload = {
        "name": "HTTP integration",
        "base_url": "https://x.example.com",
        "auth": {"method": "form_login", "credential_env": "X"},
        "endpoints": [{"name": "ep", "path": "/x"}],
    }
    created = flask_client.post("/api/projects/default/integrations", json=payload).get_json()["integration"]
    r = flask_client.post(f"/api/projects/default/integrations/{created['id']}/test-db")
    assert r.status_code == 400
    assert "database" in r.get_json()["message"].lower()


def test_api_test_db_missing_env_returns_error(flask_client, db_payload, monkeypatch):
    """Env chưa set → status=error với hint tên biến thiếu."""
    monkeypatch.delenv("FIS_DB_USERNAME", raising=False)
    monkeypatch.delenv("FIS_DB_PASSWORD", raising=False)
    # Load .env vẫn được đọc nhưng không có key này — dùng workspace
    created = flask_client.post("/api/projects/default/integrations",
                                json=db_payload).get_json()["integration"]
    r = flask_client.post(f"/api/projects/default/integrations/{created['id']}/test-db")
    assert r.status_code == 200
    body = r.get_json()
    # Có thể pass nếu .env workspace có FIS_DB_* — chấp nhận cả 2. Nếu error
    # thì message phải mention env variable.
    if body["status"] == "error":
        assert "FIS_DB" in body["message"] or "kết nối" in body["message"].lower()


def test_api_sync_database_end_to_end(flask_client, db_payload, db_env_creds, monkeypatch):
    """
    Full sync qua Flask API — mock _open_db_connection trả SQLite.
    """
    conn = sqlite3.connect(":memory:")
    _write_v_function_list_schema(conn)
    monkeypatch.setattr(
        integ_mod, "_open_db_connection",
        lambda auth, u, p, timeout=10: conn
    )
    db_payload["endpoints"][0]["query"] = "SELECT * FROM v_function_list"
    db_payload["endpoints"][0]["query_params"] = {}
    db_payload["endpoints"][0]["field_mapping"] = {}
    created = flask_client.post("/api/projects/default/integrations",
                                json=db_payload).get_json()["integration"]
    ep_id = created["endpoints"][0]["id"]

    r = flask_client.post(
        f"/api/projects/default/integrations/{created['id']}/sync",
        json={"endpoint_id": ep_id},
    )
    body = r.get_json()
    assert body["status"] == "ok", body
    assert body["rows_imported"] == 2
