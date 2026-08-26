from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from trade_alerts.ledger_integrity import LEDGER_PROJECTION_SCHEMA_VERSION, LedgerProvenance
from trade_alerts.projection_outbox import (
    RebuiltProjection,
    dispatch_next_projection,
    enqueue_projection_intent,
    outstanding_projection_intents,
)


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


@dataclass(frozen=True)
class Submission:
    status: str
    receiver_row: int | None = None
    error_code: str | None = None


def provenance(*, request_id: str | None = None, issued_at: str = "2026-08-26T00:00:00Z", payload_digest: str = DIGEST_B) -> LedgerProvenance:
    return LedgerProvenance(
        project_id="mexc-4h-momentum",
        trade_id="trade-001",
        event_type="trade_close",
        ledger_event_digest=DIGEST_A,
        payload_digest=payload_digest,
        request_id=request_id or str(uuid4()),
        issued_at=issued_at,
        source_id="momentum-wsl-prod",
        schema_version=LEDGER_PROJECTION_SCHEMA_VERSION,
    )


def rebuilt(intent, *, payload_digest: str = DIGEST_B) -> RebuiltProjection:
    proof = provenance(request_id="00000000-0000-4000-8000-000000000011", issued_at="2026-08-26T00:01:00Z", payload_digest=payload_digest)
    payload = {
        "schema_version": LEDGER_PROJECTION_SCHEMA_VERSION,
        "action": intent.action,
        "source_id": proof.source_id,
        "project_id": proof.project_id,
        "sheet_name": "mexc-4h-momentum-trailing-stop",
        "request_id": proof.request_id,
        "issued_at": proof.issued_at,
        "provenance": proof.as_dict(),
        "projection": {"trade_id": proof.trade_id},
        "signature": "0" * 64,
    }
    return RebuiltProjection(payload=payload, provenance=proof)


def test_enqueue_is_idempotent_for_same_immutable_ledger_projection(tmp_path: Path) -> None:
    path = tmp_path / "projection-outbox.jsonl"
    first = enqueue_projection_intent(path, action="update_close_v2", provenance=provenance())
    second = enqueue_projection_intent(path, action="update_close_v2", provenance=provenance(request_id=str(uuid4()), issued_at="2026-08-26T00:02:00Z"))

    assert second == first
    assert outstanding_projection_intents(path) == (first,)
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_confirmed_intent_is_not_dispatched_twice(tmp_path: Path) -> None:
    path = tmp_path / "projection-outbox.jsonl"
    intent = enqueue_projection_intent(path, action="update_close_v2", provenance=provenance())
    calls: list[str] = []

    result = dispatch_next_projection(
        path,
        rebuild=lambda queued: rebuilt(queued),
        submit=lambda payload, proof: (calls.append(proof.request_id) or Submission("CONFIRMED", receiver_row=2)),
    )

    assert result.intent == intent
    assert result.dispatch is not None
    assert result.dispatch.status == "CONFIRMED"
    assert result.dispatch.receiver_row == 2
    assert calls == ["00000000-0000-4000-8000-000000000011"]
    assert outstanding_projection_intents(path) == ()
    assert dispatch_next_projection(path, rebuild=lambda queued: rebuilt(queued), submit=lambda payload, proof: Submission("CONFIRMED", receiver_row=2)).intent is None


def test_transport_failure_remains_outstanding_for_a_later_one_shot(tmp_path: Path) -> None:
    path = tmp_path / "projection-outbox.jsonl"
    intent = enqueue_projection_intent(path, action="update_close_v2", provenance=provenance())

    first = dispatch_next_projection(path, rebuild=lambda queued: rebuilt(queued), submit=lambda payload, proof: Submission("TRANSPORT_FAILED", error_code="transport_failed"))
    assert first.dispatch is not None
    assert first.dispatch.status == "TRANSPORT_FAILED"
    assert outstanding_projection_intents(path) == (intent,)

    second = dispatch_next_projection(path, rebuild=lambda queued: rebuilt(queued), submit=lambda payload, proof: Submission("CONFIRMED", receiver_row=4))
    assert second.dispatch is not None
    assert second.dispatch.status == "CONFIRMED"
    assert outstanding_projection_intents(path) == ()


def test_changed_ledger_or_projection_digest_is_rejected_without_submit(tmp_path: Path) -> None:
    path = tmp_path / "projection-outbox.jsonl"
    enqueue_projection_intent(path, action="update_close_v2", provenance=provenance())
    submit_called = False

    def submit(payload, proof):  # pragma: no cover - assertion below proves this cannot run
        nonlocal submit_called
        submit_called = True
        return Submission("CONFIRMED", receiver_row=2)

    result = dispatch_next_projection(path, rebuild=lambda queued: rebuilt(queued, payload_digest="c" * 64), submit=submit)

    assert result.dispatch is not None
    assert result.dispatch.status == "REJECTED"
    assert result.dispatch.error_code == "rehydration_invalid"
    assert submit_called is False
    assert outstanding_projection_intents(path) == ()


def test_rejected_receiver_response_is_terminal_and_never_falls_back(tmp_path: Path) -> None:
    path = tmp_path / "projection-outbox.jsonl"
    enqueue_projection_intent(path, action="update_close_v2", provenance=provenance())
    legacy_called = False

    result = dispatch_next_projection(
        path,
        rebuild=lambda queued: rebuilt(queued),
        submit=lambda payload, proof: Submission("REJECTED", error_code="source_not_allowed"),
    )

    assert result.dispatch is not None
    assert result.dispatch.status == "REJECTED"
    assert result.dispatch.error_code == "source_not_allowed"
    assert legacy_called is False
    assert outstanding_projection_intents(path) == ()
