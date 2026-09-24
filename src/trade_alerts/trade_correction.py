"""Append-only corrections of a closed trade, derived from exchange fills.

A strategy ledger is append-only: a ``trade_close`` that recorded the wrong
volume, an estimated price or fee, or that missed a fill entirely (2026-09-21:
ed-seykota sent one entry twice and recorded only the first) is never edited.
Instead a ``trade_correction`` event is appended that restates the trade's
close summary as the exchange recorded it, together with the values it
supersedes.

Every consumer that reads a ledger applies the corrections the same way, via
this module:

* :func:`apply_trade_corrections` returns the event list with each corrected
  ``trade_close`` replaced by an effective copy (the fold, the sheet compare,
  investor figures);
* :func:`correction_order_ids` lists the exchange orders a correction accounts
  for (the ledger-vs-exchange fill check);
* a correction never changes the position a ledger implies: it is not an open
  or a close, and it is only valid for a closed trade whose corrected entry and
  exit volumes are equal.

:func:`build_trade_correction` computes a correction from the exchange's own
fills -- never from typed-in numbers -- and is shared by the operator tool and
the repair bot, so both produce the same event for the same evidence.

Pure: no I/O, no network, no ledger writes.  The caller appends the returned
fields with its own ledger writer (which adds ``event_id`` / ``event_time``).
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

TRADE_CORRECTION_EVENT = "trade_correction"
TRADE_CORRECTION_SCHEMA = "trade-correction/v1"

#: Why the recorded trade disagreed with the exchange.
REASON_CODES = frozenset({
    # the strategy sent an order the ledger never recorded (duplicate send)
    "DUPLICATE_ENTRY_UNRECORDED",
    # a fill the ledger did not record, cause not (yet) attributed
    "UNRECORDED_FILL",
    # recorded price / fee were estimates; the exchange fill supersedes them
    "ESTIMATED_FILL_SUPERSEDED",
})

#: The close-summary fields a correction restates.  ``exit_order_id`` maps to
#: the ``order_id`` of the ``trade_close`` it corrects.
CORRECTED_FIELDS = (
    "entry_volume", "exit_volume", "entry_price", "exit_price",
    "entry_fee", "exit_fee", "total_fees", "gross_pnl", "net_pnl",
    "return_on_margin", "exit_order_id",
)

_NUMERIC_FIELDS = tuple(name for name in CORRECTED_FIELDS if name != "exit_order_id")
_REQUIRED_FIELDS = (
    "schema_version", "trade_id", "symbol", "side", "reason_code", "reason",
    "corrects_event_ids", "exchange_order_ids", "added_fills", "previous",
    "corrected", "evidence",
)
_ABS_TOL = 1e-9
_REALIZED_PNL_TOL = 0.01


class TradeCorrectionError(ValueError):
    """A correction cannot be built, or an appended one no longer applies."""


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _oid(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _close_view(close: Mapping[str, Any]) -> dict[str, Any]:
    view = {name: close.get(name) for name in _NUMERIC_FIELDS}
    view["exit_order_id"] = _oid(close.get("order_id"))
    return view


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, str) or isinstance(b, str) or a is None or b is None:
        return _oid(a) == _oid(b)
    na, nb = _num(a), _num(b)
    if na is None or nb is None:
        return na is nb
    return abs(na - nb) <= _ABS_TOL * max(1.0, abs(na), abs(nb))


def _is_correction(event: Mapping[str, Any]) -> bool:
    return event.get("event_type") == TRADE_CORRECTION_EVENT


# --------------------------------------------------------------------------- #
# structural validation
# --------------------------------------------------------------------------- #
def validate_trade_correction(event: Mapping[str, Any]) -> None:
    """Raise :class:`TradeCorrectionError` unless ``event`` is a well-formed
    ``trade-correction/v1`` record.  Does not look at the rest of the ledger."""
    missing = [name for name in _REQUIRED_FIELDS if name not in event]
    if missing:
        raise TradeCorrectionError(f"trade_correction lacks {missing}")
    if event.get("schema_version") != TRADE_CORRECTION_SCHEMA:
        raise TradeCorrectionError("unsupported trade_correction schema_version")
    if event.get("reason_code") not in REASON_CODES:
        raise TradeCorrectionError("unknown trade_correction reason_code")
    if not isinstance(event.get("trade_id"), str) or not event["trade_id"]:
        raise TradeCorrectionError("trade_correction has no trade_id")
    for name in ("previous", "corrected"):
        block = event.get(name)
        if not isinstance(block, Mapping) or set(block) != set(CORRECTED_FIELDS):
            raise TradeCorrectionError(f"trade_correction {name} must carry exactly {CORRECTED_FIELDS}")
    corrected = event["corrected"]
    for name in _NUMERIC_FIELDS:
        if _num(corrected.get(name)) is None and not (name == "return_on_margin" and corrected.get(name) is None):
            raise TradeCorrectionError(f"trade_correction corrected.{name} is not a finite number")
    if not _same(corrected["entry_volume"], corrected["exit_volume"]):
        # A closed trade is flat: anything else would change the position the
        # ledger implies, which a correction must never do.
        raise TradeCorrectionError("corrected entry_volume and exit_volume differ")
    order_ids = event.get("exchange_order_ids")
    if not isinstance(order_ids, list) or not order_ids or not all(_oid(o) for o in order_ids):
        raise TradeCorrectionError("trade_correction exchange_order_ids must list the orders it accounts for")
    if not isinstance(event.get("added_fills"), list) or not isinstance(event.get("corrects_event_ids"), list):
        raise TradeCorrectionError("trade_correction added_fills / corrects_event_ids must be lists")


# --------------------------------------------------------------------------- #
# consumers
# --------------------------------------------------------------------------- #
def correction_order_ids(events: Iterable[Mapping[str, Any]]) -> set[str]:
    """Exchange order ids that appended corrections account for."""
    ids: set[str] = set()
    for event in events:
        if _is_correction(event):
            for order_id in event.get("exchange_order_ids") or []:
                oid = _oid(order_id)
                if oid:
                    ids.add(oid)
    return ids


def apply_trade_corrections(events: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return ``events`` with every corrected ``trade_close`` replaced by its
    effective copy (``corrected`` values applied, ``corrected_by`` listing the
    correction event ids).  Other events -- corrections included -- pass
    through unchanged.

    Corrections apply in file order to the *first* ``trade_close`` of their
    trade (the one every fold already treats as authoritative).  Each must
    name, in ``previous``, exactly the values it supersedes; a correction for a
    trade with no close, or whose ``previous`` no longer matches (an earlier
    correction changed them, or it was written against another ledger), raises
    :class:`TradeCorrectionError` -- never a silent partial application.
    """
    out = [dict(event) for event in events]
    first_close: dict[str, int] = {}
    for index, event in enumerate(out):
        tid = event.get("trade_id")
        if event.get("event_type") == "trade_close" and isinstance(tid, str) and tid not in first_close:
            first_close[tid] = index
    for event in out:
        if not _is_correction(event):
            continue
        validate_trade_correction(event)
        tid = event["trade_id"]
        if tid not in first_close:
            raise TradeCorrectionError(f"trade_correction for {tid} has no trade_close to correct")
        close = out[first_close[tid]]
        current = _close_view(close)
        stale = [name for name in CORRECTED_FIELDS if not _same(current.get(name), event["previous"].get(name))]
        if stale:
            raise TradeCorrectionError(f"trade_correction for {tid} no longer applies: {stale} changed")
        effective = dict(close)
        for name in _NUMERIC_FIELDS:
            effective[name] = event["corrected"][name]
        effective["order_id"] = event["corrected"]["exit_order_id"]
        effective["corrected_by"] = [*close.get("corrected_by", []), event.get("event_id")]
        out[first_close[tid]] = effective
    return out


def correction_projection_fields(event: Mapping[str, Any]) -> dict[str, Any]:
    """The correction-specific part of a ``correct_close_v2`` projection.

    A strategy adapter merges these over the non-corrected close fields it
    already projects (``trade_id``, ``exit_time``, ``leverage``, ``source``,
    ...) and adds ``corrects_payload_digest`` -- the digest of the projection
    currently in force for the trade, which only the adapter can rebuild.
    """
    validate_trade_correction(event)
    corrected = event["corrected"]
    previous = event["previous"]
    fields = {name: corrected[name] for name in _NUMERIC_FIELDS}
    fields["exit_order_id"] = corrected["exit_order_id"]
    fields["reason_code"] = event["reason_code"]
    fields["notes"] = (
        f"帳本更正 {event['reason_code']}：{event['reason']}"
        f"（淨損益 {_num(previous.get('net_pnl'))} → {_num(corrected['net_pnl'])}，"
        f"數量 {_num(previous.get('exit_volume'))} → {_num(corrected['exit_volume'])}）"
    )
    return fields


# --------------------------------------------------------------------------- #
# builder (operator tool + repair bot)
# --------------------------------------------------------------------------- #
def build_trade_correction(
    events: list[Mapping[str, Any]],
    *,
    trade_id: str,
    fills: Iterable[Mapping[str, Any]],
    reason_code: str,
    reason: str,
    evidence_source: str,
    qty_multiplier: float = 1.0,
) -> dict[str, Any]:
    """Compute the ``trade_correction`` fields for a closed trade from the
    exchange fills that make it up.

    ``fills`` are ``reconcile-source/v1`` fill rows (``order_id``, ``side``
    buy/sell, ``quantity``, ``price``, ``commission``, ``commission_asset``,
    optional ``realized_pnl`` / ``time_ms``) -- every fill of every order of the
    trade, entries and exits.  Every order the ledger already records for the
    trade must be among them: the correction restates the whole trade from the
    exchange, it does not patch a part of it.  ``qty_multiplier`` converts a
    fill quantity into the ledger's volume unit times price (1.0 when the
    ledger records base-asset quantity).
    """
    if reason_code not in REASON_CODES:
        raise TradeCorrectionError("unknown reason_code")
    if not isinstance(reason, str) or not reason.strip():
        raise TradeCorrectionError("a correction needs a human-readable reason")
    effective = apply_trade_corrections(list(events))
    opens = [e for e in effective if e.get("event_type") == "trade_open" and e.get("trade_id") == trade_id]
    closes = [e for e in effective if e.get("event_type") == "trade_close" and e.get("trade_id") == trade_id]
    if not opens:
        raise TradeCorrectionError(f"{trade_id} has no trade_open")
    if not closes:
        raise TradeCorrectionError(f"{trade_id} is not closed; only a closed trade can be corrected")
    close = closes[0]
    side = str(close.get("side") or opens[0].get("side") or "").lower()
    if side not in ("long", "short"):
        raise TradeCorrectionError(f"{trade_id} has no long/short side")
    entry_side, exit_side = ("buy", "sell") if side == "long" else ("sell", "buy")

    rows = [dict(f) for f in fills]
    if not rows:
        raise TradeCorrectionError("no exchange fills given")
    fill_order_ids = {_oid(f.get("order_id")) for f in rows}
    ledger_order_ids = {_oid(e.get("order_id")) for e in [*opens, close]} - {None}
    unseen = sorted(ledger_order_ids - fill_order_ids)
    if unseen:
        raise TradeCorrectionError(f"orders {unseen} recorded for {trade_id} are missing from the exchange fills")
    for fill in rows:
        if str(fill.get("side") or "").lower() not in (entry_side, exit_side):
            raise TradeCorrectionError(f"fill of order {fill.get('order_id')} has side {fill.get('side')!r}")
        if str(fill.get("commission_asset") or "").upper() != "USDT":
            raise TradeCorrectionError(f"fill of order {fill.get('order_id')} is not charged in USDT")
        for name in ("quantity", "price", "commission"):
            if _num(fill.get(name)) is None:
                raise TradeCorrectionError(f"fill of order {fill.get('order_id')} lacks {name}")

    def _leg(wanted: str) -> tuple[float, float, float]:
        leg = [f for f in rows if str(f.get("side")).lower() == wanted]
        qty = sum(_num(f["quantity"]) for f in leg)
        if qty <= 0:
            raise TradeCorrectionError(f"no {wanted} fills for {trade_id}")
        vwap = sum(_num(f["quantity"]) * _num(f["price"]) for f in leg) / qty
        return qty, vwap, sum(_num(f["commission"]) for f in leg)

    entry_qty, entry_price, entry_fee = _leg(entry_side)
    exit_qty, exit_price, exit_fee = _leg(exit_side)
    if abs(entry_qty - exit_qty) > _ABS_TOL * max(1.0, entry_qty):
        raise TradeCorrectionError(
            f"{trade_id} is not flat on the exchange fills (entered {entry_qty}, exited {exit_qty})"
        )
    direction = 1.0 if side == "long" else -1.0
    gross = (exit_price - entry_price) * entry_qty * qty_multiplier * direction
    exit_fills = [f for f in rows if str(f.get("side")).lower() == exit_side]
    realized = [_num(f.get("realized_pnl")) for f in exit_fills]
    if realized and all(value is not None for value in realized):
        if abs(gross - sum(realized)) > _REALIZED_PNL_TOL:
            raise TradeCorrectionError(
                f"computed gross {gross} disagrees with the exchange realized PnL {sum(realized)}"
            )
    net = gross - entry_fee - exit_fee
    leverage = _num(close.get("leverage"))
    margin = entry_price * entry_qty * qty_multiplier / leverage if leverage else None
    exit_order_ids = [_oid(f.get("order_id")) for f in sorted(exit_fills, key=lambda f: f.get("time_ms") or 0)]
    corrected = {
        "entry_volume": entry_qty,
        "exit_volume": exit_qty,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "entry_fee": entry_fee,
        "exit_fee": exit_fee,
        "total_fees": entry_fee + exit_fee,
        "gross_pnl": gross,
        "net_pnl": net,
        "return_on_margin": (net / margin) if margin else None,
        "exit_order_id": exit_order_ids[-1],
    }
    previous = _close_view(close)
    if all(_same(previous[name], corrected[name]) for name in CORRECTED_FIELDS):
        raise TradeCorrectionError(f"{trade_id} already agrees with the exchange; nothing to correct")

    recorded = ledger_order_ids | correction_order_ids(
        e for e in effective if e.get("trade_id") == trade_id
    )
    added = [
        {"order_id": _oid(f.get("order_id")), "side": str(f.get("side")).lower(),
         "quantity": _num(f.get("quantity")), "price": _num(f.get("price")),
         "fee": _num(f.get("commission")), "time_ms": f.get("time_ms")}
        for f in rows if _oid(f.get("order_id")) not in recorded
    ]
    fields = {
        "schema_version": TRADE_CORRECTION_SCHEMA,
        "trade_id": trade_id,
        "symbol": close.get("symbol") or opens[0].get("symbol"),
        "side": side,
        "execution_mode": close.get("execution_mode") or opens[0].get("execution_mode"),
        "reason_code": reason_code,
        "reason": reason.strip(),
        "corrects_event_ids": [e.get("event_id") for e in [*opens, close] if e.get("event_id")],
        "exchange_order_ids": sorted(fill_order_ids - {None}),
        "added_fills": added,
        "previous": previous,
        "corrected": corrected,
        "evidence": {"source": evidence_source, "fills": sorted(
            ({"order_id": _oid(f.get("order_id")), "side": str(f.get("side")).lower(),
              "quantity": _num(f.get("quantity")), "price": _num(f.get("price")),
              "commission": _num(f.get("commission")), "realized_pnl": _num(f.get("realized_pnl")),
              "time_ms": f.get("time_ms")} for f in rows),
            key=lambda f: (f["time_ms"] or 0, f["order_id"] or ""),
        )},
    }
    validate_trade_correction(fields)
    return fields


__all__ = [
    "CORRECTED_FIELDS",
    "REASON_CODES",
    "TRADE_CORRECTION_EVENT",
    "TRADE_CORRECTION_SCHEMA",
    "TradeCorrectionError",
    "apply_trade_corrections",
    "build_trade_correction",
    "correction_order_ids",
    "correction_projection_fields",
    "validate_trade_correction",
]
