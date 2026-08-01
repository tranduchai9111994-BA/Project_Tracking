"""
SQLite foundation (Phase F) — project meta slice.

Intermediate step: transaction-safe + queryable store for lightweight
project metadata. Parsed Function List pickle / dashboard metrics stay
file-based.

DB path (per project):
  uploads/projects/<slug>/meta.db

Schema (v1 — slice_meta):
  schema_meta(key, value)          — migration markers / version
  project_settings(id=1, payload_json, updated_at)
                                   — full settings blob (incl. baseline_snapshot_id)
  bookmarks(ma_cn PK, position, created_at)
  function_tags(ma_cn, tag) PK     — queryable by tag

Migration / fallback:
  · One-time import from project_settings.json / bookmarks.json / tags.json
  · Dual-write: app writes keep JSON mirror (backup + legacy tools)
  · If meta.db missing/unreadable → callers fall back to JSON

Concurrency: WAL + busy_timeout; short transactions via ``with conn:``.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from typing import Any, Optional

DB_FILENAME = "meta.db"
SCHEMA_VERSION = "1"
SLICE_MARKER = "slice_meta_v1"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_settings (
  id           INTEGER PRIMARY KEY CHECK (id = 1),
  payload_json TEXT    NOT NULL,
  updated_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS bookmarks (
  ma_cn      TEXT    PRIMARY KEY,
  position   INTEGER NOT NULL DEFAULT 0,
  created_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS function_tags (
  ma_cn TEXT NOT NULL,
  tag   TEXT NOT NULL,
  PRIMARY KEY (ma_cn, tag)
);

CREATE INDEX IF NOT EXISTS idx_function_tags_tag ON function_tags(tag);
CREATE INDEX IF NOT EXISTS idx_function_tags_ma  ON function_tags(ma_cn);
"""


def db_path(project_dir: str) -> str:
    return os.path.join(project_dir, DB_FILENAME)


def connect(project_dir: str) -> sqlite3.Connection:
    """Open meta.db with WAL + short busy wait. Caller must close."""
    os.makedirs(project_dir or ".", exist_ok=True)
    path = db_path(project_dir)
    # Default isolation (DEFERRED) + ``with conn:`` = short explicit transactions.
    conn = sqlite3.connect(path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()
    if not row:
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES ('schema_version', ?)",
            (SCHEMA_VERSION,),
        )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read_json_file(path: str, default: Any) -> Any:
    if not os.path.isfile(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def _marker_set(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key = ?", (SLICE_MARKER,)
    ).fetchone()
    return bool(row and row["value"] == "1")


def _set_marker(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO schema_meta(key, value) VALUES (?, '1') "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (SLICE_MARKER,),
    )


def migrate_from_json_if_needed(project_dir: str) -> bool:
    """
    One-time import JSON → SQLite when marker absent.
    Returns True if import ran (or already migrated).
    """
    try:
        conn = connect(project_dir)
    except (OSError, sqlite3.Error):
        return False
    try:
        ensure_schema(conn)
        if _marker_set(conn):
            return True
        with conn:
            # Settings
            raw = _read_json_file(
                os.path.join(project_dir, "project_settings.json"), {}
            )
            if isinstance(raw, dict) and raw:
                conn.execute(
                    "INSERT INTO project_settings(id, payload_json, updated_at) "
                    "VALUES (1, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET "
                    "payload_json = excluded.payload_json, "
                    "updated_at = excluded.updated_at",
                    (json.dumps(raw, ensure_ascii=False), _now()),
                )
            # Bookmarks
            bm_raw = _read_json_file(
                os.path.join(project_dir, "bookmarks.json"), {"functions": []}
            )
            funcs = []
            if isinstance(bm_raw, dict):
                funcs = bm_raw.get("functions") or []
            elif isinstance(bm_raw, list):
                funcs = bm_raw
            conn.execute("DELETE FROM bookmarks")
            seen: set[str] = set()
            pos = 0
            for f in funcs:
                s = str(f).strip()
                if not s or s in seen:
                    continue
                seen.add(s)
                conn.execute(
                    "INSERT INTO bookmarks(ma_cn, position, created_at) "
                    "VALUES (?, ?, ?)",
                    (s, pos, _now()),
                )
                pos += 1
            # Tags
            tags_raw = _read_json_file(
                os.path.join(project_dir, "tags.json"), {"functions": {}}
            )
            fmap: dict = {}
            if isinstance(tags_raw, dict):
                fmap = tags_raw.get("functions") or {}
            conn.execute("DELETE FROM function_tags")
            if isinstance(fmap, dict):
                for ma, tags in fmap.items():
                    ma_s = str(ma).strip()
                    if not ma_s or not isinstance(tags, list):
                        continue
                    seen_t: set[str] = set()
                    for t in tags:
                        ts = str(t).strip()
                        if not ts or ts in seen_t:
                            continue
                        seen_t.add(ts)
                        conn.execute(
                            "INSERT INTO function_tags(ma_cn, tag) VALUES (?, ?)",
                            (ma_s, ts),
                        )
            _set_marker(conn)
        return True
    except (OSError, sqlite3.Error, TypeError, ValueError):
        return False
    finally:
        conn.close()


# ------------------------------------------------------------------
# Settings
# ------------------------------------------------------------------

def load_settings_raw(project_dir: str) -> Optional[dict[str, Any]]:
    """Return settings dict from SQLite, or None if unavailable / empty."""
    if not migrate_from_json_if_needed(project_dir):
        return None
    try:
        conn = connect(project_dir)
    except (OSError, sqlite3.Error):
        return None
    try:
        ensure_schema(conn)
        row = conn.execute(
            "SELECT payload_json FROM project_settings WHERE id = 1"
        ).fetchone()
        if not row:
            return None
        data = json.loads(row["payload_json"])
        return data if isinstance(data, dict) else None
    except (OSError, sqlite3.Error, json.JSONDecodeError, TypeError):
        return None
    finally:
        conn.close()


def save_settings_raw(project_dir: str, payload: dict[str, Any]) -> bool:
    """Persist full settings blob. Returns False on failure."""
    try:
        conn = connect(project_dir)
    except (OSError, sqlite3.Error):
        return False
    try:
        ensure_schema(conn)
        blob = json.dumps(payload, ensure_ascii=False)
        with conn:
            conn.execute(
                "INSERT INTO project_settings(id, payload_json, updated_at) "
                "VALUES (1, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "payload_json = excluded.payload_json, "
                "updated_at = excluded.updated_at",
                (blob, _now()),
            )
            _set_marker(conn)
        return True
    except (OSError, sqlite3.Error, TypeError):
        return False
    finally:
        conn.close()


# ------------------------------------------------------------------
# Bookmarks
# ------------------------------------------------------------------

def load_bookmarks(project_dir: str) -> Optional[list[str]]:
    """Ordered bookmark list, or None if DB unavailable."""
    if not migrate_from_json_if_needed(project_dir):
        return None
    try:
        conn = connect(project_dir)
    except (OSError, sqlite3.Error):
        return None
    try:
        ensure_schema(conn)
        rows = conn.execute(
            "SELECT ma_cn FROM bookmarks ORDER BY position ASC, ma_cn ASC"
        ).fetchall()
        return [str(r["ma_cn"]) for r in rows]
    except (OSError, sqlite3.Error):
        return None
    finally:
        conn.close()


def save_bookmarks(project_dir: str, ma_cns: list[str]) -> bool:
    try:
        conn = connect(project_dir)
    except (OSError, sqlite3.Error):
        return False
    try:
        ensure_schema(conn)
        cleaned: list[str] = []
        seen: set[str] = set()
        for m in ma_cns or []:
            s = str(m).strip()
            if s and s not in seen:
                seen.add(s)
                cleaned.append(s)
        with conn:
            conn.execute("DELETE FROM bookmarks")
            now = _now()
            for i, s in enumerate(cleaned):
                conn.execute(
                    "INSERT INTO bookmarks(ma_cn, position, created_at) "
                    "VALUES (?, ?, ?)",
                    (s, i, now),
                )
            _set_marker(conn)
        return True
    except (OSError, sqlite3.Error):
        return False
    finally:
        conn.close()


# ------------------------------------------------------------------
# Function tags
# ------------------------------------------------------------------

def load_function_tags(project_dir: str) -> Optional[dict[str, list[str]]]:
    """{ma_cn: [tags…]} or None if DB unavailable."""
    if not migrate_from_json_if_needed(project_dir):
        return None
    try:
        conn = connect(project_dir)
    except (OSError, sqlite3.Error):
        return None
    try:
        ensure_schema(conn)
        rows = conn.execute(
            "SELECT ma_cn, tag FROM function_tags ORDER BY ma_cn, tag"
        ).fetchall()
        out: dict[str, list[str]] = {}
        for r in rows:
            ma = str(r["ma_cn"])
            out.setdefault(ma, []).append(str(r["tag"]))
        return out
    except (OSError, sqlite3.Error):
        return None
    finally:
        conn.close()


def save_function_tags(project_dir: str, tags_map: dict[str, list[str]]) -> bool:
    try:
        conn = connect(project_dir)
    except (OSError, sqlite3.Error):
        return False
    try:
        ensure_schema(conn)
        with conn:
            conn.execute("DELETE FROM function_tags")
            for ma, tags in (tags_map or {}).items():
                ma_s = str(ma).strip()
                if not ma_s:
                    continue
                seen: set[str] = set()
                for t in tags or []:
                    ts = str(t).strip()
                    if not ts or ts in seen:
                        continue
                    seen.add(ts)
                    conn.execute(
                        "INSERT INTO function_tags(ma_cn, tag) VALUES (?, ?)",
                        (ma_s, ts),
                    )
            _set_marker(conn)
        return True
    except (OSError, sqlite3.Error):
        return False
    finally:
        conn.close()


def query_ma_cns_by_tag(project_dir: str, tag: str) -> Optional[list[str]]:
    """Queryable slice demo: list Mã CN having ``tag`` (sorted)."""
    tag = str(tag or "").strip()
    if not tag:
        return []
    if not migrate_from_json_if_needed(project_dir):
        return None
    try:
        conn = connect(project_dir)
    except (OSError, sqlite3.Error):
        return None
    try:
        ensure_schema(conn)
        rows = conn.execute(
            "SELECT DISTINCT ma_cn FROM function_tags WHERE tag = ? "
            "ORDER BY ma_cn",
            (tag,),
        ).fetchall()
        return [str(r["ma_cn"]) for r in rows]
    except (OSError, sqlite3.Error):
        return None
    finally:
        conn.close()


def is_available(project_dir: str) -> bool:
    """True if meta.db exists and schema marker is set."""
    path = db_path(project_dir)
    if not os.path.isfile(path):
        return False
    try:
        conn = connect(project_dir)
    except (OSError, sqlite3.Error):
        return False
    try:
        ensure_schema(conn)
        return _marker_set(conn)
    except (OSError, sqlite3.Error):
        return False
    finally:
        conn.close()
