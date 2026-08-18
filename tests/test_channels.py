import responses

from trade_alerts import LineMessagingChannel, RetryPolicy, TelegramChannel


def test_telegram_payload_and_endpoint():
    with responses.RequestsMock() as mock:
        mock.add(
            responses.POST,
            "https://api.telegram.org/botsecret/sendMessage",
            json={"ok": True, "result": {}},
            status=200,
        )
        TelegramChannel("secret", "chat", policy=RetryPolicy(attempts=1)).send("hello")
        request = mock.calls[0].request
        body = request.body.decode() if isinstance(request.body, bytes) else request.body
        assert request.url.endswith("/sendMessage")
        assert '"chat_id": "chat"' in body
        assert "secret" not in body
        assert request.headers["Content-Type"] == "application/json"


def test_line_payload_and_bearer_header():
    with responses.RequestsMock() as mock:
        mock.add(responses.POST, "https://api.line.me/v2/bot/message/push", status=200)
        LineMessagingChannel("channel-secret", "U123", policy=RetryPolicy(attempts=1)).send("hello")
        request = mock.calls[0].request
        body = request.body.decode() if isinstance(request.body, bytes) else request.body
        assert request.headers["Authorization"] == "Bearer channel-secret"
        assert '"to": "U123"' in body
        assert "channel-secret" not in body
