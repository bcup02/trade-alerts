from __future__ import annotations

import os

from .channels import LineMessagingChannel, TelegramChannel
from .core import AlertDispatcher, RetryPolicy


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def dispatcher_from_env(*, system: str | None = None) -> AlertDispatcher:
    if not _as_bool(os.getenv("ALERTS_ENABLED"), False):
        return AlertDispatcher([], system=system or os.getenv("ALERTS_SYSTEM", "automated-system"))

    policy = RetryPolicy(
        attempts=int(os.getenv("ALERTS_RETRY_ATTEMPTS", "3")),
        backoff_seconds=float(os.getenv("ALERTS_RETRY_BACKOFF_SECONDS", "2")),
        timeout_seconds=float(os.getenv("ALERTS_TIMEOUT_SECONDS", "10")),
    )
    channels = []
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat = os.getenv("TELEGRAM_CHAT_ID", "")
    telegram_enabled = _as_bool(os.getenv("TELEGRAM_ALERTS_ENABLED"), True)
    if telegram_enabled and telegram_token and telegram_chat:
        channels.append(TelegramChannel(telegram_token, telegram_chat, policy=policy))

    line_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
    line_recipient = os.getenv("LINE_RECIPIENT_ID", os.getenv("LINE_TO", ""))
    line_enabled = _as_bool(os.getenv("LINE_ALERTS_ENABLED"), True)
    if line_enabled and line_token and line_recipient:
        channels.append(LineMessagingChannel(line_token, line_recipient, policy=policy))

    return AlertDispatcher(channels, system=system or os.getenv("ALERTS_SYSTEM", "automated-system"))
