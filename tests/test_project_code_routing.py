"""
Tests: multi-project routing theo Mã dự án (project_code_field / map / filter).
"""
from __future__ import annotations

from analyzer import integrations as integ_mod


def test_group_records_by_map():
    records = [
        {"project": "MPHG_IHRP_2025_PM", "functionCode": "A"},
        {"project": "MPHG_IHRP_2025_PM", "functionCode": "B"},
        {"project": "OTHER_X", "functionCode": "C"},
        {"project": "OTHER_X", "functionCode": "D"},
        {"project": "UNKNOWN", "functionCode": "E"},
        {"functionCode": "F"},  # missing project
    ]
    groups, skipped = integ_mod.group_records_by_project_code(
        records,
        project_code_field="project",
        project_code_map={
            "MPHG_IHRP_2025_PM": "mphg",
            "OTHER_X": "other",
        },
        default_slug="mphg",
    )
    assert set(groups.keys()) == {"mphg", "other"}
    assert len(groups["mphg"]) == 2
    assert len(groups["other"]) == 2
    # UNKNOWN + empty
    reasons = {(s["code"], s["reason"]): s["count"] for s in skipped}
    assert reasons[("UNKNOWN", "unmapped")] == 1
    assert reasons[("(empty)", "empty")] == 1


def test_group_records_filter_only():
    records = [
        {"project": "MPHG_IHRP_2025_PM", "id": 1},
        {"project": "OTHER", "id": 2},
        {"project": "MPHG_IHRP_2025_PM", "id": 3},
    ]
    groups, skipped = integ_mod.group_records_by_project_code(
        records,
        project_code_field="project",
        project_code_map={},
        project_code_filter="MPHG_IHRP_2025_PM",
        default_slug="mphg",
    )
    assert list(groups.keys()) == ["mphg"]
    assert len(groups["mphg"]) == 2
    assert any(s["reason"] == "filtered" and s["count"] == 1 for s in skipped)


def test_group_records_filter_plus_map():
    """Filter thu hẹp trước; map quyết định slug."""
    records = [
        {"project": "KEEP", "id": 1},
        {"project": "DROP", "id": 2},
        {"project": "KEEP", "id": 3},
    ]
    groups, skipped = integ_mod.group_records_by_project_code(
        records,
        project_code_field="project",
        project_code_map={"KEEP": "alpha"},
        project_code_filter="KEEP",
        default_slug="default",
    )
    assert groups == {"alpha": [records[0], records[2]]}
    assert any(s["reason"] == "filtered" for s in skipped)


def test_sanitize_endpoint_keeps_project_routing():
    ep = integ_mod._sanitize_endpoint({
        "name": "FL",
        "path": "/api/x",
        "response_type": "json",
        "data_path": "data",
        "field_mapping": {"Mã CN": "functionCode", "Mã dự án": "project"},
        "project_code_field": "project",
        "project_code_map": {"MPHG_IHRP_2025_PM": "mphg", "": "bad", "X": "Bad Slug"},
        "project_code_filter": "MPHG_IHRP_2025_PM",
    })
    assert ep is not None
    assert ep["project_code_field"] == "project"
    assert ep["project_code_filter"] == "MPHG_IHRP_2025_PM"
    assert ep["project_code_map"] == {"MPHG_IHRP_2025_PM": "mphg"}
    assert ep["field_mapping"]["Mã dự án"] == "project"


def test_routing_enabled_requires_field_and_map_or_filter():
    assert integ_mod._routing_enabled({"project_code_field": ""}) is False
    assert integ_mod._routing_enabled({
        "project_code_field": "project",
        "project_code_map": {},
        "project_code_filter": "",
    }) is False
    assert integ_mod._routing_enabled({
        "project_code_field": "project",
        "project_code_map": {"A": "a"},
    }) is True
    assert integ_mod._routing_enabled({
        "project_code_field": "project",
        "project_code_filter": "A",
    }) is True


def test_ma_du_an_meta_detect(tmp_path):
    """Parser nhận cột Mã dự án vào meta.ma_du_an."""
    import openpyxl
    from parser.excel_parser import FunctionListParser

    path = tmp_path / "fl.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Function List"
    ws.append(["Mã CN", "Tên chức năng", "Module", "Mã dự án", "Analysis - Status"])
    ws.append(["X.01", "Test", "TMS", "MPHG_IHRP_2025_PM", "Closed"])
    ws.append(["X.02", "Test2", "HR", "OTHER_CODE", "Open"])
    wb.save(path)

    parsed = FunctionListParser().parse(str(path))
    assert parsed.meta_columns.get("ma_du_an") is not None
    assert parsed.rows[0].meta.get("ma_du_an") == "MPHG_IHRP_2025_PM"
    assert parsed.all_project_codes == ["MPHG_IHRP_2025_PM", "OTHER_CODE"]


def test_filter_by_project_codes(tmp_path):
    """_filter_parsed_data cắt rows theo meta.ma_du_an."""
    import openpyxl
    from app import _filter_parsed_data
    from parser.excel_parser import FunctionListParser

    path = tmp_path / "fl2.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Function List"
    ws.append(["Mã CN", "Tên chức năng", "Module", "Mã dự án", "Analysis - Status"])
    ws.append(["A.01", "A", "TMS", "MPHG_IHRP_2025_PM", "Closed"])
    ws.append(["B.01", "B", "HR", "OTHER_CODE", "Open"])
    ws.append(["C.01", "C", "PR", "MPHG_IHRP_2025_PM", "Open"])
    wb.save(path)

    parsed = FunctionListParser().parse(str(path))
    filtered = _filter_parsed_data(parsed, project_codes=["MPHG_IHRP_2025_PM"])
    assert len(filtered.rows) == 2
    assert filtered.all_project_codes == ["MPHG_IHRP_2025_PM"]
    assert all(r.meta.get("ma_du_an") == "MPHG_IHRP_2025_PM" for r in filtered.rows)


def test_structure_includes_all_project_codes(tmp_path):
    import openpyxl
    from analyzer.dashboard_engine import DashboardEngine
    from parser.excel_parser import FunctionListParser

    path = tmp_path / "fl3.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Function List"
    ws.append(["Mã CN", "Tên chức năng", "Module", "Mã dự án", "Analysis - Status"])
    ws.append(["A.01", "A", "TMS", "CODE_A", "Closed"])
    wb.save(path)
    parsed = FunctionListParser().parse(str(path))
    metrics = DashboardEngine().compute_all(parsed)
    assert metrics["structure"]["all_project_codes"] == ["CODE_A"]


def test_dashboard_g_project_and_alias(flask_client, tmp_path):
    """Dashboard nhận g_project / g_ma_du_an; clear → full dataset."""
    import io
    import openpyxl

    path = tmp_path / "upload.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Function List"
    ws.append(["Mã CN", "Tên chức năng", "Module", "Mã dự án", "Analysis - Status"])
    ws.append(["A.01", "A", "TMS", "CODE_A", "Closed"])
    ws.append(["A.02", "B", "HR", "CODE_B", "Open"])
    wb.save(path)

    with open(path, "rb") as f:
        up = flask_client.post(
            "/api/projects/default/upload",
            data={"file": (io.BytesIO(f.read()), "upload.xlsx")},
            content_type="multipart/form-data",
        )
    assert up.status_code == 200

    r_a = flask_client.get("/api/projects/default/dashboard?g_project=CODE_A")
    assert r_a.status_code == 200
    body = r_a.get_json()
    assert body["applied_filter"]["project_codes"] == ["CODE_A"]
    assert body["applied_filter"]["row_count"] == 1
    assert body["metrics"]["summary"]["total_functions"] == 1

    r_clear = flask_client.get("/api/projects/default/dashboard")
    assert r_clear.get_json()["applied_filter"] is None
    assert r_clear.get_json()["metrics"]["summary"]["total_functions"] == 2

    r_alias = flask_client.get("/api/projects/default/dashboard?g_ma_du_an=CODE_B")
    assert r_alias.get_json()["applied_filter"]["row_count"] == 1


def test_saved_view_persists_project_codes(tmp_path):
    from analyzer.project_store import load_saved_views, upsert_saved_view

    d = str(tmp_path)
    upsert_saved_view(d, {
        "name": "Ma A",
        "modules": [],
        "processes": [],
        "pics": [],
        "project_codes": ["CODE_A"],
    })
    views = load_saved_views(d)
    assert views[0]["project_codes"] == ["CODE_A"]
