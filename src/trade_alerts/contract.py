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
) -> dict[str, Any]:
    """Build a v1 event while leaving transport and trading decisions untouched."""
    return ContractEvent(
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
