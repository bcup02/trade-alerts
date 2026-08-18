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
