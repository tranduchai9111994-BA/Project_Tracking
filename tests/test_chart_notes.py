"""
T28 — Tests cho Chart Notes (comment per-chart + tóm tắt chung cho PDF export).

Cover:
  - project_store: load_chart_notes / save_chart_notes (merge logic).
  - API endpoint GET/PUT /api/projects/<slug>/chart-notes.
"""
import os
import pytest

from analyzer import project_store as ps


@pytest.fixture
def tmp_project_dir(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    return str(d)


# ==========================================================================
# project_store.chart_notes
# ==========================================================================


def test_load_empty_returns_default_shape(tmp_project_dir):
    """Chưa có file → trả về summary rỗng + notes rỗng."""
    result = ps.load_chart_notes(tmp_project_dir)
    assert result == {"summary": "", "notes": {}}


def test_save_and_load_roundtrip(tmp_project_dir):
    payload = {
        "summary": "Tuần 30/2026 — overdue giảm 22%",
        "notes": {
            "section-overdue": "Cần push UAT CBLD",
            "section-module": "Module PR đã stable",
        },
    }
    saved = ps.save_chart_notes(tmp_project_dir, payload)
    assert saved["summary"] == payload["summary"]
    assert saved["notes"]["section-overdue"] == "Cần push UAT CBLD"

    reloaded = ps.load_chart_notes(tmp_project_dir)
    assert reloaded == saved


def test_save_truncates_summary_over_500_chars(tmp_project_dir):
    long_text = "x" * 800
    saved = ps.save_chart_notes(tmp_project_dir, {"summary": long_text})
    assert len(saved["summary"]) == 500


def test_save_truncates_note_over_200_chars(tmp_project_dir):
    long_note = "y" * 350
    saved = ps.save_chart_notes(
        tmp_project_dir, {"notes": {"section-x": long_note}}
    )
    assert len(saved["notes"]["section-x"]) == 200


def test_save_empty_note_value_removes_key(tmp_project_dir):
    """Note = "" → xoá key khỏi map."""
    ps.save_chart_notes(
        tmp_project_dir,
        {"notes": {"section-a": "abc", "section-b": "xyz"}},
    )
    saved = ps.save_chart_notes(
        tmp_project_dir, {"notes": {"section-a": "", "section-c": "new"}}
    )
    # section-a bị xoá (empty), section-b vẫn còn (không đụng trong PUT này),
    # section-c được thêm mới.
    assert "section-a" not in saved["notes"]
    assert saved["notes"]["section-b"] == "xyz"
    assert saved["notes"]["section-c"] == "new"


def test_save_partial_update_preserves_other_field(tmp_project_dir):
    """PUT chỉ summary → không mất notes cũ, và ngược lại."""
    ps.save_chart_notes(
        tmp_project_dir,
        {"summary": "abc", "notes": {"section-x": "note-x"}},
    )
    # PUT chỉ notes → summary giữ nguyên
    saved = ps.save_chart_notes(
        tmp_project_dir, {"notes": {"section-y": "note-y"}}
    )
    assert saved["summary"] == "abc"
    assert saved["notes"]["section-x"] == "note-x"
    assert saved["notes"]["section-y"] == "note-y"


def test_save_summary_empty_string_clears_it(tmp_project_dir):
    ps.save_chart_notes(tmp_project_dir, {"summary": "keep me"})
    saved = ps.save_chart_notes(tmp_project_dir, {"summary": ""})
    assert saved["summary"] == ""


def test_save_ignores_non_dict_payload(tmp_project_dir):
    """Payload không phải dict → không crash, giữ nguyên state."""
    saved = ps.save_chart_notes(tmp_project_dir, "not a dict")  # type: ignore[arg-type]
    assert saved == {"summary": "", "notes": {}}


def test_load_survives_corrupt_file(tmp_project_dir):
    """File chart_notes.json bị hỏng → fallback default, không crash."""
    with open(os.path.join(tmp_project_dir, "chart_notes.json"), "w") as f:
        f.write("{not json")
    result = ps.load_chart_notes(tmp_project_dir)
    assert result == {"summary": "", "notes": {}}


# ==========================================================================
# API endpoint
# ==========================================================================


def test_get_chart_notes_default_empty(flask_client):
    r = flask_client.get("/api/projects/default/chart-notes")
    assert r.status_code == 200
    body = r.get_json()
    assert body == {"summary": "", "notes": {}}


def test_put_chart_notes_roundtrip(flask_client):
    payload = {
        "summary": "Tuần cao điểm — 15 issue open",
        "notes": {"section-overdue": "Push UAT gấp"},
    }
    r = flask_client.put(
        "/api/projects/default/chart-notes",
        json=payload,
    )
    assert r.status_code == 200
    saved = r.get_json()
    assert saved["summary"] == payload["summary"]
    assert saved["notes"]["section-overdue"] == "Push UAT gấp"

    r2 = flask_client.get("/api/projects/default/chart-notes")
    assert r2.get_json() == saved


def test_put_chart_notes_missing_project_404(flask_client):
    r = flask_client.put(
        "/api/projects/nonexistent/chart-notes",
        json={"summary": "abc"},
    )
    assert r.status_code == 404


def test_put_chart_notes_empty_note_removes_key(flask_client):
    flask_client.put(
        "/api/projects/default/chart-notes",
        json={"notes": {"section-x": "abc"}},
    )
    r = flask_client.put(
        "/api/projects/default/chart-notes",
        json={"notes": {"section-x": ""}},
    )
    body = r.get_json()
    assert "section-x" not in body["notes"]
