from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from .core import RetryPolicy, request_with_retry

#: LINE accepts at most this many message objects in one push.
LINE_MAX_MESSAGES = 5
TRUNCATION_MARK = "\n…（內容過長，後面已省略）"


def split_text(text: str, limit: int) -> list[str]:
    """Cut ``text`` into pieces of at most ``limit`` characters, at line breaks
    where possible, so nothing is dropped.  A single line longer than ``limit``
    is cut at ``limit``.  Empty text gives one empty piece."""
    if limit < 1:
        raise ValueError("limit must be positive")
    if len(text) <= limit:
        return [text]
    pieces: list[str] = []
    current: str | None = None     # None: nothing accumulated (distinct from an empty line)
    for line in text.split("\n"):
        while len(line) > limit:
            if current is not None:
                pieces.append(current)
                current = None
            pieces.append(line[:limit])
            line = line[limit:]
        candidate = line if current is None else f"{current}\n{line}"
        if len(candidate) <= limit:
            current = candidate
        else:
            pieces.append(current if current is not None else "")
            current = line
    pieces.append(current if current is not None else "")
    return pieces


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
        for piece in split_text(text, self.max_text_length):
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
        pieces = split_text(text, self.max_text_length)
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
