"""The shared verified-close repair runner (fleet-error-catalog/v2).

Every test drives ``run_repair_round`` end to end against files in a temp
directory, with a fake adapter in place of the exchange: what is asserted is
what lands in the ledger, the fleet event log, the request queue and
``ops_export.json`` -- the four things a strategy host actually keeps.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from trade_alerts import (
    RUNNER_CODES,
    PositionStillOpen,
    RepairAdapter,
    RepairPaths,
    build_evidence,
    catalog_entry,
    find_open_event,
    load_error_catalog,
    outstanding_error_requests,
    pause_env_name,
    read_fleet_events,
    read_ledger,
    record_request_outcome,
    repair_paused,
    run_repair_round,
)
from trade_alerts import repair_runner
from trade_alerts.fleet_event_log import FleetEventLogError

OPENED_MS = 1788408032535


def _open(trade_id="T1", symbol="PUFFER_USDT", side="long"):
    return {
        "event_id": f"open-{trade_id}", "event_type": "trade_open", "trade_id": trade_id, "symbol": symbol,
        "side": side, "volume": 27376.0, "price": 0.0183, "fee": 0.2504904, "contract_size": 1.0, "leverage": 3,
        "event_epoch_ms": OPENED_MS,
    }


def _fill(*, realized_pnl="-23.81712", side="sell", time_ms=OPENED_MS + 2_400_000):
    return {"trade_id": "900", "order_id": "222798734", "price": "0.01743", "quantity": "27376",
            "commission": "0.23858184", "realized_pnl": realized_pnl, "time_ms": time_ms, "side": side}


class _Ledger:
    """A strategy's own ledger writer: one JSON line per append."""

    def __init__(self, path):
        self.path = Path(path)

    def append(self, event_type, **fields):
        event_id = f"{event_type}-{fields.get('trade_id')}"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"event_id": event_id, "event_type": event_type, "writer": "strategy",
                                     **fields}) + "\n")
        return event_id


class _Exchange:
    """Fake adapter. ``script[trade_id]`` is a list consumed one item per
    fetch: a list of fills, ``"open"`` (still holding the position), or an
    exception instance to raise. The last item repeats."""

    def __init__(self, ledger_path, script):
        self.ledger_path = ledger_path
        self.script = script
        self.fetches: list[str] = []
        self.projections: list[str] = []
        self.projection_error: Exception | None = None
        self.staging_error: Exception | None = None

    def fetch(self, trade_id):
        self.fetches.append(trade_id)
        steps = self.script[trade_id]
        step = steps.pop(0) if len(steps) > 1 else steps[0]
        if step == "open":
            raise PositionStillOpen(f"{trade_id} still open")
        if isinstance(step, Exception):
            raise step
        return build_evidence(
            open_event=find_open_event(read_ledger(self.ledger_path), trade_id), sell_fills=step,
            trailing_order_id=None, artifact_name="binance_user_trades:PUFFERUSDT",
            method="read_only_binance_user_trades",
        )

    def staging(self, path):
        if self.staging_error is not None:
            raise self.staging_error
        return _Ledger(path).append

    def project(self, trade_id):
        if self.projection_error is not None:
            raise self.projection_error
        self.projections.append(trade_id)
        return f"intent-{trade_id}"

    def adapter(self, project="momentum"):
        return RepairAdapter(project=project, fetch_evidence=self.fetch, staging_ledger=self.staging,
                             queue_projection=self.project)


@pytest.fixture
def host(tmp_path):
    audit = tmp_path / "audit"
    audit.mkdir()
    paths = RepairPaths(
        ledger=str(audit / "trading_ledger.jsonl"), ledger_status=str(audit / "ledger_status.json"),
        fleet_event_log=str(audit / "fleet_event_log.jsonl"), request_queue=str(audit / "error_requests.jsonl"),
        evidence_dir=str(audit / "verified-close-evidence"), ops_export=str(audit / "ops_export.json"),
    )
    return paths


def _seed(paths, *opens):
    with open(paths.ledger, "a", encoding="utf-8") as handle:
        for event in opens:
            handle.write(json.dumps(event) + "\n")
    Path(paths.ledger_status).write_text(json.dumps({
        "value": "DIVERGED",
        "evidence": {"position_diffs": [{"symbol": event["symbol"]} for event in opens]},
    }), encoding="utf-8")


def _events(paths, code=None):
    return [event for event in read_fleet_events(paths.fleet_event_log) if code is None or event["code"] == code]


def _export(paths):
    return json.loads(Path(paths.ops_export).read_text(encoding="utf-8"))


def _round(exchange, paths, **kwargs):
    kwargs.setdefault("paused", False)
    return run_repair_round(exchange.adapter(kwargs.pop("project", "momentum")), paths, **kwargs)


FAILED, REPAIRED, BLOCKED = "VERIFIED_CLOSE_REPAIR_FAILED", "VERIFIED_CLOSE_AUTO_REPAIRED", "VERIFIED_CLOSE_REPAIR_BLOCKED"
WRONG_SIDE = [_fill(side="buy")]  # a long closed by a BUY: structurally not this trade's close


# --------------------------------------------------------------------------- #
# R1: repaired, silently
# --------------------------------------------------------------------------- #
def test_a_clean_orphan_is_written_through_the_strategys_writer_and_nobody_is_told(host):
    _seed(host, _open())
    exchange = _Exchange(host.ledger, {"T1": [[_fill()]]})

    result = _round(exchange, host)

    assert [item["trade_id"] for item in result["repaired"]] == ["T1"]
    rows = read_ledger(host.ledger)
    assert [row["event_type"] for row in rows] == [
        "trade_open", "reconciliation_evidence_recorded", "fill", "trade_close", "position_reconciled_closed",
    ]
    assert all(row["writer"] == "strategy" for row in rows[1:])
    assert exchange.projections == ["T1"]
    [event] = _events(host)
    assert (event["code"], event["risk_tier"]) == (REPAIRED, "R1")
    assert event["details"]["pnl_source"] == "local"
    assert event["measurements"]["net_pnl"] == rows[3]["net_pnl"]
    assert list(Path(host.evidence_dir).glob("T1-*.json"))
    assert outstanding_error_requests(host.request_queue) == []   # R1 never opens a request
    assert _export(host)["notices"] == []


def test_a_pnl_disagreement_is_written_with_the_exchanges_figure(host):
    _seed(host, _open())
    exchange = _Exchange(host.ledger, {"T1": [[_fill(realized_pnl="-20.0")]]})

    _round(exchange, host)

    close = read_ledger(host.ledger)[3]
    assert close["gross_pnl"] == -20.0
    assert close["reconciliation"]["pnl_source"] == "exchange_realized"
    [event] = _events(host)
    assert event["details"]["pnl_source"] == "exchange_realized"
    assert event["details"]["local_gross_pnl"] == close["reconciliation"]["local_gross_pnl"]
    assert _export(host)["notices"] == []


def test_a_short_position_is_repaired_with_a_buy_close(host):
    _seed(host, _open(side="short"))
    exchange = _Exchange(host.ledger, {"T1": [[_fill(side="buy", realized_pnl="23.81712")]]})

    assert [item["trade_id"] for item in _round(exchange, host)["repaired"]] == ["T1"]


def test_a_failed_projection_does_not_undo_the_repair(host):
    _seed(host, _open())
    exchange = _Exchange(host.ledger, {"T1": [[_fill()]]})
    exchange.projection_error = RuntimeError("outbox locked")

    result = _round(exchange, host)

    assert result["repaired"][0]["projection"] == {"error": "RuntimeError: outbox locked"}
    assert _events(host)[0]["details"]["projection"]["error"] == "RuntimeError: outbox locked"
    assert _export(host)["notices"] == []


# --------------------------------------------------------------------------- #
# ordering: one write per round, several orphans in turn
# --------------------------------------------------------------------------- #
def test_several_orphans_are_repaired_one_per_round_in_order(host):
    _seed(host, _open("T1", "AAA_USDT"), _open("T2", "BBB_USDT"))
    exchange = _Exchange(host.ledger, {"T1": [[_fill()]], "T2": [[_fill()]]})

    first = _round(exchange, host)
    assert [item["trade_id"] for item in first["repaired"]] == ["T1"]
    assert first["deferred"] == ["T2"]
    assert exchange.fetches == ["T1"]          # the deferred one is not even queried

    second = _round(exchange, host)
    assert [item["trade_id"] for item in second["repaired"]] == ["T2"]
    assert second["candidates"] == ["T2"]


def test_a_failing_orphan_does_not_hold_up_the_next_one(host):
    _seed(host, _open("T1", "AAA_USDT"), _open("T2", "BBB_USDT"))
    exchange = _Exchange(host.ledger, {"T1": [WRONG_SIDE], "T2": [[_fill()]]})

    result = _round(exchange, host)

    assert [item["trade_id"] for item in result["failed"]] == ["T1"]
    assert [item["trade_id"] for item in result["repaired"]] == ["T2"]


def test_a_position_still_open_is_not_a_failure(host):
    _seed(host, _open())
    exchange = _Exchange(host.ledger, {"T1": ["open"]})

    for _ in range(5):
        result = _round(exchange, host)

    assert result["still_open"] == [{"trade_id": "T1", "reason": "T1 still open"}]
    assert _events(host) == []
    assert outstanding_error_requests(host.request_queue) == []


# --------------------------------------------------------------------------- #
# R2: retry, escalate once on the Nth consecutive failure
# --------------------------------------------------------------------------- #
def test_structural_failures_escalate_on_the_third_and_notify_exactly_once(host):
    _seed(host, _open())
    exchange = _Exchange(host.ledger, {"T1": [WRONG_SIDE]})

    for expected_attempt in (1, 2):
        result = _round(exchange, host)
        assert result["failed"][0]["attempt"] == expected_attempt
        assert _export(host)["notices"] == []
    third = _round(exchange, host)

    assert third["escalated"][0]["attempt"] == 3
    events = _events(host, FAILED)
    assert [event["details"]["escalated"] for event in events] == [False, False, True]
    assert {event["risk_tier"] for event in events} == {"R2"}
    [request] = outstanding_error_requests(host.request_queue)
    assert (request["code"], request["risk_tier"]) == (FAILED, "R2")
    assert events[-1]["details"]["request_id"] == request["request_id"]
    [notice] = _export(host)["notices"]
    assert notice["code"] == "MOM.VERIFIED_CLOSE_REPAIR_FAILED" and notice["critical"] is False
    assert "給 AI 的追查指令" in notice["text"]
    assert "not this trade's close" in notice["text"]

    # rounds 4 and 5 keep trying, silently
    for _ in range(2):
        later = _round(exchange, host)
        assert later["failed"][0]["silent"] is True
    assert len(_events(host, FAILED)) == 3
    assert len(_export(host)["notices"]) == 1
    assert len(outstanding_error_requests(host.request_queue)) == 1


def test_an_exchange_that_cannot_be_queried_counts_as_a_failure(host):
    """Decision B (2026-09-22): otherwise a broken API key would never reach
    anyone."""
    _seed(host, _open())
    exchange = _Exchange(host.ledger, {"T1": [ConnectionError("api.binance.com timed out")]})

    for _ in range(3):
        result = _round(exchange, host)

    assert result["escalated"][0]["reasons"] == ["evidence fetch failed: ConnectionError: api.binance.com timed out"]
    assert len(_export(host)["notices"]) == 1


def test_a_still_open_round_neither_counts_nor_resets(host):
    _seed(host, _open())
    exchange = _Exchange(host.ledger, {"T1": [WRONG_SIDE, "open", WRONG_SIDE, WRONG_SIDE]})

    outcomes = [_round(exchange, host) for _ in range(4)]

    assert outcomes[1]["still_open"] and not outcomes[1]["failed"]
    assert outcomes[3]["escalated"][0]["attempt"] == 3


def test_a_later_success_after_escalating_closes_the_request_automatically(host):
    _seed(host, _open())
    exchange = _Exchange(host.ledger, {"T1": [WRONG_SIDE, WRONG_SIDE, WRONG_SIDE, [_fill()]]})

    for _ in range(3):
        _round(exchange, host)
    result = _round(exchange, host)

    assert [item["trade_id"] for item in result["repaired"]] == ["T1"]
    assert result["closed_requests"][0]["status"] == "RESOLVED_AUTO"
    assert outstanding_error_requests(host.request_queue) == []
    assert _export(host)["open_requests"] == []


def test_a_request_is_withdrawn_once_someone_writes_the_close_by_hand(host):
    _seed(host, _open())
    exchange = _Exchange(host.ledger, {"T1": [WRONG_SIDE]})
    for _ in range(3):
        _round(exchange, host)
    with open(host.ledger, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"event_type": "trade_close", "trade_id": "T1", "symbol": "PUFFER_USDT"}) + "\n")

    result = _round(exchange, host)

    assert result["closed_requests"] == [
        {"request_id": result["closed_requests"][0]["request_id"], "code": FAILED, "trade_id": "T1",
         "status": "WITHDRAWN"},
    ]
    assert result["candidates"] == []
    assert outstanding_error_requests(host.request_queue) == []


def test_after_a_request_closes_a_recurrence_counts_from_zero(host):
    """Nothing but an escalation resets the count, so a trade whose request
    was closed starts a fresh three-strike count if it diverges again."""
    _seed(host, _open())
    exchange = _Exchange(host.ledger, {"T1": [WRONG_SIDE]})
    for _ in range(3):
        _round(exchange, host)
    [request] = outstanding_error_requests(host.request_queue)
    record_request_outcome(host.request_queue, request_id=request["request_id"], status="RESOLVED_HUMAN")

    result = _round(exchange, host)

    assert result["failed"][0]["attempt"] == 1
    assert len(_export(host)["notices"]) == 1


# --------------------------------------------------------------------------- #
# R3: a ledger that is no longer clean, or a write that failed
# --------------------------------------------------------------------------- #
def _half_applied(incident_id="verified-close-backfill-T1"):
    return {"event_type": "fill", "trade_id": "T1", "symbol": "PUFFER_USDT",
            "reconciliation": {"incident_id": incident_id}}


def test_repair_traces_in_the_ledger_stop_the_runner_for_good(host):
    _seed(host, _open(), _half_applied())
    exchange = _Exchange(host.ledger, {"T1": [[_fill()]]})
    before = Path(host.ledger).read_text(encoding="utf-8")

    first = _round(exchange, host)

    assert first["blocked"][0]["reason"] == "the ledger already carries repair records for this trade"
    assert Path(host.ledger).read_text(encoding="utf-8") == before
    [event] = _events(host)
    assert (event["code"], event["risk_tier"]) == (BLOCKED, "R3")
    [request] = outstanding_error_requests(host.request_queue)
    assert (request["code"], request["risk_tier"]) == (BLOCKED, "R3")
    [notice] = _export(host)["notices"]
    assert notice["critical"] is True

    second = _round(exchange, host)
    assert second["awaiting_human"] == [{"trade_id": "T1", "request_id": request["request_id"]}]
    assert exchange.fetches == ["T1"]           # never queried again
    assert len(_events(host)) == 1


def test_a_failed_batch_write_stops_and_leaves_the_ledger_untouched(host):
    _seed(host, _open())
    exchange = _Exchange(host.ledger, {"T1": [[_fill()]]})
    exchange.staging_error = OSError("read-only file system")
    before = Path(host.ledger).read_text(encoding="utf-8")

    result = _round(exchange, host)

    assert "ledger write failed" in result["blocked"][0]["reason"]
    assert Path(host.ledger).read_text(encoding="utf-8") == before
    assert _events(host)[0]["code"] == BLOCKED
    assert exchange.projections == []


def test_an_escalated_failure_that_turns_into_a_stop_is_superseded(host):
    _seed(host, _open())
    exchange = _Exchange(host.ledger, {"T1": [WRONG_SIDE, WRONG_SIDE, WRONG_SIDE, [_fill()]]})
    for _ in range(3):
        _round(exchange, host)
    exchange.staging_error = OSError("disk full")

    result = _round(exchange, host)

    assert [item["status"] for item in result["closed_requests"]] == ["SUPERSEDED"]
    [request] = outstanding_error_requests(host.request_queue)
    assert request["code"] == BLOCKED


def test_a_blocked_trade_is_withdrawn_once_the_close_is_in_the_ledger(host):
    _seed(host, _open(), _half_applied())
    exchange = _Exchange(host.ledger, {"T1": [[_fill()]]})
    _round(exchange, host)
    with open(host.ledger, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"event_type": "trade_close", "trade_id": "T1", "symbol": "PUFFER_USDT"}) + "\n")

    result = _round(exchange, host)

    assert [item["status"] for item in result["closed_requests"]] == ["WITHDRAWN"]
    assert outstanding_error_requests(host.request_queue) == []


# --------------------------------------------------------------------------- #
# the brake, the export, configuration
# --------------------------------------------------------------------------- #
def test_paused_does_nothing_but_keep_the_export_fresh(host):
    _seed(host, _open())
    exchange = _Exchange(host.ledger, {"T1": [[_fill()]]})
    before = Path(host.ledger).read_text(encoding="utf-8")

    result = run_repair_round(exchange.adapter(), host, environ={"MOMENTUM_REPAIR_PAUSED": "true"})

    assert result["paused"] is True
    assert result["candidates"] == []
    assert exchange.fetches == []
    assert Path(host.ledger).read_text(encoding="utf-8") == before
    assert _events(host) == []
    assert result["ops_export_written"] is True
    assert _export(host)["project"] == "momentum"


@pytest.mark.parametrize("project, name", [
    ("momentum", "MOMENTUM_REPAIR_PAUSED"), ("seykota", "SEYKOTA_REPAIR_PAUSED"),
    ("mycrypto", "MYCRYPTO_REPAIR_PAUSED"), ("btc-competition", "BTC_COMPETITION_REPAIR_PAUSED"),
])
def test_one_brake_name_per_strategy(project, name):
    assert pause_env_name(project) == name


@pytest.mark.parametrize("value, paused", [("true", True), ("1", True), (" ON ", True), ("false", False),
                                           ("", False), (None, False)])
def test_brake_parsing(value, paused):
    environ = {} if value is None else {"SEYKOTA_REPAIR_PAUSED": value}
    assert repair_paused("seykota", environ) is paused


def test_an_export_that_cannot_be_written_does_not_break_the_round(host, tmp_path):
    _seed(host, _open())
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    paths = RepairPaths(**{**host.__dict__, "ops_export": str(blocker / "ops_export.json")})
    exchange = _Exchange(host.ledger, {"T1": [[_fill()]]})

    result = _round(exchange, paths)

    assert result["repaired"] and result["ops_export_written"] is False


def test_a_corrupt_event_log_stops_the_round_before_any_exchange_query(host):
    """The log is evidence: a round that cannot read it must not act on a
    partial view of what it already tried."""
    _seed(host, _open())
    Path(host.fleet_event_log).write_text("{not json\n", encoding="utf-8")
    exchange = _Exchange(host.ledger, {"T1": [[_fill()]]})

    with pytest.raises(FleetEventLogError):
        _round(exchange, host)
    assert exchange.fetches == []


def test_a_strategy_without_the_runner_codes_is_refused_before_anything_runs(host):
    _seed(host, _open())
    exchange = _Exchange(host.ledger, {"T1": [[_fill()]]})

    with pytest.raises(FleetEventLogError, match="no catalog entry for BTC.VERIFIED_CLOSE_AUTO_REPAIRED"):
        _round(exchange, host, project="btc-competition")
    assert exchange.fetches == []
    assert not Path(host.ops_export).exists()


def test_seykota_runs_the_same_round(host):
    """Pyramided entry, short side, seykota's own catalog codes."""
    entry = {**_open(side="short"), "volume": 27375.0}
    add = {**_open(side="short"), "event_id": "add-1", "volume": 1.0, "fee": 0.0,
           "event_epoch_ms": OPENED_MS + 60_000}
    _seed(host, entry, add)
    exchange = _Exchange(host.ledger, {"T1": [[_fill(side="buy", realized_pnl="23.81712")]]})

    result = _round(exchange, host, project="seykota")

    assert [item["trade_id"] for item in result["repaired"]] == ["T1"]
    assert _events(host)[0]["project"] == "seykota"
    assert read_ledger(host.ledger)[-2]["entry_volume"] == 27376.0
    assert _export(host)["project"] == "seykota"


def test_the_runner_codes_are_catalogued_the_same_for_every_strategy_that_runs_it():
    """The fleet rule: one capability, catalogued identically for each
    strategy using it -- or the rollout register shows one strategy's repair
    activity and hides the other's."""
    catalog = load_error_catalog()
    for code in RUNNER_CODES:
        mom, sey = (catalog_entry(catalog, project, code) for project in ("momentum", "seykota"))
        for key in ("verdict", "risk_tier", "resume"):
            assert mom[key] == sey[key], (code, key)
    tiers = {code: catalog_entry(catalog, "momentum", code)["risk_tier"] for code in RUNNER_CODES}
    assert tiers == {REPAIRED: "R1", FAILED: "R2", BLOCKED: "R3"}


def test_catalog_sources_in_this_repo_point_at_the_call_that_emits_the_code():
    """Catalog entries emitted by the runner cite ``trade-alerts/...:line``;
    an edit above that line would otherwise leave the citation pointing at
    some other statement."""
    root = Path(__file__).resolve().parents[1]
    cited = 0
    for entry in load_error_catalog()["entries"]:
        bare = entry["code"].split(".", 1)[1]
        for source in entry["sources"]:
            if not source.startswith("trade-alerts/"):
                continue
            path, _, line = source[len("trade-alerts/"):].rpartition(":")
            lines = (root / path).read_text(encoding="utf-8").splitlines()
            call = " ".join(lines[int(line) - 1:int(line) + 2])
            assert "append_fleet_event(" in call, source
            constant = next(name for name, value in vars(repair_runner).items()
                            if name.startswith("CODE_") and value == bare)
            assert f"code={constant}" in call, source
            cited += 1
    assert cited == 6
