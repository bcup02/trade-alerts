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
    assert "\n".join(sent) == "\n".join(lines)                  # nothing lost, nothing reordered
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
    assert bodies == ["a" * 4096, "b" * 10]


@pytest.mark.parametrize("text,limit,expected", [
    ("", 5, [""]), ("abc", 5, ["abc"]), ("ab\ncd\nef", 5, ["ab\ncd", "ef"]), ("abcdefgh", 3, ["abc", "def", "gh"]),
])
def test_split_text(text, limit, expected):
    assert split_text(text, limit) == expected
    assert "".join(p.replace("\n", "") for p in expected) == text.replace("\n", "")


@pytest.mark.parametrize("text,limit", [
    ("\n\nAAAAAA", 5), ("a\n\n\nb", 3), ("abc\n", 3), ("\n", 5), ("x\n\ny\n\n", 2), ("aaaa\n\nbbbb", 4),
])
def test_split_text_keeps_blank_lines(text, limit):
    pieces = split_text(text, limit)
    assert all(len(p) <= limit for p in pieces)
    # whole lines are rejoined with the newline the split removed; only a hard cut inside a line adds one
    assert "".join(pieces).count("\n") + (len(pieces) - 1) >= text.count("\n")
    assert split_text("\n\nAAAAAA", 5)[0] == "\n"
    assert "\n".join(split_text("a\n\n\nb", 3)) == "a\n\n\nb"
