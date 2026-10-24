# 審閱歸檔：觀察區偵測移除 a1-crypto-equity 檢查（PR #302）

- PR：bcup02/trade-alerts #302；squash `bdb368ee4979ed4cf5a5ff76c85a8f5ee95b944a`（main）
- head `648f9bf545661a3cd1542abcc56943eb783ddb6e`；base `23e9c6b67597674fcd612636171892ac0daaaea5`
- 審閱：1 輪（ChatGPT），PASS。CI：run 40063633590（1456 passed，前次 1480，差 -24＝移除權益專用測試，含一組 15 種錯誤資料的參數化）。

## 重點
- 使用者 2026-10-24 決定 f-55（A1 加密權益低於 90 USDT 發 Telegram）不再追蹤，比照 #263 直接移除不留停用開關：`EQUITY_REMINDER_USDT`、`_finite`、`check_crypto_equity`、`CHECKS` 的 `a1-crypto-equity`，白名單拿掉只有它讀的 `audit/mycrypto/exchange_state.json`，文件整段刪除。
- 原本靠權益檢查驅動的通用機制測試（run/report/ack 往返、dry-run、鎖、存檔失敗、鎖內讀狀態、LINE→Telegram 後備）改用新的 `demo_check` fixture：只替換 `run_checks` 的預設檢查清單（`main()` 以預設清單呼叫，預設值在定義時綁定），其餘 `main()`／`notify()`／狀態與鎖都是真的在跑。

## 審閱者界線與限制
- 審閱者沒有對整個 repo 做遞迴全文搜尋，「非 archive 區零殘留」不是它的獨立結果（我本機 grep 無殘留，測試全過）。
- `run --only <id>` 不會清舊項目，只有完整 `run`（排程用）會清。

## 部署
- 2026-10-24 台北 12:56 部署到 A1-dev（只換 `/opt/observation-watch/observation_watch.py`，blob 7f17bc5→12f73fc，舊檔備份在 ~ubuntu/observation_watch.py.bak-20261024）；手動跑一輪 `observation-watch.service` 成功（exit 0），`report` 已無 f-55，state 的 items 已不含 `a1-crypto-equity`；0 個失敗單元；未碰 A1 正式機。

## 隔離聲明
審閱端只讀 GitHub 的 PR、程式、測試與 CI 日誌；未碰 /opt、/etc、/var/lib、systemd、交易所、Google 或任何實機帳本；未 checkout、未跑測試、未合併或推送。
