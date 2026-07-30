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
    wb.save(path)

    parsed = FunctionListParser().parse(str(path))
    assert parsed.meta_columns.get("ma_du_an") is not None
    assert parsed.rows[0].meta.get("ma_du_an") == "MPHG_IHRP_2025_PM"
