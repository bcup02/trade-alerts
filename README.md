# trade-alerts

`trade-alerts` 是供自動化交易策略、資料監控程式與其他長時間執行系統共用的通知函式庫。它把**事件模型、渠道、重試、備援與敏感設定**集中管理，使每個策略專案不必各自重新實作 LINE 與 Telegram 整合。

目前支援 LINE Messaging API 與 Telegram Bot API。LINE Notify 已停止服務，因此本套件不提供 LINE Notify token 介面；LINE 通知使用 Official Account 的 Messaging API Push Message。[1] [2] Telegram 使用 Bot API 的 `sendMessage`。[3]

## 安裝

目前套件 repository 為私有，其他私有策略專案可以使用 Git 安裝：

```bash
pip install "trade-alerts @ git+https://github.com/bcup02/trade-alerts.git@main"
```

未來若建立內部 Python package registry，可在不改變 import API 的情況下切換安裝來源。

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

## 驗證

```bash
python -m pytest -q
```

## References

[1]: https://notify-bot.line.me/ "LINE Notify — End of service"
[2]: https://developers.line.biz/en/docs/messaging-api/sending-messages/ "LINE Developers — Send messages"
[3]: https://core.telegram.org/bots/api "Telegram Bot API"
