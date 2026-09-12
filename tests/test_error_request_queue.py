import json
from pathlib import Path

import pytest

from trade_alerts.error_request_queue import (
    OUTCOME_KIND,
    REQUEST_KIND,
    REQUESTABLE_TIERS,
    TERMINAL_STATUSES,
    ErrorRequestError,
    find_error_request,
    open_error_request,
    outstanding_error_requests,
    record_request_outcome,
    request_fingerprint,
)
from trade_alerts.fleet_event_log import append_fleet_event, read_jsonl
from trade_alerts.safe_halt_model import build_safe_halt

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((REPO_ROOT / "catalog" / "fleet-error-catalog-v1.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((REPO_ROOT / "schemas" / "error-request-queue-v1.schema.json").read_text(encoding="utf-8"))

jsonschema = pytest.importorskip("jsonschema")

EVIDENCE = {"symbol": "BTCUSDT", "side": "long", "quantity": 0.01}


def _open(path, **overrides):
    payload = {
        "project": "seykota",
        "code": "PROTECTION_UNVERIFIED",
        "risk_tier": "R4",
        "summary": "交易所存在部位，但沒有可唯一確認的原生保護單",
        "evidence": EVIDENCE,
    }
    payload.update(overrides)
    return open_error_request(path, **payload)


def test_opening_a_request_records_code_tier_and_evidence(tmp_path):
    path = tmp_path / "audit" / "error_requests.jsonl"
    request = _open(path, measurements={"observed_stops": 0})
    assert request["project"] == "seykota"
    assert request["code"] == "PROTECTION_UNVERIFIED"
    assert request["risk_tier"] == "R4"
    assert request["evidence"] == EVIDENCE
    assert request["measurements"] == {"observed_stops": 0}
    assert request["fingerprint"] == request_fingerprint("seykota", "PROTECTION_UNVERIFIED", EVIDENCE)
    assert outstanding_error_requests(path) == [request]
    assert find_error_request(path, request["request_id"]) == request


def test_r0_conditions_can_never_open_a_request(tmp_path):
    """The catalog's R0 tier means the action after detection is fixed."""
    path = tmp_path / "queue.jsonl"
    with pytest.raises(ErrorRequestError, match="never open a request"):
        _open(path, code="TRADE_EXIT", risk_tier="R0")
    assert not path.exists()

    r0_codes = [entry for entry in CATALOG["entries"] if entry["risk_tier"] == "R0"]
    assert r0_codes, "the catalog is expected to classify some conditions as log-only"
    for entry in r0_codes:
        bare = entry["code"].split(".", 1)[1]
        with pytest.raises(ErrorRequestError, match="never open a request"):
            open_error_request(path, project=entry["project"], code=bare, risk_tier="R0")
    assert "R0" not in REQUESTABLE_TIERS


def test_the_same_problem_across_many_cycles_is_one_request(tmp_path):
    path = tmp_path / "queue.jsonl"
    first = _open(path)
    again = _open(path, summary="different wording, same facts")
    assert again["request_id"] == first["request_id"]
    assert len(outstanding_error_requests(path)) == 1
    assert len([record for record in read_jsonl(path) if record["kind"] == REQUEST_KIND]) == 1


def test_different_evidence_is_a_different_request(tmp_path):
    path = tmp_path / "queue.jsonl"
    first = _open(path)
    other = _open(path, evidence={**EVIDENCE, "quantity": 0.5})
    assert other["request_id"] != first["request_id"]
    assert len(outstanding_error_requests(path)) == 2


def test_a_resolved_condition_recurring_opens_a_second_request(tmp_path):
    path = tmp_path / "queue.jsonl"
    first = _open(path)
    record_request_outcome(path, request_id=first["request_id"], status="RESOLVED_HUMAN", note="operator cleared the latch")
    assert outstanding_error_requests(path) == []

    second = _open(path)
    assert second["request_id"] != first["request_id"]
    assert second["fingerprint"] == first["fingerprint"]
    assert [request["request_id"] for request in outstanding_error_requests(path)] == [second["request_id"]]


def test_closing_a_request_twice_is_refused(tmp_path):
    path = tmp_path / "queue.jsonl"
    request = _open(path)
    record_request_outcome(path, request_id=request["request_id"], status="RESOLVED_AUTO")
    with pytest.raises(ErrorRequestError, match="already closed"):
        record_request_outcome(path, request_id=request["request_id"], status="RESOLVED_HUMAN")
    assert len([record for record in read_jsonl(path) if record["kind"] == OUTCOME_KIND]) == 1


def test_unknown_status_or_request_is_refused(tmp_path):
    path = tmp_path / "queue.jsonl"
    request = _open(path)
    with pytest.raises(ErrorRequestError, match="unknown terminal status"):
        record_request_outcome(path, request_id=request["request_id"], status="MAYBE_LATER")
    with pytest.raises(ErrorRequestError, match="no request"):
        record_request_outcome(path, request_id="does-not-exist", status="WITHDRAWN")
    with pytest.raises(ErrorRequestError, match="no request"):
        find_error_request(path, "does-not-exist")


def test_unknown_project_prefixed_code_and_bad_evidence_are_refused(tmp_path):
    path = tmp_path / "queue.jsonl"
    with pytest.raises(ErrorRequestError, match="unknown project"):
        _open(path, project="mystery")
    with pytest.raises(ErrorRequestError, match="not the catalog code"):
        _open(path, code="SEY.PROTECTION_UNVERIFIED")
    with pytest.raises(ErrorRequestError, match="unknown risk tier"):
        _open(path, risk_tier="R7")
    with pytest.raises(ErrorRequestError, match="canonical JSON"):
        _open(path, evidence={"delta": float("nan")})
    assert not path.exists()


def test_outstanding_requests_come_back_oldest_first(tmp_path):
    path = tmp_path / "queue.jsonl"
    late = _open(path, evidence={"n": 2}, opened_at="2026-09-12T12:00:00Z")
    early = _open(path, evidence={"n": 1}, opened_at="2026-09-11T09:00:00Z")
    assert [request["request_id"] for request in outstanding_error_requests(path)] == [early["request_id"], late["request_id"]]


def test_every_stored_record_validates_against_the_published_schema(tmp_path):
    path = tmp_path / "queue.jsonl"
    request = _open(path, details={"heartbeat": "SAFE_HALT"}, event_ref="abc123")
    record_request_outcome(path, request_id=request["request_id"], status="SUPERSEDED", note="evidence moved", details={"replaced_by": "later"})
    for record in read_jsonl(path):
        jsonschema.validate(record, SCHEMA)
    assert set(SCHEMA["definitions"]["outcome"]["properties"]["status"]["enum"]) == TERMINAL_STATUSES


def test_a_request_opened_from_a_latch_shares_the_latch_evidence(tmp_path):
    """Opening a request about a latch keeps both keyed on the same facts."""
    path = tmp_path / "queue.jsonl"
    event_log = tmp_path / "fleet_events.jsonl"
    halt = build_safe_halt(code="PROTECTION_UNVERIFIED", reason="無法驗證原生保護單", evidence=EVIDENCE, details={"cycle": 41})
    event = append_fleet_event(
        event_log,
        project="seykota",
        code=halt["code"],
        risk_tier="R4",
        evidence=halt["evidence"],
        details=halt["details"],
    )
    request = _open(path, evidence=halt["evidence"], event_ref=event["event_id"])
    assert request["event_ref"] == event["event_id"]
    # The volatile half of the latch never reaches the deduplication key.
    assert request["fingerprint"] == request_fingerprint("seykota", halt["code"], EVIDENCE)


def test_non_canonical_details_and_measurements_are_queue_errors(tmp_path):
    """A caller catching ErrorRequestError must not see the log module's type."""
    path = tmp_path / "queue.jsonl"
    with pytest.raises(ErrorRequestError, match="not canonical JSON"):
        _open(path, details={"ratio": float("inf")})
    with pytest.raises(ErrorRequestError, match="not canonical JSON"):
        _open(path, measurements={"delta": float("nan")})
    assert not path.exists()

    request = _open(path)
    with pytest.raises(ErrorRequestError, match="not canonical JSON"):
        record_request_outcome(path, request_id=request["request_id"], status="WITHDRAWN", details={"x": float("nan")})
    assert outstanding_error_requests(path) == [request]
