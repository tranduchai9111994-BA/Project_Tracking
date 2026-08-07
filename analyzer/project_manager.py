"""
Project Manager — Quản lý nhiều project độc lập.

Layout đĩa:
    base_dir/
      projects.json                       # Index tất cả project
      <slug>/                             # Mỗi project 1 folder
        meta.json                         # Metadata riêng
        current.xlsx                      # File Function List hiện tại
        snapshots/
          snapshot_index.json
          YYYY-MM-DD_functionlist.xlsx
          YYYY-MM-DD_functionlist.parsed.pkl
        baselines/                          # Baseline đã chốt — bất biến
          baselines_index.json
          YYYY-MM-DD_v1_functionlist.xlsx
          YYYY-MM-DD_v1_functionlist.parsed.pkl

Backward compat: nếu tồn tại `base_dir/snapshots/` từ V2 cũ,
tự động migrate vào project "Default" khi lần đầu init.
"""
import json
import os
import re
import shutil
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional

from analyzer.snapshot_manager import SnapshotManager


PROJECTS_INDEX = "projects.json"
LEGACY_SNAPSHOTS = "snapshots"  # Layout V2 cũ: uploads/snapshots/
LEGACY_CURRENT_FILE = "current_functionlist.xlsx"


@dataclass
class Project:
    """1 project độc lập."""
    slug: str
    name: str
    description: str = ""
    created_at: str = ""
    last_upload_at: Optional[str] = None
    is_archived: bool = False
    tags: list[str] = field(default_factory=list)


class ProjectManager:
    """Quản lý danh sách project + storage per-project."""

    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)
        self.index_path = os.path.join(self.base_dir, PROJECTS_INDEX)
        # Auto-migrate legacy V2 layout vào project "Default"
        self._auto_migrate_legacy()

    # ------------------------------------------------------------------
    # Public API — CRUD Project
    # ------------------------------------------------------------------

    def create_project(self, name: str, description: str = "") -> Project:
        """Tạo project mới. Slug tự động từ name, collision-safe."""
        name = (name or "").strip()
        if not name:
            raise ValueError("Tên project không được rỗng")

        slug = self._make_unique_slug(name)
        project = Project(
            slug=slug,
            name=name,
            description=description.strip(),
            created_at=datetime.now().isoformat(timespec="seconds"),
        )

        # Tạo folder cho project
        project_dir = self._project_dir(slug)
        os.makedirs(project_dir, exist_ok=True)
        os.makedirs(os.path.join(project_dir, "snapshots"), exist_ok=True)

        # Lưu meta.json
        self._save_meta(slug, project)

        # Update index
        idx = self._load_index()
        idx.append(asdict(project))
        self._save_index(idx)

        return project

    def list_projects(self, include_archived: bool = False) -> list[Project]:
        """Danh sách project, mặc định chỉ trả active."""
        result = []
        for entry in self._load_index():
            p = Project(**entry)
            if include_archived or not p.is_archived:
                result.append(p)
        # Sort: chưa archive lên đầu, sau đó theo last_upload_at desc, cuối theo created_at
        result.sort(key=lambda p: (
            p.is_archived,
            -_iso_ts(p.last_upload_at),
            -_iso_ts(p.created_at),
        ))
        return result

    def get_project(self, slug: str) -> Optional[Project]:
        """Load 1 project theo slug."""
        for entry in self._load_index():
            if entry.get("slug") == slug:
                return Project(**entry)
        return None

    def rename_project(self, slug: str, new_name: str, new_description: str = None) -> bool:
        """Đổi tên/mô tả (slug KHÔNG đổi để tránh phá path tồn tại)."""
        new_name = (new_name or "").strip()
        if not new_name:
            return False

        idx = self._load_index()
        found = False
        for entry in idx:
            if entry.get("slug") == slug:
                entry["name"] = new_name
                if new_description is not None:
                    entry["description"] = new_description.strip()
                found = True
                break
        if not found:
            return False
        self._save_index(idx)
        # Update meta.json
        proj = self.get_project(slug)
        if proj:
            self._save_meta(slug, proj)
        return True

    def delete_project(self, slug: str) -> bool:
        """Xóa hoàn toàn project (cả file). CASCADE — không hồi phục được."""
        idx = self._load_index()
        new_idx = [e for e in idx if e.get("slug") != slug]
        if len(new_idx) == len(idx):
            return False
        # Xóa folder
        pdir = self._project_dir(slug)
        if os.path.isdir(pdir):
            shutil.rmtree(pdir, ignore_errors=True)
        self._save_index(new_idx)
        return True

    def archive_project(self, slug: str, archived: bool = True) -> bool:
        """Soft delete — đánh dấu archived, không xóa file."""
        idx = self._load_index()
        found = False
        for entry in idx:
            if entry.get("slug") == slug:
                entry["is_archived"] = archived
                found = True
                break
        if not found:
            return False
        self._save_index(idx)
        return True

    def touch_last_upload(self, slug: str) -> None:
        """Cập nhật last_upload_at khi user upload file mới."""
        idx = self._load_index()
        for entry in idx:
            if entry.get("slug") == slug:
                entry["last_upload_at"] = datetime.now().isoformat(timespec="seconds")
                break
        self._save_index(idx)

    # ------------------------------------------------------------------
    # Storage helpers per project
    # ------------------------------------------------------------------

    def get_snapshot_manager(self, slug: str) -> SnapshotManager:
        """Trả về SnapshotManager gắn với folder snapshots của project."""
        return SnapshotManager(os.path.join(self._project_dir(slug), "snapshots"))

    def get_baseline_manager(self, slug: str) -> "BaselineManager":
        """
        Trả về BaselineManager gắn với folder baselines của project.

        `baselines/` nằm NGOÀI `snapshots/` nên không bị prune theo cap
        snapshot — đó là lý do baseline không bị mất sau nhiều lần upload.
        """
        from analyzer.baseline_manager import BaselineManager
        return BaselineManager(os.path.join(self._project_dir(slug), "baselines"))

    def get_snapshot_dir(self, slug: str) -> str:
        """Path folder `snapshots/` (cần khi copy file sang baselines)."""
        return os.path.join(self._project_dir(slug), "snapshots")

    def get_current_file_path(self, slug: str) -> str:
        """Path file `current.xlsx` của project (dùng để lưu file upload)."""
        return os.path.join(self._project_dir(slug), "current.xlsx")

    def get_project_folder(self, slug: str) -> str:
        """Trả folder gốc của project (dùng lưu file tạm/export)."""
        folder = self._project_dir(slug)
        os.makedirs(folder, exist_ok=True)
        return folder

    def get_export_dir(self, slug: str) -> str:
        """
        Trả folder `exports/` riêng của project (auto-create nếu chưa có).
        Tách các file export khỏi base uploads/ để 1 project = 1 folder gọn.
        """
        folder = os.path.join(self._project_dir(slug), "exports")
        os.makedirs(folder, exist_ok=True)
        return folder

    def project_exists(self, slug: str) -> bool:
        return self.get_project(slug) is not None

    def get_or_create_default(self) -> Project:
        """
        Đảm bảo luôn có project "Default" để mọi upload không cần chọn project vẫn chạy.
        Return: project Default (tạo mới nếu chưa có).
        """
        for p in self.list_projects(include_archived=True):
            if p.slug == "default":
                return p
        return self.create_project(name="Default", description="Project mặc định")

    # ------------------------------------------------------------------
    # Migration & internal helpers
    # ------------------------------------------------------------------

    def _auto_migrate_legacy(self) -> None:
        """
        Nếu tồn tại `base_dir/snapshots/` từ V2 cũ (không có `projects.json`),
        migrate toàn bộ vào project "Default".
        Chỉ chạy 1 lần khi khởi động lần đầu sau upgrade.
        """
        if os.path.exists(self.index_path):
            return  # Đã init trước đó

        legacy_snapshots = os.path.join(self.base_dir, LEGACY_SNAPSHOTS)
        # Cẩn thận: parent của base_dir có thể là uploads/, legacy snapshot ở uploads/snapshots/
        parent_dir = os.path.dirname(self.base_dir.rstrip(os.sep))
        legacy_alt = os.path.join(parent_dir, LEGACY_SNAPSHOTS) if parent_dir else None

        legacy_dir = None
        if os.path.isdir(legacy_snapshots) and os.listdir(legacy_snapshots):
            legacy_dir = legacy_snapshots
        elif legacy_alt and os.path.isdir(legacy_alt) and os.listdir(legacy_alt):
            legacy_dir = legacy_alt

        # Kiểm tra current file legacy
        legacy_current = None
        for candidate_dir in (self.base_dir, parent_dir):
            if candidate_dir:
                c = os.path.join(candidate_dir, LEGACY_CURRENT_FILE)
                if os.path.isfile(c):
                    legacy_current = c
                    break

        if not legacy_dir and not legacy_current:
            # Không có gì để migrate, chỉ init empty index
            self._save_index([])
            return

        # Có legacy → tạo Default và di chuyển
        default = self.create_project(
            name="Default",
            description="Auto-migrate từ V2 cũ (single-project layout)",
        )
        default_dir = self._project_dir(default.slug)
        default_snapshots = os.path.join(default_dir, "snapshots")
        os.makedirs(default_snapshots, exist_ok=True)

        # Copy snapshot files
        if legacy_dir:
            for fname in os.listdir(legacy_dir):
                src = os.path.join(legacy_dir, fname)
                dst = os.path.join(default_snapshots, fname)
                try:
                    if os.path.isfile(src):
                        shutil.copy2(src, dst)
                except OSError:
                    pass

        # Copy current file
        if legacy_current:
            try:
                shutil.copy2(legacy_current, os.path.join(default_dir, "current.xlsx"))
            except OSError:
                pass

    def _project_dir(self, slug: str) -> str:
        return os.path.join(self.base_dir, slug)

    def _make_unique_slug(self, name: str) -> str:
        """Tạo slug từ name, đảm bảo unique."""
        base = _slugify(name)
        if not base:
            base = "project"
        idx = self._load_index()
        existing = {e.get("slug") for e in idx}
        slug = base
        counter = 2
        while slug in existing:
            slug = f"{base}-{counter}"
            counter += 1
        return slug

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

    def _save_meta(self, slug: str, project: Project) -> None:
        meta_path = os.path.join(self._project_dir(slug), "meta.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(asdict(project), f, ensure_ascii=False, indent=2)


# ==========================================================================
# Helpers
# ==========================================================================

def _slugify(text: str) -> str:
    """Chuyển tên tiếng Việt sang slug an toàn cho path."""
    if not text:
        return ""
    # Bỏ dấu tiếng Việt bằng NFD normalize
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    # Đổi đ → d
    text = text.replace("đ", "d").replace("Đ", "d")
    # Lowercase + thay ký tự không phải alnum bằng -
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:60]  # Giới hạn 60 ký tự cho path


def _iso_ts(s: Optional[str]) -> float:
    """Convert ISO string → timestamp float để sort. None → 0."""
    if not s:
        return 0
    try:
        return datetime.fromisoformat(s).timestamp()
    except (ValueError, TypeError):
        return 0
