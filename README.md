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

跨專案的公開契約位於 [`docs/investor-contract-v1.md`](docs/investor-contract-v1.md)，machine-readable JSON Schema 位於 [`schemas/investor-contract-v1.schema.json`](schemas/investor-contract-v1.schema.json)。第一版同時支援事件推播、唯讀投資人狀態快照、保護單描述、已平倉交易與 `7d`／`30d`／`ytd`／`1y` 績效窗口。

既有專案不必一次重構：可以繼續呼叫 `publish()`，先把 `schema_version=1.0`、`project_id` 與 `execution_mode=DRY_RUN` 放入 `fields`；新版則使用 `contract_event()` 與 `AlertDispatcher.publish_contract()`。接收端對未知選填欄位採忽略但保留原始資料的策略，對缺失損益使用 `null` 與 `data_quality.missing_fields`，不得推算或偽造數值。

LINE／Telegram 的共用唯讀查詢控制器位於 `InvestorQueryController`，詳細的 provider 與安全邊界請見 [`docs/investor-query-interface-v1.md`](docs/investor-query-interface-v1.md)。它只支援 `查看投資摘要`、`查看交易紀錄` 與 provider 固定指令；身分驗證、webhook 驗章與任何策略控制必須留在宿主專案。

## 驗證

```bash
python -m pytest -q
```

## References

[1]: https://notify-bot.line.me/ "LINE Notify — End of service"
[2]: https://developers.line.biz/en/docs/messaging-api/sending-messages/ "LINE Developers — Send messages"
[3]: https://core.telegram.org/bots/api "Telegram Bot API"
