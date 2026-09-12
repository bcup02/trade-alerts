"""Durable queue of open error-handling requests, one file per strategy.

A request is to an error what a pull request is to a commit: it names one
condition that crossed a threshold, carries the evidence and the catalog risk
tier, and stays open until something resolves it.  Opening one still notifies
nobody -- Phase 5's repair bot computes a concrete remedy first and only then
notifies, because a notification that merely restates a problem asks the reader
to do the analysis the machine could have done.

The queue lives in the strategy's ``audit/`` directory, deliberately **not** in
``/var/lib/*-control``.  That directory is 2770 setgid and writable by
ops-control, so a queue placed there would let the Telegram relay fabricate
pending items for the repair bot to act on.

``R0`` conditions can never open a request.  R0 means the action after detection
is fixed, so there is nothing for a request to be about -- those belong in
``fleet_event_log`` alone.  That rule is enforced here rather than left to each
caller, mirroring the catalog's own executable invariant that a MECHANICAL
verdict may not reach a notifying tier.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import uuid4

from .fleet_event_log import (
    PROJECT_CODE_PREFIXES,
    RISK_TIERS,
    append_jsonl,
    exclusive_log_lock,
    read_jsonl,
    utc_now_iso,
)

REQUEST_KIND = "error_request_v1"
OUTCOME_KIND = "error_request_outcome_v1"
FINGERPRINT_LENGTH = 12

#: A request leaves the queue only through one of these.  ``RESOLVED_AUTO`` is
#: an automatic remedy (R2, and R3 after its timeout), ``RESOLVED_HUMAN`` an
#: operator acting, ``SUPERSEDED`` the same condition re-opening with different
#: evidence, and ``WITHDRAWN`` the condition no longer holding on its own.
TERMINAL_STATUSES = frozenset({"RESOLVED_AUTO", "RESOLVED_HUMAN", "SUPERSEDED", "WITHDRAWN"})
#: Tiers that may open a request at all; see the module docstring for why R0
#: cannot.
REQUESTABLE_TIERS = frozenset(tier for tier in RISK_TIERS if tier != "R0")


class ErrorRequestError(ValueError):
    """A rejected request or outcome; the queue is append-only."""


def request_fingerprint(project: str, code: str, evidence: Mapping[str, Any] | None) -> str:
    """Identify "the same problem" for deduplication.

    Distinct from ``safe_halt_model.safe_halt_fingerprint``, which an operator
    pastes back to confirm *which latch* they are clearing: this one answers
    "have we already got a request open for this?" and therefore includes the
    project and excludes the human-readable reason.  Feeding it a latch's
    ``evidence`` makes both move together, which is what a caller opening a
    request about a latch wants.
    """
    core = {
        "project": _require_project(project),
        "code": _require_bare_code(code),
        "evidence": dict(evidence or {}),
    }
    try:
        blob = json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ErrorRequestError("request evidence is not canonical JSON") from exc
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:FINGERPRINT_LENGTH]


def _require_project(project: Any) -> str:
    if project not in PROJECT_CODE_PREFIXES:
        raise ErrorRequestError(f"unknown project {project!r}")
    return str(project)


def _require_bare_code(code: Any) -> str:
    if not isinstance(code, str) or not code:
        raise ErrorRequestError("condition code is required")
    if "." in code:
        raise ErrorRequestError(f"store the bare condition name, not the catalog code {code!r}")
    return code


def _require_requestable_tier(risk_tier: Any) -> str:
    if risk_tier not in RISK_TIERS:
        raise ErrorRequestError(f"unknown risk tier {risk_tier!r}")
    if risk_tier not in REQUESTABLE_TIERS:
        raise ErrorRequestError(
            f"{risk_tier} conditions never open a request: the action after detection is fixed, "
            "so record it in the fleet event log instead"
        )
    return str(risk_tier)


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ErrorRequestError(f"{label} must be a mapping")
    return dict(value)


def _require_canonical(record: Mapping[str, Any]) -> None:
    """Reject a non-canonical record as a queue error, not a log error.

    ``evidence`` is already checked while fingerprinting, but ``details`` and
    ``measurements`` are not; without this a caller catching
    ``ErrorRequestError`` would miss a NaN in either of them and see the
    underlying log module's exception type instead.
    """
    try:
        json.dumps(dict(record), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ErrorRequestError("queue record is not canonical JSON") from exc


def _requests(records: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.get("kind") != REQUEST_KIND:
            continue
        request = record.get("request")
        if not isinstance(request, Mapping):
            raise ErrorRequestError("queue record is missing its request")
        request_id = request.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            raise ErrorRequestError("queued request has no request_id")
        if request_id in found:
            raise ErrorRequestError("queue has duplicate request_id")
        found[request_id] = dict(request)
    return found


def _terminated(records: Iterable[Mapping[str, Any]]) -> set[str]:
    closed: set[str] = set()
    for record in records:
        if record.get("kind") != OUTCOME_KIND:
            continue
        outcome = record.get("outcome")
        if not isinstance(outcome, Mapping):
            raise ErrorRequestError("queue record is missing its outcome")
        if outcome.get("status") in TERMINAL_STATUSES:
            request_id = outcome.get("request_id")
            if isinstance(request_id, str) and request_id:
                closed.add(request_id)
    return closed


def open_error_request(
    path: str | Path,
    *,
    project: str,
    code: str,
    risk_tier: str,
    summary: str = "",
    evidence: Mapping[str, Any] | None = None,
    details: Mapping[str, Any] | None = None,
    measurements: Mapping[str, Any] | None = None,
    event_ref: str | None = None,
    opened_at: str | None = None,
) -> dict[str, Any]:
    """Open one request, or return the one already open for this exact problem.

    Idempotency is on ``(project, code, evidence)``: a condition that stays true
    for twenty polling cycles produces one request, not twenty.  Once that
    request is resolved, the same condition recurring opens a new one -- the
    strategy really did hit the problem a second time, and that is worth a
    second request rather than a silent reopen of a closed one.
    """
    fingerprint = request_fingerprint(project, code, evidence)
    tier = _require_requestable_tier(risk_tier)
    request = {
        "request_id": uuid4().hex,
        "opened_at": opened_at or utc_now_iso(),
        "project": _require_project(project),
        "code": _require_bare_code(code),
        "risk_tier": tier,
        "fingerprint": fingerprint,
        "summary": summary if isinstance(summary, str) else "",
        "evidence": _require_mapping(evidence, "evidence"),
        "details": _require_mapping(details, "details"),
        "measurements": _require_mapping(measurements, "measurements"),
        "event_ref": event_ref if isinstance(event_ref, str) and event_ref else None,
    }
    _require_canonical(request)
    with exclusive_log_lock(path):
        for existing in outstanding_error_requests(path):
            if existing.get("fingerprint") == fingerprint:
                return existing
        append_jsonl(path, {"kind": REQUEST_KIND, "request": request})
    return request


def outstanding_error_requests(path: str | Path) -> list[dict[str, Any]]:
    """Return still-open requests, oldest first."""
    records = read_jsonl(path, error=ErrorRequestError)
    requests = _requests(records)
    closed = _terminated(records)
    return sorted(
        (request for request_id, request in requests.items() if request_id not in closed),
        key=lambda request: (str(request.get("opened_at") or ""), str(request.get("request_id") or "")),
    )


def find_error_request(path: str | Path, request_id: str) -> dict[str, Any]:
    request = _requests(read_jsonl(path, error=ErrorRequestError)).get(request_id)
    if request is None:
        raise ErrorRequestError(f"no request {request_id!r} in queue")
    return request


def record_request_outcome(
    path: str | Path,
    *,
    request_id: str,
    status: str,
    note: str = "",
    details: Mapping[str, Any] | None = None,
    recorded_at: str | None = None,
) -> dict[str, Any]:
    """Close one open request and return the stored outcome.

    Closing a request that is already closed is refused rather than appended
    twice: an outcome is the audit record of what actually happened to it, so a
    second one would make the history ambiguous about which remedy ran.
    """
    if status not in TERMINAL_STATUSES:
        raise ErrorRequestError(f"unknown terminal status {status!r}")
    outcome = {
        "request_id": request_id,
        "recorded_at": recorded_at or utc_now_iso(),
        "status": status,
        "note": note if isinstance(note, str) else "",
        "details": _require_mapping(details, "details"),
    }
    _require_canonical(outcome)
    with exclusive_log_lock(path):
        records = read_jsonl(path, error=ErrorRequestError)
        if request_id not in _requests(records):
            raise ErrorRequestError(f"no request {request_id!r} in queue")
        if request_id in _terminated(records):
            raise ErrorRequestError(f"request {request_id!r} is already closed")
        append_jsonl(path, {"kind": OUTCOME_KIND, "outcome": outcome})
    return outcome
