# PR #9 — fix(gs): legacy update paths set @ format BEFORE setValue (v0.13.4)

- Repo / PR: bcup02/trade-alerts#9
- Squash: edbc84a985cf717b34dc3f8421896f2ef4f48c60
- Base: 259dd10fbdba581bc6cc7722512701f5f51d3234 (main)
- Feature head: 0479efc58e07103f7c3a308d7067330ff0681503
- Tag: v0.13.4
- CI: job `pytest` SUCCESS (run 33767631080) -- pytest 113 + node (legacy /
  receiver_v2 / unified) all passed
- Perplexity: PASS (first review)

## What

v0.13.3 gap. handleLegacyUpdateByTradeId / handleLegacyUpdateByKey called
cell.setNumberFormat('@') AFTER cell.setValue(). Writing a datetime-shaped
string into a cell that already held a Date value with a seconds-hiding date
number-format: setValue parses it to a Date serial (display drops seconds),
then setNumberFormat('@') freezes that already-reformatted display string as
text -> "2026-08-20 2:25:00" became "2026-08-20 2:25".

Reorder to @ first, then setValue, in both update loops. handleLegacyAppend
(sets @ in the forEach before range.setValues) and v2 writeProjection (already
@-then-setValue) unchanged.

- node test: the sheet stub's range object gets a module-level callLog
  recording setValue / setNumberFormat call order; the trailing shadowing
  no-op setNumberFormat on the range literal is removed; update_by_trade_id /
  update_by_key assert ['setNumberFormat','setValue'] for a datetime column
  and ['setValue'] for a plain one.
- 0.13.3 -> 0.13.4; release-log entry.

## Consumer action

No pin bump. Re-paste google_ledger_receiver.gs -> Manage deployments -> new
version. The 3 seconds-dropped rows from the first R6 --apply run are re-fixed
by momentum PR #55 (canonical_taipei accepts "YYYY-MM-DD H:MM") after this
re-deploy.

## Perplexity review (PASS)

Verified the reorder matches the root cause (@ first -> string not parsed as
Date -> seconds kept); handleLegacyAppend and writeProjection confirmed
already correct and untouched; non-datetime values still setValue-only (no @),
covered by the column-14 '-0.1' assertion; removing the trailing duplicate
no-op setNumberFormat on the stub literal is necessary (last key wins, would
have shadowed the recording version); existing final-value assertions
unchanged. Read-only review.
