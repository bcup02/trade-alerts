"""Pure, non-secret Google-ledger provenance contract.

This module deliberately has no HTTP, filesystem, Google, exchange, or strategy
state access.  A strategy adapter must first locate an exact append-only ledger
event, then use these helpers to build a signed projection request and a local
non-secret provenance record.  This keeps the authority boundary explicit:
Google is a projection of the ledger, never a source of a ledger event.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from typing import Any, Mapping
from uuid import UUID

LEDGER_PROJECTION_SCHEMA_VERSION = "google-ledger-projection-v2"
_ALLOWED_EVENT_TYPES = frozenset({"trade_open", "trade_close"})
_ALLOWED_ACTIONS = frozenset({"append_open_v2", "update_close_v2", "read_audit_v2", "read_reconciliation_v2", "quarantine_v2"})
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class LedgerIntegrityError(ValueError):
    """Raised before an invalid or ambiguous ledger projection can be sent."""


class ProjectionClassification(StrEnum):
    MATCHED = "MATCHED"
    PENDING_SYNC = "PENDING_SYNC"
    GOOGLE_NO_LEDGER_SOURCE = "GOOGLE_NO_LEDGER_SOURCE"
    DIGEST_MISMATCH = "DIGEST_MISMATCH"
    DUPLICATE_GOOGLE_TRADE_ID = "DUPLICATE_GOOGLE_TRADE_ID"
    SOURCE_REJECTED = "SOURCE_REJECTED"


@dataclass(frozen=True)
class LedgerProvenance:
    """Non-secret immutable evidence binding one projection to one ledger event."""

    project_id: str
    trade_id: str
    event_type: str
    ledger_event_digest: str
    payload_digest: str
    request_id: str
    issued_at: str
    source_id: str
    schema_version: str = LEDGER_PROJECTION_SCHEMA_VERSION

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class ProjectionComparison:
    """Result of a read-only comparison; it never instructs a writer to repair."""

    classification: ProjectionClassification
    trade_id: str
    detail: str


def canonical_json(value: Mapping[str, Any] | list[Any]) -> str:
    """Return one deterministic UTF-8 JSON representation suitable for digests.

    NaN and non-finite numbers are rejected because their JSON spellings vary
    between runtimes and would make a provenance digest non-auditable.
    """
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise LedgerIntegrityError("payload is not canonical JSON") from exc


def sha256_digest(value: Mapping[str, Any] | list[Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _projection_value(value: Any) -> Any:
    """Use JSON-stable strings for financial numbers crossing Python/Apps Script.

    JavaScript parses 15.0 as ``15`` while Python preserves ``15.0``. Converting
    all numeric projection leaves to non-exponent decimal strings before signing
    avoids an otherwise invisible cross-runtime HMAC mismatch. The receiver may
    convert allowlisted display values back to numbers only after verification.
    """
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise LedgerIntegrityError("projection contains non-finite number")
        return format(value, ".15f").rstrip("0").rstrip(".") or "0"
    if isinstance(value, list):
        return [_projection_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _projection_value(item) for key, item in value.items()}
    raise LedgerIntegrityError("projection contains unsupported value")


def normalise_projection(projection: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(projection, Mapping):
        raise LedgerIntegrityError("projection is not an object")
    return {str(key): _projection_value(value) for key, value in projection.items()}


def _require_identifier(name: str, value: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise LedgerIntegrityError(f"invalid {name}")


def _require_digest(name: str, value: str) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise LedgerIntegrityError(f"invalid {name}")


def _require_request_id(value: str) -> None:
    try:
        UUID(str(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise LedgerIntegrityError("invalid request_id") from exc


def build_provenance(
    *,
    project_id: str,
    trade_id: str,
    event_type: str,
    ledger_event: Mapping[str, Any],
    projection: Mapping[str, Any],
    request_id: str,
    issued_at: str,
    source_id: str,
) -> LedgerProvenance:
    """Build evidence only after the caller has selected an exact ledger event.

    The function validates identifiers but intentionally does not inspect a
    strategy's storage format.  That validation belongs in each thin adapter.
    """
    _require_identifier("project_id", project_id)
    _require_identifier("trade_id", trade_id)
    _require_identifier("source_id", source_id)
    if event_type not in _ALLOWED_EVENT_TYPES:
        raise LedgerIntegrityError("unsupported event_type")
    _require_request_id(request_id)
    if not isinstance(issued_at, str) or not issued_at:
        raise LedgerIntegrityError("invalid issued_at")
    return LedgerProvenance(
        project_id=project_id,
        trade_id=trade_id,
        event_type=event_type,
        ledger_event_digest=sha256_digest(dict(ledger_event)),
        payload_digest=sha256_digest(normalise_projection(projection)),
        request_id=request_id,
        issued_at=issued_at,
        source_id=source_id,
    )


def signed_request(
    *,
    action: str,
    sheet_name: str,
    provenance: LedgerProvenance,
    projection: Mapping[str, Any],
    source_hmac_secret: str,
) -> dict[str, Any]:
    """Build a v2 receiver payload with an HMAC over all non-secret contents.

    The HMAC secret is used only in memory.  It is never returned as part of
    the payload, provenance record, exception message, or log-friendly result.
    """
    if action not in _ALLOWED_ACTIONS:
        raise LedgerIntegrityError("unsupported action")
    _require_identifier("sheet_name", sheet_name)
    if not isinstance(source_hmac_secret, str) or not source_hmac_secret:
        raise LedgerIntegrityError("missing source signing credential")
    _require_digest("ledger_event_digest", provenance.ledger_event_digest)
    _require_digest("payload_digest", provenance.payload_digest)
    body: dict[str, Any] = {
        "schema_version": LEDGER_PROJECTION_SCHEMA_VERSION,
        "action": action,
        "source_id": provenance.source_id,
        "project_id": provenance.project_id,
        "sheet_name": sheet_name,
        "request_id": provenance.request_id,
        "issued_at": provenance.issued_at,
        "provenance": provenance.as_dict(),
        "projection": normalise_projection(projection),
    }
    signature = hmac.new(
        source_hmac_secret.encode("utf-8"), canonical_json(body).encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return {**body, "signature": signature}


def signed_reconciliation_request(
    *,
    project_id: str,
    sheet_name: str,
    source_id: str,
    request_id: str,
    issued_at: str,
    source_hmac_secret: str,
) -> dict[str, Any]:
    """Build the fixed, source-scoped Google inventory query for reconciliation.

    This request deliberately carries no ledger event or projection.  It can
    only read a receiver-generated inventory for the registered project/sheet;
    it cannot select arbitrary spreadsheet rows or invoke any write action.
    """
    _require_identifier("project_id", project_id)
    _require_identifier("sheet_name", sheet_name)
    _require_identifier("source_id", source_id)
    _require_request_id(request_id)
    if not isinstance(issued_at, str) or not issued_at:
        raise LedgerIntegrityError("invalid issued_at")
    if not isinstance(source_hmac_secret, str) or not source_hmac_secret:
        raise LedgerIntegrityError("missing source signing credential")
    body: dict[str, Any] = {
        "schema_version": LEDGER_PROJECTION_SCHEMA_VERSION,
        "action": "read_reconciliation_v2",
        "source_id": source_id,
        "project_id": project_id,
        "sheet_name": sheet_name,
        "request_id": request_id,
        "issued_at": issued_at,
        "query": {"kind": "source_projection_inventory_v1"},
    }
    signature = hmac.new(
        source_hmac_secret.encode("utf-8"), canonical_json(body).encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return {**body, "signature": signature}


def signed_read_audit_request(
    *,
    sheet_name: str,
    provenance: LedgerProvenance,
    projection: Mapping[str, Any],
    request_id: str,
    issued_at: str,
    source_hmac_secret: str,
) -> dict[str, Any]:
    """Build a fresh signed read-only audit query for an existing local proof.

    The caller must already have produced ``provenance`` from an exact local
    ledger event.  Reissuing only the nonce and timestamp keeps the receiver's
    replay window valid without altering the bound ledger/payload digests.
    """
    _require_request_id(request_id)
    if not isinstance(issued_at, str) or not issued_at:
        raise LedgerIntegrityError("invalid issued_at")
    fresh_provenance = replace(provenance, request_id=request_id, issued_at=issued_at)
    return signed_request(
        action="read_audit_v2",
        sheet_name=sheet_name,
        provenance=fresh_provenance,
        projection=projection,
        source_hmac_secret=source_hmac_secret,
    )


def verify_signed_request(payload: Mapping[str, Any], *, source_hmac_secret: str) -> bool:
    """Verify request integrity for deterministic tests and receiver parity checks."""
    if not isinstance(payload, Mapping) or not isinstance(source_hmac_secret, str) or not source_hmac_secret:
        return False
    signature = payload.get("signature")
    if not isinstance(signature, str) or not _SHA256_RE.fullmatch(signature):
        return False
    unsigned = {key: value for key, value in payload.items() if key != "signature"}
    expected = hmac.new(
        source_hmac_secret.encode("utf-8"), canonical_json(unsigned).encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


def comparison_for(
    *,
    trade_id: str,
    local_payload_digest: str | None,
    google_payload_digests: list[str],
    receiver_rejected: bool = False,
) -> ProjectionComparison:
    """Classify a read-only reconciliation result without mutating either system.

    A local provenance record binds two different digests: ``ledger_event_digest``
    proves the source event, while ``payload_digest`` proves the exact Google
    projection. The receiver audit must compare the latter. Comparing it to the
    ledger event digest would falsely flag every valid projection whose displayed
    fields are intentionally a subset of the ledger event.
    """
    _require_identifier("trade_id", trade_id)
    if receiver_rejected:
        return ProjectionComparison(ProjectionClassification.SOURCE_REJECTED, trade_id, "receiver rejected verified source")
    if local_payload_digest is None:
        return ProjectionComparison(ProjectionClassification.GOOGLE_NO_LEDGER_SOURCE, trade_id, "no local ledger provenance")
    _require_digest("local_payload_digest", local_payload_digest)
    if not google_payload_digests:
        return ProjectionComparison(ProjectionClassification.PENDING_SYNC, trade_id, "local ledger provenance has no confirmed Google projection")
    for digest in google_payload_digests:
        _require_digest("google_payload_digest", digest)
    if len(google_payload_digests) > 1:
        return ProjectionComparison(ProjectionClassification.DUPLICATE_GOOGLE_TRADE_ID, trade_id, "more than one Google projection has this trade_id")
    if google_payload_digests[0] != local_payload_digest:
        return ProjectionComparison(ProjectionClassification.DIGEST_MISMATCH, trade_id, "local and Google projection digests differ")
    return ProjectionComparison(ProjectionClassification.MATCHED, trade_id, "local and Google projection digests match")
