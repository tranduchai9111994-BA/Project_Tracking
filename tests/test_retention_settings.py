"""U27 — retention snapshot/history configurable via project settings."""
from datetime import date, timedelta

from analyzer import project_store as ps
from analyzer.snapshot_manager import SnapshotManager


def test_settings_max_snapshots_roundtrip(tmp_path):
    d = str(tmp_path)
    s = ps.save_project_settings(d, {"max_snapshots": 15})
    assert s["max_snapshots"] == 15
    # UI 1 ô → đồng bộ history
    assert s["max_upload_history"] == 15
    again = ps.load_project_settings(d)
    assert again["max_snapshots"] == 15


def test_append_history_respects_settings_cap(tmp_path):
    d = str(tmp_path)
    ps.save_project_settings(d, {"max_upload_history": 5})
    for i in range(10):
        ps.append_upload_history(d, filename=f"f{i}.xlsx", row_count=i)
    hist = ps.load_upload_history(d)
    assert len(hist) == 5
    assert hist[0]["filename"] == "f9.xlsx"


def test_snapshot_manager_respects_override(tmp_path):
    """Constructor override max_snapshots=3 → prune về 3."""
    snap_dir = tmp_path / "snapshots"
    snap_dir.mkdir()
    mgr = SnapshotManager(str(snap_dir), max_snapshots=3)
    today = date(2026, 3, 1)
    index = []
    for i in range(6):
        d = (today - timedelta(days=i)).isoformat()
        index.append({
            "date": d, "filename": f"{d}_functionlist.xlsx",
            "pickle": f"{d}_functionlist.parsed.pkl",
            "total_functions": 1, "source": "upload",
        })
    kept = mgr._prune_overflow(index, persist=False)
    assert len(kept) == 3
