"""Non-secret cross-strategy reconciliation evidence contract."""
from __future__ import annotations

from typing import Any, Mapping

RECONCILIATION_EVIDENCE_SCHEMA_VERSION = "1.0"


class ReconciliationEvidenceValidationError(ValueError):
    """Raised when an adapter submits incomplete or ambiguous evidence."""


def _nonempty(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ReconciliationEvidenceValidationError(f"{field} 必須是非空白文字")
    return text


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ReconciliationEvidenceValidationError(f"{field} 必須是物件")
    return dict(value)


def _rows(value: Any, field: str) -> list[dict[str, Any]]:
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
    """Create and validate a non-secret, versioned evidence envelope."""
    return validate_reconciliation_evidence_v1({
        "schema_version": RECONCILIATION_EVIDENCE_SCHEMA_VERSION,
        "project_id": project_id,
        "trade_id": trade_id,
        "symbol": symbol,
        "local_position": dict(local_position),
        "exchange_observation": dict(exchange_observation),
        "close": dict(close),
        "source": dict(source),
    })


def validate_reconciliation_evidence_v1(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return a canonical evidence copy or reject incomplete input."""
    if not isinstance(payload, Mapping):
        raise ReconciliationEvidenceValidationError("evidence 必須是物件")
    if payload.get("schema_version") != RECONCILIATION_EVIDENCE_SCHEMA_VERSION:
        raise ReconciliationEvidenceValidationError("不支援的對帳證據契約版本")

    local = _mapping(payload.get("local_position"), "local_position")
    exchange = _mapping(payload.get("exchange_observation"), "exchange_observation")
    close = _mapping(payload.get("close"), "close")
    source = _mapping(payload.get("source"), "source")
    for field in ("entry_order_id", "entry_price", "entry_volume", "entry_fee", "close_side", "originating_protection_id"):
        _nonempty(local.get(field), f"local_position.{field}")
    deals = _rows(close.get("deals"), "close.deals")
    if deals:
        for field in ("order_id", "occurred_at"):
            _nonempty(close.get(field), f"close.{field}")
        for deal in deals:
            for field in ("order_id", "side", "volume", "price", "fee", "profit"):
                _nonempty(deal.get(field), f"close.deals[].{field}")
    normalized_exchange = {}
    for field in ("open_positions", "general_orders", "plan_orders", "tpsl_orders", "protections", "unattributed_protections"):
        normalized_exchange[field] = _rows(exchange.get(field), f"exchange_observation.{field}")
    for field in ("artifact_sha256", "adapter_version", "collected_at"):
        _nonempty(source.get(field), f"source.{field}")
    return {
        "schema_version": RECONCILIATION_EVIDENCE_SCHEMA_VERSION,
        "project_id": _nonempty(payload.get("project_id"), "project_id"),
        "trade_id": _nonempty(payload.get("trade_id"), "trade_id"),
        "symbol": _nonempty(payload.get("symbol"), "symbol"),
        "local_position": local,
        "exchange_observation": normalized_exchange,
        "close": {**close, "deals": deals},
        "source": source,
    }
