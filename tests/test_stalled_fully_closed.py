"""Tests: loại function đã Closed hết / phase cuối Closed khỏi stalled."""
from datetime import date

from analyzer.dashboard_engine import DashboardEngine
from analyzer.drill_down import _filter_stalled
from analyzer.risk_scorer import compute_risk_score
from analyzer.stalled import is_fully_closed, is_stalled_transition
from parser.excel_parser import FunctionRow, PhaseData, PhaseGroup, ParsedData


PHASES = ["Analysis", "Dev", "Golive"]
TODAY = date(2025, 7, 31)


def _row(ma: str, statuses: dict[str, str | None], *, end_analysis: date | None = None) -> FunctionRow:
    phases = {}
    for name in PHASES:
        st = statuses.get(name)
        pd = PhaseData(status=st)
        if name == "Analysis" and st == "Closed":
            pd.end_date = end_analysis or date(2024, 12, 30)
        phases[name] = pd
    return FunctionRow(row_num=1, meta={"ma_cn": ma, "ten_cn": ma, "module": "HR"}, phases=phases)


def _parsed(rows: list[FunctionRow]) -> ParsedData:
    pgs = [PhaseGroup(name=n) for n in PHASES]
    return ParsedData(
        headers={},
        meta_columns={},
        phase_groups=pgs,
        rows=rows,
        all_phases=list(PHASES),
        all_modules=["HR"],
    )


def test_is_fully_closed_all_closed():
    row = _row("A1", {"Analysis": "Closed", "Dev": "Closed", "Golive": "Closed"})
    assert is_fully_closed(row, PHASES) is True


def test_is_fully_closed_golive_closed_middle_blank():
    row = _row("A2", {"Analysis": "Closed", "Dev": None, "Golive": "Closed"})
    assert is_fully_closed(row, PHASES) is True


def test_is_fully_closed_analysis_closed_dev_blank_not_done():
    row = _row("A3", {"Analysis": "Closed", "Dev": None, "Golive": None})
    assert is_fully_closed(row, PHASES) is False


def test_is_fully_closed_all_cancelled():
    row = _row("A4", {"Analysis": "Cancelled", "Dev": "Cancelled", "Golive": "Cancelled"})
    assert is_fully_closed(row, PHASES) is True


def test_all_closed_not_in_stalled_items():
    data = _parsed([
        _row("DONE", {"Analysis": "Closed", "Dev": "Closed", "Golive": "Closed"}),
        _row("STUCK", {"Analysis": "Closed", "Dev": "Open", "Golive": None}),
    ])
    st = DashboardEngine(today=TODAY)._stalled_tasks(data)
    codes = {i["ma_cn"] for i in st["items"]}
    assert "DONE" not in codes
    assert "STUCK" in codes
    assert any(t["from"] == "Analysis" and t["to"] == "Dev" for t in st["transitions"])


def test_golive_closed_excludes_even_if_dev_open():
    """Golive Closed → không đình trệ dù Dev còn Open/blank (data lệch)."""
    data = _parsed([
        _row("GL", {"Analysis": "Closed", "Dev": "Open", "Golive": "Closed"}),
    ])
    st = DashboardEngine(today=TODAY)._stalled_tasks(data)
    assert st["items"] == []
    assert st["transitions"] == []


def test_analysis_closed_dev_blank_still_stalled():
    data = _parsed([
        _row("WAIT", {"Analysis": "Closed", "Dev": None, "Golive": None}),
    ])
    st = DashboardEngine(today=TODAY)._stalled_tasks(data)
    assert len(st["items"]) == 1
    assert st["items"][0]["ma_cn"] == "WAIT"
    assert st["items"][0]["completed_phase"] == "Analysis"
    assert st["items"][0]["waiting_phase"] == "Dev"


def test_drill_down_respects_fully_closed():
    data = _parsed([
        _row("DONE", {"Analysis": "Closed", "Dev": "Closed", "Golive": "Closed"}),
        _row("WAIT", {"Analysis": "Closed", "Dev": "Open", "Golive": None}),
    ])
    items = _filter_stalled(data, {}, TODAY)
    codes = {i["ma_cn"] for i in items}
    assert "DONE" not in codes
    assert "WAIT" in codes


def test_risk_scorer_no_stalled_when_fully_closed():
    done = _row("DONE", {"Analysis": "Closed", "Dev": "Open", "Golive": "Closed"})
    stuck = _row("WAIT", {"Analysis": "Closed", "Dev": "Open", "Golive": None})
    r_done = compute_risk_score(done, TODAY, PHASES)
    r_stuck = compute_risk_score(stuck, TODAY, PHASES)
    assert "Bị đình trệ" not in r_done["factors"]
    assert "Bị đình trệ" in r_stuck["factors"]


def test_is_stalled_transition_helpers():
    assert is_stalled_transition(PhaseData(status="Closed"), PhaseData(status="Open"))
    assert is_stalled_transition(PhaseData(status="Closed"), None)
    assert not is_stalled_transition(PhaseData(status="Closed"), PhaseData(status="Closed"))
    assert not is_stalled_transition(PhaseData(status="Open"), PhaseData(status="Open"))
