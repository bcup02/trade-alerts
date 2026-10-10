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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .fleet_event_log import append_fleet_event, exclusive_log_lock, read_fleet_events, utc_now_iso

CODE_PENDING_EXPIRED = "LEDGER_PENDING_EXPIRED"

_REASON_TEXT = {
    "waited_over_limit": "超過上限仍沒結清",
    "time_unreadable": "標記的時間讀不出來，無法證明它是新的",
    "time_in_future": "標記的時間比現在還晚（時鐘或帳本有問題），無法證明它是新的",
}


def expired_markers(ledger_status: Any) -> list[dict[str, Any]]:
    """The markers the compare stopped waiting for, or ``[]`` for any other document shape."""
    # Only a verdict that says the two sides agree: a DIVERGED / UNKNOWN / PENDING document keeps the
    # evidence but must not be announced as "matches, only the marker is left" (review #162 B2).
    if not isinstance(ledger_status, Mapping) or ledger_status.get("value") != "RECONCILED":
        return []
    evidence = ledger_status.get("evidence")
    block = evidence.get("pending_expired") if isinstance(evidence, Mapping) else None
    markers = block.get("markers") if isinstance(block, Mapping) else None
    if not isinstance(markers, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in markers:
        trade_id = str(m.get("trade_id") or "") if isinstance(m, Mapping) else ""
        if trade_id and trade_id not in seen:   # one entry per trade, whatever the document repeats (review #162 B3)
            seen.add(trade_id)
            out.append(dict(m))
    return out


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


# --------------------------------------------------------------------------- #
# btc-competition: one unsettled rebalance batch / fills after the last snapshot
# --------------------------------------------------------------------------- #
_MAX_EPISODE_IDS = 50


def _valid_batch_block(block: Any) -> bool:
    """A usable competition ``pending_expired`` block: a known reason and a finite, positive limit.
    An empty or half-filled dict is not evidence of anything and must not become an R3 event."""
    if not isinstance(block, Mapping) or "markers" in block or block.get("reason") not in _REASON_TEXT:
        return False
    limit = block.get("max_hours")
    return isinstance(limit, (int, float)) and not isinstance(limit, bool) and 0 < limit < float("inf")


def _batch_episode(block: Mapping[str, Any], moment: datetime) -> str:
    """Identity of one stuck period, strongest first:

    1. ``since`` -- when the oldest waiting thing began (readable times only);
    2. ``episode_ids`` -- the ledger event ids of the waiting rows (the competition supplies them when a
       time cannot be read): a different stuck period has different rows;
    3. neither: nothing identifies the period, so it is announced at most once per UTC day while it lasts.
       Never silently once-for-ever: a later, different period must not be swallowed by an old notice.
    """
    since = block.get("since")
    if isinstance(since, str) and since:
        return f"since:{since}"
    ids = block.get("episode_ids")
    if isinstance(ids, list):
        clean = sorted({str(i) for i in ids if isinstance(i, (str, int)) and str(i)})[:_MAX_EPISODE_IDS]
        if clean:
            return "ids:" + "|".join(clean)
    return f"unidentified:{block.get('reason')}:{moment.strftime('%Y-%m-%d')}"


def announce_batch_expired(
    ledger_status: Any,
    *,
    project: str,
    fleet_event_log: str | Path,
    risk_tier: str,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """The competition's version of the notice: its compare gives up waiting for an unsettled rebalance
    batch (or spot fills after the last holdings snapshot) after 24 h and records ONE
    ``evidence["pending_expired"]`` dict (not a marker list).  Written once per episode, only when the
    verdict is ``RECONCILED`` (balances agree); a DIVERGED verdict already has its own alert.

    The read of "already announced" and the append share one lock.  Returns the stored event, or
    ``None`` when there is nothing new.  Raises on an unreadable log or a failed write -- the caller
    isolates that, nothing has been announced then and the next round tries again.
    """
    if not isinstance(ledger_status, Mapping) or ledger_status.get("value") != "RECONCILED":
        return None
    evidence = ledger_status.get("evidence")
    block = evidence.get("pending_expired") if isinstance(evidence, Mapping) else None
    if not _valid_batch_block(block):
        return None
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    episode = _batch_episode(block, moment)
    with exclusive_log_lock(fleet_event_log):
        for event in read_fleet_events(fleet_event_log):
            ev = event.get("evidence")
            if (event.get("project") == project and event.get("code") == CODE_PENDING_EXPIRED
                    and isinstance(ev, Mapping) and ev.get("episode") == episode):
                return None
        age = f"，已等 {block['age_hours']} 小時" if block.get("age_hours") is not None else ""
        why = _REASON_TEXT.get(str(block.get("reason")), str(block.get("reason")))
        text = "\n".join([
            f"對帳等了超過 {block.get('max_hours')} 小時，有調倉批次或快照之後的現貨成交還沒結算；系統已不再等，"
            f"改按交易所餘額與帳本比對（比對結果：{ledger_status.get('value')}）。",
            f"- 開始等的時間：{block.get('since')}{age}（{why}）",
            f"- 沒有持倉快照就結束的調倉批次：{'有' if block.get('rebalance_batch_without_snapshot') else '沒有'}；"
            f"最後一份持倉快照之後的現貨成交：{block.get('spot_fills_after_last_snapshot')} 筆",
        ])
        return append_fleet_event(
            fleet_event_log, project=project, code=CODE_PENDING_EXPIRED, risk_tier=risk_tier,
            recorded_at=utc_now_iso(moment),
            summary="rebalance batch or spot fills unsettled past the limit",
            evidence={"episode": episode},
            details={"pending_expired": dict(block), "ledger_value": ledger_status.get("value"),
                     "notice_text": text},
        )
