from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

log = logging.getLogger("trade_alerts")


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    backoff_seconds: float = 2.0
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if self.attempts < 1:
            raise ValueError("attempts must be at least 1")
        if self.backoff_seconds < 0 or self.timeout_seconds <= 0:
            raise ValueError("backoff must be non-negative and timeout must be positive")


@dataclass(frozen=True)
class AlertEvent:
    event: str
    message: str
    critical: bool = False
    system: str = "automated-system"
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    fields: dict[str, Any] = field(default_factory=dict)

    def render(self) -> str:
        marker = "[CRITICAL]" if self.critical else "[INFO]"
        timestamp = self.occurred_at.astimezone(timezone.utc).isoformat(timespec="seconds")
        lines = [f"{marker} {self.system}", f"{self.event}", self.message, f"UTC: {timestamp}"]
        for key, value in self.fields.items():
            lines.append(f"{key}: {value}")
        return "\n".join(lines)


class AlertChannel(Protocol):
    name: str

    def send(self, text: str, *, timeout: float) -> None:
        ...


class AlertDispatcher:
    """Fan-out dispatcher. Channel errors are logged and do not alter caller control flow."""

    def __init__(self, channels: list[AlertChannel] | None = None, *, system: str = "automated-system"):
        self.channels = channels or []
        self.system = system

    def publish(
        self,
        event: str | AlertEvent,
        message: str | None = None,
        *,
        critical: bool = False,
        fields: dict[str, Any] | None = None,
    ) -> None:
        alert = event if isinstance(event, AlertEvent) else AlertEvent(
            event=event,
            message=message or "",
            critical=critical,
            fields=fields or {},
            system=self.system,
        )
        text = alert.render()
        for channel in self.channels:
            try:
                channel.send(text, timeout=getattr(channel, "policy", RetryPolicy()).timeout_seconds)
            except Exception:
                log.exception("alert channel failed: %s", getattr(channel, "name", "unknown"))

    def test(self) -> None:
        self.publish("TEST", "通知渠道測試成功。")


def request_with_retry(request_fn: Any, policy: RetryPolicy) -> Any:
    last_error: Exception | None = None
    for attempt in range(policy.attempts):
        try:
            return request_fn(policy.timeout_seconds)
        except Exception as exc:
            last_error = exc
            if attempt + 1 < policy.attempts:
                time.sleep(policy.backoff_seconds * (2**attempt))
    raise RuntimeError(f"request failed after {policy.attempts} attempts: {last_error}") from last_error
