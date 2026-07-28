"""HTTP integration tests cho export-chart và audit-report endpoints."""
import io
import openpyxl


def _upload(client, sample_xlsx_path):
    with open(sample_xlsx_path, "rb") as f:
        return client.post(
            "/api/projects/default/upload",
            data={"file": (io.BytesIO(f.read()), "sample.xlsx")},
            content_type="multipart/form-data",
        )


# ==========================================================================
# GET/POST /api/projects/<slug>/export-chart
# ==========================================================================

def test_export_chart_requires_upload(flask_client):
    r = flask_client.get("/api/projects/default/export-chart?chart=priority")
    assert r.status_code in (400, 404)
    assert "error" in r.get_json()


def test_export_chart_missing_chart_param(flask_client, sample_xlsx_path):
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.get("/api/projects/default/export-chart")
    assert r.status_code == 400
    assert "chart" in r.get_json()["error"].lower()


def test_export_chart_unsupported(flask_client, sample_xlsx_path):
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.get("/api/projects/default/export-chart?chart=not_a_real_chart")
    assert r.status_code == 400
    data = r.get_json()
    assert "supported" in data


def test_export_chart_priority_xlsx(flask_client, sample_xlsx_path):
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.get("/api/projects/default/export-chart?chart=priority")
    assert r.status_code == 200
    assert "spreadsheet" in (r.content_type or "") or r.data[:2] == b"PK"
    wb = openpyxl.load_workbook(io.BytesIO(r.data))
    assert len(wb.sheetnames) >= 1
    wb.close()


def test_export_chart_effort_heatmap_with_module_filter(flask_client, sample_xlsx_path):
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.get(
        "/api/projects/default/export-chart?chart=effort_heatmap&module=TMS"
    )
    assert r.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(r.data))
    assert len(wb.sheetnames) >= 1
    wb.close()


def test_export_chart_post_body(flask_client, sample_xlsx_path):
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.post(
        "/api/projects/default/export-chart",
        json={"chart": "task_type", "module": ["TMS"]},
    )
    assert r.status_code == 200
    assert r.data[:2] == b"PK"


# ==========================================================================
# GET/POST /api/projects/<slug>/audit-report
# ==========================================================================

def test_audit_report_requires_upload(flask_client):
    r = flask_client.get("/api/projects/default/audit-report?scope=all")
    assert r.status_code in (400, 404)
    assert "error" in r.get_json()


def test_audit_report_all_xlsx(flask_client, sample_xlsx_path):
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.get("/api/projects/default/audit-report?scope=all")
    assert r.status_code == 200
    assert r.data[:2] == b"PK"
    wb = openpyxl.load_workbook(io.BytesIO(r.data))
    # Audit report có nhiều sheet (summary + issue sheets)
    assert len(wb.sheetnames) >= 2
    wb.close()


def test_audit_report_filtered_scope(flask_client, sample_xlsx_path):
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.get(
        "/api/projects/default/audit-report?scope=filtered&module=TMS"
    )
    assert r.status_code == 200
    assert r.data[:2] == b"PK"


def test_audit_report_post(flask_client, sample_xlsx_path):
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.post(
        "/api/projects/default/audit-report",
        json={"scope": "all"},
    )
    assert r.status_code == 200
    assert r.data[:2] == b"PK"
