import json
from pathlib import Path

import pytest

from trade_alerts.fleet_event_log import (
    FLEET_EVENT_KIND,
    PROJECT_CODE_PREFIXES,
    FleetEventLogError,
    append_fleet_event,
    catalog_code,
    catalog_entry,
    exclusive_log_lock,
    load_error_catalog,
    read_fleet_events,
    read_jsonl,
    risk_tier_for,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = REPO_ROOT / "src" / "trade_alerts" / "catalog" / "fleet-error-catalog-v1.json"
CATALOG = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
SCHEMA = json.loads((REPO_ROOT / "schemas" / "fleet-event-log-v1.schema.json").read_text(encoding="utf-8"))

jsonschema = pytest.importorskip("jsonschema")


def test_appends_are_canonical_single_lines(tmp_path):
    path = tmp_path / "audit" / "fleet_events.jsonl"
    first = append_fleet_event(
        path,
        project="seykota",
        code="RECONCILE_DELTA_EXCEEDED",
        summary="單筆對帳差額超過容忍值",
        risk_tier="R0",
        measurements={"delta_usdt": 12.5, "tolerance_usdt": 5.0},
    )
    second = append_fleet_event(path, project="seykota", code="TRADE_EXIT")

    assert path.exists()
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["event_id"] == first["event_id"]
    assert first["event_id"] != second["event_id"]
    assert read_fleet_events(path) == [first, second]


def test_every_stored_event_validates_against_the_published_schema(tmp_path):
    path = tmp_path / "fleet_events.jsonl"
    append_fleet_event(
        path,
        project="momentum",
        code="PROTECTION_UNVERIFIED",
        summary="原生移動停損無法驗證",
        risk_tier="R4",
        evidence={"trade_id": "t-1", "symbol": "BTC_USDT"},
        details={"expected_order_id": "o-9"},
        measurements={"observed_orders": 0},
    )
    append_fleet_event(path, project="fleet", code="LEDGER_DIVERGED_UNIT_EXIT")
    for record in read_jsonl(path):
        jsonschema.validate(record, SCHEMA)


def test_defaults_are_present_and_empty_rather_than_absent(tmp_path):
    record = append_fleet_event(tmp_path / "log.jsonl", project="btc-competition", code="REBALANCE_PENDING")
    assert record["kind"] == FLEET_EVENT_KIND
    assert record["risk_tier"] is None
    assert record["evidence"] == {} and record["details"] == {} and record["measurements"] == {}
    assert record["summary"] == ""


def test_unknown_project_tier_and_prefixed_code_are_refused(tmp_path):
    path = tmp_path / "log.jsonl"
    with pytest.raises(FleetEventLogError, match="unknown project"):
        append_fleet_event(path, project="mystery", code="X")
    with pytest.raises(FleetEventLogError, match="unknown risk tier"):
        append_fleet_event(path, project="seykota", code="X", risk_tier="R9")
    with pytest.raises(FleetEventLogError, match="bare condition name"):
        append_fleet_event(path, project="seykota", code="SEY.TRADE_EXIT")
    with pytest.raises(FleetEventLogError, match="code is required"):
        append_fleet_event(path, project="seykota", code="")
    with pytest.raises(FleetEventLogError, match="evidence must be a mapping"):
        append_fleet_event(path, project="seykota", code="X", evidence=["not", "a", "mapping"])
    with pytest.raises(FleetEventLogError, match="canonical JSON"):
        append_fleet_event(path, project="seykota", code="X", measurements={"delta": float("inf")})
    assert not path.exists(), "a rejected event must not leave a partial line behind"


def test_a_malformed_line_fails_the_read_rather_than_being_skipped(tmp_path):
    path = tmp_path / "log.jsonl"
    append_fleet_event(path, project="seykota", code="TRADE_EXIT")
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{not json}\n")
    with pytest.raises(FleetEventLogError, match="malformed JSON at line 2"):
        read_fleet_events(path)


def test_read_of_a_missing_log_is_empty_not_an_error(tmp_path):
    assert read_fleet_events(tmp_path / "never-written.jsonl") == []


def test_appending_inside_the_shared_lock_does_not_wait_on_itself(tmp_path):
    """The queue reads then appends under one lock; that must not deadlock."""
    path = tmp_path / "log.jsonl"
    with exclusive_log_lock(path):
        assert read_fleet_events(path) == []
        append_fleet_event(path, project="seykota", code="TRADE_EXIT")
    assert len(read_fleet_events(path)) == 1
    assert (tmp_path / "log.jsonl.lock").exists()


def test_prefix_table_reproduces_every_published_catalog_code():
    """The project->prefix table cannot drift away from the published catalog."""
    for entry in CATALOG["entries"]:
        prefix, _, bare = entry["code"].partition(".")
        assert prefix, f"{entry['code']} has no project prefix"
        assert catalog_code(entry["project"], bare) == entry["code"]
    used = {entry["code"].split(".", 1)[0] for entry in CATALOG["entries"]}
    assert used <= set(PROJECT_CODE_PREFIXES.values())
    assert set(PROJECT_CODE_PREFIXES) == set(CATALOG["projects"])


def test_catalog_lookup_resolves_a_tier_from_a_bare_condition_name():
    catalog = load_error_catalog(CATALOG_PATH)
    assert risk_tier_for(catalog, "seykota", "PROTECTION_UNVERIFIED") == "R4"
    assert risk_tier_for(catalog, "seykota", "TRADE_EXIT") == "R0"
    assert catalog_entry(catalog, "seykota", "PROTECTION_PLACEMENT_FAILED_FLATTENED")["resume"] == "automatic"
    with pytest.raises(FleetEventLogError, match="no catalog entry"):
        risk_tier_for(catalog, "seykota", "NOT_A_REAL_CONDITION")


def test_load_error_catalog_rejects_a_document_that_is_not_a_catalog(tmp_path):
    path = tmp_path / "whatever.json"
    path.write_text(json.dumps({"entries": "nope"}), encoding="utf-8")
    with pytest.raises(FleetEventLogError, match="not a fleet error catalog"):
        load_error_catalog(path)
