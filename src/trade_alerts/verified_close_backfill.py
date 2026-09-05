"""Exchange-agnostic evidence-building + append-only ledger repair for a
"verified-close backfill": a tracked position vanished from the exchange
without the strategy recording a ``trade_close`` (a race in the strategy's
own decoupled position-sync), and was later confirmed -- via a read-only
query of the exchange's own trade history -- to have genuinely closed for
real money.

This module never talks to an exchange and never constructs a ledger writer.
Callers resolve those two things themselves and pass in:

  * ``sell_fills`` -- exchange fills already normalized to the same shape
    ``trade_alerts.binance_reconcile_fetch``'s ``fills`` entries use
    (``trade_id``, ``order_id``, ``price``, ``quantity``, ``commission``,
    ``realized_pnl``, ``time_ms``, ...). Any exchange adapter that already
    emits that shape -- Binance today via ``binance_reconcile_fetch.fill_rows``,
    MEXC when a matching adapter exists -- can feed this directly, so a
    project's exchange reassignment needs no changes here.
  * ``ledger_append`` -- a callable bound to the caller's own ``TradeLedger``
    instance (each project has its own append-only ledger class; this module
    deliberately never imports one, so it stays usable regardless of which
    project's ledger schema it's writing into).

Two-stage flow, mirroring every other repair tool in this toolkit family
(``reconcile_apply.py``, ``safe_halt_resume.py``): build + preview the
evidence first, only append after an explicit second step.

  1. ``build_evidence(...)`` -> a schema ``1.0`` evidence dict. The caller
     writes it to disk (or not, for a preview-only run).
  2. ``append_repair(ledger_path, evidence_path, ledger_append=..., apply=...)``
     -- reads that evidence file back and, only when ``apply=True``, appends
     ``reconciliation_evidence_recorded`` / ``fill`` (one per deal) /
     ``trade_close`` / ``position_reconciled_closed`` events via the injected
     ``ledger_append``.

Consumers: ``mexc-4h-momentum-trailing-stop`` (Binance today); ``ed-seykota``
and ``my-crypto-bot`` planned.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

from .ledger_reconcile import read_ledger

_SCHEMA_VERSION = "1.0"
_DEFAULT_METHOD = "read_only_exchange_history"

REPAIR_EVENT_TYPES = frozenset({
    "reconciliation_evidence_recorded",
    "fill",
    "trade_close",
    "position_reconciled_closed",
})


class VerifiedCloseError(RuntimeError):
    """Raised for anything that should abort a backfill attempt (ambiguous
    fills, position still open, evidence already applied, ...). Callers
    decide how to surface it (a CLI turns this into ``SystemExit``, per the
    existing ``fetch_verified_close_evidence.py`` convention)."""


def _as_decimal(value: Any, *, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise VerifiedCloseError(f"invalid {field}: {value!r}") from exc


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _epoch_ms_to_iso(epoch_ms: int) -> str:
    return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------- #
# stage 1: build evidence from a local trade_open + exchange fills
# --------------------------------------------------------------------------- #
def find_open_event(events: list[dict[str, Any]], trade_id: str) -> dict[str, Any]:
    """The most recent ``trade_open`` for ``trade_id``. Refuses if the trade
    already has a ``trade_close`` -- this tool is only for a genuinely missing
    close, never a second opinion on an existing one."""
    opens = [e for e in events if e.get("event_type") == "trade_open" and e.get("trade_id") == trade_id]
    if not opens:
        raise VerifiedCloseError(f"no trade_open in the ledger for trade_id {trade_id}")
    if any(e.get("event_type") == "trade_close" and e.get("trade_id") == trade_id for e in events):
        raise VerifiedCloseError(f"trade_id {trade_id} already has a trade_close -- nothing to back-fill")
    return opens[-1]


def build_evidence(
    *,
    open_event: dict[str, Any],
    sell_fills: list[dict[str, Any]],
    trailing_order_id: str | None,
    artifact_name: str,
    method: str = _DEFAULT_METHOD,
    incident_prefix: str = "verified-close-backfill",
) -> dict[str, Any]:
    """Assemble a schema-``1.0`` evidence dict from a local ``trade_open`` and
    the exchange's closing-side fills that closed it.

    ``sell_fills`` entries must use the ``reconcile-source/v1`` fill shape
    (see ``binance_reconcile_fetch.fill_rows``): ``trade_id``, ``order_id``,
    ``price``, ``quantity``, ``commission``, ``realized_pnl``, ``time_ms``,
    ``side``. Despite the parameter name (kept for call-site stability), a
    *closing* fill is SELL for a long position but BUY for a short one --
    not every project this core serves is long-only (seykota trades both
    directions). Already side-filtered by the caller (this function trusts
    every entry in ``sell_fills`` is a close-side fill for this position; it
    only reads each entry's own ``side`` to label the deal accurately, it
    does not use ``side`` to decide inclusion).

    ``method`` records *how* this evidence was obtained (e.g.
    ``"read_only_binance_user_trades"``, ``"read_only_mexc_order_deals"``) so
    the eventual ledger repair event carries an accurate provenance label
    instead of a value hardcoded to whichever exchange this tool was first
    written against.
    """
    entry_volume = _as_decimal(open_event["volume"], field="open_event.volume")
    if not sell_fills:
        raise VerifiedCloseError(
            "no closing fills found on the exchange for this symbol/window -- "
            "the position may still be open, or the close is outside the lookback window"
        )

    deals: list[dict[str, Any]] = []
    exit_volume = Decimal("0")
    for f in sorted(sell_fills, key=lambda r: int(r.get("time_ms") or 0)):
        qty = _as_decimal(f.get("quantity"), field="fill.quantity")
        deals.append({
            "deal_id": str(f.get("trade_id")),
            "volume": str(qty),
            "price": str(_as_decimal(f.get("price"), field="fill.price")),
            "fee": str(_as_decimal(f.get("commission") or "0", field="fill.commission")),
            "profit": str(_as_decimal(f.get("realized_pnl") or "0", field="fill.realized_pnl")),
            # Each fill's own side, not a hardcoded "SELL" -- a short
            # position's real closing fills are BUY-side. Falls back to
            # "SELL" only when the caller's normalization left it unset
            # (backward compatible with any pre-existing long-only caller).
            "exchange_side": str(f.get("side") or "SELL").upper(),
        })
        exit_volume += qty

    if exit_volume != entry_volume:
        raise VerifiedCloseError(
            f"closing fills sum to {exit_volume} but the trade_open volume is {entry_volume}; "
            "refusing an ambiguous close (widen the lookback window, or reconcile by hand)"
        )

    last = max(sell_fills, key=lambda r: int(r.get("time_ms") or 0))
    occurred_at = _epoch_ms_to_iso(int(last["time_ms"]))
    exchange_profit = sum((Decimal(d["profit"]) for d in deals), Decimal("0"))
    artifact_sha256 = hashlib.sha256(_canonical(sorted(deals, key=lambda d: d["deal_id"])).encode()).hexdigest()

    return {
        "audit_schema_version": _SCHEMA_VERSION,
        "incident_id": f"{incident_prefix}-{str(open_event['trade_id'])[:12]}",
        "symbol": open_event["symbol"],
        "source": {
            "artifact_sha256": artifact_sha256,
            "artifact_name": artifact_name,
            "github_actions_run_id": None,
        },
        "trade": {
            "trade_id": open_event["trade_id"],
            "contract_size": str(_as_decimal(open_event.get("contract_size") or "1", field="contract_size")),
            "leverage": int(open_event.get("leverage") or 3),
            "entry": {
                "price": str(_as_decimal(open_event["price"], field="open_event.price")),
                "volume": str(entry_volume),
                "fee": str(_as_decimal(open_event.get("fee") or "0", field="open_event.fee")),
            },
            "close": {
                "order_id": str(last.get("order_id")),
                "occurred_at": occurred_at,
                "exchange_profit": str(exchange_profit),
                "originating_trailing_order_id": trailing_order_id,
                "deals": deals,
                "method": method,
            },
        },
    }


# --------------------------------------------------------------------------- #
# stage 2: append the evidence-backed repair to the local ledger
# --------------------------------------------------------------------------- #
def load_evidence(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("audit_schema_version") != _SCHEMA_VERSION:
        raise VerifiedCloseError("unsupported or malformed reconciliation evidence")
    source = payload.get("source")
    trade = payload.get("trade")
    if not isinstance(source, dict) or not isinstance(trade, dict):
        raise VerifiedCloseError("reconciliation evidence is missing source or trade data")
    if not isinstance(source.get("artifact_sha256"), str) or not source["artifact_sha256"]:
        raise VerifiedCloseError("reconciliation evidence is missing artifact SHA-256")
    if not isinstance(payload.get("incident_id"), str) or not payload["incident_id"]:
        raise VerifiedCloseError("reconciliation evidence is missing incident ID")
    if not isinstance(trade.get("entry"), dict) or not isinstance(trade.get("close"), dict):
        raise VerifiedCloseError("reconciliation evidence is missing entry or close data")
    if not isinstance(trade["close"].get("deals"), list) or not trade["close"]["deals"]:
        raise VerifiedCloseError("reconciliation evidence has no close deals")
    return payload


def _existing_repair(events: list[dict[str, Any]], *, trade_id: str, incident_id: str) -> bool:
    return any(
        event.get("trade_id") == trade_id
        and event.get("event_type") in {"trade_close", "position_reconciled_closed"}
        and isinstance(event.get("reconciliation"), dict)
        and event["reconciliation"].get("incident_id") == incident_id
        for event in events
    )


def _existing_close(events: list[dict[str, Any]], *, trade_id: str) -> bool:
    return any(event.get("event_type") == "trade_close" and event.get("trade_id") == trade_id for event in events)


def build_repair_events(evidence: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Build deterministic append-only events from verified exchange evidence."""
    source = evidence["source"]
    trade = evidence["trade"]
    entry = trade["entry"]
    close = trade["close"]
    deals = close["deals"]

    entry_price = _as_decimal(entry["price"], field="entry.price")
    entry_volume = _as_decimal(entry["volume"], field="entry.volume")
    entry_fee = _as_decimal(entry["fee"], field="entry.fee")
    contract_size = _as_decimal(trade["contract_size"], field="contract_size")
    leverage = int(trade["leverage"])
    exchange_profit = _as_decimal(close["exchange_profit"], field="close.exchange_profit")

    exit_volume = sum((_as_decimal(deal["volume"], field="deal.volume") for deal in deals), Decimal("0"))
    if exit_volume <= 0 or exit_volume != entry_volume:
        raise VerifiedCloseError("close deal volume does not exactly reconcile to entry volume")
    exit_price = sum(
        (_as_decimal(deal["price"], field="deal.price") * _as_decimal(deal["volume"], field="deal.volume")
         for deal in deals),
        Decimal("0"),
    ) / exit_volume
    exit_fee = sum((_as_decimal(deal["fee"], field="deal.fee") for deal in deals), Decimal("0"))
    # Direction from the closing fills' own side (every deal in one close
    # shares it): a BUY closes a short (profit when exit < entry) -- every
    # other value, including SELL, unrecognized strings, and pre-v0.14.0
    # evidence carrying MEXC's numeric side codes (e.g. the legacy MUBARAK
    # fixture's exchange_side=3), defaults to the long formula (profit when
    # exit > entry), which is what every evidence file predating
    # bidirectional support already assumed unconditionally. Only opt IN to
    # the short formula on an unambiguous "BUY" -- never opt out of the
    # long-standing default on an ambiguous or unrecognized value.
    closing_side = str(deals[0].get("exchange_side") or "").upper()
    direction = Decimal("-1") if closing_side == "BUY" else Decimal("1")
    gross_pnl = direction * (exit_price - entry_price) * exit_volume * contract_size
    total_fees = entry_fee + exit_fee
    net_pnl = gross_pnl - total_fees
    margin = entry_price * entry_volume * contract_size / Decimal(leverage) if leverage else Decimal("0")
    # ``method`` on old evidence predating this field falls back to a neutral
    # label rather than guessing which exchange it came from.
    reconciliation = {
        "incident_id": evidence["incident_id"],
        "artifact_sha256": source["artifact_sha256"],
        "github_actions_run_id": source.get("github_actions_run_id"),
        "method": close.get("method") or _DEFAULT_METHOD,
        "exchange_occurred_at": close["occurred_at"],
        "originating_trailing_order_id": close["originating_trailing_order_id"],
    }
    common = {
        "trade_id": trade["trade_id"],
        "symbol": evidence["symbol"],
        "closed_at": close["occurred_at"],
        "reconciliation": reconciliation,
    }
    events: list[tuple[str, dict[str, Any]]] = [
        (
            "reconciliation_evidence_recorded",
            {
                **common,
                "evidence_schema_version": evidence["audit_schema_version"],
                "evidence_artifact_sha256": source["artifact_sha256"],
                "evidence_artifact_name": source.get("artifact_name"),
                "evidence_run_id": source.get("github_actions_run_id"),
            },
        )
    ]
    for deal in deals:
        events.append(
            (
                "fill",
                {
                    **common,
                    "order_id": close["order_id"],
                    "action": "reconcile_missing_native_trailing_stop",
                    "side": deal.get("exchange_side"),
                    "volume": float(_as_decimal(deal["volume"], field="deal.volume")),
                    "price": float(_as_decimal(deal["price"], field="deal.price")),
                    "fee": float(_as_decimal(deal["fee"], field="deal.fee")),
                    "exchange_profit": float(_as_decimal(deal["profit"], field="deal.profit")),
                    "raw": {
                        "deal_id": deal.get("deal_id"),
                        "order_id": close["order_id"],
                        "source_artifact_sha256": source["artifact_sha256"],
                    },
                },
            )
        )
    events.extend(
        [
            (
                "trade_close",
                {
                    **common,
                    "entry_volume": float(entry_volume),
                    "exit_volume": float(exit_volume),
                    "entry_price": float(entry_price),
                    "exit_price": float(exit_price),
                    "contract_size": float(contract_size),
                    "leverage": leverage,
                    "entry_fee": float(entry_fee),
                    "exit_fee": float(exit_fee),
                    "total_fees": float(total_fees),
                    "gross_pnl": float(gross_pnl),
                    "net_pnl": float(net_pnl),
                    "return_on_margin": float(net_pnl / margin) if margin else None,
                    "order_id": close["order_id"],
                    "source": "native_trailing_stop",
                    "exchange_profit": float(exchange_profit),
                    "reconciliation_delta": float(net_pnl - exchange_profit),
                },
            ),
            (
                "position_reconciled_closed",
                {
                    **common,
                    "source": "native_trailing_stop",
                    "order_id": close["order_id"],
                    "exchange_profit": float(exchange_profit),
                    "net_pnl": float(net_pnl),
                },
            ),
        ]
    )
    return events


def append_repair(
    ledger_path: str | Path,
    evidence_path: str | Path,
    *,
    ledger_append: Callable[..., str],
    apply: bool = False,
) -> dict[str, Any]:
    """Preview or append one idempotent reconciliation repair; never touches
    strategy state.

    ``ledger_append`` is the caller's own ``TradeLedger.append`` (or
    equivalent) bound method -- this module never constructs a ledger writer
    itself, since every project in this toolkit family has its own
    ``TradeLedger`` class."""
    evidence = load_evidence(evidence_path)
    trade = evidence["trade"]
    events = read_ledger(ledger_path)
    if _existing_repair(events, trade_id=trade["trade_id"], incident_id=evidence["incident_id"]):
        raise VerifiedCloseError("this evidence-backed repair has already been appended")
    if _existing_close(events, trade_id=trade["trade_id"]):
        raise VerifiedCloseError("trade already has a close record; manual review is required")

    repair_events = build_repair_events(evidence)
    result = {
        "apply": apply,
        "incident_id": evidence["incident_id"],
        "trade_id": trade["trade_id"],
        "event_count": len(repair_events),
        "event_types": [event_type for event_type, _fields in repair_events],
        "state_file_touched": False,
    }
    if apply:
        result["appended_event_ids"] = [ledger_append(event_type, **fields) for event_type, fields in repair_events]
    return result
