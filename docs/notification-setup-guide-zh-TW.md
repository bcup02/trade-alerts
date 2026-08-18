# LINE／Telegram 通知設定與驗證指南

本指南適用於 `trade-alerts` 共用套件，以及已整合該套件的 Seykota BTCUSDT 專案。實際發送測試訊息需要使用者自己的 LINE／Telegram 憑證；目前工作環境未設定任何通知憑證，因此本次只能完成 mock 與 dry-run 驗證，不能代替你的帳號發送真實訊息。

## 一、先建立本機設定檔

在策略專案目錄建立未加入 Git 的 `.env`。可以從範例複製：

```bash
cd /home/ubuntu/ed-seykota-systematic-trend-following
cp .env.example .env
chmod 600 .env
```

確認 `.gitignore` 已排除 `.env`，並且不要把 token 貼到對話、截圖或 GitHub。共用套件使用以下設定：

```dotenv
ALERTS_ENABLED=true
ALERTS_SYSTEM=seykota-btc_usdt
ALERTS_RETRY_ATTEMPTS=3
ALERTS_RETRY_BACKOFF_SECONDS=2
ALERTS_TIMEOUT_SECONDS=10

LINE_CHANNEL_ACCESS_TOKEN=
LINE_RECIPIENT_ID=

TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

`LINE_RECIPIENT_ID` 可以是個人 user ID、群組 ID 或多人聊天室 ID。舊設定名稱 `LINE_TO` 也可被共用套件讀取；Seykota 舊版的 `NOTIFICATIONS_ENABLED` 仍可相容，但新部署應優先使用 `ALERTS_ENABLED`。

## 二、設定 LINE Messaging API

LINE Notify 已停止服務，本系統使用 LINE Official Account 的 Messaging API Push Message。[1] [2]

### 1. 建立或選擇 LINE Official Account

前往 [LINE Official Account Manager](https://manager.line.biz/)，登入你的 LINE Business ID。若尚未有 Official Account，依 LINE 官方流程建立。LINE 官方文件說明，使用 Messaging API 必須先有 LINE Official Account，再啟用 Messaging API。[1]

### 2. 啟用 Messaging API channel

在 Official Account Manager 找到帳號設定中的 Messaging API 選項並啟用。啟用時要選擇或建立 Provider；Provider 一旦綁定，日後不能任意移轉，因此建議使用專門給自動化交易通知的 Provider。完成後前往 [LINE Developers Console](https://developers.line.biz/console/)，選取對應 Provider 與 Messaging API channel。

### 3. 取得 channel access token

在 LINE Developers Console 開啟該 Messaging API channel 的 **Messaging API** 分頁，建立或發行 channel access token。將 token 填入 `.env` 的 `LINE_CHANNEL_ACCESS_TOKEN`。

LINE 官方說明 channel access token 是授權 Messaging API 呼叫的 opaque token；若懷疑外洩，應立即撤銷並重新發行。[2]

### 4. 取得 LINE recipient ID

最簡單的個人測試方式是：

1. 在 LINE Developers Console 的 channel **Basic settings** 找到 **Your user ID**，將該值填入 `LINE_RECIPIENT_ID`。
2. 確認你的 LINE 帳號已將該 Official Account 加為好友；否則 push message 通常不會送達。
3. 若使用群組，先把 Official Account 加入群組，再透過 webhook 取得群組 ID；不要使用顯示名稱或 LINE 登入帳號名稱代替 ID。

LINE 官方文件指出，user ID 不是使用者的顯示名稱或可搜尋 LINE ID；它是由 LINE Platform 發出的識別字串，通常形如 `U` 加上 32 個十六進位字元。[3]

### 5. 填入 LINE 設定

```dotenv
ALERTS_ENABLED=true
LINE_CHANNEL_ACCESS_TOKEN=填入你的 channel access token
LINE_RECIPIENT_ID=填入你的 LINE user ID
```

若只測試 LINE，Telegram 欄位可以留空。完成後執行「四、實際測試」。

## 三、設定 Telegram Bot API

### 1. 建立 bot 與取得 token

在 Telegram 搜尋官方帳號 [@BotFather](https://t.me/BotFather)，按下 Start，執行 `/newbot`，依指示設定 bot 顯示名稱與 username。完成後 BotFather 會提供 bot token，格式通常類似 `123456789:AA...`。將它填入 `TELEGRAM_BOT_TOKEN`。

不要把 bot token 放在 URL、Git commit、公開 issue 或截圖中。Telegram 官方 Bot API 所有請求都使用 `https://api.telegram.org/bot<token>/METHOD_NAME` 的 HTTPS 格式。[4]

### 2. 取得個人 chat ID

1. 開啟你剛建立的 bot 對話。
2. 按 Start，或傳送一則測試文字，例如 `hello`。
3. 在本機執行以下命令，把 `<BOT_TOKEN>` 替換成 token。請勿把含真實 token 的命令貼到公共地方。

```bash
curl -sS "https://api.telegram.org/bot<BOT_TOKEN>/getUpdates"
```

回傳 JSON 中尋找：

```json
{"message":{"chat":{"id":123456789,"type":"private"}}}
```

將 `chat.id` 的數字填入 `TELEGRAM_CHAT_ID`。如果回傳 `result: []`，先回到 bot 對話傳一則新訊息，再重新執行 `getUpdates`。如果 bot 設定過 webhook，`getUpdates` 可能不可用；這時要先移除 webhook，或使用 Telegram API 的 webhook 管理方式處理。

### 3. 取得群組 chat ID

先把 bot 加入群組，在群組中傳送一則訊息，再執行 `getUpdates`。群組 ID 通常是負數，超級群組常見 `-100...` 開頭；必須完整複製數值。若 bot 沒有收到群組訊息，檢查群組隱私模式與 bot 權限。

### 4. 填入 Telegram 設定

```dotenv
ALERTS_ENABLED=true
TELEGRAM_BOT_TOKEN=填入你的 bot token
TELEGRAM_CHAT_ID=填入你的 chat ID
```

若只測試 Telegram，LINE 欄位可以留空。完成後執行「四、實際測試」。

## 四、實際測試命令

### 直接測試共用套件

在安裝 `trade-alerts` 的 Python 環境中執行：

```bash
cd /home/ubuntu/trade-alerts
set -a
. /home/ubuntu/ed-seykota-systematic-trend-following/.env
set +a
python3 - <<'PY'
from trade_alerts import dispatcher_from_env

a = dispatcher_from_env(system="manual-notification-test")
a.test()
print("notification test dispatched")
PY
```

### 測試 Seykota 整合

```bash
cd /home/ubuntu/ed-seykota-systematic-trend-following
set -a
. ./.env
set +a
seykota-bot validate
seykota-bot notify-test
```

`validate` 應顯示 `notifications_enabled: True`、`mode: DRY_RUN` 與 `live_enabled: False`。`notify-test` 只會發送測試通知，不會抓取行情，也不會下單。

### 同時測試兩個渠道

在 `.env` 同時填入 LINE 與 Telegram 欄位後執行 `seykota-bot notify-test`。預期會在兩個渠道各收到一則標題含 `TEST` 的訊息。若只有其中一個渠道收到，先單獨測試該渠道，再檢查 token、ID 與帳號權限。

## 五、目前已完成的離線驗證

即使沒有真實憑證，套件仍可做完整 mock 測試：

```bash
cd /home/ubuntu/trade-alerts
pytest -q
```

目前結果為 **5 passed**。Seykota 專案測試結果為 **8 passed**：

```bash
cd /home/ubuntu/ed-seykota-systematic-trend-following
pytest -q
```

停用通知時的安全測試如下：

```bash
ALERTS_ENABLED=0 NOTIFICATIONS_ENABLED=0 seykota-bot validate
ALERTS_ENABLED=0 NOTIFICATIONS_ENABLED=0 seykota-bot notify-test
```

此模式不會發出外部 HTTP 請求。

## 六、常見錯誤

| 症狀 | 可能原因 | 處理方式 |
|---|---|---|
| LINE 回傳 401／403 | token 錯誤、過期或 channel 不匹配 | 重新確認 channel，必要時撤銷並重新發行 token |
| LINE 回傳 400 | recipient ID 錯誤或訊息格式不合法 | 使用 Basic settings 的 user ID，確認不是顯示名稱 |
| LINE 沒收到訊息但 API 成功 | Official Account 未加好友、帳號方案或推送權限問題 | 先加好友並確認 channel 對應的 Official Account |
| Telegram `Unauthorized` | bot token 錯誤 | 回 BotFather 重新取得或撤銷 token 後重設 |
| Telegram `chat not found` | chat ID 錯誤，或 bot 不在該群組 | 先與 bot 對話或把 bot 加入群組，再從 `getUpdates` 取得 ID |
| Telegram `result: []` | bot 尚未收到新訊息，或 webhook 已啟用 | 先傳新訊息；若仍為空，檢查 webhook 狀態 |
| 只有 `notification test dispatched` 沒收到訊息 | 渠道失敗只記錄在 log，CLI 不把渠道錯誤重新拋出 | 以 DEBUG／INFO log 檢查 `trade_alerts`，並逐一驗證 token 與 recipient ID |

## 七、安全檢查

完成測試後，執行：

```bash
grep -nE 'TOKEN|SECRET|CHAT_ID|RECIPIENT_ID' .env

git status --short
```

第一個命令只應在本機使用，確認欄位存在；不要把輸出複製給他人。第二個命令確認 `.env` 沒有出現在待提交檔案中。若 token 曾經貼到公開位置，應立即在 LINE Developers Console 或 BotFather 撤銷並重新產生。

## References

[1]: https://developers.line.biz/en/docs/messaging-api/getting-started/ "LINE Developers — Get started with the Messaging API"
[2]: https://developers.line.biz/en/docs/basics/channel-access-token/ "LINE Developers — Channel access token"
[3]: https://developers.line.biz/en/docs/messaging-api/getting-user-ids/ "LINE Developers — Get user IDs"
[4]: https://core.telegram.org/bots/api "Telegram Bot API"
