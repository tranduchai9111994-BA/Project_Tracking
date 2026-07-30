"""U06 fingerprint + U07 csv parse + U19 token expiry tests."""
from datetime import datetime, timedelta, timezone

from parser.column_mapping import header_fingerprint, match_preset_by_fingerprint
from analyzer.integrations import _parse_csv_records, SUPPORTED_RESPONSE_TYPES
from analyzer import public_api as pubapi


def test_header_fingerprint_stable_order_insensitive():
    a = header_fingerprint(["B", "A", "C"])
    b = header_fingerprint(["a", "c", "b"])
    assert a == b
    assert len(a) == 16


def test_match_preset_by_fingerprint():
    fp = header_fingerprint(["Code", "Name"])
    presets = [
        {"name": "old", "mapping": {"Mã CN": "Code"}, "fingerprint": fp, "updated_at": "2026-01-01"},
        {"name": "new", "mapping": {"Mã CN": "Code"}, "fingerprint": fp, "updated_at": "2026-06-01"},
    ]
    hit = match_preset_by_fingerprint(presets, fp)
    assert hit["name"] == "new"
    assert match_preset_by_fingerprint(presets, "deadbeefdeadbeef") is None


def test_csv_supported_and_parse():
    assert "csv" in SUPPORTED_RESPONSE_TYPES
    rows = _parse_csv_records("ma_cn,ten_cn\nA.01,Foo\nB.02,Bar\n")
    assert len(rows) == 2
    assert rows[0]["ma_cn"] == "A.01"


def test_token_expiry_auto_revoke(tmp_path):
    d = str(tmp_path)
    plain, entry = pubapi.create_token(d, name="Temp", scope=["summary"], expires_in_days=1)
    assert entry.get("expires_at")
    assert entry.get("expires_in_days") == 1
    # Force expire by rewriting expires_at to past
    raw = pubapi._read_tokens_raw(d)
    raw["tokens"][0]["expires_at"] = (
        datetime.now(timezone.utc) - timedelta(days=1)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    pubapi._write_tokens_raw(d, raw)
    try:
        pubapi.verify_token(d, plain)
        assert False, "expected InvalidTokenError"
    except pubapi.InvalidTokenError as e:
        assert "hết hạn" in str(e).lower() or "expired" in str(e).lower()
    # Auto-revoked
    toks = pubapi.list_tokens(d)
    assert toks[0]["revoked"] is True
