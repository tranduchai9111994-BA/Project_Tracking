"""Disk janitor — prune synced_*.xlsx + dedupe PM weekly PPTX."""
from __future__ import annotations

import os
import time
from pathlib import Path

from analyzer.disk_janitor import (
    MAX_SYNCED_XLSX,
    purge_duplicate_pm_weekly,
    purge_excess_synced_xlsx,
)
from analyzer import pm_store


def test_purge_excess_synced_keeps_newest(tmp_path: Path):
    """keep=N → chỉ còn N file mới nhất; current.xlsx không bị đụng."""
    d = tmp_path / "proj"
    d.mkdir()
    (d / "current.xlsx").write_bytes(b"current")
    paths = []
    for i in range(8):
        p = d / f"synced_20260730_{i:04d}.xlsx"
        p.write_bytes(b"x" * (i + 1))
        # Đảm bảo mtime tăng dần
        os.utime(p, (time.time() + i, time.time() + i))
        paths.append(p)

    deleted = purge_excess_synced_xlsx(str(d), keep=5)
    assert deleted == 3
    remaining = sorted(p.name for p in d.glob("synced_*.xlsx"))
    assert len(remaining) == 5
    assert remaining == [f"synced_20260730_{i:04d}.xlsx" for i in range(3, 8)]
    assert (d / "current.xlsx").is_file()
    assert MAX_SYNCED_XLSX == 5


def test_purge_synced_default_keep(tmp_path: Path):
    d = tmp_path / "proj"
    d.mkdir()
    for i in range(7):
        p = d / f"synced_mphg_20260731_{i:04d}.xlsx"
        p.write_bytes(b"y")
        os.utime(p, (time.time() + i, time.time() + i))
    assert purge_excess_synced_xlsx(str(d)) == 2
    assert len(list(d.glob("synced_*.xlsx"))) == MAX_SYNCED_XLSX


def test_purge_duplicate_pm_weekly(tmp_path: Path):
    """Có weekly.pptx + bản tên dài → chỉ giữ canonical."""
    pm = tmp_path / "proj" / "pm"
    pm.mkdir(parents=True)
    (pm / "weekly.pptx").write_bytes(b"canonical")
    long_name = "MPHG_iHRP_2025_PM_Weekly_Report_15.12.2025.pptx"
    (pm / long_name).write_bytes(b"canonical")
    (pm / "other_notes.pptx").write_bytes(b"keep-me")  # không chứa weekly

    deleted = purge_duplicate_pm_weekly(str(tmp_path / "proj"))
    assert deleted == 1
    assert (pm / "weekly.pptx").is_file()
    assert not (pm / long_name).exists()
    assert (pm / "other_notes.pptx").is_file()


def test_save_weekly_dedupes_long_named_source(tmp_path: Path):
    """Hydrate/save từ file tên dài → copy weekly.pptx rồi xóa bản dài."""
    project_dir = tmp_path / "proj"
    pm = project_dir / "pm"
    pm.mkdir(parents=True)
    long_name = "MPHG_Weekly_Report_demo.pptx"
    src = pm / long_name
    src.write_bytes(b"pptx-bytes")

    saved = pm_store.save_weekly(
        str(project_dir),
        {"done": [], "next": [], "summary": {}},
        source_filename=long_name,
        source_path=str(src),
    )
    assert saved["source_filename"] == long_name
    assert (pm / "weekly.pptx").is_file()
    assert (pm / "weekly.pptx").read_bytes() == b"pptx-bytes"
    assert not src.exists()
    assert (pm / "weekly.json").is_file()
