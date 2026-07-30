"""Tests — giới hạn 10 lần upload/sync history + snapshot prune."""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from analyzer.project_store import (
    MAX_UPLOAD_HISTORY,
    append_upload_history,
    load_upload_history,
    save_archive_settings,
)
from analyzer.snapshot_manager import MAX_SNAPSHOTS, SnapshotManager


def test_max_upload_history_constant_is_10():
    assert MAX_UPLOAD_HISTORY == 10
    assert MAX_SNAPSHOTS == MAX_UPLOAD_HISTORY


def test_append_upload_history_caps_at_10(tmp_path):
    d = str(tmp_path)
    for i in range(15):
        append_upload_history(d, filename=f"f{i}.xlsx", row_count=i, checksum=f"c{i}")
    hist = load_upload_history(d)
    assert len(hist) == MAX_UPLOAD_HISTORY
    # Mới nhất ở đầu
    assert hist[0]["filename"] == "f14.xlsx"
    assert hist[-1]["filename"] == "f5.xlsx"


def test_load_upload_history_migrates_over_cap(tmp_path):
    """File cũ >10 entry → load prune về 10 và ghi lại."""
    d = str(tmp_path)
    path = os.path.join(d, "upload_history.json")
    bloated = [
        {"time": f"2026-01-{i:02d}T10:00:00", "filename": f"old{i}.xlsx",
         "row_count": i, "checksum": "", "source": "upload"}
        for i in range(1, 16)
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(bloated, f)

    hist = load_upload_history(d)
    assert len(hist) == MAX_UPLOAD_HISTORY
    # Đã persist
    with open(path, "r", encoding="utf-8") as f:
        on_disk = json.load(f)
    assert len(on_disk) == MAX_UPLOAD_HISTORY


def test_append_keeps_sync_and_upload_sources(tmp_path):
    d = str(tmp_path)
    append_upload_history(d, filename="a.xlsx", row_count=1, source="upload")
    append_upload_history(
        d, filename="b.xlsx", row_count=2, source="sync:integ1:ep1",
    )
    hist = load_upload_history(d)
    assert hist[0]["source"] == "sync:integ1:ep1"
    assert hist[1]["source"] == "upload"


def test_list_snapshots_migrates_over_cap(tmp_path):
    mgr = SnapshotManager(str(tmp_path))
    fake = []
    for i in range(MAX_SNAPSHOTS + 5):
        fake.append({
            "date": f"2026-02-{i + 1:02d}",
            "filename": f"fake_{i}.xlsx",
            "pickle": f"fake_{i}.pkl",
            "total_functions": 1,
            "overall_pct": 0,
            "overdue_count": 0,
            "unassigned_count": 0,
            "high_risk_count": 0,
            "upload_time": "2026-02-01T00:00:00",
            "source": "upload",
        })
    with open(mgr.index_path, "w", encoding="utf-8") as f:
        json.dump(fake, f)

    listed = mgr.list_snapshots()
    assert len(listed) == MAX_SNAPSHOTS
    # Newest kept
    assert listed[0]["date"] == f"2026-02-{MAX_SNAPSHOTS + 5:02d}"
    with open(mgr.index_path, "r", encoding="utf-8") as f:
        assert len(json.load(f)) == MAX_SNAPSHOTS


def test_save_snapshot_prunes_and_keeps_newest(
    tmp_path, sample_xlsx_path, parsed_data, metrics,
):
    """Overflow → xóa hot (archive off); newest (today) luôn còn."""
    project = tmp_path / "proj"
    snaps = project / "snapshots"
    snaps.mkdir(parents=True)
    save_archive_settings(str(project), {"enabled": False})

    mgr = SnapshotManager(str(snaps))
    # Seed index cũ hơn today
    today = date.today()
    fake = []
    for i in range(MAX_SNAPSHOTS + 3):
        d = (today - timedelta(days=i + 1)).isoformat()
        fake.append({
            "date": d,
            "filename": f"{d}_functionlist.xlsx",
            "pickle": f"{d}_functionlist.parsed.pkl",
            "total_functions": 1,
            "overall_pct": 0,
            "overdue_count": 0,
            "unassigned_count": 0,
            "high_risk_count": 0,
            "upload_time": f"{d}T00:00:00",
            "source": "upload",
        })
        # Tạo file giả để verify bị xóa
        (snaps / fake[-1]["filename"]).write_bytes(b"xlsx")
        (snaps / fake[-1]["pickle"]).write_bytes(b"pkl")

    with open(mgr.index_path, "w", encoding="utf-8") as f:
        json.dump(fake, f)

    entry = mgr.save_snapshot(sample_xlsx_path, parsed_data, metrics, source="upload")
    listed = mgr.list_snapshots()
    assert len(listed) == MAX_SNAPSHOTS
    assert listed[0]["date"] == entry["date"]
    assert listed[0]["date"] == today.isoformat()
    # current.xlsx không tồn tại trong snapshots — không bị đụng
    assert not (snaps / "current.xlsx").exists()


def test_prune_archives_when_enabled(
    tmp_path, sample_xlsx_path, parsed_data, metrics,
):
    """Archive enabled → overflow gọi archive_snapshot (gzip), bỏ khỏi index."""
    project = tmp_path / "proj"
    snaps = project / "snapshots"
    snaps.mkdir(parents=True)
    save_archive_settings(str(project), {"enabled": True})

    mgr = SnapshotManager(str(snaps))
    today = date.today()
    # 1 snapshot thật ở quá khứ
    old_day = (today - timedelta(days=20)).isoformat()
    # Tạm fake today để save_snapshot ghi đè logic — seed bằng save rồi sửa date
    mgr.save_snapshot(sample_xlsx_path, parsed_data, metrics)
    # Đổi entry today → old_day trên disk
    index = mgr._load_index()
    assert len(index) == 1
    old_entry = dict(index[0])
    old_xlsx = snaps / old_entry["filename"]
    old_pkl = snaps / old_entry["pickle"]
    new_xlsx_name = f"{old_day}_functionlist.xlsx"
    new_pkl_name = f"{old_day}_functionlist.parsed.pkl"
    old_xlsx.rename(snaps / new_xlsx_name)
    old_pkl.rename(snaps / new_pkl_name)
    old_entry["date"] = old_day
    old_entry["filename"] = new_xlsx_name
    old_entry["pickle"] = new_pkl_name
    mgr._save_index([old_entry])

    # Seed thêm MAX_SNAPSHOTS - 1 entry fake mới hơn old_day nhưng cũ hơn today
    extra = []
    for i in range(MAX_SNAPSHOTS - 1):
        d = (today - timedelta(days=i + 1)).isoformat()
        extra.append({
            "date": d,
            "filename": f"{d}_functionlist.xlsx",
            "pickle": f"{d}_functionlist.parsed.pkl",
            "total_functions": 1,
            "overall_pct": 0,
            "overdue_count": 0,
            "unassigned_count": 0,
            "high_risk_count": 0,
            "upload_time": f"{d}T00:00:00",
            "source": "upload",
        })
        (snaps / extra[-1]["filename"]).write_bytes(b"x")
        (snaps / extra[-1]["pickle"]).write_bytes(b"p")

    mgr._save_index(extra + [old_entry])
    assert len(mgr._load_index()) == MAX_SNAPSHOTS

    with patch.object(mgr, "_archive_enabled", return_value=True):
        # save today → index tạm thời MAX+1 → prune old_day (oldest)
        mgr.save_snapshot(sample_xlsx_path, parsed_data, metrics)

    listed = mgr.list_snapshots()
    assert len(listed) == MAX_SNAPSHOTS
    assert all(e["date"] != old_day for e in listed)
    # .gz còn trong archive/ (soft backup)
    gz = snaps / "archive" / (new_pkl_name + ".gz")
    assert gz.is_file()
    # Hot của old_day đã biến mất
    assert not (snaps / new_xlsx_name).exists()
    assert not (snaps / new_pkl_name).exists()
