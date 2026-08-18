from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from .core import RetryPolicy, request_with_retry


@dataclass
class TelegramChannel:
    bot_token: str
    chat_id: str
    policy: RetryPolicy = RetryPolicy()
    name: str = "telegram"

    def send(self, text: str, *, timeout: float | None = None) -> None:
        if not self.bot_token or not self.chat_id:
            raise ValueError("Telegram credentials are incomplete")
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": text, "disable_web_page_preview": True}
        effective = self.policy if timeout is None else RetryPolicy(self.policy.attempts, self.policy.backoff_seconds, timeout)

        def call(request_timeout: float) -> Any:
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
        payload = {"to": self.recipient_id, "messages": [{"type": "text", "text": text[: self.max_text_length]}]}
        effective = self.policy if timeout is None else RetryPolicy(self.policy.attempts, self.policy.backoff_seconds, timeout)

        def call(request_timeout: float) -> Any:
            response = requests.post(url, headers=headers, json=payload, timeout=request_timeout)
            response.raise_for_status()
            return response

        request_with_retry(call, effective)
