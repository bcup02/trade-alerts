# Review archive — ledger_reconcile shared reconciliation toolkit (v0.12.0)

- **PR**: bcup02/trade-alerts#4
- **Date**: 2026-09-01
- **Branch**: `feature/ledger-reconcile-toolkit` → `main`
- **Squash SHA on main**: `8eb3c3f6a1ce0033a95ba7fcbb979ffcdc939d10`
- **Base**: `c9d100bcd87a4f47c4941316aa9fd4e6dbfb40bb`
- **First-pass head reviewed**: `187fc308ad8608411fb9c83d2bdb58d361211a72`
- **Re-review head**: `aa014ef7e224a74668cf0efddaf4f8b93b1c4e0d`
- **Tag**: `v0.12.0`
- **CI**: SUCCESS (run 33491138488) — pytest 94 passed (54 pre-existing + 40 new
  in `tests/test_ledger_reconcile.py`) + `node tests/*_node_test.js` all pass
  (no `.gs` change)
- **Reviewer**: Perplexity (Debug AI) — **PASS**, then **PASS on re-review**.
- **Merge**: `gh pr merge --squash` by hand (`scripts/merge-pr.sh` refuses
  base≠`development`; trade-alerts is single-branch `main`), then
  `git tag -a v0.12.0 && git push origin v0.12.0`.

## Why

Backlog task 3 (directive 8: reconcile / sheet code is an external dependency),
**L2** — package the Python reconciliation layer. L1 (Apps Script source) is
done. The two consumers' `reconcile_shared.py` / `reconcile_compare.py` /
`google_reconcile.py` were ~90% byte-identical copies; the deltas are all
deliberate per-repo choices (documented in their comments).

User decisions: (1) L2 before task 1 (momentum→Binance); (2) scope = momentum +
my-crypto only (seykota has no local ledger, verdict permanently `UNKNOWN`, not a
`trade-alerts` consumer); (3) one `v0.12.0` release, then a per-consumer
pin-bump + adapter governance PR.

## What changed

Purely additive to `trade-alerts`. New `src/trade_alerts/ledger_reconcile.py`
(pure functions; `requests` only for `fetch_sheet_rows`):

- **IO / parse**: `read_ledger` `read_json` `atomic_write` `parse_iso`
  `utc_now_iso` `to_float` (`_f`) `to_number` (`_num`) `env_int` `env_float`
- **event classification**: `is_paper_event(…, live_close_estimate_is_real=)`
  (False ≡ momentum `reconcile_shared.is_paper_event`; True ≡ my-crypto
  `_is_paper` with the LIVE estimated-close carve-out), `recorded_order_ids`,
  `unsettled_pending_markers(…, is_paper=)`
- **layer 1** `exchange_ledger_compare(…)` → `ledger_status.json`
- **layer 2** `fold_ledger_trades(…)` (`local_trades`) + `sheet_ledger_compare(…)`
  (`compare`) → `google_reconcile_status.json`; `fetch_sheet_rows(…)`
- **constants**: `RECONCILE_SOURCE_SCHEMA` `DRY_RUN_SOURCES` `CLOSE_MARKERS`
  `SHEET_COLUMN_INDEX` `SHEET_PAPER_MODES` `SHEET_DIVERGENCE_KINDS`
  `SHEET_INFO_KINDS`

Per-repo differences → parameters: `is_paper`, `norm_symbol` (`norm_symbol_plain`
vs `norm_symbol_ccxt`), `open_event_types` (momentum `{trade_open}`; my-crypto
`+ position_recovered`), `include_pending_markers` (momentum True; my-crypto
False). `exchange_ledger_compare` aggregates exchange position rows by
normalised symbol (**sum**) — my-crypto already did this; momentum's old
"last-row-wins" is subsumed.

Also: `__init__.py` re-exports the new surface + fixes stale
`__version__ = "0.10.0"` → `"0.12.0"`; `pyproject` `0.11.0` → `0.12.0`; release
record in `docs/consumer-release-runbook.md`.

## Perplexity notes & how they were handled

First pass **PASS** with three follow-ups:

1. **`DRY_RUN_SOURCES` had a stray `"dry_run"`** (carried in from ed-seykota,
   out of scope) — silently broadened `is_paper_event`. **Fixed in re-review
   commit `aa014ef`**: now `frozenset({"dry_run_signal", "dry_run_simulated"})`,
   byte-for-byte both consumers, with a comment.
2. **`fetch_sheet_rows` had no direct tests.** **Fixed in `aa014ef`**: 7 tests
   (success / 302 follow / receiver-rejection-is-terminal (asserts 1 call) /
   retry-then-succeed / retries-exhausted / empty-body). `import requests` moved
   to module scope (already a hard dep) so tests can `monkeypatch` it.
3. **`exchange_ledger_compare` sum vs momentum's last-row-wins.** Left for the
   **momentum adapter PR** to verify against `reconcile_mexc_fetch.py`. Initial
   check (recorded in the fix commit): momentum `_position_rows()` maps
   `positionType` 1/2 → long/short with unsigned `holdVol`, and momentum is a
   single-direction strategy (one position per symbol via
   `EQUITY_FRACTION_PER_POSITION` / `max_account_exposure_fraction`), so it
   should never emit two rows for one symbol. **The momentum adapter PR must
   provide code-level evidence or a "preserve old semantics" parameter** —
   Perplexity will hold that PR to this.

Re-review of `aa014ef` vs `187fc30`: confirmed the only delta is the two
`ledger_reconcile.py` fixes + 7 new tests; all previously-reviewed function
bodies byte-identical; `import requests` at module scope has no side effect
(not re-exported); 94 passed, no regression. **PASS.**

## Isolation

Additive package change. No `/opt` `/etc` `/var/lib` systemd exchange Google
live-data contact. `apps_script/*.gs` untouched (node tests unaffected). No
secrets in the module.

## Next (task 3 L2, remaining)

- **PR 2** — `columnbb/my-crypto-bot`: `reconcile_compare.py` /
  `google_reconcile.py` → thin adapters on `trade_alerts.ledger_reconcile`; pin
  bump `v0.9.1`→`v0.12.0` (`deploy/install_systemd.sh` + `.github/workflows/ci.yml`).
- **PR 3** — `vivoy2027game/mexc-4h-momentum-trailing-stop`: `reconcile_shared.py`
  / `reconcile_compare.py` / `google_reconcile.py` → thin adapters; pin bump
  (`pyproject` + `deploy/install_systemd.sh`); **resolve the sum-vs-last-row-wins
  open item**.
