"""Transport for the signed Google ledger receiver v2.

It deliberately does not know strategy state, exchange APIs, or fallback v1
endpoints.  A missing endpoint or receiver rejection records a local outcome
and returns failure; it never retries through an unauthenticated legacy path.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import urlparse
from pathlib import Path
from typing import Any, Callable, Mapping

import requests

from .ledger_integrity import LedgerProvenance
from .provenance_outbox import append_outbox_record


_PROJECTION_SUBMISSION_ACTIONS = frozenset({"append_open_v2", "update_close_v2"})

# Receiver ``ok: false`` errors that mean the payload itself is structurally
# wrong -- the SAME intent can never succeed, so its dispatch is terminal.
# Every other receiver error (unauthorized, signature_invalid, request_not_fresh,
# source_not_allowed, unsupported_action/schema from a stale deployment,
# sheet_not_found, malformed_request) is a configuration/transport problem the
# same intent survives once the operator fixes it -> retryable, so a durable
# outbox keeps the intent instead of burning it.
_TERMINAL_RECEIVER_ERRORS = frozenset({
    "provenance_invalid",
    "open_projection_invalid",
    "close_projection_invalid",
})


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


def _permitted_redirect(endpoint: str, location: str) -> str:
    """Accept only HTTPS redirects to the same host or Apps Script content host."""
    origin = urlparse(endpoint)
    target = urlparse(location)
    if origin.scheme != "https" or target.scheme != "https" or not origin.hostname or not target.hostname:
        raise ValueError("receiver_redirect_not_allowed")
    allowed_hosts = {origin.hostname.lower()}
    # Apps Script web apps normally redirect script.google.com to the official
    # script.googleusercontent.com response host; no arbitrary host is allowed.
    if origin.hostname.lower() == "script.google.com":
        allowed_hosts.add("script.googleusercontent.com")
    if target.hostname.lower() not in allowed_hosts or target.username or target.password:
        raise ValueError("receiver_redirect_not_allowed")
    return location


def _post_json(*, endpoint: str, payload: Mapping[str, Any], post: Callable[..., Any], get: Callable[..., Any]) -> Any:
    response = post(endpoint, json=dict(payload), timeout=15, allow_redirects=False)
    if response.status_code in (301, 302, 303) and response.headers.get("Location"):
        response = get(_permitted_redirect(endpoint, response.headers["Location"]), timeout=15)
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


def deliver_projection_v2(
    *,
    endpoint: str | None,
    payload: Mapping[str, Any],
    post: Callable[..., Any] = requests.post,
    get: Callable[..., Any] = requests.get,
    sleep: Callable[[float], None] = time.sleep,
    attempts: int = 3,
) -> ProjectionSubmission:
    """Deliver one signed payload without writing a local outbox record.

    This function is for a strategy-owned durable outbox worker. It accepts
    only fixed v2 projection actions and never uses a legacy or arbitrary
    endpoint fallback.
    """
    action = payload.get("action") if isinstance(payload.get("action"), str) else "unknown"
    if action not in _PROJECTION_SUBMISSION_ACTIONS:
        return ProjectionSubmission(False, "REJECTED", None, "action_not_allowed")
    if not isinstance(endpoint, str) or not endpoint.startswith("https://"):
        return ProjectionSubmission(False, "REJECTED", None, "endpoint_not_configured")
    for attempt in range(max(1, attempts)):
        try:
            result = _post_json(endpoint=endpoint, payload=payload, post=post, get=get)
            if not isinstance(result, dict) or not result.get("ok"):
                error = str(result.get("error") if isinstance(result, dict) else "receiver_invalid_response")
                status = "REJECTED" if error in _TERMINAL_RECEIVER_ERRORS else "TRANSPORT_FAILED"
                return ProjectionSubmission(False, status, None, error)
            row = result.get("row")
            if not isinstance(row, int) or row < 2:
                return ProjectionSubmission(False, "REJECTED", None, "receiver_row_invalid")
            return ProjectionSubmission(True, "CONFIRMED", row, None)
        except Exception:
            if attempt + 1 < max(1, attempts):
                sleep(min(2 ** attempt, 4))
    return ProjectionSubmission(False, "TRANSPORT_FAILED", None, "transport_failed")


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
    """Backward-compatible direct submit with the existing provenance lifecycle."""
    action = payload.get("action") if isinstance(payload.get("action"), str) else "unknown"
    if action not in _PROJECTION_SUBMISSION_ACTIONS:
        return ProjectionSubmission(False, "REJECTED", None, "action_not_allowed")
    append_outbox_record(outbox_path, provenance=provenance, action=action, status="PENDING")
    result = deliver_projection_v2(endpoint=endpoint, payload=payload, post=post, get=get, sleep=sleep, attempts=attempts)
    append_outbox_record(
        outbox_path,
        provenance=provenance,
        action=action,
        status=result.status,
        receiver_row=result.receiver_row,
        error_code=result.error_code,
    )
    return result
