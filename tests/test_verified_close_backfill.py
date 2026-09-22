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
    append_repair_from_evidence,
    assess_repair,
    expected_closing_side,
    incident_traces,
    REPAIR_EVENT_TYPES,
    VerifiedCloseError,
    append_repair,
    build_evidence,
    build_repair_events,
    detect_repair_candidates,
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


def test_build_repair_events_short_close_profits_when_price_falls():
    # A short position (closed by a BUY fill) profits when exit < entry --
    # the opposite sign from momentum's long-only closes. Entry 100, exit 90,
    # volume 1, contract_size 1 -> gross_pnl must be +10, not -10.
    ev = build_evidence(
        open_event=_open_event(price=100.0, fee=0.0),
        sell_fills=[_sell_fill(price="90.0", quantity="27376", commission="0", realized_pnl="273760", side="buy")],
        trailing_order_id=None, artifact_name="x", method="m",
    )
    events = {event_type: fields for event_type, fields in build_repair_events(ev)}
    assert events["trade_close"]["gross_pnl"] == pytest.approx(10.0 * 27376.0 * 1.0)
    assert events["trade_close"]["exit_price"] == pytest.approx(90.0)


def test_build_repair_events_long_close_still_profits_when_price_rises():
    # Same shape, SELL-closing (long) fill: unchanged long-only direction.
    ev = build_evidence(
        open_event=_open_event(price=100.0, fee=0.0),
        sell_fills=[_sell_fill(price="110.0", quantity="27376", commission="0", realized_pnl="273760", side="sell")],
        trailing_order_id=None, artifact_name="x", method="m",
    )
    events = {event_type: fields for event_type, fields in build_repair_events(ev)}
    assert events["trade_close"]["gross_pnl"] == pytest.approx(10.0 * 27376.0 * 1.0)
    assert events["trade_close"]["exit_price"] == pytest.approx(110.0)


def test_build_repair_events_legacy_numeric_exchange_side_defaults_to_long_direction():
    # The real MUBARAK fixture's deals carry exchange_side=3 (a MEXC numeric
    # code), not "SELL"/"BUY". This must NOT be misread as a short close --
    # every evidence file predating bidirectional support assumed the long
    # formula unconditionally, and this fixture's own golden net_pnl
    # (asserted elsewhere in this file) only holds under that assumption.
    evidence = load_evidence(EVIDENCE)
    assert evidence["trade"]["close"]["deals"][0]["exchange_side"] == 3
    events = {event_type: fields for event_type, fields in build_repair_events(evidence)}
    assert events["trade_close"]["net_pnl"] == pytest.approx(-0.1828984)


# --------------------------------------------------------------------------- #
# v2: the exchange's realized P&L is the authority
# --------------------------------------------------------------------------- #
def _close_of(evidence, **kwargs):
    return next(fields for event_type, fields in build_repair_events(evidence, **kwargs) if event_type == "trade_close")


def _puffer_evidence(realized_pnl):
    return build_evidence(
        open_event=_open_event(), sell_fills=[_sell_fill(realized_pnl=realized_pnl, side="sell")],
        trailing_order_id=None, artifact_name="x",
    )


@pytest.mark.parametrize(
    "realized_pnl, source",
    [
        ("-23.81712", "local"),               # agrees exactly
        ("-23.81212", "local"),               # residual 0.005: inside the absolute tolerance
        ("-23.80712", "local"),               # residual exactly 0.01: the bound is inclusive
        ("-23.80711", "exchange_realized"),   # residual 0.01001: just past it
    ],
)
def test_exchange_pnl_takes_over_only_past_the_tolerance(realized_pnl, source):
    close = _close_of(_puffer_evidence(realized_pnl))
    assert close["reconciliation"].get("pnl_source", "local") == source


def test_exchange_pnl_override_rewrites_every_pnl_field_consistently():
    local = _close_of(_puffer_evidence("-23.81712"))
    close = _close_of(_puffer_evidence("-20.0"))
    fees = Decimal(str(close["total_fees"]))

    assert close["gross_pnl"] == -20.0
    assert Decimal(str(close["net_pnl"])) == Decimal("-20.0") - fees
    margin = Decimal("0.0183") * Decimal("27376") / Decimal(3)
    assert close["return_on_margin"] == pytest.approx(float((Decimal("-20.0") - fees) / margin))
    assert close["reconciliation_delta"] == pytest.approx(-float(fees))
    # what was replaced is on the row, not lost
    assert close["reconciliation"]["pnl_source"] == "exchange_realized"
    assert close["reconciliation"]["local_gross_pnl"] == local["gross_pnl"]
    assert close["reconciliation"]["exchange_pnl_residual"] == pytest.approx(3.81712)
    # the prices are what the fills say either way
    for key in ("entry_price", "exit_price", "entry_volume", "exit_volume", "entry_fee", "exit_fee"):
        assert close[key] == local[key], key


def test_every_repair_row_carries_the_same_override_record():
    rows = build_repair_events(_puffer_evidence("-20.0"))
    assert {fields["reconciliation"]["pnl_source"] for _event_type, fields in rows} == {"exchange_realized"}
    reconciled = next(fields for event_type, fields in rows if event_type == "position_reconciled_closed")
    assert reconciled["net_pnl"] == _close_of(_puffer_evidence("-20.0"))["net_pnl"]


def test_agreeing_evidence_writes_byte_identical_rows_to_before():
    """Within the tolerance nothing about a repair changes -- no new keys, so
    rows written by v0.20.0 and v0.21.0 from the same evidence are identical."""
    close = _close_of(_puffer_evidence("-23.81712"))
    assert set(close["reconciliation"]) == {
        "incident_id", "artifact_sha256", "github_actions_run_id", "method",
        "exchange_occurred_at", "originating_trailing_order_id",
    }


def test_a_fill_without_realized_pnl_never_makes_the_sum_an_authority():
    """An adapter that could not attach realized P&L records 0 for that fill,
    as before; the resulting sum is not the exchange's word, so it must never
    overwrite ours."""
    evidence = build_evidence(
        open_event=_open_event(), sell_fills=[_sell_fill(realized_pnl=None, side="sell")],
        trailing_order_id=None, artifact_name="x",
    )
    assert evidence["trade"]["close"]["exchange_profit_reported"] is False
    assert "pnl_source" not in _close_of(evidence)["reconciliation"]
    assert "exchange_profit_reported" not in _puffer_evidence("-23.81712")["trade"]["close"]


def test_the_manual_and_unattended_paths_write_identical_rows(tmp_path):
    """append_repair (the manual tool) and append_repair_from_evidence (the
    runner) both go through build_repair_events, override included."""
    evidence = _puffer_evidence("-20.0")
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    manual, unattended = tmp_path / "manual.jsonl", tmp_path / "unattended.jsonl"
    for path in (manual, unattended):
        path.write_text(json.dumps(_open_event()) + "\n", encoding="utf-8")

    append_repair(manual, evidence_path, ledger_append=_FakeLedger(manual).append, apply=True)
    append_repair_from_evidence(unattended, evidence, ledger_append=_FakeLedger(unattended).append, apply=True)

    assert manual.read_text(encoding="utf-8") == unattended.read_text(encoding="utf-8")
    assert read_ledger(manual)[-2]["reconciliation"]["pnl_source"] == "exchange_realized"


def test_residual_is_exact_on_a_large_high_priced_position():
    """The residual compares two Decimal sums over the same deals, so it does
    not grow with notional: a ~1.3M USDT BTC-sized close still reconciles to
    exactly zero when the exchange agrees. The 0.01 tolerance is therefore
    absolute by design -- it absorbs exchange-side rounding of realized_pnl,
    not a percentage of position size."""
    open_event = _open_event(symbol="BTC_USDT", volume=12.5, price=104250.7, fee=651.566875)
    gross = (Decimal("105012.3") - Decimal("104250.7")) * Decimal("12.5")
    evidence = build_evidence(
        open_event=open_event,
        sell_fills=[
            _sell_fill(trade_id="1", price="105012.3", quantity="7.5", commission="393.79612",
                       realized_pnl=str((Decimal("105012.3") - Decimal("104250.7")) * Decimal("7.5")),
                       side="sell"),
            _sell_fill(trade_id="2", price="105012.3", quantity="5", commission="262.53075",
                       realized_pnl=str((Decimal("105012.3") - Decimal("104250.7")) * Decimal("5")),
                       time_ms=1788410434000, side="sell"),
        ],
        trailing_order_id=None, artifact_name="x",
    )
    assert Decimal(evidence["trade"]["close"]["exchange_profit"]) == gross
    assert "pnl_source" not in _close_of(evidence)["reconciliation"]


# --------------------------------------------------------------------------- #
# v2: a pyramided position (seykota) is one trade
# --------------------------------------------------------------------------- #
def _leg(volume, price, fee, epoch, source="add"):
    return {**_open_event(volume=volume, price=price, fee=fee), "side": "long",
            "event_epoch_ms": epoch, "source": source}


def test_find_open_event_folds_pyramided_legs_into_one_position():
    legs = [_leg(0.006, 80000.0, 0.24, 1_000, "entry"), _leg(0.004, 81000.0, 0.162, 2_000)]
    folded = find_open_event(legs, "T1")
    assert Decimal(folded["volume"]) == Decimal("0.010")
    assert Decimal(folded["price"]) == (Decimal("80000.0") * Decimal("0.006") + Decimal("81000.0") * Decimal("0.004")) \
        / Decimal("0.010")
    assert Decimal(folded["fee"]) == Decimal("0.402")
    assert folded["event_epoch_ms"] == 1_000     # the window reaches back to the first leg
    assert folded["open_leg_count"] == 2
    assert folded["trade_id"] == "T1" and folded["side"] == "long"


def test_a_pyramided_position_closed_in_full_builds_evidence():
    """Before v0.21.0 the close was compared against the *last* leg's volume,
    so every seykota trade with an add failed on volume forever."""
    legs = [_leg(0.006, 80000.0, 0.0, 1_000, "entry"), _leg(0.004, 81000.0, 0.0, 2_000)]
    evidence = build_evidence(
        open_event=find_open_event(legs, "T1"),
        sell_fills=[_sell_fill(price="82000", quantity="0.010", commission="0", realized_pnl="16", side="sell",
                               time_ms=3_000)],
        trailing_order_id=None, artifact_name="x",
    )
    close = _close_of(evidence)
    assert close["entry_volume"] == pytest.approx(0.010)
    assert close["gross_pnl"] == pytest.approx(16.0)  # (82000 - 80400) * 0.010 -- agrees, so local
    assert "pnl_source" not in close["reconciliation"]
    assert assess_repair(evidence, legs)["verdict"] == "repair"


def test_find_open_event_returns_a_single_open_unchanged():
    single = _open_event()
    assert find_open_event([single], "T1") is single


def test_find_open_event_refuses_legs_that_disagree_on_side():
    legs = [_leg(1, 1.0, 0, 1_000), {**_leg(1, 1.0, 0, 2_000), "side": "short"}]
    with pytest.raises(VerifiedCloseError, match="disagree on side"):
        find_open_event(legs, "T1")


def test_find_open_event_leaves_the_window_unknown_if_any_leg_lacks_a_time():
    legs = [_leg(1, 1.0, 0, 1_000), _leg(1, 1.0, 0, 0)]
    assert find_open_event(legs, "T1")["event_epoch_ms"] == 0


def test_detect_repair_candidates_counts_a_pyramided_trade_once():
    """One trade_open per add used to read as two still-open trades on the
    symbol, so the only candidate a seykota add could produce was skipped as
    ambiguous."""
    legs = [_leg(1, 1.0, 0, 1_000, "entry"), _leg(1, 1.0, 0, 2_000)]
    assert detect_repair_candidates(_diverged_status("PUFFER_USDT"), legs) == ["T1"]


def test_repair_event_types_matches_what_build_repair_events_emits():
    evidence = load_evidence(EVIDENCE)
    event_types = {event_type for event_type, _fields in build_repair_events(evidence)}
    assert event_types == REPAIR_EVENT_TYPES


# --------------------------------------------------------------------------- #
# detect_repair_candidates
# --------------------------------------------------------------------------- #
def _diverged_status(*symbols):
    return {
        "value": "DIVERGED",
        "evidence": {"position_diffs": [{"symbol": s, "ledger_qty": 0.0, "exchange_qty": 1.0} for s in symbols]},
    }


def test_detect_repair_candidates_finds_the_still_open_trade_for_a_diverged_symbol():
    events = [_open_event(trade_id="T1", symbol="PUFFER_USDT")]
    assert detect_repair_candidates(_diverged_status("PUFFER_USDT"), events) == ["T1"]


def test_detect_repair_candidates_ignores_symbols_without_a_position_diff():
    events = [_open_event(trade_id="T1", symbol="PUFFER_USDT")]
    assert detect_repair_candidates(_diverged_status("OTHER_USDT"), events) == []


def test_detect_repair_candidates_skips_a_symbol_already_closed():
    events = [_open_event(trade_id="T1", symbol="PUFFER_USDT"),
              {"event_type": "trade_close", "trade_id": "T1", "symbol": "PUFFER_USDT"}]
    assert detect_repair_candidates(_diverged_status("PUFFER_USDT"), events) == []


def test_detect_repair_candidates_skips_an_ambiguous_symbol_with_two_open_trades():
    events = [_open_event(trade_id="T1", symbol="PUFFER_USDT"),
              _open_event(trade_id="T2", symbol="PUFFER_USDT")]
    assert detect_repair_candidates(_diverged_status("PUFFER_USDT"), events) == []


def test_detect_repair_candidates_returns_nothing_when_not_diverged():
    events = [_open_event(trade_id="T1", symbol="PUFFER_USDT")]
    assert detect_repair_candidates({"value": "PENDING", "evidence": {"position_diffs": []}}, events) == []
    assert detect_repair_candidates({"value": "RECONCILED"}, events) == []


# --------------------------------------------------------------------------- #
# v2: assess_repair / incident_traces / append_repair_from_evidence
#
# These gate an *unattended* ledger write, so each reason gets its own test:
# a check that silently stops firing would not fail anything else here.
# --------------------------------------------------------------------------- #
def _clean_evidence(open_event=None, **fill_overrides):
    fill_overrides.setdefault("side", "sell")
    return build_evidence(
        open_event=open_event or _open_event(), sell_fills=[_sell_fill(**fill_overrides)],
        trailing_order_id=None, artifact_name="binance_user_trades:PUFFERUSDT",
    )


def _assess(evidence, events=None, **kwargs):
    return assess_repair(evidence, events if events is not None else [_open_event()], **kwargs)


def _reasons(result):
    return " | ".join(result["reasons"])


def test_assess_repairs_an_unambiguous_single_long_close():
    result = _assess(_clean_evidence())
    assert result == {"verdict": "repair", "reasons": [], "checks": result["checks"]}
    assert result["checks"]["closing_sides"] == ["SELL"]
    assert result["checks"]["expected_closing_side"] == "SELL"
    assert result["checks"]["pnl_source"] == "local"


def test_assess_keeps_the_fee_delta_out_of_the_decision():
    """reconciliation_delta is *expected* to be about -(entry_fee + exit_fee) --
    roughly -0.49 here -- and is reported, never judged."""
    result = _assess(_clean_evidence())
    assert Decimal(result["checks"]["reconciliation_delta"]) < Decimal("-0.4")
    assert result["verdict"] == "repair"


def test_assess_repairs_with_the_exchange_pnl_when_the_two_disagree():
    """v1 refused this and asked a human; v2 writes the exchange's figure."""
    result = _assess(_clean_evidence(realized_pnl="-20.0"))
    assert result["verdict"] == "repair", _reasons(result)
    assert result["checks"]["pnl_source"] == "exchange_realized"


def test_assess_repairs_a_short_close_when_the_trade_open_is_short():
    short_open = {**_open_event(), "side": "short"}
    result = _assess(_clean_evidence(open_event=short_open, side="buy"), events=[short_open])
    assert result["verdict"] == "repair", _reasons(result)
    assert result["checks"]["expected_closing_side"] == "BUY"


def test_assess_calls_a_close_on_the_wrong_side_unmappable():
    result = _assess(_clean_evidence(side="buy"))
    assert result["verdict"] == "unmappable"
    assert "not this trade's close" in _reasons(result)


def test_assess_calls_a_sell_close_of_a_short_position_unmappable():
    short_open = {**_open_event(), "side": "short"}
    result = _assess(_clean_evidence(open_event=short_open, side="sell"), events=[short_open])
    assert result["verdict"] == "unmappable"
    assert "closes with BUY" in _reasons(result)


def test_assess_uses_the_adapters_default_side_only_when_the_open_records_none():
    no_side = _open_event()
    assert "side" not in no_side
    assert _assess(_clean_evidence(side="buy"), events=[no_side], default_position_side="short")["verdict"] == "repair"
    recorded_long = {**no_side, "side": "long"}
    assert _assess(_clean_evidence(side="buy"), events=[recorded_long], default_position_side="short")["verdict"] \
        == "unmappable"


def test_assess_refuses_to_guess_an_unreadable_trade_open_side():
    odd = {**_open_event(), "side": "sideways"}
    result = _assess(_clean_evidence(), events=[odd])
    assert result["verdict"] == "unmappable"
    assert "cannot be read as long or short" in _reasons(result)


@pytest.mark.parametrize("raw, expected", [
    ("long", "SELL"), ("LONG", "SELL"), ("buy", "SELL"), ("short", "BUY"), ("sell", "BUY"), ("flat", None),
])
def test_expected_closing_side(raw, expected):
    assert expected_closing_side({"side": raw}) == expected


def test_assess_calls_a_fill_that_predates_the_trade_open_unmappable():
    result = _assess(_clean_evidence(time_ms=_open_event()["event_epoch_ms"] - 1))
    assert result["verdict"] == "unmappable"
    assert "predates the trade_open" in _reasons(result)


def test_assess_calls_deals_without_timestamps_unmappable():
    evidence = _clean_evidence()
    for deal in evidence["trade"]["close"]["deals"]:
        deal.pop("time_ms")
    result = _assess(evidence)
    assert result["verdict"] == "unmappable"
    assert "without a timestamp" in _reasons(result)


def test_assess_halts_when_a_previous_repair_left_traces():
    evidence = _clean_evidence()
    half_applied = {
        "event_type": "fill", "trade_id": "T1",
        "reconciliation": {"incident_id": evidence["incident_id"]},
    }
    result = _assess(evidence, events=[_open_event(), half_applied])
    assert result["verdict"] == "halt"
    assert "left traces" in _reasons(result)


def test_assess_halts_on_an_earlier_repair_of_this_trade_under_another_incident_id():
    earlier = {
        "event_type": "reconciliation_evidence_recorded", "trade_id": "T1",
        "reconciliation": {"incident_id": "some-earlier-manual-repair"},
    }
    result = _assess(_clean_evidence(), events=[_open_event(), earlier])
    assert result["verdict"] == "halt"
    assert "different repair" in _reasons(result)


def test_halt_wins_over_unmappable():
    """A ledger that is no longer clean is the more dangerous finding: it must
    not be downgraded to a retry just because the evidence is also off."""
    evidence = _clean_evidence(side="buy")
    half_applied = {"event_type": "fill", "trade_id": "T1", "reconciliation": {"incident_id": evidence["incident_id"]}}
    result = _assess(evidence, events=[_open_event(), half_applied])
    assert result["verdict"] == "halt"
    assert "not this trade's close" in _reasons(result)


def test_assess_calls_a_trade_that_already_has_a_close_unmappable():
    result = _assess(_clean_evidence(), events=[_open_event(), {"event_type": "trade_close", "trade_id": "T1"}])
    assert result["verdict"] == "unmappable"
    assert "already has a trade_close" in _reasons(result)


def test_assess_reports_malformed_evidence_rather_than_raising():
    result = _assess({"trade": {"close": {"deals": []}}})
    assert result["verdict"] == "unmappable"
    assert result["reasons"]


def test_assess_calls_a_trade_missing_from_the_ledger_unmappable():
    result = _assess(_clean_evidence(), events=[])
    assert result["verdict"] == "unmappable"
    assert "no trade_open for this trade_id" in _reasons(result)


def test_assess_calls_a_trade_open_without_epoch_unmappable():
    open_without_epoch = dict(_open_event())
    open_without_epoch.pop("event_epoch_ms")
    result = _assess(_clean_evidence(), events=[open_without_epoch])
    assert result["verdict"] == "unmappable"
    assert "no event_epoch_ms" in _reasons(result)


@pytest.mark.parametrize("incident_id", ["", None])
def test_assess_refuses_evidence_without_an_incident_id(incident_id):
    """Review repro (PR #21): with an empty incident_id the trace check used to
    be skipped outright, so a half-applied repair already in the ledger could
    not block anything. It still halts on the other-incident trace."""
    evidence = _clean_evidence()
    evidence["incident_id"] = incident_id
    half_applied = {"event_type": "fill", "trade_id": "T1", "reconciliation": {"incident_id": "whatever"}}

    result = _assess(evidence, events=[_open_event(), half_applied])

    assert result["verdict"] == "halt"
    assert "no incident_id" in _reasons(result)
    assert _assess(evidence)["verdict"] == "unmappable"


def test_assess_refuses_evidence_without_a_trade_id():
    evidence = _clean_evidence()
    evidence["trade"]["trade_id"] = ""
    result = _assess(evidence)
    assert result["verdict"] == "unmappable"
    assert "no trade_id" in _reasons(result)


def test_assess_ignores_repair_records_that_belong_to_other_trades():
    other = {"event_type": "fill", "trade_id": "T9", "reconciliation": {"incident_id": "other"}}
    assert _assess(_clean_evidence(), events=[_open_event(), other])["verdict"] == "repair"


def test_assess_matches_trade_ids_across_str_and_int():
    """Review note on #21: every trade_id comparison in the assessment agrees
    on str(), so an int id in evidence cannot silently miss a string id in the
    ledger."""
    evidence = build_evidence(
        open_event=_open_event(trade_id="12345"), sell_fills=[_sell_fill(side="sell")],
        trailing_order_id=None, artifact_name="x",
    )
    evidence["trade"]["trade_id"] = 12345
    earlier = {"event_type": "fill", "trade_id": "12345", "reconciliation": {"incident_id": "an-earlier-repair"}}

    result = _assess(evidence, events=[_open_event(trade_id="12345"), earlier])

    assert "different repair" in _reasons(result)
    assert "no trade_open" not in _reasons(result)
    assert "no event_epoch_ms" not in _reasons(result)


def test_incident_traces_sees_a_half_applied_repair_that_the_terminal_check_misses():
    """_existing_repair only looks at trade_close / position_reconciled_closed.
    A batch that stopped after the fills leaves neither -- the exact state an
    unattended repair must never write the rest of."""
    incident = "verified-close-backfill-abc"
    events = [
        {"event_type": "reconciliation_evidence_recorded", "trade_id": "T1",
         "reconciliation": {"incident_id": incident}},
        {"event_type": "fill", "trade_id": "T1", "reconciliation": {"incident_id": incident}},
    ]
    assert len(incident_traces(events, incident_id=incident)) == 2
    assert incident_traces(events, incident_id="some-other-incident") == []


def test_append_repair_from_evidence_matches_the_file_based_path(tmp_path):
    from_file = tmp_path / "from_file.jsonl"
    from_dict = tmp_path / "from_dict.jsonl"
    _write_open_trade(from_file)
    _write_open_trade(from_dict)

    file_result = append_repair(from_file, EVIDENCE, ledger_append=_FakeLedger(from_file).append, apply=True)
    dict_result = append_repair_from_evidence(
        from_dict, load_evidence(EVIDENCE), ledger_append=_FakeLedger(from_dict).append, apply=True,
    )

    assert file_result == dict_result
    assert from_file.read_text(encoding="utf-8") == from_dict.read_text(encoding="utf-8")


def test_append_repair_from_evidence_validates_the_dict_like_load_evidence_does(tmp_path):
    ledger_path = tmp_path / "ledger.jsonl"
    _write_open_trade(ledger_path)
    with pytest.raises(VerifiedCloseError, match="unsupported or malformed"):
        append_repair_from_evidence(
            ledger_path, {"audit_schema_version": "0.9"},
            ledger_append=_FakeLedger(ledger_path).append, apply=False,
        )
