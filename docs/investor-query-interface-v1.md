# Trade Alerts 投資人查詢介面 v1

本介面讓 LINE 與 Telegram 共用同一個唯讀查詢控制器，根據投資人整合契約 v1 的 `portfolio_snapshot` 與 `closed_trades` 回傳文字。它不保存 channel token、不處理 webhook 簽章、不執行交易控制，也不接受任意 shell／檔案／provider 名稱。

## 指令白名單

| 指令 | 行為 |
|---|---|
| `查看投資摘要`／`投資摘要`／`查看告警狀態` | **一律**顯示 provider 專案選單。 |
| `查看交易紀錄` | **一律**顯示 provider 專案選單。 |
| `<provider.trade_command>` | 顯示該 provider 最近十筆已平倉交易。 |
| `<provider.portfolio_command>` | 顯示該 provider 的投資摘要。 |

任何其他輸入都會回傳未處理結果，必須由宿主原有的安全白名單處理；不得因此轉交 shell、交易控制或設定修改入口。

## Provider 契約

每個 provider 必須有穩定的 `project_id`、`project_name`、`portfolio_command`、`trade_command`，並實作兩個**唯讀**方法：`portfolio_snapshot()` 回傳 v1 snapshot object，`closed_trades()` 回傳 v1 closed-trade objects。即使目前僅註冊一個 provider，控制器仍先顯示選單；這使日後新增專案時不需要改變投資人的操作習慣。LINE／Telegram 宿主應先完成各自的使用者身分驗證，才呼叫控制器。

所有機器資料時間仍是 UTC ISO 8601；共用文字渲染器會統一轉為台北時間（UTC+8）`年-月-日 時:分`。`strategy_extensions` 保持選用，未知欄位不得造成查詢失敗。

## Seykota 整合

Seykota 提供 `SeykotaInvestorProvider`，只容許兩個固定管理動作：`portfolio-json` 與 `trades-json`。這兩個動作均在既有 `require_dry_run` 檢查後，透過 `seykota_bot.investor` 從同一份 v1 adapter 讀取資料。它們不載入秘密、不回傳秘密、不提交訂單，且不提供任何寫入／控制 action。

> 交易專案應把 provider 資料來源限制在本機唯讀 state 或受控 API。通知渠道與策略核心的例外不得用查詢失敗來繞過風控或改變交易決策。
