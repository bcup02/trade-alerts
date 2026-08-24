from datetime import datetime, timezone
import pytest

from trade_alerts import SCHEMA_VERSION, adapt_legacy_event, contract_event, empty_performance


def test_contract_event_has_stable_v1_envelope():
    event = contract_event(
        event_id="evt-1",
        event_type="ENTRY",
        project_id="seykota-btcusdt-4h",
        project_name="Seykota",
        execution_mode="DRY_RUN",
        severity="INFO",
        message="模擬進場",
        data={"symbol": "BTCUSDT", "contracts": 1},
        occurred_at=datetime(2026, 8, 19, 8, 0, tzinfo=timezone.utc),
    )
    assert event["schema_version"] == SCHEMA_VERSION == "1.0"
    assert event["occurred_at"] == "2026-08-19T08:00:00Z"
    assert event["data"]["contracts"] == 1


def test_legacy_event_is_adapted_without_inventing_fields():
    event = adapt_legacy_event(
        event="EXIT",
        message="舊介面事件",
        system="legacy-project",
        occurred_at=datetime(2026, 8, 19, 8, 0, tzinfo=timezone.utc),
        fields={"reason": "stop", "execution_mode": "DRY_RUN"},
    )
    assert event["schema_version"] == "1.0"
    assert event["project_id"] == "legacy-project"
    assert event["execution_mode"] == "DRY_RUN"
    assert "realized_pnl" not in event["data"]


def test_empty_performance_is_explicitly_incomplete():
    windows = empty_performance()
    assert set(windows) == {"7d", "30d", "ytd", "1y"}
    assert windows["7d"]["total_pnl"] is None
    assert windows["1y"]["calculated_from"] is None


from trade_alerts import (
    RECONCILIATION_EVIDENCE_SCHEMA_VERSION,
    ReconciliationEvidenceValidationError,
    reconciliation_evidence_v1,
    validate_reconciliation_evidence_v1,
)


def _reconciliation_payload():
    return {
        "project_id": "example-strategy",
        "trade_id": "trade-001",
        "symbol": "EXAMPLE_USDT",
        "local_position": {
            "entry_order_id": "open-001", "entry_price": "3.8", "entry_volume": "2",
            "entry_fee": "0.01", "close_side": 4, "originating_protection_id": "protect-001",
        },
        "exchange_observation": {
            "open_positions": [], "general_orders": [], "plan_orders": [],
            "tpsl_orders": [], "protections": [], "unattributed_protections": [],
        },
        "close": {
            "order_id": "close-001", "occurred_at": "2026-08-24T08:25:24Z",
            "deals": [{"order_id": "close-001", "side": 4, "volume": "2", "price": "3.679", "fee": "0.005", "profit": "-0.28"}],
        },
        "source": {"artifact_sha256": "a" * 64, "adapter_version": "example.v1", "collected_at": "2026-08-24T08:26:00Z"},
    }


def test_reconciliation_evidence_v1_has_stable_versioned_non_secret_envelope():
    payload = _reconciliation_payload()
    evidence = reconciliation_evidence_v1(**payload)
    assert evidence["schema_version"] == RECONCILIATION_EVIDENCE_SCHEMA_VERSION == "1.0"
    assert evidence["project_id"] == "example-strategy"
    assert evidence["close"]["deals"][0]["order_id"] == "close-001"


def test_reconciliation_evidence_retains_missing_deals_for_central_manual_escalation():
    payload = _reconciliation_payload()
    payload["close"]["deals"] = []
    evidence = reconciliation_evidence_v1(**payload)
    assert evidence["close"]["deals"] == []


def test_reconciliation_evidence_rejects_unknown_schema_without_mutation():
    payload = reconciliation_evidence_v1(**_reconciliation_payload())
    payload["schema_version"] = "9.9"
    with pytest.raises(ReconciliationEvidenceValidationError, match="不支援"):
        validate_reconciliation_evidence_v1(payload)
