"""
Snapshot Manager — Lưu và quản lý các snapshot của file Function List.

Mỗi lần upload, một bản copy file .xlsx được lưu vào `uploads/snapshots/`,
kèm theo file JSON index chứa metadata (tổng function, % done, overdue count...).

Cùng ngày upload nhiều lần → ghi đè snapshot của ngày đó.
Giới hạn 30 snapshot gần nhất, snapshot cũ hơn sẽ bị xóa.
"""
import json
import os
import pickle
import shutil
from datetime import date, datetime
from typing import Any, Optional

from parser.excel_parser import ParsedData


MAX_SNAPSHOTS = 30
INDEX_FILE = "snapshot_index.json"
PICKLE_SUFFIX = ".parsed.pkl"


class SnapshotManager:
    """Lưu, load, list, delete snapshots."""

    def __init__(self, snapshot_dir: str):
        self.dir = snapshot_dir
        os.makedirs(self.dir, exist_ok=True)
        self.index_path = os.path.join(self.dir, INDEX_FILE)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save_snapshot(
        self,
        source_xlsx: str,
        parsed_data: ParsedData,
        metrics: dict,
        source: str = "upload",
    ) -> dict:
        """
        Lưu 1 snapshot:
        - Copy file .xlsx vào snapshots/{date}_functionlist.xlsx
        - Serialize ParsedData vào snapshots/{date}_functionlist.parsed.pkl
        - Update snapshot_index.json
        - source: "upload" | "sync:<integ_id>:<endpoint_id>" (T35 Task 4)
        Return: entry đã lưu.
        """
        today_str = date.today().isoformat()  # YYYY-MM-DD
        xlsx_name = f"{today_str}_functionlist.xlsx"
        pkl_name = f"{today_str}_functionlist{PICKLE_SUFFIX}"
        xlsx_path = os.path.join(self.dir, xlsx_name)
        pkl_path = os.path.join(self.dir, pkl_name)

        # Copy file (ghi đè nếu cùng ngày)
        shutil.copy2(source_xlsx, xlsx_path)

        # Serialize ParsedData
        with open(pkl_path, "wb") as f:
            pickle.dump(parsed_data, f)

        summary = metrics.get("summary", {})
        src = (source or "upload").strip() or "upload"
        entry = {
            "date": today_str,
            "filename": xlsx_name,
            "pickle": pkl_name,
            "total_functions": summary.get("total_functions", 0),
            "overall_pct": summary.get("overall_progress_pct", 0),
            "overdue_count": summary.get("total_overdue", 0),
            "unassigned_count": summary.get("unassigned_count", 0),
            "high_risk_count": summary.get("high_risk_count", 0),
            "upload_time": datetime.now().isoformat(timespec="seconds"),
            "source": src,
        }

        # Update index
        index = self._load_index()
        # Xóa entry cũ cùng ngày (nếu có)
        index = [e for e in index if e["date"] != today_str]
        index.append(entry)
        # Sort giảm dần theo ngày
        index.sort(key=lambda x: x["date"], reverse=True)

        # Giới hạn số snapshot
        if len(index) > MAX_SNAPSHOTS:
            for old in index[MAX_SNAPSHOTS:]:
                self._delete_files(old)
            index = index[:MAX_SNAPSHOTS]

        self._save_index(index)
        return entry

    def list_snapshots(self) -> list[dict]:
        """Return list of snapshot metadata (sorted giảm dần theo ngày).

        Backward compat: entry cũ không có `source` → default \"upload\".
        Thêm field `archived` (bool) cho UI Hot/Archived badge.
        """
        out = []
        for e in self._load_index():
            entry = dict(e)
            if "source" not in entry or not entry.get("source"):
                entry["source"] = "upload"
            entry["archived"] = bool(entry.get("archived"))
            out.append(entry)
        return out

    def load_snapshot(self, snapshot_date: str) -> Optional[dict]:
        """
        Load 1 snapshot theo ngày (YYYY-MM-DD).
        Return: {"parsed": ParsedData, "meta": entry_dict} hoặc None.

        T-AA: nếu archived=True → decompress gzip pickle trong memory
        (không extract ra disk).
        """
        entry = self._find_entry(snapshot_date)
        if not entry:
            return None

        if entry.get("archived"):
            # Transparent decompress từ archive/
            try:
                from analyzer.archive_manager import load_archived_pickle_bytes
                import io
                raw = load_archived_pickle_bytes(self.dir, entry)
                if raw is None:
                    return None
                parsed = pickle.loads(raw)
            except Exception:
                return None
            return {"parsed": parsed, "meta": entry}

        pkl_path = os.path.join(self.dir, entry["pickle"])
        if not os.path.exists(pkl_path):
            return None
        try:
            with open(pkl_path, "rb") as f:
                parsed = pickle.load(f)
        except Exception:
            return None
        return {"parsed": parsed, "meta": entry}

    def delete_snapshot(self, snapshot_date: str) -> bool:
        """Xóa 1 snapshot."""
        entry = self._find_entry(snapshot_date)
        if not entry:
            return False
        self._delete_files(entry)
        index = [e for e in self._load_index() if e["date"] != snapshot_date]
        self._save_index(index)
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_index(self) -> list[dict]:
        if not os.path.exists(self.index_path):
            return []
        try:
            with open(self.index_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def _save_index(self, index: list[dict]) -> None:
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)

    def _find_entry(self, snapshot_date: str) -> Optional[dict]:
        for e in self._load_index():
            if e["date"] == snapshot_date:
                return e
        return None

    def _delete_files(self, entry: dict) -> None:
        for key in ("filename", "pickle"):
            path = os.path.join(self.dir, entry.get(key, ""))
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
