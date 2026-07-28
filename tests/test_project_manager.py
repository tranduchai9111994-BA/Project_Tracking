"""Tests cho analyzer.project_manager.ProjectManager."""
import json
import os
import shutil

import pytest

from analyzer.project_manager import ProjectManager, _slugify


# ==========================================================================
# Slugify
# ==========================================================================

def test_slugify_removes_vietnamese_diacritics():
    assert _slugify("Minh Phú 2026") == "minh-phu-2026"


def test_slugify_lowercase_and_dashes():
    assert _slugify("HR Module TEST") == "hr-module-test"


def test_slugify_handles_special_chars():
    assert _slugify("Project #1 (2026)") == "project-1-2026"


def test_slugify_empty_string_returns_empty():
    assert _slugify("") == ""


def test_slugify_dấu_đ():
    assert _slugify("Đơn hàng ĐẶC BIỆT") == "don-hang-dac-biet"


# ==========================================================================
# ProjectManager CRUD
# ==========================================================================

@pytest.fixture
def pm(tmp_path):
    return ProjectManager(str(tmp_path))


def test_create_project(pm):
    p = pm.create_project("Test Project", "Mô tả test")
    assert p.slug == "test-project"
    assert p.name == "Test Project"
    assert p.description == "Mô tả test"
    assert p.is_archived is False


def test_create_project_empty_name_raises(pm):
    with pytest.raises(ValueError):
        pm.create_project("")


def test_create_project_creates_folders(pm, tmp_path):
    p = pm.create_project("Alpha")
    proj_dir = tmp_path / p.slug
    assert proj_dir.exists()
    assert (proj_dir / "snapshots").exists()
    assert (proj_dir / "meta.json").exists()


def test_slug_collision_appends_suffix(pm):
    p1 = pm.create_project("Same Name")
    p2 = pm.create_project("Same Name")
    p3 = pm.create_project("Same Name")
    slugs = {p1.slug, p2.slug, p3.slug}
    assert len(slugs) == 3
    assert "same-name" in slugs
    assert "same-name-2" in slugs
    assert "same-name-3" in slugs


def test_list_projects_sorted_active_first(pm):
    a = pm.create_project("A")
    b = pm.create_project("B")
    pm.archive_project(a.slug)
    active = pm.list_projects()  # mặc định chỉ active
    assert len(active) == 1
    assert active[0].slug == b.slug


def test_list_include_archived(pm):
    a = pm.create_project("A")
    pm.archive_project(a.slug)
    all_projects = pm.list_projects(include_archived=True)
    assert any(p.slug == a.slug for p in all_projects)


def test_get_project(pm):
    p = pm.create_project("Test")
    got = pm.get_project(p.slug)
    assert got is not None
    assert got.slug == p.slug


def test_get_project_missing(pm):
    assert pm.get_project("nonexistent") is None


def test_rename_project(pm):
    p = pm.create_project("Old Name")
    ok = pm.rename_project(p.slug, "New Name", "New desc")
    assert ok
    got = pm.get_project(p.slug)
    assert got.name == "New Name"
    assert got.description == "New desc"


def test_rename_keeps_slug(pm):
    """Rename KHÔNG được đổi slug (tránh phá path)."""
    p = pm.create_project("First Name")
    pm.rename_project(p.slug, "Totally Different")
    got = pm.get_project(p.slug)
    assert got.slug == "first-name"  # slug giữ nguyên


def test_rename_missing_returns_false(pm):
    assert pm.rename_project("nonexistent", "New") is False


def test_delete_project(pm, tmp_path):
    p = pm.create_project("To Delete")
    assert pm.delete_project(p.slug) is True
    assert pm.get_project(p.slug) is None
    assert not (tmp_path / p.slug).exists()


def test_delete_missing_returns_false(pm):
    assert pm.delete_project("nonexistent") is False


def test_archive_and_restore(pm):
    p = pm.create_project("Alpha")
    assert pm.archive_project(p.slug) is True
    assert pm.get_project(p.slug).is_archived is True
    assert pm.archive_project(p.slug, False) is True
    assert pm.get_project(p.slug).is_archived is False


def test_touch_last_upload_updates_timestamp(pm):
    p = pm.create_project("Alpha")
    assert p.last_upload_at is None
    pm.touch_last_upload(p.slug)
    got = pm.get_project(p.slug)
    assert got.last_upload_at is not None


def test_get_or_create_default(pm):
    """Gọi 2 lần → cùng 1 project."""
    d1 = pm.get_or_create_default()
    d2 = pm.get_or_create_default()
    assert d1.slug == d2.slug == "default"
    assert len(pm.list_projects()) == 1


def test_get_snapshot_manager_scoped_to_project(pm, tmp_path):
    p1 = pm.create_project("Alpha")
    p2 = pm.create_project("Beta")
    smgr1 = pm.get_snapshot_manager(p1.slug)
    smgr2 = pm.get_snapshot_manager(p2.slug)
    assert smgr1.dir != smgr2.dir
    assert p1.slug in smgr1.dir
    assert p2.slug in smgr2.dir


def test_get_current_file_path_per_project(pm):
    p = pm.create_project("Alpha")
    path = pm.get_current_file_path(p.slug)
    assert path.endswith(os.path.join(p.slug, "current.xlsx"))


def test_get_export_dir_creates_folder(pm, tmp_path):
    """get_export_dir tạo thư mục exports/ trong project folder và trả về path."""
    p = pm.create_project("Alpha")
    export_dir = pm.get_export_dir(p.slug)
    # Path phải nằm trong project folder
    assert p.slug in export_dir
    assert export_dir.endswith("exports")
    # Folder được tạo tự động
    assert os.path.isdir(export_dir)


def test_get_export_dir_per_project(pm):
    """Mỗi project có exports/ riêng, không chung."""
    p1 = pm.create_project("Alpha")
    p2 = pm.create_project("Beta")
    assert pm.get_export_dir(p1.slug) != pm.get_export_dir(p2.slug)


def test_index_persists_between_instances(pm, tmp_path):
    p = pm.create_project("Persistent")
    pm2 = ProjectManager(str(tmp_path))
    got = pm2.get_project(p.slug)
    assert got is not None
    assert got.name == "Persistent"


# ==========================================================================
# Auto-migrate legacy V2 layout
# ==========================================================================

def test_auto_migrate_legacy_snapshots(tmp_path):
    """
    Simulate V2 cũ: uploads/snapshots/, uploads/current_functionlist.xlsx
    Khởi tạo ProjectManager tại uploads/projects/ → auto-migrate vào 'default'.
    """
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    legacy_snaps = uploads / "snapshots"
    legacy_snaps.mkdir()
    # Fake legacy snapshot
    (legacy_snaps / "2026-07-27_functionlist.xlsx").write_bytes(b"fake xlsx")
    (legacy_snaps / "snapshot_index.json").write_text('[{"date":"2026-07-27"}]', encoding="utf-8")
    (uploads / "current_functionlist.xlsx").write_bytes(b"fake current")

    projects_dir = uploads / "projects"
    pm = ProjectManager(str(projects_dir))

    default = pm.get_project("default")
    assert default is not None
    assert default.name == "Default"

    # Verify files được copy
    default_snaps = projects_dir / "default" / "snapshots"
    assert (default_snaps / "2026-07-27_functionlist.xlsx").exists()
    assert (default_snaps / "snapshot_index.json").exists()
    assert (projects_dir / "default" / "current.xlsx").exists()


def test_no_migrate_when_index_exists(tmp_path):
    """
    Nếu đã có projects.json → không migrate legacy (tránh double-migrate).
    """
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir()
    # Tạo index rỗng để giả lập đã init trước đó
    (projects_dir / "projects.json").write_text("[]", encoding="utf-8")

    # Tạo legacy folder ở parent (uploads/snapshots/)
    legacy_snaps = tmp_path / "snapshots"
    legacy_snaps.mkdir()
    (legacy_snaps / "old.xlsx").write_bytes(b"x")

    pm = ProjectManager(str(projects_dir))
    assert pm.list_projects() == []  # Không tự tạo Default


def test_no_legacy_no_default_auto_created(tmp_path):
    """Fresh install, không có legacy → index rỗng, cần get_or_create_default để có."""
    pm = ProjectManager(str(tmp_path))
    assert pm.list_projects() == []
    d = pm.get_or_create_default()
    assert d.slug == "default"
