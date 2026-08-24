"""Versioned investor-facing contract helpers.

The helpers are intentionally dependency-free. They normalize the existing
AlertEvent-shaped API into the v1 envelope without changing delivery behavior.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class ContractEvent:
    event_id: str
    event_type: str
    project_id: str
    project_name: str
    occurred_at: str
    execution_mode: str
    severity: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_iso(value: datetime | None = None) -> str:
    value = value or datetime.now(timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def contract_event(
    *,
    event_id: str,
    event_type: str,
    project_id: str,
    project_name: str,
    execution_mode: str,
    severity: str,
    message: str,
    data: Mapping[str, Any] | None = None,
    occurred_at: datetime | None = None,
    presentation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a v1 event while leaving transport and trading decisions untouched.

    ``presentation`` is an optional, backward-compatible extension for a
    channel-specific investor view. Machine-readable timestamps and data remain
    in the canonical v1 fields.
    """
    envelope = ContractEvent(
        event_id=event_id,
        event_type=event_type,
        project_id=project_id,
        project_name=project_name,
        occurred_at=utc_iso(occurred_at),
        execution_mode=execution_mode,
        severity=severity,
        message=message,
        data=dict(data or {}),
    ).to_dict()
    if presentation is not None:
        envelope["presentation"] = dict(presentation)
    return envelope


def adapt_legacy_event(
    *,
    event: str,
    message: str,
    system: str,
    occurred_at: datetime,
    critical: bool = False,
    fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Map the stable pre-v1 AlertEvent API to a v1 envelope.

    The adapter deliberately preserves unknown fields and never invents absent
    trading values. It is suitable for old projects during gradual migration.
    """
    return contract_event(
        event_id=f"legacy-{occurred_at.timestamp():.6f}",
        event_type=event,
        project_id=system,
        project_name=system,
        occurred_at=occurred_at,
        execution_mode=str((fields or {}).get("execution_mode", "DRY_RUN")),
        severity="CRITICAL" if critical else "INFO",
        message=message,
        data=fields,
    )


def empty_performance() -> dict[str, Any]:
    """Return explicit nulls for windows whose source data is not available."""
    return {
        window: {
            "realized_pnl": None,
            "unrealized_pnl_change": None,
            "total_pnl": None,
            "trade_count": None,
            "win_count": None,
            "loss_count": None,
            "calculated_from": None,
        }
        for window in ("7d", "30d", "ytd", "1y")
    }


# ---------------------------------------------------------------------------
# Cross-strategy reconciliation evidence contract
# ---------------------------------------------------------------------------
# This contract intentionally contains no exchange client, credential, strategy
# state mutation, order operation, or notification operation.  It is only the
# non-secret data hand-off between a strategy-local restricted adapter and the
# central incident policy engine.
RECONCILIATION_EVIDENCE_SCHEMA_VERSION = "1.0"


class ReconciliationEvidenceValidationError(ValueError):
    """Raised when an adapter submits incomplete or ambiguous evidence."""


def _reconciliation_nonempty(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ReconciliationEvidenceValidationError(f"{field} 必須是非空白文字")
    return text


def _reconciliation_mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ReconciliationEvidenceValidationError(f"{field} 必須是物件")
    return dict(value)


def _reconciliation_rows(value: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(row, Mapping) for row in value):
        raise ReconciliationEvidenceValidationError(f"{field} 必須是物件陣列")
    return [dict(row) for row in value]


def reconciliation_evidence_v1(
    *,
    project_id: str,
    trade_id: str,
    symbol: str,
    local_position: Mapping[str, Any],
    exchange_observation: Mapping[str, Any],
    close: Mapping[str, Any],
    source: Mapping[str, Any],
) -> dict[str, Any]:
    """Create and validate a non-secret, versioned evidence envelope.

    The central policy never infers a close merely from a missing position.  A
    strategy adapter must supply the local open fact, a complete exchange
    inventory, actual close deals, and an immutable evidence digest.
    """
    payload = {
        "schema_version": RECONCILIATION_EVIDENCE_SCHEMA_VERSION,
        "project_id": project_id,
        "trade_id": trade_id,
        "symbol": symbol,
        "local_position": dict(local_position),
        "exchange_observation": dict(exchange_observation),
        "close": dict(close),
        "source": dict(source),
    }
    return validate_reconciliation_evidence_v1(payload)


def validate_reconciliation_evidence_v1(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a canonical evidence copy or reject incomplete input.

    Validation is deliberately structural.  Strategy-neutral policy evaluates
    volume, direction, attribution and double-read rules separately; this
    function ensures each strategy provides the same minimum raw facts.
    """
    if not isinstance(payload, Mapping):
        raise ReconciliationEvidenceValidationError("evidence 必須是物件")
    if payload.get("schema_version") != RECONCILIATION_EVIDENCE_SCHEMA_VERSION:
        raise ReconciliationEvidenceValidationError("不支援的對帳證據契約版本")

    local = _reconciliation_mapping(payload.get("local_position"), "local_position")
    exchange = _reconciliation_mapping(payload.get("exchange_observation"), "exchange_observation")
    close = _reconciliation_mapping(payload.get("close"), "close")
    source = _reconciliation_mapping(payload.get("source"), "source")

    for field in ("entry_order_id", "entry_price", "entry_volume", "entry_fee", "close_side", "originating_protection_id"):
        _reconciliation_nonempty(local.get(field), f"local_position.{field}")
    deals = _reconciliation_rows(close.get("deals"), "close.deals")
    # A no-deal observation is valid *evidence of insufficient proof*, not an
    # invalid payload.  The central policy must retain the event and escalate
    # it to MANUAL_REQUIRED; rejecting it here would discard that safety signal.
    if deals:
        for field in ("order_id", "occurred_at"):
            _reconciliation_nonempty(close.get(field), f"close.{field}")
        for deal in deals:
            for field in ("order_id", "side", "volume", "price", "fee", "profit"):
                _reconciliation_nonempty(deal.get(field), f"close.deals[].{field}")

    normalized_exchange = {}
    for field in ("open_positions", "general_orders", "plan_orders", "tpsl_orders", "protections", "unattributed_protections"):
        normalized_exchange[field] = _reconciliation_rows(exchange.get(field), f"exchange_observation.{field}")
    for field in ("artifact_sha256", "adapter_version", "collected_at"):
        _reconciliation_nonempty(source.get(field), f"source.{field}")

    return {
        "schema_version": RECONCILIATION_EVIDENCE_SCHEMA_VERSION,
        "project_id": _reconciliation_nonempty(payload.get("project_id"), "project_id"),
        "trade_id": _reconciliation_nonempty(payload.get("trade_id"), "trade_id"),
        "symbol": _reconciliation_nonempty(payload.get("symbol"), "symbol"),
        "local_position": local,
        "exchange_observation": normalized_exchange,
        "close": {**close, "deals": deals},
        "source": source,
    }
