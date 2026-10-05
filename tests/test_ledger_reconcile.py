from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from trade_alerts import ledger_reconcile as lr
from trade_alerts.ledger_reconcile import (
    CLOSE_MARKERS,
    RECONCILE_SOURCE_SCHEMA,
    atomic_write,
    exchange_ledger_compare,
    fetch_sheet_rows,
    fold_ledger_trades,
    is_paper_event,
    load_reconcile_ignore,
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


# --------------------------------------------------------------------------- #
# fetch_sheet_rows -- transport
# --------------------------------------------------------------------------- #

class _Resp:
    def __init__(self, *, status_code=200, text="", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return json.loads(self.text)


_OK_BODY = json.dumps({"ok": True, "rows": [{"row": 14, "values": ["t1", "LIVE"]}]})


def test_fetch_missing_config(monkeypatch):
    monkeypatch.delenv("SHEETS_SYNC_URL", raising=False)
    monkeypatch.delenv("SHEETS_SYNC_SECRET", raising=False)
    rows, err = fetch_sheet_rows(sheet_name="S")
    assert rows is None and "not configured" in err


def test_fetch_success(monkeypatch):
    monkeypatch.setattr(lr.requests, "post", lambda *a, **k: _Resp(text=_OK_BODY))
    rows, err = fetch_sheet_rows(sheet_name="S", url="https://x/exec", secret="s")
    assert err is None
    assert rows == [{"row": 14, "values": ["t1", "LIVE"]}]


def test_fetch_follows_302(monkeypatch):
    monkeypatch.setattr(lr.requests, "post", lambda *a, **k: _Resp(
        status_code=302, headers={"Location": "https://x/echo"}))
    monkeypatch.setattr(lr.requests, "get", lambda *a, **k: _Resp(text=_OK_BODY))
    rows, err = fetch_sheet_rows(sheet_name="S", url="https://x/exec", secret="s")
    assert err is None and rows[0]["row"] == 14


def test_fetch_receiver_error_is_terminal(monkeypatch):
    calls = []

    def _post(*a, **k):
        calls.append(1)
        return _Resp(text=json.dumps({"ok": False, "error": "unauthorized"}))

    monkeypatch.setattr(lr.requests, "post", _post)
    rows, err = fetch_sheet_rows(sheet_name="S", url="https://x/exec", secret="s",
                                 sleep=lambda _s: None)
    assert rows is None and "unauthorized" in err
    assert len(calls) == 1  # a receiver rejection is not retried


def test_fetch_retries_then_succeeds(monkeypatch):
    seq = [_Resp(status_code=500, text="boom"), _Resp(text=_OK_BODY)]
    monkeypatch.setattr(lr.requests, "post", lambda *a, **k: seq.pop(0))
    rows, err = fetch_sheet_rows(sheet_name="S", url="https://x/exec", secret="s",
                                 sleep=lambda _s: None)
    assert err is None and rows[0]["row"] == 14


def test_fetch_exhausts_retries(monkeypatch):
    def _boom(*a, **k):
        raise ConnectionError("down")

    monkeypatch.setattr(lr.requests, "post", _boom)
    rows, err = fetch_sheet_rows(sheet_name="S", url="https://x/exec", secret="s",
                                 attempts=2, sleep=lambda _s: None)
    assert rows is None and "ConnectionError" in err


def test_fetch_empty_body_exhausts(monkeypatch):
    monkeypatch.setattr(lr.requests, "post", lambda *a, **k: _Resp(text="   "))
    rows, err = fetch_sheet_rows(sheet_name="S", url="https://x/exec", secret="s",
                                 attempts=2, sleep=lambda _s: None)
    assert rows is None and err == "empty response body"


# --------------------------------------------------------------------------- #
# the operator's ignore list (f-16)
# --------------------------------------------------------------------------- #

def test_ignored_trades_are_left_out_but_listed():
    trades = {**_trade("old1", symbol="XRP_USDT"), **_trade("old2", symbol="BOME_USDT", opened_ms=2)}
    doc = sheet_ledger_compare(trades, [], sheet_name="S", norm_symbol=norm_symbol_plain,
                               now=NOW, ignore={"old1": "smoke test", "old2": "MEXC era, not wanted"})
    assert doc["value"] == "RECONCILED"                     # both missing rows are ignored
    assert doc["summary"]["ignored"] == 2 and doc["summary"]["actionable"] == 0
    assert doc["ignored"] == [
        {"trade_id": "old1", "symbol": "XRP_USDT", "reason": "smoke test"},
        {"trade_id": "old2", "symbol": "BOME_USDT", "reason": "MEXC era, not wanted"},
    ]
    assert "2 trade(s) ignored" in doc["note"]


def test_a_trade_that_is_not_ignored_is_still_reported():
    trades = {**_trade("old1"), **_trade("new1", opened_ms=2)}
    doc = sheet_ledger_compare(trades, [], sheet_name="S", norm_symbol=norm_symbol_plain,
                               now=NOW, ignore={"old1": "not wanted"})
    assert doc["value"] == "DIVERGED"
    assert [d["trade_id"] for d in doc["discrepancies"] if d["divergence"]] == ["new1"]
    assert doc["summary"]["ignored"] == 1


def test_an_id_on_the_list_that_is_not_in_the_ledger_is_not_reported_as_ignored():
    trades = _trade("t1", closed=True, close_event={"event_type": "trade_close", "exit_price": 1.0, "net_pnl": 0.5,
                    "order_id": "x2"}, closed_ms=2)
    rows = [_row(14, trade_id="t1", exit_time="2026-09-01", exit_price="1.0", net_pnl="0.5", exit_order_id="x2")]
    doc = sheet_ledger_compare(trades, rows, sheet_name="S", norm_symbol=norm_symbol_plain, now=NOW,
                               ignore={"gone": "stale entry"})
    assert doc["value"] == "RECONCILED" and doc["ignored"] == [] and doc["summary"]["ignored"] == 0


def test_a_sheet_row_of_an_ignored_trade_is_not_reported_as_unknown_to_the_ledger():
    doc = sheet_ledger_compare(_trade("old1"), [_row(5, trade_id="old1")], sheet_name="S",
                               norm_symbol=norm_symbol_plain, now=NOW, ignore={"old1": "not wanted"})
    assert doc["value"] == "RECONCILED" and doc["ignored"][0]["trade_id"] == "old1"


def test_without_a_list_the_document_is_unchanged():
    doc = sheet_ledger_compare(_trade("t1"), [], sheet_name="S", norm_symbol=norm_symbol_plain, now=NOW)
    assert "ignored" not in doc and "ignored" not in doc["summary"] and "ignore_list_problem" not in doc


def test_a_broken_list_is_reported_and_hides_nothing():
    doc = sheet_ledger_compare(_trade("t1"), [], sheet_name="S", norm_symbol=norm_symbol_plain,
                               now=NOW, ignore={}, ignore_problem="google-reconcile-ignore.json is not valid JSON")
    assert doc["value"] == "DIVERGED"
    assert doc["ignore_list_problem"] == "google-reconcile-ignore.json is not valid JSON"


def test_load_reconcile_ignore(tmp_path):
    path = tmp_path / "google-reconcile-ignore.json"
    assert load_reconcile_ignore(path) == ({}, None)                         # no file = empty list
    path.write_text(json.dumps({"ignore": [{"trade_id": " a ", "reason": " old "}, {"trade_id": "b", "reason": "x"}]}))
    assert load_reconcile_ignore(path) == ({"a": "old", "b": "x"}, None)
    for bad in ('not json', '[]', '{"ignore": {}}', '{"ignore": [{"trade_id": "a"}]}',
                '{"ignore": [{"trade_id": "a", "reason": "  "}]}', '{"ignore": ["a"]}',
                '{"ignore": [{"trade_id": "ok", "reason": "r"}, {"reason": "no id"}]}'):
        path.write_text(bad)
        entries, problem = load_reconcile_ignore(path)
        assert entries == {} and problem, bad                                 # one bad entry voids the whole list
    path.write_bytes(b"\xff\xfe")
    assert load_reconcile_ignore(path)[0] == {} and load_reconcile_ignore(path)[1]


def test_an_id_on_the_list_that_the_ledger_does_not_have_never_hides_a_stray_sheet_row():
    """Review finding F1: the list may only exclude trades the ledger really has."""
    trades = _trade("t1")
    rows = [_row(5, trade_id="t1"), _row(6, trade_id="gone")]
    doc = sheet_ledger_compare(trades, rows, sheet_name="S", norm_symbol=norm_symbol_plain, now=NOW,
                               ignore={"gone": "stale entry"})
    assert doc["value"] == "DIVERGED"
    assert [(d["kind"], d["trade_id"]) for d in doc["discrepancies"] if d["divergence"]][-1] == ("LEDGER_MISSING_ROW", "gone")
    assert doc["ignored"] == [] and doc["summary"]["ignored"] == 0


def test_an_empty_or_missing_list_leaves_the_document_exactly_as_before():
    trades = {**_trade("t1"), **_trade("t2", opened_ms=2)}
    rows = [_row(5, trade_id="t1"), _row(6, trade_id="stray")]
    without = sheet_ledger_compare(trades, rows, sheet_name="S", norm_symbol=norm_symbol_plain, now=NOW)
    empty = sheet_ledger_compare(trades, rows, sheet_name="S", norm_symbol=norm_symbol_plain, now=NOW, ignore={})
    assert json.dumps(without, sort_keys=True) == json.dumps(empty, sort_keys=True)
    assert sorted(without) == ["checked_at", "discrepancies", "last_reconciled_at", "note", "scope", "sheet_name", "summary", "value"]
    assert sorted(without["summary"]) == ["actionable", "by_kind", "discrepancies", "local_trades", "sheet_rows"]


# --------------------------------------------------------------------------- #
# adopted positions / reconciled native-stop closes carry no order_id
# (2026-10-03 trend-strategy demo incident: two real fills stayed DIVERGED)
# --------------------------------------------------------------------------- #
_ADOPT_T0 = FETCHED_MS - 3_600_000  # an hour before the snapshot


def _seykota_style_paper(e):
    """Mirrors the trend strategy: a LIVE/DEMO close with a real exit price is real."""
    if str(e.get("source") or "") in {"dry_run", "dry_run_signal", "dry_run_simulated"}:
        return True
    if e.get("event_type") in ("trade_open", "trade_close") and e.get("order_id") is None:
        return not (e.get("event_type") == "trade_close"
                    and str(e.get("execution_mode") or "").upper() in ("LIVE", "DEMO")
                    and to_float(e.get("exit_price")) > 0)
    return False


def _adopt_state(fills):
    return {"schema_version": RECONCILE_SOURCE_SCHEMA, "fetched_at": FETCHED_AT,
            "fetch_status": {"complete": True, "errors": []}, "positions": [], "fills": fills}


def _adopt_fill(order_id, side, price, qty, ms):
    return {"order_id": order_id, "trade_id": order_id + 1, "symbol": "BTCUSDT", "side": side,
            "price": price, "quantity": qty, "time_ms": ms}


def _recovered(price=84593.6, qty=0.002, ms=None, **over):
    event = {"event_type": "position_recovered", "symbol": "BTCUSDT", "side": "long", "volume": qty,
             "entry_price": price, "order_id": None, "execution_mode": "DEMO",
             "source": "exchange_position_sync", "trade_id": "BTCUSDT-adopted-1", "event_id": "r1",
             "event_epoch_ms": ms if ms is not None else _ADOPT_T0 + 17_000}
    event.update(over)
    return event


def _native_close(price=84586.0, qty=0.002, ms=None, **over):
    event = {"event_type": "trade_close", "symbol": "BTCUSDT", "side": "long", "exit_volume": qty,
             "exit_price": price, "order_id": None, "execution_mode": "DEMO",
             "source": "native_stop_reconciled", "trade_id": "BTCUSDT-adopted-1", "event_id": "c1",
             "event_epoch_ms": ms if ms is not None else _ADOPT_T0 + 133_000}
    event.update(over)
    return event


def _adopt_compare(fills, events):
    return exchange_ledger_compare(
        _adopt_state(fills), events, is_paper=_seykota_style_paper, norm_symbol=norm_symbol_plain,
        open_event_types=frozenset({"trade_open", "position_recovered"}), include_pending_markers=False,
        now=NOW,
    )


def _incident_fills():
    return [_adopt_fill(1001, "buy", 84593.6, 0.002, _ADOPT_T0),
            _adopt_fill(1002, "sell", 84586.0, 0.002, _ADOPT_T0 + 104_000)]


def test_fills_behind_an_adopted_position_and_its_native_close_are_accounted_for():
    verdict = _adopt_compare(_incident_fills(), [_recovered(), _native_close()])
    assert verdict["value"] == "RECONCILED"
    assert verdict["evidence"]["unmatched_exchange_fills"] == []
    matched = verdict["evidence"]["fills_matched_to_adopted_events"]
    assert [m["order_id"] for m in matched] == [1001, 1002]
    assert {m["ledger_trade_id"] for m in matched} == {"BTCUSDT-adopted-1"}


def test_without_the_ledger_rows_the_same_fills_still_diverge():
    verdict = _adopt_compare(_incident_fills(), [_recovered(order_id=None, event_type="trade_open",
                                                            source="dry_run_signal")])
    # a dry-run row is not real, so there is no real ledger at all
    assert verdict["value"] == "UNKNOWN"
    verdict = _adopt_compare(_incident_fills(), [_recovered(ms=_ADOPT_T0 + 17_000, event_type="trade_open",
                                                            order_id=7)])
    assert [f["order_id"] for f in verdict["evidence"]["unmatched_exchange_fills"]] == [1001, 1002]


def test_a_duplicated_send_is_not_hidden_by_one_adopted_event():
    fills = [_adopt_fill(1001, "buy", 84593.6, 0.002, _ADOPT_T0),
             _adopt_fill(1003, "buy", 84593.6, 0.002, _ADOPT_T0 + 1_000)]  # same price and size, second order
    verdict = _adopt_compare(fills, [_recovered()])
    unmatched = verdict["evidence"]["unmatched_exchange_fills"]
    assert [f["order_id"] for f in unmatched] == [1003]  # only one fill is explained by the one event
    assert verdict["value"] == "DIVERGED"


@pytest.mark.parametrize("fill_over", [
    {"price": 84593.7},                      # price differs
    {"quantity": 0.003},                     # size differs
    {"side": "sell"},                        # wrong side for the entry of a long
    {"symbol": "ETHUSDT"},                   # other symbol
    {"time_ms": _ADOPT_T0 + 1_000_000},      # fill happened after the ledger row
    {"time_ms": _ADOPT_T0 - 13 * 3_600_000},  # fill far too long before the ledger row
])
def test_a_fill_that_does_not_line_up_exactly_stays_unmatched(fill_over):
    fill = {**_adopt_fill(1001, "buy", 84593.6, 0.002, _ADOPT_T0), **fill_over}
    verdict = _adopt_compare([fill], [_recovered()])
    assert [f["order_id"] for f in verdict["evidence"]["unmatched_exchange_fills"]] == [1001]


@pytest.mark.parametrize("event_over", [
    {"order_id": 555},                       # has an order id: the order-id comparison owns it
    {"execution_mode": "DRY_RUN"},           # not a real-money or demo row
    {"source": "dry_run_signal"},
    {"side": "short"},                       # an entry of a short would be a sell
])
def test_ledger_rows_that_are_not_adopted_real_rows_explain_nothing(event_over):
    fills = [_adopt_fill(1001, "buy", 84593.6, 0.002, _ADOPT_T0)]
    matched = lr.match_fills_to_adopted_events(fills, [_recovered(**event_over)], norm_symbol=norm_symbol_plain)
    assert matched == {}


def test_the_exit_of_a_short_is_a_buy():
    fills = [_adopt_fill(2001, "sell", 100.0, 1.0, _ADOPT_T0), _adopt_fill(2002, "buy", 99.0, 1.0, _ADOPT_T0 + 60_000)]
    events = [_recovered(price=100.0, qty=1.0, side="short"), _native_close(price=99.0, qty=1.0, side="short")]
    assert sorted(lr.match_fills_to_adopted_events(fills, events, norm_symbol=norm_symbol_plain)) == [0, 1]


# --- reviewer finding on #117: a missing/zero/garbled time must fail closed ---
_BAD_TIMES = [None, 0, "", "abc", -5, float("nan"), float("inf"), float("-inf"), True, False, 0.5, 10 ** 400]


@pytest.mark.parametrize("bad", _BAD_TIMES)
def test_a_ledger_row_without_a_usable_time_explains_nothing(bad):
    fill = _adopt_fill(1001, "buy", 84593.6, 0.002, _ADOPT_T0)
    matched = lr.match_fills_to_adopted_events([fill], [_recovered(event_epoch_ms=bad)], norm_symbol=norm_symbol_plain)
    assert matched == {}


@pytest.mark.parametrize("bad", _BAD_TIMES)
def test_a_fill_without_a_usable_time_is_never_matched(bad):
    fill = {**_adopt_fill(1001, "buy", 84593.6, 0.002, _ADOPT_T0), "time_ms": bad}
    matched = lr.match_fills_to_adopted_events([fill], [_recovered()], norm_symbol=norm_symbol_plain)
    assert matched == {}


def _adopt_state_with_position(fills):
    """Position already agrees with the ledger (0.002 BTC), so the verdict can
    only be driven by the fill -- the reviewer's reproduction."""
    state = _adopt_state(fills)
    state["positions"] = [{"symbol": "BTCUSDT", "quantity": 0.002}]
    return state


def _compare_with_position(fills, events):
    return exchange_ledger_compare(
        _adopt_state_with_position(fills), events, is_paper=_seykota_style_paper, norm_symbol=norm_symbol_plain,
        open_event_types=frozenset({"trade_open", "position_recovered"}), include_pending_markers=False, now=NOW,
    )


@pytest.mark.parametrize("bad", _BAD_TIMES)
def test_an_unusable_fill_time_keeps_the_fill_unmatched_end_to_end(bad):
    """NaN / +inf / bool / 0.5 / overflow on the *fill* must neither match nor
    silently disappear in the grace filter: the fill stays in unmatched and the
    verdict is not RECONCILED."""
    fill = {**_adopt_fill(1001, "buy", 84593.6, 0.002, _ADOPT_T0), "time_ms": bad}
    verdict = _compare_with_position([fill], [_recovered()])
    assert [f["order_id"] for f in verdict["evidence"]["unmatched_exchange_fills"]] == [1001]
    assert "fills_matched_to_adopted_events" not in verdict["evidence"]
    assert verdict["value"] == "DIVERGED"


@pytest.mark.parametrize("bad", _BAD_TIMES)
def test_an_unusable_time_on_both_sides_never_lines_up_end_to_end(bad):
    """The reviewer's reproduction, now for every unusable value: ledger row and
    fill both carry the same bad time, everything else identical."""
    fill = {**_adopt_fill(1001, "buy", 84593.6, 0.002, _ADOPT_T0), "time_ms": bad}
    if bad == "abc":
        # A garbled *string* on the ledger side already makes the older raw
        # ``> cutoff`` comparisons raise TypeError; the strategy wrappers turn
        # that into an UNKNOWN verdict.  That is existing, stricter-than-needed
        # fail-closed behaviour (the whole comparison aborts), kept on purpose.
        with pytest.raises(TypeError):
            _compare_with_position([fill], [_recovered(event_epoch_ms=bad)])
        return
    verdict = _compare_with_position([fill], [_recovered(event_epoch_ms=bad)])
    assert verdict["value"] != "RECONCILED"
    assert [f["order_id"] for f in verdict["evidence"]["unmatched_exchange_fills"]] == [1001]
    assert "fills_matched_to_adopted_events" not in verdict["evidence"]


def test_a_numeric_string_time_is_read_as_a_number():
    from trade_alerts.ledger_reconcile import _positive_ms

    assert _positive_ms("1788263700000") == 1788263700000
    assert _positive_ms(1788263700000.0) == 1788263700000
    assert _positive_ms(1) == 1 and _positive_ms(True) is None


def test_the_window_edge_is_inclusive_and_one_millisecond_more_is_not():
    from trade_alerts.ledger_reconcile import ADOPTED_FILL_WINDOW_MS

    event_ms = _ADOPT_T0 + ADOPTED_FILL_WINDOW_MS
    on_edge = _adopt_fill(1001, "buy", 84593.6, 0.002, _ADOPT_T0)
    just_past = _adopt_fill(1002, "buy", 84593.6, 0.002, _ADOPT_T0 - 1)
    assert lr.match_fills_to_adopted_events([on_edge], [_recovered(ms=event_ms)], norm_symbol=norm_symbol_plain) != {}
    assert lr.match_fills_to_adopted_events([just_past], [_recovered(ms=event_ms)], norm_symbol=norm_symbol_plain) == {}


# --- reviewer finding F3 on #117: NaN price/size must never read as "equal" ---
class bool_:  # stands in for numpy.bool_ (same type name, no numpy dependency)
    def __float__(self):
        return 1.0


_BAD_FIGURES = [float("nan"), "nan", float("inf"), float("-inf"), "inf", 0, -1, None, "", True, False,
                "abc", bool_()]


@pytest.mark.parametrize("bad", _BAD_FIGURES)
@pytest.mark.parametrize("field", ["price", "quantity"])
def test_a_fill_with_an_unusable_price_or_size_is_never_matched(bad, field):
    fill = {**_adopt_fill(1001, "buy", 84593.6, 0.002, _ADOPT_T0), field: bad}
    assert lr.match_fills_to_adopted_events([fill], [_recovered()], norm_symbol=norm_symbol_plain) == {}


@pytest.mark.parametrize("bad", _BAD_FIGURES)
@pytest.mark.parametrize("field", ["volume", "entry_price"])
def test_a_ledger_row_with_an_unusable_price_or_size_explains_nothing(bad, field):
    fill = _adopt_fill(1001, "buy", 84593.6, 0.002, _ADOPT_T0)
    event = _recovered(**{field: bad})
    assert lr.match_fills_to_adopted_events([fill], [event], norm_symbol=norm_symbol_plain) == {}


@pytest.mark.parametrize("bad", _BAD_FIGURES)
@pytest.mark.parametrize("field", ["price", "quantity"])
def test_an_unusable_fill_price_or_size_stays_unmatched_end_to_end(bad, field):
    """The reviewer's reproduction: valid times, ledger row normal, position already
    agrees -- only the fill's price or size is NaN / "nan" / inf.  It must not
    become RECONCILED."""
    fill = {**_adopt_fill(1001, "buy", 84593.6, 0.002, _ADOPT_T0), field: bad}
    verdict = _compare_with_position([fill], [_recovered()])
    assert verdict["value"] == "DIVERGED"
    assert [f["order_id"] for f in verdict["evidence"]["unmatched_exchange_fills"]] == [1001]
    assert "fills_matched_to_adopted_events" not in verdict["evidence"]


@pytest.mark.parametrize("bad", _BAD_FIGURES)
@pytest.mark.parametrize("field", ["volume", "entry_price"])
def test_an_unusable_ledger_price_or_size_stays_unmatched_end_to_end(bad, field):
    fill = _adopt_fill(1001, "buy", 84593.6, 0.002, _ADOPT_T0)
    verdict = _compare_with_position([fill], [_recovered(**{field: bad})])
    assert verdict["value"] != "RECONCILED"
    assert [f["order_id"] for f in verdict["evidence"]["unmatched_exchange_fills"]] == [1001]


@pytest.mark.parametrize("bad", ["nan", float("nan")])
def test_a_nan_ledger_position_is_a_mismatch_not_flat(bad):
    """Same family: ``abs(a - b) > tol`` and ``abs(q) > 1e-9`` are both False for NaN, which
    used to drop a NaN ledger position and read the account as flat/agreeing."""
    state = _adopt_state([])  # exchange holds nothing
    verdict = exchange_ledger_compare(
        state, [_recovered(volume=bad)], is_paper=_seykota_style_paper, norm_symbol=norm_symbol_plain,
        open_event_types=frozenset({"trade_open", "position_recovered"}), include_pending_markers=False, now=NOW,
    )
    assert verdict["value"] == "DIVERGED"
    assert verdict["evidence"]["position_diffs"]


def test_numpy_style_booleans_are_not_times():
    assert lr._positive_ms(bool_()) is None
    assert lr._finite_positive(bool_()) is None
    assert lr._finite_positive("84593.6") == 84593.6


def test_the_usual_figures_still_match_with_the_positive_comparisons():
    fill = _adopt_fill(1001, "buy", 84593.6, 0.002, _ADOPT_T0)
    assert lr.match_fills_to_adopted_events([fill], [_recovered()], norm_symbol=norm_symbol_plain) != {}
    within = {**fill, "price": 84593.6 + 1e-6}  # inside the 1e-9 relative tolerance (~8.5e-5 here)
    assert lr.match_fills_to_adopted_events([within], [_recovered()], norm_symbol=norm_symbol_plain) != {}
    other = {**fill, "price": 84593.6 + 1.0}
    assert lr.match_fills_to_adopted_events([other], [_recovered()], norm_symbol=norm_symbol_plain) == {}


def _paper_shadow(e):
    """A caller-specific paper marker the matcher itself knows nothing about."""
    return e.get("source") == "paper_shadow" or _seykota_style_paper(e)


def _shadow_compare(is_paper):
    fills = [_adopt_fill(1001, "buy", 84593.6, 0.002, _ADOPT_T0)]
    real_other = _recovered(price=70000.0, event_id="r-real", trade_id="BTCUSDT-adopted-0")
    shadow = _recovered(source="paper_shadow", event_id="r-paper")
    return exchange_ledger_compare(
        _adopt_state(fills), [real_other, shadow], is_paper=is_paper, norm_symbol=norm_symbol_plain,
        open_event_types=frozenset({"trade_open", "position_recovered"}), include_pending_markers=False, now=NOW,
    )


def test_a_row_the_caller_calls_paper_never_explains_a_real_fill():
    """t11: the shared compare hands the matcher only the paper-filtered rows.
    The shadow row lines up with the fill exactly and passes every matcher check
    (DEMO, order_id null, non-dry-run source), so only the caller's is_paper
    keeps it out."""
    verdict = _shadow_compare(_paper_shadow)
    assert [f["order_id"] for f in verdict["evidence"]["unmatched_exchange_fills"]] == [1001]
    assert "fills_matched_to_adopted_events" not in verdict["evidence"]
    assert verdict["value"] == "DIVERGED"


def test_the_same_row_counts_when_the_caller_calls_it_real():
    verdict = _shadow_compare(_seykota_style_paper)
    assert [m["order_id"] for m in verdict["evidence"]["fills_matched_to_adopted_events"]] == [1001]


# --- t12: MEXC-style fill sides (open_long / close_long / open_short / close_short) ---
@pytest.mark.parametrize("position_side, entry_label, exit_label", [
    ("long", "open_long", "close_long"),
    ("short", "open_short", "close_short"),
])
def test_mexc_style_sides_explain_the_matching_action_only(position_side, entry_label, exit_label):
    fills = [_adopt_fill(3001, entry_label, 100.0, 1.0, _ADOPT_T0),
             _adopt_fill(3002, exit_label, 99.0, 1.0, _ADOPT_T0 + 60_000)]
    events = [_recovered(price=100.0, qty=1.0, side=position_side),
              _native_close(price=99.0, qty=1.0, side=position_side)]
    assert sorted(lr.match_fills_to_adopted_events(fills, events, norm_symbol=norm_symbol_plain)) == [0, 1]


@pytest.mark.parametrize("position_side, wrong_for_entry, wrong_for_exit", [
    ("long", "close_short", "open_short"),    # same buy / sell direction, wrong action
    ("short", "close_long", "open_long"),
    ("long", "close_long", "open_long"),      # right direction word, wrong action
    ("short", "close_short", "open_short"),
])
def test_a_mexc_label_for_the_wrong_action_never_matches(position_side, wrong_for_entry, wrong_for_exit):
    fills = [_adopt_fill(3001, wrong_for_entry, 100.0, 1.0, _ADOPT_T0),
             _adopt_fill(3002, wrong_for_exit, 99.0, 1.0, _ADOPT_T0 + 60_000)]
    events = [_recovered(price=100.0, qty=1.0, side=position_side),
              _native_close(price=99.0, qty=1.0, side=position_side)]
    assert lr.match_fills_to_adopted_events(fills, events, norm_symbol=norm_symbol_plain) == {}


def test_mexc_label_works_end_to_end_through_the_shared_compare():
    fills = [_adopt_fill(1001, "open_long", 84593.6, 0.002, _ADOPT_T0),
             _adopt_fill(1002, "close_long", 84586.0, 0.002, _ADOPT_T0 + 104_000)]
    verdict = _adopt_compare(fills, [_recovered(), _native_close()])
    assert verdict["value"] == "RECONCILED"
    assert [m["order_id"] for m in verdict["evidence"]["fills_matched_to_adopted_events"]] == [1001, 1002]


# --- F1 on momentum #118: an adopted interrupted entry is TWO records of ONE opening ---
def _both_types_compare(positions, events):
    state = {**_adopt_state([]), "positions": positions}
    return exchange_ledger_compare(
        state, events, is_paper=_seykota_style_paper, norm_symbol=norm_symbol_plain,
        open_event_types=frozenset({"trade_open", "position_recovered"}), include_pending_markers=False, now=NOW,
    )


def _held_btc(qty):
    return {"symbol": "BTCUSDT", "side": "long", "quantity": qty}


def _trade_open_row(trade_id="BTCUSDT-adopted-1", qty=0.002, ms=None, **over):
    event = {"event_type": "trade_open", "symbol": "BTCUSDT", "side": "long", "volume": qty,
             "price": 84593.6, "order_id": "7001", "execution_mode": "DEMO", "source": "exchange_fill",
             "trade_id": trade_id, "event_id": "o1", "recovered_from_attempt_event_id": "a1",
             "event_epoch_ms": ms if ms is not None else _ADOPT_T0 + 18_000}
    event.update(over)
    return event


def test_recovered_plus_trade_open_of_one_trade_counts_once_while_open():
    events = [_recovered(order_id="7001"), _trade_open_row()]
    verdict = _both_types_compare([_held_btc(0.002)], events)
    assert verdict["evidence"]["position_diffs"] == []


def test_recovered_plus_trade_open_of_one_trade_counts_once_after_the_close():
    close = _native_close(order_id="7002")
    events = [_recovered(order_id="7001"), _trade_open_row(), close]
    verdict = _both_types_compare([], events)
    assert verdict["evidence"]["position_diffs"] == []


def test_two_separate_trade_opens_still_both_count():
    """Adds are not duplicates: only a recovered row that shares a trade_id with a trade_open is collapsed."""
    events = [_trade_open_row(trade_id="t1", qty=0.002, event_id="o1", order_id="7001"),
              _trade_open_row(trade_id="t1", qty=0.003, event_id="o2", order_id="7002", ms=_ADOPT_T0 + 30_000)]
    verdict = _both_types_compare([_held_btc(0.005)], events)
    assert verdict["evidence"]["position_diffs"] == []


def test_a_recovered_row_of_another_trade_still_counts():
    events = [_recovered(order_id="7001", trade_id="adopt-A"), _trade_open_row(trade_id="own-B", qty=0.003)]
    verdict = _both_types_compare([_held_btc(0.005)], events)
    assert verdict["evidence"]["position_diffs"] == []


def test_a_recovered_row_without_a_trade_id_is_never_assumed_to_be_a_duplicate():
    events = [_recovered(order_id="7001", trade_id=None), _trade_open_row(trade_id="own-B", qty=0.002)]
    verdict = _both_types_compare([_held_btc(0.002)], events)
    assert [(d["ledger_qty"], d["exchange_qty"]) for d in verdict["evidence"]["position_diffs"]] == [(0.004, 0.002)]


def test_the_collapse_does_not_hide_a_real_missing_position():
    events = [_recovered(order_id="7001"), _trade_open_row()]
    verdict = _both_types_compare([], events)
    assert [(d["ledger_qty"], d["exchange_qty"]) for d in verdict["evidence"]["position_diffs"]] == [(0.002, 0.0)]
    assert verdict["value"] == "DIVERGED"


def test_a_trade_open_newer_than_the_snapshot_does_not_erase_the_recovered_row():
    """The snapshot sits between the two writes: only what is at or before the snapshot counts."""
    events = [_recovered(order_id="7001"), _trade_open_row(ms=FETCHED_MS + 60_000)]
    verdict = _both_types_compare([_held_btc(0.002)], events)
    assert verdict["evidence"]["position_diffs"] == []
