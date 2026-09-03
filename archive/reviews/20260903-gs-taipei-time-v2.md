# PR #8 — feat(gs): v2 projection writes entry_time/exit_time as Taipei local text (v0.13.3)

- Repo / PR: bcup02/trade-alerts#8
- Squash: fe1ab81
- Base: e6d9b61328cac448455f82d67f5db1cdc18dc87c (main)
- Feature head: 9dcaf738677599f0cfc9ce7fb1c303584b4ce0e4
- Tag: v0.13.3
- CI: job `pytest` SUCCESS (run 33756797574) -- pytest 113 + node
  (legacy_list_by_sheet / receiver_v2 / unified) all passed
- Perplexity: PASS (first review)

## What

R6 (timezone) step 1 of 2. The v2 projection carried entry_time / exit_time
as UTC ISO-8601 from the ledger (opened_at / closed_at), so drained rows
landed as "2026-08-29T15:57:11Z" while every pre-v2 row is Taipei local text
"2026-08-26 0:00:49". Convert on write, receiver-side.

- apps_script/google_ledger_receiver.gs (canonical, deployed) + the
  reference sibling google_ledger_receiver_v2.gs, kept in sync:
  * SHEET_TIME_KEYS / SHEET_TIME_TEXT_RE (/^\d{4}-\d{2}-\d{2} \d{1,2}:\d{2}:\d{2}$/)
    / SHEET_TIME_TZ ('Asia/Taipei') constants.
  * formatSheetTime(value): '' / already-Taipei-text / unparseable -> pass
    through (never throws); else Utilities.formatDate(d, 'Asia/Taipei',
    'yyyy-MM-dd H:mm:ss') -- hour unpadded (SimpleDateFormat 'H'), min/sec
    padded, Taipei = UTC+8 no DST.
  * sheetValue(): entry_time / exit_time take the new branch before the
    numeric check.
  * needsTextFormat(value): replaces the 4 inline /^[0-9]{16,}$/ checks
    (legacy append + update_by_trade_id + update_by_key + v2
    writeProjection); a Taipei datetime string now also stays @-text so
    Sheets does not auto-parse it into a right-aligned Date cell.
- payload_digest unaffected (conversion is post-signature, only inside
  appendOpen/updateClose -> writeProjection). google_reconcile does not
  compare time columns -> verdicts unchanged.
- tests/apps_script_unified_receiver_node_test.js: Utilities.formatDate stub
  + v2 open/close-with-UTC-ISO -> Taipei-text assertions + formatSheetTime
  passthrough/no-throw. receiver_v2 node test untouched (no write path).
- 0.13.2 -> 0.13.3; release-log entry.

## Consumer action

No pin bump (.gs is pasted manually, not imported; v0.13.3 is only the .gs
version coordinate). The operator must paste google_ledger_receiver.gs into
the Apps Script editor -> Manage deployments -> new version (same Web App URL,
all tabs, Script Properties untouched). The ~25 already-wrong rows are fixed
by a momentum-side rewrite tool (R6 step 2).

## Perplexity review (PASS)

execute_python-verified SHEET_TIME_TEXT_RE against 8 inputs (1- and 2-digit
hour match; ISO with T/Z and fractional-second variants do not); confirmed
SimpleDateFormat 'H' vs 'mm'/'ss' padding asymmetry and Taipei UTC+8 no-DST;
traced validateProjection (checks trade_id / required keys / no extra keys --
never reads time values) so a rejected projection never reaches
writeProjection; needsTextFormat is a pure OR-extension of the old 16-digit
check; both .gs files byte-identical in the added code. Read-only review; the
manual Web App re-deploy was not performed.
