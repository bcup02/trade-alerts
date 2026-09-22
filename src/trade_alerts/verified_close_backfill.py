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

Consumers: ``trade_alerts.repair_runner`` (the unattended path, which drives
stages 0-2 plus ``assess_repair`` for each strategy's adapter), and each
strategy's manual tools (``fetch_verified_close_evidence.py`` /
``append_reconciled_close.py``) -- momentum and seykota on Binance today,
my-crypto's estimated-close tool as a calculator.
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
    """The ``trade_open`` for ``trade_id``, folded into one entry leg when the
    strategy pyramids. Refuses if the trade already has a ``trade_close`` --
    this tool is only for a genuinely missing close, never a second opinion on
    an existing one.

    A strategy that adds to a position (seykota) writes one more
    ``trade_open`` per add under the same ``trade_id``, each carrying only
    that leg's ``volume``/``price``/``fee``. The exchange's closing fills
    close the whole position, so the evidence has to be built against the
    whole position: volumes and fees summed, the entry price volume-weighted,
    and the earliest ``event_epoch_ms`` -- the fetch window must reach back to
    the first leg, not the last. A single open (momentum, or seykota without
    adds) is returned unchanged.
    """
    opens = [e for e in events if e.get("event_type") == "trade_open" and e.get("trade_id") == trade_id]
    if not opens:
        raise VerifiedCloseError(f"no trade_open in the ledger for trade_id {trade_id}")
    if any(e.get("event_type") == "trade_close" and e.get("trade_id") == trade_id for e in events):
        raise VerifiedCloseError(f"trade_id {trade_id} already has a trade_close -- nothing to back-fill")
    if len(opens) == 1:
        return opens[0]
    return _fold_open_legs(opens)


def _fold_open_legs(opens: list[dict[str, Any]]) -> dict[str, Any]:
    for key in ("symbol", "side"):
        values = {str(leg.get(key)) for leg in opens}
        if len(values) != 1:
            raise VerifiedCloseError(
                f"the trade_open legs of trade_id {opens[0].get('trade_id')} disagree on {key} "
                f"({sorted(values)}); refusing to fold them into one position"
            )
    volumes = [_as_decimal(leg["volume"], field="open_event.volume") for leg in opens]
    volume = sum(volumes, Decimal("0"))
    if volume <= 0:
        raise VerifiedCloseError("the trade_open legs sum to a non-positive volume")
    price = sum(
        (_as_decimal(leg["price"], field="open_event.price") * leg_volume
         for leg, leg_volume in zip(opens, volumes)),
        Decimal("0"),
    ) / volume
    fee = sum((_as_decimal(leg.get("fee") or "0", field="open_event.fee") for leg in opens), Decimal("0"))
    epochs = [int(leg.get("event_epoch_ms") or 0) for leg in opens]
    return {
        **opens[0],
        "volume": str(volume),
        "price": str(price),
        "fee": str(fee),
        # 0 (unknown) on any leg makes the whole window unknown, never "the
        # other legs' minimum" -- callers refuse a trade_open without it.
        "event_epoch_ms": min(epochs) if all(epochs) else 0,
        "open_leg_count": len(opens),
    }


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
    # A fill the adapter could not attach realized P&L to is recorded as 0,
    # as before -- but then the summed exchange_profit is not the exchange's
    # word on this close, and build_repair_events must not treat it as the
    # authority. Flagged only when it happens, so evidence built from a
    # complete exchange response is unchanged.
    profit_unreported = any(f.get("realized_pnl") is None for f in sell_fills)
    for f in sorted(sell_fills, key=lambda r: int(r.get("time_ms") or 0)):
        qty = _as_decimal(f.get("quantity"), field="fill.quantity")
        deals.append({
            "deal_id": str(f.get("trade_id")),
            "volume": str(qty),
            "price": str(_as_decimal(f.get("price"), field="fill.price")),
            "fee": str(_as_decimal(f.get("commission") or "0", field="fill.commission")),
            "profit": str(_as_decimal(f.get("realized_pnl") or "0", field="fill.realized_pnl")),
            # Per-deal timestamp, so a later reader can check every deal lands
            # inside the trade's own lifetime without re-querying the exchange
            # (``close.occurred_at`` only carries the last one). Evidence files
            # written before this field exists simply lack it; readers that
            # need it must treat "absent" as unknown, never as "in range".
            "time_ms": int(f.get("time_ms") or 0),
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

    close: dict[str, Any] = {
        "order_id": str(last.get("order_id")),
        "occurred_at": occurred_at,
        "exchange_profit": str(exchange_profit),
        "originating_trailing_order_id": trailing_order_id,
        "deals": deals,
        "method": method,
    }
    if profit_unreported:
        close["exchange_profit_reported"] = False
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
            "close": close,
        },
    }


# --------------------------------------------------------------------------- #
# stage 2: append the evidence-backed repair to the local ledger
# --------------------------------------------------------------------------- #
def load_evidence(path: str | Path) -> dict[str, Any]:
    return validate_evidence(json.loads(Path(path).read_text(encoding="utf-8")))


def validate_evidence(payload: Any) -> dict[str, Any]:
    """The schema checks ``load_evidence`` applies, on evidence already in
    memory -- so an in-process caller gets exactly the same refusals as one
    reading the artefact back from disk, rather than a second, laxer path."""
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


def incident_traces(events: list[dict[str, Any]], *, incident_id: str) -> list[dict[str, Any]]:
    """Every ledger event already carrying this repair's ``incident_id``.

    Broader on purpose than ``_existing_repair``, which only looks at the two
    terminal event types. A repair is 4+ events; a batch that stopped part way
    can leave ``reconciliation_evidence_recorded`` and some ``fill`` events
    with no ``trade_close`` -- invisible to the terminal-type check, and the
    exact state an unattended repair must never write "the rest of" on a guess.
    Any trace at all means a human decides what happened.
    """
    return [
        event
        for event in events
        if isinstance(event.get("reconciliation"), dict)
        and event["reconciliation"].get("incident_id") == incident_id
    ]


#: Default ceiling, in quote currency, on how far our own gross P&L may sit
#: from the exchange's reported realized P&L before the exchange's figure is
#: written instead of ours (fleet-error-catalog/v2: the exchange is the
#: authority).
#:
#: Note this is *not* a bound on ``reconciliation_delta`` itself. Phase 4e
#: measured that delta to be exactly ``-(entry_fee + exit_fee)`` on every real
#: sample -- for a typical trade that is ~0.5 USDT, so bounding it directly by
#: a small number would reject every genuine repair. What a human actually
#: checks by eye is the part the fees do not explain: ``gross_pnl`` against the
#: exchange's own ``realized_pnl``. Those two describe the same quantity from
#: two sources, so anything past rounding noise means the evidence and the
#: local arithmetic disagree about what happened -- and the exchange wins.
#: The bound is absolute, not a fraction of notional: both sides are Decimal
#: sums over the same deals, so an agreeing exchange yields a residual of
#: exactly zero at any position size; the slack only absorbs exchange-side
#: rounding of each fill's realized P&L. The bound is inclusive.
DEFAULT_MAX_EXCHANGE_PNL_RESIDUAL = Decimal("0.01")


def build_repair_events(
    evidence: dict[str, Any],
    *,
    max_exchange_pnl_residual: Decimal = DEFAULT_MAX_EXCHANGE_PNL_RESIDUAL,
) -> list[tuple[str, dict[str, Any]]]:
    """Build deterministic append-only events from verified exchange evidence.

    P&L follows the exchange when the two sources disagree. Our gross P&L is
    recomputed from the deals; when it sits more than
    ``max_exchange_pnl_residual`` from the exchange's own realized P&L (and the
    exchange reported one for every deal), ``gross_pnl`` is the exchange's
    figure, ``net_pnl`` / ``return_on_margin`` follow from it, and the
    ``reconciliation`` block records ``pnl_source: "exchange_realized"`` with
    our figure and the gap, so the override is visible on every repair row.
    Within the tolerance the rows are exactly what they always were. This is
    the single place that decides it, so the manual flow
    (``append_repair``) and the repair runner write identical rows.
    """
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
    local_gross_pnl = gross_pnl
    exchange_pnl_residual = abs(gross_pnl - exchange_profit)
    exchange_is_authority = (
        close.get("exchange_profit_reported") is not False
        and exchange_pnl_residual > max_exchange_pnl_residual
    )
    if exchange_is_authority:
        gross_pnl = exchange_profit
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
    if exchange_is_authority:
        reconciliation["pnl_source"] = "exchange_realized"
        reconciliation["local_gross_pnl"] = float(local_gross_pnl)
        reconciliation["exchange_pnl_residual"] = float(exchange_pnl_residual)
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


# --------------------------------------------------------------------------- #
# stage 0: detect candidates (pure -- writes nothing)
# --------------------------------------------------------------------------- #
def detect_repair_candidates(
    ledger_status: dict[str, Any],
    ledger_events: list[dict[str, Any]],
    *,
    norm_symbol: Callable[[Any], str] = str,
) -> list[str]:
    """Map a ``DIVERGED`` ``ledger_status.json`` verdict's ``position_diffs``
    to candidate ``trade_id``s a verified-close backfill might fix.

    Only symbols reported in ``evidence.position_diffs`` are considered -- a
    real position-quantity divergence, not merely a stale pending marker.
    ``reconcile_apply.py`` already owns the pending-marker case and
    explicitly refuses this one (see its module docstring); this is the
    detection half of the path it defers to "a later PR".

    For each such symbol, the candidate is that symbol's still-open
    ``trade_id``: a ``trade_open`` with no matching ``trade_close``. Every
    strategy in this toolkit family runs at most one open position per
    symbol, so a single candidate per symbol is unambiguous. A symbol with
    zero or more than one still-open ``trade_id`` is skipped rather than
    guessed at -- shadow mode logs what it can act on, it never picks
    between two plausible answers. Several ``trade_open`` legs under one
    ``trade_id`` (a pyramided position) count as that one trade.
    """
    if ledger_status.get("value") != "DIVERGED":
        return []
    evidence = ledger_status.get("evidence") or {}
    diff_symbols = {norm_symbol(d.get("symbol")) for d in evidence.get("position_diffs") or []}
    if not diff_symbols:
        return []

    # dict-as-ordered-set: a pyramiding strategy writes one trade_open per
    # add under the same trade_id, and that is still one open trade.
    open_by_symbol: dict[str, dict[str, None]] = {}
    closed_trade_ids: set[str] = set()
    for event in ledger_events:
        trade_id = event.get("trade_id")
        if not trade_id:
            continue
        event_type = event.get("event_type")
        if event_type == "trade_open":
            open_by_symbol.setdefault(norm_symbol(event.get("symbol")), {})[str(trade_id)] = None
        elif event_type == "trade_close":
            closed_trade_ids.add(str(trade_id))

    candidates: list[str] = []
    for symbol in sorted(diff_symbols):
        still_open = [tid for tid in open_by_symbol.get(symbol, {}) if tid not in closed_trade_ids]
        if len(still_open) == 1:
            candidates.append(still_open[0])
    return candidates


# --------------------------------------------------------------------------- #
# fleet-error-catalog/v2: can this repair be written, and if not, why not?
# --------------------------------------------------------------------------- #
#: ``assess_repair`` verdicts. ``repair``: write it (R1). ``unmappable``: the
#: evidence does not line up with the ledger's trade -- count one failed
#: attempt (R2). ``halt``: the ledger already carries part of a repair for
#: this trade, so writing anything would be a guess -- stop (R3).
REPAIR = "repair"
UNMAPPABLE = "unmappable"
HALT = "halt"

_CLOSING_SIDE = {"long": "SELL", "buy": "SELL", "short": "BUY", "sell": "BUY"}


def expected_closing_side(open_event: dict[str, Any], *, default_position_side: str = "long") -> str | None:
    """``SELL`` for a long ``trade_open``, ``BUY`` for a short one; ``None``
    when the recorded side is something else. A ``trade_open`` without a side
    at all falls back to ``default_position_side`` (the strategy's adapter
    says what it trades), never to a guess."""
    raw = open_event.get("side")
    side = str(raw if raw not in (None, "") else default_position_side).strip().lower()
    return _CLOSING_SIDE.get(side)


def assess_repair(
    evidence: dict[str, Any],
    ledger_events: list[dict[str, Any]],
    *,
    default_position_side: str = "long",
    max_exchange_pnl_residual: Decimal = DEFAULT_MAX_EXCHANGE_PNL_RESIDUAL,
) -> dict[str, Any]:
    """Decide what the repair runner does with one freshly fetched evidence
    dict, returning ``{"verdict", "reasons", "checks"}``.

    This is the single place that answers the question -- callers must not
    assemble their own version of it. It never raises: an input that cannot be
    assessed is itself a reason.

    What is *not* a reason any more (v1 treated all three as "ask a human"):
    other candidates this round (the runner repairs them one per round, in
    order), a P&L gap to the exchange (``build_repair_events`` writes the
    exchange's figure), and a short position (the closing side is derived
    from the ``trade_open``). What remains is structural -- the fills cannot
    be this trade's close -- or a ledger that is no longer clean.
    """
    unmappable: list[str] = []
    halt: list[str] = []
    checks: dict[str, Any] = {}

    trade = evidence.get("trade") or {}
    close = trade.get("close") or {}
    deals = close.get("deals") or []
    trade_id = trade.get("trade_id")
    incident_id = evidence.get("incident_id")

    # Identity first: without both ids the trace and close checks below cannot
    # run, and a check that cannot run must refuse rather than pass by silence.
    if not trade_id:
        unmappable.append("evidence carries no trade_id, so the ledger cannot be checked for this trade")
    if not incident_id:
        unmappable.append("evidence carries no incident_id, so the ledger cannot be checked for repair traces")

    opens = [
        event for event in ledger_events
        if event.get("event_type") == "trade_open" and trade_id and str(event.get("trade_id")) == str(trade_id)
    ]
    if trade_id and not opens:
        unmappable.append("the ledger has no trade_open for this trade_id")

    expected = None
    if opens:
        sides = {expected_closing_side(event, default_position_side=default_position_side) for event in opens}
        if len(sides) == 1 and None not in sides:
            expected = sides.pop()
        else:
            unmappable.append(f"the trade_open side cannot be read as long or short ({sorted(map(str, sides))})")
    closing_sides = {str(deal.get("exchange_side") or "").upper() for deal in deals}
    checks["expected_closing_side"] = expected
    checks["closing_sides"] = sorted(closing_sides)
    if expected and closing_sides != {expected}:
        unmappable.append(
            f"closing fills are {sorted(closing_sides)} but this position closes with {expected} -- "
            "these fills are not this trade's close"
        )

    epochs = [int(event.get("event_epoch_ms") or 0) for event in opens]
    open_epoch_ms = min(epochs) if epochs and all(epochs) else 0
    deal_times = [int(deal.get("time_ms") or 0) for deal in deals]
    checks["earliest_deal_ms"] = min(deal_times) if deal_times else None
    checks["trade_open_ms"] = open_epoch_ms or None
    if not deal_times or not all(deal_times):
        unmappable.append("evidence has deals without a timestamp, so the fetch window cannot be verified")
    elif opens and not open_epoch_ms:
        unmappable.append("a trade_open carries no event_epoch_ms to bound the fetch window against")
    elif open_epoch_ms and min(deal_times) < open_epoch_ms:
        unmappable.append(
            "a closing fill predates the trade_open, so the fetch window caught a fill "
            "belonging to some earlier position"
        )

    traces = incident_traces(ledger_events, incident_id=str(incident_id)) if incident_id else []
    # Also any reconciliation-carrying event for this trade under *another*
    # incident_id: a differently-labelled earlier repair is still a repair.
    trade_traces = [
        event for event in ledger_events
        if trade_id
        and str(event.get("trade_id")) == str(trade_id)
        and isinstance(event.get("reconciliation"), dict)
        and event not in traces
    ]
    checks["incident_trace_count"] = len(traces)
    checks["other_repair_trace_count"] = len(trade_traces)
    if traces:
        halt.append(
            f"{len(traces)} ledger events already carry this incident_id -- a previous repair "
            "left traces; do not write the rest of it on a guess"
        )
    if trade_traces:
        halt.append(
            f"{len(trade_traces)} ledger events for this trade carry a different repair's "
            "reconciliation record -- an earlier repair under another incident_id"
        )
    if trade_id and _existing_close(ledger_events, trade_id=str(trade_id)):
        unmappable.append("the trade already has a trade_close")

    try:
        repair_events = build_repair_events(evidence, max_exchange_pnl_residual=max_exchange_pnl_residual)
    except (VerifiedCloseError, KeyError, TypeError, ValueError) as exc:
        unmappable.append(f"the repair does not compute cleanly: {exc}")
        repair_events = []
    if repair_events:
        trade_close = next(fields for event_type, fields in repair_events if event_type == "trade_close")
        checks["reconciliation_delta"] = str(trade_close["reconciliation_delta"])
        checks["pnl_source"] = trade_close["reconciliation"].get("pnl_source", "local")

    if halt:
        return {"verdict": HALT, "reasons": halt + unmappable, "checks": checks}
    if unmappable:
        return {"verdict": UNMAPPABLE, "reasons": unmappable, "checks": checks}
    return {"verdict": REPAIR, "reasons": [], "checks": checks}


def append_repair_from_evidence(
    ledger_path: str | Path,
    evidence: dict[str, Any],
    *,
    ledger_append: Callable[..., str],
    apply: bool = False,
) -> dict[str, Any]:
    """``append_repair`` for evidence already in memory.

    The repair bot computes evidence and decides in one pass; making it write
    the dict to disk purely to read it straight back would add a failure mode
    (a half-written evidence file) to the path that is supposed to be the
    careful one. The caller still persists the evidence as the audit artefact
    -- this just stops that copy being load-bearing.
    """
    validate_evidence(evidence)
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
    return append_repair_from_evidence(
        ledger_path,
        load_evidence(evidence_path),
        ledger_append=ledger_append,
        apply=apply,
    )
