"""Exchange-agnostic verified-close-backfill core: evidence building from
normalized (reconcile-source/v1-shaped) fills, and append-only ledger repair
via an injected ``ledger_append`` callable.

No exchange, no ledger-implementation import -- this is the toolkit-level
core every project's thin per-exchange adapter is meant to feed.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from trade_alerts import (
    REPAIR_EVENT_TYPES,
    VerifiedCloseError,
    append_repair,
    build_evidence,
    build_repair_events,
    find_open_event,
    load_evidence,
)
from trade_alerts.ledger_reconcile import read_ledger


def _open_event(trade_id="T1", symbol="PUFFER_USDT", volume=27376.0, price=0.0183, fee=0.2504904):
    return {
        "event_type": "trade_open", "trade_id": trade_id, "symbol": symbol,
        "volume": volume, "price": price, "fee": fee, "contract_size": 1.0, "leverage": 3,
        "order_id": "222778500", "event_epoch_ms": 1788408032535, "opened_at": "2026-09-03T04:00:32Z",
    }


# a "normalized fill" -- the reconcile-source/v1 shape binance_reconcile_fetch.fill_rows emits
def _sell_fill(*, trade_id="900", order_id="222798734", price="0.01743", quantity="27376",
                commission="0.23858184", realized_pnl="-23.81712", time_ms=1788410433000, side=None):
    fill = {"trade_id": trade_id, "order_id": order_id, "price": price, "quantity": quantity,
            "commission": commission, "realized_pnl": realized_pnl, "time_ms": time_ms}
    if side is not None:
        fill["side"] = side
    return fill


# --------------------------------------------------------------------------- #
# find_open_event
# --------------------------------------------------------------------------- #
def test_find_open_event_returns_the_matching_open():
    events = [_open_event(), {"event_type": "order_result", "trade_id": "T1"}]
    assert find_open_event(events, "T1")["trade_id"] == "T1"


def test_find_open_event_refuses_when_missing():
    with pytest.raises(VerifiedCloseError, match="no trade_open"):
        find_open_event([_open_event(trade_id="OTHER")], "T1")


def test_find_open_event_refuses_when_already_closed():
    events = [_open_event(), {"event_type": "trade_close", "trade_id": "T1"}]
    with pytest.raises(VerifiedCloseError, match="already has a trade_close"):
        find_open_event(events, "T1")


# --------------------------------------------------------------------------- #
# build_evidence
# --------------------------------------------------------------------------- #
def test_build_evidence_from_open_and_one_normalized_sell_fill():
    ev = build_evidence(
        open_event=_open_event(), sell_fills=[_sell_fill()], trailing_order_id="1000000190615768",
        artifact_name="binance_user_trades:PUFFERUSDT", method="read_only_binance_user_trades",
    )
    assert ev["audit_schema_version"] == "1.0"
    assert ev["symbol"] == "PUFFER_USDT"
    assert ev["trade"]["entry"]["price"] == "0.0183" and ev["trade"]["entry"]["fee"] == "0.2504904"
    assert Decimal(ev["trade"]["entry"]["volume"]) == Decimal("27376")
    d = ev["trade"]["close"]["deals"]
    assert len(d) == 1 and Decimal(d[0]["volume"]) == Decimal("27376") and d[0]["price"] == "0.01743"
    assert ev["trade"]["close"]["exchange_profit"] == "-23.81712"
    assert ev["trade"]["close"]["originating_trailing_order_id"] == "1000000190615768"
    assert ev["trade"]["close"]["method"] == "read_only_binance_user_trades"
    assert len(ev["source"]["artifact_sha256"]) == 64


def test_build_evidence_records_each_fills_own_side_not_hardcoded_sell():
    # A short position's real closing fills are BUY-side -- seykota trades
    # both directions, unlike momentum (long-only). exchange_side must
    # reflect the actual fill, not a hardcoded "SELL".
    buy_fill = _sell_fill(side="buy")
    ev = build_evidence(open_event=_open_event(), sell_fills=[buy_fill], trailing_order_id=None,
                         artifact_name="x", method="m")
    assert ev["trade"]["close"]["deals"][0]["exchange_side"] == "BUY"


def test_build_evidence_defaults_exchange_side_to_sell_when_fill_omits_it():
    # Backward compatible: a caller whose normalized fills don't carry a
    # side key (none of the existing ones do) keeps the original behavior.
    ev = build_evidence(open_event=_open_event(), sell_fills=[_sell_fill()], trailing_order_id=None,
                         artifact_name="x", method="m")
    assert ev["trade"]["close"]["deals"][0]["exchange_side"] == "SELL"


def test_build_evidence_multi_deal_close_is_time_ordered():
    fills = [
        _sell_fill(trade_id="2", order_id="6", price="3.0", quantity="60", commission="0.02",
                   realized_pnl="-2", time_ms=1788410100000),
        _sell_fill(trade_id="1", order_id="5", price="2.0", quantity="40", commission="0.01",
                   realized_pnl="-1", time_ms=1788410000000),
    ]
    ev = build_evidence(
        open_event=_open_event(volume=100.0), sell_fills=fills, trailing_order_id=None,
        artifact_name="x", method="read_only_binance_user_trades",
    )
    c = ev["trade"]["close"]
    assert [x["deal_id"] for x in c["deals"]] == ["1", "2"]  # time-ordered despite input order
    assert c["exchange_profit"] == "-3"
    assert c["order_id"] == "6"  # last (latest) fill's order


def test_build_evidence_refuses_when_no_fills():
    with pytest.raises(VerifiedCloseError, match="no closing fills"):
        build_evidence(open_event=_open_event(), sell_fills=[], trailing_order_id=None,
                        artifact_name="x", method="m")


def test_build_evidence_refuses_when_fills_do_not_sum_to_entry_volume():
    short = [_sell_fill(quantity="20000")]
    with pytest.raises(VerifiedCloseError, match="ambiguous close"):
        build_evidence(open_event=_open_event(volume=27376.0), sell_fills=short, trailing_order_id=None,
                        artifact_name="x", method="m")


def test_build_evidence_defaults_method_when_not_given():
    ev = build_evidence(open_event=_open_event(), sell_fills=[_sell_fill()], trailing_order_id=None,
                         artifact_name="x")
    assert ev["trade"]["close"]["method"] == "read_only_exchange_history"


# --------------------------------------------------------------------------- #
# append_repair / build_repair_events -- against the same real evidence fixture
# momentum's tests use, ported verbatim (legacy MEXC-era evidence: numeric
# exchange_side codes, no "method" field -- proves the repair path stays
# fully exchange-agnostic and backward compatible with pre-"method" evidence)
# --------------------------------------------------------------------------- #
EVIDENCE = Path(__file__).parent / "fixtures" / "mubarak-20260820-exchange-evidence.json"
TRADE_ID = "f7f8f3bfc34046aa86bdb0b5db916171"


def _write_open_trade(ledger_path):
    ledger_path.write_text(json.dumps({
        "event_id": "open-1", "event_type": "trade_open", "event_time": "2026-08-19T18:25:05Z",
        "trade_id": TRADE_ID, "symbol": "MUBARAK_USDT", "volume": 3.0, "price": 0.02091,
    }) + "\n", encoding="utf-8")


class _FakeLedger:
    """Minimal stand-in for a project's own TradeLedger: append() writes one
    JSONL line and returns a fake event id, mirroring every project's real
    TradeLedger.append(event_type, **fields) -> str signature."""

    def __init__(self, path):
        self.path = Path(path)

    def append(self, event_type, **fields):
        event_id = f"evt-{event_type}-{fields.get('trade_id', '')}"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"event_id": event_id, "event_type": event_type, **fields}) + "\n")
        return event_id


def test_preview_is_non_mutating_and_lists_exact_repair_events(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    _write_open_trade(ledger_path)
    before = ledger_path.read_text(encoding="utf-8")

    result = append_repair(ledger_path, EVIDENCE, ledger_append=_FakeLedger(ledger_path).append, apply=False)

    assert result == {
        "apply": False,
        "incident_id": "mubarak-20260820-native-trailing-stop-reconciliation",
        "trade_id": TRADE_ID,
        "event_count": 5,
        "event_types": [
            "reconciliation_evidence_recorded", "fill", "fill", "trade_close", "position_reconciled_closed",
        ],
        "state_file_touched": False,
    }
    assert ledger_path.read_text(encoding="utf-8") == before


def test_apply_appends_evidence_backed_close_without_overwriting_open_trade(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    _write_open_trade(ledger_path)

    result = append_repair(ledger_path, EVIDENCE, ledger_append=_FakeLedger(ledger_path).append, apply=True)
    events = read_ledger(ledger_path)

    assert len(result["appended_event_ids"]) == 5
    assert len(events) == 6
    assert events[0]["event_type"] == "trade_open"
    assert [event["event_type"] for event in events[1:]] == [
        "reconciliation_evidence_recorded", "fill", "fill", "trade_close", "position_reconciled_closed",
    ]
    close = events[-2]
    assert close["trade_id"] == TRADE_ID
    assert close["closed_at"] == "2026-08-19T19:36:09Z"
    assert close["entry_price"] == 0.02091
    assert close["exit_price"] == pytest.approx(0.020333333333333333)
    assert close["entry_fee"] == 0.0050184
    assert close["exit_fee"] == 0.00488
    assert close["net_pnl"] == pytest.approx(-0.1828984)
    assert close["exchange_profit"] == -0.173
    assert close["reconciliation"]["artifact_sha256"] == "7d2a22349fb570cbae4760e20fba84aecdf0fd8d681b451b85d6b28349a11c64"
    # This fixture predates the "method" field entirely -> neutral fallback,
    # not a guess at which exchange it came from.
    assert close["reconciliation"]["method"] == "read_only_exchange_history"


def test_apply_is_idempotent_and_refuses_to_duplicate_a_repaired_trade(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    _write_open_trade(ledger_path)

    append_repair(ledger_path, EVIDENCE, ledger_append=_FakeLedger(ledger_path).append, apply=True)

    with pytest.raises(VerifiedCloseError, match="already been appended"):
        append_repair(ledger_path, EVIDENCE, ledger_append=_FakeLedger(ledger_path).append, apply=True)


def test_refuses_to_override_an_existing_close(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    _write_open_trade(ledger_path)
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"event_id": "close-1", "event_type": "trade_close", "trade_id": TRADE_ID}) + "\n")

    with pytest.raises(VerifiedCloseError, match="already has a close record"):
        append_repair(ledger_path, EVIDENCE, ledger_append=_FakeLedger(ledger_path).append, apply=True)


def test_load_evidence_refuses_malformed_payload(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"audit_schema_version": "2.0"}), encoding="utf-8")
    with pytest.raises(VerifiedCloseError, match="unsupported or malformed"):
        load_evidence(bad)


def test_repair_event_types_matches_what_build_repair_events_emits():
    evidence = load_evidence(EVIDENCE)
    event_types = {event_type for event_type, _fields in build_repair_events(evidence)}
    assert event_types == REPAIR_EVENT_TYPES
