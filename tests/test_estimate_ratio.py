"""Tests ước lượng theo hệ số (estimate_ratio)."""
from __future__ import annotations

import json

from parser.excel_parser import FunctionRow, ParsedData, PhaseData, PhaseGroup
from analyzer.estimate_ratio import (
    DEFAULT_PARAMS,
    compute_estimate_ratio,
    estimate_function_md,
    load_estimation_params,
    map_phase_bucket,
    normalize_params,
    save_estimation_params,
    _compile_keywords,
)


def _row(ma: str, phases: dict, meta: dict | None = None, row_num: int = 2) -> FunctionRow:
    m = {"ma_cn": ma, "ten_cn": ma, "module": "PR"}
    if meta:
        m.update(meta)
    return FunctionRow(row_num=row_num, meta=m, phases=phases)


def _data(rows, phase_names: list[str]) -> ParsedData:
    groups = [PhaseGroup(name=n, attributes={}) for n in phase_names]
    return ParsedData(
        headers={},
        meta_columns={},
        rows=rows,
        phase_groups=groups,
        all_phases=list(phase_names),
        all_modules=["PR"],
    )


def test_map_phase_keywords():
    compiled = _compile_keywords(DEFAULT_PARAMS["phase_keywords"])
    assert map_phase_bucket("Analysis", "Phân tích", compiled) == "ba"
    assert map_phase_bucket("Dev", "Lập trình", compiled) == "dev"
    assert map_phase_bucket("Local Test", "Kiểm thử", compiled) == "test"
    assert map_phase_bucket("UAT", "UAT", compiled) == "uat"
    assert map_phase_bucket("Config UAT", "Cấu hình UAT", compiled) == "config"


def test_seed_from_fl_estimate_and_ratios():
    """BA=8MH→1MD, Dev=16MH→2MD; Des=0.25, Test=0.6, Doc=0.3 (mh_per_day=8)."""
    row = _row("F1", {
        "Analysis": PhaseData(status="Open", estimate_mh=8),
        "Dev": PhaseData(status="Open", estimate_mh=16),
    })
    data = _data([row], ["Analysis", "Dev"])
    params = normalize_params({
        "mh_per_day": 8,
        "md_per_mm": 22,
        "ratios": {
            "des_of_ba": 0.25,
            "test_of_dev": 0.30,
            "doc_of_dev": 0.15,
            "config_of_dev": 0.0,
            "migration_of_dev": 0.0,
        },
        "overhead": {
            "include_uat": False,
            "include_golive": False,
            "include_pm": False,
            "include_warranty": False,
            "include_pentest": False,
        },
    })
    compiled = _compile_keywords(params["phase_keywords"])
    buckets = {p: map_phase_bucket(p, p, compiled) for p in ["Analysis", "Dev"]}
    # Fix buckets via task types like compute does
    buckets = {"Analysis": "ba", "Dev": "dev"}
    est = estimate_function_md(row, buckets, params)
    assert est["used_default_seed"] is False
    assert est["ba_source"] == "fl_estimate"
    assert est["dev_source"] == "fl_estimate"
    assert est["buckets_md"]["ba"] == 1.0
    assert est["buckets_md"]["dev"] == 2.0
    assert abs(est["buckets_md"]["des"] - 0.25) < 1e-9
    assert abs(est["buckets_md"]["test"] - 0.6) < 1e-9
    assert abs(est["buckets_md"]["doc"] - 0.3) < 1e-9

    result = compute_estimate_ratio(data, params)
    assert result["totals"]["functions"] == 1
    assert result["totals"]["functions_default_seed"] == 0
    assert result["basis_label"] == "Ước lượng theo hệ số"


def test_default_seed_and_lookup():
    row_default = _row("D1", {
        "Analysis": PhaseData(status="Open"),
        "Dev": PhaseData(status="Open"),
    })
    row_lookup = _row(
        "L1",
        {"Analysis": PhaseData(status="Open"), "Dev": PhaseData(status="Open")},
        meta={"complexity": "High", "fit_gap": "GAP"},
    )
    data = _data([row_default, row_lookup], ["Analysis", "Dev"])
    params = normalize_params({
        "seed_defaults": {"ba_md": 0.5, "dev_md": 2.0},
        "lookup": [
            {"complexity": "High", "fit_gap": "GAP", "ba_md": 2.0, "dev_md": 8.0},
        ],
        "overhead": {
            "include_uat": False,
            "include_golive": False,
            "include_pm": False,
            "include_warranty": False,
            "include_pentest": False,
        },
        "ratios": {"config_of_dev": 0, "migration_of_dev": 0},
    })
    result = compute_estimate_ratio(data, params)
    by_ma = {d["ma_cn"]: d for d in result["detail"]}
    assert by_ma["D1"]["used_default_seed"] is True
    assert by_ma["D1"]["buckets_md"]["ba"] == 0.5
    assert by_ma["D1"]["buckets_md"]["dev"] == 2.0
    assert by_ma["L1"]["used_default_seed"] is False
    assert by_ma["L1"]["ba_source"] == "lookup"
    assert by_ma["L1"]["buckets_md"]["ba"] == 2.0
    assert by_ma["L1"]["buckets_md"]["dev"] == 8.0
    assert result["totals"]["functions_default_seed"] == 1
    assert any("default" in w.lower() or "mặc định" in w for w in result["warnings"])


def test_uat_formula_incl_total():
    """UAT = 0.15/(0.85) * build."""
    row = _row("U1", {
        "Analysis": PhaseData(status="Open", estimate_mh=8),  # 1 MD
        "Dev": PhaseData(status="Open", estimate_mh=16),     # 2 MD
    })
    data = _data([row], ["Analysis", "Dev"])
    params = normalize_params({
        "ratios": {
            "des_of_ba": 0.25,
            "test_of_dev": 0.30,
            "doc_of_dev": 0.15,
            "config_of_dev": 0,
            "migration_of_dev": 0,
            "uat_of_total_incl_uat": 0.15,
            "golive_of_uat": 0.15,
            "pm_of_subtotal": 0.05,
        },
        "overhead": {
            "include_uat": True,
            "include_golive": True,
            "include_pm": True,
            "include_warranty": False,
            "include_pentest": False,
        },
    })
    result = compute_estimate_ratio(data, params)
    by = {p["bucket"]: p["md"] for p in result["by_phase"]}
    # build = ba1 + des0.25 + dev2 + test0.6 + doc0.3 = 4.15
    build = 1 + 0.25 + 2 + 0.6 + 0.3
    assert abs(result["totals"]["build_md"] - build) < 1e-6
    expect_uat = (0.15 / 0.85) * build
    assert abs(by["uat"] - expect_uat) < 1e-3
    assert abs(by["golive"] - expect_uat * 0.15) < 1e-3
    subtotal = build + expect_uat + expect_uat * 0.15
    assert abs(by["pm"] - subtotal * 0.05) < 1e-3


def test_params_save_load_project(tmp_path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    projects_folder = tmp_path / "projects"
    projects_folder.mkdir()
    saved = save_estimation_params(
        str(project_dir),
        {"seed_defaults": {"ba_md": 1.25, "dev_md": 3.5}, "md_per_mm": 20},
        scope="project",
        projects_folder=str(projects_folder),
    )
    assert saved["seed_defaults"]["ba_md"] == 1.25
    assert saved["_source"] == "project"
    path = project_dir / "estimation_params.json"
    assert path.is_file()
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["md_per_mm"] == 20
    loaded = load_estimation_params(str(project_dir), str(projects_folder))
    assert loaded["seed_defaults"]["dev_md"] == 3.5


def test_sovi_style_row_smoke():
    """
    So sánh vài dòng kiểu SOVI Estimation (MD nhập tay BA/Dev) với ratio Des/Test/Doc.
    Không assert tổng file SOVI — chỉ kiểm tra hệ số khớp mẫu.
    Row mẫu: BA=0.25, Dev=0.5 → Des=0.0625, Test=0.15, Doc=0.075
    """
    # Seed bằng Estimate MH: 0.25 MD * 8 = 2 MH; 0.5 MD * 8 = 4 MH
    row = _row("SOVI1", {
        "Analysis": PhaseData(status="Open", estimate_mh=2.0),
        "Dev": PhaseData(status="Open", estimate_mh=4.0),
    })
    params = normalize_params({
        "mh_per_day": 8,
        "ratios": {
            "des_of_ba": 0.25,
            "test_of_dev": 0.30,
            "doc_of_dev": 0.15,
            "config_of_dev": 0,
            "migration_of_dev": 0,
        },
        "overhead": {
            "include_uat": False,
            "include_golive": False,
            "include_pm": False,
            "include_warranty": False,
            "include_pentest": False,
        },
    })
    est = estimate_function_md(row, {"Analysis": "ba", "Dev": "dev"}, params)
    assert abs(est["buckets_md"]["ba"] - 0.25) < 1e-9
    assert abs(est["buckets_md"]["dev"] - 0.5) < 1e-9
    assert abs(est["buckets_md"]["des"] - 0.0625) < 1e-9
    assert abs(est["buckets_md"]["test"] - 0.15) < 1e-9
    assert abs(est["buckets_md"]["doc"] - 0.075) < 1e-9
