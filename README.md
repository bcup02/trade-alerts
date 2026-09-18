# trade-alerts

`trade-alerts` 是供自動化交易策略、資料監控程式與其他長時間執行系統共用的通知函式庫。它把**事件模型、渠道、重試、備援與敏感設定**集中管理，使每個策略專案不必各自重新實作 LINE 與 Telegram 整合。

目前支援 LINE Messaging API 與 Telegram Bot API。LINE Notify 已停止服務，因此本套件不提供 LINE Notify token 介面；LINE 通知使用 Official Account 的 Messaging API Push Message。[1] [2] Telegram 使用 Bot API 的 `sendMessage`。[3]

## 安裝

目前套件 repository 為私有，其他私有策略專案可以使用 Git 安裝。**部署時必須釘選已驗證的版本標籤，不可使用 `@main`**，以避免未經測試的更新或本機舊副本造成版本落差：

```bash
pip install "trade-alerts @ git+https://github.com/bcup02/trade-alerts.git@v0.8.1"
```

未來若建立內部 Python package registry，可在不改變 import API 的情況下切換安裝來源。

## 版本同步與部署

`trade-alerts` 是多個交易專案的共用相依。**發布新版本不代表更新完成**；受影響的消費專案必須同步更新釘選版本、部署並驗證實際已安裝版本。

完整的專案清單、發布順序、各專案部署入口與交接紀錄模板，請從首頁手冊開始：[`docs/consumer-release-runbook.md`](docs/consumer-release-runbook.md)。所有新的消費專案都必須先登錄於該手冊，才可宣告整合或發布完成。

## 最小使用方式

```python
from trade_alerts import dispatcher_from_env

alerts = dispatcher_from_env(system="my-strategy")
alerts.publish(
    "ENTRY",
    "建立多頭部位",
    fields={"symbol": "BTC_USDT", "contracts": 1, "price": 65000},
)
alerts.publish("SAFE_HALT", "交易所持倉與本地狀態不一致", critical=True)
```

通知錯誤會被記錄而不會改變呼叫端的交易決策；交易程式仍必須自行以 `SAFE_HALT` 或等價狀態阻止危險操作。這是刻意的責任分離：共用套件負責「盡力送達」，策略引擎負責「是否允許交易」。

## 環境變數

| 變數 | 必要性 | 說明 |
|---|---|---|
| `ALERTS_ENABLED` | 必要 | `true` 才啟用渠道；預設 `false` |
| `ALERTS_SYSTEM` | 建議 | 通知標題中的系統名稱 |
| `LINE_CHANNEL_ACCESS_TOKEN` | 使用 LINE 時必要 | LINE Messaging API channel access token |
| `LINE_RECIPIENT_ID` | 使用 LINE 時必要 | LINE user、group 或 room ID；亦相容 `LINE_TO` |
| `TELEGRAM_BOT_TOKEN` | 使用 Telegram 時必要 | Telegram bot token |
| `TELEGRAM_CHAT_ID` | 使用 Telegram 時必要 | Telegram chat ID |
| `ALERTS_RETRY_ATTEMPTS` | 選填 | 預設 3 次 |
| `ALERTS_RETRY_BACKOFF_SECONDS` | 選填 | 預設 2 秒，採指數退避 |
| `ALERTS_TIMEOUT_SECONDS` | 選填 | 預設 10 秒 |

Token 必須由部署環境的 secret 管理或本機未納入版本控制的 `.env` 注入，不能提交到任何 repository。

## 穩定公開 API

跨專案只應依賴以下名稱：`AlertEvent`、`AlertDispatcher`、`RetryPolicy`、`LineMessagingChannel`、`TelegramChannel` 與 `dispatcher_from_env`。策略事件建議使用一致名稱，例如 `ENTRY`、`ADD`、`EXIT`、`ENTRY_SKIPPED`、`SAFE_HALT`、`HEALTHY` 與 `ERROR`，並把 symbol、方向、數量、價格、止損與錯誤代碼放入 `fields`。

## 投資人整合契約 v1

跨專案的公開契約位於 [`docs/investor-contract-v1.md`](docs/investor-contract-v1.md)，machine-readable JSON Schema 位於 [`schemas/investor-contract-v1.schema.json`](schemas/investor-contract-v1.schema.json)。第一版支援標準化事件推播。

既有專案不必一次重構：可以繼續呼叫 `publish()`，先把 `schema_version=1.0`、`project_id` 與 `execution_mode=DRY_RUN` 放入 `fields`；新版則使用 `contract_event()` 與 `AlertDispatcher.publish_contract()`。接收端對未知選填欄位採忽略但保留原始資料的策略。

## 交易機隊錯誤目錄 v2

全機隊錯誤分類的權威來源位於 [`docs/fleet-error-catalog.md`](docs/fleet-error-catalog.md)，
機器可讀版本位於 [`src/trade_alerts/catalog/fleet-error-catalog-v2.json`](src/trade_alerts/catalog/fleet-error-catalog-v2.json)，
其 JSON Schema 位於
[`schemas/fleet-error-catalog-v2.schema.json`](schemas/fleet-error-catalog-v2.schema.json)。

目錄替四支策略每一條維運可見的錯誤條件記錄：現行程式的行為、依判準「這個錯誤讓人做出什麼、
跟自動處理不一樣的決定？」判定的 `MECHANICAL`／`JUDGEMENT`、風險等級 R0–R3（v2，2026-09-18：只記錄／自動不通知／自動嘗試失敗才通知／必須人工）、自動與人工處置，
以及改動落在哪一個 Phase。

**Phase 7b 起目錄隨套件發佈、會在執行期被讀取**：`trade_alerts.ops_export` 從每個條件的
`operator_message`（白話的「發生什麼事／解決方向／處理步驟」）組出送給維運者的訊息，所以
`load_error_catalog()` 不帶路徑時讀的就是套件內那一份。改動通知文字＝發新版本並讓策略重新釘選。

`trade_alerts.ops_export.build_ops_export()` + `write_ops_export()` 把一支策略的事件日誌與未結案
請求整理成 `audit/ops_export.json`（格式 `schemas/fleet-ops-export-v2.schema.json`），由 ops-notify
讀取後送到維運頻道；策略本身不推播。

`tests/test_fleet_error_catalog.py` 守住幾條不變式，其中最重要的一條是：判定為 `MECHANICAL`
的條件不得落在任何會通知人的風險等級。

## 機隊一致性登記冊

[`src/trade_alerts/catalog/fleet-rollout-registry.json`](src/trade_alerts/catalog/fleet-rollout-registry.json)
（格式 [`schemas/fleet-rollout-registry-v1.schema.json`](schemas/fleet-rollout-registry-v1.schema.json)）
記錄每一項機隊功能、錯誤目錄每一條的行為與事件日誌，在四支策略裡**實際做到了沒有**：`done` 附證據、
`pending` 附預定 phase 與理由、`n/a` 附理由。規則是「四支一起做，否則寫在這裡」——
`trade_alerts.registry_problems()` 是這條規則的可執行版本，`tests/test_rollout_registry.py` 讓 CI 擋下
漏列、缺理由、目錄與登記冊對不上的情況；策略 repo 的測試可用 `project_rows()` 檢查登記冊對自己的宣稱。

給人看的兩頁 `docs/guides/fleet-risk-register.html`（由錯誤目錄產生）與
`docs/guides/fleet-rollout-register.html`（由登記冊產生）都由 `scripts/render_guides.py` 產生，
不可手改：改完 JSON 後執行 `python scripts/render_guides.py`，CI 會比對 repo 內的頁面與重新產生的結果。

## 共用 Google Apps Script

`apps_script/google_ledger_receiver.gs` 是綁在「AI自動程式交易紀錄」試算表上的**共用 Apps Script Web App 的權威源**（一個部署服所有專案分頁，靠 payload 的 `sheet_name` 選分頁）。它同時處理 legacy 協定（`SHARED_SECRET` + `append` / `update_by_trade_id` / `update_by_key` / `list_by_sheet` 唯讀）與 `google-ledger-projection-v2`（per-source HMAC + provenance）。欄位 schema、部署步驟、`list_by_sheet` 契約與呼叫端轉址告警都在該檔檔頭。`apps_script/google_ledger_receiver_v2.gs` 是 v2-only 的參考源，非部署對象。**部署（貼進 Apps Script 編輯器 → 管理部署作業 → 新版本）是手動、需另行核准的動作，不在版本標籤的自動範圍內。**

## 驗證

```bash
python -m pytest -q
for f in tests/*_node_test.js; do node "$f"; done
```

## References

[1]: https://notify-bot.line.me/ "LINE Notify — End of service"
[2]: https://developers.line.biz/en/docs/messaging-api/sending-messages/ "LINE Developers — Send messages"
[3]: https://core.telegram.org/bots/api "Telegram Bot API"
