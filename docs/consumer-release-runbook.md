# trade-alerts 消費專案登錄與發布交接手冊

本文件是 **trade-alerts 發布的唯一交接入口**。任何介面、契約、查詢呈現或推播行為變更，都必須先更新本文件，再發布新的版本標籤。所有消費專案均應使用明確版本標籤，不得依賴 `main`。

> 版本更新的完成條件不是「套件已推送」；而是每個受影響的消費專案都已釘選、安裝、部署並驗證該版本。

## 消費專案登錄表

| 專案 | 目前整合狀態 | 版本/部署入口 | 發布後負責動作 | 最低驗證 |
|---|---|---|---|---|
| `columnbb/my-crypto-bot` | 尚待 v1 契約遷移 | 尚未建立部署相依 | 實作整合時必須在本表補上版本釘選與部署命令 | 契約測試、DRY_RUN 查詢 |
| `columnbb/MarkMinervini-cryptio-bot` | 尚待 v1 契約遷移 | 尚未建立部署相依 | 實作整合時必須在本表補上版本釘選與部署命令 | 契約測試、模擬查詢 |
| `bcup02/ed-seykota-systematic-trend-following` | 已整合投資人查詢與通知 | `master` 的 `pyproject.toml` 釘選版本；WSL `/opt/.../.admin-venv` | 更新釘選版本、測試後執行 `deploy/update_remote_admin.sh` | 已安裝版本、三項服務 `active`、LINE/Telegram 查詢 |
| `vivoy2027game/mexc-4h-momentum-trailing-stop` | 已整合通知與唯讀投資人快照 | GitHub Actions 執行環境；Seykota 管理端另同步唯讀快照 | 更新工作流程相依後，以安全方式驗證一次工作流程與快照 | 不變更下單邏輯；確認快照與查詢格式 |

## 標準發布流程

| 順序 | 維護者必做事項 | 通過條件 |
|---|---|---|
| 1 | 修改程式、Schema、文件與測試。 | 全部測試通過，且向下相容影響已記錄。 |
| 2 | 更新 `pyproject.toml` 版本，建立並推送帶註解的 Git tag，例如 `v0.8.2`。 | `main` 與 tag 均已推送。 |
| 3 | 逐一檢查本表的「已整合」專案，將相依版本從舊 tag 更新為新 tag。 | 每個受影響專案的提交均明確寫出目標版本。 |
| 4 | 依各專案部署入口部署，並執行最低驗證。 | 實際安裝版本與目標 tag 相同。 |
| 5 | 在發布紀錄中列出：套件 commit、tag、各消費專案 commit、部署時間與驗證結果。 | 交接者可不依賴口頭資訊重現狀態。 |

## Seykota 專案的特別規則

Seykota 的管理服務部署腳本會在停止 `seykota-admin.service` **之前**比較兩個版本：Seykota `pyproject.toml` 所釘選的 `trade-alerts` tag，以及目標 WSL 本機 `trade-alerts` 工作副本的 `pyproject.toml` 版本。若兩者不同，部署會明確失敗，不會以舊版覆蓋管理虛擬環境。

部署後，腳本也會從 `.admin-venv` 讀取已安裝版本；若與釘選版本不同即失敗。因此，下一位維護者只需依序更新兩個 Git 工作副本、執行部署，並確認輸出含有已驗證版本即可。

## 禁止事項

不得將任何 token、密碼、API key、帳號識別資料或 `.env` 內容寫入本文件、提交、部署輸出或發行說明。Seykota 仍必須維持 DRY_RUN；套件升級不得藉此啟用實盤、下單、轉帳或變更保護單。

## 發布紀錄模板

```text
trade-alerts：vX.Y.Z（commit <sha>）
變更摘要：<一句話說明>
受影響消費專案：<repo/branch/commit>
部署入口：<已執行的安全部署命令>
版本驗證：<實際已安裝版本>
服務/工作流程驗證：<結果>
交易安全：未啟用實盤、未下單、未修改秘密或保護單
```

## 發布紀錄

```text
trade-alerts：v0.11.0
變更摘要：apps_script/google_ledger_receiver.gs 新增 legacy 唯讀 action list_by_sheet
          （回 header + 資料列，可選 trade_ids 過濾），供各專案 google_reconcile.py
          做「本地帳本 ↔ Google 表」三方對帳；共用 Apps Script Web App 的唯讀權威源
          正式定位在本 repo 的 apps_script/（原本唯一副本在 columnbb/my-crypto-bot
          的 sheets_sync_apps_script.gs，位置屬歷史偶然）。首次加入 CI（.github/
          workflows/ci.yml：pytest + node apps_script 測試 + sticky 摘要）。
受影響消費專案：
  - columnbb/my-crypto-bot：把本地 sheets_sync_apps_script.gs 換成指向本 repo 的
    pointer；文件參照改指 apps_script/google_ledger_receiver.gs。
  - vivoy2027game/mexc-4h-momentum-trailing-stop：文件參照改指同上。
  - bcup02/ed-seykota-systematic-trend-following、columnbb/MarkMinervini-cryptio-bot：
    無 .gs 副本、無需動作。
部署入口：list_by_sheet 對現有部署的 legacy 行為為純新增、且與部署中的
          sheets_sync_apps_script.gs 逐欄等價，故 v0.11.0 本身「不需要」重新發布
          Apps Script。維護者可在方便時把 google_ledger_receiver.gs 貼進「AI自動
          程式交易紀錄」的 Apps Script 編輯器 → 管理部署作業 → 新版本（同一端點
          之後也會吃 v2），此動作需另行核准、非本次發布的完成條件。
版本驗證：消費專案的 pyproject pin 不需 bump（.gs 是手動貼上、非 import）；
          v0.11.0 只是給 .gs 一個版本座標。
服務/工作流程驗證：trade-alerts pytest + node 測試全綠；下一輪各專案
          *-reconcile-fetch timer 的 google_reconcile_status.json 仍 RECONCILED。
交易安全：未啟用實盤、未下單、未修改秘密或保護單。
```
