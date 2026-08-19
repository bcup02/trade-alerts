from trade_alerts.factory import dispatcher_from_env


def _configure(monkeypatch):
    monkeypatch.setenv("ALERTS_ENABLED", "1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "telegram-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "line-token")
    monkeypatch.setenv("LINE_RECIPIENT_ID", "U123")


def test_both_channels_enabled_by_default(monkeypatch):
    _configure(monkeypatch)

    dispatcher = dispatcher_from_env(system="test")

    assert {channel.name for channel in dispatcher.channels} == {"telegram", "line_messaging_api"}


def test_line_can_be_disabled_independently(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setenv("LINE_ALERTS_ENABLED", "0")

    dispatcher = dispatcher_from_env(system="test")

    assert [channel.name for channel in dispatcher.channels] == ["telegram"]


def test_telegram_can_be_disabled_independently(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setenv("TELEGRAM_ALERTS_ENABLED", "false")

    dispatcher = dispatcher_from_env(system="test")

    assert [channel.name for channel in dispatcher.channels] == ["line_messaging_api"]
