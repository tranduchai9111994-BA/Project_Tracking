"""Phase F — SQLite foundation (meta.db: settings / bookmarks / tags)."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from analyzer import project_store as ps
from analyzer import sqlite_store as sql


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_wal_mode_and_schema(tmp_path: Path):
    d = str(tmp_path / "proj")
    os.makedirs(d)
    assert sql.migrate_from_json_if_needed(d) is True
    conn = sql.connect(d)
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert str(mode).lower() == "wal"
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "project_settings" in tables
        assert "bookmarks" in tables
        assert "function_tags" in tables
        assert "schema_meta" in tables
    finally:
        conn.close()


def test_one_time_import_from_json(tmp_path: Path):
    d = str(tmp_path / "proj")
    os.makedirs(d)
    _write_json(
        Path(d) / "project_settings.json",
        {"baseline_snapshot_id": "2026-07-01", "upload_reminder_days": 14},
    )
    _write_json(Path(d) / "bookmarks.json", {"functions": ["A.01", "B.02", "A.01"]})
    _write_json(
        Path(d) / "tags.json",
        {"functions": {"A.01": ["UAT issue", "đã review"], "B.02": ["CR"]}},
    )

    assert sql.migrate_from_json_if_needed(d) is True
    assert sql.is_available(d) is True

    settings = sql.load_settings_raw(d)
    assert settings["baseline_snapshot_id"] == "2026-07-01"
    assert settings["upload_reminder_days"] == 14
    assert sql.load_bookmarks(d) == ["A.01", "B.02"]
    tags = sql.load_function_tags(d)
    assert tags["A.01"] == ["UAT issue", "đã review"] or set(tags["A.01"]) == {
        "UAT issue",
        "đã review",
    }
    assert sql.query_ma_cns_by_tag(d, "CR") == ["B.02"]
    assert sql.query_ma_cns_by_tag(d, "UAT issue") == ["A.01"]

    # Second call is no-op (marker already set) — even if JSON changes
    _write_json(Path(d) / "bookmarks.json", {"functions": ["Z.99"]})
    assert sql.migrate_from_json_if_needed(d) is True
    assert sql.load_bookmarks(d) == ["A.01", "B.02"]


def test_project_store_dual_write_and_read(tmp_path: Path):
    d = str(tmp_path / "proj")
    os.makedirs(d)

    s = ps.save_project_settings(
        d, {"baseline_snapshot_id": "2026-07-15", "max_snapshots": 12}
    )
    assert s["baseline_snapshot_id"] == "2026-07-15"
    assert s["max_snapshots"] == 12

    # JSON mirror còn
    raw = json.loads((Path(d) / "project_settings.json").read_text(encoding="utf-8"))
    assert raw["baseline_snapshot_id"] == "2026-07-15"
    assert (Path(d) / "meta.db").is_file()

    again = ps.load_project_settings(d)
    assert again["baseline_snapshot_id"] == "2026-07-15"
    assert again["max_snapshots"] == 12

    ps.save_bookmarks(d, ["X.1", "X.2"])
    assert ps.load_bookmarks(d) == ["X.1", "X.2"]
    is_now, all_bm = ps.toggle_bookmark(d, "X.1")
    assert is_now is False
    assert all_bm == ["X.2"]

    ps.save_function_tags(d, {"X.2": ["escalate", "UAT issue"]})
    assert set(ps.load_function_tags(d)["X.2"]) == {"escalate", "UAT issue"}
    assert sql.query_ma_cns_by_tag(d, "escalate") == ["X.2"]


def test_fallback_when_db_missing(tmp_path: Path):
    """Xoá meta.db → đọc lại từ JSON (re-import hoặc fallback)."""
    d = str(tmp_path / "proj")
    os.makedirs(d)
    ps.save_project_settings(d, {"baseline_snapshot_id": "2026-06-01"})
    ps.save_bookmarks(d, ["F.01"])
    ps.save_function_tags(d, {"F.01": ["CR"]})

    # Xoá DB (+ WAL sidecars)
    for name in ("meta.db", "meta.db-wal", "meta.db-shm"):
        p = Path(d) / name
        if p.exists():
            p.unlink()

    assert ps.load_project_settings(d)["baseline_snapshot_id"] == "2026-06-01"
    assert ps.load_bookmarks(d) == ["F.01"]
    assert ps.load_function_tags(d)["F.01"] == ["CR"]
    # Self-heal: meta.db được tạo lại từ JSON
    assert (Path(d) / "meta.db").is_file()


def test_fallback_when_db_corrupt(tmp_path: Path):
    d = str(tmp_path / "proj")
    os.makedirs(d)
    _write_json(
        Path(d) / "project_settings.json",
        {"baseline_snapshot_id": "2026-05-01", "upload_reminder_days": 9},
    )
    _write_json(Path(d) / "bookmarks.json", {"functions": ["OK.1"]})
    # File giả DB
    (Path(d) / "meta.db").write_bytes(b"not a sqlite database")

    # load qua project_store không ném exception
    s = ps.load_project_settings(d)
    assert s["baseline_snapshot_id"] == "2026-05-01"
    assert s["upload_reminder_days"] == 9
    assert ps.load_bookmarks(d) == ["OK.1"]


def test_bookmark_replace_is_transactional(tmp_path: Path):
    d = str(tmp_path / "proj")
    os.makedirs(d)
    assert sql.save_bookmarks(d, ["A", "B", "C"]) is True
    assert sql.load_bookmarks(d) == ["A", "B", "C"]
    assert sql.save_bookmarks(d, ["D"]) is True
    assert sql.load_bookmarks(d) == ["D"]


def test_settings_roundtrip_via_sql_only(tmp_path: Path):
    d = str(tmp_path / "proj")
    os.makedirs(d)
    payload = {
        "upload_reminder_days": 11,
        "baseline_snapshot_id": "2026-07-20",
        "sla": {"must_have_days": 4, "should_have_days": 8},
    }
    assert sql.save_settings_raw(d, payload) is True
    loaded = sql.load_settings_raw(d)
    assert loaded["baseline_snapshot_id"] == "2026-07-20"
    assert loaded["upload_reminder_days"] == 11
