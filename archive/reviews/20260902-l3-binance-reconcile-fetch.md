# Review archive — shared Binance reconcile-source fetcher (v0.13.0)

- **PR**: bcup02/trade-alerts#5
- **Date**: 2026-09-02
- **Branch**: `feature/l3-binance-reconcile-fetch` → `main`
- **Squash SHA on main**: `0be6e20`
- **Base**: `eda51df6c3f1c00270a281d15d7934b97c7630ec`
- **Head reviewed**: `2805283fcb3974f9cd73d4f24dd80ef726762788`
- **Tag**: `v0.13.0`
- **CI**: SUCCESS (run 33577381863) — pytest 110 passed (94 pre-existing + 16
  new in `tests/test_binance_reconcile_fetch.py`) + `node tests/*_node_test.js`
  all pass (no `.gs` change)
- **Reviewer**: Perplexity (Debug AI) — **PASS** (first pass, no BLOCK).
- **Merge**: `gh pr merge --squash --delete-branch` by hand (`scripts/merge-pr.sh`
  refuses base≠`development`; trade-alerts is single-branch `main`), then
  `git tag -a v0.13.0 && git push origin v0.13.0`.

## Why

Backlog task 3 (directive 8: reconcile / sheet code is an external dependency),
**L3** — package the reconcile-source **fetchers**. L1 (Apps Script source) and
L2 (Python reconciliation layer) are done. Task 1 (momentum MEXC→Binance) shipped
2026-09-02, so momentum and seykota now both run a read-only Binance signed-GET
reconcile-source fetcher; their two `binance_fetch.py` files were near
byte-identical. This PR extracts the shared core to
`trade_alerts.binance_reconcile_fetch`.

Deferred (per CLAUDE.md / user 2026-09-01): my-crypto's MEXC fetcher (ccxt
single-symbol, single consumer, different client stack — not forced into a
shared module); the v2 projection modules (`google_ledger_v2` /
`google_projection_worker` / `google_ledger_provenance` — already thin adapters
over `trade_alerts`, not wired into the live strategy).

## What shipped

`src/trade_alerts/binance_reconcile_fetch.py` (new, pure):
- No `binance_trading_toolkit` import. The caller builds the client (toolkit
  `BinanceFuturesClient` or any object with the same read surface) and passes it
  in via `BinanceReconcileParams.client`. Credential resolution / mainnet
  detection / `EXCHANGE` dispatch stay in each repo's credential layer.
- `BinanceReconcileParams` injects per-repo differences: `query_symbols`
  (Binance-native; `user_trades` is per-symbol), `scope_symbol` (`None` = every
  symbol for momentum, the symbol string for seykota — used for
  `position_information` / `open_orders` / `open_algo_orders`), `doc_symbol`,
  `to_ledger_symbol` (identity vs `momentum_ledger_symbol` GPSUSDT→GPS_USDT),
  `lookback_hours`, `user_trades_limit`.
- `fetch()` always emits `symbols_queried` + `fills_possibly_truncated` (a
  harmless superset for the single-symbol consumer; `exchange_ledger_compare`
  reads only named keys via `.get()`).
- `_order_rows` carries the T1-6 PR #41 algo field fix (`orderType` /
  `createTime`) — seykota gains it too.
- `client=None` → one `client` section error + otherwise-empty doc (comparator
  downgrades to UNKNOWN).
- `run()` reuses `ledger_reconcile.atomic_write` (0644 atomic); never raises.

`__init__.py`: exports `BinanceReconcileParams` + `momentum_ledger_symbol`.
`fetch`/`run` deliberately NOT re-exported at top level (would shadow the
submodule attribute `trade_alerts.binance_reconcile_fetch`); consumers import
them from the submodule, matching the `from trade_alerts.ledger_reconcile import`
style.

`pyproject.toml` + `__init__.__version__` → `0.13.0`.
`tests/test_binance_reconcile_fetch.py`: 16 tests, fake client. Suite 94 → 110.
`docs/consumer-release-runbook.md`: v0.13.0 release record + consumer table rows
for seykota / momentum reconcile-fetcher dependency.

## Perplexity notes

- PASS on the first pass, no BLOCK.
- Non-blocking observation: per-section isolation is only exercised via
  `balance_raises`; `positions` / `open_orders` / `fills` each failing alone has
  no dedicated test. `_section` is one generic wrapper applied to all five
  blocks, so the `balance` case already proves the mechanism — coverage nicety,
  not a defect.
- Reviewer flagged that PR-3 (momentum: restore `reconcile_mexc_fetch.py` +
  `EXCHANGE` dispatcher) touches the T1-5 deletion decision and needs its own
  equally strict review.

## Follow-on

- PR-2 `bcup02/ed-seykota-systematic-trend-following` → `development`: shrink
  `src/seykota_bot/reconcile/binance_fetch.py` to a thin adapter; add
  `trade-alerts @ ...@v0.13.0` to `pyproject.toml` + `requirements.lock`.
- PR-3 `vivoy2027game/mexc-4h-momentum-trailing-stop` → `development`: shrink
  `src/binance_fetch.py` to a thin adapter; restore `src/reconcile_mexc_fetch.py`
  (deleted in T1-5); add `src/reconcile_fetch.py` dispatcher (picks the Binance
  or MEXC fetcher by `EXCHANGE`, closing the one-way gap T1-5 left); pin bump to
  `v0.13.0`; venue-switch runbook in `docs/operations-modes.md`.
