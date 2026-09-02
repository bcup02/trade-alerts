"""Shared read-only Binance reconcile-source fetcher core (L3).

No network -- the toolkit client is faked.  These pin the row normalization,
the ledger-symbol hook (identity vs momentum underscore form), per-section
isolation, the always-present ``symbols_queried`` / ``fills_possibly_truncated``
fields, that ``run()`` never raises, and that the document is shaped for
``exchange_ledger_compare``.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from trade_alerts import BinanceReconcileParams, momentum_ledger_symbol
from trade_alerts.binance_reconcile_fetch import fetch, run
from trade_alerts.ledger_reconcile import exchange_ledger_compare

_NOW = datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc)
_NOW_MS = int(_NOW.timestamp() * 1000)


class _FakeClient:
    def __init__(self, **overrides):
        self._o = overrides
        self.calls: list[tuple] = []

    def sync_server_time(self, *, force=False):
        self.calls.append(("sync_server_time", force))
        return {"serverTime": _NOW_MS - 3}

    def account_balance(self):
        self.calls.append(("account_balance",))
        if "balance_raises" in self._o:
            raise RuntimeError("boom balance")
        return self._o.get("balance", [
            {"asset": "BTC", "balance": "1"},
            {"asset": "USDT", "balance": "500.25", "availableBalance": "480.10",
             "crossUnPnl": "1.20", "updateTime": _NOW_MS - 10},
        ])

    def position_information(self, symbol):
        self.calls.append(("position_information", symbol))
        return self._o.get("positions", [
            {"symbol": "GPSUSDT", "positionAmt": "12", "entryPrice": "1.95",
             "markPrice": "2.0", "unRealizedProfit": "0.6", "leverage": "3",
             "marginType": "isolated", "positionSide": "BOTH", "updateTime": _NOW_MS - 20},
            {"symbol": "ZEROUSDT", "positionAmt": "0", "entryPrice": "0"},  # flat -> skipped
        ])

    def user_trades(self, symbol, *, start_time_ms=None, limit=1000):
        self.calls.append(("user_trades", symbol, start_time_ms, limit))
        return self._o.get("trades", {}).get(symbol, [
            {"id": 71, "orderId": 555, "symbol": symbol, "side": "BUY", "price": "1.95",
             "qty": "12", "quoteQty": "23.4", "realizedPnl": "0", "commission": "0.0094",
             "commissionAsset": "USDT", "maker": False, "positionSide": "BOTH", "time": _NOW_MS - 22},
        ])

    def open_orders(self, symbol):
        self.calls.append(("open_orders", symbol))
        return self._o.get("open_orders", [
            {"orderId": 900, "clientOrderId": "x", "symbol": "GPSUSDT", "type": "LIMIT",
             "side": "SELL", "price": "3.0", "origQty": "1", "reduceOnly": True,
             "status": "NEW", "updateTime": _NOW_MS - 5},
        ])

    def open_algo_orders(self, symbol):
        self.calls.append(("open_algo_orders", symbol))
        return self._o.get("open_algo_orders", [
            # exact demo-fapi shape (2026-09-02): orderType / createTime
            {"algoId": 555, "clientAlgoId": "trail", "symbol": "GPSUSDT",
             "algoType": "CONDITIONAL", "orderType": "TRAILING_STOP_MARKET", "side": "SELL",
             "triggerPrice": "1.85", "activatePrice": "1.90", "callbackRate": "5.0",
             "quantity": "12", "reduceOnly": True, "closePosition": False,
             "algoStatus": "NEW", "createTime": _NOW_MS - 21, "updateTime": _NOW_MS - 20},
        ])


def _momentum_params(client, **kw):
    kw = {
        "client": client,
        "account_scope": "mexc-4h-momentum",
        "execution_mode": "DEMO",
        "environment": "testnet",
        "base_url": "https://demo-fapi.binance.com",
        "query_symbols": ["GPSUSDT"],
        "scope_symbol": None,
        "doc_symbol": None,
        "to_ledger_symbol": momentum_ledger_symbol,
        **kw,
    }
    return BinanceReconcileParams(**kw)


def _seykota_params(client, **kw):
    kw = {
        "client": client,
        "account_scope": "seykota-btcusdt-4h",
        "execution_mode": "DEMO",
        "environment": "testnet",
        "base_url": "https://demo-fapi.binance.com",
        "query_symbols": ["BTCUSDT"],
        "scope_symbol": "BTCUSDT",
        "doc_symbol": "BTCUSDT",
        **kw,
    }
    return BinanceReconcileParams(**kw)


# --------------------------------------------------------------------------- #
# symbol helper
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("binance", "ledger"), [
    ("GPSUSDT", "GPS_USDT"), ("1000PEPEUSDT", "1000PEPE_USDT"),
    ("GPS_USDT", "GPS_USDT"), ("", ""), (None, None),
])
def test_momentum_ledger_symbol(binance, ledger):
    assert momentum_ledger_symbol(binance) == ledger


# --------------------------------------------------------------------------- #
# fetch() -- momentum (multi symbol, underscore ledger form)
# --------------------------------------------------------------------------- #
def test_fetch_momentum_normalisation():
    doc = fetch(_momentum_params(_FakeClient()), now=_NOW)

    assert doc["schema_version"] == "reconcile-source/v1"
    assert doc["exchange"] == "binance-usdm-futures"
    assert doc["environment"] == "testnet" and doc["execution_mode"] == "DEMO"
    assert doc["account_scope"] == "mexc-4h-momentum"
    assert doc["symbol"] is None
    assert doc["fetch_status"]["complete"] is True

    assert doc["balance"] == {
        "asset": "USDT", "wallet_balance": 500.25, "available_balance": 480.10,
        "unrealized_pnl": 1.20, "update_time_ms": _NOW_MS - 10,
    }
    assert [p["symbol"] for p in doc["positions"]] == ["GPS_USDT"]  # flat dropped, underscored
    assert doc["positions"][0]["side"] == "long" and doc["positions"][0]["quantity"] == 12.0
    assert doc["symbols_queried"] == ["GPS_USDT"]
    assert [f["symbol"] for f in doc["fills"]] == ["GPS_USDT"]
    assert doc["fills"][0]["order_id"] == 555 and doc["fills"][0]["side"] == "buy"
    assert {o["symbol"] for o in doc["open_orders"]} == {"GPS_USDT"}
    algo = next(o for o in doc["open_orders"] if o["kind"] == "algo")
    assert algo["type"] == "TRAILING_STOP_MARKET"   # from orderType, not algoType
    assert algo["update_time_ms"] == _NOW_MS - 20    # from updateTime/createTime
    assert doc["fills_possibly_truncated"] is False


def test_fetch_scope_symbol_passed_through():
    client = _FakeClient()
    fetch(_seykota_params(client), now=_NOW)
    assert ("position_information", "BTCUSDT") in client.calls
    assert ("open_orders", "BTCUSDT") in client.calls
    assert ("open_algo_orders", "BTCUSDT") in client.calls

    client = _FakeClient()
    fetch(_momentum_params(client), now=_NOW)
    assert ("position_information", None) in client.calls


def test_fetch_seykota_identity_symbol_and_doc_symbol():
    doc = fetch(_seykota_params(_FakeClient()), now=_NOW)
    assert doc["symbol"] == "BTCUSDT"
    assert doc["account_scope"] == "seykota-btcusdt-4h"
    assert doc["symbols_queried"] == ["BTCUSDT"]  # identity, not underscored


def test_fetch_lookback_window():
    client = _FakeClient()
    fetch(_momentum_params(client, lookback_hours=24), now=_NOW)
    call = next(c for c in client.calls if c[0] == "user_trades")
    assert call[2] == _NOW_MS - 24 * 3600 * 1000


def test_fetch_fills_truncation_flag():
    many = {"GPSUSDT": [
        {"id": i, "orderId": i, "symbol": "GPSUSDT", "side": "BUY", "qty": "1",
         "price": "1", "time": _NOW_MS - i} for i in range(1000)
    ]}
    doc = fetch(_momentum_params(_FakeClient(trades=many)), now=_NOW)
    assert doc["fills_possibly_truncated"] is True


def test_fetch_empty_query_symbols_is_not_an_error():
    doc = fetch(_momentum_params(_FakeClient(), query_symbols=[]), now=_NOW)
    assert doc["fills"] == [] and doc["symbols_queried"] == []
    assert doc["fetch_status"]["complete"] is True


# --------------------------------------------------------------------------- #
# fetch() -- isolation / degraded input
# --------------------------------------------------------------------------- #
def test_fetch_section_isolation():
    doc = fetch(_momentum_params(_FakeClient(balance_raises=True)), now=_NOW)
    assert doc["fetch_status"]["complete"] is False
    assert [e["section"] for e in doc["fetch_status"]["errors"]] == ["balance"]
    assert doc["positions"] and doc["fills"]  # the rest still populated


def test_fetch_none_client_is_a_client_section_error():
    doc = fetch(_momentum_params(None), now=_NOW)
    assert doc["fetch_status"]["complete"] is False
    assert doc["fetch_status"]["errors"][0]["section"] == "client"
    assert doc["positions"] == [] and doc["fills"] == []
    assert doc["symbols_queried"] == ["GPS_USDT"]  # still reported


def test_fetch_is_exchange_ledger_compare_compatible():
    doc = fetch(_momentum_params(_FakeClient()), now=_NOW)
    # no local ledger -> UNKNOWN, but the comparator must accept the snapshot
    verdict = exchange_ledger_compare(
        exchange_state=doc, ledger_events=[], now=_NOW,
        is_paper=lambda e: False, norm_symbol=lambda s: s,
        open_event_types={"trade_open"},
    )
    assert verdict["value"] in {"UNKNOWN", "RECONCILED", "PENDING", "DIVERGED"}
    assert "no valid reconcile-source snapshot" not in verdict["note"]


# --------------------------------------------------------------------------- #
# run()
# --------------------------------------------------------------------------- #
def test_run_writes_atomically_and_never_raises(tmp_path):
    out = tmp_path / "audit" / "exchange_state.json"
    doc = run(_momentum_params(_FakeClient()), out, now=_NOW)
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written == doc
    assert written["schema_version"] == "reconcile-source/v1"
    assert (out.stat().st_mode & 0o777) == 0o644


def test_run_reports_write_failure_without_raising(tmp_path, monkeypatch):
    from trade_alerts import binance_reconcile_fetch as mod

    def _boom(path, document):
        raise OSError("read-only fs")

    monkeypatch.setattr(mod, "atomic_write", _boom)
    doc = run(_momentum_params(_FakeClient()), tmp_path / "x.json", now=_NOW)
    assert doc["fetch_status"]["complete"] is False
    assert any(e["section"] == "write" for e in doc["fetch_status"]["errors"])
