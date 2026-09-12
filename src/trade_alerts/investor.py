"""Taipei-time display formatting shared across consumer projects.

The LINE/Telegram investor-query rendering this module used to hold
(``InvestorQueryController``, ``render_portfolio_snapshot``,
``render_closed_trades``, ...) was never adopted by any consumer -- each
project ended up rolling its own local rendering instead -- and was removed.
``taipei_time`` is the one piece that is still a live, actively used part of
the public API (e.g. mexc-4h-momentum-trailing-stop's notifications.py).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=TAIPEI).astimezone(TAIPEI) if parsed.tzinfo is None else parsed.astimezone(TAIPEI)
    except (TypeError, ValueError):
        return None


def taipei_time(value: Any) -> str:
    parsed = _parse_time(value)
    return parsed.strftime("%Y-%m-%d %H:%M") if parsed else "時間未提供"
