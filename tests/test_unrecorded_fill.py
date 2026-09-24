"""g1: unrecorded exchange fills -- correct only a certain duplicate send.

The main scenario is the real 2026-09-21 incident (the h4 fixture): order
1142206692162 was a second send of 1142206675339 under the same clientOrderId,
and the native stop's exit 1144042776223 was never recorded either.  h4 fixed
it by hand; here the handler must reach the same correction on its own.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from trade_alerts import (
    TRADE_CORRECTION_EVENT,
    build_trade_correction,
    UnrecordedFillAdapter,
    UnrecordedFillPaths,
    exchange_ledger_compare,
    load_error_catalog,
    read_ledger,
    run_unrecorded_fill_round,
)
from trade_alerts.error_request_queue import outstanding_error_requests
from trade_alerts.fleet_event_log import read_fleet_events
from trade_alerts.ledger_reconcile import is_paper_event, norm_symbol_plain
from trade_alerts.unrecorded_fill import (
    CODE_CORRECTED,
    CODE_UNRESOLVED,
    LOOKUP_GRACE_MS,
    unrecorded_orders,
)

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "seykota_duplicate_entry_20260921.json").read_text("utf-8")
)
LEDGER = FIXTURE["ledger"]
STATE = FIXTURE["exchange_state"]
NOW = datetime(2026, 9, 24, 5, 30, 30, tzinfo=timezone.utc)
TRADE_B = "BTCUSDT-1142206675339"
DUPLICATE, ORIGINAL, EXIT = "1142206692162", "1142206675339", "1144042776223"
ORDERS_B = {ORIGINAL, DUPLICATE, "1143212109561", EXIT}
CATALOG = load_error_catalog()


def _client_ids(**overrides: str | None) -> dict[str, str | None]:
    ids = {str(f["order_id"]): f"sk-{f['order_id']}" for f in STATE["fills"]}
    ids[DUPLICATE] = ids[ORIGINAL]  # the 09-21 duplicate send
    ids.update(overrides)
    return ids


class Exchange:
    def __init__(self, client_ids: dict[str, str | None], *, fail_lookup: bool = False) -> None:
        self.client_ids = client_ids
        self.fail_lookup = fail_lookup
        self.lookups: list[str] = []

    def client_order_id(self, _symbol: str, order_id: str) -> str | None:
        self.lookups.append(order_id)
        if self.fail_lookup:
            raise ConnectionError("read timed out")
        return self.client_ids.get(order_id)

    def fetch_fills(self, _symbol: str, order_ids: list[str]) -> list[dict]:
        return [dict(f) for f in STATE["fills"] if str(f["order_id"]) in set(order_ids)]


def _setup(tmp_path: Path, ledger=LEDGER) -> UnrecordedFillPaths:
    paths = UnrecordedFillPaths(
        ledger=str(tmp_path / "ledger.jsonl"), ledger_status=str(tmp_path / "ledger_status.json"),
        fleet_event_log=str(tmp_path / "fleet.jsonl"), request_queue=str(tmp_path / "requests.jsonl"),
        evidence_dir=str(tmp_path / "evidence"), ops_export=str(tmp_path / "ops_export.json"),
    )
    Path(paths.ledger).write_text("".join(json.dumps(e) + "\n" for e in ledger), encoding="utf-8")
    status = exchange_ledger_compare(STATE, ledger, is_paper=is_paper_event, norm_symbol=norm_symbol_plain, now=NOW)
    Path(paths.ledger_status).write_text(json.dumps(status), encoding="utf-8")
    return paths


def _trade_adapter(paths: UnrecordedFillPaths, exchange: Exchange, *, append=None, **kw) -> UnrecordedFillAdapter:
    written: list[str] = []

    def append_trade_correction(fields: dict) -> str:
        event_id = f"corr-{len(written) + 1}"
        with open(paths.ledger, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"event_type": TRADE_CORRECTION_EVENT, "event_id": event_id,
                                 "event_epoch_ms": 1790200000000, **fields}) + "\n")
        written.append(event_id)
        return event_id

    return UnrecordedFillAdapter(
        project="seykota", style="trade", client_ids=True, evidence_source="fixture",
        client_order_id=exchange.client_order_id, fetch_fills=exchange.fetch_fills,
        append_trade_correction=append or append_trade_correction,
        after_trade_correction=lambda fields, event_id: {"queued": event_id},
        owns_client_order_id=kw.pop("owns", lambda cid: cid.startswith("sk-")), **kw,
    )


def _round(adapter, paths, now=NOW):
    return run_unrecorded_fill_round(adapter, paths, catalog=CATALOG, now=now)


def _codes(paths):
    return [e["code"] for e in read_fleet_events(paths.fleet_event_log)]


# --------------------------------------------------------------------------- #
def test_the_fixture_shows_both_unrecorded_orders():
    status = exchange_ledger_compare(STATE, LEDGER, is_paper=is_paper_event, norm_symbol=norm_symbol_plain, now=NOW)
    assert [o["order_id"] for o in unrecorded_orders(status, LEDGER)] == [DUPLICATE, EXIT]


def test_a_certain_duplicate_send_is_corrected_like_the_manual_h4_fix(tmp_path):
    paths = _setup(tmp_path)
    result = _round(_trade_adapter(paths, Exchange(_client_ids())), paths)

    assert result["unresolved"] == []
    [done] = result["corrected"]
    assert done["trade_id"] == TRADE_B and set(done["order_ids"]) == {DUPLICATE, EXIT}
    correction = [e for e in read_ledger(paths.ledger) if e.get("event_type") == TRADE_CORRECTION_EVENT]
    assert len(correction) == 1
    c = correction[0]
    assert set(c["exchange_order_ids"]) == ORDERS_B
    assert c["reason_code"] == "DUPLICATE_ENTRY_UNRECORDED"
    assert c["corrected"]["exit_volume"] == pytest.approx(0.011)
    assert c["corrected"]["net_pnl"] == pytest.approx(-13.233, abs=5e-4)  # h4: -10.387 -> -13.233
    # R3 notice, no request: the ledger is right; the human chases the bug.
    [event] = read_fleet_events(paths.fleet_event_log)
    assert event["code"] == CODE_CORRECTED and event["risk_tier"] == "R3"
    assert "重複送單" in event["details"]["notice_text"]
    assert event["details"]["post"] == {"queued": "corr-1"}
    assert outstanding_error_requests(paths.request_queue) == []
    assert json.loads(Path(paths.ops_export).read_text())["notices"][0]["code"] == "SEY." + CODE_CORRECTED


def test_the_next_round_finds_nothing_left_to_do(tmp_path):
    paths = _setup(tmp_path)
    adapter = _trade_adapter(paths, Exchange(_client_ids()))
    _round(adapter, paths)
    again = _round(adapter, paths)  # ledger_status is still the stale DIVERGED one
    assert again["unrecorded_orders"] == [] and again["corrected"] == []
    assert _codes(paths) == [CODE_CORRECTED]


def test_a_hand_placed_order_in_the_same_trade_blocks_the_whole_correction(tmp_path):
    """PR #67 review: the duplicate is certain, but another unrecorded order in
    the trade's window came from the app.  Even if every fill balances, the
    ledger is not written."""
    paths = _setup(tmp_path)
    exchange = Exchange(_client_ids(**{EXIT: "web_Xk2pQ9manual"}))
    result = _round(_trade_adapter(paths, exchange), paths)

    assert result["corrected"] == []
    [u] = result["unresolved"]
    assert u["reason_code"] == "UNATTRIBUTED_ORDERS" and set(u["order_ids"]) == {DUPLICATE, EXIT}
    assert not any(e.get("event_type") == TRADE_CORRECTION_EVENT for e in read_ledger(paths.ledger))
    assert _codes(paths) == [CODE_UNRESOLVED]
    [request] = outstanding_error_requests(paths.request_queue)
    assert set(request["details"]["order_ids"]) == {DUPLICATE, EXIT}
    again = _round(_trade_adapter(paths, exchange), paths)  # one incident, one notice
    assert again["unresolved"] == [] and _codes(paths) == [CODE_UNRESOLVED]


def test_without_an_ownership_rule_no_other_order_can_be_folded_in(tmp_path):
    paths = _setup(tmp_path)
    result = _round(_trade_adapter(paths, Exchange(_client_ids()), owns=None), paths)
    assert result["corrected"] == []
    assert [u["reason_code"] for u in result["unresolved"]] == ["UNATTRIBUTED_ORDERS"]
    assert not any(e.get("event_type") == TRADE_CORRECTION_EVENT for e in read_ledger(paths.ledger))


def test_a_fill_of_unknown_origin_is_never_written(tmp_path):
    paths = _setup(tmp_path)
    exchange = Exchange(_client_ids(**{DUPLICATE: "web_manual_123"}))  # e.g. placed by hand in the app
    result = _round(_trade_adapter(paths, exchange), paths)

    assert result["corrected"] == []
    assert [(u["order_id"], u["reason_code"]) for u in result["unresolved"]] == [
        (DUPLICATE, "ORIGIN_UNKNOWN"), (EXIT, "ORIGIN_UNKNOWN")]
    assert not any(e.get("event_type") == TRADE_CORRECTION_EVENT for e in read_ledger(paths.ledger))
    assert _codes(paths) == [CODE_UNRESOLVED, CODE_UNRESOLVED]
    assert len(outstanding_error_requests(paths.request_queue)) == 2


def test_an_open_request_is_not_notified_again(tmp_path):
    paths = _setup(tmp_path)
    adapter = _trade_adapter(paths, Exchange(_client_ids(**{DUPLICATE: "web_manual_123"})))
    _round(adapter, paths)
    again = _round(adapter, paths)
    assert again["unresolved"] == [] and {a["order_id"] for a in again["awaiting_human"]} == {DUPLICATE, EXIT}
    assert len(_codes(paths)) == 2


def test_a_request_is_withdrawn_once_the_ledger_accounts_for_the_order(tmp_path):
    paths = _setup(tmp_path)
    exchange = Exchange(_client_ids(**{DUPLICATE: "web_manual_123"}))
    _round(_trade_adapter(paths, exchange), paths)
    assert len(outstanding_error_requests(paths.request_queue)) == 2
    # A human corrects it with the manual tool (same builder the handler uses).
    fields = build_trade_correction(read_ledger(paths.ledger), trade_id=TRADE_B, fills=exchange.fetch_fills("", sorted(ORDERS_B)),
                                    reason_code="UNRECORDED_FILL", reason="manual", evidence_source="fixture")
    with open(paths.ledger, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"event_type": TRADE_CORRECTION_EVENT, "event_id": "manual", **fields}) + "\n")

    result = _round(_trade_adapter(paths, exchange), paths)
    assert {w["order_id"] for w in result["withdrawn"]} == {DUPLICATE, EXIT}
    assert outstanding_error_requests(paths.request_queue) == []


def test_a_duplicate_whose_trade_is_still_open_is_left_to_the_human(tmp_path):
    ledger = [e for e in LEDGER if not (e.get("trade_id") == TRADE_B and e["event_type"] != "trade_open")]
    paths = _setup(tmp_path, ledger)
    result = _round(_trade_adapter(paths, Exchange(_client_ids())), paths)

    assert result["corrected"] == []
    assert result["unresolved"][0]["reason_code"] == "POSITION_OPEN"
    assert "減倉由你決定" in read_fleet_events(paths.fleet_event_log)[0]["details"]["notice_text"]
    assert not any(e.get("event_type") == TRADE_CORRECTION_EVENT for e in read_ledger(paths.ledger))


def test_fills_that_cannot_restate_the_trade_are_left_to_the_human(tmp_path):
    paths = _setup(tmp_path)
    exchange = Exchange(_client_ids())
    exchange.fetch_fills = lambda _s, ids: [dict(f) for f in STATE["fills"] if str(f["order_id"]) in set(ids) and str(f["order_id"]) != EXIT]
    result = _round(_trade_adapter(paths, exchange), paths)

    assert result["corrected"] == []
    [u] = result["unresolved"]
    assert u["reason_code"] == "NOT_RESTATABLE" and set(u["order_ids"]) == {DUPLICATE, EXIT}
    assert len(outstanding_error_requests(paths.request_queue)) == 1  # one incident, one request


def test_a_strategy_without_client_ids_only_reports(tmp_path):
    paths = _setup(tmp_path)
    exchange = Exchange(_client_ids())
    adapter = UnrecordedFillAdapter(project="mycrypto", style="trade", client_ids=False, evidence_source="fixture")
    result = _round(adapter, paths)
    assert [u["reason_code"] for u in result["unresolved"]] == ["NO_CLIENT_IDS", "NO_CLIENT_IDS"]
    assert exchange.lookups == []
    assert {e["code"] for e in read_fleet_events(paths.fleet_event_log)} == {CODE_UNRESOLVED}


def test_a_failed_lookup_is_retried_silently_then_reported(tmp_path):
    paths = _setup(tmp_path)
    adapter = _trade_adapter(paths, Exchange(_client_ids(), fail_lookup=True))
    duplicate_fill_ms = next(f["time_ms"] for f in STATE["fills"] if str(f["order_id"]) == DUPLICATE)

    young = datetime.fromtimestamp((duplicate_fill_ms + LOOKUP_GRACE_MS - 60_000) / 1000, timezone.utc)
    first = _round(adapter, paths, now=young)
    assert first["unresolved"] == [] and len(first["deferred"]) == 2
    assert _codes(paths) == []

    later = _round(adapter, paths, now=NOW)
    assert [u["reason_code"] for u in later["unresolved"]] == ["LOOKUP_FAILED", "LOOKUP_FAILED"]


def test_a_failed_write_is_reported_and_never_retried(tmp_path):
    paths = _setup(tmp_path)

    def broken(_fields):
        raise OSError("disk full")

    adapter = _trade_adapter(paths, Exchange(_client_ids()), append=broken)
    result = _round(adapter, paths)
    assert [u["reason_code"] for u in result["unresolved"]] == ["WRITE_FAILED"]
    again = _round(adapter, paths)
    assert again["corrected"] == [] and again["unresolved"] == []
    assert _codes(paths) == [CODE_UNRESOLVED]


def test_nothing_happens_unless_the_verdict_is_diverged(tmp_path):
    paths = _setup(tmp_path)
    Path(paths.ledger_status).write_text(json.dumps({"value": "RECONCILED", "evidence": {}}), encoding="utf-8")
    exchange = Exchange(_client_ids())
    result = _round(_trade_adapter(paths, exchange), paths)
    assert result["unrecorded_orders"] == [] and exchange.lookups == []


def test_the_catalog_carries_every_code_an_adapter_can_emit():
    tiers = {e["code"]: e["risk_tier"] for e in CATALOG["entries"]}
    for prefix in ("SEY", "MOM", "BTC"):
        for code in (CODE_CORRECTED, CODE_UNRESOLVED):
            assert tiers[f"{prefix}.{code}"] == "R3"
    assert any(e["code"] == "MYC." + CODE_UNRESOLVED for e in CATALOG["entries"])
    assert not any(e["code"] == "MYC." + CODE_CORRECTED for e in CATALOG["entries"])


def test_an_adapter_that_corrects_must_say_how():
    with pytest.raises(ValueError, match="append_trade_correction"):
        UnrecordedFillAdapter(project="seykota", style="trade", client_ids=True, evidence_source="x",
                              client_order_id=lambda s, o: None, fetch_fills=lambda s, o: [])


# --- spot (btc-competition) -------------------------------------------------- #
def _spot_setup(tmp_path: Path):
    t0 = 1790200000000
    ledger = [{"event_type": "spot_fill", "event_id": "f1", "order_id": "501", "symbol": "ETHUSDT",
               "execution_mode": "LIVE", "event_epoch_ms": t0, "side": "buy", "quantity": 0.1}]
    state = {"schema_version": "reconcile-source/v1", "fetched_at": "2026-09-24T12:00:00Z",
             "fetch_status": {"complete": True, "errors": []}, "positions": [],
             "fills": [{"order_id": 501, "side": "buy", "quantity": 0.1, "price": 2600, "time_ms": t0,
                        "symbol": "ETHUSDT", "commission": 0.1, "commission_asset": "USDT"},
                       {"order_id": 502, "side": "buy", "quantity": 0.1, "price": 2601, "time_ms": t0 + 800,
                        "symbol": "ETHUSDT", "commission": 0.1, "commission_asset": "USDT"}]}
    paths = UnrecordedFillPaths(
        ledger=str(tmp_path / "ledger.jsonl"), ledger_status=str(tmp_path / "ledger_status.json"),
        fleet_event_log=str(tmp_path / "fleet.jsonl"), request_queue=str(tmp_path / "requests.jsonl"),
        evidence_dir=str(tmp_path / "evidence"), ops_export=str(tmp_path / "ops_export.json"),
    )
    Path(paths.ledger).write_text("".join(json.dumps(e) + "\n" for e in ledger), encoding="utf-8")
    status = {"value": "DIVERGED", "evidence": {"unmatched_exchange_fills": [
        {k: state["fills"][1][k] for k in ("order_id", "symbol", "time_ms", "quantity", "price", "side")}]}}
    Path(paths.ledger_status).write_text(json.dumps(status), encoding="utf-8")
    return paths, state


def test_a_spot_duplicate_send_is_recorded_from_its_fills(tmp_path):
    paths, state = _spot_setup(tmp_path)
    client = {"501": "btc-a", "502": "btc-a"}

    def append_spot_fills(symbol, order_id, fills):
        with open(paths.ledger, "a", encoding="utf-8") as fh:
            for f in fills:
                fh.write(json.dumps({"event_type": "spot_fill", "event_id": f"x{order_id}", "order_id": order_id,
                                     "symbol": symbol, "quantity": f["quantity"]}) + "\n")
        return {"event_ids": [f"x{order_id}"]}

    adapter = UnrecordedFillAdapter(
        project="btc-competition", style="spot", client_ids=True, evidence_source="fixture",
        client_order_id=lambda _s, oid: client.get(oid),
        fetch_fills=lambda _s, ids: [f for f in state["fills"] if str(f["order_id"]) in ids],
        append_spot_fills=append_spot_fills,
    )
    result = run_unrecorded_fill_round(adapter, paths, catalog=CATALOG, now=NOW)
    assert [c["order_ids"] for c in result["corrected"]] == [["502"]]
    assert [e["order_id"] for e in read_ledger(paths.ledger) if e["event_type"] == "spot_fill"] == ["501", "502"]
    assert _codes(paths) == [CODE_CORRECTED]
