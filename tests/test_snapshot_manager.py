"""Tests cho analyzer.snapshot_manager."""
import json
import os
from datetime import date

import pytest

from analyzer.snapshot_manager import SnapshotManager, MAX_SNAPSHOTS


def test_save_creates_files(tmp_path, sample_xlsx_path, parsed_data, metrics):
    """save_snapshot tạo file .xlsx + .pkl + index."""
    mgr = SnapshotManager(str(tmp_path))
    entry = mgr.save_snapshot(sample_xlsx_path, parsed_data, metrics)

    assert os.path.exists(os.path.join(str(tmp_path), entry["filename"]))
    assert os.path.exists(os.path.join(str(tmp_path), entry["pickle"]))
    assert os.path.exists(os.path.join(str(tmp_path), "snapshot_index.json"))


def test_save_metadata_correct(tmp_path, sample_xlsx_path, parsed_data, metrics):
    """Metadata trong entry khớp với summary."""
    mgr = SnapshotManager(str(tmp_path))
    entry = mgr.save_snapshot(sample_xlsx_path, parsed_data, metrics)
    assert entry["total_functions"] == metrics["summary"]["total_functions"]
    assert entry["overdue_count"] == metrics["summary"]["total_overdue"]
    assert entry["unassigned_count"] == metrics["summary"]["unassigned_count"]
    assert entry["high_risk_count"] == metrics["summary"]["high_risk_count"]


def test_save_same_day_overwrites(tmp_path, sample_xlsx_path, parsed_data, metrics):
    """Save 2 lần cùng ngày → chỉ có 1 entry."""
    mgr = SnapshotManager(str(tmp_path))
    mgr.save_snapshot(sample_xlsx_path, parsed_data, metrics)
    mgr.save_snapshot(sample_xlsx_path, parsed_data, metrics)
    assert len(mgr.list_snapshots()) == 1


def test_load_snapshot(tmp_path, sample_xlsx_path, parsed_data, metrics):
    """load_snapshot trả về đúng ParsedData đã lưu."""
    mgr = SnapshotManager(str(tmp_path))
    entry = mgr.save_snapshot(sample_xlsx_path, parsed_data, metrics)
    loaded = mgr.load_snapshot(entry["date"])
    assert loaded is not None
    assert len(loaded["parsed"].rows) == len(parsed_data.rows)


def test_load_nonexistent_returns_none(tmp_path):
    """Load ngày không tồn tại → None."""
    mgr = SnapshotManager(str(tmp_path))
    assert mgr.load_snapshot("1999-01-01") is None


def test_delete_snapshot(tmp_path, sample_xlsx_path, parsed_data, metrics):
    """Delete xóa cả file + entry."""
    mgr = SnapshotManager(str(tmp_path))
    entry = mgr.save_snapshot(sample_xlsx_path, parsed_data, metrics)
    assert mgr.delete_snapshot(entry["date"]) is True
    assert not os.path.exists(os.path.join(str(tmp_path), entry["filename"]))
    assert not os.path.exists(os.path.join(str(tmp_path), entry["pickle"]))
    assert mgr.list_snapshots() == []


def test_delete_nonexistent_returns_false(tmp_path):
    mgr = SnapshotManager(str(tmp_path))
    assert mgr.delete_snapshot("1999-01-01") is False


def test_max_snapshots_limit(tmp_path, sample_xlsx_path, parsed_data, metrics):
    """Vượt MAX_SNAPSHOTS → snapshot cũ nhất bị xóa."""
    mgr = SnapshotManager(str(tmp_path))
    # Fake nhiều entry bằng cách sửa index trực tiếp
    fake_entries = []
    for i in range(MAX_SNAPSHOTS + 5):
        fake_entries.append({
            "date": f"2026-01-{i+1:02d}",
            "filename": f"fake_{i}.xlsx",
            "pickle": f"fake_{i}.pkl",
            "total_functions": 100,
            "overall_pct": 50,
            "overdue_count": 5,
            "unassigned_count": 3,
            "high_risk_count": 10,
            "upload_time": "2026-01-01T00:00:00",
        })
    # Ghi index
    with open(mgr.index_path, "w", encoding="utf-8") as f:
        json.dump(fake_entries, f)

    # Save 1 snapshot thật → sẽ trigger cleanup
    mgr.save_snapshot(sample_xlsx_path, parsed_data, metrics)
    assert len(mgr.list_snapshots()) == MAX_SNAPSHOTS


def test_index_persists_between_instances(tmp_path, sample_xlsx_path, parsed_data, metrics):
    """Instance mới đọc lại được index cũ."""
    mgr1 = SnapshotManager(str(tmp_path))
    entry = mgr1.save_snapshot(sample_xlsx_path, parsed_data, metrics)
    mgr2 = SnapshotManager(str(tmp_path))
    assert len(mgr2.list_snapshots()) == 1
    assert mgr2.list_snapshots()[0]["date"] == entry["date"]
