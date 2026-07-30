"""Tests cho analyzer.archive_manager — archive / restore / auto / purge / transparent load."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
from datetime import date, timedelta

import pytest

from analyzer.archive_manager import (
    archive_snapshot,
    auto_archive_project,
    list_archived,
    purge_archive,
    restore_snapshot,
    snapshot_disk_usage,
)
from analyzer.snapshot_manager import SnapshotManager
from analyzer import project_store as ps


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        h.update(f.read())
    return h.hexdigest()


def test_archive_then_restore_checksum_equal(tmp_path, sample_xlsx_path, parsed_data, metrics):
    """Archive → restore → checksum xlsx/pkl bằng bản gốc."""
    mgr = SnapshotManager(str(tmp_path))
    entry = mgr.save_snapshot(sample_xlsx_path, parsed_data, metrics)
    snap_id = entry["date"]

    xlsx_path = os.path.join(str(tmp_path), entry["filename"])
    pkl_path = os.path.join(str(tmp_path), entry["pickle"])
    xlsx_hash = _sha256(xlsx_path)
    pkl_hash = _sha256(pkl_path)

    archived = archive_snapshot(str(tmp_path), snap_id)
    assert archived["archived"] is True
    assert archived["archive_checksums"]["xlsx"] == xlsx_hash
    assert archived["archive_checksums"]["pickle"] == pkl_hash
    # Hot files đã bị xóa
    assert not os.path.isfile(xlsx_path)
    assert not os.path.isfile(pkl_path)
    # Archive .gz tồn tại
    assert os.path.isfile(os.path.join(str(tmp_path), "archive", entry["filename"] + ".gz"))
    assert os.path.isfile(os.path.join(str(tmp_path), "archive", entry["pickle"] + ".gz"))

    restored = restore_snapshot(str(tmp_path), snap_id)
    assert restored["archived"] is False
    assert os.path.isfile(xlsx_path)
    assert os.path.isfile(pkl_path)
    assert _sha256(xlsx_path) == xlsx_hash
    assert _sha256(pkl_path) == pkl_hash


def test_load_snapshot_transparent_when_archived(tmp_path, sample_xlsx_path, parsed_data, metrics):
    """load_snapshot đọc được pickle gzip khi archived (không extract)."""
    mgr = SnapshotManager(str(tmp_path))
    entry = mgr.save_snapshot(sample_xlsx_path, parsed_data, metrics)
    n_rows = len(parsed_data.rows)

    archive_snapshot(str(tmp_path), entry["date"])
    # Hot pickle đã mất
    assert not os.path.isfile(os.path.join(str(tmp_path), entry["pickle"]))

    loaded = mgr.load_snapshot(entry["date"])
    assert loaded is not None
    assert len(loaded["parsed"].rows) == n_rows
    assert loaded["meta"]["archived"] is True


def test_list_snapshots_includes_archived_flag(tmp_path, sample_xlsx_path, parsed_data, metrics):
    mgr = SnapshotManager(str(tmp_path))
    entry = mgr.save_snapshot(sample_xlsx_path, parsed_data, metrics)
    listed = mgr.list_snapshots()
    assert listed[0]["archived"] is False

    archive_snapshot(str(tmp_path), entry["date"])
    listed2 = mgr.list_snapshots()
    assert listed2[0]["archived"] is True
    assert len(list_archived(str(tmp_path))) == 1


def test_auto_archive_by_days(tmp_path, sample_xlsx_path, parsed_data, metrics):
    """Snapshot cũ hơn days → bị archive; mới hơn → giữ hot."""
    mgr = SnapshotManager(str(tmp_path))
    entry = mgr.save_snapshot(sample_xlsx_path, parsed_data, metrics)

    # Fake ngày snapshot thành 100 ngày trước
    index_path = os.path.join(str(tmp_path), "snapshot_index.json")
    with open(index_path, "r", encoding="utf-8") as f:
        index = json.load(f)
    old_date = (date.today() - timedelta(days=100)).isoformat()
    # Rename files cho khớp date mới
    old_xlsx = f"{old_date}_functionlist.xlsx"
    old_pkl = f"{old_date}_functionlist.parsed.pkl"
    os.rename(
        os.path.join(str(tmp_path), index[0]["filename"]),
        os.path.join(str(tmp_path), old_xlsx),
    )
    os.rename(
        os.path.join(str(tmp_path), index[0]["pickle"]),
        os.path.join(str(tmp_path), old_pkl),
    )
    index[0]["date"] = old_date
    index[0]["filename"] = old_xlsx
    index[0]["pickle"] = old_pkl
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f)

    processed = auto_archive_project(str(tmp_path), days=90, today=date.today())
    assert len(processed) == 1
    assert processed[0]["archived"] is True

    # days=0 → không archive gì thêm
    assert auto_archive_project(str(tmp_path), days=0) == []


def test_purge_archive_old(tmp_path, sample_xlsx_path, parsed_data, metrics):
    mgr = SnapshotManager(str(tmp_path))
    entry = mgr.save_snapshot(sample_xlsx_path, parsed_data, metrics)
    archive_snapshot(str(tmp_path), entry["date"])

    # Fake archived_at rất cũ
    index_path = os.path.join(str(tmp_path), "snapshot_index.json")
    with open(index_path, "r", encoding="utf-8") as f:
        index = json.load(f)
    index[0]["archived_at"] = (date.today() - timedelta(days=400)).isoformat() + "T00:00:00"
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f)

    purged = purge_archive(str(tmp_path), days=365, today=date.today())
    assert entry["date"] in purged
    assert list_archived(str(tmp_path)) == []


def test_archive_settings_roundtrip(tmp_path):
    s = ps.load_archive_settings(str(tmp_path))
    assert s["archive_after_days"] == 90
    assert s["enabled"] is True

    saved = ps.save_archive_settings(str(tmp_path), {
        "enabled": False,
        "archive_after_days": 30,
        "auto_run_on_startup": False,
        "purge_after_days": 180,
    })
    assert saved["enabled"] is False
    assert saved["archive_after_days"] == 30
    assert saved["purge_after_days"] == 180

    again = ps.load_archive_settings(str(tmp_path))
    assert again == saved


def test_archive_settings_api(flask_client, sample_xlsx_path):
    """GET/PUT archive-settings + POST archive-run smoke."""
    import io
    with open(sample_xlsx_path, "rb") as f:
        flask_client.post(
            "/api/projects/default/upload",
            data={"file": (io.BytesIO(f.read()), "sample.xlsx")},
            content_type="multipart/form-data",
        )
    r = flask_client.get("/api/projects/default/archive-settings")
    assert r.status_code == 200
    payload = r.get_json()
    assert "settings" in payload
    assert "snapshots" in payload

    r2 = flask_client.put(
        "/api/projects/default/archive-settings",
        json={"archive_after_days": 7, "enabled": True},
    )
    assert r2.status_code == 200
    assert r2.get_json()["settings"]["archive_after_days"] == 7

    # archive-run với days rất lớn → không archive snapshot hôm nay
    r3 = flask_client.post(
        "/api/projects/default/archive-run",
        json={"days": 9999, "purge": False},
    )
    assert r3.status_code == 200
    assert r3.get_json()["archived_count"] == 0


def test_snapshot_disk_usage(tmp_path, sample_xlsx_path, parsed_data, metrics):
    mgr = SnapshotManager(str(tmp_path))
    entry = mgr.save_snapshot(sample_xlsx_path, parsed_data, metrics)
    before = snapshot_disk_usage(str(tmp_path))
    assert before["hot_bytes"] > 0
    archive_snapshot(str(tmp_path), entry["date"])
    after = snapshot_disk_usage(str(tmp_path))
    assert after["archived_bytes"] > 0
    # Gzip thường nhỏ hơn hoặc bằng (xlsx đã zip sẵn — có thể ~ tương đương)
    assert after["total_bytes"] > 0
