"""Unit tests — analyzer.module_order + project_store module_order."""
from __future__ import annotations

import os
import tempfile

from analyzer.module_order import (
    apply_module_order,
    module_sort_key,
    normalize_order,
    process_module_rank,
    sort_modules,
)
from analyzer import project_store as ps


def test_normalize_order_shapes():
    assert normalize_order(["TMS", "HR", "TMS", ""]) == ["TMS", "HR"]
    assert normalize_order({"order": ["PR", "HR"]}) == ["PR", "HR"]
    assert normalize_order({"TMS": 1, "HR": 2, "PR": 1}) == ["PR", "TMS", "HR"]
    assert normalize_order(None) == []
    assert normalize_order("bad") == []


def test_sort_modules_default_alphabetical():
    assert sort_modules(["TMS", "HR", "PR"]) == ["HR", "PR", "TMS"]
    assert apply_module_order(["B", "A"], []) == ["A", "B"]


def test_sort_modules_preferred_then_extras():
    assert sort_modules(
        ["ESS", "HR", "PR", "SYS", "TMS"],
        ["TMS", "HR", "PR"],
    ) == ["TMS", "HR", "PR", "ESS", "SYS"]


def test_module_sort_key_and_process_rank():
    order = ["TMS", "HR", "PR"]
    assert module_sort_key("TMS", order) < module_sort_key("HR", order)
    assert module_sort_key("ZZZ", order)[0] == 1  # unknown → alpha bucket
    assert process_module_rank(["HR", "TMS"], order) == module_sort_key("TMS", order)
    assert process_module_rank([], order) == (1, "")


def test_project_store_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        assert ps.load_module_order(d) == []
        saved = ps.save_module_order(d, ["TMS", " HR ", "TMS", ""])
        assert saved == ["TMS", "HR"]
        assert ps.load_module_order(d) == ["TMS", "HR"]
        assert os.path.isfile(os.path.join(d, "module_order.json"))
        ps.reset_module_order(d)
        assert ps.load_module_order(d) == []
        assert not os.path.isfile(os.path.join(d, "module_order.json"))


def test_process_analysis_respects_all_modules_order(parsed_data):
    """Process tiles sort theo module rank trong data.all_modules."""
    from analyzer.dashboard_engine import DashboardEngine

    # Ép order: TMS trước HR trước các module khác
    preferred = ["TMS", "HR"] + [
        m for m in parsed_data.all_modules if m not in ("TMS", "HR")
    ]
    parsed_data.all_modules = preferred
    items = DashboardEngine().compute_all(parsed_data)["process_analysis"]
    assert items, "cần có process_analysis"
    # Module đại diện của item đầu phải là TMS (rank 0) nếu có process thuộc TMS
    tms_first_idx = next(
        (i for i, it in enumerate(items) if "TMS" in (it.get("modules") or [])),
        None,
    )
    hr_first_idx = next(
        (i for i, it in enumerate(items) if it.get("modules") == ["HR"]),
        None,
    )
    if tms_first_idx is not None and hr_first_idx is not None:
        assert tms_first_idx < hr_first_idx
