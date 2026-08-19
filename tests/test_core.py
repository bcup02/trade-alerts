from datetime import datetime, timezone

from trade_alerts import AlertDispatcher, AlertEvent, RetryPolicy


class RecordingChannel:
    name = "recording"
    policy = RetryPolicy(attempts=1)

    def __init__(self):
        self.messages = []

    def send(self, text, *, timeout):
        self.messages.append((text, timeout))


def test_event_render_contains_system_and_fields():
    event = AlertEvent(
        event="ENTRY",
        message="opened long",
        system="strategy-a",
        occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        fields={"symbol": "BTC_USDT", "contracts": 1},
    )
    rendered = event.render()
    assert "strategy-a" in rendered
    assert "ENTRY" in rendered
    assert "symbol: BTC_USDT" in rendered


def test_dispatcher_fans_out():
    channel = RecordingChannel()
    AlertDispatcher([channel], system="test").publish("TEST", "hello")
    assert len(channel.messages) == 1
    assert "hello" in channel.messages[0][0]


def test_channel_failure_isolated():
    class Broken:
        name = "broken"
        policy = RetryPolicy(attempts=1)

        def send(self, text, *, timeout):
            raise RuntimeError("offline")

    good = RecordingChannel()
    AlertDispatcher([Broken(), good]).publish("TEST", "still delivered")
    assert len(good.messages) == 1


def test_contract_mobile_presentation_hides_internal_metadata():
    channel = RecordingChannel()
    dispatcher = AlertDispatcher([channel], system="test")

    dispatcher.publish_contract(
        {
            "schema_version": "1.0",
            "event_id": "event-1",
            "event_type": "POSITION_OPENED",
            "project_id": "private-project-id",
            "project_name": "Private Project",
            "occurred_at": "2026-08-19T18:25:05Z",
            "execution_mode": "LIVE",
            "severity": "INFO",
            "message": "Machine-readable fallback.",
            "data": {"trade_id": "secret-internal-id", "ledger_event_type": "trade_open"},
            "presentation": {
                "format": "investor_mobile_v1",
                "text": "【MEXC 4H Momentum Trailing Stop】\n開倉通知\n\n標的：MUBARAK_USDT",
            },
        }
    )

    text = channel.messages[0][0]
    assert text == "【MEXC 4H Momentum Trailing Stop】\n開倉通知\n\n標的：MUBARAK_USDT"
    assert "trade_id" not in text
    assert "private-project-id" not in text
    assert "ledger_event_type" not in text
    assert "POSITION_OPENED" not in text
    assert "UTC:" not in text
