"""Tests: stalled = pred Closed + waiting chưa start + End phase chờ đã quá hạn."""
from datetime import date, timedelta

from analyzer.dashboard_engine import DashboardEngine
from analyzer.drill_down import _filter_stalled
from analyzer.risk_scorer import compute_risk_score
from analyzer.stalled import (
    is_fully_closed,
    is_stalled_transition,
    waiting_phase_deadline_passed,
)
from parser.excel_parser import FunctionRow, PhaseData, PhaseGroup, ParsedData


PHASES = ["Analysis", "Dev", "Golive"]
TODAY = date(2025, 7, 31)
PAST_END = TODAY - timedelta(days=5)
FUTURE_END = TODAY + timedelta(days=10)


def _row(
    ma: str,
    statuses: dict[str, str | None],
    *,
    end_analysis: date | None = None,
    end_dev: date | None = None,
) -> FunctionRow:
    phases = {}
    for name in PHASES:
        st = statuses.get(name)
        pd = PhaseData(status=st)
        if name == "Analysis" and st == "Closed":
            pd.end_date = end_analysis or date(2024, 12, 30)
        if name == "Dev" and end_dev is not None:
            pd.end_date = end_dev
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
        _row("STUCK", {"Analysis": "Closed", "Dev": "Open", "Golive": None}, end_dev=PAST_END),
    ])
    st = DashboardEngine(today=TODAY)._stalled_tasks(data)
    codes = {i["ma_cn"] for i in st["items"]}
    assert "DONE" not in codes
    assert "STUCK" in codes
    assert any(t["from"] == "Analysis" and t["to"] == "Dev" for t in st["transitions"])


def test_golive_closed_excludes_even_if_dev_open():
    """Golive Closed → không đình trệ dù Dev còn Open/blank (data lệch)."""
    data = _parsed([
        _row("GL", {"Analysis": "Closed", "Dev": "Open", "Golive": "Closed"}, end_dev=PAST_END),
    ])
    st = DashboardEngine(today=TODAY)._stalled_tasks(data)
    assert st["items"] == []
    assert st["transitions"] == []


def test_analysis_closed_dev_past_end_stalled():
    """Analysis Closed + Dev Open/blank + Dev End đã quá → stalled."""
    data = _parsed([
        _row("WAIT", {"Analysis": "Closed", "Dev": None, "Golive": None}, end_dev=PAST_END),
    ])
    st = DashboardEngine(today=TODAY)._stalled_tasks(data)
    assert len(st["items"]) == 1
    assert st["items"][0]["ma_cn"] == "WAIT"
    assert st["items"][0]["completed_phase"] == "Analysis"
    assert st["items"][0]["waiting_phase"] == "Dev"


def test_dev_future_deadline_not_stalled():
    """Analysis Closed, Dev chưa start/PIC nhưng Dev End chưa tới → không stalled."""
    data = _parsed([
        _row("FUTURE", {"Analysis": "Closed", "Dev": "Open", "Golive": None}, end_dev=FUTURE_END),
    ])
    st = DashboardEngine(today=TODAY)._stalled_tasks(data)
    assert st["items"] == []
    assert st["transitions"] == []


def test_dev_no_end_not_stalled():
    """Không có End trên phase chờ → không stalled (kể cả pred Closed)."""
    data = _parsed([
        _row("NOEND", {"Analysis": "Closed", "Dev": "Open", "Golive": None}),
    ])
    st = DashboardEngine(today=TODAY)._stalled_tasks(data)
    assert st["items"] == []
    assert st["transitions"] == []


def test_dev_end_equals_today_not_stalled():
    """End == today → chưa quá hạn (cùng overdue: end < today)."""
    data = _parsed([
        _row("TODAY", {"Analysis": "Closed", "Dev": "Open", "Golive": None}, end_dev=TODAY),
    ])
    st = DashboardEngine(today=TODAY)._stalled_tasks(data)
    assert st["items"] == []


def test_drill_down_respects_fully_closed_and_deadline():
    data = _parsed([
        _row("DONE", {"Analysis": "Closed", "Dev": "Closed", "Golive": "Closed"}),
        _row("WAIT", {"Analysis": "Closed", "Dev": "Open", "Golive": None}, end_dev=PAST_END),
        _row("FUTURE", {"Analysis": "Closed", "Dev": "Open", "Golive": None}, end_dev=FUTURE_END),
    ])
    items = _filter_stalled(data, {}, TODAY)
    codes = {i["ma_cn"] for i in items}
    assert "DONE" not in codes
    assert "WAIT" in codes
    assert "FUTURE" not in codes


def test_risk_scorer_stalled_only_when_deadline_passed():
    done = _row("DONE", {"Analysis": "Closed", "Dev": "Open", "Golive": "Closed"}, end_dev=PAST_END)
    stuck = _row("WAIT", {"Analysis": "Closed", "Dev": "Open", "Golive": None}, end_dev=PAST_END)
    future = _row("FUTURE", {"Analysis": "Closed", "Dev": "Open", "Golive": None}, end_dev=FUTURE_END)
    r_done = compute_risk_score(done, TODAY, PHASES)
    r_stuck = compute_risk_score(stuck, TODAY, PHASES)
    r_future = compute_risk_score(future, TODAY, PHASES)
    assert "Bị đình trệ" not in r_done["factors"]
    assert "Bị đình trệ" in r_stuck["factors"]
    assert "Bị đình trệ" not in r_future["factors"]


def test_is_stalled_transition_helpers():
    closed = PhaseData(status="Closed")
    open_past = PhaseData(status="Open", end_date=PAST_END)
    open_future = PhaseData(status="Open", end_date=FUTURE_END)
    open_no_end = PhaseData(status="Open")

    assert is_stalled_transition(closed, open_past, TODAY)
    assert not is_stalled_transition(closed, open_future, TODAY)
    assert not is_stalled_transition(closed, open_no_end, TODAY)
    assert not is_stalled_transition(closed, None, TODAY)
    assert not is_stalled_transition(closed, PhaseData(status="Closed", end_date=PAST_END), TODAY)
    assert not is_stalled_transition(PhaseData(status="Open"), open_past, TODAY)

    assert waiting_phase_deadline_passed(open_past, TODAY)
    assert not waiting_phase_deadline_passed(open_future, TODAY)
    assert not waiting_phase_deadline_passed(None, TODAY)
