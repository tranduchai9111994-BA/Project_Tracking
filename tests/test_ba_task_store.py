"""Tests cho analyzer.ba_task_store (B1)."""
import threading
from datetime import date

from analyzer import ba_task_store as store


def test_create_and_list(tmp_path):
    pdir = str(tmp_path)
    t = store.create_task(pdir, {"title": "Khảo sát TMS", "module": "TMS"})
    assert t["id"].startswith("task_")
    assert t["status"] == "open"
    assert t["type"] == "task"
    assert t["week_iso"]
    rows = store.list_tasks(pdir)
    assert len(rows) == 1
    assert rows[0]["title"] == "Khảo sát TMS"


def test_invalid_enum_falls_back_to_default(tmp_path):
    pdir = str(tmp_path)
    t = store.create_task(pdir, {"title": "X", "type": "bogus", "status": "bogus", "priority": "bogus"})
    assert t["type"] == "task"
    assert t["status"] == "open"
    assert t["priority"] == "medium"


def test_update_task(tmp_path):
    pdir = str(tmp_path)
    t = store.create_task(pdir, {"title": "A"})
    updated = store.update_task(pdir, t["id"], {"status": "in_progress", "assignee": "Nhi"})
    assert updated["status"] == "in_progress"
    assert updated["assignee"] == "Nhi"
    assert updated["title"] == "A"  # giữ field cũ không gửi lên


def test_update_missing_task_returns_none(tmp_path):
    assert store.update_task(str(tmp_path), "task_notexist", {"status": "done"}) is None


def test_delete_task(tmp_path):
    pdir = str(tmp_path)
    t = store.create_task(pdir, {"title": "A"})
    assert store.delete_task(pdir, t["id"]) is True
    assert store.list_tasks(pdir) == []
    assert store.delete_task(pdir, t["id"]) is False


def test_bulk_create(tmp_path):
    pdir = str(tmp_path)
    created = store.bulk_create_tasks(pdir, [{"title": "A"}, {"title": "B"}])
    assert len(created) == 2
    assert len(store.list_tasks(pdir)) == 2


def test_done_status_sets_done_date(tmp_path):
    pdir = str(tmp_path)
    t = store.create_task(pdir, {"title": "A", "status": "done"}, today=date(2026, 8, 3))
    assert t["done_date"] == "2026-08-03"


def test_sub_info_only_for_matching_type(tmp_path):
    pdir = str(tmp_path)
    t = store.create_task(pdir, {
        "title": "Họp KH", "type": "meeting",
        "meeting_info": {"meeting_date": "2026-08-05", "attendees": ["A"]},
    })
    assert t["meeting_info"]["meeting_date"] == "2026-08-05"
    assert t["deliverable_info"] is None
    assert t["debt_info"] is None


def test_compute_alert_overdue():
    task = {"status": "in_progress", "due_date": "2026-08-01"}
    assert store.compute_alert(task, date(2026, 8, 3)) == "overdue"


def test_compute_alert_upcoming():
    task = {"status": "open", "due_date": "2026-08-04"}
    assert store.compute_alert(task, date(2026, 8, 3), auto_alert_days_before=2) == "upcoming"


def test_compute_alert_blocked():
    task = {"status": "blocked", "due_date": None}
    assert store.compute_alert(task, date(2026, 8, 3)) == "blocked"


def test_compute_alert_none_for_done():
    task = {"status": "done", "due_date": "2020-01-01"}
    assert store.compute_alert(task, date(2026, 8, 3)) is None


def test_compute_alert_none_when_far_future_and_open():
    task = {"status": "open", "due_date": "2026-12-31"}
    assert store.compute_alert(task, date(2026, 8, 3)) is None


def test_settings_roundtrip(tmp_path):
    pdir = str(tmp_path)
    s = store.get_settings(pdir)
    assert s["auto_alert_days_before"] == 2
    updated = store.update_settings(pdir, {"auto_alert_days_before": 5, "default_assignee": "Nhi"})
    assert updated["auto_alert_days_before"] == 5
    assert updated["default_assignee"] == "Nhi"
    assert store.get_settings(pdir)["default_assignee"] == "Nhi"


def test_corrupt_file_falls_back_to_empty(tmp_path):
    pdir = str(tmp_path)
    path = store._store_path(pdir)
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not valid json")
    assert store.list_tasks(pdir) == []


def test_atomic_write_no_tmp_leftover(tmp_path):
    pdir = str(tmp_path)
    store.create_task(pdir, {"title": "A"})
    files = list(tmp_path.iterdir())
    assert [f.name for f in files] == ["ba_tasks.json"]


def test_concurrent_deletes_dont_lose_updates(tmp_path):
    """Regression: 2 request cùng lúc đọc-sửa-ghi phải không được ghi đè nhau.

    Trước fix: delete_task chỉ lock bước ghi, không lock bước đọc → N thread
    cùng đọc bản cũ (còn đủ N task) rồi mỗi thread tự xoá 1 task trên bản đó
    và ghi đè lẫn nhau → chỉ còn xoá được thread ghi sau cùng, mất các lần xoá khác.
    """
    pdir = str(tmp_path)
    tasks = store.bulk_create_tasks(pdir, [{"title": f"T{i}"} for i in range(20)])
    ids = [t["id"] for t in tasks]

    results = []
    threads = [threading.Thread(target=lambda tid=tid: results.append(store.delete_task(pdir, tid))) for tid in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(results)
    assert store.list_tasks(pdir) == []


def test_concurrent_creates_dont_lose_tasks(tmp_path):
    pdir = str(tmp_path)
    threads = [
        threading.Thread(target=lambda i=i: store.create_task(pdir, {"title": f"T{i}"}))
        for i in range(20)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(store.list_tasks(pdir)) == 20
