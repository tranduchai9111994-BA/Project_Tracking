"""Tests cho analyzer.risk_scorer."""
from datetime import date, timedelta

import pytest

from analyzer.risk_scorer import compute_risk_score, compute_all_risk_scores
from parser.excel_parser import FunctionRow, PhaseData


TODAY = date(2026, 7, 28)


def _make_row(**meta):
    """Helper: tạo FunctionRow rỗng với meta."""
    return FunctionRow(row_num=1, meta=meta, phases={})


def test_must_have_adds_20():
    row = _make_row(priority="Must-have")
    r = compute_risk_score(row, TODAY, [])
    assert r["breakdown"].get("priority") == 20
    assert "Must-have" in r["factors"]


def test_should_have_adds_10():
    row = _make_row(priority="Should-have")
    r = compute_risk_score(row, TODAY, [])
    assert r["breakdown"].get("priority") == 10


def test_complexity_high_adds_15():
    row = _make_row(complexity="High")
    r = compute_risk_score(row, TODAY, [])
    assert r["breakdown"].get("complexity") == 15


def test_no_priority_complexity_no_score():
    row = _make_row()
    r = compute_risk_score(row, TODAY, [])
    assert r["score"] == 0
    assert r["factors"] == []


def test_overdue_adds_20():
    row = _make_row(priority="")
    row.phases["Dev"] = PhaseData(
        start_date=None,
        end_date=TODAY - timedelta(days=5),
        status="In-progress",
        pics=["A"],
    )
    r = compute_risk_score(row, TODAY, ["Dev"])
    assert r["breakdown"].get("overdue") == 20
    assert "Có phase overdue" in r["factors"]


def test_overdue_days_extra_cap_30():
    """Trễ 60 ngày → +30 (cap), không phải +80."""
    row = _make_row()
    row.phases["Dev"] = PhaseData(
        end_date=TODAY - timedelta(days=60),
        status="In-progress",
        pics=["A"],
        start_date=None,
    )
    r = compute_risk_score(row, TODAY, ["Dev"])
    assert r["breakdown"].get("overdue_days") == 30


def test_unassigned_adds_15():
    row = _make_row()
    row.phases["Dev"] = PhaseData(
        start_date=None, end_date=None, status="In-progress", pics=[],
    )
    r = compute_risk_score(row, TODAY, ["Dev"])
    assert r["breakdown"].get("unassigned") == 15


def test_closed_phase_not_unassigned():
    """Phase đã Closed không PIC → không tính unassigned."""
    row = _make_row()
    row.phases["Dev"] = PhaseData(
        start_date=None, end_date=None, status="Closed", pics=[],
    )
    r = compute_risk_score(row, TODAY, ["Dev"])
    assert r["breakdown"].get("unassigned") is None


def test_long_duration_adds_10():
    row = _make_row()
    row.phases["Dev"] = PhaseData(
        start_date=TODAY - timedelta(days=30),
        end_date=None,
        status="In-progress",
        pics=["A"],
    )
    r = compute_risk_score(row, TODAY, ["Dev"], long_duration_threshold=3)
    assert r["breakdown"].get("long_duration") == 10


def test_stalled_adds_10():
    row = _make_row()
    row.phases["Analysis"] = PhaseData(
        start_date=None, end_date=None, status="Closed", pics=["A"],
    )
    row.phases["Dev"] = PhaseData(
        start_date=None, end_date=TODAY - timedelta(days=5), status="Open", pics=[],
    )
    r = compute_risk_score(row, TODAY, ["Analysis", "Dev"])
    assert r["breakdown"].get("stalled") == 10


def test_stalled_future_start_no_points():
    """Dev Start tương lai (Not Started) → không cộng điểm đình trệ."""
    row = _make_row()
    row.phases["Analysis"] = PhaseData(
        start_date=None, end_date=TODAY - timedelta(days=3), status="Closed", pics=["A"],
    )
    row.phases["Dev"] = PhaseData(
        start_date=TODAY + timedelta(days=10),
        end_date=TODAY + timedelta(days=12),
        status="Open",
        pics=[],
        from_not_started=True,
    )
    r = compute_risk_score(row, TODAY, ["Analysis", "Dev"])
    assert r["breakdown"].get("stalled", 0) == 0
    assert "Bị đình trệ" not in r["factors"]


def test_risk_note_adds_5():
    row = _make_row(risk_blocker="Client thay đổi req")
    r = compute_risk_score(row, TODAY, [])
    assert r["breakdown"].get("risk_note") == 5


def test_score_capped_at_100():
    """Nhiều yếu tố cộng vượt 100 phải cap 100."""
    row = _make_row(priority="Must-have", complexity="High", risk_blocker="X")
    row.phases["Analysis"] = PhaseData(
        start_date=None, end_date=None, status="Closed", pics=["A"],
    )
    row.phases["Dev"] = PhaseData(
        start_date=TODAY - timedelta(days=60),
        end_date=TODAY - timedelta(days=30),
        status="In-progress",
        pics=[],
    )
    r = compute_risk_score(row, TODAY, ["Analysis", "Dev"])
    assert r["score"] == 100


def test_compute_all_returns_sorted_list(parsed_data):
    """compute_all_risk_scores sort giảm dần theo score."""
    result = compute_all_risk_scores(parsed_data, TODAY)
    scores = [r["risk_score"] for r in result]
    assert scores == sorted(scores, reverse=True)
    assert len(result) == len(parsed_data.rows)


def test_compute_all_has_required_fields(parsed_data):
    """Mỗi entry có đủ fields: ma_cn, ten_cn, module, risk_score, risk_factors, risk_breakdown."""
    result = compute_all_risk_scores(parsed_data, TODAY)
    for r in result:
        for field in ("ma_cn", "ten_cn", "module", "risk_score",
                      "risk_factors", "risk_breakdown"):
            assert field in r
