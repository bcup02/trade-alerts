from __future__ import annotations

from datetime import datetime, timezone

import pytest

from trade_alerts.ledger_reconcile import (
    CLOSE_MARKERS,
    RECONCILE_SOURCE_SCHEMA,
    atomic_write,
    exchange_ledger_compare,
    fold_ledger_trades,
    is_paper_event,
    norm_symbol_ccxt,
    norm_symbol_plain,
    parse_iso,
    read_json,
    read_ledger,
    recorded_order_ids,
    sheet_ledger_compare,
    to_float,
    to_number,
    unsettled_pending_markers,
)

NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=timezone.utc)
FETCHED_AT = "2026-09-01T11:55:00Z"
FETCHED_MS = int(parse_iso(FETCHED_AT).timestamp() * 1000)


def _paper(e):  # momentum-style: no LIVE carve-out
    return is_paper_event(e)


def _paper_live_ok(e):  # my-crypto-style
    return is_paper_event(e, live_close_estimate_is_real=True)


def _snapshot(**over):
    base = {
        "schema_version": RECONCILE_SOURCE_SCHEMA,
        "fetched_at": FETCHED_AT,
        "fetch_status": {"complete": True, "errors": []},
        "positions": [],
        "fills": [],
    }
    base.update(over)
    return base


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def test_parse_iso_variants():
    assert parse_iso("2026-09-01T00:00:00Z").tzinfo is not None
    assert parse_iso("2026-09-01T00:00:00").tzinfo is timezone.utc
    assert parse_iso("") is None
    assert parse_iso("not-a-date") is None
    assert parse_iso(12345) is None


def test_to_float_and_to_number():
    assert to_float("1.5") == 1.5
    assert to_float(None) == 0.0
    assert to_float("x") == 0.0
    assert to_number("") is None
    assert to_number(None) is None
    assert to_number("2.0") == 2.0
    assert to_number("x") is None


def test_norm_symbol_plain_vs_ccxt():
    assert norm_symbol_plain(" gps_usdt ") == "GPS_USDT"
    assert norm_symbol_ccxt("BTC/USDT:USDT") == "BTCUSDT"
    assert norm_symbol_ccxt("BTC_USDT") == "BTCUSDT"
    assert norm_symbol_ccxt(None) == ""


def test_read_ledger_skips_junk(tmp_path):
    p = tmp_path / "l.jsonl"
    p.write_text('{"a":1}\n\nnot json\n["list"]\n{"b":2}\n', encoding="utf-8")
    assert read_ledger(p) == [{"a": 1}, {"b": 2}]
    assert read_ledger(tmp_path / "missing.jsonl") == []


def test_atomic_write_then_read_json(tmp_path):
    p = tmp_path / "out" / "status.json"
    atomic_write(p, {"value": "RECONCILED", "n": 1})
    assert read_json(p) == {"value": "RECONCILED", "n": 1}
    assert (p.stat().st_mode & 0o777) == 0o644


# --------------------------------------------------------------------------- #
# is_paper_event
# --------------------------------------------------------------------------- #

def test_is_paper_event_dry_run_source():
    assert is_paper_event({"source": "dry_run_simulated", "event_type": "trade_open", "order_id": "x"})


def test_is_paper_event_missing_order_id():
    assert is_paper_event({"event_type": "trade_close", "order_id": None})
    assert not is_paper_event({"event_type": "trade_close", "order_id": "123"})


def test_is_paper_event_live_estimate_carveout():
    e = {"event_type": "trade_close", "order_id": None, "execution_mode": "LIVE"}
    assert is_paper_event(e) is True                                   # momentum
    assert is_paper_event(e, live_close_estimate_is_real=True) is False  # my-crypto
    # carve-out only applies to LIVE
    d = {"event_type": "trade_close", "order_id": None, "execution_mode": "DRY_RUN"}
    assert is_paper_event(d, live_close_estimate_is_real=True) is True


def test_recorded_order_ids():
    evs = [{"order_id": "1"}, {"order_id": None}, {"order_id": "  "}, {"order_id": 2}]
    assert recorded_order_ids(evs) == {"1", "2"}


# --------------------------------------------------------------------------- #
# unsettled_pending_markers
# --------------------------------------------------------------------------- #

def _pending(tid, **o):
    return {"event_type": "position_reconciliation_pending", "trade_id": tid,
            "symbol": "AAA_USDT", "volume": 1, **o}


def test_pending_marker_open_when_nothing_settles_it():
    out = unsettled_pending_markers([_pending("t1")], is_paper=_paper)
    assert [m["trade_id"] for m in out] == ["t1"]


def test_pending_marker_settled_by_close_marker_and_real_close_and_manual_clear():
    events = [
        _pending("t1"), {"event_type": "position_reconciled_closed", "trade_id": "t1"},
        _pending("t2"), {"event_type": "trade_close", "trade_id": "t2", "order_id": "9"},
        _pending("t3"), {"event_type": "manual_state_reconciliation", "trade_id": "t3",
                         "action": "clear_local_stale_position_without_exchange_order"},
    ]
    assert unsettled_pending_markers(events, is_paper=_paper) == []


def test_pending_marker_not_settled_by_paper_close():
    events = [_pending("t1"),
             {"event_type": "trade_close", "trade_id": "t1", "order_id": None}]
    assert [m["trade_id"] for m in unsettled_pending_markers(events, is_paper=_paper)] == ["t1"]


def test_pending_marker_dropped_when_trade_is_paper_only():
    events = [
        {"event_type": "trade_open", "trade_id": "t1", "source": "dry_run_signal", "order_id": None},
        _pending("t1"),
    ]
    assert unsettled_pending_markers(events, is_paper=_paper) == []


# --------------------------------------------------------------------------- #
# exchange_ledger_compare
# --------------------------------------------------------------------------- #

def test_exchange_compare_unknown_gates():
    common = dict(is_paper=_paper, norm_symbol=norm_symbol_plain, now=NOW)
    assert exchange_ledger_compare(None, [], **common)["value"] == "UNKNOWN"
    assert exchange_ledger_compare({"schema_version": "other"}, [], **common)["value"] == "UNKNOWN"
    incomplete = _snapshot(fetch_status={"complete": False, "errors": ["boom"]})
    assert exchange_ledger_compare(incomplete, [], **common)["value"] == "UNKNOWN"
    stale = _snapshot(fetched_at="2026-08-01T00:00:00Z")
    assert exchange_ledger_compare(stale, [], **common)["value"] == "UNKNOWN"
    # valid snapshot but no real ledger entries
    assert exchange_ledger_compare(_snapshot(), [], **common)["value"] == "UNKNOWN"


def test_exchange_compare_reconciled():
    ledger = [
        {"event_type": "trade_open", "symbol": "GPS_USDT", "order_id": "o1",
         "volume": 10, "event_epoch_ms": FETCHED_MS - 10_000},
        {"event_type": "trade_close", "symbol": "GPS_USDT", "order_id": "o2",
         "exit_volume": 10, "event_epoch_ms": FETCHED_MS - 5_000},
    ]
    doc = exchange_ledger_compare(_snapshot(), ledger, is_paper=_paper,
                                  norm_symbol=norm_symbol_plain, now=NOW)
    assert doc["value"] == "RECONCILED"
    assert doc["evidence"]["position_agreement"] == "match"


def test_exchange_compare_position_diverged():
    ledger = [{"event_type": "trade_open", "symbol": "GPS_USDT", "order_id": "o1",
               "volume": 10, "event_epoch_ms": FETCHED_MS - 10_000}]
    snap = _snapshot(positions=[{"symbol": "GPS_USDT", "quantity": 4}])
    doc = exchange_ledger_compare(snap, ledger, is_paper=_paper,
                                  norm_symbol=norm_symbol_plain, now=NOW)
    assert doc["value"] == "DIVERGED"
    assert doc["evidence"]["position_diffs"][0] == {
        "symbol": "GPS_USDT", "ledger_qty": 10.0, "exchange_qty": 4.0}


def test_exchange_compare_unmatched_fill_diverged():
    ledger = [{"event_type": "trade_open", "symbol": "GPS_USDT", "order_id": "o1",
               "volume": 10, "event_epoch_ms": FETCHED_MS - 10_000},
              {"event_type": "trade_close", "symbol": "GPS_USDT", "order_id": "o2",
               "exit_volume": 10, "event_epoch_ms": FETCHED_MS - 9_000}]
    snap = _snapshot(fills=[{"order_id": "ghost", "symbol": "GPS_USDT",
                             "time_ms": FETCHED_MS - 10 * 60 * 1000}])
    doc = exchange_ledger_compare(snap, ledger, is_paper=_paper,
                                  norm_symbol=norm_symbol_plain, now=NOW)
    assert doc["value"] == "DIVERGED"
    assert doc["evidence"]["unmatched_exchange_fills"][0]["order_id"] == "ghost"


def test_exchange_compare_pending_from_events_after_snapshot():
    # first trade fully opens+closes before the snapshot (nets to flat); a fresh
    # open lands *after* the snapshot -> not yet in ledger_pos or the exchange,
    # so no divergence, just PENDING until the next fetch catches up.
    ledger = [{"event_type": "trade_open", "symbol": "GPS_USDT", "order_id": "o1",
               "volume": 10, "event_epoch_ms": FETCHED_MS - 10_000},
              {"event_type": "trade_close", "symbol": "GPS_USDT", "order_id": "o2",
               "exit_volume": 10, "event_epoch_ms": FETCHED_MS - 8_000},
              {"event_type": "trade_open", "symbol": "AAA_USDT", "order_id": "o3",
               "volume": 5, "event_epoch_ms": FETCHED_MS + 60_000}]
    doc = exchange_ledger_compare(_snapshot(), ledger, is_paper=_paper,
                                  norm_symbol=norm_symbol_plain, now=NOW)
    assert doc["value"] == "PENDING"
    assert doc["evidence"]["ledger_events_after_snapshot"] == 1


def test_exchange_compare_include_pending_markers_toggle():
    ledger = [
        {"event_type": "trade_open", "symbol": "GPS_USDT", "order_id": "o1",
         "volume": 10, "event_epoch_ms": FETCHED_MS - 10_000},
        {"event_type": "trade_close", "symbol": "GPS_USDT", "order_id": "o2",
         "exit_volume": 10, "event_epoch_ms": FETCHED_MS - 5_000},
        _pending("orphan"),
    ]
    on = exchange_ledger_compare(_snapshot(), ledger, is_paper=_paper,
                                 norm_symbol=norm_symbol_plain, now=NOW)
    assert on["value"] == "PENDING"
    assert "pending_reconciliations" in on["evidence"]
    off = exchange_ledger_compare(_snapshot(), ledger, is_paper=_paper,
                                  norm_symbol=norm_symbol_plain, now=NOW,
                                  include_pending_markers=False)
    assert off["value"] == "RECONCILED"
    assert "pending_reconciliations" not in off["evidence"]


def test_exchange_compare_open_event_types_and_ccxt_symbol():
    # my-crypto knobs: position_recovered opens, BTC/USDT:USDT <-> BTC_USDT
    ledger = [{"event_type": "position_recovered", "symbol": "BTC/USDT:USDT",
               "order_id": "r1", "volume": 1, "event_epoch_ms": FETCHED_MS - 10_000}]
    snap = _snapshot(positions=[{"symbol": "BTC_USDT", "quantity": 1}])
    doc = exchange_ledger_compare(
        snap, ledger, is_paper=_paper_live_ok, norm_symbol=norm_symbol_ccxt, now=NOW,
        open_event_types=frozenset({"trade_open", "position_recovered"}),
        include_pending_markers=False,
    )
    assert doc["value"] == "RECONCILED"


# --------------------------------------------------------------------------- #
# fold_ledger_trades
# --------------------------------------------------------------------------- #

def test_fold_open_and_close():
    evs = [{"event_type": "trade_open", "trade_id": "t1", "symbol": "GPS_USDT",
            "order_id": "o1", "event_epoch_ms": 1},
           {"event_type": "trade_close", "trade_id": "t1", "order_id": "o2",
            "exit_price": 1.0, "event_epoch_ms": 2}]
    rec = fold_ledger_trades(evs, norm_symbol=norm_symbol_plain)["t1"]
    assert rec["opened"] and rec["closed"] and rec["close_event"]["order_id"] == "o2"


def test_fold_marker_only_close_leaves_close_event_none():
    evs = [{"event_type": "trade_open", "trade_id": "t1", "symbol": "X", "order_id": "o1"},
           {"event_type": "position_reconciled_closed", "trade_id": "t1"}]
    rec = fold_ledger_trades(evs, norm_symbol=norm_symbol_plain)["t1"]
    assert rec["closed"] is True and rec["close_event"] is None


def test_fold_drops_peripheral_only_trade_id():
    evs = [{"event_type": "order_attempt", "trade_id": "ghost", "symbol": "X"}]
    assert fold_ledger_trades(evs, norm_symbol=norm_symbol_plain) == {}


def test_fold_position_recovered_as_open_when_configured():
    evs = [{"event_type": "position_recovered", "trade_id": "t1", "symbol": "X", "order_id": "r1"}]
    without = fold_ledger_trades(evs, norm_symbol=norm_symbol_plain)
    assert without == {}
    with_pr = fold_ledger_trades(
        evs, norm_symbol=norm_symbol_plain,
        open_event_types=frozenset({"trade_open", "position_recovered"}))
    assert with_pr["t1"]["opened"] is True


# --------------------------------------------------------------------------- #
# sheet_ledger_compare
# --------------------------------------------------------------------------- #

def _row(row, *, trade_id="", execution_mode="LIVE", symbol="GPS_USDT",
         exit_time="", exit_price="", net_pnl="", entry_order_id="", exit_order_id=""):
    values = [""] * 21
    values[0] = trade_id
    values[1] = execution_mode
    values[2] = symbol
    values[5] = exit_time
    values[7] = exit_price
    values[13] = net_pnl
    values[16] = entry_order_id
    values[17] = exit_order_id
    return {"row": row, "values": values}


def _trade(tid, *, opened=True, closed=False, close_event=None, open_oid="o1",
           symbol="GPS_USDT", opened_ms=1, closed_ms=0):
    return {tid: {
        "trade_id": tid, "symbol": symbol, "opened": opened, "closed": closed,
        "open_event": {"order_id": open_oid} if opened else None,
        "close_event": close_event, "opened_ms": opened_ms, "closed_ms": closed_ms,
    }}


def test_sheet_compare_unknown_when_fetch_failed_or_no_trades():
    a = sheet_ledger_compare({}, None, sheet_name="S", norm_symbol=norm_symbol_plain,
                             fetch_error="boom", now=NOW)
    assert a["value"] == "UNKNOWN"
    b = sheet_ledger_compare({}, [], sheet_name="S", norm_symbol=norm_symbol_plain, now=NOW)
    assert b["value"] == "UNKNOWN"


def test_sheet_compare_reconciled():
    trades = _trade("t1", closed=True, close_event={"event_type": "trade_close",
                    "exit_price": 1.0, "net_pnl": 0.5, "order_id": "x2"}, closed_ms=2)
    rows = [_row(14, trade_id="t1", exit_time="2026-09-01", exit_price="1.0",
                 net_pnl="0.5", exit_order_id="x2")]
    doc = sheet_ledger_compare(trades, rows, sheet_name="S",
                               norm_symbol=norm_symbol_plain, now=NOW)
    assert doc["value"] == "RECONCILED"
    assert doc["summary"]["actionable"] == 0


def test_sheet_compare_missing_row_and_missing_close():
    trades = {**_trade("t1"), **_trade("t2", closed=True, close_event={
        "event_type": "trade_close", "exit_price": 2.0, "net_pnl": 1.0,
        "order_id": "c2", "source": "trend_reversal"}, closed_ms=2)}
    rows = [_row(10, trade_id="t2")]  # t1 absent; t2 present but open
    doc = sheet_ledger_compare(trades, rows, sheet_name="S",
                               norm_symbol=norm_symbol_plain, now=NOW)
    kinds = {d["kind"] for d in doc["discrepancies"]}
    assert kinds == {"SHEET_MISSING_ROW", "SHEET_MISSING_CLOSE"}
    assert doc["value"] == "DIVERGED"


def test_sheet_compare_unexpected_close_and_ledger_missing_row():
    trades = _trade("t1")  # open, not closed
    rows = [_row(5, trade_id="t1", exit_time="2026-09-01", net_pnl="9"),
            _row(6, trade_id="stray", exit_time="2026-08-01")]
    doc = sheet_ledger_compare(trades, rows, sheet_name="S",
                               norm_symbol=norm_symbol_plain, now=NOW)
    kinds = {d["kind"] for d in doc["discrepancies"]}
    assert kinds == {"SHEET_UNEXPECTED_CLOSE", "LEDGER_MISSING_ROW"}


def test_sheet_compare_value_mismatch_vs_estimate_superseded():
    est = {"event_type": "trade_close", "exit_price": 1.0, "net_pnl": 1.0,
           "order_id": None, "execution_mode": "LIVE", "source": "native_stop_price_estimate"}
    trades = _trade("t1", closed=True, close_event=est, closed_ms=2)
    # sheet carries different values + a real exit id -> estimate_superseded (info)
    rows = [_row(14, trade_id="t1", exit_time="2026-09-01", exit_price="1.25",
                 net_pnl="2.0", exit_order_id="real99")]
    doc = sheet_ledger_compare(trades, rows, sheet_name="S",
                               norm_symbol=norm_symbol_plain, now=NOW)
    assert doc["value"] == "RECONCILED"
    assert doc["discrepancies"][0]["kind"] == "estimate_superseded"

    # same mismatch but no real exit id on the sheet -> VALUE_MISMATCH (actionable)
    rows2 = [_row(14, trade_id="t1", exit_time="2026-09-01", exit_price="1.25", net_pnl="2.0")]
    doc2 = sheet_ledger_compare(trades, rows2, sheet_name="S",
                                norm_symbol=norm_symbol_plain, now=NOW)
    assert doc2["value"] == "DIVERGED"
    assert doc2["discrepancies"][0]["kind"] == "VALUE_MISMATCH"


def test_sheet_compare_entry_order_id_fallback_is_informational():
    trades = _trade("ledger-uuid", closed=True, close_event={
        "event_type": "trade_close", "exit_price": 1.0, "net_pnl": 0.5, "order_id": "x2"},
        open_oid="ENTRY-42", closed_ms=2)
    rows = [_row(3, trade_id="sheet-uuid", entry_order_id="ENTRY-42",
                 exit_time="2026-09-01", exit_price="1.0", net_pnl="0.5", exit_order_id="x2")]
    doc = sheet_ledger_compare(trades, rows, sheet_name="S",
                               norm_symbol=norm_symbol_plain, now=NOW)
    assert doc["value"] == "RECONCILED"
    assert doc["discrepancies"][0]["kind"] == "trade_id_mismatch"
    assert doc["discrepancies"][0]["divergence"] is False


def test_sheet_compare_since_ms_scopes_out_old_trades():
    trades = _trade("old", closed=True, close_event={"event_type": "trade_close",
                    "exit_price": 1.0}, opened_ms=1_000, closed_ms=2_000)
    doc = sheet_ledger_compare(trades, [], sheet_name="S", norm_symbol=norm_symbol_plain,
                               since_ms=10_000, now=NOW)
    # scoped out -> no SHEET_MISSING_ROW -> RECONCILED
    assert doc["value"] == "RECONCILED"
    assert doc["summary"]["discrepancies"] == 0


def test_sheet_compare_skips_paper_mode_rows_for_ledger_missing():
    doc = sheet_ledger_compare(_trade("t1", opened=False), [
        _row(9, trade_id="paper1", execution_mode="DRY_RUN", exit_time="2026-09-01"),
    ], sheet_name="S", norm_symbol=norm_symbol_plain, now=NOW)
    # the only ledger trade has no open/close -> not counted; paper sheet row skipped
    assert not any(d["kind"] == "LEDGER_MISSING_ROW" for d in doc["discrepancies"])


def test_close_markers_constant_exposed():
    assert "position_reconciled_closed" in CLOSE_MARKERS
