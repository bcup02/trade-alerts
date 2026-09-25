# Perplexity 審閱歸檔 — registry: momentum g1-4 is live; seykota's unrecorded-fill row too

- **Repo**：bcup02/trade-alerts
- **PR**：#73，最終 head `98d5b602eb7e8b626595aa4726739e07e211c40b`，base `main` @ `30538d3`，squash 合併為 `82eee07`
- **審閱者**：Perplexity — 首審 **`PASS`**
- **CI**：pytest = success（run `36090221072`；381 passed，純資料無增減）
- **對應待辦**：機隊工程進度 `phase-g1`（g1-4 收尾）；一致性登記冊動能 `ledger.trade_correction`、`reconcile.unrecorded_fill_handling`、`MOM.UNRECORDED_FILL_CORRECTED`／`_UNRESOLVED`，趨勢 `reconcile.unrecorded_fill_handling`
- **部署**：不需要（資料）；合併後重新發布兩張登記冊頁。

## 做了什麼

動能 g1-4（mexc-4h-momentum-trailing-stop #104）2026-09-25 03:18 UTC 上正式機（operations `43be152`；/opt 69 個受版控檔與該 commit 逐檔 sha256 相同；03:20 UTC 第一輪修復機器人 unrecorded_fill 0 筆無錯）。
動能 4 項改已做、補改趨勢策略在 #71 漏改的 `reconcile.unrecorded_fill_handling`；`sources.momentum` → 43be152，所有動能引用用 difflib 從 61ff1e5 重算並把裸 `:行號` 寫成完整路徑；錯誤目錄動能 sources 重指到發出代碼的行；`recent_changes` 換成這次的五項；兩張登記冊頁重新產生。`verify_registry_evidence.py` 0 problems。

## 審閱

- 首審 PASS。審閱者註明：主機雜湊與部署紀錄為開發端唯讀蒐證；「已做」代表程式已部署在跑，不代表兩種未記成交分支已被真實案例觸發。

## 隔離聲明

本 PR 為資料變更；蒐證只對正式機做唯讀讀取（git、sha256、systemctl、journalctl），未改動正式機、交易所、Google 或實機帳本。完整差異見同名 `.patch`。
