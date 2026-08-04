"""Tests HTTP integration cho BA Task Management API (Gói B2)."""
import io

import openpyxl


def test_create_list_get(flask_client):
    r = flask_client.post("/api/projects/default/ba-tasks", json={"title": "Khảo sát TMS", "module": "TMS"})
    assert r.status_code == 201
    task = r.get_json()["task"]
    assert task["title"] == "Khảo sát TMS"

    r = flask_client.get("/api/projects/default/ba-tasks")
    assert r.status_code == 200
    data = r.get_json()
    assert data["total"] == 1

    r = flask_client.get(f"/api/projects/default/ba-tasks/{task['id']}")
    assert r.status_code == 200
    assert r.get_json()["task"]["id"] == task["id"]


def test_create_missing_title_400(flask_client):
    r = flask_client.post("/api/projects/default/ba-tasks", json={})
    assert r.status_code == 400


def test_update_and_delete(flask_client):
    r = flask_client.post("/api/projects/default/ba-tasks", json={"title": "A"})
    task_id = r.get_json()["task"]["id"]

    r = flask_client.put(f"/api/projects/default/ba-tasks/{task_id}", json={"status": "in_progress"})
    assert r.status_code == 200
    assert r.get_json()["task"]["status"] == "in_progress"

    r = flask_client.delete(f"/api/projects/default/ba-tasks/{task_id}")
    assert r.status_code == 200

    r = flask_client.get(f"/api/projects/default/ba-tasks/{task_id}")
    assert r.status_code == 404


def test_update_missing_404(flask_client):
    r = flask_client.put("/api/projects/default/ba-tasks/task_notexist", json={"status": "done"})
    assert r.status_code == 404


def test_delete_missing_404(flask_client):
    r = flask_client.delete("/api/projects/default/ba-tasks/task_notexist")
    assert r.status_code == 404


def test_project_missing_404(flask_client):
    r = flask_client.get("/api/projects/nonexistent-slug/ba-tasks")
    assert r.status_code == 404


def test_bulk_create(flask_client):
    r = flask_client.post("/api/projects/default/ba-tasks/bulk", json={"tasks": [{"title": "A"}, {"title": "B"}]})
    assert r.status_code == 201
    assert len(r.get_json()["tasks"]) == 2
    r = flask_client.get("/api/projects/default/ba-tasks")
    assert r.get_json()["total"] == 2


def test_bulk_create_missing_tasks_400(flask_client):
    r = flask_client.post("/api/projects/default/ba-tasks/bulk", json={})
    assert r.status_code == 400


def test_filter_by_status_and_type(flask_client):
    flask_client.post("/api/projects/default/ba-tasks", json={"title": "A", "status": "open"})
    flask_client.post("/api/projects/default/ba-tasks", json={"title": "B", "status": "done"})
    flask_client.post("/api/projects/default/ba-tasks", json={"title": "Họp", "type": "meeting"})

    r = flask_client.get("/api/projects/default/ba-tasks?status=done")
    assert r.get_json()["total"] == 1

    r = flask_client.get("/api/projects/default/ba-tasks?type=meeting")
    assert r.get_json()["total"] == 1


def test_filter_by_alert_overdue(flask_client):
    flask_client.post("/api/projects/default/ba-tasks", json={"title": "Trễ", "due_date": "2000-01-01"})
    flask_client.post("/api/projects/default/ba-tasks", json={"title": "Xa", "due_date": "2099-01-01"})
    r = flask_client.get("/api/projects/default/ba-tasks?alert=overdue")
    data = r.get_json()
    assert data["total"] == 1
    assert data["tasks"][0]["title"] == "Trễ"


def test_stats_endpoint(flask_client):
    flask_client.post("/api/projects/default/ba-tasks", json={"title": "A", "status": "open"})
    flask_client.post("/api/projects/default/ba-tasks", json={"title": "B", "status": "done"})
    r = flask_client.get("/api/projects/default/ba-tasks/stats")
    assert r.status_code == 200
    stats = r.get_json()
    assert stats["by_status"]["open"] == 1
    assert stats["by_status"]["done"] == 1


def test_export_all(flask_client):
    flask_client.post("/api/projects/default/ba-tasks", json={"title": "A"})
    r = flask_client.get("/api/projects/default/ba-tasks/export")
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("application/") or "sheet" in r.headers["Content-Type"]


def test_export_weekly_default_week(flask_client):
    flask_client.post("/api/projects/default/ba-tasks", json={"title": "A"})
    r = flask_client.get("/api/projects/default/ba-tasks/export-weekly")
    assert r.status_code == 200


def _make_xlsx_bytes(headers, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def test_import_preview_and_confirm(flask_client):
    buf = _make_xlsx_bytes(
        ["Tiêu đề", "Module", "Người phụ trách", "Hạn", "Loại", "Ghi chú"],
        [
            ["Khảo sát chấm công", "TMS", "Nhi", "2026-08-10", "task", "Chờ KH gửi form"],
            ["Review config", "TMS", "Hải", "2026-08-12", "task", ""],
        ],
    )
    r = flask_client.post(
        "/api/projects/default/ba-tasks/import/preview",
        data={"file": (buf, "tasks.xlsx")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 200
    preview = r.get_json()
    assert preview["suggested_mapping"]["title"] == "Tiêu đề"
    assert preview["suggested_mapping"]["due_date"] == "Hạn"
    tmp_id = preview["tmp_id"]

    r = flask_client.post(
        "/api/projects/default/ba-tasks/import",
        json={"tmp_id": tmp_id, "mapping": preview["suggested_mapping"]},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["imported"] == 2

    r = flask_client.get("/api/projects/default/ba-tasks")
    assert r.get_json()["total"] == 2


def test_import_bad_tmp_id_400(flask_client):
    r = flask_client.post("/api/projects/default/ba-tasks/import", json={"tmp_id": "doesnotexist"})
    assert r.status_code == 400


def test_import_preview_no_file_400(flask_client):
    r = flask_client.post("/api/projects/default/ba-tasks/import/preview", data={}, content_type="multipart/form-data")
    assert r.status_code == 400
