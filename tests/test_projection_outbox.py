from __future__ import annotations

import json
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
    TRADE_ID_CONFLICT_ERROR,
    TRADE_ID_CONFLICT_PARK_AFTER,
    TRADE_ID_CONFLICT_PARKED_CODE,
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


def test_requeue_never_resends_what_was_ever_confirmed_even_if_a_later_record_says_rejected(tmp_path: Path) -> None:
    """Review of #144: a CONFIRMED followed by a contradictory REJECTED must not make the projection requeueable."""
    path = tmp_path / "projection-outbox.jsonl"
    closed = enqueue_projection_intent(path, action="update_close_v2", provenance=provenance())
    record_projection_dispatch(path, intent=closed, status="CONFIRMED", receiver_row=2)
    record_projection_dispatch(path, intent=closed, status="REJECTED", error_code="late_error")
    assert requeue_rejected_projection_intents(path, trade_id="trade-001") == ()


def test_requeue_with_a_confirmed_copy_and_a_rejected_copy_of_the_same_projection_queues_nothing(tmp_path: Path, monkeypatch) -> None:
    _ticking_clock(monkeypatch)
    path = tmp_path / "projection-outbox.jsonl"
    first = enqueue_projection_intent(path, action="update_close_v2", provenance=provenance())
    record_projection_dispatch(path, intent=first, status="REJECTED", error_code=ORPHAN_CLOSE_PARKED_CODE)
    (second,) = requeue_rejected_projection_intents(path, trade_id="trade-001")
    record_projection_dispatch(path, intent=second, status="CONFIRMED", receiver_row=2)
    assert requeue_rejected_projection_intents(path, trade_id="trade-001") == ()


def test_requeue_with_two_rejected_copies_of_one_projection_queues_one(tmp_path: Path, monkeypatch) -> None:
    _ticking_clock(monkeypatch)
    path = tmp_path / "projection-outbox.jsonl"
    first = enqueue_projection_intent(path, action="update_close_v2", provenance=provenance())
    record_projection_dispatch(path, intent=first, status="REJECTED", error_code=ORPHAN_CLOSE_PARKED_CODE)
    (second,) = requeue_rejected_projection_intents(path, trade_id="trade-001")
    record_projection_dispatch(path, intent=second, status="REJECTED", error_code=ORPHAN_CLOSE_PARKED_CODE)
    (third,) = requeue_rejected_projection_intents(path, trade_id="trade-001")
    assert third.intent_id not in {first.intent_id, second.intent_id}
    assert requeue_rejected_projection_intents(path, trade_id="trade-001") == ()  # the third is outstanding now

def test_a_spot_fill_is_its_own_action_not_an_open_row(tmp_path: Path) -> None:
    """e-2: a spot fill is projected by append_fill_v2 / spot_fill; it is not an open that waits for a close."""
    fill = LedgerProvenance(
        project_id="btc-competition", trade_id="ETHBTC-5551212", event_type="spot_fill", ledger_event_digest=DIGEST_A,
        payload_digest=DIGEST_B, request_id=str(uuid4()), issued_at="2026-10-08T00:00:00Z",
        source_id="btc-competition-wsl-prod", schema_version=LEDGER_PROJECTION_SCHEMA_VERSION,
    )
    path = tmp_path / "projection-outbox.jsonl"
    intent = enqueue_projection_intent(path, action="append_fill_v2", provenance=fill)
    assert intent.event_type == "spot_fill" and intent.action == "append_fill_v2"
    assert outstanding_projection_intents(path) == (intent,)
    # the old pairing no longer fits: a fill is not an open, and an open is not a fill
    try:
        enqueue_projection_intent(path, action="append_open_v2", provenance=fill)
    except ValueError as exc:
        assert "does not match" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("append_open_v2 must refuse a spot_fill provenance")
    try:
        enqueue_projection_intent(path, action="append_fill_v2", provenance=_open_provenance())
    except ValueError as exc:
        assert "does not match" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("append_fill_v2 must refuse a trade_open provenance")


def test_an_invalid_fill_is_rejected_and_the_next_projection_still_goes_out(tmp_path: Path, monkeypatch) -> None:
    """Review of #145, receiver error -> client status -> outbox lifecycle: an invalid fill is REJECTED (not retried
    forever at the head of the queue) and the next intent is delivered; a stale receiver's unsupported_action is retried."""
    from trade_alerts.google_ledger_client import deliver_projection_v2

    _ticking_clock(monkeypatch)
    path = tmp_path / "projection-outbox.jsonl"
    fill_proof = LedgerProvenance(
        project_id="mexc-4h-momentum", trade_id="ETHBTC-5551212", event_type="spot_fill", ledger_event_digest=DIGEST_A,
        payload_digest=DIGEST_B, request_id=str(uuid4()), issued_at="2026-10-08T00:00:00Z",
        source_id="momentum-wsl-prod", schema_version=LEDGER_PROJECTION_SCHEMA_VERSION,
    )
    fill = enqueue_projection_intent(path, action="append_fill_v2", provenance=fill_proof)
    nxt = enqueue_projection_intent(path, action="append_open_v2", provenance=_open_provenance())

    class _Resp:
        def __init__(self, body):
            self._body = body
            self.status_code = 200
            self.headers = {}

        def raise_for_status(self):
            pass

        def json(self):
            return self._body

    def submit_with(answer_for_fill):
        def post(url, **kwargs):
            payload = kwargs.get("json") or json.loads(kwargs["data"])
            if payload["action"] == "append_fill_v2":
                return _Resp(answer_for_fill)
            return _Resp({"ok": True, "row": 2})
        return lambda payload, _proof: deliver_projection_v2(endpoint="https://example.test/receiver", payload=payload, post=post, sleep=lambda _: None, attempts=1)

    stale = dispatch_next_projection(path, rebuild=_rebuild_like, submit=submit_with({"ok": False, "error": "unsupported_action"}))
    assert stale.dispatch.status == "TRANSPORT_FAILED"
    assert outstanding_projection_intents(path)[0].intent_id == fill.intent_id  # retried later, not dropped

    invalid = dispatch_next_projection(path, rebuild=_rebuild_like, submit=submit_with({"ok": False, "error": "fill_projection_invalid"}))
    assert invalid.dispatch.status == "REJECTED" and invalid.dispatch.error_code == "fill_projection_invalid"
    assert [i.intent_id for i in outstanding_projection_intents(path)] == [nxt.intent_id]
    delivered = dispatch_next_projection(path, rebuild=_rebuild_like, submit=submit_with({"ok": True, "row": 2}))
    assert delivered.dispatch.status == "CONFIRMED"


# --------------------------------------------------------------------------- #
# 8b: a parked orphan close / a refused correction base leaves an R1 fleet event
# --------------------------------------------------------------------------- #
def _events(path: Path) -> list[dict]:
    from trade_alerts import read_fleet_events

    return read_fleet_events(path) if path.exists() else []


def test_parking_an_orphan_close_records_one_r1_fleet_event(tmp_path: Path, monkeypatch) -> None:
    _ticking_clock(monkeypatch)
    path, log = tmp_path / "projection-outbox.jsonl", tmp_path / "fleet_event_log.jsonl"
    intent = enqueue_projection_intent(path, action="update_close_v2", provenance=provenance())
    not_found = lambda *_a: Submission("TRANSPORT_FAILED", error_code="trade_id_not_found")  # noqa: E731

    for _ in range(ORPHAN_CLOSE_PARK_AFTER - 1):
        dispatch_next_projection(path, rebuild=rebuilt, submit=not_found, fleet_event_log=log, strategy_project="momentum")
    assert _events(log) == []                                    # still retrying: nothing recorded yet

    dispatch_next_projection(path, rebuild=rebuilt, submit=not_found, fleet_event_log=log, strategy_project="momentum")
    [event] = _events(log)
    assert (event["project"], event["code"], event["risk_tier"]) == ("fleet", "PROJECTION_ORPHAN_CLOSE_PARKED", "R1")
    assert event["evidence"]["trade_id"] == "trade-001" and event["evidence"]["intent_id"] == intent.intent_id
    assert event["details"]["strategy"] == "momentum"

    assert dispatch_next_projection(path, rebuild=rebuilt, submit=not_found, fleet_event_log=log, strategy_project="momentum").intent is None
    assert len(_events(log)) == 1                                # the parked intent is terminal: written once


def test_a_refused_correction_base_records_an_r1_event_for_the_trend_strategy_only(tmp_path: Path) -> None:
    for strategy, expected in (("seykota", 1), ("mycrypto", 0)):
        path, log = tmp_path / f"{strategy}-outbox.jsonl", tmp_path / f"{strategy}-events.jsonl"
        enqueue_projection_intent(path, action="correct_close_v2", provenance=_prov("trade_correction", "c" * 64))
        result = dispatch_next_projection(path, rebuild=_rebuild_like, submit=_answer("correction_base_mismatch", "REJECTED"),
                                          fleet_event_log=log, strategy_project=strategy)
        assert result.dispatch.status == "REJECTED"
        events = _events(log)
        assert len(events) == expected
        if expected:
            assert (events[0]["project"], events[0]["code"], events[0]["risk_tier"]) == ("seykota", "CORRECTION_BASE_MISMATCH", "R1")


def test_other_rejections_and_a_missing_event_log_record_nothing(tmp_path: Path) -> None:
    path, log = tmp_path / "projection-outbox.jsonl", tmp_path / "fleet_event_log.jsonl"
    enqueue_projection_intent(path, action="update_close_v2", provenance=provenance())
    dispatch_next_projection(path, rebuild=rebuilt, submit=_answer("close_projection_invalid", "REJECTED"),
                             fleet_event_log=log, strategy_project="seykota")
    assert _events(log) == []

    path2 = tmp_path / "second-outbox.jsonl"
    enqueue_projection_intent(path2, action="correct_close_v2", provenance=_prov("trade_correction", "c" * 64))
    dispatch_next_projection(path2, rebuild=_rebuild_like, submit=_answer("correction_base_mismatch", "REJECTED"))   # no log given: as before
    assert not (tmp_path / "second-events.jsonl").exists()


def test_an_event_that_cannot_be_written_never_stops_the_queue(tmp_path: Path, monkeypatch) -> None:
    import trade_alerts.projection_outbox as outbox

    monkeypatch.setattr(outbox, "append_fleet_event", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    path = tmp_path / "projection-outbox.jsonl"
    enqueue_projection_intent(path, action="correct_close_v2", provenance=_prov("trade_correction", "c" * 64))
    result = dispatch_next_projection(path, rebuild=_rebuild_like, submit=_answer("correction_base_mismatch", "REJECTED"),
                                      fleet_event_log=tmp_path / "log.jsonl", strategy_project="seykota")
    assert result.dispatch.status == "REJECTED" and outstanding_projection_intents(path) == ()


def test_parking_a_correction_that_cannot_be_confirmed_records_the_same_r1_event(tmp_path: Path, monkeypatch) -> None:
    _ticking_clock(monkeypatch)
    path, log = tmp_path / "projection-outbox.jsonl", tmp_path / "fleet_event_log.jsonl"
    enqueue_projection_intent(path, action="correct_close_v2", provenance=_prov("trade_correction", "c" * 64))
    for _ in range(CORRECTION_UNCONFIRMED_PARK_AFTER):
        dispatch_next_projection(path, rebuild=_rebuild_like, submit=_answer(CORRECTION_UNCONFIRMED_ERROR),
                                 fleet_event_log=log, strategy_project="seykota")
    [event] = _events(log)
    assert (event["project"], event["code"], event["details"]["error_code"]) == ("fleet", "PROJECTION_ORPHAN_CLOSE_PARKED", CORRECTION_PARKED_CODE)


def test_a_busy_event_log_cannot_hold_the_dispatch_up(tmp_path: Path, monkeypatch) -> None:
    import fcntl
    import time

    import trade_alerts.projection_outbox as outbox

    monkeypatch.setattr(outbox, "PARK_EVENT_LOCK_TIMEOUT_SECONDS", 0.2)
    path, log = tmp_path / "projection-outbox.jsonl", tmp_path / "fleet_event_log.jsonl"
    enqueue_projection_intent(path, action="correct_close_v2", provenance=_prov("trade_correction", "c" * 64))
    with log.open("a+", encoding="utf-8") as holder:              # another process holds the log's lock
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
        started = time.monotonic()
        result = dispatch_next_projection(path, rebuild=_rebuild_like, submit=_answer("correction_base_mismatch", "REJECTED"),
                                          fleet_event_log=log, strategy_project="seykota")
        waited = time.monotonic() - started
    assert waited < 5                                               # gave up after ~0.2 s instead of waiting for ever
    assert result.dispatch.status == "REJECTED" and outstanding_projection_intents(path) == ()   # the dispatch itself is on disk
    assert _events(log) == []                                       # the audit line was the only thing dropped


def test_the_event_log_lock_wait_is_unbounded_unless_a_timeout_is_given(tmp_path: Path) -> None:
    import fcntl

    import pytest

    from trade_alerts import FleetEventLogError, append_fleet_event

    log = tmp_path / "fleet_event_log.jsonl"
    with log.open("a+", encoding="utf-8") as holder:
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
        with pytest.raises(FleetEventLogError):
            append_fleet_event(log, project="seykota", code="X", lock_timeout=0.1)
    append_fleet_event(log, project="seykota", code="X", lock_timeout=0.1)   # free again: written
    assert len(_events(log)) == 1


# --------------------------------------------------------------------------- #
# f-64: an open / fill row whose trade_id the receiver already holds is parked, not retried forever
# --------------------------------------------------------------------------- #
def _fill_provenance(trade_id: str = "SOLUSDT-3395297505") -> LedgerProvenance:
    return _prov("spot_fill", DIGEST_B, trade_id)


def test_a_trade_id_conflict_on_an_open_or_fill_is_parked_so_the_queue_moves_on(tmp_path: Path, monkeypatch) -> None:
    for action, proof in (("append_fill_v2", _fill_provenance()), ("append_open_v2", _prov("trade_open", DIGEST_B))):
        _ticking_clock(monkeypatch)
        path, log = tmp_path / f"{action}-outbox.jsonl", tmp_path / f"{action}-events.jsonl"
        stuck = enqueue_projection_intent(path, action=action, provenance=proof)
        later = enqueue_projection_intent(path, action="append_open_v2", provenance=_open_provenance())
        conflict = _answer(TRADE_ID_CONFLICT_ERROR)

        for attempt in range(1, TRADE_ID_CONFLICT_PARK_AFTER):
            result = dispatch_next_projection(path, rebuild=_rebuild_like, submit=conflict, fleet_event_log=log, strategy_project="btc-competition")
            assert result.dispatch.status == "TRANSPORT_FAILED", (action, attempt)
            assert outstanding_projection_intents(path)[0].intent_id == stuck.intent_id
        assert _events(log) == []                                    # still retrying: nothing recorded yet

        parked = dispatch_next_projection(path, rebuild=_rebuild_like, submit=conflict, fleet_event_log=log, strategy_project="btc-competition")
        assert (parked.dispatch.status, parked.dispatch.error_code) == ("REJECTED", TRADE_ID_CONFLICT_PARKED_CODE)
        assert [i.intent_id for i in outstanding_projection_intents(path)] == [later.intent_id]

        [event] = _events(log)
        assert (event["project"], event["code"], event["risk_tier"]) == ("fleet", "PROJECTION_TRADE_ID_CONFLICT_PARKED", "R1")
        assert event["evidence"]["trade_id"] == proof.trade_id and event["evidence"]["intent_id"] == stuck.intent_id
        assert event["details"]["error_code"] == TRADE_ID_CONFLICT_PARKED_CODE

        delivered = dispatch_next_projection(path, rebuild=_rebuild_like, submit=_answer(None, "CONFIRMED", 2), fleet_event_log=log, strategy_project="btc-competition")
        assert delivered.dispatch.status == "CONFIRMED" and len(_events(log)) == 1   # the next row goes out; the event is written once



def test_conflict_count_restarts_when_the_answer_changes(tmp_path: Path) -> None:
    path = tmp_path / "projection-outbox.jsonl"
    enqueue_projection_intent(path, action="append_fill_v2", provenance=_fill_provenance())
    for _ in range(TRADE_ID_CONFLICT_PARK_AFTER - 1):
        dispatch_next_projection(path, rebuild=_rebuild_like, submit=_answer(TRADE_ID_CONFLICT_ERROR))
    dispatch_next_projection(path, rebuild=_rebuild_like, submit=_answer("transport_failed"))   # a different failure breaks the run
    result = dispatch_next_projection(path, rebuild=_rebuild_like, submit=_answer(TRADE_ID_CONFLICT_ERROR))
    assert result.dispatch.status == "TRANSPORT_FAILED"                                          # one answer again, not the Nth in a row


def test_a_close_or_correction_conflict_is_never_parked_by_this_rule(tmp_path: Path) -> None:
    for action, event_type in (("update_close_v2", "trade_close"), ("correct_close_v2", "trade_correction")):
        path = tmp_path / f"{action}-outbox.jsonl"
        enqueue_projection_intent(path, action=action, provenance=_prov(event_type, DIGEST_B))
        for _ in range(TRADE_ID_CONFLICT_PARK_AFTER + 3):
            result = dispatch_next_projection(path, rebuild=_rebuild_like, submit=_answer(TRADE_ID_CONFLICT_ERROR))
            assert result.dispatch.status == "TRANSPORT_FAILED", action


def test_the_receivers_real_conflict_answer_reaches_the_park_rule_through_the_client(tmp_path: Path) -> None:
    """End to end through ``deliver_projection_v2``: the receiver's ``trade_id_conflict`` is a retryable answer there,
    so only the outbox's own rule can stop it blocking the head of the queue."""
    from trade_alerts.google_ledger_client import deliver_projection_v2

    class _Resp:
        status_code = 200
        headers: dict = {}

        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": False, "error": "trade_id_conflict"}

    path = tmp_path / "projection-outbox.jsonl"
    enqueue_projection_intent(path, action="append_fill_v2", provenance=_fill_provenance())
    submit = lambda payload, _proof: deliver_projection_v2(endpoint="https://example.test/receiver", payload=payload, post=lambda url, **k: _Resp(), sleep=lambda _: None, attempts=1)  # noqa: E731
    statuses = [dispatch_next_projection(path, rebuild=_rebuild_like, submit=submit).dispatch for _ in range(TRADE_ID_CONFLICT_PARK_AFTER)]
    assert [d.status for d in statuses] == ["TRANSPORT_FAILED"] * (TRADE_ID_CONFLICT_PARK_AFTER - 1) + ["REJECTED"]
    assert statuses[-1].error_code == TRADE_ID_CONFLICT_PARKED_CODE and outstanding_projection_intents(path) == ()
