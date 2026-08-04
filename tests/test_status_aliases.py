"""Unit tests — STATUS_ALIASES + Not Started phụ thuộc PIC."""
from parser.excel_parser import (
    FunctionListParser,
    STATUS_ALIASES,
    _NOT_STARTED_TOKENS,
)


def _p() -> FunctionListParser:
    return FunctionListParser()


def test_not_started_no_pic_maps_to_open():
    p = _p()
    for token in ("Not Started", "not started", "Chưa bắt đầu", "chua bat dau"):
        assert p._normalize_status(token, has_pic=False) == "Open"
        assert p._normalize_status(token) == "Open"  # default has_pic=False


def test_not_started_with_pic_maps_to_assigned():
    p = _p()
    for token in ("Not Started", "NOT STARTED", "Chưa bắt đầu", "chua bat dau"):
        assert p._normalize_status(token, has_pic=True) == "Assigned"


def test_not_started_not_in_static_aliases():
    """Rule: không alias tĩnh Not Started → Open trong STATUS_ALIASES."""
    for token in _NOT_STARTED_TOKENS:
        assert token not in STATUS_ALIASES


def test_finished_done_complete_to_closed():
    p = _p()
    for raw in ("Finished", "Done", "Complete", "Completed", "Hoàn thành", "hoan thanh"):
        assert p._normalize_status(raw) == "Closed"


def test_unknown_status_becomes_none():
    p = _p()
    assert p._normalize_status("XyZ Weird") is None
    assert p._normalize_status("Almost Done") is None
    assert p._normalize_status(8) is None  # số = lệch cột Estimate MH
    assert p._normalize_status("") is None
    assert p._normalize_status(None) is None


def test_common_aliases():
    p = _p()
    assert p._normalize_status("In Progress") == "In-progress"
    assert p._normalize_status("waiting") == "Pending"
    assert p._normalize_status("canceled") == "Cancelled"
    assert p._normalize_status("assign") == "Assigned"
    assert p._normalize_status("resolve") == "Resolved"
