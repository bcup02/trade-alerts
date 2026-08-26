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
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Mapping
from uuid import uuid4

from .ledger_integrity import LEDGER_PROJECTION_SCHEMA_VERSION, LedgerProvenance

ProjectionAction = Literal["append_open_v2", "update_close_v2"]
ProjectionOutcomeStatus = Literal["CONFIRMED", "REJECTED", "TRANSPORT_FAILED"]
_ALLOWED_ACTIONS = frozenset({"append_open_v2", "update_close_v2"})
_TERMINAL_STATUSES = frozenset({"CONFIRMED", "REJECTED"})


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
    return tuple(intent for intent in sorted(intents.values(), key=lambda value: (value.created_at, value.intent_id)) if intent.intent_id not in terminal)


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
    fresh request id/timestamp/signature. ``submit`` is transport only. Neither
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
        return ProjectionDispatchResult(intent, record_projection_dispatch(path, intent=intent, status=status, receiver_row=receiver_row, error_code=error_code))


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
