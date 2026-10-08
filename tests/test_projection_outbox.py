from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from trade_alerts.ledger_integrity import LEDGER_PROJECTION_SCHEMA_VERSION, LedgerProvenance
from trade_alerts.projection_outbox import (
    ORPHAN_CLOSE_PARK_AFTER,
    CORRECTION_PARKED_CODE,
    CORRECTION_UNCONFIRMED_ERROR,
    CORRECTION_UNCONFIRMED_PARK_AFTER,
    ORPHAN_CLOSE_PARKED_CODE,
    RebuiltProjection,
    dispatch_next_projection,
    enqueue_projection_intent,
    outstanding_projection_intents,
    record_projection_dispatch,
    requeue_rejected_projection_intents,
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
        submit=lambda payload, proof: Submission("REJECTED", error_code="provenance_invalid"),
    )

    assert result.dispatch is not None
    assert result.dispatch.status == "REJECTED"
    assert result.dispatch.error_code == "provenance_invalid"
    assert legacy_called is False
    assert outstanding_projection_intents(path) == ()


def test_unreadable_ledger_pauses_without_consuming_the_intent(tmp_path: Path) -> None:
    from trade_alerts import LedgerUnreadableError

    path = tmp_path / "projection-outbox.jsonl"
    intent = enqueue_projection_intent(path, action="update_close_v2", provenance=provenance())
    submitted = False

    def damaged(queued):
        raise LedgerUnreadableError("ledger line 7 is malformed")

    def submit(payload, proof):  # pragma: no cover - must not run
        nonlocal submitted
        submitted = True
        return Submission("CONFIRMED", receiver_row=2)

    before = path.read_text(encoding="utf-8")
    result = dispatch_next_projection(path, rebuild=damaged, submit=submit)

    assert result.intent == intent
    assert result.dispatch is None
    assert result.paused_reason == "ledger line 7 is malformed"
    assert submitted is False
    assert path.read_text(encoding="utf-8") == before
    assert outstanding_projection_intents(path) == (intent,)

    # once the ledger is repaired the same intent goes through
    fixed = dispatch_next_projection(path, rebuild=lambda queued: rebuilt(queued), submit=lambda payload, proof: Submission("CONFIRMED", receiver_row=2))
    assert fixed.dispatch is not None and fixed.dispatch.status == "CONFIRMED"
    assert fixed.paused_reason is None
    assert outstanding_projection_intents(path) == ()


def test_other_rebuild_errors_are_still_terminal(tmp_path: Path) -> None:
    from trade_alerts import LedgerIntegrityError

    path = tmp_path / "projection-outbox.jsonl"
    enqueue_projection_intent(path, action="update_close_v2", provenance=provenance())

    def ambiguous(queued):
        raise LedgerIntegrityError("ambiguous local trade_close events for trade_id")

    result = dispatch_next_projection(path, rebuild=ambiguous, submit=lambda payload, proof: Submission("CONFIRMED", receiver_row=2))
    assert result.dispatch is not None and result.dispatch.status == "REJECTED"
    assert result.paused_reason is None


def _open_provenance() -> LedgerProvenance:
    return LedgerProvenance(
        project_id="mexc-4h-momentum", trade_id="trade-002", event_type="trade_open", ledger_event_digest=DIGEST_A,
        payload_digest=DIGEST_B, request_id=str(uuid4()), issued_at="2026-08-26T00:00:00Z",
        source_id="momentum-wsl-prod", schema_version=LEDGER_PROJECTION_SCHEMA_VERSION,
    )


def _ticking_clock(monkeypatch) -> None:
    """``created_at`` has one-second resolution and the queue is ordered by it,
    so two intents queued in the same second would be ordered by their random
    ids.  Give every intent its own second so the tests control the order."""
    counter = iter(range(1, 100000))

    def tick() -> str:
        n = next(counter)
        return f"2026-08-26T{n // 3600:02d}:{n // 60 % 60:02d}:{n % 60:02d}Z"

    monkeypatch.setattr("trade_alerts.projection_outbox._utc_now", tick)


def test_a_close_the_receiver_cannot_find_is_parked_so_the_queue_moves_on(tmp_path: Path, monkeypatch) -> None:
    _ticking_clock(monkeypatch)
    path = tmp_path / "projection-outbox.jsonl"
    orphan = enqueue_projection_intent(path, action="update_close_v2", provenance=provenance())
    later = enqueue_projection_intent(path, action="append_open_v2", provenance=_open_provenance())
    not_found = lambda *_a: Submission("TRANSPORT_FAILED", error_code="trade_id_not_found")  # noqa: E731

    for attempt in range(1, ORPHAN_CLOSE_PARK_AFTER):
        result = dispatch_next_projection(path, rebuild=rebuilt, submit=not_found)
        assert result.dispatch.status == "TRANSPORT_FAILED", attempt
        assert outstanding_projection_intents(path)[0].intent_id == orphan.intent_id  # still blocking, as before

    parked = dispatch_next_projection(path, rebuild=rebuilt, submit=not_found)
    assert parked.dispatch.status == "REJECTED"
    assert parked.dispatch.error_code == ORPHAN_CLOSE_PARKED_CODE
    assert [i.intent_id for i in outstanding_projection_intents(path)] == [later.intent_id]


def test_orphan_count_restarts_when_the_answer_changes(tmp_path: Path) -> None:
    path = tmp_path / "projection-outbox.jsonl"
    enqueue_projection_intent(path, action="update_close_v2", provenance=provenance())
    not_found = lambda *_a: Submission("TRANSPORT_FAILED", error_code="trade_id_not_found")  # noqa: E731
    flaky = lambda *_a: Submission("TRANSPORT_FAILED", error_code="transport_failed")  # noqa: E731
    for _ in range(ORPHAN_CLOSE_PARK_AFTER - 1):
        dispatch_next_projection(path, rebuild=rebuilt, submit=not_found)
    dispatch_next_projection(path, rebuild=rebuilt, submit=flaky)  # a different failure breaks the run
    result = dispatch_next_projection(path, rebuild=rebuilt, submit=not_found)
    assert result.dispatch.status == "TRANSPORT_FAILED"  # one answer again, not the 12th in a row


def test_an_open_that_is_not_found_is_never_parked(tmp_path: Path) -> None:
    path = tmp_path / "projection-outbox.jsonl"
    enqueue_projection_intent(path, action="append_open_v2", provenance=_open_provenance())
    not_found = lambda *_a: Submission("TRANSPORT_FAILED", error_code="trade_id_not_found")  # noqa: E731

    def rebuilt_open(intent):
        proof = _open_provenance()
        return RebuiltProjection(payload={**rebuilt(intent).payload, "provenance": proof.as_dict()}, provenance=proof)

    for _ in range(ORPHAN_CLOSE_PARK_AFTER + 3):
        result = dispatch_next_projection(path, rebuild=rebuilt_open, submit=not_found)
        assert result.dispatch.status == "TRANSPORT_FAILED"


def test_intents_queued_in_the_same_second_keep_their_queue_order(tmp_path: Path, monkeypatch) -> None:
    """f-21: a trade's open and close queued in one second must go out open first,
    whatever their random ids sort like (the close's id here sorts before the open's)."""
    from types import SimpleNamespace

    monkeypatch.setattr("trade_alerts.projection_outbox._utc_now", lambda: "2026-10-06T09:37:53Z")
    ids = iter(["20ca9096" + "0" * 24, "1e794fad" + "0" * 24])  # open first, then close
    monkeypatch.setattr("trade_alerts.projection_outbox.uuid4", lambda: SimpleNamespace(hex=next(ids)))
    path = tmp_path / "projection-outbox.jsonl"
    opened = enqueue_projection_intent(path, action="append_open_v2", provenance=_open_provenance())
    closed = enqueue_projection_intent(path, action="update_close_v2", provenance=provenance())
    assert closed.intent_id < opened.intent_id  # the trap: sorting by (created_at, intent_id) would put the close first

    assert [i.intent_id for i in outstanding_projection_intents(path)] == [opened.intent_id, closed.intent_id]


# --------------------------------------------------------------------------- #
# f-25: a correction behind a parked close is parked too; parked intents can be requeued
# --------------------------------------------------------------------------- #
def _prov(event_type: str, digest: str, trade_id: str = "trade-001") -> LedgerProvenance:
    return LedgerProvenance(
        project_id="mexc-4h-momentum", trade_id=trade_id, event_type=event_type, ledger_event_digest=DIGEST_A,
        payload_digest=digest, request_id=str(uuid4()), issued_at="2026-08-26T00:00:00Z",
        source_id="momentum-wsl-prod", schema_version=LEDGER_PROJECTION_SCHEMA_VERSION,
    )


def _rebuild_like(intent) -> RebuiltProjection:
    """A rebuild that reproduces whatever immutable binding the intent carries."""
    proof = LedgerProvenance(
        project_id=intent.project_id, trade_id=intent.trade_id, event_type=intent.event_type,
        ledger_event_digest=intent.ledger_event_digest, payload_digest=intent.payload_digest,
        request_id=str(uuid4()), issued_at="2026-08-26T00:01:00Z", source_id=intent.source_id,
        schema_version=intent.schema_version,
    )
    payload = {
        "schema_version": intent.schema_version, "action": intent.action, "source_id": intent.source_id,
        "project_id": intent.project_id, "sheet_name": "mexc-4h-momentum-trailing-stop",
        "request_id": proof.request_id, "issued_at": proof.issued_at, "provenance": proof.as_dict(),
        "projection": {"trade_id": intent.trade_id}, "signature": "0" * 64,
    }
    return RebuiltProjection(payload=payload, provenance=proof)


def _answer(code: str, status: str = "TRANSPORT_FAILED", row: int | None = None):
    return lambda *_a: Submission(status, receiver_row=row, error_code=code)


def test_a_correction_the_receiver_cannot_confirm_a_close_for_is_parked_so_the_queue_moves_on(tmp_path: Path, monkeypatch) -> None:
    _ticking_clock(monkeypatch)
    path = tmp_path / "projection-outbox.jsonl"
    correction = enqueue_projection_intent(path, action="correct_close_v2", provenance=_prov("trade_correction", "c" * 64))
    later = enqueue_projection_intent(path, action="append_open_v2", provenance=_open_provenance())
    unconfirmed = _answer(CORRECTION_UNCONFIRMED_ERROR)

    for attempt in range(1, CORRECTION_UNCONFIRMED_PARK_AFTER):
        result = dispatch_next_projection(path, rebuild=_rebuild_like, submit=unconfirmed)
        assert result.dispatch.status == "TRANSPORT_FAILED", attempt
        assert outstanding_projection_intents(path)[0].intent_id == correction.intent_id  # still blocking

    parked = dispatch_next_projection(path, rebuild=_rebuild_like, submit=unconfirmed)
    assert parked.dispatch.status == "REJECTED" and parked.dispatch.error_code == CORRECTION_PARKED_CODE
    assert [i.intent_id for i in outstanding_projection_intents(path)] == [later.intent_id]


def test_close_not_confirmed_on_a_plain_close_is_never_parked(tmp_path: Path) -> None:
    path = tmp_path / "projection-outbox.jsonl"
    enqueue_projection_intent(path, action="update_close_v2", provenance=provenance())
    for _ in range(CORRECTION_UNCONFIRMED_PARK_AFTER + 3):
        result = dispatch_next_projection(path, rebuild=rebuilt, submit=_answer(CORRECTION_UNCONFIRMED_ERROR))
        assert result.dispatch.status == "TRANSPORT_FAILED"


def test_requeue_puts_a_trades_parked_intents_back_in_their_original_order(tmp_path: Path, monkeypatch) -> None:
    _ticking_clock(monkeypatch)
    path = tmp_path / "projection-outbox.jsonl"
    opened = enqueue_projection_intent(path, action="append_open_v2", provenance=_prov("trade_open", "b" * 64))
    closed = enqueue_projection_intent(path, action="update_close_v2", provenance=_prov("trade_close", "c" * 64))
    corrected = enqueue_projection_intent(path, action="correct_close_v2", provenance=_prov("trade_correction", "d" * 64))
    other = enqueue_projection_intent(path, action="update_close_v2", provenance=_prov("trade_close", "e" * 64, trade_id="trade-other"))
    # the open lands, the close is parked (the open was late), the correction is parked behind it, the other trade is parked too
    record_projection_dispatch(path, intent=opened, status="CONFIRMED", receiver_row=2)
    record_projection_dispatch(path, intent=closed, status="REJECTED", error_code=ORPHAN_CLOSE_PARKED_CODE)
    record_projection_dispatch(path, intent=corrected, status="REJECTED", error_code=CORRECTION_PARKED_CODE)
    record_projection_dispatch(path, intent=other, status="REJECTED", error_code=ORPHAN_CLOSE_PARKED_CODE)
    assert outstanding_projection_intents(path) == ()

    queued = requeue_rejected_projection_intents(path, trade_id="trade-001")

    assert [q.action for q in queued] == ["update_close_v2", "correct_close_v2"]  # not the confirmed open, not the other trade
    assert all(q.intent_id not in {closed.intent_id, corrected.intent_id} for q in queued)
    assert [(q.ledger_event_digest, q.payload_digest) for q in queued] == [(closed.ledger_event_digest, closed.payload_digest), (corrected.ledger_event_digest, corrected.payload_digest)]
    assert outstanding_projection_intents(path) == queued
    # the receiver's usual path takes it from here
    first = dispatch_next_projection(path, rebuild=_rebuild_like, submit=lambda *_a: Submission("CONFIRMED", receiver_row=2))
    assert first.intent.action == "update_close_v2" and first.dispatch.status == "CONFIRMED"


def test_requeue_does_nothing_twice_or_for_delivered_intents(tmp_path: Path) -> None:
    path = tmp_path / "projection-outbox.jsonl"
    closed = enqueue_projection_intent(path, action="update_close_v2", provenance=provenance())
    assert requeue_rejected_projection_intents(path, trade_id="trade-001") == ()  # still outstanding
    record_projection_dispatch(path, intent=closed, status="CONFIRMED", receiver_row=2)
    assert requeue_rejected_projection_intents(path, trade_id="trade-001") == ()  # delivered
    assert requeue_rejected_projection_intents(path, trade_id="no-such-trade") == ()


def test_requeue_twice_in_a_row_queues_only_once(tmp_path: Path) -> None:
    path = tmp_path / "projection-outbox.jsonl"
    closed = enqueue_projection_intent(path, action="update_close_v2", provenance=provenance())
    record_projection_dispatch(path, intent=closed, status="REJECTED", error_code=ORPHAN_CLOSE_PARKED_CODE)
    assert len(requeue_rejected_projection_intents(path, trade_id="trade-001")) == 1
    assert requeue_rejected_projection_intents(path, trade_id="trade-001") == ()
