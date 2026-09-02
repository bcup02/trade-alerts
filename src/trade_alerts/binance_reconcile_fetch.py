"""Shared read-only Binance USDⓈ-M futures reconcile-source fetcher.

Pure transform + IO.  This module does **not** import
``binance_trading_toolkit`` or any credential layer.  The caller resolves the
credential pair / execution mode / the symbol set, builds a
``BinanceFuturesClient`` (or any object exposing the same read-only methods),
and passes a :class:`BinanceReconcileParams`.

Consumers:
  * ``ed-seykota`` -- single symbol (``BTCUSDT``), ledger symbol == native.
  * ``mexc-4h-momentum`` -- multi symbol, ledger symbol is the underscore form
    (``GPSUSDT`` -> ``GPS_USDT``); ``user_trades`` is pulled per symbol because
    Binance's endpoint has no all-symbols variant.

Each exchange section is fetched in its own ``try``/``except``; a failure is
recorded in ``fetch_status.errors`` and the document is still returned /
written.  :func:`run` never raises.

The written document is ``reconcile-source/v1`` -- the same schema
``trade_alerts.ledger_reconcile.exchange_ledger_compare`` consumes.  It always
carries ``symbols_queried`` and ``fills_possibly_truncated`` (a harmless
superset for the single-symbol consumer; the comparator ignores unknown keys).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from .ledger_reconcile import atomic_write, to_number, utc_now_iso

log = logging.getLogger("trade_alerts.binance_reconcile_fetch")

SCHEMA_VERSION = "reconcile-source/v1"
EXCHANGE = "binance-usdm-futures"
_QUOTE = "USDT"


def _identity(symbol: str) -> str:
    return symbol


def momentum_ledger_symbol(symbol: str | None) -> str | None:
    """``GPSUSDT`` -> ``GPS_USDT``; anything already underscored, or not a
    ``*USDT`` symbol, is returned unchanged.  The momentum adapter passes this
    as ``to_ledger_symbol`` so ``reconcile_compare``'s ``norm_symbol_plain``
    lines the fetched rows up with the ledger."""
    if not symbol:
        return symbol
    if symbol.endswith(_QUOTE) and not symbol.endswith("_" + _QUOTE):
        return f"{symbol[: -len(_QUOTE)]}_{_QUOTE}"
    return symbol


@dataclass
class BinanceReconcileParams:
    """Everything the shared fetcher needs, resolved by the per-repo adapter."""

    #: Object with the toolkit ``BinanceFuturesClient`` read surface:
    #: ``sync_server_time(*, force)`` / ``account_balance()`` /
    #: ``position_information(symbol_or_None)`` /
    #: ``user_trades(symbol, *, start_time_ms, limit)`` /
    #: ``open_orders(symbol_or_None)`` / ``open_algo_orders(symbol_or_None)``.
    client: Any
    account_scope: str
    execution_mode: str
    environment: str  # "mainnet" | "testnet"
    base_url: str
    #: Binance-native symbols (``BTCUSDT`` / ``GPSUSDT``) to pull a fill window
    #: for -- ``user_trades`` has no all-symbols variant.  Either a fixed
    #: sequence (seykota: its one symbol) or a callable given the normalized
    #: position rows (ledger-form symbols) that returns the native symbols to
    #: query (momentum: the open positions' symbols unioned with a static env
    #: list, resolved only after positions are fetched).  An empty result is
    #: not an error -- it yields no fills.  A callable's own exception is *not*
    #: caught -- it propagates out of ``fetch`` / ``run`` (which otherwise never
    #: raise).  That is deliberate: the callable is the adapter's own code, so a
    #: bug there should fail loudly rather than be swallowed like a flaky
    #: exchange call; an adapter that wants fail-safe behaviour must try/except
    #: inside its own callable.
    query_symbols: Sequence[str] | Callable[[list[dict[str, Any]]], Sequence[str]] = field(default_factory=tuple)
    lookback_hours: int = 168
    #: Passed to ``position_information`` / ``open_orders`` / ``open_algo_orders``.
    #: ``None`` = every symbol (momentum); a symbol string scopes them (seykota).
    scope_symbol: str | None = None
    #: The document's top-level ``"symbol"`` field.
    doc_symbol: str | None = None
    #: Binance-native symbol -> ledger symbol.  Identity for seykota.
    to_ledger_symbol: Callable[[str | None], str | None] = _identity
    user_trades_limit: int = 1000


def _balance_block(client: Any) -> dict[str, Any]:
    for row in client.account_balance():
        if row.get("asset") == "USDT":
            return {
                "asset": "USDT",
                "wallet_balance": to_number(row.get("balance")),
                "available_balance": to_number(row.get("availableBalance")),
                "unrealized_pnl": to_number(row.get("crossUnPnl")),
                "update_time_ms": row.get("updateTime"),
            }
    return {"asset": "USDT", "wallet_balance": None, "available_balance": None,
            "unrealized_pnl": None, "update_time_ms": None}


def _position_rows(client: Any, params: BinanceReconcileParams) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for p in client.position_information(params.scope_symbol):
        amt = to_number(p.get("positionAmt")) or 0.0
        if amt == 0.0:
            continue
        rows.append({
            "symbol": params.to_ledger_symbol(p.get("symbol")),
            "side": "long" if amt > 0 else "short",
            "quantity": abs(amt),
            "entry_price": to_number(p.get("entryPrice")),
            "mark_price": to_number(p.get("markPrice")),
            "unrealized_pnl": to_number(p.get("unRealizedProfit")),
            "leverage": to_number(p.get("leverage")),
            "margin_type": p.get("marginType"),
            "position_side": p.get("positionSide"),
            "update_time_ms": p.get("updateTime"),
        })
    return rows


def _resolve_query_symbols(
    params: BinanceReconcileParams, positions: list[dict[str, Any]] | None,
) -> list[str]:
    """The native symbols to pull a fill window for.  A callable
    ``query_symbols`` is given the normalized position rows (so momentum can
    union the open positions' symbols with its static env list); a plain
    sequence is used as-is (seykota).  Not wrapped in ``_section`` -- a
    callable that raises propagates (see ``query_symbols`` on the params)."""
    qs = params.query_symbols
    resolved = qs(positions or []) if callable(qs) else qs
    return list(resolved)


def _fill_rows(
    client: Any, params: BinanceReconcileParams, since_ms: int, query_native: list[str],
) -> tuple[list[dict[str, Any]], bool]:
    """``user_trades`` for each native symbol in ``query_native`` (Binance's
    endpoint is per-symbol).  ``truncated`` is set when any symbol comes back at
    the page limit."""
    limit = params.user_trades_limit
    rows: list[dict[str, Any]] = []
    truncated = False
    for native in query_native:
        trades = client.user_trades(native, start_time_ms=since_ms, limit=limit)
        truncated = truncated or len(trades) >= limit
        for t in trades:
            rows.append({
                "trade_id": t.get("id"),
                "order_id": t.get("orderId"),
                "symbol": params.to_ledger_symbol(t.get("symbol")) or params.to_ledger_symbol(native),
                "side": (t.get("side") or "").lower() or None,
                "price": to_number(t.get("price")),
                "quantity": to_number(t.get("qty")),
                "quote_quantity": to_number(t.get("quoteQty")),
                "realized_pnl": to_number(t.get("realizedPnl")),
                "commission": to_number(t.get("commission")),
                "commission_asset": t.get("commissionAsset"),
                "is_maker": t.get("maker"),
                "position_side": t.get("positionSide"),
                "time_ms": t.get("time"),
            })
    rows.sort(key=lambda r: (r["time_ms"] or 0, r["trade_id"] or 0))
    return rows, truncated


def _order_rows(client: Any, params: BinanceReconcileParams) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for kind, getter in (("order", client.open_orders), ("algo", client.open_algo_orders)):
        for o in getter(params.scope_symbol):
            out.append({
                "kind": kind,
                "order_id": o.get("orderId") or o.get("algoId"),
                "client_id": o.get("clientOrderId") or o.get("clientAlgoId"),
                "symbol": params.to_ledger_symbol(o.get("symbol")),
                # An algo row's type is ``orderType`` (verified on demo-fapi
                # 2026-09-02); ``type`` is the plain-order field, ``algoType``
                # is only the CONDITIONAL/... family.
                "type": o.get("type") or o.get("orderType") or o.get("algoType"),
                "side": (o.get("side") or "").lower() or None,
                "price": to_number(o.get("price")),
                "stop_price": to_number(o.get("stopPrice") or o.get("triggerPrice") or o.get("activatePrice")),
                "quantity": to_number(o.get("origQty") or o.get("quantity")),
                "reduce_only": o.get("reduceOnly"),
                "close_position": o.get("closePosition"),
                "status": o.get("status") or o.get("algoStatus"),
                "update_time_ms": o.get("updateTime") or o.get("createTime") or o.get("bookTime"),
            })
    return out


def fetch(params: BinanceReconcileParams, *, now: datetime | None = None) -> dict[str, Any]:
    """Build the ``reconcile-source/v1`` document.  Each exchange section is
    isolated: a failing call is logged into ``fetch_status.errors`` and the
    rest of the document is still returned."""
    now = now or datetime.now(timezone.utc)
    lookback_hours = max(1, int(params.lookback_hours))
    since_ms = int(now.timestamp() * 1000) - lookback_hours * 3600 * 1000

    errors: list[dict[str, str]] = []

    def _section(name: str, thunk):
        try:
            return thunk()
        except Exception as exc:  # noqa: BLE001 - contained by design
            log.warning("reconcile_fetch_section_failed section=%s error=%s: %s",
                        name, type(exc).__name__, exc)
            errors.append({"section": name, "error_type": type(exc).__name__, "error": str(exc)[:300]})
            return None

    client = params.client
    if client is None:
        # The adapter's credential resolution / client build failed and it
        # passed ``client=None`` rather than raise.  Record it and emit an
        # otherwise-empty document so the comparator downgrades to UNKNOWN.
        errors.append({"section": "client", "error_type": "ClientUnavailable",
                       "error": "adapter passed client=None"})
        server_time = balance = positions = orders = None
        fills, truncated = None, False
        query_native = _resolve_query_symbols(params, None)
    else:
        server_time = _section("server_time", lambda: client.sync_server_time(force=True))
        balance = _section("balance", lambda: _balance_block(client))
        positions = _section("positions", lambda: _position_rows(client, params))
        orders = _section("open_orders", lambda: _order_rows(client, params))
        query_native = _resolve_query_symbols(params, positions)
        fill_result = _section("fills", lambda: _fill_rows(client, params, since_ms, query_native))
        fills, truncated = fill_result if fill_result is not None else (None, False)

    symbols_queried = [params.to_ledger_symbol(s) for s in query_native]

    document = {
        "schema_version": SCHEMA_VERSION,
        "exchange": EXCHANGE,
        "environment": params.environment,
        "base_url": params.base_url,
        "account_scope": params.account_scope,
        "execution_mode": params.execution_mode,
        "symbol": params.doc_symbol,
        "symbols_queried": symbols_queried,
        "fetched_at": utc_now_iso(now),
        "exchange_server_time_ms": (server_time or {}).get("serverTime") if isinstance(server_time, dict) else None,
        "lookback": {"since_ms": since_ms, "hours": lookback_hours},
        "balance": balance,
        "positions": positions if positions is not None else [],
        "fills": fills if fills is not None else [],
        "fills_possibly_truncated": truncated,
        "open_orders": orders if orders is not None else [],
        "fetch_status": {"complete": not errors, "errors": errors},
    }
    return document


def run(
    params: BinanceReconcileParams, out_path: str | Path, *, now: datetime | None = None,
) -> dict[str, Any]:
    """Fetch and atomically write ``out_path`` (0644).  Never raises: a write
    failure is logged and reflected in the returned document's
    ``fetch_status``."""
    document = fetch(params, now=now)
    try:
        atomic_write(Path(out_path), document)
        written = True
    except OSError as exc:
        log.warning("reconcile_source_write_failed error=%s", type(exc).__name__)
        document["fetch_status"]["complete"] = False
        document["fetch_status"]["errors"].append({"section": "write", "error_type": type(exc).__name__})
        written = False
    log.info(
        "reconcile_source_fetch environment=%s execution_mode=%s complete=%s fills=%d positions=%d truncated=%s written=%s",
        document["environment"], document["execution_mode"], document["fetch_status"]["complete"],
        len(document["fills"]), len(document["positions"]),
        document["fills_possibly_truncated"], written,
    )
    return document
