# Review archive — legacy list_by_sheet action + first CI (v0.11.0)

- **PR**: bcup02/trade-alerts#3
- **Date**: 2026-09-01
- **Branch**: `feature/legacy-list-by-sheet` → `main`
- **Squash SHA on main**: `69ae0deba1276d3d48c89727c186565408fd960c`
- **Base**: `fb62be6079dd33215b1507a898639c07d62e91e2`
- **Tag**: `v0.11.0`
- **CI**: SUCCESS (run 33477579826) — pytest 54 passed (unchanged; no Python) + `node tests/*_node_test.js` all pass (`apps_script_legacy_list_by_sheet_node_test: passed`)
- **Reviewer**: Perplexity (Debug AI) — **PASS** (no BLOCK; two non-blocking notes: PR wording slightly overstated that the new node test re-covers append dedup — that lives in the existing `apps_script_unified_receiver_node_test.js` which CI still runs; and README's "目前套件 repository 為私有" is stale — the repo is public — pre-existing, worth a later tiny PR)
- **Merge**: `gh pr merge --squash` by hand (`scripts/merge-pr.sh` refuses base≠`development`; trade-alerts is single-branch `main`)

## Why

`#2` reconcile toolkit, backlog task 3 (directive 8: reconcile / sheet code is an
external dependency) — L1: pull the shared Google Apps Script Web App source into
its canonical home. The `.gs` (bound to the 「AI自動程式交易紀錄」 sheet, one
deployment serving every project tab) had its sole authoritative copy in
`columnbb/my-crypto-bot/sheets_sync_apps_script.gs` by historical accident, and
last week gained the legacy read-only action `list_by_sheet` (my-crypto PR #17)
that every project's `google_reconcile.py` reads for ledger↔sheet reconcile.
`trade-alerts` already had `apps_script/google_ledger_receiver.gs` (unified
legacy+v2 receiver, legacy behaviour column-for-column equivalent) — just missing
`list_by_sheet`. User decision (after seeing both `.gs` in full): merge
`list_by_sheet` into `google_ledger_receiver.gs`, make it the one canonical source.

## What changed

- **`apps_script/google_ledger_receiver.gs`**: `handleLegacy()` dispatch gains
  `if (data.action === 'list_by_sheet') return handleLegacyListBySheet(...)`
  after `update_by_key`, before the append fall-through. New
  `handleLegacyListBySheet` — verbatim port of my-crypto's `handleListBySheet`,
  adapted only to `return {…}` (this file's legacy handlers return plain
  objects; `doPost` wraps). Same response shape / `trade_ids` semantics /
  `lastRow<2||lastCol<1` branch. File header expanded to carry the operational
  docs from the my-crypto copy (shared-Web-App framing, A~U schema + T/U swap,
  redeploy steps, 302-redirect caveat, full `list_by_sheet` contract).
- **`tests/apps_script_legacy_list_by_sheet_node_test.js`** (new): `vm`+stub,
  isolated mock with `getLastColumn()`. Covers `list_by_sheet` (no filter /
  non-array / non-empty / **empty array = empty set** / header-only tab / bad
  secret / `doPost` wrap) and regresses `append` / `update_by_trade_id` /
  `update_by_key`, asserting `list_by_sheet` wrote nothing.
- **`.github/workflows/ci.yml`** (new — first CI): job `pytest` = `pytest` +
  `node tests/*_node_test.js` + the sticky `<!-- pytest-summary -->` PR comment,
  same as the other five repos. `.github/pytest-summary.py` copied verbatim.
- **`pyproject.toml`**: `0.10.0` → `0.11.0` (backward-compatible additive = minor).
- **`docs/consumer-release-runbook.md`**: `v0.11.0` release record — consumers
  need **no pin bump** (the `.gs` is pasted into the Apps Script editor, not
  imported; `src/trade_alerts/**` unchanged). **`README.md`**: new "共用 Google
  Apps Script" section.

Untouched: `src/trade_alerts/**` (zero Python), `apps_script/google_ledger_receiver_v2.gs`,
the existing node/pytest suites.

## Consumers / follow-ups

- **No pin bump.** Redeploying the Web App from this canonical source is a
  separate approval-gated manual step, **not** required by v0.11.0 —
  `list_by_sheet`'s legacy behaviour == what's deployed.
- Follow-up PRs (separate): `columnbb/my-crypto-bot` replace local `.gs` with a
  pointer; `my-crypto-bot` + `vivoy2027game/mexc-4h-momentum-trailing-stop`
  repoint doc references to `apps_script/google_ledger_receiver.gs`.

## Isolation

Repo-only change. No `/opt` `/etc` `/var/lib` systemd exchange contact, no Apps
Script deploy, no touch of the shared spreadsheet's contents.
