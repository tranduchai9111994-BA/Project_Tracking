"""
T-AA — Auto-archive snapshots cũ để giải phóng dung lượng đĩa.

Quy trình archive:
  1. Gzip (level 6) file .xlsx + .pkl → snapshots/archive/
  2. Xóa bản hot (không gzip) sau khi verify checksum
  3. Đánh dấu archived=True trong snapshot_index.json

Restore (rã đông): extract lại về snapshots/, unset archived.

Load transparent: SnapshotManager.load_snapshot đọc trực tiếp từ .gz
khi archived=True (không extract ra disk).
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
from datetime import date, datetime, timedelta
from typing import Any, Optional

from analyzer.snapshot_manager import INDEX_FILE, PICKLE_SUFFIX

ARCHIVE_SUBDIR = "archive"
GZIP_LEVEL = 6
DEFAULT_ARCHIVE_AFTER_DAYS = 90
DEFAULT_PURGE_AFTER_DAYS = 365


def _archive_dir(project_dir: str) -> str:
    """project_dir ở đây = snapshots/ folder (giống SnapshotManager.dir)."""
    path = os.path.join(project_dir, ARCHIVE_SUBDIR)
    os.makedirs(path, exist_ok=True)
    return path


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 64)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _gzip_file(src: str, dest_gz: str, level: int = GZIP_LEVEL) -> str:
    """Nén src → dest_gz, return sha256 của nội dung gốc."""
    checksum = _sha256_file(src)
    with open(src, "rb") as fin, gzip.open(dest_gz, "wb", compresslevel=level) as fout:
        shutil.copyfileobj(fin, fout, length=1024 * 64)
    return checksum


def _gunzip_to_file(src_gz: str, dest: str) -> str:
    """Giải nén src_gz → dest, return sha256 của nội dung giải nén."""
    with gzip.open(src_gz, "rb") as fin, open(dest, "wb") as fout:
        shutil.copyfileobj(fin, fout, length=1024 * 64)
    return _sha256_file(dest)


def _read_gzip_bytes(src_gz: str) -> bytes:
    with gzip.open(src_gz, "rb") as f:
        return f.read()


def _parse_entry_date(entry: dict) -> Optional[date]:
    """Parse date từ entry (field 'date' YYYY-MM-DD)."""
    raw = entry.get("date") or ""
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _load_index(snap_dir: str) -> list[dict]:
    path = os.path.join(snap_dir, INDEX_FILE)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _save_index(snap_dir: str, index: list[dict]) -> None:
    path = os.path.join(snap_dir, INDEX_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def _find_entry(index: list[dict], snapshot_id: str) -> Optional[dict]:
    for e in index:
        if e.get("date") == snapshot_id:
            return e
    return None


def archive_snapshot(project_dir: str, snapshot_id: str) -> dict:
    """
    Archive 1 snapshot (gzip + move sang archive/, mark archived).

    project_dir: path tới folder snapshots/ (SnapshotManager.dir).
    snapshot_id: YYYY-MM-DD.

    Return: entry đã cập nhật.
    Raise: ValueError nếu không tìm thấy / đã archived / file thiếu.
    """
    index = _load_index(project_dir)
    entry = _find_entry(index, snapshot_id)
    if not entry:
        raise ValueError(f"Không tìm thấy snapshot {snapshot_id}")
    if entry.get("archived"):
        return entry  # idempotent

    xlsx_name = entry.get("filename") or f"{snapshot_id}_functionlist.xlsx"
    pkl_name = entry.get("pickle") or f"{snapshot_id}_functionlist{PICKLE_SUFFIX}"
    xlsx_path = os.path.join(project_dir, xlsx_name)
    pkl_path = os.path.join(project_dir, pkl_name)
    if not os.path.isfile(xlsx_path) and not os.path.isfile(pkl_path):
        raise ValueError(f"Snapshot {snapshot_id} thiếu file hot (xlsx/pkl)")

    arch = _archive_dir(project_dir)
    checksums: dict[str, str] = {}

    if os.path.isfile(xlsx_path):
        dest = os.path.join(arch, xlsx_name + ".gz")
        checksums["xlsx"] = _gzip_file(xlsx_path, dest)
        # Verify: decompress in-memory và so hash
        verified = _sha256_bytes(_read_gzip_bytes(dest))
        if verified != checksums["xlsx"]:
            raise RuntimeError(f"Checksum xlsx không khớp sau archive ({snapshot_id})")

    if os.path.isfile(pkl_path):
        dest = os.path.join(arch, pkl_name + ".gz")
        checksums["pickle"] = _gzip_file(pkl_path, dest)
        verified = _sha256_bytes(_read_gzip_bytes(dest))
        if verified != checksums["pickle"]:
            raise RuntimeError(f"Checksum pickle không khớp sau archive ({snapshot_id})")

    # Xóa bản hot sau khi verify OK
    for p in (xlsx_path, pkl_path):
        if os.path.isfile(p):
            try:
                os.remove(p)
            except OSError:
                pass

    entry["archived"] = True
    entry["archived_at"] = datetime.now().isoformat(timespec="seconds")
    entry["archive_checksums"] = checksums
    # Cập nhật lại trong index
    for i, e in enumerate(index):
        if e.get("date") == snapshot_id:
            index[i] = entry
            break
    _save_index(project_dir, index)
    return entry


def restore_snapshot(project_dir: str, snapshot_id: str) -> dict:
    """
    Rã đông snapshot: extract từ archive/ về snapshots/, unset archived.
    """
    index = _load_index(project_dir)
    entry = _find_entry(index, snapshot_id)
    if not entry:
        raise ValueError(f"Không tìm thấy snapshot {snapshot_id}")
    if not entry.get("archived"):
        return entry  # đã hot

    xlsx_name = entry.get("filename") or f"{snapshot_id}_functionlist.xlsx"
    pkl_name = entry.get("pickle") or f"{snapshot_id}_functionlist{PICKLE_SUFFIX}"
    arch = _archive_dir(project_dir)
    expected = entry.get("archive_checksums") or {}

    xlsx_gz = os.path.join(arch, xlsx_name + ".gz")
    pkl_gz = os.path.join(arch, pkl_name + ".gz")
    if not os.path.isfile(xlsx_gz) and not os.path.isfile(pkl_gz):
        raise ValueError(f"Không tìm thấy file archive cho {snapshot_id}")

    if os.path.isfile(xlsx_gz):
        dest = os.path.join(project_dir, xlsx_name)
        got = _gunzip_to_file(xlsx_gz, dest)
        if expected.get("xlsx") and got != expected["xlsx"]:
            raise RuntimeError(f"Checksum xlsx không khớp khi restore ({snapshot_id})")

    if os.path.isfile(pkl_gz):
        dest = os.path.join(project_dir, pkl_name)
        got = _gunzip_to_file(pkl_gz, dest)
        if expected.get("pickle") and got != expected["pickle"]:
            raise RuntimeError(f"Checksum pickle không khớp khi restore ({snapshot_id})")

    # Xóa .gz sau restore thành công
    for p in (xlsx_gz, pkl_gz):
        if os.path.isfile(p):
            try:
                os.remove(p)
            except OSError:
                pass

    entry["archived"] = False
    entry.pop("archived_at", None)
    entry.pop("archive_checksums", None)
    for i, e in enumerate(index):
        if e.get("date") == snapshot_id:
            index[i] = entry
            break
    _save_index(project_dir, index)
    return entry


def auto_archive_project(
    project_dir: str,
    days: int = DEFAULT_ARCHIVE_AFTER_DAYS,
    *,
    today: Optional[date] = None,
) -> list[dict]:
    """
    Quét snapshot cũ hơn `days` ngày → archive.
    days <= 0 → không archive gì (return []).
    Return: list entry đã archive trong lần chạy này.
    """
    if days is None or days <= 0:
        return []
    ref = today or date.today()
    cutoff = ref - timedelta(days=int(days))
    processed: list[dict] = []
    for entry in list(_load_index(project_dir)):
        if entry.get("archived"):
            continue
        d = _parse_entry_date(entry)
        if d is None or d >= cutoff:
            continue
        try:
            updated = archive_snapshot(project_dir, entry["date"])
            processed.append(updated)
        except Exception:
            # Bỏ qua snapshot lỗi (file thiếu…) — không chặn batch
            continue
    return processed


def list_archived(project_dir: str) -> list[dict]:
    """Return danh sách snapshot đã archived (cho UI)."""
    return [e for e in _load_index(project_dir) if e.get("archived")]


def purge_archive(
    project_dir: str,
    days: int = DEFAULT_PURGE_AFTER_DAYS,
    *,
    today: Optional[date] = None,
) -> list[str]:
    """
    Xóa vĩnh viễn archive cũ hơn `days` ngày (destructive).
    days <= 0 → không xóa gì.
    Return: list snapshot_id đã purge.
    """
    if days is None or days <= 0:
        return []
    ref = today or date.today()
    cutoff = ref - timedelta(days=int(days))
    index = _load_index(project_dir)
    purged: list[str] = []
    keep: list[dict] = []
    arch = _archive_dir(project_dir)

    for entry in index:
        if not entry.get("archived"):
            keep.append(entry)
            continue
        # Ưu tiên archived_at; fallback date
        purge_date: Optional[date] = None
        raw_at = entry.get("archived_at") or ""
        if raw_at:
            try:
                purge_date = datetime.fromisoformat(raw_at[:19]).date()
            except ValueError:
                purge_date = None
        if purge_date is None:
            purge_date = _parse_entry_date(entry)
        if purge_date is None or purge_date >= cutoff:
            keep.append(entry)
            continue

        # Xóa file .gz
        xlsx_name = entry.get("filename") or f"{entry.get('date')}_functionlist.xlsx"
        pkl_name = entry.get("pickle") or f"{entry.get('date')}_functionlist{PICKLE_SUFFIX}"
        for name in (xlsx_name + ".gz", pkl_name + ".gz"):
            path = os.path.join(arch, name)
            if os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        purged.append(entry.get("date") or "")

    _save_index(project_dir, keep)
    return [p for p in purged if p]


def load_archived_pickle_bytes(project_dir: str, entry: dict) -> Optional[bytes]:
    """Đọc pickle đã gzip từ archive/ vào memory (transparent load)."""
    pkl_name = entry.get("pickle") or ""
    if not pkl_name:
        return None
    path = os.path.join(_archive_dir(project_dir), pkl_name + ".gz")
    if not os.path.isfile(path):
        return None
    try:
        return _read_gzip_bytes(path)
    except OSError:
        return None


def snapshot_disk_usage(project_dir: str) -> dict[str, Any]:
    """Thống kê dung lượng hot vs archived (bytes) — dùng cho UI."""
    hot = 0
    archived = 0
    for name in os.listdir(project_dir) if os.path.isdir(project_dir) else []:
        path = os.path.join(project_dir, name)
        if not os.path.isfile(path):
            continue
        if name.endswith(".gz"):
            continue
        try:
            hot += os.path.getsize(path)
        except OSError:
            pass
    arch = os.path.join(project_dir, ARCHIVE_SUBDIR)
    if os.path.isdir(arch):
        for name in os.listdir(arch):
            path = os.path.join(arch, name)
            if os.path.isfile(path):
                try:
                    archived += os.path.getsize(path)
                except OSError:
                    pass
    return {"hot_bytes": hot, "archived_bytes": archived, "total_bytes": hot + archived}
