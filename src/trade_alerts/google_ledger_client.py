"""Transport for the signed Google ledger receiver v2.

It deliberately does not know strategy state, exchange APIs, or fallback v1
endpoints.  A missing endpoint or receiver rejection records a local outcome
and returns failure; it never retries through an unauthenticated legacy path.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

import requests

from .ledger_integrity import LedgerProvenance
from .provenance_outbox import append_outbox_record


@dataclass(frozen=True)
class ProjectionSubmission:
    ok: bool
    status: str
    receiver_row: int | None
    error_code: str | None


@dataclass(frozen=True)
class ProjectionAuditRead:
    ok: bool
    audit: tuple[Mapping[str, Any], ...]
    error_code: str | None


@dataclass(frozen=True)
class ReconciliationInventoryRead:
    ok: bool
    items: tuple[Mapping[str, Any], ...]
    error_code: str | None


def _post_json(*, endpoint: str, payload: Mapping[str, Any], post: Callable[..., Any], get: Callable[..., Any]) -> Any:
    response = post(endpoint, json=dict(payload), timeout=15, allow_redirects=False)
    if response.status_code in (301, 302, 303) and response.headers.get("Location"):
        response = get(response.headers["Location"], timeout=15)
    response.raise_for_status()
    result = response.json()
    if not isinstance(result, dict):
        raise ValueError("receiver_invalid_response")
    return result


def read_projection_audit_v2(
    *,
    endpoint: str | None,
    payload: Mapping[str, Any],
    post: Callable[..., Any] = requests.post,
    get: Callable[..., Any] = requests.get,
) -> ProjectionAuditRead:
    """Read receiver audit only; this function creates no local audit record."""
    if payload.get("action") != "read_audit_v2":
        return ProjectionAuditRead(False, (), "audit_action_invalid")
    if not isinstance(endpoint, str) or not endpoint.startswith("https://"):
        return ProjectionAuditRead(False, (), "endpoint_not_configured")
    try:
        result = _post_json(endpoint=endpoint, payload=payload, post=post, get=get)
    except Exception:
        return ProjectionAuditRead(False, (), "transport_failed")
    if not result.get("ok"):
        return ProjectionAuditRead(False, (), str(result.get("error") or "receiver_invalid_response"))
    audit = result.get("audit")
    if not isinstance(audit, list) or not all(isinstance(row, Mapping) for row in audit):
        return ProjectionAuditRead(False, (), "audit_invalid_response")
    return ProjectionAuditRead(True, tuple(dict(row) for row in audit), None)


def read_reconciliation_inventory_v2(
    *,
    endpoint: str | None,
    payload: Mapping[str, Any],
    post: Callable[..., Any] = requests.post,
    get: Callable[..., Any] = requests.get,
) -> ReconciliationInventoryRead:
    """Read a source-scoped receiver inventory; never append an outbox record."""
    if payload.get("action") != "read_reconciliation_v2":
        return ReconciliationInventoryRead(False, (), "reconciliation_action_invalid")
    if not isinstance(endpoint, str) or not endpoint.startswith("https://"):
        return ReconciliationInventoryRead(False, (), "endpoint_not_configured")
    try:
        result = _post_json(endpoint=endpoint, payload=payload, post=post, get=get)
    except Exception:
        return ReconciliationInventoryRead(False, (), "transport_failed")
    if not result.get("ok"):
        return ReconciliationInventoryRead(False, (), str(result.get("error") or "receiver_invalid_response"))
    items = result.get("items")
    if not isinstance(items, list) or not all(isinstance(row, Mapping) for row in items):
        return ReconciliationInventoryRead(False, (), "inventory_invalid_response")
    return ReconciliationInventoryRead(True, tuple(dict(row) for row in items), None)


def submit_projection_v2(
    *,
    endpoint: str | None,
    payload: Mapping[str, Any],
    provenance: LedgerProvenance,
    outbox_path: str | Path,
    post: Callable[..., Any] = requests.post,
    get: Callable[..., Any] = requests.get,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = 3,
) -> ProjectionSubmission:
    """Submit one already-signed payload with bounded transport retries.

    No caller-provided free-form endpoint fallback is accepted. The function
    writes a non-secret PENDING outbox record before network activity and a
    terminal CONFIRMED/REJECTED/TRANSPORT_FAILED record afterwards.
    """
    action = payload.get("action") if isinstance(payload.get("action"), str) else "unknown"
    append_outbox_record(outbox_path, provenance=provenance, action=action, status="PENDING")
    if not isinstance(endpoint, str) or not endpoint.startswith("https://"):
        append_outbox_record(outbox_path, provenance=provenance, action=action, status="REJECTED", error_code="endpoint_not_configured")
        return ProjectionSubmission(False, "REJECTED", None, "endpoint_not_configured")
    last_transport_error = "transport_failed"
    for attempt in range(max(1, attempts)):
        try:
            result = _post_json(endpoint=endpoint, payload=payload, post=post, get=get)
            if not isinstance(result, dict) or not result.get("ok"):
                error_code = str(result.get("error") if isinstance(result, dict) else "receiver_invalid_response")
                append_outbox_record(outbox_path, provenance=provenance, action=action, status="REJECTED", error_code=error_code)
                return ProjectionSubmission(False, "REJECTED", None, error_code)
            row = result.get("row")
            if not isinstance(row, int) or row < 2:
                append_outbox_record(outbox_path, provenance=provenance, action=action, status="REJECTED", error_code="receiver_row_invalid")
                return ProjectionSubmission(False, "REJECTED", None, "receiver_row_invalid")
            append_outbox_record(outbox_path, provenance=provenance, action=action, status="CONFIRMED", receiver_row=row)
            return ProjectionSubmission(True, "CONFIRMED", row, None)
        except Exception:
            last_transport_error = "transport_failed"
            if attempt + 1 < max(1, attempts):
                sleep(min(2 ** attempt, 4))
    append_outbox_record(outbox_path, provenance=provenance, action=action, status="TRANSPORT_FAILED", error_code=last_transport_error)
    return ProjectionSubmission(False, "TRANSPORT_FAILED", None, last_transport_error)
