# Perplexity 審閱歸檔 — docs: register the seykota duplicate-order incident and the gap it exposed

- **Repo**：bcup02/trade-alerts
- **PR**：#50，最終 head `e1de72db75fd164eda0caf1ceb72100445e97d5d`
- **base**：`main` @ `4317d92`
- **squash 合併為**：`c72e1ff`
- **審閱者**：Perplexity — 首審 **`BLOCK`**（head `4519af4`）→ 複審 **`PASS`**
- **CI**：pytest = success（首審 run `35900400049`、複審 run `35901321860`；342 passed，純資料變更 +0）
- **對應待辦**：機隊工程進度 `phase-h1`、`phase-h7`、`phase-g1`、`phase-g2`、`phase-e`
- **部署**：不需要；合併後重新產生並重新發布兩張登記冊頁面。

## 做了什麼

登記冊新增 4 列、5 個 phase：
- `orders.single_send`：四支全 pending。seykota → `hotfix-seykota-order-resend`（修正 ed-seykota #65）；
  momentum／mycrypto／btc-competition → `single-send-audit`（見下方 BLOCK）。
- `reconcile.unrecorded_fill_handling`：四支 pending（`unrecorded-fill`），含「clientOrderId 相同＝重複送單＝R3」判斷規則。
- `repair_bot.recurrence_escalation`：四支 pending（`repair-recurrence`）。
- `notify.error_id`：四支 pending（`error-ids`），使用者 2026-09-24 新需求。

## BLOCK 與修正

首審 BLOCK：momentum／mycrypto／btc-competition 三格原標 `done`，證據只引用下單函式本身；審閱者要求查核所有呼叫端
（送出結果不明時同一輪是否重試、下一輪是否對同一訊號再送）。開發端確認這是真實缺口——當初確實沒查呼叫端；
且 momentum 用固定 client id，而 09-21 已證明 Binance 不擋已成交市價單的重複 client id，實際安全性依賴下一輪的部位同步，
必須逐路徑驗證。採保守做法：三格改 pending＋新 phase `single-send-audit`，reason 只陳述已知線索、不下安全結論（7ffb07a），
另把 reason 裡裸檔名 `runner.py` 改成完整路徑以通過 `verify_registry_evidence.py`（e1de72d）。複審 PASS。

教訓：登記冊標 `done` 前，安全性質要查到呼叫端與跨輪行為，不能只看被呼叫的函式。

## 隔離聲明

只動 `src/trade_alerts/catalog/fleet-rollout-registry.json` 與兩個由 `scripts/render_guides.py` 產生的 HTML；錯誤目錄未動；
無程式碼、部署或秘密變更。完整差異見同名 `.patch`。
