"""Durable, non-secret projection intent queue and one-shot dispatcher.

The queue is deliberately separate from the append-only trading ledger.  An
intent can only be enqueued after a strategy has selected one exact ledger
fact.  At dispatch time the strategy must rebuild a fresh signed payload from
that fact and prove that its immutable digest binding did not change.
"""
from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Mapping
from uuid import uuid4

from .ledger_integrity import LEDGER_PROJECTION_SCHEMA_VERSION, LedgerProvenance, LedgerUnreadableError

ProjectionAction = Literal["append_open_v2", "update_close_v2", "correct_close_v2"]
ProjectionOutcomeStatus = Literal["CONFIRMED", "REJECTED", "TRANSPORT_FAILED"]
_ALLOWED_ACTIONS = frozenset({"append_open_v2", "update_close_v2", "correct_close_v2"})
# Each write action projects exactly one kind of ledger event.
_ACTION_EVENT_TYPE = {"append_open_v2": "trade_open", "update_close_v2": "trade_close", "correct_close_v2": "trade_correction"}
_TERMINAL_STATUSES = frozenset({"CONFIRMED", "REJECTED"})
#: A close whose trade the receiver has never heard of (``trade_id_not_found``)
#: is not a transport problem: the open row is missing, so no retry will help
#: (f-16: one such intent sat at the head of a strategy's queue for days and
#: blocked every later row).  After this many consecutive answers it is parked
#: as REJECTED so the queue moves on; the sheet check keeps reporting the gap.
ORPHAN_CLOSE_PARK_AFTER = 12
ORPHAN_CLOSE_ERROR = "trade_id_not_found"
ORPHAN_CLOSE_PARKED_CODE = "orphan_close_no_open_row"
_CLOSE_ACTIONS = frozenset({"update_close_v2", "correct_close_v2"})
#: A correction whose trade the receiver answers ``close_not_confirmed`` can never succeed on its own: the
#: queue sends a trade's close before its correction, so the close is terminal (parked or lost) and the
#: receiver has no confirmed close to correct.  Retrying forever blocked the head of the queue (f-25), so
#: after this many consecutive answers it is parked as REJECTED; ``requeue_rejected_projection_intents``
#: puts the trade's rejected intents back, in their original order, once the close can be confirmed.
CORRECTION_UNCONFIRMED_ERROR = "close_not_confirmed"
CORRECTION_UNCONFIRMED_PARK_AFTER = 12
CORRECTION_PARKED_CODE = "correction_close_not_confirmed"


@dataclass(frozen=True)
class ProjectionIntent:
    """Immutable, non-secret identity of one ledger-backed Google projection."""

    intent_id: str
    created_at: str
    action: ProjectionAction
    project_id: str
    trade_id: str
    event_type: str
    source_id: str
    ledger_event_digest: str
    payload_digest: str
    schema_version: str = LEDGER_PROJECTION_SCHEMA_VERSION

    @classmethod
    def from_provenance(cls, *, action: ProjectionAction, provenance: LedgerProvenance, intent_id: str | None = None) -> "ProjectionIntent":
        if action not in _ALLOWED_ACTIONS:
            raise ValueError("projection action is not allowed")
        if provenance.event_type != _ACTION_EVENT_TYPE[action]:
            raise ValueError("projection action does not match the ledger event type")
        return cls(
            intent_id=intent_id or uuid4().hex,
            created_at=_utc_now(),
            action=action,
            project_id=provenance.project_id,
            trade_id=provenance.trade_id,
            event_type=provenance.event_type,
            source_id=provenance.source_id,
            ledger_event_digest=provenance.ledger_event_digest,
            payload_digest=provenance.payload_digest,
            schema_version=provenance.schema_version,
        )


@dataclass(frozen=True)
class ProjectionDispatch:
    """Non-secret result recorded after one dispatcher attempt."""

    intent_id: str
    recorded_at: str
    status: ProjectionOutcomeStatus
    receiver_row: int | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class ProjectionDispatchResult:
    """Returned by a one-shot dispatcher; it never retries in a loop."""

    intent: ProjectionIntent | None
    dispatch: ProjectionDispatch | None
    #: Set when the ledger could not be read (``LedgerUnreadableError``): nothing
    #: was recorded, the intent stays outstanding, and the caller should stop
    #: and report instead of trying the next intent.
    paused_reason: str | None = None


@dataclass(frozen=True)
class RebuiltProjection:
    """Freshly signed request reconstructed from the source ledger fact."""

    payload: Mapping[str, Any]
    provenance: LedgerProvenance


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@contextmanager
def _exclusive_outbox_lock(path: str | Path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_name(target.name + ".lock")
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _append_locked(path: str | Path, record: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(dict(record), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    with target.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_records(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    records: list[dict[str, Any]] = []
    with target.open("r", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
        try:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"projection outbox contains malformed JSON at line {line_number}") from exc
                if not isinstance(value, dict):
                    raise ValueError(f"projection outbox record at line {line_number} is not an object")
                records.append(value)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return records


def _intent_from_record(record: Mapping[str, Any]) -> ProjectionIntent:
    if record.get("kind") != "projection_intent_v1":
        raise ValueError("not a projection intent record")
    raw = record.get("intent")
    if not isinstance(raw, Mapping):
        raise ValueError("projection intent is missing")
    try:
        intent = ProjectionIntent(**dict(raw))
    except TypeError as exc:
        raise ValueError("projection intent is invalid") from exc
    if intent.action not in _ALLOWED_ACTIONS:
        raise ValueError("projection intent action is invalid")
    if intent.schema_version != LEDGER_PROJECTION_SCHEMA_VERSION:
        raise ValueError("projection intent schema is invalid")
    return intent


def enqueue_projection_intent(path: str | Path, *, action: ProjectionAction, provenance: LedgerProvenance) -> ProjectionIntent:
    """Persist one immutable intent before any network activity.

    Retrying the same immutable ledger projection returns the original intent;
    it never creates a second queue item for the same action and digest pair.
    """
    candidate = ProjectionIntent.from_provenance(action=action, provenance=provenance)
    with _exclusive_outbox_lock(path):
        for record in _read_records(path):
            if record.get("kind") != "projection_intent_v1":
                continue
            existing = _intent_from_record(record)
            if _intent_key(existing) == _intent_key(candidate):
                return existing
        _append_locked(path, {"kind": "projection_intent_v1", "intent": asdict(candidate)})
        return candidate


def outstanding_projection_intents(path: str | Path) -> tuple[ProjectionIntent, ...]:
    """Return intents needing a future one-shot attempt in creation order."""
    intents: dict[str, ProjectionIntent] = {}
    terminal: set[str] = set()
    for record in _read_records(path):
        kind = record.get("kind")
        if kind == "projection_intent_v1":
            intent = _intent_from_record(record)
            if intent.intent_id in intents:
                raise ValueError("projection outbox has duplicate intent_id")
            intents[intent.intent_id] = intent
        elif kind == "projection_dispatch_v1":
            raw = record.get("dispatch")
            if not isinstance(raw, Mapping):
                raise ValueError("projection dispatch is missing")
            try:
                dispatch = ProjectionDispatch(**dict(raw))
            except TypeError as exc:
                raise ValueError("projection dispatch is invalid") from exc
            if dispatch.status in _TERMINAL_STATUSES:
                terminal.add(dispatch.intent_id)
    return tuple(intent for intent in intents.values() if intent.intent_id not in terminal)  # file order = creation order; never sort by the 1-second created_at (f-21)


def record_projection_dispatch(path: str | Path, *, intent: ProjectionIntent, status: ProjectionOutcomeStatus, receiver_row: int | None = None, error_code: str | None = None) -> ProjectionDispatch:
    if status not in {"CONFIRMED", "REJECTED", "TRANSPORT_FAILED"}:
        raise ValueError("projection dispatch status is invalid")
    if receiver_row is not None and (not isinstance(receiver_row, int) or receiver_row < 2):
        raise ValueError("projection dispatch receiver row is invalid")
    if error_code is not None and (not isinstance(error_code, str) or not error_code):
        raise ValueError("projection dispatch error is invalid")
    dispatch = ProjectionDispatch(intent_id=intent.intent_id, recorded_at=_utc_now(), status=status, receiver_row=receiver_row, error_code=error_code)
    _append_locked(path, {"kind": "projection_dispatch_v1", "dispatch": asdict(dispatch)})
    return dispatch


def dispatch_next_projection(
    path: str | Path,
    *,
    rebuild: Callable[[ProjectionIntent], RebuiltProjection],
    submit: Callable[[Mapping[str, Any], LedgerProvenance], Any],
) -> ProjectionDispatchResult:
    """Attempt only the oldest outstanding intent once.

    ``rebuild`` must read the strategy's authoritative ledger and construct a
    fresh request id/timestamp/signature. A ``LedgerUnreadableError`` from it
    pauses the intent (nothing is recorded) rather than rejecting it. ``submit`` is transport only. Neither
    callback receives a secret from this module, and this dispatcher never loops
    or falls back to legacy synchronization.
    """
    with _exclusive_outbox_lock(path):
        intents = outstanding_projection_intents(path)
        if not intents:
            return ProjectionDispatchResult(None, None)
        intent = intents[0]
        try:
            rebuilt = rebuild(intent)
            _validate_rebuilt(intent, rebuilt)
        except LedgerUnreadableError as exc:
            # A damaged ledger is a repairable, temporary state: do not burn the
            # intent (a terminal REJECTED needs a manual re-queue to recover).
            return ProjectionDispatchResult(intent, None, paused_reason=str(exc) or "ledger unreadable")
        except Exception:
            return ProjectionDispatchResult(intent, record_projection_dispatch(path, intent=intent, status="REJECTED", error_code="rehydration_invalid"))
        try:
            submission = submit(rebuilt.payload, rebuilt.provenance)
            status = getattr(submission, "status", None)
            receiver_row = getattr(submission, "receiver_row", None)
            error_code = getattr(submission, "error_code", None)
            if status not in {"CONFIRMED", "REJECTED", "TRANSPORT_FAILED"}:
                status, receiver_row, error_code = "REJECTED", None, "submission_invalid"
        except Exception:
            status, receiver_row, error_code = "TRANSPORT_FAILED", None, "transport_failed"
        if status == "TRANSPORT_FAILED" and error_code == ORPHAN_CLOSE_ERROR and intent.action in _CLOSE_ACTIONS:
            if _consecutive_orphan_answers(path, intent.intent_id) + 1 >= ORPHAN_CLOSE_PARK_AFTER:
                status, receiver_row, error_code = "REJECTED", None, ORPHAN_CLOSE_PARKED_CODE
        elif status == "TRANSPORT_FAILED" and error_code == CORRECTION_UNCONFIRMED_ERROR and intent.action == "correct_close_v2":
            if _consecutive_answers(path, intent.intent_id, CORRECTION_UNCONFIRMED_ERROR) + 1 >= CORRECTION_UNCONFIRMED_PARK_AFTER:
                status, receiver_row, error_code = "REJECTED", None, CORRECTION_PARKED_CODE
        return ProjectionDispatchResult(intent, record_projection_dispatch(path, intent=intent, status=status, receiver_row=receiver_row, error_code=error_code))


def _consecutive_orphan_answers(path: str | Path, intent_id: str) -> int:
    """How many dispatches of this intent in a row were ``trade_id_not_found``."""
    return _consecutive_answers(path, intent_id, ORPHAN_CLOSE_ERROR)


def _consecutive_answers(path: str | Path, intent_id: str, code: str) -> int:
    """How many dispatches of this intent in a row ended with ``code``."""
    count = 0
    for record in _read_records(path):
        if record.get("kind") != "projection_dispatch_v1":
            continue
        raw = record.get("dispatch")
        if not isinstance(raw, Mapping) or raw.get("intent_id") != intent_id:
            continue
        count = count + 1 if raw.get("error_code") == code else 0
    return count


def requeue_rejected_projection_intents(path: str | Path, *, trade_id: str) -> tuple[ProjectionIntent, ...]:
    """Queue a fresh copy of every parked (REJECTED) intent of one trade, in its original order.

    ``enqueue_projection_intent`` returns the original intent for the same immutable projection, so a
    REJECTED one could never be sent again.  This is the supported recovery (f-25): for each immutable
    projection of ``trade_id`` whose latest intent ended REJECTED -- and that has no CONFIRMED or still
    outstanding intent -- append a new intent (new ``intent_id`` and ``created_at``, same digests).  The
    receiver and the dispatcher keep their usual checks, so a requeue cannot write anything the ledger does
    not back.  Returns the intents it queued (empty when there is nothing to recover).
    """
    with _exclusive_outbox_lock(path):
        intents: list[ProjectionIntent] = []
        last_status: dict[str, str] = {}
        for record in _read_records(path):
            kind = record.get("kind")
            if kind == "projection_intent_v1":
                intents.append(_intent_from_record(record))
            elif kind == "projection_dispatch_v1":
                raw = record.get("dispatch")
                if isinstance(raw, Mapping):
                    last_status[str(raw.get("intent_id"))] = str(raw.get("status"))
        by_key: dict[tuple[str, ...], list[ProjectionIntent]] = {}
        for intent in intents:
            if intent.trade_id == trade_id:
                by_key.setdefault(_intent_key(intent), []).append(intent)
        queued: list[ProjectionIntent] = []
        for key_intents in by_key.values():
            statuses = [last_status.get(i.intent_id) for i in key_intents]
            if "CONFIRMED" in statuses or any(s not in _TERMINAL_STATUSES for s in statuses):
                continue  # already delivered, or a copy is still waiting in the queue
            latest = key_intents[-1]
            queued.append(replace(latest, intent_id=uuid4().hex, created_at=_utc_now()))
        for intent in queued:
            _append_locked(path, {"kind": "projection_intent_v1", "intent": asdict(intent)})
        return tuple(queued)


def _validate_rebuilt(intent: ProjectionIntent, rebuilt: RebuiltProjection) -> None:
    provenance = rebuilt.provenance
    if provenance.schema_version != intent.schema_version:
        raise ValueError("schema mismatch")
    if (
        provenance.project_id != intent.project_id
        or provenance.trade_id != intent.trade_id
        or provenance.event_type != intent.event_type
        or provenance.source_id != intent.source_id
        or provenance.ledger_event_digest != intent.ledger_event_digest
        or provenance.payload_digest != intent.payload_digest
    ):
        raise ValueError("immutable projection binding changed")
    payload = rebuilt.payload
    if payload.get("action") != intent.action or payload.get("schema_version") != intent.schema_version:
        raise ValueError("payload action or schema mismatch")
    if payload.get("project_id") != intent.project_id or payload.get("source_id") != intent.source_id:
        raise ValueError("payload identity mismatch")
    if payload.get("provenance") != provenance.as_dict():
        raise ValueError("payload provenance mismatch")


def _intent_key(intent: ProjectionIntent) -> tuple[str, ...]:
    return (
        intent.action,
        intent.project_id,
        intent.trade_id,
        intent.event_type,
        intent.source_id,
        intent.ledger_event_digest,
        intent.payload_digest,
        intent.schema_version,
    )
