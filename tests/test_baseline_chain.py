"""
Tests — chuỗi baseline bất biến (analyzer/baseline_manager.py).

Trọng tâm là 2 lỗi mà baseline kiểu cũ (`baseline_snapshot_id` trỏ vào
`snapshots/`) mắc phải:
  1. Snapshot bị prune khi vượt cap → baseline biến mất.
  2. Upload lại cùng ngày ghi đè snapshot → nội dung baseline âm thầm đổi.
"""
from __future__ import annotations

import io
import os
import pickle
from datetime import date

import openpyxl
import pytest

from analyzer.baseline_manager import BaselineManager, latest_baseline
from analyzer.snapshot_manager import SnapshotManager


def _fake_parsed(tag: str):
    """Object đơn giản, chỉ cần pickle được và phân biệt được nội dung."""
    return {"tag": tag}


def _make_snapshot(snap_dir: str, snap_date: str, tag: str) -> dict:
    """Tạo tay 1 cặp file snapshot + entry (không cần cả DashboardEngine)."""
    os.makedirs(snap_dir, exist_ok=True)
    xlsx = f"{snap_date}_functionlist.xlsx"
    pkl = f"{snap_date}_functionlist.parsed.pkl"
    wb = openpyxl.Workbook()
    wb.active.cell(1, 1, tag)
    wb.save(os.path.join(snap_dir, xlsx))
    wb.close()
    with open(os.path.join(snap_dir, pkl), "wb") as f:
        pickle.dump(_fake_parsed(tag), f)
    return {
        "date": snap_date, "filename": xlsx, "pickle": pkl,
        "total_functions": 10, "overall_pct": 42,
    }


# ------------------------------------------------------------------
# pin / version / bất biến
# ------------------------------------------------------------------

def test_pin_creates_immutable_copy_with_checksum(tmp_path):
    snap_dir = str(tmp_path / "snapshots")
    entry = _make_snapshot(snap_dir, "2026-06-01", "v1")
    bm = BaselineManager(str(tmp_path / "baselines"))

    pinned = bm.pin_from_snapshot(snap_dir, entry, label="Approved 06", created_by="admin")
    assert pinned["version"] == 1
    assert pinned["id"] == "2026-06-01_v1"
    assert pinned["label"] == "Approved 06"
    assert pinned["created_by"] == "admin"
    assert len(pinned["checksum"]) == 64
    # File nằm trong baselines/, không phải trong snapshots/
    assert os.path.isfile(str(tmp_path / "baselines" / pinned["pickle"]))
    assert os.path.isfile(str(tmp_path / "baselines" / pinned["filename"]))


def test_version_increases_per_pin(tmp_path):
    snap_dir = str(tmp_path / "snapshots")
    e1 = _make_snapshot(snap_dir, "2026-06-01", "a")
    e2 = _make_snapshot(snap_dir, "2026-07-01", "b")
    bm = BaselineManager(str(tmp_path / "baselines"))

    assert bm.pin_from_snapshot(snap_dir, e1)["version"] == 1
    assert bm.pin_from_snapshot(snap_dir, e2)["version"] == 2
    # Chốt lại cùng ngày vẫn ra version mới, id khác nhau
    third = bm.pin_from_snapshot(snap_dir, e1)
    assert third["version"] == 3
    assert third["id"] == "2026-06-01_v3"
    assert len(bm.list_baselines()) == 3


def test_pin_missing_pickle_returns_none(tmp_path):
    snap_dir = str(tmp_path / "snapshots")
    os.makedirs(snap_dir)
    bm = BaselineManager(str(tmp_path / "baselines"))
    entry = {"date": "2026-06-01", "filename": "x.xlsx", "pickle": "khong-ton-tai.pkl"}
    assert bm.pin_from_snapshot(snap_dir, entry) is None
    assert bm.list_baselines() == []


def test_prune_snapshots_does_not_lose_baseline(tmp_path):
    """Cap snapshot = 3: bản cũ bị prune nhưng baseline vẫn load được."""
    snap_dir = str(tmp_path / "snapshots")
    smgr = SnapshotManager(snap_dir, max_snapshots=3)
    bm = BaselineManager(str(tmp_path / "baselines"))

    entry = _make_snapshot(snap_dir, "2026-01-01", "goc")
    pinned = bm.pin_from_snapshot(snap_dir, entry, label="Bản gốc")
    # Nhồi index vượt cap rồi prune
    index = [entry] + [
        _make_snapshot(snap_dir, f"2026-0{m}-01", f"s{m}") for m in range(2, 7)
    ]
    smgr._save_index(index)
    kept = {e["date"] for e in smgr.list_snapshots()}
    assert "2026-01-01" not in kept  # đã bị prune khỏi index

    loaded = bm.load_baseline(pinned["id"])
    assert loaded is not None
    assert loaded["parsed"] == {"tag": "goc"}


def test_same_day_overwrite_keeps_baseline_content_and_flags_drift(tmp_path):
    snap_dir = str(tmp_path / "snapshots")
    entry = _make_snapshot(snap_dir, "2026-06-01", "ban-da-chot")
    bm = BaselineManager(str(tmp_path / "baselines"))
    pinned = bm.pin_from_snapshot(snap_dir, entry)
    assert pinned["source_drifted"] is False

    # Upload lần 2 trong ngày → ghi đè pickle của snapshot gốc
    with open(os.path.join(snap_dir, entry["pickle"]), "wb") as f:
        pickle.dump(_fake_parsed("noi-dung-moi"), f)

    items = bm.refresh_source_drift(snap_dir, [entry])
    assert items[0]["source_drifted"] is True
    # Nội dung baseline KHÔNG đổi
    assert bm.load_baseline(pinned["id"])["parsed"] == {"tag": "ban-da-chot"}

    # Ghi lại đúng nội dung cũ → cờ tự tắt
    with open(os.path.join(snap_dir, entry["pickle"]), "wb") as f:
        pickle.dump(_fake_parsed("ban-da-chot"), f)
    assert bm.refresh_source_drift(snap_dir, [entry])[0]["source_drifted"] is False


def test_delete_removes_entry_and_files(tmp_path):
    snap_dir = str(tmp_path / "snapshots")
    entry = _make_snapshot(snap_dir, "2026-06-01", "x")
    bm = BaselineManager(str(tmp_path / "baselines"))
    pinned = bm.pin_from_snapshot(snap_dir, entry)

    assert bm.delete(pinned["id"]) is True
    assert bm.list_baselines() == []
    assert not os.path.isfile(str(tmp_path / "baselines" / pinned["pickle"]))
    assert bm.delete(pinned["id"]) is False


# ------------------------------------------------------------------
# resolve_latest — "baseline gần nhất"
# ------------------------------------------------------------------

def test_resolve_latest_respects_as_of(tmp_path):
    snap_dir = str(tmp_path / "snapshots")
    bm = BaselineManager(str(tmp_path / "baselines"))
    bm.pin_from_snapshot(snap_dir, _make_snapshot(snap_dir, "2026-03-01", "a"))
    bm.pin_from_snapshot(snap_dir, _make_snapshot(snap_dir, "2026-06-01", "b"))

    assert bm.resolve_latest(None)["snapshot_date"] == "2026-06-01"
    assert bm.resolve_latest(date(2026, 5, 1))["snapshot_date"] == "2026-03-01"
    assert bm.resolve_latest(date(2026, 6, 1))["snapshot_date"] == "2026-06-01"
    assert bm.resolve_latest(date(2026, 1, 1)) is None


def test_latest_baseline_ties_break_by_version():
    entries = [
        {"id": "d_v1", "snapshot_date": "2026-06-01", "version": 1},
        {"id": "d_v4", "snapshot_date": "2026-06-01", "version": 4},
    ]
    assert latest_baseline(entries, None)["id"] == "d_v4"
    assert latest_baseline([], None) is None
    # Entry ngày rác bị bỏ qua thay vì làm crash
    assert latest_baseline([{"snapshot_date": "khong-phai-ngay"}], None) is None


# ------------------------------------------------------------------
# API + migration từ field cũ
# ------------------------------------------------------------------

def _upload(client, xlsx_path, project="default"):
    with open(xlsx_path, "rb") as f:
        data = {"file": (io.BytesIO(f.read()), "test.xlsx")}
    return client.post(
        f"/api/projects/{project}/upload", data=data,
        content_type="multipart/form-data",
    )


def test_api_baselines_crud(flask_client, sample_xlsx_path):
    assert _upload(flask_client, sample_xlsx_path).status_code == 200

    r = flask_client.get("/api/projects/default/baselines")
    assert r.status_code == 200
    assert r.get_json()["items"] == []

    r = flask_client.post("/api/projects/default/baselines", json={"label": "Kế hoạch gốc"})
    assert r.status_code == 200, r.get_data(as_text=True)
    created = r.get_json()["baseline"]
    assert created["version"] == 1
    assert created["label"] == "Kế hoạch gốc"

    r = flask_client.get("/api/projects/default/baselines")
    body = r.get_json()
    assert len(body["items"]) == 1
    assert body["active"]["id"] == created["id"]
    # Con trỏ legacy được đồng bộ để 8 endpoint cũ vẫn thấy baseline
    assert body["legacy_snapshot_id"] == created["snapshot_date"]

    r = flask_client.delete(f"/api/projects/default/baselines/{created['id']}")
    assert r.status_code == 200
    assert r.get_json()["items"] == []
    assert flask_client.get("/api/projects/default/baselines").get_json()["active"] is None


def test_api_pin_unknown_snapshot_date_rejected(flask_client, sample_xlsx_path):
    _upload(flask_client, sample_xlsx_path)
    r = flask_client.post(
        "/api/projects/default/baselines", json={"snapshot_date": "1999-01-01"},
    )
    assert r.status_code == 400
    assert "không tìm thấy" in r.get_json()["error"].lower()


def test_legacy_baseline_field_migrates_into_chain(flask_client, sample_xlsx_path):
    """Project cũ chỉ có baseline_snapshot_id → tự pin vào chain khi đọc."""
    from analyzer import project_store as ps
    import app as app_module

    _upload(flask_client, sample_xlsx_path)
    snaps = app_module._project_mgr.get_snapshot_manager("default").list_snapshots()
    snap_date = snaps[0]["date"]
    folder = app_module._project_mgr.get_project_folder("default")
    ps.save_project_settings(folder, {"baseline_snapshot_id": snap_date})

    r = flask_client.get("/api/projects/default/baselines")
    items = r.get_json()["items"]
    assert len(items) == 1
    assert items[0]["snapshot_date"] == snap_date
    assert items[0]["created_by"] == "system"

    # Resolver ưu tiên chain và trả về đúng bản đã migrate
    baseline, resolved_date, entry = app_module._resolve_project_baseline("default")
    assert baseline is not None
    assert resolved_date == snap_date
    assert entry is not None


def test_resolver_falls_back_to_legacy_when_chain_empty(flask_client, sample_xlsx_path, monkeypatch):
    """Không migrate được (pin lỗi) thì vẫn đọc được baseline theo đường cũ."""
    import app as app_module
    from analyzer import project_store as ps
    from analyzer.baseline_manager import BaselineManager

    _upload(flask_client, sample_xlsx_path)
    snap_date = app_module._project_mgr.get_snapshot_manager("default").list_snapshots()[0]["date"]
    ps.save_project_settings(
        app_module._project_mgr.get_project_folder("default"),
        {"baseline_snapshot_id": snap_date},
    )
    monkeypatch.setattr(BaselineManager, "pin_from_snapshot", lambda *a, **k: None)

    baseline, resolved_date, entry = app_module._resolve_project_baseline("default")
    assert baseline is not None
    assert resolved_date == snap_date
    assert entry is None  # đọc từ snapshots/, không phải từ chain
