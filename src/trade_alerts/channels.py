from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from .core import RetryPolicy, request_with_retry

#: LINE accepts at most this many message objects in one push.
LINE_MAX_MESSAGES = 5
TRUNCATION_MARK = "\n…（內容過長，後面已省略）"


def split_text(text: str, limit: int) -> list[str]:
    """Cut ``text`` into pieces of at most ``limit`` characters with
    ``"".join(pieces) == text`` -- nothing dropped, nothing reordered, no
    piece empty (except for empty input).  Each cut prefers the position just
    after the last line break inside the window, unless that would leave a
    whitespace-only piece, in which case it cuts at ``limit``.  A piece that is
    only whitespace can still occur at the very end; ``sendable`` drops those,
    because the APIs reject them and nothing visible is lost."""
    if limit < 1:
        raise ValueError("limit must be positive")
    pieces: list[str] = []
    rest = text
    while len(rest) > limit:
        cut = rest[:limit].rfind("\n") + 1
        if cut <= 0 or not rest[:cut].strip():
            cut = limit
        pieces.append(rest[:cut])
        rest = rest[cut:]
    pieces.append(rest)
    return pieces


def sendable(pieces: list[str], original: str) -> list[str]:
    """The pieces an API will accept (not whitespace-only); the original text
    when nothing is left, so an empty message fails exactly as it always did."""
    return [piece for piece in pieces if piece.strip()] or [original]


@dataclass
class TelegramChannel:
    bot_token: str
    chat_id: str
    policy: RetryPolicy = RetryPolicy()
    name: str = "telegram"
    max_text_length: int = 4096

    def send(self, text: str, *, timeout: float | None = None) -> None:
        if not self.bot_token or not self.chat_id:
            raise ValueError("Telegram credentials are incomplete")
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        effective = self.policy if timeout is None else RetryPolicy(self.policy.attempts, self.policy.backoff_seconds, timeout)

        # Telegram rejects a message over 4096 characters outright; send the
        # rest as further messages instead of losing it.
        for piece in sendable(split_text(text, self.max_text_length), text):
            payload = {"chat_id": self.chat_id, "text": piece, "disable_web_page_preview": True}

            def call(request_timeout: float, payload: dict = payload) -> Any:
                response = requests.post(url, json=payload, timeout=request_timeout)
                response.raise_for_status()
                data = response.json()
                if not data.get("ok", False):
                    raise RuntimeError(f"Telegram API error: {data}")
                return data

            request_with_retry(call, effective)


@dataclass
class LineMessagingChannel:
    channel_access_token: str
    recipient_id: str
    policy: RetryPolicy = RetryPolicy()
    name: str = "line_messaging_api"
    max_text_length: int = 5000

    def send(self, text: str, *, timeout: float | None = None) -> None:
        if not self.channel_access_token or not self.recipient_id:
            raise ValueError("LINE Messaging API credentials are incomplete")
        url = "https://api.line.me/v2/bot/message/push"
        headers = {
            "Authorization": f"Bearer {self.channel_access_token}",
            "Content-Type": "application/json",
        }
        # Over the limit the old code silently cut the text off (the tail of a
        # notice is what mattered most).  Split it across message objects of one
        # push; only beyond LINE_MAX_MESSAGES pieces is anything dropped, and
        # then the last piece says so.
        pieces = sendable(split_text(text, self.max_text_length), text)
        if len(pieces) > LINE_MAX_MESSAGES:
            pieces = pieces[:LINE_MAX_MESSAGES]
            pieces[-1] = pieces[-1][: self.max_text_length - len(TRUNCATION_MARK)] + TRUNCATION_MARK
        payload = {"to": self.recipient_id, "messages": [{"type": "text", "text": piece} for piece in pieces]}
        effective = self.policy if timeout is None else RetryPolicy(self.policy.attempts, self.policy.backoff_seconds, timeout)

        def call(request_timeout: float) -> Any:
            response = requests.post(url, headers=headers, json=payload, timeout=request_timeout)
            response.raise_for_status()
            return response

        request_with_retry(call, effective)
