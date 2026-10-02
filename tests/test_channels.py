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


import json

import pytest

from trade_alerts.channels import LINE_MAX_MESSAGES, TRUNCATION_MARK, split_text


def _line_messages(text: str, **kwargs) -> list[str]:
    with responses.RequestsMock() as mock:
        mock.add(responses.POST, "https://api.line.me/v2/bot/message/push", status=200)
        LineMessagingChannel("t", "U1", policy=RetryPolicy(attempts=1), **kwargs).send(text)
        return [m["text"] for m in json.loads(mock.calls[0].request.body)["messages"]]


def test_a_short_text_is_one_unchanged_line_message():
    assert _line_messages("hello") == ["hello"]


def test_a_long_text_is_split_at_line_breaks_not_cut_off():
    lines = [f"line {i:03d} " + "x" * 90 for i in range(120)]   # ~12k characters
    sent = _line_messages("\n".join(lines))
    assert len(sent) == 3 and all(len(piece) <= 5000 for piece in sent)
    assert "".join(sent) == "\n".join(lines)                    # nothing lost, nothing reordered
    assert all(piece.startswith("line ") for piece in sent)      # cut between lines, not inside one


def test_text_beyond_five_messages_says_it_was_cut():
    sent = _line_messages("a" * (5000 * 6 + 10))
    assert len(sent) == LINE_MAX_MESSAGES and sent[-1].endswith(TRUNCATION_MARK) and len(sent[-1]) <= 5000


def test_telegram_sends_the_rest_as_further_messages():
    with responses.RequestsMock() as mock:
        mock.add(responses.POST, "https://api.telegram.org/botsecret/sendMessage", json={"ok": True, "result": {}})
        mock.add(responses.POST, "https://api.telegram.org/botsecret/sendMessage", json={"ok": True, "result": {}})
        TelegramChannel("secret", "chat", policy=RetryPolicy(attempts=1)).send("a" * 4096 + "\n" + "b" * 10)
        bodies = [json.loads(call.request.body)["text"] for call in mock.calls]
    assert bodies == ["a" * 4096, "\n" + "b" * 10]


@pytest.mark.parametrize("text,limit", [
    ("abc", 5), ("ab\ncd\nef", 5), ("abcdefgh", 3), ("\n\nAAAAAA", 5), ("a\n\n\nb", 3), ("abc\n", 3), ("\n", 5),
    ("x\n\ny\n\n", 2), ("aaaa\n\nbbbb", 4), ("\n" + "A" * 4097, 4096), ("A" * 4096 + "\n", 4096),
])
def test_split_text_loses_nothing_and_never_yields_an_empty_piece(text, limit):
    pieces = split_text(text, limit)
    assert "".join(pieces) == text
    assert all(0 < len(p) <= limit for p in pieces)


def test_split_text_prefers_line_breaks():
    assert split_text("ab\ncd\nef", 5) == ["ab\n", "cd\nef"]


@pytest.mark.parametrize("text", ["\n" + "A" * 4097, "A" * 4096 + "\n", "\n\n" + "B" * 8200])
def test_telegram_never_sends_an_empty_or_blank_message_and_keeps_the_text(text):
    with responses.RequestsMock() as mock:
        for _ in range(4):
            mock.add(responses.POST, "https://api.telegram.org/botsecret/sendMessage", json={"ok": True, "result": {}})
        TelegramChannel("secret", "chat", policy=RetryPolicy(attempts=1)).send(text)
        bodies = [json.loads(c.request.body)["text"] for c in mock.calls]
        mock.assert_all_requests_are_fired = False
    assert bodies and all(b.strip() and len(b) <= 4096 for b in bodies)
    assert "".join(bodies).strip() == text.strip()


@pytest.mark.parametrize("text", ["\n" + "A" * 5001, "A" * 5000 + "\n"])
def test_line_never_sends_a_blank_message(text):
    sent = _line_messages(text)
    assert sent and all(m.strip() for m in sent) and "".join(sent).strip() == text.strip()
