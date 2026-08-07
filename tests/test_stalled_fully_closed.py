"""Tests: stalled = pred Closed + waiting chưa start + End phase chờ đã quá hạn."""
from datetime import date, timedelta

from analyzer.dashboard_engine import DashboardEngine
from analyzer.drill_down import _filter_stalled
from analyzer.risk_scorer import compute_risk_score
from analyzer.stalled import (
    is_fully_closed,
    is_stalled_transition,
    waiting_phase_deadline_passed,
    prev_phases_all_closed,
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
    start_dev: date | None = None,
    end_dev: date | None = None,
    dev_from_not_started: bool = False,
) -> FunctionRow:
    phases = {}
    for name in PHASES:
        st = statuses.get(name)
        pd = PhaseData(status=st)
        if name == "Analysis" and st == "Closed":
            pd.end_date = end_analysis or date(2024, 12, 30)
        if name == "Dev":
            if end_dev is not None:
                pd.end_date = end_dev
            if start_dev is not None:
                pd.start_date = start_dev
            if dev_from_not_started and st == "Open":
                pd.from_not_started = True
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


def test_prev_phases_all_closed():
    """prev_phases_all_closed: chỉ True khi mọi phase trước curr_idx đều Closed."""
    row_ok = _row("P1", {"Analysis": "Closed", "Dev": "Closed", "Golive": "Open"})
    row_nok = _row("P2", {"Analysis": "In-progress", "Dev": "Open", "Golive": None})
    assert prev_phases_all_closed(row_ok, PHASES, 0) is True   # không có phase trước
    assert prev_phases_all_closed(row_ok, PHASES, 1) is True   # Analysis Closed
    assert prev_phases_all_closed(row_ok, PHASES, 2) is True   # Analysis+Dev Closed
    assert prev_phases_all_closed(row_nok, PHASES, 0) is True  # không có phase trước
    assert prev_phases_all_closed(row_nok, PHASES, 1) is False # Analysis In-progress
    assert prev_phases_all_closed(row_nok, PHASES, 2) is False # Analysis In-progress


def test_analysis_not_closed_no_stalled_downstream():
    """Nếu Analysis chưa Closed → không flag stalled cho Dev→Golive."""
    data = _parsed([
        _row("INPROG", {"Analysis": "In-progress", "Dev": "Open", "Golive": None}),
    ])
    st = DashboardEngine(today=TODAY)._stalled_tasks(data)
    assert st["items"] == []


def test_analysis_closed_dev_closed_golive_stalled():
    """Analysis+Dev Closed, Golive Open → stalled tại Dev→Golive."""
    data = _parsed([
        _row("STUCK2", {"Analysis": "Closed", "Dev": "Closed", "Golive": "Open"}),
    ])
    st = DashboardEngine(today=TODAY)._stalled_tasks(data)
    assert len(st["items"]) == 1
    assert st["items"][0]["completed_phase"] == "Dev"
    assert st["items"][0]["waiting_phase"] == "Golive"


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
    """Rule mới: Analysis Closed + Dev Open = stalled ngay, dù Dev End chưa tới."""
    data = _parsed([
        _row("FUTURE", {"Analysis": "Closed", "Dev": "Open", "Golive": None}, end_dev=FUTURE_END),
    ])
    st = DashboardEngine(today=TODAY)._stalled_tasks(data)
    assert len(st["items"]) == 1
    assert st["items"][0]["ma_cn"] == "FUTURE"


def test_dev_no_end_now_stalled():
    """Rule mới: pred Closed + next chưa start = đình trệ ngay (không cần End)."""
    data = _parsed([
        _row("NOEND", {"Analysis": "Closed", "Dev": "Open", "Golive": None}),
    ])
    st = DashboardEngine(today=TODAY)._stalled_tasks(data)
    assert len(st["items"]) == 1
    assert st["items"][0]["ma_cn"] == "NOEND"
    # wait_days tính từ Analysis.end_date (curr_pd Closed) tới today
    assert st["items"][0]["wait_days"] >= 0


def test_dev_end_equals_today_stalled():
    """Rule mới: pred Closed + next Open = đình trệ dù End == today."""
    data = _parsed([
        _row("TODAY", {"Analysis": "Closed", "Dev": "Open", "Golive": None}, end_dev=TODAY),
    ])
    st = DashboardEngine(today=TODAY)._stalled_tasks(data)
    assert len(st["items"]) == 1


def test_drill_down_respects_fully_closed_and_deadline():
    """DONE excluded; WAIT stalled; FUTURE Start chưa tới → không stalled."""
    data = _parsed([
        _row("DONE", {"Analysis": "Closed", "Dev": "Closed", "Golive": "Closed"}),
        _row("WAIT", {"Analysis": "Closed", "Dev": "Open", "Golive": None}, end_dev=PAST_END),
        _row(
            "FUTURE",
            {"Analysis": "Closed", "Dev": "Open", "Golive": None},
            start_dev=FUTURE_END,
            end_dev=FUTURE_END,
            dev_from_not_started=True,
        ),
    ])
    items = _filter_stalled(data, {}, TODAY)
    codes = {i["ma_cn"] for i in items}
    assert "DONE" not in codes
    assert "WAIT" in codes
    assert "FUTURE" not in codes


def test_risk_scorer_stalled_only_when_deadline_passed():
    """Stalled risk chỉ khi phase chờ đã tới Start (PRM.FR.53: Start tương lai → không)."""
    done = _row("DONE", {"Analysis": "Closed", "Dev": "Open", "Golive": "Closed"}, end_dev=PAST_END)
    stuck = _row("WAIT", {"Analysis": "Closed", "Dev": "Open", "Golive": None}, end_dev=PAST_END)
    future = _row(
        "FUTURE",
        {"Analysis": "Closed", "Dev": "Open", "Golive": None},
        start_dev=FUTURE_END,
        end_dev=FUTURE_END,
        dev_from_not_started=True,
    )
    r_done = compute_risk_score(done, TODAY, PHASES)
    r_stuck = compute_risk_score(stuck, TODAY, PHASES)
    r_future = compute_risk_score(future, TODAY, PHASES)
    assert "Bị đình trệ" not in r_done["factors"]
    assert "Bị đình trệ" in r_stuck["factors"]
    assert "Bị đình trệ" not in r_future["factors"]


def test_is_stalled_transition_helpers():
    """Pred Closed + next chưa start — chỉ stalled khi Start phase chờ đã tới."""
    closed = PhaseData(status="Closed", end_date=PAST_END)
    open_past = PhaseData(status="Open", end_date=PAST_END)
    open_future = PhaseData(
        status="Open", start_date=FUTURE_END, end_date=FUTURE_END,
        from_not_started=True,
    )
    open_no_end = PhaseData(status="Open", from_not_started=True)

    assert is_stalled_transition(closed, open_past, TODAY)
    assert not is_stalled_transition(closed, open_future, TODAY)  # Start tương lai
    assert not is_stalled_transition(closed, open_no_end, TODAY)  # Not Started, chưa tới Start
    assert is_stalled_transition(closed, None, TODAY)
    assert not is_stalled_transition(
        closed, PhaseData(status="Closed", end_date=PAST_END), TODAY,
    )
    assert not is_stalled_transition(PhaseData(status="Open"), open_past, TODAY)

    # waiting_phase_deadline_passed vẫn hoạt động đúng (dùng nơi khác)
    assert waiting_phase_deadline_passed(open_past, TODAY)
    assert not waiting_phase_deadline_passed(open_future, TODAY)
    assert not waiting_phase_deadline_passed(None, TODAY)
