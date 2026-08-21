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
