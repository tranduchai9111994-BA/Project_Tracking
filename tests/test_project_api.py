"""Tests HTTP integration cho Project API endpoints (V3)."""
import io
import os
import zipfile

import pytest


def _upload(client, xlsx_path, project="default"):
    with open(xlsx_path, "rb") as f:
        data = {"file": (io.BytesIO(f.read()), "test.xlsx")}
    return client.post(
        f"/api/projects/{project}/upload",
        data=data,
        content_type="multipart/form-data",
    )


# ==========================================================================
# CRUD Project
# ==========================================================================

def test_list_projects_has_default(flask_client):
    """GET /api/projects luôn có ít nhất project 'default' sau khởi động."""
    r = flask_client.get("/api/projects")
    assert r.status_code == 200
    data = r.get_json()
    slugs = {p["slug"] for p in data["projects"]}
    assert "default" in slugs


def test_create_project(flask_client):
    r = flask_client.post("/api/projects", json={"name": "Minh Phú 2026", "description": "Client A"})
    assert r.status_code == 201
    p = r.get_json()["project"]
    assert p["slug"] == "minh-phu-2026"
    assert p["name"] == "Minh Phú 2026"
    assert p["description"] == "Client A"


def test_create_project_empty_name_400(flask_client):
    r = flask_client.post("/api/projects", json={"name": ""})
    assert r.status_code == 400


def test_get_project(flask_client):
    r = flask_client.get("/api/projects/default")
    assert r.status_code == 200
    assert r.get_json()["project"]["slug"] == "default"


def test_get_project_missing_404(flask_client):
    r = flask_client.get("/api/projects/nonexistent")
    assert r.status_code == 404


def test_rename_project(flask_client):
    flask_client.post("/api/projects", json={"name": "Old"})
    r = flask_client.put("/api/projects/old", json={"name": "New Name", "description": "desc"})
    assert r.status_code == 200
    assert r.get_json()["project"]["name"] == "New Name"


def test_delete_project(flask_client):
    flask_client.post("/api/projects", json={"name": "Delme"})
    r = flask_client.delete("/api/projects/delme")
    assert r.status_code == 200
    r2 = flask_client.get("/api/projects/delme")
    assert r2.status_code == 404


def test_cannot_delete_default(flask_client):
    r = flask_client.delete("/api/projects/default")
    assert r.status_code == 400


def test_soft_delete_and_restore(flask_client):
    flask_client.post("/api/projects", json={"name": "Softy"})
    r = flask_client.delete("/api/projects/softy?soft=1")
    assert r.status_code == 200

    # Không hiện trong list mặc định
    active = {p["slug"] for p in flask_client.get("/api/projects").get_json()["projects"]}
    assert "softy" not in active

    # Nhưng hiện khi include_archived
    all_p = {p["slug"] for p in flask_client.get("/api/projects?include_archived=1").get_json()["projects"]}
    assert "softy" in all_p

    # Restore
    r = flask_client.post("/api/projects/softy/restore")
    assert r.status_code == 200
    active2 = {p["slug"] for p in flask_client.get("/api/projects").get_json()["projects"]}
    assert "softy" in active2


# ==========================================================================
# Upload & Dashboard per-project
# ==========================================================================

def test_upload_to_default_project(flask_client, sample_xlsx_path):
    r = _upload(flask_client, sample_xlsx_path, project="default")
    assert r.status_code == 200
    data = r.get_json()
    assert data["success"] is True
    assert data["project"]["slug"] == "default"
    assert data["rows_count"] == 6


def test_upload_to_new_project(flask_client, sample_xlsx_path):
    """Tạo project mới rồi upload vào."""
    flask_client.post("/api/projects", json={"name": "Client X"})
    r = _upload(flask_client, sample_xlsx_path, project="client-x")
    assert r.status_code == 200
    assert r.get_json()["project"]["slug"] == "client-x"


def test_upload_to_missing_project_404(flask_client, sample_xlsx_path):
    r = _upload(flask_client, sample_xlsx_path, project="nonexistent")
    assert r.status_code == 404


def test_project_dashboard(flask_client, sample_xlsx_path):
    _upload(flask_client, sample_xlsx_path, project="default")
    r = flask_client.get("/api/projects/default/dashboard")
    assert r.status_code == 200
    assert r.get_json()["metrics"]["summary"]["total_functions"] == 6


def test_isolated_state_between_projects(flask_client, sample_xlsx_path):
    """
    Upload vào 2 project khác nhau → mỗi project có state riêng.
    """
    flask_client.post("/api/projects", json={"name": "Alpha"})
    flask_client.post("/api/projects", json={"name": "Beta"})
    _upload(flask_client, sample_xlsx_path, project="alpha")
    # Beta chưa upload
    r = flask_client.get("/api/projects/beta/dashboard")
    assert r.status_code == 404  # NO_FILE

    r_alpha = flask_client.get("/api/projects/alpha/dashboard")
    assert r_alpha.status_code == 200


def test_last_upload_updated_after_upload(flask_client, sample_xlsx_path):
    _upload(flask_client, sample_xlsx_path, project="default")
    proj = flask_client.get("/api/projects/default").get_json()["project"]
    assert proj["last_upload_at"] is not None


# ==========================================================================
# Snapshot & Compare per-project
# ==========================================================================

def test_snapshots_scoped_to_project(flask_client, sample_xlsx_path):
    """Snapshot của project A không hiện trong project B."""
    flask_client.post("/api/projects", json={"name": "Alpha"})
    _upload(flask_client, sample_xlsx_path, project="alpha")
    _upload(flask_client, sample_xlsx_path, project="default")

    alpha_snaps = flask_client.get("/api/projects/alpha/snapshots").get_json()["snapshots"]
    default_snaps = flask_client.get("/api/projects/default/snapshots").get_json()["snapshots"]
    assert len(alpha_snaps) == 1
    assert len(default_snaps) == 1
    # Same filename pattern but files ở folder khác


def test_compare_cross_project(flask_client, sample_xlsx_path):
    """Compare snapshot giữa 2 project khác nhau."""
    flask_client.post("/api/projects", json={"name": "Alpha"})
    _upload(flask_client, sample_xlsx_path, project="alpha")
    _upload(flask_client, sample_xlsx_path, project="default")

    a_date = flask_client.get("/api/projects/alpha/snapshots").get_json()["snapshots"][0]["date"]
    d_date = flask_client.get("/api/projects/default/snapshots").get_json()["snapshots"][0]["date"]

    r = flask_client.get(
        f"/api/compare-cross?project_a=alpha&snap_a={a_date}&project_b=default&snap_b={d_date}"
    )
    assert r.status_code == 200
    body = r.get_json()
    assert "result" in body
    assert body["project_a"]["slug"] == "alpha"
    assert body["project_b"]["slug"] == "default"


def test_compare_cross_missing_snapshot_404(flask_client, sample_xlsx_path):
    _upload(flask_client, sample_xlsx_path, project="default")
    r = flask_client.get(
        "/api/compare-cross?project_a=default&snap_a=1999-01-01"
        "&project_b=default&snap_b=1999-01-02"
    )
    assert r.status_code == 404


# ==========================================================================
# Export/Import package
# ==========================================================================

def test_export_project_package(flask_client, sample_xlsx_path):
    _upload(flask_client, sample_xlsx_path, project="default")
    r = flask_client.get("/api/projects/default/export-package")
    assert r.status_code == 200
    assert r.headers["Content-Type"] == "application/zip"
    assert len(r.data) > 100

    # Verify zip content
    zf = zipfile.ZipFile(io.BytesIO(r.data))
    names = zf.namelist()
    assert any("meta.json" in n for n in names)
    assert any("current.xlsx" in n for n in names)


def test_import_project_package(flask_client, sample_xlsx_path):
    """Export → Import → project mới với data giống hệt."""
    _upload(flask_client, sample_xlsx_path, project="default")
    exported = flask_client.get("/api/projects/default/export-package").data

    # Import
    r = flask_client.post(
        "/api/projects/import-package",
        data={"file": (io.BytesIO(exported), "backup.zip")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 200
    new_slug = r.get_json()["project"]["slug"]
    # Slug được auto-generate vì "Default" đã tồn tại → "default-2"
    assert new_slug == "default-2"

    # Dashboard của project mới có metrics
    r2 = flask_client.get(f"/api/projects/{new_slug}/dashboard")
    assert r2.status_code == 200
    assert r2.get_json()["metrics"]["summary"]["total_functions"] == 6


def test_import_invalid_zip_400(flask_client):
    r = flask_client.post(
        "/api/projects/import-package",
        data={"file": (io.BytesIO(b"not a zip"), "bad.zip")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 400


# ==========================================================================
# Legacy endpoints vẫn hoạt động (backward compat)
# ==========================================================================

def test_legacy_upload_defaults_to_default_project(flask_client, sample_xlsx_path):
    """POST /api/upload không có project → dùng 'default'."""
    with open(sample_xlsx_path, "rb") as f:
        data = {"file": (io.BytesIO(f.read()), "test.xlsx")}
    r = flask_client.post("/api/upload", data=data, content_type="multipart/form-data")
    assert r.status_code == 200
    assert r.get_json()["project"]["slug"] == "default"


def test_legacy_dashboard_after_legacy_upload(flask_client, sample_xlsx_path):
    with open(sample_xlsx_path, "rb") as f:
        data = {"file": (io.BytesIO(f.read()), "test.xlsx")}
    flask_client.post("/api/upload", data=data, content_type="multipart/form-data")
    r = flask_client.get("/api/dashboard")
    assert r.status_code == 200
