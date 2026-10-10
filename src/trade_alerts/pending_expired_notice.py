"""Tell the operator, once per marker, that a pending reconciliation gave up waiting (f-30).

``ledger_reconcile.exchange_ledger_compare`` stops holding the ledger axis at ``PENDING`` once a
``position_reconciliation_pending`` marker is older than its limit (24 h): it judges by the
comparison it already made and lists the markers it stopped waiting for under
``evidence["pending_expired"]``.  When the two sides agree the verdict is a plain ``RECONCILED``,
which says nothing about the unsettled marker -- the close it stands for still has no verified
fill, so its P&L may still be an estimate.  This module turns that evidence into one R3 fleet
event so the operator is told, with the steps to settle it.

Stateless and idempotent: whether a marker was already announced is read from the fleet event log
itself (``evidence["trade_ids"]`` of earlier events with the same code), so a killed run, a
restarted timer or a second caller can never announce the same marker twice, and a marker that
expires later gets its own notice.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

CODE_PENDING_EXPIRED = "LEDGER_PENDING_EXPIRED"

_REASON_TEXT = {
    "waited_over_limit": "超過上限仍沒結清",
    "time_unreadable": "標記的時間讀不出來，無法證明它是新的",
    "time_in_future": "標記的時間比現在還晚（時鐘或帳本有問題），無法證明它是新的",
}


def expired_markers(ledger_status: Any) -> list[dict[str, Any]]:
    """The markers the compare stopped waiting for, or ``[]`` for any other document shape."""
    if not isinstance(ledger_status, Mapping):
        return []
    evidence = ledger_status.get("evidence")
    block = evidence.get("pending_expired") if isinstance(evidence, Mapping) else None
    markers = block.get("markers") if isinstance(block, Mapping) else None
    if not isinstance(markers, list):
        return []
    return [m for m in markers if isinstance(m, Mapping) and str(m.get("trade_id") or "")]


def _announced_trade_ids(events: list[dict[str, Any]], project: str) -> set[str]:
    seen: set[str] = set()
    for event in events:
        if event.get("project") != project or event.get("code") != CODE_PENDING_EXPIRED:
            continue
        evidence = event.get("evidence")
        ids = evidence.get("trade_ids") if isinstance(evidence, Mapping) else None
        if isinstance(ids, list):
            seen.update(str(i) for i in ids)
    return seen


def plan_pending_expired_notice(
    ledger_status: Any, fleet_events: list[dict[str, Any]], *, project: str,
) -> dict[str, Any] | None:
    """The fields of the next event to write (``summary`` / ``evidence`` / ``details``), or ``None``.

    ``None`` when the verdict carries no ``pending_expired`` evidence or every marker in it was
    announced before.  The caller appends the event itself (``append_fleet_event`` with
    ``code=CODE_PENDING_EXPIRED`` and the tier it resolved from the error catalog), so the catalog
    entry can cite the one call that emits the code.
    """
    markers = expired_markers(ledger_status)
    if not markers:
        return None
    seen = _announced_trade_ids(fleet_events, project)
    fresh = [m for m in markers if str(m["trade_id"]) not in seen]
    if not fresh:
        return None

    max_hours = ledger_status["evidence"]["pending_expired"].get("max_hours")
    lines = [f"對帳等了超過 {max_hours} 小時，下面 {len(fresh)} 筆標記還沒結清；系統已不再等，改按實際比對判斷"
             f"（比對結果：{ledger_status.get('value')}）。"]
    for m in fresh:
        why = _REASON_TEXT.get(str(m.get("expired_reason")), str(m.get("expired_reason")))
        age = f"，已等 {m['age_hours']} 小時" if m.get("age_hours") is not None else ""
        lines.append(f"- 交易編號：{m['trade_id']}　商品：{m.get('symbol')}　數量：{m.get('volume')}"
                     f"　標記時間：{m.get('event_time')}{age}（{why}）")
    return {
        "summary": f"{len(fresh)} pending reconciliation marker(s) unsettled past the limit",
        "evidence": {"trade_ids": sorted(str(m["trade_id"]) for m in fresh)},
        "details": {"ledger_value": ledger_status.get("value"), "max_hours": max_hours,
                    "markers": fresh, "notice_text": "\n".join(lines)},
    }
