"""Tests — resolver mốc so sánh (analyzer/compare_base.py)."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from analyzer.compare_base import (
    DEFAULT_MODE,
    WEEK_LOOKBACK_DAYS,
    normalize_mode,
    resolve_compare_base,
)


TODAY = date(2026, 8, 5)

# Sort giảm dần theo ngày, giống SnapshotManager.list_snapshots()
SNAPS = [
    {"date": "2026-08-05", "upload_time": "2026-08-05T09:00:00"},
    {"date": "2026-08-03", "upload_time": "2026-08-03T09:00:00"},
    {"date": "2026-07-20", "upload_time": "2026-07-20T09:00:00"},
]

BASELINES = [
    {"id": "2026-07-01_v2", "version": 2, "snapshot_date": "2026-07-01", "label": "Approved 07"},
    {"id": "2026-05-01_v1", "version": 1, "snapshot_date": "2026-05-01", "label": ""},
]


def test_mode_baseline_picks_latest_and_labels_version():
    r = resolve_compare_base(SNAPS, BASELINES, mode="baseline", today=TODAY)
    assert r["error"] == ""
    assert r["source"] == "baseline"
    assert r["id"] == "2026-07-01_v2"
    assert r["snapshot_date"] == "2026-07-01"
    assert r["label"] == "Baseline v2 — Approved 07 · 01/07/2026"


def test_mode_baseline_without_baseline_returns_vietnamese_error():
    r = resolve_compare_base(SNAPS, [], mode="baseline", today=TODAY)
    assert r["source"] == ""
    assert r["id"] == ""
    assert "Chốt baseline" in r["error"]


def test_mode_week_falls_back_to_nearest_older_snapshot():
    """Không có snapshot đúng today-7 → lùi tiếp về bản gần nhất trước đó."""
    r = resolve_compare_base(SNAPS, BASELINES, mode="week", today=TODAY)
    assert r["snapshot_date"] == "2026-07-20"
    assert r["source"] == "snapshot"
    assert r["label"] == "Tuần trước · 20/07/2026"


def test_mode_week_includes_exact_cutoff_day():
    cutoff = (TODAY - timedelta(days=WEEK_LOOKBACK_DAYS)).isoformat()
    r = resolve_compare_base(
        [{"date": "2026-08-05"}, {"date": cutoff}], [], mode="week", today=TODAY,
    )
    assert r["snapshot_date"] == cutoff == "2026-07-29"


def test_mode_week_without_old_snapshot_errors():
    r = resolve_compare_base(
        [{"date": "2026-08-05"}, {"date": "2026-08-04"}], [], mode="week", today=TODAY,
    )
    assert r["source"] == ""
    assert "7 ngày trước" in r["error"]
    assert "29/07/2026" in r["error"]


def test_mode_previous_uses_second_snapshot():
    r = resolve_compare_base(SNAPS, [], mode="previous", today=TODAY)
    assert r["snapshot_date"] == "2026-08-03"
    assert r["label"] == "Bản trước · 03/08/2026"


def test_mode_previous_with_single_snapshot_errors():
    r = resolve_compare_base([{"date": "2026-08-05"}], [], mode="previous", today=TODAY)
    assert "1 bản" in r["error"]


def test_mode_date_exact_and_missing():
    ok = resolve_compare_base(SNAPS, [], mode="date", explicit_date="2026-07-20", today=TODAY)
    assert ok["snapshot_date"] == "2026-07-20"
    assert ok["label"] == "Bản 20/07/2026"

    missing = resolve_compare_base(SNAPS, [], mode="date", explicit_date="2026-01-01", today=TODAY)
    assert "01/01/2026" in missing["error"]

    blank = resolve_compare_base(SNAPS, [], mode="date", explicit_date="", today=TODAY)
    assert "Chưa chọn bản" in blank["error"]


def test_mode_off_returns_empty_without_error():
    r = resolve_compare_base(SNAPS, BASELINES, mode="off", today=TODAY)
    assert r["mode"] == "off"
    assert r["source"] == ""
    assert r["error"] == ""


def test_baseline_after_as_of_is_ignored():
    """Baseline chốt ở tương lai không được chọn làm mốc cho hôm nay."""
    future = [{"id": "2027-01-01_v9", "version": 9, "snapshot_date": "2027-01-01"}]
    r = resolve_compare_base(SNAPS, future, mode="baseline", today=TODAY)
    assert r["source"] == ""
    assert r["error"] != ""


def test_normalize_mode():
    assert normalize_mode("week") == "week"
    assert normalize_mode("WEEK") == "week"
    assert normalize_mode("  date ") == "date"
    assert normalize_mode(None, has_baseline=True) == DEFAULT_MODE
    assert normalize_mode("rác", has_baseline=False) == "previous"


def test_invalid_mode_falls_back_to_default():
    r = resolve_compare_base(SNAPS, BASELINES, mode="tùm-lum", today=TODAY)
    assert r["mode"] == DEFAULT_MODE
    assert r["source"] == "baseline"
