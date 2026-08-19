from datetime import datetime, timezone

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
