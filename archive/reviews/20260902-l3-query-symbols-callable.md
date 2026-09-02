# Review archive — query_symbols accepts a callable (v0.13.1)

- **PR**: bcup02/trade-alerts#6
- **Date**: 2026-09-02
- **Branch**: `feature/l3-query-symbols-callable` → `main`
- **Squash SHA on main**: `b75cf5b`
- **Base**: `2c272a021d1b0273f0697ba6b73c55fe04a64fcc`
- **Reviewed head**: `2fb01559ad48bb776038850a4aa7c69d1d55ba22`
- **Post-PASS commit**: `122e045` — docstring-only, per the reviewer's own
  non-blocking suggestion (note that a callable `query_symbols` exception is
  not caught). No logic change; not re-reviewed.
- **Tag**: `v0.13.1`
- **CI**: SUCCESS (run 33578730662 on the reviewed head; run 33580819377 on the
  docstring commit) — pytest 112 passed (110 pre-existing + 2 new) + node tests
  all pass.
- **Reviewer**: Perplexity (Debug AI) — **PASS**, with one non-blocking design
  observation (callable exceptions bypass `_section` isolation → technically
  break "run() never raises"; reviewer judged this an acceptable trust boundary
  — adapter's own code should fail loudly — and asked only for a docstring
  note, added in `122e045`).
- **Merge**: `gh pr merge --squash --delete-branch` by hand, then
  `git tag -a v0.13.1 && git push origin v0.13.1`.

## Why

Point release on v0.13.0 (PR #5).  While writing momentum's L3 adapter (PR-3)
it turned out v0.13.0's `query_symbols` (a fixed sequence) could not express
momentum's reconcile fill window: "the open positions' symbols unioned with the
static `RECONCILE_SYMBOLS` env list", where the positions are only known after
they are fetched.  seykota (single symbol, fixed sequence) is unaffected.

## What shipped

- `BinanceReconcileParams.query_symbols`:
  `Sequence[str] | Callable[[list[dict]], Sequence[str]]`.  A callable is
  invoked after the positions section with the normalized (ledger-form)
  position rows and returns the native symbols to pull `user_trades` for.
- New `_resolve_query_symbols(params, positions)` helper; `_fill_rows` takes
  the resolved list explicitly instead of reading `params.query_symbols`.
- `positions` section failure / `client=None` → the callable gets `[]` (the
  adapter's static env list still contributes).
- Docstrings (`122e045`) spell out that a callable's exception is not caught
  and propagates out of `fetch`/`run` — deliberate.
- `pyproject` + `__init__.__version__` → `0.13.1`.  +2 tests (112).
- Backward compatible: the fixed-sequence path is byte-for-byte unchanged.

## Follow-on

- PR-3 `vivoy2027game/mexc-4h-momentum-trailing-stop`: momentum adapter uses
  the callable form and pins `trade-alerts@v0.13.1`.
- PR-2 `bcup02/ed-seykota-systematic-trend-following` #15: unaffected — pins
  `v0.13.0`, uses a fixed sequence.
